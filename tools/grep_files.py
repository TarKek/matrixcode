"""grep_files — regex-поиск по содержимому файлов."""
import re
from pathlib import Path


# regex-поиск по содержимому
def _run(pattern: str, path: str = ".", max_results: int = 50,
         ignore_case: bool = False) -> str:
    root = Path(path)
    if not root.is_dir():
        return f"error: not a directory: {path}"
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        return f"error: bad regex: {e}"

    hits: list[str] = []
    try:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            try:
                if p.stat().st_size > 2_000_000:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for ln, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    rel = str(p.relative_to(root)).replace("\\", "/")
                    hits.append(f"{rel}:{ln}: {line.rstrip()}")
                    if len(hits) >= max_results:
                        break
            if len(hits) >= max_results:
                break
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"

    if not hits:
        return f"(no matches for {pattern!r} under {path})"
    return "\n".join(hits)


def register(reg):
    reg.add(
        "grep_files",
        '<call- grep_files: pattern:"def foo" path:"." -call>\n'
        "Regex search across text files. Skips files >2MB and binaries.\n"
        "Args: pattern (string, required, Python regex), path (default \".\"), "
        "max_results (int, default 50), ignore_case (bool, default false).\n"
        "Result: lines formatted as `path:line_no: text`.",
        _run,
    )
