"""склейка сообщений: подряд идущие user/assistant объединяются.

Нужно из-за того, что мы пушим tool-result'ы как user-сообщения, и они
могут накапливаться без ответа ассистента между ними.
"""
from __future__ import annotations

RESULT_OPEN  = "<result>"
RESULT_CLOSE = "</result>"


def is_tool_result(content: str) -> bool:
    return content.lstrip().startswith(RESULT_OPEN)


# склейка подряд идущих ролей
def _append_msg(messages: list[dict], role: str, content: str,
                usage: dict | None = None) -> None:
    if messages and messages[-1].get("role") == role:
        prev = messages[-1]
        prev["content"] = (prev.get("content") or "") + "\n\n" + content
        if usage is not None:
            prev["usage"] = usage
        return
    m: dict = {"role": role, "content": content}
    if usage is not None:
        m["usage"] = usage
    messages.append(m)


# user/assistant подряд -> один блок
def _collapse_consecutive(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        r = m.get("role")
        if r in ("user", "assistant"):
            _append_msg(out, r, m.get("content") or "", m.get("usage"))
        else:
            out.append(dict(m))
    return out


# чистим usage перед записью в лог
def _strip_usage(messages: list[dict]) -> list[dict]:
    """Для логов: убрать поле usage, чтобы JSON не пух."""
    out: list[dict] = []
    for m in messages:
        if "usage" in m:
            out.append({k: v for k, v in m.items() if k != "usage"})
        else:
            out.append(m)
    return out
