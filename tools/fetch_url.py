# tools/fetch_url.py
"""fetch_url — GET по URL, HTML → текст.

Требует approval на КАЖДЫЙ вызов: URL в query string — канал утечки
(модель читает .env, добавляет в query, делает запрос). Тот же
approval-хук, что у run_shell.

Ограничения:
  - только GET, только http/https
  - max 200 KB ответа
  - timeout 15 сек
  - UA: matrixcode/0.1
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from core import sandbox

_MAX_BYTES = 200_000
_TIMEOUT = 15.0
_UA = "Mozilla/5.0 (compatible; matrixcode/0.1) fetch_url"

# content-scan: даже одобренный URL может вернуть вредное содержимое.
# агент вставит это в контекст, а модель  в файл. Поэтому помечаем
# ответ тегами и заменяем очевидно опасные куски.
_DANGER_PATTERNS = [
    (re.compile(r"javascript\s*:", re.I), "javascript: URL"),
    (re.compile(r"vbscript\s*:", re.I), "vbscript: URL"),
    (re.compile(r"data\s*:\s*text/html", re.I), "data: HTML"),
    (re.compile(r"<script\b", re.I), "inline <script>"),
    (re.compile(r"<iframe\b", re.I), "inline <iframe>"),
    (re.compile(r"onerror\s*=", re.I), "onerror= handler"),
    (re.compile(r"powershell\s+-e(nc|ncod|ncodedcommand)?\b",
                re.I), "PowerShell -enc payload"),
    (re.compile(r"\bcurl\s+[^|]*\|\s*(?:sh|bash)\b", re.I),
     "curl|sh pattern"),
]

# длинные base64-строки (>200 символов) в HTML/JSON  классический
# способ спрятать payload. Порог намеренно высокий, чтобы не ловить
# обычные токены/хэши.
_B64_RE = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")


# ищем инъекции в ответе: prompt injection guard
def _scan_content(text: str) -> list[str]:
    """Возвращает список найденных опасных маркеров (может быть пуст)."""
    hits: list[str] = []
    for pat, name in _DANGER_PATTERNS:
        if pat.search(text):
            hits.append(name)
    if _B64_RE.search(text):
        hits.append("long base64-like blob (>200 chars)")
    return hits

_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>",
                        re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ENTITIES = {
    "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&quot;": '"', "&#39;": "'", "&apos;": "'",
    "&mdash;": "—", "&ndash;": "–", "&hellip;": "…",
}


# html -> plain text
def _html_to_text(html: str) -> str:
    html = _SCRIPT_RE.sub(" ", html)
    html = re.sub(
        r"</?(?:p|div|br|li|h[1-6]|tr|section|article|header|footer)"
        r"[^>]*>", "\n", html, flags=re.I)
    text = _TAG_RE.sub("", html)
    for k, v in _ENTITIES.items():
        text = text.replace(k, v)
    text = re.sub(r"&#(\d+);",
                  lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"\n[ \t]+\n", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# GET по url, html в текст
def fetch_url(url: str) -> str:
    try:
        parsed = urlparse(url)
    except Exception as e:
        return f"error: bad url: {e}"
    if parsed.scheme not in ("http", "https"):
        return f"error: only http/https allowed, got '{parsed.scheme}'"
    if not parsed.netloc:
        return "error: url has no host"

    allowed = sandbox._request_access(
        url, "fetch_url", "network request")
    if not allowed:
        return ("error: fetch_url requires approval — denied by user "
                "or no approval hook available.")

    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": _UA}) as client:
            r = client.get(url)
    except httpx.HTTPError as e:
        return f"error: {type(e).__name__}: {e}"

    if r.status_code >= 400:
        return f"error: HTTP {r.status_code} {r.reason_phrase}"

    ct = (r.headers.get("content-type") or "").lower()
    raw = r.content[:_MAX_BYTES]
    truncated = (f"\n\n[truncated at {_MAX_BYTES} bytes]"
                 if len(r.content) > _MAX_BYTES else "")

    enc = "utf-8"
    m = re.search(r"charset=([\w\-]+)", ct)
    if m:
        enc = m.group(1)
    try:
        text = raw.decode(enc, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")

    if "html" in ct:
        body = _html_to_text(text)
        kind = "html→text"
    elif "json" in ct:
        body = text
        kind = "json"
    else:
        body = text
        kind = ct.split(";")[0] or "text"

    header = (f"[{r.status_code} {kind}, {len(r.content)} bytes, "
              f"final url: {r.url}]")

    # content-scan: помечаем (но не блокируем  пользователь уже одобрил
    # URL). Помечаем, потому что агент может вслепую писать это в файл.
    hits = _scan_content(body)
    if hits:
        warn = ("[!] content scan flagged: " + ", ".join(hits) +
                "  DO NOT paste this verbatim into a script.")
        return f"{header}\n{warn}\n\n{body}{truncated}"

    return f"{header}\n\n{body}{truncated}"


def register(reg):
    reg.add(
        "fetch_url",
        '<call- fetch_url: url:"https://docs.python.org/3/library/httpx.html" -call>\n'
        "GET a URL, return body as plain text (HTML tags stripped).\n"
        "Use for live docs, changelogs, GitHub READMEs, API responses — "
        "anything your training data may be stale on.\n"
        "Only GET, only http/https, max 200 KB, timeout 15s. Requires "
        "user approval on every call.\n"
        "Args: url (string, required).\n"
        "Result: <result>[status line]\\n\\nbody</result>",
        fetch_url,
    )
