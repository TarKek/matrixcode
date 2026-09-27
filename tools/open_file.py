# tools/open_file.py
"""open_file — открывает файл дефолтным приложением.

Опасность: os.startfile на Windows не просто «открывает» —
для .bat/.cmd/.ps1/.exe/.lnk он ЗАПУСКАЕТ файл. Это RCE
в один вызов, если файл подложен агентом. Поэтому — whitelist
расширений. Всё, что может исполниться, — отказ.

Путь вне workspace отсекается ДО этой функции: sandbox.guard_kwargs
в executor'е видит kwarg `path` и бросает PermissionError.
"""
from __future__ import annotations

import os
from pathlib import Path

# расширения, которые безопасно открывать «как документ»: рендерятся
# вьюером и не исполняются. Никаких .bat, .cmd, .ps1, .exe, .scr, .com,
# .js, .jse, .vbs, .vbe, .wsf, .wsh, .hta, .lnk, .url, .msi, .reg —
# всё, что ShellExecute может интерпретировать как команду.
_SAFE_EXTS = frozenset({
    # текст и разметка
    ".txt", ".md", ".rst", ".log", ".ini", ".cfg", ".toml",
    ".yaml", ".yml", ".json", ".xml", ".csv", ".tsv",
    # веб (открывается в браузере как документ)
    ".html", ".htm",
    # pdf
    ".pdf",
    # картинки
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff",
    ".ico", ".svg",
})


# открыть файл дефолтным приложением
def _run(path: str) -> str:
    p = Path(path).resolve()
    if not p.exists():
        return f"error: no such file: {p}"

    ext = p.suffix.lower()
    if ext not in _SAFE_EXTS:
        return (f"error: refusing to open '{p.suffix}' files — they may "
                f"execute code. Allowed extensions: "
                f"{', '.join(sorted(_SAFE_EXTS))}")

    try:
        os.startfile(str(p))  # Windows: ShellExecute, guarded by sandbox
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"
    return f"ok: opened {p}"


def register(reg):
    reg.add(
        "open_file",
        '<call- open_file: path:"heart.png" -call>\n'
        "Opens a file with the default system application "
        "(mspaint for images, notepad for txt, etc.). "
        "Prefer this over `start ...` in run_shell — no quoting issues.\n"
        "Only document-type files are allowed: txt, md, json, yaml, csv, "
        "png, jpg, pdf, html, etc. Executable scripts (.bat, .ps1, .exe, "
        ".lnk) are refused — use run_shell with explicit user approval.\n"
        "Args: path (string, required).\n"
        "Result: <result>ok: opened PATH</result>",
        _run,
    )
