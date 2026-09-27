"""безопасный разбор Rich-разметки.

Перед парсингом прогоняем markdown → Rich, потому что модель
по умолчанию пишет markdown, а не Rich markup.
"""
from __future__ import annotations

import io
import re

from rich.console import Console
from rich.text import Text

from core.display import markdown_to_rich

_VALIDATE_CONSOLE = Console(file=io.StringIO(), force_terminal=False)
_TAG_RE = re.compile(r"\[/?[a-zA-Z#][^\]\n]*\]")


def _strip_markup(text: str) -> str:
    return _TAG_RE.sub("", text)


# markdown -> rich, без падения на мусоре
def safe_markup(text: str) -> Text:
    text = markdown_to_rich(text)
    try:
        t = Text.from_markup(text)
    except Exception:
        return Text(_strip_markup(text))

    if not t.spans:
        return t

    clean = []
    for span in t.spans:
        style = span.style
        if style is None:
            clean.append(span)
            continue
        try:
            _VALIDATE_CONSOLE.get_style(style)
            clean.append(span)
        except Exception:
            pass
    if len(clean) != len(t.spans):
        t.spans = clean
    return t
