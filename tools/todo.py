"""todo_write / todo_read  план между итерациями агента.

Хранится в workspace/.matrixcode/todos.json. Формат  простой список
пунктов {text, status}, status из: pending / in_progress / done / skipped.
Агент пишет план целиком (перезапись), читает  для самопроверки.
"""
from __future__ import annotations

import json

from core.paths import WORKSPACE_DIR

_TODO_DIR = WORKSPACE_DIR / ".matrixcode"
_TODO_FILE = _TODO_DIR / "todos.json"

_VALID = ("pending", "in_progress", "done", "skipped")


# читаем todos.json
def _load() -> list[dict]:
    try:
        if _TODO_FILE.is_file():
            data = json.loads(_TODO_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


# пишем todos.json атомарно
def _save(items: list[dict]) -> None:
    _TODO_DIR.mkdir(parents=True, exist_ok=True)
    _TODO_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8")


# формат для модели
def _fmt(items: list[dict]) -> str:
    if not items:
        return "(empty todo list)"
    icon = {"pending": "[ ]", "in_progress": "[~]",
            "done": "[x]", "skipped": "[-]"}
    lines = []
    for i, it in enumerate(items, 1):
        st = it.get("status", "pending")
        lines.append(f"{i:>2}. {icon.get(st, '[ ]')} {it.get('text', '')}")
    return "\n".join(lines)


# записать план
def todo_write(items: str) -> str:
    """items  JSON-массив вида [{"text": "...", "status": "pending"}].

    Принимаем и просто многострочный текст: каждая строка = пункт (pending).
    """
    parsed: list[dict] = []
    raw = (items or "").strip()
    if not raw:
        return "error: todo_write: empty. Provide a JSON list or one item per line."
    if raw.startswith("["):
        try:
            data = json.loads(raw)
        except Exception as e:
            return f"error: todo_write: bad JSON: {type(e).__name__}: {e}"
        if not isinstance(data, list):
            return "error: todo_write: JSON must be a list"
        for it in data:
            if isinstance(it, str):
                parsed.append({"text": it, "status": "pending"})
            elif isinstance(it, dict):
                st = str(it.get("status", "pending"))
                parsed.append({"text": str(it.get("text", "")),
                               "status": st if st in _VALID else "pending"})
        # авто-фолбэк: первый pending -> in_progress, если in_progress нет
        if not any(p["status"] == "in_progress" for p in parsed):
            for p in parsed:
                if p["status"] == "pending":
                    p["status"] = "in_progress"
                    break
    else:
        for line in raw.splitlines():
            line = line.strip(" -\t")
            if line:
                parsed.append({"text": line, "status": "pending"})
        if parsed:
            parsed[0]["status"] = "in_progress"
    _save(parsed)
    done = sum(1 for p in parsed if p["status"] == "done")
    return (f"ok: saved {len(parsed)} item(s) "
            f"({done} done, {len(parsed) - done} remaining)\n" + _fmt(parsed))


# прочитать план
def todo_read() -> str:
    items = _load()
    if not items:
        return "(empty todo list)"
    return _fmt(items)


def register(reg):
    reg.add(
        "todo_write",
        '<call- todo_write: items>[\n  {"text": "read main.py", "status": "in_progress"},\n  {"text": "fix parser"}\n]</call>\n'
        "Replaces the todo list. `items` is a JSON array of "
        '{"text": str, "status": pending|in_progress|done|skipped}. '
        "Marks the first pending as in_progress automatically. "
        "Use BEFORE a multi-step task, then update statuses as you go.",
        todo_write,
    )
    reg.add(
        "todo_read",
        '<call- todo_read: -call>\n'
        "Returns the current todo list.",
        todo_read,
    )
