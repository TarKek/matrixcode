"""команда /audit  сводка событий из logs/session-*.jsonl.

Подкоманды:
  /audit               сводка по текущей сессии
  /audit approvals     сколько approve/reject/timeout
  /audit errors        какие ошибки были в тулах
  /audit tools         топ используемых тулов
  /audit last N        последние N событий (по умолчанию 20)
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


# читаем jsonl лога
def _load(path: Path):
    if not path.is_file():
        return
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


_CALL_RE = __import__("re").compile(r"<call-\s*([A-Za-z_][A-Za-z0-9_]*)")


# имя тула из сырой записи
def _tool_name(raw: str) -> str:
    """Вытаскивает имя тула из raw-строки <call- name: ...>."""
    m = _CALL_RE.search(str(raw))
    if m:
        return m.group(1)
    # фолбэк для логов, где call был dict/строкой в старом формате.
    s = str(raw).strip()
    for sep in (":", " "):
        if sep in s:
            s = s.split(sep)[0]
    return s[:40] or "?"


_ERR_TAGS = (
    ("user denied", "user denied"),
    ("syntax error", "syntax error"),
    ("bad args", "bad args"),
    ("PermissionError", "PermissionError"),
    ("TimeoutExpired", "timeout"),
    ("FileNotFoundError", "FileNotFound"),
    ("unknown tool", "unknown tool"),
    ("malformed", "malformed call"),
    ("refusing to write", "refused write"),
    ("refusing to apply edit", "refused edit"),
)


# классификация ошибки
def _error_kind(err: str) -> str:
    low = err.lower()
    for needle, code in _ERR_TAGS:
        if needle.lower() in low:
            return code
    return "error (other)"


def _current_log(app) -> Path | None:
    lg = getattr(app, "logger", None)
    p = getattr(lg, "path", None)
    if isinstance(p, Path) and p.is_file():
        return p
    return None


# сводка событий сессии
def _summary(app, arg: str) -> str:
    log = _current_log(app)
    if log is None:
        return "audit: no log file for this session"
    kinds: Counter = Counter()
    tools: Counter = Counter()
    errors: Counter = Counter()
    approvals = {"granted": 0, "denied": 0, "cached": 0,
                 "timeout": 0, "error": 0}
    total = 0
    for rec in _load(log):
        total += 1
        k = rec.get("kind", "?")
        kinds[k] += 1
        if k == "tool_result":
            nm = _tool_name(rec.get("call") or "")
            tools[nm] += 1
            if rec.get("is_error"):
                err = str(rec.get("result", ""))
                errors[_error_kind(err)] += 1
        elif k.startswith("approval_"):
            key = k.split("_", 1)[1]
            if key in approvals:
                approvals[key] += 1

    lines = [f"audit: {log.name}", f"total events: {total}", ""]
    lines.append("approvals:")
    for k in ("granted", "denied", "cached", "timeout", "error"):
        lines.append(f"  {k:<8} {approvals[k]}")
    lines.append("")
    if errors:
        lines.append("tool errors:")
        for k, n in errors.most_common(10):
            lines.append(f"  {n:>4}  {k}")
        lines.append("")
    if tools:
        lines.append("top tools:")
        for k, n in tools.most_common(10):
            lines.append(f"  {n:>4}  {k}")
    return "\n".join(lines)


# последние N событий
def _last(app, n: int) -> str:
    log = _current_log(app)
    if log is None:
        return "audit: no log file"
    rows = list(_load(log))
    rows = rows[-n:]
    lines = [f"audit: last {len(rows)} events"]
    for rec in rows:
        ts = rec.get("ts", "")[11:23]
        k = rec.get("kind", "?")
        extra = ""
        if k == "tool_result":
            extra = " " + str(rec.get("call", ""))[:60]
            if rec.get("is_error"):
                extra += " [ERR]"
        elif k.startswith("approval_"):
            extra = " " + str(rec.get("args", ""))[:60]
        lines.append(f"  {ts}  {k}{extra}")
    return "\n".join(lines)


# /audit  сводка из логов
def _run(app, arg: str = "") -> str:
    arg = (arg or "").strip()
    low = arg.lower()
    if not arg:
        return _summary(app, arg)
    if low.startswith("last"):
        parts = low.split()
        n = 20
        if len(parts) > 1:
            try:
                n = max(1, min(500, int(parts[1])))
            except ValueError:
                n = 20
        return _last(app, n)
    if low in ("approvals", "tools", "errors"):
        return _summary(app, arg)
    return "usage: /audit [approvals|tools|errors|last N]"


def register(reg):
    reg.add("/audit", "сводка по логу сессии", _run)
