"""загрузка системного промпта: сначала env, потом файл.

Сюда же подмешивается prompts/memory.md - долговременная память по
проекту. Файл читается один раз на старте сессии.
"""
from __future__ import annotations

import os

from core.paths import MEMORY_FILE, SYSTEM_FILE


def load_memory() -> str:
    """Содержимое prompts/memory.md (пустая строка, если файла нет)."""
    try:
        if MEMORY_FILE.is_file():
            return MEMORY_FILE.read_text(encoding="utf-8",
                                         errors="replace").strip()
    except Exception:
        pass
    return ""


def load_system_prompt() -> str:
    raw = os.getenv("MATRIXCODE_SYSTEM_PROMPT")
    if raw is not None:
        base = raw
    else:
        if not SYSTEM_FILE.is_file():
            raise FileNotFoundError(
                f"нет файла {SYSTEM_FILE}. Создай его или задай "
                f"MATRIXCODE_SYSTEM_PROMPT.")
        base = SYSTEM_FILE.read_text(encoding="utf-8")

    mem = load_memory()
    if mem:
        base += ("\n\nPROJECT MEMORY (prompts/memory.md) - durable "
                 "knowledge about this project. Update it with "
                 "edit_file/write_file when you learn something new "
                 "(stack, conventions, known bugs, TODO, decisions):\n"
                 + mem)
    return base
