"""запись событий сессии в logs/session-*.jsonl + текст-утилиты."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

# ansi-мусор из логов
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# вырезаем thinking-блоки перед логом
_THINK_RE = re.compile(
    r"<(?:think|THINK|thinking|THINKING)>.*?"
    r"</(?:think|THINK|thinking|THINKING)>\s*"
    r"|\[(?:think|THINK|thinking|THINKING)\].*?"
    r"\[/(?:think|THINK|thinking|THINKING)\]\s*",
    re.DOTALL,
)


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def strip_thinking(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


# пишет jsonl, глотает i/o-ошибки
class Logger:
    """Пишет по одной JSON-записи на строку. Не падает при ошибках I/O."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.f = path.open("a", encoding="utf-8")

    # одна запись = одна строка
    def event(self, kind: str, **fields) -> None:
        rec = {"ts": now_iso(), "kind": kind}
        rec.update(fields)
        try:
            self.f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.f.flush()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.f.close()
        except Exception:
            pass
