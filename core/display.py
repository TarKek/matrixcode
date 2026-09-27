"""форматирование текста для UI / логов: обрезка, brief-строки, markdown→Rich."""
from __future__ import annotations

import re

from core.parser import (
    _PARTIAL_TAGS,
    KEY_RE,
    NAME_RE,
    _find_call_end,
    _inside_code,
    first_call_pos,
)

# --- thinking split --------------------------------------------------------

_THINK_OPEN_RE = re.compile(r"<(?:think|thinking)\b[^>]*>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"</(?:think|thinking)\s*>", re.IGNORECASE)


# разделяем think и видимый текст
def split_thinking(text: str) -> tuple[str, str]:
    """Возвращает (thinking_text, visible_text)."""
    thinking_parts: list[str] = []
    visible_parts: list[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _THINK_OPEN_RE.search(text, pos)
        if not m:
            visible_parts.append(text[pos:])
            break
        visible_parts.append(text[pos:m.start()])
        start = m.end()
        close = _THINK_CLOSE_RE.search(text, start)
        if close is None:
            thinking_parts.append(text[start:])
            break
        thinking_parts.append(text[start:close.start()])
        pos = close.end()
    return "".join(thinking_parts), "".join(visible_parts)


# --- markdown → Rich markup ------------------------------------------------
#
# модель обычно пишет markdown (`**bold**`, `### heading`, `- item`), а
# панель чата использует Rich markup. Конвертируем. Если модель уже
# пишет `[bold]...[/bold]` — не трогаем, паттерны не совпадут.

# код-блоки трогаем первыми, иначе съест inline
_MD_CODE_BLOCK = re.compile(r"```([a-zA-Z0-9_+-]*)\n(.*?)```", re.DOTALL)
_MD_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_MD_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_MD_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?!\*)")
_MD_H3 = re.compile(r"^###\s+(.+)$", re.MULTILINE)
_MD_H2 = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_MD_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_MD_BULLET = re.compile(r"^(\s*)[-*]\s+(.+)$", re.MULTILINE)
_MD_OLIST = re.compile(r"^(\s*)(\d+)\.\s+(.+)$", re.MULTILINE)
_MD_HR = re.compile(r"^-{3,}$", re.MULTILINE)


# markdown -> rich markup, терпит недописанное
def markdown_to_rich(text: str) -> str:
    """Грубый, но безопасный конвертер. Не падает на неполном markdown
    (во время стриминга куски бывают незакрытыми)."""

    # экранируем [ чтобы rich не парсил код
    def _code_block(m: re.Match) -> str:
        code = m.group(2).rstrip()
        # экранируем одиночные [ чтобы Rich не пытался парсить как markup.
        code = code.replace("[", r"\[")
        return f"[on grey11]\n{code}\n[/on grey11]"

    text = _MD_CODE_BLOCK.sub(_code_block, text)
    text = _MD_INLINE_CODE.sub(lambda m: "[reverse]"
                               + m.group(1).replace("[", r"\[")
                               + "[/reverse]", text)
    text = _MD_BOLD.sub(r"[bold]\1[/bold]", text)
    text = _MD_ITALIC.sub(r"[italic]\1[/italic]", text)
    text = _MD_H3.sub(r"[bold]\1[/bold]", text)
    text = _MD_H2.sub(r"[bold]\1[/bold]", text)
    text = _MD_H1.sub(r"[bold]\1[/bold]", text)
    text = _MD_HR.sub("[grey50]" + "─" * 40 + "[/grey50]", text)
    text = _MD_BULLET.sub(r"\1  • \2", text)
    text = _MD_OLIST.sub(r"\1  \2. \3", text)
    return text


# --- generic helpers -------------------------------------------------------

# ANSI CSI: ESC [ params letter. Этого хватает для 99% случаев —
# SGR-цвета (`\x1b[38;2;R;G;Bm`), reset (`\x1b[0m`), курсор и т.п.
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


# ansi escape долой
def strip_ansi(s: str) -> str:
    """Удалить ANSI escape-последовательности из строки."""
    return _ANSI_CSI_RE.sub("", s)


# обрезаем, не рвя escape-последовательность
def truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    cut = limit
    # не рвать ANSI escape-последовательность пополам: если на позиции
    # среза внутри CSI, сдвигаем срез к началу этой последовательности.
    esc = s.rfind("\x1b[", 0, cut)
    if esc != -1:
        m = _ANSI_CSI_RE.match(s, esc)
        if m is not None and m.end() > cut:
            cut = esc
    return f"{s[:cut]}\n[... truncated {len(s) - cut} chars]"


# однострочный бриф вызова для чата
def call_brief(c: dict, max_total: int = 55) -> str:
    """Однострочный brief вызова. Гарантированно ≤ max_total символов."""
    p = c.get("parsed")
    if not p:
        return "(malformed)"
    name = p.get("name", "?")
    args = p.get("args") or {}
    parts = []
    for k, v in list(args.items())[:2]:
        vs = str(v).replace("\n", "␣").replace("\r", "").replace("\t", " ")
        if len(vs) > 18:
            vs = vs[:15] + "…"
        parts.append(f'{k}="{vs}"')
    s = f"{name}({', '.join(parts)})"
    if len(s) > max_total:
        s = s[:max_total - 1] + "…"
    return s


# бриф результата, без ansi и переносов
def result_brief(res: str, max_len: int = 100) -> str:
    inner = res
    if inner.startswith("<result>"):
        inner = inner[len("<result>"):]
    if inner.endswith("</result>"):
        inner = inner[:-len("</result>")]
    # убираем ANSI: в бриф-строке чата коды отображались бы сырым мусором.
    inner = strip_ansi(inner)
    inner = inner.replace("\n", " ").strip()
    if len(inner) > max_len:
        inner = inner[:max_len - 3] + "..."
    return inner


def _strip_trailing_partial(content: str) -> str:
    for tag in _PARTIAL_TAGS:
        if content.endswith(tag):
            before = content[:-len(tag)]
            if not before or before[-1] in " \t\n>":
                return before
    return content


# только видимый текст: без вызовов и think
def display_text(content: str) -> str:
    """Оставляет только «видимый» текст: без tool-call'ов и без think-блоков."""
    content = _strip_trailing_partial(content)

    parts: list[str] = []
    i, n = 0, len(content)
    while i < n:
        rel = first_call_pos(content[i:])
        if rel == -1:
            parts.append(content[i:])
            break
        start = i + rel
        if _inside_code(content, start):
            parts.append(content[i:start + 5])
            i = start + 5
            continue
        parts.append(content[i:start])
        end, mlen = _find_call_end(content, start + 5)
        if mlen == 0:
            break
        i = end + mlen

    text = "".join(parts)
    _, text = split_thinking(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def re_sub_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)


def text_before_calls(text: str) -> str:
    pos = first_call_pos(text)
    if pos == -1:
        return text.strip()
    return text[:pos].strip()


# инфа о недописанном вызове для индикатора
def partial_call_info(content: str) -> dict | None:
    """Информация о незакрытом tool-call'е — для UI-индикатора."""
    _, content = split_thinking(content)

    search_from = 0
    candidate = -1
    while True:
        rel = first_call_pos(content[search_from:])
        if rel == -1:
            break
        pos = search_from + rel
        if _inside_code(content, pos):
            search_from = pos + 5
            continue
        end, mlen = _find_call_end(content, pos + 5)
        if mlen == 0:
            candidate = pos
            break
        search_from = end + mlen

    if candidate == -1:
        return None

    body_clean = content[candidate + 5:].lstrip("- \t\n")
    m = NAME_RE.match(body_clean)
    if not m:
        return {"name": "?", "arg_hint": "", "chars": len(body_clean)}

    name = m.group(1)
    rest = body_clean[m.end():]
    last_key = ""
    last_end = 0
    for mm in KEY_RE.finditer(rest):
        last_key = mm.group(1)
        last_end = mm.end()
    chars = max(0, len(rest) - last_end)
    return {"name": name, "arg_hint": last_key, "chars": chars}
