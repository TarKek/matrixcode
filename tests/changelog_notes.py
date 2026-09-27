"""журнал правок: что менялось в каждой итерации этой сессии.
Пишется из финального отчёта; здесь  machine-readable сводка.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Change:
    file: str
    iter: str
    what: str
    why: str
    proof: str = ""


CHANGES: list[Change] = [
    # --- итерация 1: run_shell.py ---
    Change("tools/run_shell.py", "1",
           "_SUSPICIOUS расширен 10 правилами: del/erase, rmdir/rd, "
           "move, ren/rename, &&/||, git state-changing, pip install, "
           "npm install, yarn install",
           "Команды меняющие ФС/состояние должны требовать approval",
           "test_classify 77/77"),
    Change("tools/run_shell.py", "1",
           "Блок 'not allowed' возвращает понятный агенту результат с "
           "reason и 'Do NOT retry'",
           "Loop-guard полагается на текст; без явного запрета модель "
           "повторяет ту же команду",
           "test_denied_flow"),

    # --- итерация 2: ui/app.py ---
    Change("ui/app.py", "2",
           "_on_key: Esc/Ctrl+C отклоняют активный approval",
           "UX: не ждать 10 минут при отказе",
           "AST OK, app imports OK"),
    Change("ui/app.py", "2",
           "_ask_confirm: русские вопросы + парсер д/н/да/нет/y/n",
           "Локализация + понятный формат ответа",
           "REASK-флаг True"),

    # --- итерация 3: упрощение pipe ---
    Change("tools/run_shell.py", "3",
           "Убрано общее правило '|'; заменено на 'pipe to shell' "
           "(bash|sh|zsh|pwsh|powershell|cmd|iex|Invoke-Expression)",
           "echo a | findstr foo  не угроза, ложный approval",
           "test_classify: 3 pipe-кейса ALLOW"),
    Change("tools/run_shell.py", "3",
           "system cmdlet правило переставлено ДО LOLBin",
           "taskkill ловился как shell open/exec; reason вводил в заблуждение",
           "test_classify: taskkill -> 'system cmdlet'"),
    Change("tools/run_shell.py", "3",
           "findstr убран из gray cmdlet",
           "findstr  read-only grep, не угроза",
           "test_classify: findstr ALLOW"),

    # --- итерация 4: ApprovalDenied ---
    Change("core/sandbox.py", "4",
           "Новый класс ApprovalDenied(PermissionError); "
           "_guard поднимает его вместо PermissionError",
           "Различить явный отказ пользователя и путь-вне-workspace; "
           "дать агенту actionable текст",
           "test_sandbox: 15/15"),
    Change("execution/executor.py", "4",
           "Отдельный except для ApprovalDenied -> 'user denied... ' + "
           "'Do NOT retry'",
           "Унификация с run_shell-отказом",
           "test_denied_flow: ALL OK"),

    # --- итерация 5: TTL + resolve + audit ---
    Change("ui/app.py", "5",
           "_approved_paths из set[str] -> dict[str, float] "
           "(path -> monotonic expiry)",
           "Разовая выдача не должна превращаться в вечный пропуск",
           "test_approval_cache: TTL expiry"),
    Change("ui/app.py", "5",
           "_approval_key: Path.resolve() снимает .. и нормализует диск",
           "C:\\a\\..\\Windows и C:\\Windows должны быть одним ключом",
           "test_approval_cache: resolve identical"),
    Change("ui/app.py", "5",
           "_approval_lock (threading.Lock) вокруг кэша",
           "Hook вызывается из рабочего потока subprocess, "
           "а _ask_confirm  из event loop",
           "test_approval_cache: 200 потоков"),
    Change("ui/app.py", "5",
           "Логирование approval_granted/denied/cached/timeout/error",
           "Аудит + статистика сколько раз что спрашивали",
           "_log_command events"),

    # --- итерация 6: таймаут + App.Ctrl+C ---
    Change("ui/app.py", "6",
           "_ask_confirm: asyncio.wait_for(fut, timeout=600) + "
           "сообщение ' таймаут подтверждения  отказ'",
           "Понятный итог вместо тихого виса",
           "compile OK"),
    Change("ui/app.py", "6",
           "Binding ctrl+c -> action_cancel_confirm (show=False)",
           "Ctrl+C на уровне App должен отменять approval, "
           "а не выходить из приложения",
           "AST OK"),

    # --- итерация 7: cmd-обфускация ---
    Change("tools/run_shell.py", "7",
           "_normalize: убирает ^ и кавычки вокруг одиночной буквы",
           "d^el, d\"el  обход посимвольных правил",
           "test_classify OBFUSCATED: 4/4"),

    # --- финал: тесты ---
    Change("tests/", "8",
           "4 файла: test_classify (77), test_sandbox (15), "
           "test_denied_flow (1), test_approval_cache (9)",
           "Защита от регрессий: любая будущая правка regex / "
           "sandbox / executor ловится до коммита",
           "tests/run_all.py -> ALL 4 FILES OK"),
    Change("core/paths.py", "8",
           "APPROVAL_TTL_SEC = 600 (единый источник правды)",
           "Убрать magic number из app.py и sandbox.py",
           "paths.APPROVAL_TTL_SEC == sandbox.APPROVAL_TTL_SEC == 600"),
]


def summary() -> str:
    by_file: dict[str, int] = {}
    for c in CHANGES:
        by_file[c.file] = by_file.get(c.file, 0) + 1
    lines = [f"total changes: {len(CHANGES)}"]
    for f, n in sorted(by_file.items()):
        lines.append(f"  {f}: {n}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
    for c in CHANGES:
        print(f"\n[{c.file}] iter={c.iter}")
        print(f"  what: {c.what}")
        print(f"  why : {c.why}")
        if c.proof:
            print(f"  proof: {c.proof}")
