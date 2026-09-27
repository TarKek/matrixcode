"""rename_file — перемещает/переименовывает. Перезаписывает target, если существует."""
from pathlib import Path


# переместить/переименовать
def _run(path: str, new_path: str) -> str:
    src = Path(path)
    dst = Path(new_path)
    if not src.is_file():
        return f"error: no such file: {path}"
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        # path.replace перезаписывает target на Windows (в отличие от Path.rename).
        src.replace(dst)
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"
    return f"ok: {path} -> {new_path}"


def register(reg):
    reg.add(
        "rename_file",
        '<call- rename_file: path:"a.py" new_path:"b.py" -call>\n'
        "Renames or moves a file. Overwrites destination if it exists.\n"
        "Args: path (string, required), new_path (string, required).\n"
        "Result: <result>ok: PATH -> NEW_PATH</result>",
        _run,
    )
