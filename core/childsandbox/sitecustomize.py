"""auto-installed sandbox for Python subprocesses spawned by matrixcode.

Живёт на PYTHONPATH. site.py импортирует его до user-code.

Env-контракт:
  MATRIXCODE_SANDBOX=1     — включить (иначе no-op)
  MATRIXCODE_WORKSPACE     — абсолютный путь к workspace
  MATRIXCODE_DEBUG=1       — печатать подтверждение в stderr
"""
from __future__ import annotations

import io
import os
import sys

if os.environ.get("MATRIXCODE_SANDBOX") == "1":
    import builtins
    import tempfile
    from pathlib import Path

    _ws = Path(os.environ["MATRIXCODE_WORKSPACE"]).resolve()

    # --- разрешённые корни ---------------------------------------------------
    _roots: list[Path] = [_ws]

    for _env in ("TEMP", "TMP", "TMPDIR"):
        _v = os.environ.get(_env)
        if _v:
            try:
                _roots.append(Path(_v).resolve())
            except Exception:
                pass
    try:
        _roots.append(Path(tempfile.gettempdir()).resolve())
    except Exception:
        pass

    _seen: set[str] = set()
    for _p in (sys.prefix, sys.base_prefix,
               sys.exec_prefix, sys.base_exec_prefix):
        if _p and _p not in _seen:
            _seen.add(_p)
            try:
                _roots.append(Path(_p).resolve())
            except Exception:
                pass
    for _p in list(sys.path):
        if not _p or _p in _seen:
            continue
        if "site-packages" in _p or "dist-packages" in _p:
            _seen.add(_p)
            try:
                _roots.append(Path(_p).resolve())
            except Exception:
                pass

    # путь в workspace или temp?
    def _is_allowed(rp: Path) -> bool:
        for _r in _roots:
            try:
                rp.relative_to(_r)
                return True
            except ValueError:
                pass
        return False

    # главный чек пути в дочернем процессе
    def _guard(path) -> None:
        if path is None:
            return
        try:
            p = Path(os.fspath(path))
        except TypeError:
            return
        if not p.is_absolute():
            p = Path.cwd() / p
        try:
            rp = p.resolve()
        except Exception:
            rp = p.absolute()
        if _is_allowed(rp):
            return
        raise PermissionError(
            f"matrixcode child sandbox: '{rp}' outside workspace {_ws}"
        )

    # --- builtins.open / io.open --------------------------------------------
    _orig_open = io.open

    # подмена open с проверкой
    def _sandbox_open(file, mode="r", *a, **kw):
        if not isinstance(file, int):
            _guard(file)
        return _orig_open(file, mode, *a, **kw)

    builtins.open = _sandbox_open
    io.open = _sandbox_open

    # --- os.* (path-taking) --------------------------------------------------
    # оборачиваем os.* и shutil.*
    def _wrap(name):
        real = getattr(os, name)

        def wrapper(path=".", *a, **kw):
            _guard(path)
            return real(path, *a, **kw)

        wrapper.__name__ = name
        wrapper.__qualname__ = name
        return wrapper

    for _name in ("listdir", "scandir", "mkdir", "makedirs",
                  "remove", "unlink", "rmdir", "rename", "replace",
                  "chdir"):
        if hasattr(os, _name):
            setattr(os, _name, _wrap(_name))

    # --- shutil: copy/copy2/move копируют через _winapi.CopyFile2, --------
    # --- который не виден нашему патчу builtins.open. Патчим явно.       --
    try:
        import shutil as _sh

        def _wrap_shutil(name):
            real = getattr(_sh, name)

            def wrapper(*a, **kw):
                # src, dst идут первыми двумя позиционными.
                if len(a) >= 2:
                    _guard(a[1])
                return real(*a, **kw)

            wrapper.__name__ = name
            wrapper.__qualname__ = name
            return wrapper

        for _name in ("copyfile", "copy", "copy2", "copytree", "move"):
            if hasattr(_sh, _name):
                setattr(_sh, _name, _wrap_shutil(_name))
    except Exception:
        pass

    # --- _winapi.CopyFile2 (Windows fast-path для shutil) --------------------
    if sys.platform == "win32":
        try:
            import _winapi
            _orig_copyfile2 = _winapi.CopyFile2

            def _sandbox_copyfile2(src, dst, flags=0):
                _guard(dst)
                return _orig_copyfile2(src, dst, flags)

            _winapi.CopyFile2 = _sandbox_copyfile2
        except Exception:
            pass

    # --- shell escapes -------------------------------------------------------
    _BLOCKED_EXES = {
        "cmd", "cmd.exe", "powershell", "powershell.exe",
        "pwsh", "pwsh.exe", "bash", "sh", "zsh", "dash", "ksh",
    }

    # shell=True с командой вне whitelist
    def _blocked_shell(args) -> bool:
        if not args:
            return False
        first = args[0] if isinstance(args, (list, tuple)) else args
        if not isinstance(first, str):
            return False
        return os.path.basename(first).lower() in _BLOCKED_EXES

    # блок os.system вне workspace
    def _no_system(cmd):
        raise PermissionError(
            "matrixcode child sandbox: os.system/popen disabled — "
            "use subprocess with a non-shell executable"
        )

    os.system = _no_system
    os.popen = _no_system

    try:
        import subprocess as _sp
        _orig_popen = _sp.Popen

        class _Popen(_orig_popen):
            def __init__(self, args, *a, **kw):
                if kw.get("shell"):
                    raise PermissionError(
                        "matrixcode child sandbox: shell=True disabled"
                    )
                if _blocked_shell(args):
                    raise PermissionError(
                        f"matrixcode child sandbox: refusing to spawn "
                        f"shell {args!r}"
                    )
                super().__init__(args, *a, **kw)

        _sp.Popen = _Popen
    except Exception:
        pass

    if os.environ.get("MATRIXCODE_DEBUG") == "1":
        print(f"[matrixcode-child] sandbox active, ws={_ws}",
              file=sys.stderr, flush=True)
