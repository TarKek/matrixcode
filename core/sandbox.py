"""ограничение файловых операций workspace'ом + %TEMP%.

Три части:

  1. Родительский sandbox — патчит builtins.open, io.open, os.*
     в текущем процессе. Активируется флагом _tls.active (его ставит
     executor на время вызова тула, чтобы фоновые операции агента
     не блокировались).

  2. Дочерний sandbox — helper child_env() отдаёт env для subprocess,
     который заставляет Python-подпроцессы сами себя обезопасить через
     sitecustomize на PYTHONPATH.

  3. Preflight-гард — guard_kwargs() прогоняет _guard на всех
     kwargs с путевыми именами. Это ловит тулы, которые читают файлы
     через C-extension (Pillow) или через API, не покрытые патчами
     (os.startfile). Executor вызывает guard_kwargs перед каждым тулом.
"""
from __future__ import annotations

import builtins
import io
import os
import tempfile
import threading
from pathlib import Path

from core import policy
from core.paths import WORKSPACE_DIR

_tls = threading.local()
_approval_hook = None

CHILD_SANDBOX_DIR = Path(__file__).resolve().parent / "childsandbox"

# срок жизни одобрения пути в _approved_paths (секунды).
APPROVAL_TTL_SEC = 600


# юзер отказал  отдельный тип, чтобы не ретраили
class ApprovalDenied(PermissionError):
    """Пользователь явно отклонил доступ (или истёк таймаут).

    Отдельный тип нужен, чтобы executor мог отдать агенту
    понятное 'user denied' вместо безликого PermissionError
    и чтобы модель не пыталась повторять тот же путь.
    """

# имена kwargs, значения которых — пути. Если тул принимает путь под
# другим именем — добавь сюда. Executor сверяется с этим набором.
PATH_ARG_NAMES = frozenset({
    "path", "paths",
    "new_path", "old_path", "target", "target_path",
    "src", "source", "source_path",
    "dst", "dest", "destination", "dest_path",
    "file", "filename", "filepath", "file_path",
    "dir", "directory", "folder",
    "root", "base",
})


def set_approval_hook(fn) -> None:
    """fn(path: str, mode: str, reason: str = "") -> bool.

    Вызывается для путей вне workspace. Возврат True — пропустить.
    """
    global _approval_hook
    _approval_hook = fn


# env для subprocess: включает child sandbox
def child_env(extra: dict | None = None) -> dict:
    """env для subprocess: включает sandbox в дочерних Python-процессах.

    Копия os.environ с добавленным:

      * PYTHONPATH      — наш childsandbox/ первым элементом,
      * MATRIXCODE_SANDBOX=1, MATRIXCODE_WORKSPACE=<абс>,
      * PYTHONSAFEPATH=1 — запрет добавлять cwd/script-dir в sys.path
        (иначе атакующий положит свой sitecustomize.py в workspace и
        перетрёт наш).

    Для не-Python процессов эти переменные игнорируются, вреда нет.
    """
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(CHILD_SANDBOX_DIR) + (os.pathsep + existing if existing else "")
    )
    env["MATRIXCODE_SANDBOX"] = "1"
    env["MATRIXCODE_WORKSPACE"] = str(WORKSPACE_DIR)
    env["PYTHONSAFEPATH"] = "1"
    if extra:
        env.update(extra)
    return env


_TEMP_DIRS: set[Path] = set()
try:
    _TEMP_DIRS.add(Path(tempfile.gettempdir()).resolve())
except Exception:
    pass
for _env in ("TEMP", "TMP", "TMPDIR"):
    _v = os.environ.get(_env)
    if _v:
        try:
            _TEMP_DIRS.add(Path(_v).resolve())
        except Exception:
            pass


def is_in_workspace(path) -> bool:
    try:
        p = Path(path).resolve()
    except Exception:
        return False
    try:
        p.relative_to(WORKSPACE_DIR)
        return True
    except ValueError:
        return False


def is_in_tempdir(path) -> bool:
    try:
        p = Path(path).resolve()
    except Exception:
        return False
    for t in _TEMP_DIRS:
        try:
            p.relative_to(t)
            return True
        except ValueError:
            continue
    return False


def _request_access(path, mode: str, reason: str = "") -> bool:
    if policy.safe_mode():
        return False
    if _approval_hook is None:
        return False
    try:
        return bool(_approval_hook(str(path), mode, reason))
    except TypeError:
        # обратная совместимость со старым хуком на 2 аргумента
        try:
            return bool(_approval_hook(str(path), mode))
        except Exception:
            return False
    except Exception:
        return False


# главный чек пути: workspace, temp, approval
def _guard(path, mode: str) -> None:
    if not getattr(_tls, "active", False):
        return
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
    if is_in_workspace(rp):
        return
    if is_in_tempdir(rp):
        return
    if _request_access(rp, mode):
        return
    raise ApprovalDenied(
        f"user denied access to '{rp}' (mode={mode}). "
        "Do NOT retry the same path with different args  "
        "ask the user for a workspace-relative alternative.")


# preflight: гоняем _guard по всем path-kwargs
def guard_kwargs(kwargs: dict, prefix: str = "") -> None:
    """Preflight: _guard на каждый kwarg с путевым именем.

    Вызывается executor'ом ДО fn(**kwargs). Ловит тулы, которые
    читают файлы не через builtins.open (например, Pillow через
    C-extension) или используют API, не покрытые os.*-обёртками
    (os.startfile). Если тул принимает путь под нестандартным
    именем — добавь это имя в PATH_ARG_NAMES.
    """
    for k, v in kwargs.items():
        if not isinstance(v, str):
            continue
        key = k.lower()
        if key not in PATH_ARG_NAMES:
            continue
        _guard(v, f"{prefix}{k}" if prefix else k)


_orig_open = io.open


def _sandbox_open(file, mode="r", *args, **kwargs):
    if not isinstance(file, int):
        _guard(file, f"open[{mode}]")
    return _orig_open(file, mode, *args, **kwargs)


def _wrap_os1(name: str):
    """Обёртка для os.* с одним путём: listdir, mkdir, remove, ..."""
    real = getattr(os, name)

    def wrapper(path=".", *args, **kwargs):
        _guard(path, f"os.{name}")
        return real(path, *args, **kwargs)

    wrapper.__name__ = name
    wrapper.__qualname__ = name
    return wrapper


# двухпутевые os.*  оба конца проверяем
def _wrap_os2(name: str):
    """Обёртка для os.* с двумя путями: rename(src, dst), replace(src, dst).

    _wrap_os1 здесь НЕ подходит: он проверяет только первый аргумент.
    Именно так rename_file обошёл sandbox — _guard видел src (в workspace),
    а dst (Desktop) уезжал наружу без проверки.
    """
    real = getattr(os, name)

    def wrapper(src, dst, *args, **kwargs):
        _guard(src, f"os.{name}[src]")
        _guard(dst, f"os.{name}[dst]")
        return real(src, dst, *args, **kwargs)

    wrapper.__name__ = name
    wrapper.__qualname__ = name
    return wrapper


# os.startfile = rce в один вызов, патчим
def _install_startfile_guard() -> None:
    """os.startfile не покрыт: open_file открывает .bat / .exe дефолтной
    программой → запуск. Это RCE в один вызов. Патчим."""
    if not hasattr(os, "startfile"):
        return
    orig = os.startfile  # type: ignore[attr-defined]

    def _sandbox_startfile(path, *args, **kwargs):
        _guard(path, "os.startfile")
        return orig(path, *args, **kwargs)

    os.startfile = _sandbox_startfile  # type: ignore[attr-defined]


_SANDBOX_INSTALLED = False


# вешаем патчи один раз при старте
def install_sandbox() -> None:
    global _SANDBOX_INSTALLED
    if _SANDBOX_INSTALLED:
        return
    _SANDBOX_INSTALLED = True
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    builtins.open = _sandbox_open
    io.open = _sandbox_open

    # однопутевые
    for name in ("listdir", "scandir", "mkdir", "makedirs",
                 "remove", "unlink", "rmdir", "chdir"):
        if hasattr(os, name):
            setattr(os, name, _wrap_os1(name))

    # двухпутевые: оба конца проверяются явно.
    for name in ("rename", "replace", "link", "symlink"):
        if hasattr(os, name):
            setattr(os, name, _wrap_os2(name))

    _install_startfile_guard()
