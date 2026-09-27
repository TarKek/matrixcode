"""write_file  пишет текстовый файл (перезаписывает). С самопроверкой."""
from pathlib import Path

from core import verify

_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".pdf", ".zip", ".gz", ".7z", ".rar", ".exe", ".dll",
    ".so", ".bin", ".gguf", ".pyc", ".pyd", ".ttf", ".woff",
    ".woff2", ".mp3", ".mp4", ".wav", ".avi", ".mov",
}


# записать файл целиком + post-check
def _run(path: str, content: str) -> str:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in _BINARY_EXTS and "\x00" not in content:
        return (f"error: refusing to write text into '{path}' "
                f"({suffix} is a binary format). write_file only "
                f"writes text. To create an image/chart, write a "
                f".py script and run it with run_shell. If you "
                f"meant a source file, use a .py path.")

    # preflight: python-синтаксис до записи. Иначе сломанный файл
    # ложится на диск, ломает импорты, и откат  на совести модели.
    syn = verify.check_source(path, content)
    if syn is not None:
        return (f"error: refusing to write {path}  {syn}. "
                f"File on disk is UNCHANGED. Fix the syntax and retry.")

    try:
        if p.parent and str(p.parent) not in ("", "."):
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"

    try:
        readback = p.read_text(encoding="utf-8")
    except Exception as e:
        return (f"error: wrote {path} but can't read it back: "
                f"{type(e).__name__}: {e}")

    if readback != content:
        return (f"error: wrote {path} but read-back differs "
                f"(wrote {len(content)} chars, read {len(readback)}). "
                f"Path may be wrong or disk full.")

    return verify.append_to_ok(
        f"ok: wrote {len(content)} chars to {path} (verified)", path)


def register(reg):
    reg.add(
        "write_file",
        '<call- write_file: path:"out.txt" content>hello\nworld</call>\n'
        "Writes text to a file, overwriting if exists. Creates parent dirs.\n"
        "Verifies content after writing  'ok' means the file is really there.\n"
        "For .py files the source is syntax-checked in memory BEFORE the\n"
        "write; a syntax error leaves the old file untouched.\n"
        "Args: path (string, required), content (string, required).\n"
        "\n"
        "ALWAYS use the `content>` form. NEVER `content:\"...\"`. NEVER\n"
        "`content:` unquoted. The raw text between `content>` and `</call>`\n"
        "is written to disk VERBATIM  newlines and indentation preserved\n"
        "exactly as you emit them. No quotes, no escaping.\n"
        "\n"
        "The body starts IMMEDIATELY after `content>`. Do NOT indent the\n"
        "whole body for cosmetic alignment  those spaces go into the file.\n"
        "\n"
        "Result: <result>ok: wrote N chars to PATH (verified)</result>",
        _run,
    )
