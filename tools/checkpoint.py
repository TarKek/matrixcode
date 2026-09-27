# tools/checkpoint.py
"""checkpoint / checkpoint_list / checkpoint_revert.

Снапшот workspace, чтобы модель могла экспериментировать и откатывать.

Хранение: WORKSPACE_DIR/.checkpoints/<id>/  (id = YYYYMMDD-HHMMSS[-name])

Исключено из снапшота (обоих направлений):
  .checkpoints/ .matrixcode/ .git/ node_modules/ .venv/ venv/
  __pycache__/ dist/ build/ .pytest_cache/ .mypy_cache/ .ruff_cache/

Лимит: 200 файлов на снапшот — защита от гигабайтов.
"""
from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from core import sandbox
from core.paths import WORKSPACE_DIR

_CP_DIR = WORKSPACE_DIR / ".checkpoints"
_SKIP_DIRS = frozenset({
    ".checkpoints", ".matrixcode", ".git",
    "node_modules", ".venv", "venv", "env",
    "__pycache__", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".idea", ".vscode",
})
_MAX_FILES = 200


# все файлы workspace, пропуская служебное
def _iter_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        yield rel


# id снапшота: timestamp + имя
def _checkpoint_id(name: str = "") -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_"
                   for c in name)[:40] if name else ""
    candidate = f"{ts}-{safe}" if safe else ts
    # коллизия: добавим суффикс
    n = 1
    base = candidate
    while (_CP_DIR / candidate).exists():
        candidate = f"{base}-{n:02d}"
        n += 1
        if n > 99:
            raise RuntimeError("too many checkpoints in this second")
    return candidate


# человекочитаемый размер
def _human_size(p: Path) -> str:
    total = 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except Exception:
                pass
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024:
            return f"{total:.1f} {unit}"
        total /= 1024
    return f"{total:.1f} TB"


# снять снапшот workspace
def checkpoint(name: str = "") -> str:
    files = list(_iter_files(WORKSPACE_DIR))
    if not files:
        return "error: no files in workspace to checkpoint"
    if len(files) > _MAX_FILES:
        return (f"error: workspace has {len(files)} files, max {_MAX_FILES}. "
                f"Move work into a subdirectory or clean up first.")

    try:
        cid = _checkpoint_id(name)
    except RuntimeError as e:
        return f"error: {e}"

    dest = _CP_DIR / cid
    dest.mkdir(parents=True, exist_ok=True)

    for rel in files:
        src = WORKSPACE_DIR / rel
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
        except Exception as e:
            return f"error while copying {rel}: {type(e).__name__}: {e}"

    return (f"ok: checkpoint '{cid}' created "
            f"({len(files)} files, {_human_size(dest)})")


# список всех снапшотов
def checkpoint_list() -> str:
    if not _CP_DIR.is_dir():
        return "no checkpoints"
    entries = sorted([d for d in _CP_DIR.iterdir() if d.is_dir()])
    if not entries:
        return "no checkpoints"
    lines = [f"CHECKPOINTS ({len(entries)}):"]
    for e in entries:
        n = sum(1 for _ in _iter_files(e))
        lines.append(f"  {e.name}  ({n} files, {_human_size(e)})")
    return "\n".join(lines)


# откат workspace к снапшоту
def checkpoint_revert(id: str) -> str:
    if not id:
        return "error: id is required (see checkpoint_list)"
    src = _CP_DIR / id
    if not src.is_dir():
        return f"error: no such checkpoint: {id}"

    allowed = sandbox._request_access(
        str(src),
        "checkpoint_revert",
        f"restore workspace to {id} — files not in snapshot will be DELETED",
    )
    if not allowed:
        return ("error: checkpoint_revert requires approval — denied by "
                "user or no approval hook available.")

    restored = 0
    for rel in _iter_files(src):
        dstf = WORKSPACE_DIR / rel
        dstf.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src / rel, dstf)
            restored += 1
        except Exception as e:
            return f"error while restoring {rel}: {type(e).__name__}: {e}"

    snap_set = {str(r) for r in _iter_files(src)}
    deleted = 0
    for rel in list(_iter_files(WORKSPACE_DIR)):
        if str(rel) not in snap_set:
            try:
                (WORKSPACE_DIR / rel).unlink()
                deleted += 1
            except Exception:
                pass

    return (f"ok: reverted to '{id}' — "
            f"{restored} files restored, {deleted} files removed")


def register(reg):
    reg.add(
        "checkpoint",
        '<call- checkpoint: name:"before-refactor" -call>\n'
        "Snapshot the workspace (excluding .checkpoints/, .matrixcode/, "
        ".git/, node_modules/ and similar noise). Cheap. Use before "
        "risky edits.\n"
        "Args: name (string, optional) — suffix for the id.\n"
        "Result: <result>ok: checkpoint ID created (N files, size)</result>",
        checkpoint,
    )
    reg.add(
        "checkpoint_list",
        '<call- checkpoint_list: -call>\n'
        "List saved checkpoints with id, file count, size.\n"
        "Result: CHECKPOINTS (n): lines.",
        checkpoint_list,
    )
    reg.add(
        "checkpoint_revert",
        '<call- checkpoint_revert: id:"20260921-140000" -call>\n'
        "Restore the workspace to a saved checkpoint. Destructive: files "
        "not present in the snapshot are DELETED. Requires user approval.\n"
        "Args: id (string, required) — from checkpoint_list.\n"
        "Result: <result>ok: reverted to ID</result>",
        checkpoint_revert,
    )
