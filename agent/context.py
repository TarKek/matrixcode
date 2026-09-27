"""что подмешивается в последнее user-сообщение перед отправкой:
   снимок workspace + содержимое MEMORY.md."""
from __future__ import annotations

from core.paths import WORKSPACE_DIR


# снимок workspace  обновляется каждый ход
def workspace_snapshot() -> str:
    """Список файлов и папок в workspace — обновляется каждый ход."""
    try:
        entries = sorted(
            WORKSPACE_DIR.iterdir(),
            key=lambda x: (not x.is_dir(), x.name.lower()),
        )
    except Exception:
        return ""
    if not entries:
        return ""
    lines = ["Current workspace (refreshed each turn):"]
    for e in entries[:20]:
        try:
            if e.is_dir():
                lines.append(f"  [dir]  {e.name}/")
            else:
                size = e.stat().st_size
                lines.append(f"  {size:>8}  {e.name}")
        except Exception:
            lines.append(f"  ?       {e.name}")
    if len(entries) > 20:
        lines.append(f"  ... and {len(entries) - 20} more")
    return "\n".join(lines)


# долговременная память между сессиями
def memory_text() -> str:
    """MEMORY.md — долговременная память между сессиями."""
    p = WORKSPACE_DIR / "MEMORY.md"
    try:
        if p.is_file():
            return ("Long-term memory (MEMORY.md — edit it with "
                    "edit_file/write_file to remember things across "
                    "sessions):\n"
                    + p.read_text(encoding="utf-8",
                                  errors="replace")[:2000])
    except Exception:
        pass
    return ""


# подмешиваем workspace+memory в user-сообщение
def build_request_messages(messages: list[dict]) -> list[dict]:
    """Копия messages, в последнем user-сообщении — header с workspace."""
    snap = workspace_snapshot()
    mem = memory_text()
    header = "\n\n".join(x for x in (snap, mem) if x)
    if not header or not messages:
        return messages
    last = messages[-1]
    if last.get("role") != "user":
        return messages
    merged = dict(last)
    merged["content"] = header + "\n\n---\n\n" + (last.get("content") or "")
    return [*messages[:-1], merged]
