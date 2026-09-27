"""list_dir — показывает содержимое папки."""
from pathlib import Path


# содержимое папки с размерами
def _run(path: str = ".") -> str:
    p = Path(path)
    if not p.is_dir():
        return f"error: not a directory: {path}"
    try:
        entries = sorted(p.iterdir(),
                         key=lambda x: (not x.is_dir(), x.name.lower()))
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"
    if not entries:
        return f"(empty) {path}"
    lines = []
    for e in entries[:200]:
        if e.is_dir():
            lines.append(f"  [dir]  {e.name}/")
        else:
            try:
                size = e.stat().st_size
            except Exception:
                size = 0
            lines.append(f"  {size:>8}  {e.name}")
    if len(entries) > 200:
        lines.append(f"  ... and {len(entries) - 200} more")
    return "\n".join(lines)


def register(reg):
    reg.add(
        "list_dir",
        '<call- list_dir: path:"." -call>\n'
        "Lists files and subdirectories in a folder.\n"
        "Args: path (string, default \".\").\n"
        "Result: <result>listing</result>",
        _run,
    )
