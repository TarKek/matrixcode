"""команда /approvals  список активных разрешений на пути."""
from __future__ import annotations

import time


# /approvals  список активных разрешений
def _run(app, arg: str = "") -> str:
    arg = (arg or "").strip().lower()
    cache = getattr(app, "_approved_paths", None)
    if cache is None:
        return "approvals: cache unavailable"

    if arg in ("clear", "reset", "flush"):
        n = len(cache)
        cache.clear()
        return f"approvals: cleared {n} entr{'y' if n == 1 else 'ies'}"

    if not cache:
        return "approvals: empty (no path has been approved this session)"

    now = time.monotonic()
    rows: list[tuple[str, float]] = []
    for k, exp in list(cache.items()):
        if exp < now:
            cache.pop(k, None)
            continue
        rows.append((k, exp - now))

    if not rows:
        return "approvals: empty (all entries expired)"

    rows.sort(key=lambda t: t[1])
    lines = [f"approvals ({len(rows)} active):"]
    for k, ttl in rows:
        lines.append(f"  {ttl:6.1f}s  {k}")
    lines.append("")
    lines.append("usage: /approvals [clear]")
    return "\n".join(lines)


def register(reg):
    reg.add("/approvals", "активные разрешения путей (TTL)", _run)
