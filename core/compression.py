"""сжатие старых tool-result'ов перед отправкой в модель.

Ключевая идея: пользовательских ходов в сессии может быть один-два,
а tool-циклов — сотни. Поэтому «keep_turns» — это количество последних
tool-циклов, которые остаются нетронутыми. Всё, что старше, сжимается
до короткой строки-заголовка.
"""
from __future__ import annotations

from core.messages import (
    RESULT_CLOSE,
    RESULT_OPEN,
    is_tool_result,
)


# обрезка одного tool-result
def compress_tool_result(content: str, max_inner: int = 200) -> str:
    if not is_tool_result(content):
        return content
    if not content.rstrip().endswith(RESULT_CLOSE):
        return content
    # срезаем теги result
    inner = content.strip()[len(RESULT_OPEN):-len(RESULT_CLOSE)]
    if len(inner) <= max_inner:
        return content
    head = inner[:80].replace("\n", " ⏎ ")
    return (f"{RESULT_OPEN}[compressed: {len(inner)} chars, "
            f"began with: {head!r}]{RESULT_CLOSE}")


# жмём старые tool-result'ы, свежие не трогаем
def compress_messages(messages: list[dict], keep_turns: int,
                      max_result: int = 200) -> int:
    """Сжимает старые tool-result'ы, оставляя последние keep_turns.

    Возвращает число изменённых сообщений (0 = нечего сжимать).
    """
    if len(messages) < 3:
        return 0

    # индексы всех tool-result'ов в истории
    tool_idx = [
        i for i, m in enumerate(messages)
        if m.get("role") == "user" and is_tool_result(m.get("content", ""))
    ]
    if len(tool_idx) <= keep_turns:
        return 0

    to_compress = tool_idx[:-keep_turns]
    changed = 0
    for i in to_compress:
        c = messages[i].get("content", "")
        new = compress_tool_result(c, max_result)
        if new != c:
            messages[i]["content"] = new
            changed += 1
    return changed
