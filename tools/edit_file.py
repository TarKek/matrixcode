"""edit_file — заменяет один уникальный фрагмент, с самопроверкой."""
import difflib
import re as _re
from pathlib import Path

from core import verify


# заменить уникальный фрагмент, с post-check
def _run(path: str, old: str, new: str) -> str:
    p = Path(path)
    if not p.is_file():
        return f"error: no such file: {path}"
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"

    if not old:
        return "error: 'old' must not be empty"
    if old == new:
        return "error: 'old' and 'new' are identical — nothing to do"

    count = text.count(old)
    if count == 0:
        head = text[:300].replace("\n", "⏎")
        hint = _miss_hint(text, old)
        return (f"error: 'old' string not found in {path}. "
                f"{hint}"
                f"File begins with: {head!r}. ")
    if count > 1:
        return (f"error: 'old' string appears {count} times in {path}. "
                f"Add 2-3 lines of surrounding context to make it unique, "
                f"or use write_file with the full new content.")

    new_text = text.replace(old, new, 1)

    # preflight: python-синтаксис ДО записи. Если правишь .py и
    # сломал синтаксис  файл на диске остаётся целым, а модель
    # получает понятную ошибку с указателем на строку.
    syn = verify.check_source(path, new_text)
    if syn is not None:
        return (f"error: refusing to apply edit to {path}  {syn}. "
                f"File on disk is UNCHANGED. Fix the syntax and retry.")

    try:
        p.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"

    # read-back: убеждаемся, что запись прошла. НЕ проверяем `if old in
    # readback` — это ошибочно, когда `new` содержит `old` как подстроку
    # (например, добавление комментария над строкой `import sys`).
    try:
        readback = p.read_text(encoding="utf-8")
    except Exception as e:
        return (f"error: wrote {path} but can't read it back: "
                f"{type(e).__name__}: {e}")
    if readback != new_text:
        return f"error: {path} read-back differs after edit"

    dl = new.count("\n") - old.count("\n")
    return verify.append_to_ok(
        f"ok: replaced {len(old)} chars with {len(new)} chars "
        f"in {path} (line delta: {dl:+d}, verified)", path)


# подсказка модели, почему old не найден
def _miss_hint(text: str, old: str) -> str:
    """Попробовать объяснить, почему `old` не найден.

    Порядок проверок — от самых дешёвых и наиболее вероятных к самым
    дорогим. Каждая подсказка включает фрагмент, который реально есть
    в файле, — это даёт модели возможность самому исправиться с одной
    попытки, а не перебирать варианты.
    """
    # 1. Случай из реальной жизни: модель шлёт строку в ОДИНАРНЫХ
    # кавычках, а в файле она в ДВОЙНЫХ (или наоборот). Например:
    #   old: print('hello')   — а в файле print("hello")
    if '"' not in old and "'" in old:
        swapped = old.replace("'", '"')
        if swapped in text:
            return (f"hint: exact match not found, but THIS is in the "
                    f"file: {swapped!r} — your `old` used SINGLE quotes, "
                    f"the file uses DOUBLE quotes. Copy from read_file. ")
    if "'" not in old and '"' in old:
        swapped = old.replace('"', "'")
        if swapped in text:
            return (f"hint: exact match not found, but THIS is in the "
                    f"file: {swapped!r} — your `old` used DOUBLE quotes, "
                    f"the file uses SINGLE quotes. Copy from read_file. ")

    # 2. Модель включила ведущий '>' или ':' (гибрид `key:">value"`).
    stripped = old.lstrip(">:").strip()
    if stripped and stripped != old and stripped in text:
        return (f"hint: did you mean {stripped!r}? Your value had an "
                f"extra leading '>' or ':'. ")

    # 3. Отличаются только ведущие/висячие пробелы.
    trimmed = old.strip()
    if trimmed != old and trimmed in text:
        return ("hint: leading/trailing whitespace differs. "
                "Try the stripped version.")

    # 4. Одна строка — ищем ближайшую строку в файле через difflib.
    # ловит опечатки, перепутанные скобки, пропущенные символы.
    if "\n" not in old and len(old) >= 8:
        lines = text.splitlines()
        matches = difflib.get_close_matches(old, lines, n=1, cutoff=0.75)
        if matches:
            line_no = lines.index(matches[0]) + 1
            return (f"hint: closest line in the file (line {line_no}) is "
                    f"{matches[0]!r}. Copy it exactly with read_file. ")

    # 5. Whitespace-normalized line match.
    norm = _re.sub(r"\s+", " ", old).strip()
    if norm:
        for line_no, line in enumerate(text.splitlines(), 1):
            if _re.sub(r"\s+", " ", line).strip() == norm:
                return (f"hint: exact match not found, but line {line_no} "
                        f"matches after whitespace-normalization: "
                        f"{line!r}. ")

    return "hint: use read_file to copy the exact current content. "


def register(reg):
    reg.add(
        "edit_file",
        '<call- edit_file: path:"main.py" old:"def foo():" new:"def bar():" -call>\n'
        "Replaces ONE occurrence of `old` with `new` in a UTF-8 text file.\n"
        "`old` must be UNIQUE in the file — if not, include 2-3 lines of\n"
        "surrounding context.\n"
        "\n"
        "IMPORTANT: `old` must match the file EXACTLY. Do NOT prefix it\n"
        "with '>' and do NOT wrap in extra quotes inside the value. If\n"
        "unsure, call read_file first and copy the exact line.\n"
        "\n"
        "Prefer edit_file over write_file when you change only a small\n"
        "part of an existing file. If `old` appears >1 time, either add\n"
        "context or fall back to write_file with the full new content.\n"
        "\n"
        "For multi-line strings, escape newlines as \\n inside the\n"
        "double-quoted value:\n"
        '  old:"def foo():\\n    pass" new:"def bar():\\n    return 1"\n'
        "\n"
        "Do NOT use the `key>` form for edit_file — use `key:\"...\"`.\n"
        "Args: path (string, required), old (string, required), "
        "new (string, required).\n"
        "For .py files the resulting source is syntax-checked in "
        "memory BEFORE the write; on error the old file is intact.\n"
        "Result: <result>ok: replaced N chars with M chars in PATH "
        "(verified)</result>",
        _run,
    )
