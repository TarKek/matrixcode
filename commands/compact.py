"""команда /compact  принудительно сжать старые tool-result'ы."""
from core.compression import compress_messages
from core.paths import KEEP_TURNS


# /compact  сжать историю сейчас
def cmd_compact(app, arg: str) -> str:
    if not app.agent:
        return "no agent yet"
    msgs = app.agent.messages
    if len(msgs) < 3:
        return "nothing to compact (session is empty)"
    before = sum(len(m.get("content", "") or "") for m in msgs)
    n = compress_messages(msgs, KEEP_TURNS)
    after = sum(len(m.get("content", "") or "") for m in msgs)
    if n:
        return (f"compacted {n} tool result(s); "
                f"{before} -> {after} chars "
                f"(saved {before - after})")
    return f"nothing to compact ({before} chars, {len(msgs)} messages)"


def register(reg):
    reg.add("/compact", "/compact  force-compress old tool results",
            cmd_compact)
