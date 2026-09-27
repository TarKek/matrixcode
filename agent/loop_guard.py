"""сообщения-коррекции, когда детектор циклов срабатывает.

Вместо того чтобы оборвать ход, мы подсовываем модели явное сообщение
с инструкцией «STOP, поменяй подход». Модель обычно следует ему
с первой попытки — если ей сказать, что именно поменять.
"""
from __future__ import annotations


# модель залипла на одном вызове
def loop_correction(calls: list[dict], fp: tuple, count: int) -> str:
    """Один и тот же fingerprint (name + ключевые args) повторился count раз."""
    name = fp[0][0] if fp else "?"
    key_repr = repr(fp[0][1]) if fp else ""

    lines = [
        f"<result>LOOP DETECTED: `{name}` was called with the same "
        f"arguments {count} times in a row.",
        f"Arguments: {key_repr}",
        "",
        "You are STUCK. Repeating will not help. Change approach:",
        "  1. Do NOT call the same tool with the same arguments again.",
        "  2. Use read_file or list_dir to inspect the CURRENT state "
        "of the file/dir.",
        "  3. If a step keeps failing, switch tool: e.g. write_file "
        "with the FULL new content instead of edit_file.",
        "  4. If the step cannot succeed, SKIP it and continue to the "
        "next step from the original plan.",
        "  5. Emit ONE new tool call now, with DIFFERENT arguments.",
    ]

    if name == "write_file":
        lines += [
            "",
            "Reminder: `write_file` content MUST use the `content>` form.",
            "The text between `content>` and `</call>` is the file body —",
            "raw, newlines and indentation preserved, no quotes, no",
            "escaping. The body starts immediately after `content>`.",
            "",
            "Correct:",
            '  <call- write_file: path:"a.py" content>def main():',
            '      print("hi")',
            '',
            '  if __name__ == "__main__":',
            '      main()</call>',
            "",
            "WRONG — do not do this:",
            '  <call- write_file: path:"a.py" content:def main(): print("hi")</call>',
            "",
            "The parser slices `content:` at the first whitespace and",
            "invents phantom args (`main`, `withopenout`, `asf`), then",
            "write_file fails with `bad args (unknown ...)`. If you are",
            "seeing that error, switch to `content>` NOW.",
        ]
    elif name == "edit_file":
        lines += [
            "",
            "Reminder: `edit_file` `old` and `new` MUST be double-quoted:",
            '  <call- edit_file: path:"a.py" old:"foo" new:"bar" -call>',
            "Multi-line values: escape newlines as \\n inside the quotes.",
            "Do NOT use the `key>` form for edit_file.",
            "If `old` appears more than once, add 2-3 lines of context,",
            "or fall back to write_file with the full new content.",
        ]

    lines.append("</result>")
    return "\n".join(lines)


# тот же call+result повторяется
def repeat_correction(sig: tuple, count: int) -> str:
    """call+result совпадают точь-в-точь count раз."""
    call_desc = sig[0] if sig else "(unknown)"
    return "\n".join([
        f"<result>LOOP DETECTED: identical call+result repeated "
        f"{count} times.",
        f"Call: {call_desc}",
        "",
        "STOP. The tool is returning the same result — retrying is "
        "pointless. Change approach:",
        "  1. read_file / list_dir to inspect the current state.",
        "  2. Different tool for the same goal "
        "(edit_file → write_file, etc.).",
        "  3. If the step cannot succeed, SKIP it and move on.",
        "  4. Emit ONE new tool call now.",
        "</result>",
    ])


# модель сочинила result без вызова
def fabricated_correction() -> str:
    """Модель написала <result>...</result> в своём ответе (не как tool call)."""
    return (
        "<result>note: your message contained a literal <result> tag. "
        "Real tool results come only from the host — you cannot write "
        "them yourself. If you were trying to give the FINAL answer, "
        "just write plain text without any tags. If you wanted to run "
        "a tool, emit ONE real call: <call- name: key:value -call>. "
        "Do NOT repeat the whole plan from the start.</result>"
    )


# битый синтаксис вызова
def malformed_correction() -> str:
    """Есть <call-, но парсер не смог закрыть тег."""
    return (
        "<result>error: malformed tool call — could not parse "
        "(missing/bad closing tag). Correct format: "
        "<call- name: key:value -call>. "
        "For large multi-line values use the `key>` form: "
        "<call- write_file: path:\"a.py\" content>…raw text…</call>"
        "</result>"
    )
