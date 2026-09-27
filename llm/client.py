"""async-клиент llama-server: streaming chat-completions + метаданные.

Никакой логики агента — только транспорт.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable

import httpx

from core.display import display_text, partial_call_info, split_thinking
from core.paths import (
    BASE_URL,
    CTX_DEFAULT,
    GRAMMAR_ENABLED,
    GRAMMAR_FILE,
    HEADERS,
    MAX_TOKENS,
    TEMPERATURE,
    THINKING_TEMPERATURE,
    TIMEOUT,
)


# сервер сказал 400 из-за переполнения ctx
class ContextOverflow(Exception):
    """llama-server вернул 400 из-за переполнения контекста."""


_GRAMMAR_CACHE: str | None = None

# метрики retry: сколько раз клиент повторил запрос.
RETRY_COUNT = 0


def reset_retry_count() -> None:
    global RETRY_COUNT
    RETRY_COUNT = 0


def _bump_retry() -> None:
    global RETRY_COUNT
    RETRY_COUNT += 1


# экспоненциальный backoff с джиттером
def _backoff(attempt: int, retry_after: float | None = None) -> float:
    if retry_after and retry_after > 0:
        return min(retry_after, 30.0)
    base = min(1.5 * (2 ** attempt), 20.0)
    return base + random.uniform(0, 0.5 * base)


# gbnf-грамматика, читаем один раз
def _load_grammar() -> str | None:
    """Читает prompts/tools.gbnf один раз.

    None — если файла нет или грамматика отключена через
    MATRIXCODE_GRAMMAR=0. Печатает статус в stdout при первом вызове —
    это видно в чате и в логах, помогает понять, применилась ли
    грамматика к запросу.
    """
    global _GRAMMAR_CACHE
    if _GRAMMAR_CACHE is not None:
        return _GRAMMAR_CACHE or None
    if not GRAMMAR_ENABLED:
        print("[grammar] disabled by MATRIXCODE_GRAMMAR", flush=True)
        _GRAMMAR_CACHE = ""
        return None
    try:
        _GRAMMAR_CACHE = GRAMMAR_FILE.read_text(encoding="utf-8")
        print(f"[grammar] loaded {len(_GRAMMAR_CACHE)} chars "
              f"from {GRAMMAR_FILE}", flush=True)
    except Exception as e:
        print(f"[grammar] FAILED to read {GRAMMAR_FILE}: "
              f"{type(e).__name__}: {e}", flush=True)
        _GRAMMAR_CACHE = ""
        return None
    return _GRAMMAR_CACHE or None


# n_ctx из /props, fallback на дефолт
async def fetch_context_window() -> tuple[int, str]:
    """Спросить у сервера n_ctx. Возвращает (n_ctx, source)."""
    base = BASE_URL[:-3] if BASE_URL.endswith("/v1") else BASE_URL
    async with httpx.AsyncClient(timeout=5) as client:
        for url in (f"{base}/props", f"{BASE_URL}/props"):
            try:
                r = await client.get(url)
                if r.status_code != 200:
                    continue
                d = r.json()
            except Exception:
                continue
            dgs = d.get("default_generation_settings") or {}
            for src in (dgs, d):
                n = src.get("n_ctx")
                if isinstance(n, int) and n > 0:
                    return n, "props"
    return CTX_DEFAULT, "default"


# список моделей сервера
async def list_models() -> list[str]:
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(f"{BASE_URL}/models", headers=HEADERS)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return []
    return [it["id"] for it in (data.get("data") or []) if it.get("id")]


# эвристика: 400  это overflow?
def _looks_like_context_error(body: str) -> bool:
    b = body.lower()
    return (
        "context" in b
        or "too long" in b
        or "too many tokens" in b
        or "exceed" in b
        or "kv cache" in b
        or "n_ctx" in b
    )


# один стриминговый запрос, ретраит на ошибках
async def chat_stream(
    messages: list[dict],
    model: str,
    on_text_so_far: Callable[[str], Awaitable[None]] | None = None,
    on_call_stream: Callable[[dict | None], Awaitable[None]] | None = None,
    on_thinking_so_far: Callable[[str], Awaitable[None]] | None = None,
    thinking_budget: int = -1,
    use_grammar: bool = True,
) -> tuple[str, dict, str, int]:
    """Один стриминговый запрос.

    Возвращает (content, usage, thinking_text, thinking_ms).
    Если сервер не отдаёт reasoning_content (ik_llama часто не умеет),
    thinking извлекается из content по тегам <think>...</think>.

    Бросает ContextOverflow, если сервер вернул 400 с признаками
    переполнения контекста — Agent это ловит и ретраит после сжатия.
    """
    url = f"{BASE_URL}/chat/completions"
    temperature = (THINKING_TEMPERATURE if thinking_budget > 0
                   else TEMPERATURE)

    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if thinking_budget >= 0:
        payload["chat_template_kwargs"] = {
            "enable_thinking": thinking_budget > 0,
        }
    if thinking_budget > 0:
        payload["thinking_budget_tokens"] = thinking_budget

    if use_grammar:
        grammar = _load_grammar()
        if grammar:
            payload["grammar"] = grammar

    full: list[str] = []
    reasoning_buf: list[str] = []
    usage: dict = {}
    thinking_t0: float | None = None
    thinking_ms = 0
    content_thinking = ""

    last_exc: Exception | None = None
    max_attempts = 4
    for attempt in range(max_attempts):
        # сбрасываем буферы перед повтором
        full.clear()
        reasoning_buf.clear()
        usage = {}
        thinking_t0 = None
        thinking_ms = 0
        content_thinking = ""

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:  # noqa: SIM117
                async with client.stream("POST", url, headers=HEADERS,
                                         json=payload) as r:
                    if r.status_code == 400:
                        # читаем тело — вдруг это context overflow.
                        try:
                            body_bytes = await r.aread()
                            body = body_bytes.decode(
                                "utf-8", errors="replace")
                        except Exception:
                            body = ""
                        if _looks_like_context_error(body):
                            raise ContextOverflow(body[:400])
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("usage"):
                            usage = obj["usage"]
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}

                        reasoning_chunk = delta.get("reasoning_content") or ""
                        if reasoning_chunk:
                            if thinking_t0 is None:
                                thinking_t0 = time.monotonic()
                            reasoning_buf.append(reasoning_chunk)
                            if on_thinking_so_far is not None:
                                try:
                                    await on_thinking_so_far(
                                        "".join(reasoning_buf))
                                except Exception:
                                    pass

                        chunk = delta.get("content") or ""
                        if not chunk:
                            continue

                        full.append(chunk)
                        whole = "".join(full)

                        thinking_now, visible_now = split_thinking(whole)
                        if thinking_now:
                            content_thinking = thinking_now
                            if thinking_t0 is None:
                                thinking_t0 = time.monotonic()
                            if on_thinking_so_far is not None:
                                try:
                                    await on_thinking_so_far(thinking_now)
                                except Exception:
                                    pass
                        else:
                            if (thinking_t0 is not None
                                    and thinking_ms == 0):
                                thinking_ms = int(
                                    (time.monotonic() - thinking_t0) * 1000)

                        if on_text_so_far is not None:
                            try:
                                await on_text_so_far(
                                    display_text(visible_now))
                            except Exception:
                                pass
                        if on_call_stream is not None:
                            try:
                                await on_call_stream(
                                    partial_call_info(visible_now))
                            except Exception:
                                pass
            break
        except ContextOverflow:
            # не ретраим сами — пусть Agent решает.
            raise
        except httpx.HTTPStatusError as e:
            last_exc = e
            code = e.response.status_code
            if code < 400:
                raise
            if code == 429 or code >= 500:  # noqa: SIM102
                if attempt < max_attempts - 1:
                    ra = e.response.headers.get("retry-after")
                    try:
                        ra_f = float(ra) if ra else None
                    except ValueError:
                        ra_f = None
                    _bump_retry()
                    await asyncio.sleep(_backoff(attempt, ra_f))
                    continue
            raise
        except httpx.TransportError as e:
            last_exc = e
            if attempt < max_attempts - 1:
                _bump_retry()
                await asyncio.sleep(_backoff(attempt))
    else:
        if last_exc is not None:
            raise last_exc

    if thinking_t0 is not None and thinking_ms == 0:
        thinking_ms = int((time.monotonic() - thinking_t0) * 1000)

    reasoning_text = "".join(reasoning_buf)
    all_thinking = reasoning_text or content_thinking

    return ("".join(full), usage, all_thinking, thinking_ms)
