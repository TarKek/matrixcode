"""разбор текстовых tool-call'ов формата <call- name: key:value -call>.

Принимаем ДВА синтаксиса закрытия скобок:
  <call- ... -call>   — правильный
  [call- ... -call]   — эмулируется маленькими моделями, которые
                        путают угловые скобки с квадратными

Главное, что тут происходит:
  - extract_calls(text) → список найденных вызовов (raw + parsed)
  - parse_args(s) → dict аргументов
  - call_signature / call_fingerprint — для детекторов повторов

Парсер игнорирует вызовы внутри ``` ... ``` и `...`.
"""
from __future__ import annotations

import hashlib
import re

NAME_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*[:=]')
KEY_RE  = re.compile(r'([A-Za-z_][A-Za-z0-9_-]*)\s*([:=>])')

# оба открывающих маркера имеют длину 6 ('<call-' и '[call-').
# '<call ' (пробел вместо дефиса) — мягкая форма, которую иногда пишут
# маленькие модели. Закрытие для неё ищем такое же (-call> / -call]).
CALL_MARKERS  = ("<call-", "[call-", "<call ")

# для UI-индикатора незакрытого вызова. '<c' / '[c' не включаем — они
# слишком часто встречаются в обычном тексте (markdown-ссылки и т.п.).
_PARTIAL_TAGS = ("<call", "<cal", "<ca", "<c", "<",
                 "[call", "[cal", "[ca")

# варианты закрывающего тега в порядке приоритета.
_CLOSE_TAGS = (
    ("-call>", 6),
    ("-call]", 6),
    ("</call>", 7),
    ("</call]", 7),
)

# ключи-«сырые хвосты». Их значение может быть многострочным кодом,
# и модель часто пишет его БЕЗ кавычек после `key:`. Раньше парсер
# резал значение по первому пробелу и получал фантомные ключи
# (main, withopenout, asf), а write_file падал с
# "bad args (unknown main, ...)" и loop_guard крутил модель по кругу.
# теперь для этих ключей без кавычек берём весь остаток до конца
# вызова — ровно как для формы `key>`.
_RAW_TAIL_KEYS = frozenset({"content"})


# позиция ближайшего маркера вызова
def first_call_pos(text: str) -> int:
    positions = [text.find(m) for m in CALL_MARKERS]
    positions = [p for p in positions if p >= 0]
    return min(positions) if positions else -1


_KNOWN_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "n": "\n",
    "t": "\t",
    "r": "\r",
}


# умный парсер строки в кавычках
def _parse_quoted(s: str, i: int) -> tuple[str, int]:
    """Умный парсер строки в кавычках.

    Внутри "..." разрешает неэкранированные ", если за ними не следует
    следующий ключ (key:) или закрытие тега (-call> / -call] / </call>).
    """
    n = len(s)
    i += 1
    buf: list[str] = []
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt in _KNOWN_ESCAPES:
                buf.append(_KNOWN_ESCAPES[nxt])
                i += 2
                continue
            buf.append(c)
            i += 1
            continue
        if c == '"':
            j = i + 1
            while j < n and s[j] in " \t":
                j += 1
            if j >= n:
                return "".join(buf), i + 1
            if KEY_RE.match(s, j):
                return "".join(buf), i + 1
            after = s[i + 1:]
            if after.startswith(">"):
                after = after[1:]
            if (after.startswith("-call>")
                    or after.startswith("-call]")
                    or after.startswith("</call")
                    or not after.strip()):
                return "".join(buf), i + 1
            buf.append(c)
            i += 1
            continue
        buf.append(c)
        i += 1
    raise ValueError("unterminated string")


# снять парные кавычки с многострочного блока
def _strip_paired_quotes(rest: str) -> str:
    """Снять парные кавычки вокруг значения, если модель ими обернула
    многострочный блок: `content:"...код..."` с битым закрытием."""
    for q in ('"""', "'''", '"', "'"):
        if (len(rest) >= 2 * len(q)
                and rest.startswith(q)
                and rest.endswith(q)):
            return rest[len(q):-len(q)]
    return rest


# ключ-значение + raw-хвосты для content
def parse_args(s: str) -> dict:
    args: dict[str, str] = {}
    i, n = 0, len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        m = KEY_RE.match(s, i)
        if not m:
            raise ValueError(f"expected 'key:value' near: {s[i:i+30]!r}")
        key = m.group(1)
        sep = m.group(2)
        i = m.end()

        # key>... — берёт всё до конца (до закрывающего тега).
        if sep == ">":
            rest = s[i:]
            rest = _strip_paired_quotes(rest)
            args[key] = rest
            break

        while i < n and s[i].isspace():
            i += 1

        if i < n and s[i] == '"':
            value, i = _parse_quoted(s, i)
            if i < n and s[i] == ">":
                i += 1
            # гибрид `key:">value"`: модель смешала короткую и длинную
            # формы. Ведущий '>' не является частью значения.
            if value.startswith(">"):
                value = value[1:]
            args[key] = value
            continue

        # `content:def main():\n  ...` — многострочный код без кавычек.
        # забираем весь остаток до конца вызова. Только для ключей из
        # _RAW_TAIL_KEYS; для остальных оставляем старое «жадное слово».
        if key in _RAW_TAIL_KEYS:
            rest = s[i:]
            rest = _strip_paired_quotes(rest)
            args[key] = rest
            break

        j = i
        while j < n and not s[j].isspace():
            j += 1
        args[key] = s[i:j]
        i = j
    return args


# имя + аргументы, чиним path/filename
def parse_call_body(body: str):
    m = NAME_RE.match(body)
    if not m:
        return None
    name = m.group(1)
    try:
        args = parse_args(body[m.end():])
    except ValueError as e:
        return {"name": name, "args": {}, "error": str(e)}
    if "path" not in args:
        for _a in ("filename", "filepath", "file"):
            if _a in args:
                args["path"] = args.pop(_a)
                break
    for k, v in args.items():
        if isinstance(v, str) and ("<call-" in v or "[call-" in v):
            return {"name": name, "args": {},
                    "error": f"argument '{k}' contains a nested tool call — "
                             f"emit ONE tool call per turn, wait for "
                             f"<result>, then emit the next one"}
    return {"name": name, "args": args, "error": None}


# вызовы в ``` и ` игнорируем
def _inside_code(text: str, pos: int) -> bool:
    before = text[:pos]
    if before.count("```") % 2 == 1:
        return True
    line_start = before.rfind("\n") + 1
    line = before[line_start:].replace("```", "")
    return line.count("`") % 2 == 1


def _match_close(text: str, j: int) -> tuple[int, int] | None:
    """Если в позиции j начинается закрывающий тег — вернуть (j, len)."""
    for tag, ln in _CLOSE_TAGS:
        if text.startswith(tag, j):
            return j, ln
    return None


def _find_call_end(text: str, start: int) -> tuple[int, int]:
    """Ищет закрывающий тег с учётом кавычек.

    Возвращает (pos, len) позиции закрытия или (len(text), 0) — не нашли.
    """
    j = start
    in_quote = False
    triple = ""
    while j < len(text):
        if triple:
            if text.startswith(triple, j):
                j += 3
                triple = ""
            else:
                j += 1
            continue
        c = text[j]
        if in_quote:
            if c == "\\" and j + 1 < len(text):
                j += 2
                continue
            if c == '"':
                rest = text[j + 1:]
                stripped = rest.lstrip(" \t")
                if stripped.startswith(">"):
                    stripped = stripped[1:]
                if (stripped.startswith("-call>")
                        or stripped.startswith("-call]")
                        or stripped.startswith("</call")
                        or not stripped.strip()):
                    in_quote = False
            j += 1
            continue
        if text.startswith('"""', j) or text.startswith("'''", j):
            triple = text[j:j + 3]
            j += 3
            continue
        if c == '"':
            in_quote = True
            j += 1
            continue
        hit = _match_close(text, j)
        if hit is not None:
            return hit
        # мягкая форма </call ...> или </call ...] с атрибутами/мусором.
        if text.startswith("</call", j):
            k1 = text.find(">", j)
            k2 = text.find("]", j)
            candidates = [k for k in (k1, k2) if k != -1]
            if candidates:
                k = min(candidates)
                return j, k - j + 1
        j += 1

    # fallback для оборванных вызовов — ищем любой закрывающий маркер
    # после start. Это нужно, если в кавычках что-то не срослось.
    best: tuple[int, int] | None = None
    for tag, ln in _CLOSE_TAGS:
        k = text.find(tag, start)
        if k != -1 and (best is None or k < best[0]):
            best = (k, ln)
    if best is not None:
        return best
    k = text.find("</call-", start)
    if k != -1:
        k2_gt = text.find(">", k)
        k2_br = text.find("]", k)
        candidates = [x for x in (k2_gt, k2_br) if x != -1]
        if candidates:
            k2 = min(candidates)
            return k, k2 - k + 1
    return len(text), 0


def extract_calls(text: str) -> list[dict]:
    """Возвращает список {raw, parsed}. parsed = None или {'name', 'args', 'error'}."""
    calls = []
    i = 0
    while True:
        start = first_call_pos(text[i:])
        if start == -1:
            break
        start += i
        if _inside_code(text, start):
            i = start + 5
            continue
        end, mlen = _find_call_end(text, start + 5)
        if mlen == 0:
            # truncated call  модель оборвалась до `-call>` (max_tokens или
            # сбой генерации). не теряем вызов и его аргументы:
            # отдаём весь остаток как есть, помечаем truncated.
            raw = text[start:]
            body = text[start + 5:].lstrip("- \t\n")
            calls.append({"raw": raw, "parsed": parse_call_body(body),
                          "truncated": True})
            break
        raw = text[start:end + mlen]
        body = text[start + 5:end].lstrip("- \t\n")
        calls.append({"raw": raw, "parsed": parse_call_body(body)})
        i = end + mlen
    return calls


def call_signature(calls: list[dict]) -> tuple:
    """Точная сигнатура: name + все аргументы."""
    sig = []
    for c in calls:
        p = c["parsed"] or {}
        args = p.get("args") or {}
        sig.append(p.get("name", "?") + "|" +
                   ",".join(f"{k}={v}" for k, v in args.items()))
    return tuple(sig)


def _content_hash(*parts: str) -> str:
    h = hashlib.md5()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="replace"))
        h.update(b"\x00")
    return h.hexdigest()[:12]


def call_fingerprint(calls: list[dict]) -> tuple:
    """Смысловая сигнатура: name + ключевая часть аргументов."""
    fp = []
    for c in calls:
        p = c.get("parsed") or {}
        name = p.get("name", "?")
        args = p.get("args") or {}
        if name == "run_shell":
            key = (args.get("command") or "")[:60]
        elif name == "rename_file":
            key = (args.get("path") or "", args.get("new_path") or "")
        elif name == "write_file":
            key = (args.get("path") or "",
                   _content_hash(args.get("content") or ""))
        elif name == "edit_file":
            key = (args.get("path") or "",
                   _content_hash(args.get("old") or "",
                                 args.get("new") or ""))
        else:
            key = args.get("path") or ""
        fp.append((name, key))
    return tuple(fp)
