"""главный цикл диалога: модель -> tool-call -> результат -> модель.

Единственное место, где живёт логика «сколько итераций, когда сдаться,
что делать при зацикливании». Всё общение с UI — через callback-объект.
"""
from __future__ import annotations

import inspect
import re
import time
from typing import Any

import httpx

from agent.context import build_request_messages
from agent.loop_guard import (
    fabricated_correction,
    loop_correction,
    malformed_correction,
    repeat_correction,
)
from agent.prompts import load_system_prompt
from core.compression import compress_messages
from core.display import display_text
from core.logger import Logger, strip_thinking
from core.messages import (
    _append_msg,
    _collapse_consecutive,
    _strip_usage,
)
from core.parser import (
    _inside_code,
    call_fingerprint,
    call_signature,
    extract_calls,
    first_call_pos,
)
from core.paths import (
    COMPRESS_AT,
    FP_REPEAT_LIMIT,
    KEEP_TURNS,
    LOOP_REPEAT_LIMIT,
    MAX_ITERS,
    MAX_LOOP_RECOVERIES,
    MAX_TOKENS,
    SUMMARY_AT,
    SUMMARY_ENABLED,
    SUMMARY_KEEP,
    SUMMARY_MIN_MSGS,
    TEMPERATURE,
    THINKING_TEMPERATURE,
)
from core.registries import Registry, SkillRegistry
from core.summarize import needs_summary, summarize_history
from execution.executor import execute_one
from llm.client import ContextOverflow, chat_stream

# запас на `build_request_messages` (workspace-снимок, MEMORY.md и т.п.).
_REQUEST_OVERHEAD_TOKENS = 600


# обёртка cb, глотает ошибки колбэков
class SafeCB:
    """Прокси, который не падает, если у cb нет метода или он бросил."""

    def __init__(self, inner: Any, logger: Logger):
        self._inner = inner
        self._logger = logger

    def __getattr__(self, name: str) -> Any:
        try:
            inner = getattr(self._inner, name)
        except AttributeError:
            async def noop(*a: Any, **kw: Any) -> None:
                return None
            return noop
        if not callable(inner):
            return inner

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                result = inner(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception as e:
                self._logger.event(
                    "cb_error", method=name,
                    error=f"{type(e).__name__}: {e}",
                )
                return None

        return wrapper


# главный цикл: модель -> tool -> результат
class Agent:
    """Диалог с моделью + исполнение тулов.

    Публичный интерфейс:
      - ask(text, cb): прогнать ход (или продолжить, если text=None)
      - reset(): очистить историю
      - restore(messages): восстановить из лога
      - session_totals(): суммарные токены
    """

    def __init__(self, model: str, registry: Registry,
                 skill_registry: SkillRegistry,
                 logger: Logger, ctx_window: int,
                 system_text: str | None = None,
                 thinking_budget: int = -1):
        self.model = model
        self.registry = registry
        self.skill_registry = skill_registry
        self.logger = logger
        self.ctx_window = ctx_window
        self.compress_threshold = int(ctx_window * COMPRESS_AT)
        self.thinking_budget = thinking_budget

        if system_text is None:
            system_text = load_system_prompt()
            skills_block = skill_registry.block()
            tools_block = registry.block()
            if skills_block:
                system_text += "\n\n" + skills_block
            if tools_block:
                system_text += "\n\n" + tools_block

        self.system_text = system_text
        self.messages: list[dict] = [
            {"role": "system", "content": system_text}
        ]
        self.last_prompt_tokens = 0
        self._last_request_chars = 0
        self._last_fabricated = False

    # сжать историю по запросу /summarize
    async def summarize(self, cb) -> int:
        """Заменить старую часть истории одним резюме (слой 2).

        Возвращает число ходов, ушедших в резюме (0 = no-op).
        При SUMMARY_ENABLED=0 или слишком короткой истории  ничего.
        """
        if not SUMMARY_ENABLED:
            return 0
        if not needs_summary(
                self.messages, ctx_window=self.ctx_window,
                pct=SUMMARY_AT, min_msgs=SUMMARY_MIN_MSGS):
            return 0

        before = len(self.messages)

        async def _err(msg: str) -> None:
            await cb.on_error(msg)

        new_msgs, moved = await summarize_history(
            self.messages, model=self.model, keep_last=SUMMARY_KEEP,
            chat_fn=chat_stream, on_error=_err,
        )
        if moved <= 0:
            return 0

        self.messages = new_msgs
        self.logger.event(
            "summary", moved=moved,
            before=before, after=len(self.messages),
            keep=SUMMARY_KEEP, pct_threshold=SUMMARY_AT,
        )
        await cb.on_error(
            f"summarized {moved} old message(s) into 1; "
            f"history now {len(self.messages)}")
        return moved

    # --- public --------------------------------------------------------


    # очистить историю
    def reset(self) -> None:
        self.messages = [{"role": "system", "content": self.system_text}]
        self.last_prompt_tokens = 0
        self._last_request_chars = 0

    # восстановить из --continue
    def restore(self, messages: list[dict]) -> int:
        if not messages or messages[0].get("role") != "system":
            return 0
        self.messages = _collapse_consecutive(messages)
        return len(self.messages) - 1

    # суммарные токены за сессию
    def session_totals(self) -> tuple[int, int]:
        pt = ct = 0
        for m in self.messages:
            u = m.get("usage") or {}
            pt += u.get("prompt_tokens", 0)
            ct += u.get("completion_tokens", 0)
        return pt, ct

    # один ход пользователя
    async def ask(self, user_text: str | None, cb) -> None:
        cb = SafeCB(cb, self.logger)

        if user_text is not None:
            _append_msg(self.messages, "user", user_text)
        elif len(self.messages) <= 1:
            await cb.on_error("nothing to continue")
            return

        last_combined: tuple | None = None
        fp_counts: dict[tuple, int] = {}
        repeats = 0
        hit_limit = False
        it = 0
        loop_recoveries = 0
        self._last_fabricated = False

        try:
            while MAX_ITERS <= 0 or it < MAX_ITERS:
                current = it
                it += 1

                if not self._ensure_fit(cb):
                    await cb.on_error(
                        "context overflow — cannot fit even after "
                        "aggressive compression. Try /compact manually.")
                    self.logger.event(
                        "error", error_kind="context_overflow_giveup",
                        ctx_window=self.ctx_window)
                    return

                content = await self._one_model_call(
                    cb, current, allow_tools=True)
                if content is None:
                    return

                calls = extract_calls(content)

                if not calls:
                    if self._last_fabricated:
                        _append_msg(self.messages, "user",
                                    fabricated_correction())
                        await cb.on_error(
                            "fabricated result detected — retrying")
                        self.logger.event(
                            "error",
                            error_kind="fabricated_result_retry",
                            snippet=content[:500])
                        continue

                    pos = first_call_pos(content)
                    if pos != -1 and not _inside_code(content, pos):
                        _append_msg(self.messages, "user",
                                    malformed_correction())
                        await cb.on_tool_call("(malformed)", "?")
                        await cb.on_tool_result(
                            "malformed tool call — see chat", True, "?")
                        self.logger.event(
                            "error", error_kind="malformed_call",
                            snippet=content[:500])
                        continue
                    return

                # --- выполнить первый найденный вызов ---
                c = calls[0]
                nm = (c.get("parsed") or {}).get("name", "?")
                await cb.on_tool_call(self._brief(c), nm)

                diff_buffer: list[tuple[str, str, str]] = []

                # накопить и показать диff при большом выводе
                async def _buffered_diff(path, old, new, _buf=diff_buffer):
                    _buf.append((path, old, new))
                res, is_err, nm2 = await execute_one(
                    c, self.registry, self.logger,
                    on_output=cb.on_tool_output,
                    on_diff=_buffered_diff,
                )
                await cb.on_tool_result(self._brief_result(res), is_err, nm2)

                for path, old, new in diff_buffer:
                    await cb.on_tool_diff(path, old, new)
                    await cb.on_file_touched(path, nm2)

                if is_err:
                    await cb.on_tool_error(res, nm2)

                results = [(res, is_err)]

                _append_msg(self.messages, "user",
                            "\n".join(r for r, _ in results))

                # --- детекторы повторов ---
                sig = call_signature(calls)
                result_sig = tuple(r for r, _ in results)
                combined = (sig, result_sig)
                if combined == last_combined:
                    repeats += 1
                else:
                    repeats = 0
                    last_combined = combined

                fp = call_fingerprint(calls)
                fp_counts[fp] = fp_counts.get(fp, 0) + 1
                fp_total = fp_counts[fp]

                if fp_total >= FP_REPEAT_LIMIT:
                    if await self._recover_loop(
                            cb, loop_recoveries, fp_total,
                            fp=fp, sig=None):
                        loop_recoveries += 1
                        fp_counts.clear()
                        last_combined = None
                        repeats = 0
                        continue
                    return

                if repeats >= LOOP_REPEAT_LIMIT - 1:
                    if await self._recover_loop(
                            cb, loop_recoveries, repeats + 1,
                            fp=None, sig=sig):
                        loop_recoveries += 1
                        fp_counts.clear()
                        last_combined = None
                        repeats = 0
                        continue
                    return
            else:
                hit_limit = True
                await cb.on_error(
                    f"max iterations reached ({MAX_ITERS})")
                self.logger.event("error", error_kind="max_iters",
                                  limit=MAX_ITERS)
                await self._final_no_tools_turn(
                    cb, f"tool iteration limit reached ({MAX_ITERS})")
        finally:
            await cb.on_turn_end(hit_limit)

    # --- internals -----------------------------------------------------

    @staticmethod
    def _brief(c: dict) -> str:
        from core.display import call_brief
        return call_brief(c)

    @staticmethod
    def _brief_result(res: str) -> str:
        from core.display import result_brief
        return result_brief(res)

    # --- context fit ---------------------------------------------------

    # грубая оценка токенов истории
    def _estimate_tokens(self) -> int:
        """Грубая оценка токенов для self.messages.

        Использует соотношение char/token из последнего успешного запроса.
        До первого запроса — консервативные 3.0 символа/токен.
        """
        chars = 0
        for m in self.messages:
            chars += len(m.get("content", "") or "") + 8  # role overhead
        if self._last_request_chars and self.last_prompt_tokens:
            ratio = self._last_request_chars / self.last_prompt_tokens
            ratio = max(2.0, min(5.0, ratio))
        else:
            ratio = 3.0
        return int(chars / ratio) + _REQUEST_OVERHEAD_TOKENS

    # сколько токенов осталось на ход
    def _budget_tokens(self) -> int:
        # оставляем место на max_tokens ответа + небольшой запас.
        return max(1024, self.ctx_window - MAX_TOKENS - 256)

    # сжать или дропнуть историю до бюджета
    def _ensure_fit(self, cb) -> bool:
        """Гарантирует, что следующий prompt влезет в ctx_window.

        Возвращает True, если можно делать запрос; False — если даже
        после агрессивного дропа не влезли.
        """
        budget = self._budget_tokens()
        est = self._estimate_tokens()

        # быстрый путь.
        if est <= budget:
            return True

        # шаг 1: обычное сжатие tool-result'ов.
        before_est = est
        before_chars = sum(len(m.get("content", "") or "")
                           for m in self.messages)
        n = compress_messages(self.messages, KEEP_TURNS)
        est = self._estimate_tokens()
        after_chars = sum(len(m.get("content", "") or "")
                          for m in self.messages)
        if n:
            self.logger.event(
                "compression", turns=n,
                chars_before=before_chars, chars_after=after_chars,
                est_before=before_est, est_after=est, budget=budget,
                ctx_window=self.ctx_window)

        if est <= budget:
            return True

        # шаг 2: дропаем самые старые tool-циклы. Сохраняем system (0)
        # и последние 3 сообщения.
        dropped = 0
        while est > budget and len(self.messages) > 4:
            n_drop = min(2, len(self.messages) - 3)
            del self.messages[1:1 + n_drop]
            dropped += n_drop
            est = self._estimate_tokens()

        if dropped:
            self.logger.event(
                "compression_drop", dropped=dropped,
                est_after=est, budget=budget)

        return est <= budget

    # --- loop recovery -------------------------------------------------

    # подсунуть модели коррекцию при цикле
    async def _recover_loop(self, cb, recoveries: int, count: int,
                            fp, sig) -> bool:
        """True → продолжать ход, False → сдаться."""
        if recoveries >= MAX_LOOP_RECOVERIES:
            await cb.on_error("loop limit reached — stopping.")
            self.logger.event(
                "error", error_kind="loop_detected_giveup",
                fingerprint=([(n, str(k)) for n, k in fp] if fp else None),
                signature=(list(sig) if sig else None),
                count=count, recoveries=recoveries,
            )
            return False

        if fp:
            _append_msg(self.messages, "user",
                        loop_correction([], fp, count))
            label = f"{fp[0][0]} on {fp[0][1]!r}"
        else:
            _append_msg(self.messages, "user",
                        repeat_correction(sig, count))
            label = "same call+result"

        await cb.on_error(
            f"loop detected: {label} — auto-recovering "
            f"({recoveries + 1}/{MAX_LOOP_RECOVERIES})")
        self.logger.event(
            "error", error_kind="loop_detected_recover",
            label=label, count=count, recovery=recoveries + 1,
        )
        return True

    # --- model call ----------------------------------------------------

    # один запрос к модели + парсинг вызовов
    async def _one_model_call(self, cb, iter_label: int,
                              allow_tools: bool) -> str | None:
        request_messages = build_request_messages(self.messages)

        self.logger.event(
            "request", iter=iter_label,
            messages=_strip_usage(self.messages),
            temperature=(THINKING_TEMPERATURE
                         if self.thinking_budget > 0 else TEMPERATURE),
            max_tokens=MAX_TOKENS,
            thinking_budget=self.thinking_budget)

        self._last_request_chars = sum(
            len(m.get("content", "") or "") for m in request_messages)

        t0 = time.monotonic()
        try:
            content, usage, thinking_text, thinking_ms = await chat_stream(
                request_messages, self.model,
                on_text_so_far=cb.on_text_so_far,
                on_call_stream=cb.on_call_stream if allow_tools else None,
                on_thinking_so_far=cb.on_thinking_so_far,
                thinking_budget=self.thinking_budget,
            )
        except ContextOverflow as e:
            # оценка промахнулась. Агрессивно чистим и пробуем один раз.
            await cb.on_error(
                "context overflow from server — shrinking and retrying")
            self.logger.event("error", error_kind="context_overflow",
                              body=str(e)[:300])
            dropped = 0
            while len(self.messages) > 4:
                n_drop = min(4, len(self.messages) - 3)
                del self.messages[1:1 + n_drop]
                dropped += n_drop
                if self._estimate_tokens() <= self._budget_tokens():
                    break
            self.logger.event("compression_drop",
                              dropped=dropped, reason="overflow_retry")
            try:
                request_messages = build_request_messages(self.messages)
                self._last_request_chars = sum(
                    len(m.get("content", "") or "")
                    for m in request_messages)
                content, usage, thinking_text, thinking_ms = await chat_stream(
                    request_messages, self.model,
                    on_text_so_far=cb.on_text_so_far,
                    on_call_stream=(cb.on_call_stream
                                    if allow_tools else None),
                    on_thinking_so_far=cb.on_thinking_so_far,
                    thinking_budget=self.thinking_budget,
                )
            except Exception as e2:
                await cb.on_error(f"{type(e2).__name__}: {e2}")
                self.logger.event("error", error_kind="network",
                                  message=str(e2))
                return None
        except httpx.HTTPStatusError as e:
            body = ""
            try:
                body = e.response.text[:300]
            except Exception:
                pass
            await cb.on_error(f"http {e.response.status_code}: {body}")
            self.logger.event("error", error_kind="http", body=body)
            return None
        except Exception as e:
            await cb.on_error(f"{type(e).__name__}: {e}")
            self.logger.event("error", error_kind="network",
                              message=str(e))
            return None

        dt_ms = int((time.monotonic() - t0) * 1000)
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        self.last_prompt_tokens = prompt_tokens
        pct = (prompt_tokens / self.ctx_window * 100
               if self.ctx_window else 0)

        clean_content = strip_thinking(content)

        # --- anti-fabrication ---
        fabricated = ("<result>" in clean_content
                      or "</result>" in clean_content)
        if fabricated:
            clean_content = re.sub(r"</?result>", "",
                                   clean_content).strip()
            self.logger.event("error",
                              error_kind="fabricated_result",
                              snippet=content[:500])

        _append_msg(self.messages, "assistant", clean_content, usage)

        self.logger.event("response", iter=iter_label,
                          content=clean_content,
                          thinking_chars=len(thinking_text),
                          thinking_ms=thinking_ms,
                          usage=usage, latency_ms=dt_ms)
        self.logger.event("context", iter=iter_label,
                          prompt_tokens=prompt_tokens,
                          completion_tokens=completion_tokens,
                          context_window=self.ctx_window,
                          percent=round(pct, 1),
                          threshold=self.compress_threshold)

        if thinking_text:
            await cb.on_thinking_final(thinking_text, thinking_ms)

        await cb.on_text_final(display_text(content))
        await cb.on_status(prompt_tokens, completion_tokens, dt_ms, pct,
                           len(thinking_text), thinking_ms)

        self._last_fabricated = fabricated
        return content

    # финальный ответ без тулов
    async def _final_no_tools_turn(self, cb, reason: str) -> None:
        _append_msg(
            self.messages, "user",
            f"<result>info: {reason}. Do NOT call any tools this turn. "
            f"In plain text, briefly tell the user: "
            f"(1) what was done, (2) what's still left, "
            f"(3) that they can type /continue to keep going.</result>")
        # если после добавления этого сообщения не влезаем — почистим.
        self._ensure_fit(cb)
        try:
            await self._one_model_call(cb, iter_label=-1,
                                       allow_tools=False)
        except Exception as e:
            self.logger.event("error", error_kind="final_turn",
                              message=str(e))
