# post-check files after write_file/edit_file.
"""проверка файлов после write_file / edit_file: py_compile, размер, базовые инварианты.

модуль вызывается из tools.write_file и tools.edit_file, чтобы не отдавать
модели успешно записано, если файл не компилируется. границы:
  - только .py (остальные расширения пропускаются молча);
  - таймаут py_compile  TIMEOUT_SECONDS, без падения всего агента."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TIMEOUT_SECONDS = 5.0


# проверяем только .py
def is_python(path):
    return Path(path).suffix.lower() == ".py"


# py_compile в подпроцессе с таймаутом
def syntax_check(path):
    if not is_python(path):
        return ""
    p = Path(path)
    if not p.is_file():
        return ""
    try:
        proc = subprocess.run([sys.executable, "-m", "py_compile", str(p)],
                              capture_output=True, text=True,
                              timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return "syntax: FAILED\ncheck timed out (5s)"
    except Exception as e:
        return ("syntax: FAILED\ncould not run check: "
                + type(e).__name__ + ": " + str(e))
    if proc.returncode == 0:
        return "syntax: OK"
    err = (proc.stderr or proc.stdout or "").strip()
    if not err:
        err = "py_compile exited with code " + str(proc.returncode)
    return "syntax: FAILED\n" + err


# дописывает результат проверки к сообщению
def append_to_ok(ok_message, path):
    check = syntax_check(path)
    if not check:
        return ok_message
    if check == "syntax: OK":
        return ok_message + "\nsyntax: OK"
    detail = check.split("\n", 1)[1] if "\n" in check else check
    return "error: wrote " + path + " but syntax check failed:\n" + detail


def check_source(path, source: str):
    """Проверяет source на синтаксис, НЕ трогая диск.

    Возвращает None, если файл ок, иначе  текст ошибки.
    Для не-python файлов всегда None.

    Зачем: py_compile после записи бесполезен  файл уже испорчен.
    Компиляция в памяти позволяет отклонить правку ДО записи,
    оставив старое содержимое файла целым.
    """
    if not is_python(path):
        return None
    try:
        compile(source, str(path), "exec")
    except SyntaxError as e:
        loc = ("line " + str(e.lineno)) if e.lineno else "unknown line"
        msg = e.msg or "syntax error"
        detail = ""
        if e.text is not None and e.offset:
            caret = " " * max(e.offset - 1, 0)
            detail = "\n  " + e.text.rstrip() + "\n  " + caret + "^"
        return "syntax error (" + loc + "): " + msg + detail
    except ValueError as e:
        return "syntax error: " + type(e).__name__ + ": " + str(e)
    except Exception as e:
        return "syntax error: " + type(e).__name__ + ": " + str(e)
    return None
