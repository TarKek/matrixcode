"""find_files — glob-поиск файлов в workspace."""
import fnmatch
from pathlib import Path


# glob-поиск в workspace
def _run(pattern: str, path: str = ".", max_results: int = 100) -> str:
    root = Path(path)
    if not root.is_dir():
        return f"error: not a directory: {path}"
    results: list[str] = []
    try:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(root)
            rel_s = str(rel).replace("\\", "/")
            if fnmatch.fnmatch(rel_s, pattern) or fnmatch.fnmatch(p.name, pattern):
                results.append(rel_s)
                if len(results) >= max_results:
                    break
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"
    if not results:
        return f"(no files matching {pattern!r} under {path})"
    return "\n".join(results)


def register(reg):
    reg.add(
        "find_files",
        '<call- find_files: pattern:"*.py" path:"." -call>\n'
        "Glob-search for files by name. Pattern matches against basename "
        "AND relative path (both use forward slashes).\n"
        "Args: pattern (string, required), path (default \".\"), "
        "max_results (int, default 100).\n"
        "Result: one relative path per line, or a no-matches note.",
        _run,
    )
