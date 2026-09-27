"""read_file — читает текстовый файл."""
from pathlib import Path


# прочитать файл с лимитом строк
def _run(path: str, max_lines: int = 500) -> str:
    p = Path(path)
    if not p.is_file():
        return f"error: no such file: {path}"
    try:
        # читаем построчно, чтобы не тянуть гигабайты в память.
        with p.open("r", encoding="utf-8", errors="replace") as f:
            lines: list[str] = []
            truncated = False
            for i, line in enumerate(f):
                if i >= max_lines:
                    truncated = True
                    break
                lines.append(line)
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"

    text = "".join(lines)
    if truncated:
        text += f"\n[... truncated after {max_lines} lines]"
    return text


def register(reg):
    reg.add(
        "read_file",
        '<call- read_file: path:"main.py" max_lines:500 -call>\n'
        "Reads a UTF-8 text file. Truncates after max_lines lines.\n"
        "Args: path (string, required), max_lines (int, default 500).\n"
        "Result: <result>file contents</result>",
        _run,
    )
