"""delete_file — удаляет файл."""
from pathlib import Path


# удалить файл
def _run(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        return f"error: no such file: {path}"
    try:
        p.unlink()
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"
    return f"ok: deleted {path}"


def register(reg):
    reg.add(
        "delete_file",
        '<call- delete_file: path:"old.py" -call>\n'
        "Deletes a file.\n"
        "Args: path (string, required).\n"
        "Result: <result>ok: deleted PATH</result>",
        _run,
    )
