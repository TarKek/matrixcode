"""семантическое резюме старой части истории диалога.

Слой 2 между /compact (механика, бесплатно) и аварийным drop.
Один вызов chat_stream с выключенной грамматикой и thinking_budget=0.

Чистые функции (needs_summary / split_history / build_summary_messages /
assemble_with_summary) не делают сетевых вызовов и тестируются без LLM.
Сетевой слой  единственная async-функция summarize_history.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from core.logger import strip_thinking

SUMMARY_HEADER = ">[session summary]"

SUMMARY_PROMPT = (
    "Summarize the coding session above for your future self. "
    "Output 5-10 plain lines, no tool calls, no tags, no markdown fences. "
    "Cover: what was attempted, what succeeded (name files and results), "
    "what failed and why, what remains. Be specific. Drop chatter."
)


def _content(m: dict) -> str:
    return m.get("content", "") or ""


def _is_summary_msg(m: dict) -> bool:
    return (m.get("role") == "system"
            and _content(m).lstrip().startswith(SUMMARY_HEADER))


def _chars(messages: list[dict]) -> int:
    return sum(len(_content(m)) + 8 for m in messages)


# пора ли сжимать историю
def needs_summary(messages: list[dict], *, ctx_window: int,
                  pct: float, min_msgs: int,
                  char_per_token: float = 3.0) -> bool:
    """True, если историю стоит заменить резюме.

    Считаем по символам (дёшево, без токенизатора). pct  доля окна,
    при которой пора резюмировать (обычно 0.55).
    """
    if len(messages) < min_msgs:
        return False
    budget = int(ctx_window * pct)
    est = int(_chars(messages) / max(2.0, char_per_token))
    return est > budget


def split_history(messages: list[dict], keep_last: int) -> tuple[list[dict], list[dict]]:
    """Делит историю на (old, recent).

    messages[0]  system, он ВСЕГДА остаётся в recent.
    keep_last  сколько последних НЕ-system сообщений оставить как есть.
    Если в истории уже есть резюме (messages[1]), оно уходит в old.
    """
    if not messages:
        return [], []
    head = messages[0]
    rest = messages[1:]
    if keep_last <= 0 or len(rest) <= keep_last:
        return [], list(messages)
    idx = len(rest) - keep_last
    # не начинать свежий кусок с assistant: некоторые шаблоны
    # ждут первый не-system как user. Сдвигаем на один назад.
    if idx > 0 and rest[idx].get("role") == "assistant":
        idx -= 1
    old = rest[:idx]
    recent = rest[idx:]
    return old, [head, *recent]


def build_summary_messages(system_msg: dict, old: list[dict],
                           recent: list[dict]) -> list[dict]:
    """Собирает messages для одного вызова chat_stream.

    system (сокращённый) + просьба + старые ходы + просьба вывести резюме.
    Свежие ходы НЕ включаем  они останутся в контексте после сборки.
    """
    brief_system = {
        "role": "system",
        "content": (
            "You compress a coding session into a short handover note. "
            "Reply with plain text only. No tool calls. No XML tags."
        ),
    }
    ask = {"role": "user", "content": SUMMARY_PROMPT}
    out = [brief_system, ask]
    for m in old:
        # нормализуем: system-резюме из прошлого цикла не должно
        # идти в середину  chat-template может ругнуться.
        role = m.get("role")
        if role not in ("user", "assistant"):
            role = "user"
        out.append({"role": role, "content": _content(m)})
    out.append({"role": "user", "content":
                "Now write the summary (5-10 plain lines)."})
    return out


def assemble_with_summary(messages: list[dict], keep_last: int,
                          summary_text: str) -> list[dict]:
    """Новая история: [system, summary(system), *recent].

    Резюме кладём role="system" сразу после основного system, чтобы
    _collapse_consecutive() не склеил его с user-сообщениями.
    """
    old, recent = split_history(messages, keep_last)
    if not old:
        return list(messages)
    summary_msg = {
        "role": "system",
        "content": SUMMARY_HEADER + "\n" + summary_text.strip(),
    }
    return [recent[0], summary_msg, *recent[1:]]


def clean_summary(text: str) -> str:
    """Убираем теги/фенсы/think, которые модель могла дописать."""
    t = strip_thinking(text)
    t = re.sub(r"</?result>", "", t)
    t = re.sub(r"```[a-zA-Z]*\n?", "", t)
    t = t.replace("```", "")
    return t.strip()


# модель пишет резюме старой части
async def summarize_history(
    messages: list[dict], *, model: str, keep_last: int,
    chat_fn: Callable[..., Awaitable],
    on_error: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[list[dict], int]:
    """Считает резюме и возвращает (new_messages, сколько ходов ушло).

    chat_fn  llm.client.chat_stream (инжектится, чтобы тест не бил сеть).
    При любой ошибке возвращает (messages, 0)  ход не ломается.
    """
    old, recent = split_history(messages, keep_last)
    if not old:
        return list(messages), 0

    req = build_summary_messages(recent[0], old, recent)
    try:
        content, _usage, _think, _tms = await chat_fn(
            req, model,
            use_grammar=False,
            thinking_budget=0,
        )
    except Exception as e:
        if on_error is not None:
            try:
                await on_error(f"summarize failed: {type(e).__name__}: {e}")
            except Exception:
                pass
        return list(messages), 0

    summary = clean_summary(content)
    if not summary:
        return list(messages), 0

    new_msgs = assemble_with_summary(messages, keep_last, summary)
    return new_msgs, len(old)
