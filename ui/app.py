"""matrixCodeApp: layout, ввод, sandbox-подтверждение, /команды."""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

from rich.segment import Segment
from rich.style import Style
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.strip import Strip
from textual.widgets import TextArea

from agent.agent import Agent
from core import paths as core_paths
from core.logger import Logger
from core.messages import is_tool_result
from core.registries import (
    CommandRegistry,
    Registry,
    SkillRegistry,
)
from core.sandbox import APPROVAL_TTL_SEC, WORKSPACE_DIR, set_approval_hook
from ui.callbacks import CB
from ui.chat import ChatColumn
from ui.stats import StatsPanel, StatusBar

_BUSY_PREFIX = "  relax and watch someone cooking.  "


# кадры анимации спиннера
def _slide_frames(width: int = 8) -> list[str]:
    frames: list[str] = []
    for i in range(width):
        row = ["·"] * width
        row[i] = "●"
        frames.append("".join(row))
    for i in range(width - 2, 0, -1):
        row = ["·"] * width
        row[i] = "●"
        frames.append("".join(row))
    return frames


_BUSY_PLACEHOLDER_FRAMES = [_BUSY_PREFIX + f for f in _slide_frames(8)]


# ввод с историей и авто-высотой
class HistoryInput(TextArea):
    """Однострочный по умолчанию, авто-расширяется до 3 строк.

    Enter — отправить.  Shift+Enter / Ctrl+Enter — новая строка.
    Alt+↑ / Alt+↓ — история ввода.
    Ctrl+V — вставка многострочного текста работает штатно.

    NB: у TextArea есть встроенный атрибут `history` (undo/redo),
    поэтому наша история ввода называется `_input_history`.

    NB2: BINDINGS на "enter" у TextArea НЕ работают — она перехватывает
    Enter на уровне _on_key. Поэтому логика отправки сидит прямо в
    _on_key, а не в Binding.
    """

    MIN_CONTENT_H = 1
    MAX_CONTENT_H = 3
    BORDER_H = 2
    MIN_H = MIN_CONTENT_H + BORDER_H
    MAX_H = MAX_CONTENT_H + BORDER_H

    class Submitted(Message):
        def __init__(self, widget: HistoryInput, value: str) -> None:
            super().__init__()
            self.input = widget
            self.value = value

    def __init__(self, placeholder: str = "ask matrixcode…", **kwargs):
        kwargs.setdefault("soft_wrap", True)
        kwargs.setdefault("show_line_numbers", False)
        kwargs.setdefault("tab_behavior", "focus")
        super().__init__(**kwargs)
        self._placeholder_text = placeholder
        self._input_history: list[str] = []
        self._hist_pos = 0
        self._saved_live = ""
        self.styles.height = self.MIN_H

    # --- перехват клавиш (обязательно до BINDINGS) -----------------

    # перехват клавиш: enter, стрелки, ctrl+c
    async def _on_key(self, event) -> None:
        key = event.key
        if key in ("escape", "ctrl+c"):
            app = self.app
            fut = getattr(app, "_pending_confirm", None)
            if fut is not None and not fut.done():
                fut.set_result(False)
                try:
                    from ui.chat import ChatColumn as _CC
                    app.query_one("#chat-log", _CC).add_system("запрещено")
                except Exception:
                    pass
                event.stop()
                event.prevent_default()
                return
        if key == "enter":
            text = self.text
            if text.strip():
                self.post_message(self.Submitted(self, text))
            event.stop()
            event.prevent_default()
            return
        if key in ("shift+enter", "ctrl+enter"):
            self.insert("\n")
            event.stop()
            event.prevent_default()
            return
        if key == "alt+up":
            self._history_prev()
            event.stop()
            event.prevent_default()
            return
        if key == "alt+down":
            self._history_next()
            event.stop()
            event.prevent_default()
            return
        await super()._on_key(event)

    # --- плейсхолдер -----------------------------------------------

    def set_placeholder(self, text: str) -> None:
        self._placeholder_text = text
        if not self.text:
            self.refresh()

    def render_line(self, y: int) -> Strip:
        if not self.text and y == 0:
            style = Style(color="grey50")
            strip = Strip([Segment(self._placeholder_text, style)])
            return strip.adjust_cell_length(self.size.width)
        return super().render_line(y)

    # --- авто-высота -----------------------------------------------

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._auto_resize()

    # подгоняем высоту под контент
    def _auto_resize(self) -> None:
        text = self.text or ""
        lines = max(1, text.count("\n") + 1)
        content_h = min(self.MAX_CONTENT_H,
                        max(self.MIN_CONTENT_H, lines))
        h = content_h + self.BORDER_H
        if self.styles.height != h:
            self.styles.height = h
        self.refresh()

    # --- история ввода ---------------------------------------------

    def remember(self, text: str) -> None:
        if text and (not self._input_history
                     or self._input_history[-1] != text):
            self._input_history.append(text)
        self._hist_pos = 0
        self._saved_live = ""

    def _replace_all(self, text: str) -> None:
        self.text = text
        try:
            lines = text.split("\n")
            self.cursor_location = (len(lines) - 1, len(lines[-1]))
        except Exception:
            pass
        self._auto_resize()

    # навигация по истории вверх
    def _history_prev(self) -> None:
        if not self._input_history:
            return
        if self._hist_pos == 0:
            self._saved_live = self.text
        if self._hist_pos < len(self._input_history):
            self._hist_pos += 1
            self._replace_all(
                self._input_history[-self._hist_pos])

    def _history_next(self) -> None:
        if self._hist_pos == 0:
            return
        self._hist_pos -= 1
        if self._hist_pos == 0:
            self._replace_all(self._saved_live)
        else:
            self._replace_all(
                self._input_history[-self._hist_pos])


# корневое tui-приложение
class MatrixCodeApp(App):
    CSS = """
    Screen { layout: vertical; }
    #main { height: 1fr; }
    #chat-panel {
        width: 3fr;
        border: round $success;
        padding: 0 1;
    }
    #stats-panel {
        width: 1fr;
        min-width: 36;
        border: round $accent;
        padding: 0 1;
    }
    #chat-log { height: 1fr; width: 100%; }
    #stats-scroll { height: 1fr; width: 100%; }
    .msg-user, .msg-assistant, .msg-system, .msg-warn,
    .msg-thinking, .msg-tool, .msg-tool-output, .msg-separator {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }
    .msg-thinking { margin: 0 0 1 0; }
    .msg-tool, .msg-tool-output { margin: 0; }
    .msg-separator { margin: 1 0 0 0; }
    #prompt {
        height: 3;
        margin: 0 1;
        padding: 0 1;
        border: round $primary;
        background: transparent;
    }
    #status { height: 1; background: $panel; padding: 0 1; }
    """

    BINDINGS = [  # noqa: RUF012 -- textual convention
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+l", "clear_chat", "Clear"),
        Binding("ctrl+c", "cancel_confirm", "Cancel", show=False),
    ]

    def __init__(self, registry: Registry,
                 skill_registry: SkillRegistry,
                 logger: Logger, ctx_window: int, models: list[str],
                 thinking_budget: int = -1,
                 commands: CommandRegistry | None = None,
                 resume_messages: list[dict] | None = None):
        super().__init__()
        self.registry = registry
        self.skill_registry = skill_registry
        self.logger = logger
        self.ctx_window = ctx_window
        self.models = models
        self.model: str | None = None
        self.agent: Agent | None = None
        self.pending_model_selection = len(models) > 1
        self.thinking_budget = thinking_budget
        self.commands = commands or CommandRegistry()
        self.resume_messages = resume_messages

        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending_confirm: asyncio.Future | None = None
        # path -> expiry (monotonic). TTL  чтобы разовое разрешение
        # не превращалось в вечный пропуск.
        self._approved_paths: dict[str, float] = {}
        self._approval_lock = threading.Lock()
        self._approval_counts = [0, 0, 0]  # granted, denied, cached

        self._busy = False
        self._busy_frame = 0
        self._busy_warned = False
        self._turn_count = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with Vertical(id="chat-panel"):
                yield ChatColumn(id="chat-log")
            with Vertical(id="stats-panel"):
                yield StatsPanel(id="stats-scroll")
        yield HistoryInput(id="prompt")
        yield StatusBar(id="status")

    def action_clear_chat(self) -> None:
        chat = self.query_one("#chat-log", ChatColumn)
        for child in list(chat.children):
            child.remove()
        chat.finalize_current()
        chat.drop_thinking()
        self._turn_count = 0

    def action_cancel_confirm(self) -> None:
        """Ctrl+C: отклонить активный approval, не выходя из app."""
        fut = self._pending_confirm
        if fut is not None and not fut.done():
            fut.set_result(False)
            try:
                self.query_one("#chat-log", ChatColumn).add_system(
                    "запрещено")
            except Exception:
                pass

    # старт: агент, хоткеи, таймеры
    async def on_mount(self) -> None:
        self._loop = asyncio.get_running_loop()
        set_approval_hook(self._thread_approval_hook)

        stats = self.query_one("#stats-scroll", StatsPanel)
        status = self.query_one(StatusBar)
        status.thinking = self._thinking_label()

        chat = self.query_one("#chat-log", ChatColumn)
        chat.add_system(f"workspace: {WORKSPACE_DIR}")
        if self.pending_model_selection:
            chat.add_system("Выбери модель:")
            for i, m in enumerate(self.models, 1):
                chat.add_system(f"   {i}. {m}")
            chat.add_system(f"введи номер [1-{len(self.models)}]")
            stats.setup("—", core_paths.BASE_URL, self.ctx_window,
                        self.registry.names())
        else:
            self._set_model(self.models[0])
            chat.add_system(f"model: {self.model}")
        chat.add_system(f"thinking: {self._thinking_label()}")

        self.query_one("#prompt", HistoryInput).focus()
        self.set_interval(0.11, self._tick_placeholder)
        self.set_interval(0.5, self._poll_todos)

    def _thinking_label(self) -> str:
        b = self.thinking_budget
        if b < 0:
            return "auto"
        if b == 0:
            return "off"
        return f"on ({b} tok)"

    def _set_model(self, model: str) -> None:
        self.model = model
        self.agent = Agent(
            model=model, registry=self.registry,
            skill_registry=self.skill_registry,
            logger=self.logger, ctx_window=self.ctx_window,
            thinking_budget=self.thinking_budget,
        )
        self.query_one(StatusBar).model = model
        self.query_one("#stats-scroll", StatsPanel).setup(
            model, core_paths.BASE_URL, self.ctx_window,
            self.registry.names())
        self.pending_model_selection = False

        if self.resume_messages:
            n = self.agent.restore(self.resume_messages)
            self.resume_messages = None
            if n:
                try:
                    chat = self.query_one("#chat-log", ChatColumn)
                    chat.add_system(
                        f"── resumed session: {n} messages restored ──")
                except Exception:
                    pass

    # --- busy animation (меняет placeholder) ------------------------

    # анимация плейсхолдера
    def _tick_placeholder(self) -> None:
        if not self._busy:
            return
        self._busy_frame = ((self._busy_frame + 1)
                            % len(_BUSY_PLACEHOLDER_FRAMES))
        try:
            inp = self.query_one("#prompt", HistoryInput)
            inp.set_placeholder(_BUSY_PLACEHOLDER_FRAMES[self._busy_frame])
        except Exception:
            return

    # периодически обновляем todo-панель
    def _poll_todos(self) -> None:
        try:
            self.query_one("#stats-scroll", StatsPanel).poll_todos()
        except Exception:
            pass

    # блокируем ввод на время хода
    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._busy_warned = False
        try:
            self.query_one(StatusBar).busy = busy
        except Exception:
            pass
        try:
            inp = self.query_one("#prompt", HistoryInput)
            if busy:
                inp.set_placeholder(_BUSY_PLACEHOLDER_FRAMES[0])
            else:
                self._busy_frame = 0
                inp.set_placeholder("ask matrixcode…")
        except Exception:
            pass

    # --- sandbox approval -------------------------------------------

    # показываем запрос подтверждения
    def _sync_approval_ui(self, pending: bool | None = None) -> None:
        """Обновляет StatusBar: индикатор ожидания + счётчики."""
        try:
            sb = self.query_one(StatusBar)
        except Exception:
            return
        if pending is not None:
            sb.pending_approval = bool(pending)
        sb.approval_stats = tuple(self._approval_counts)

    def _approval_key(self, path: str) -> str:
        """Нормализованный ключ одобрения (resolve снимает ..)."""
        try:
            return str(Path(path).resolve())
        except Exception:
            return path

    def _approval_cached(self, key: str) -> bool:
        now = time.monotonic()
        with self._approval_lock:
            exp = self._approved_paths.get(key)
            if exp is None:
                return False
            if exp < now:
                del self._approved_paths[key]
                return False
            return True

    # запомнить одобренный путь
    def _approval_store(self, key: str) -> None:
        with self._approval_lock:
            self._approved_paths[key] = (
                time.monotonic() + APPROVAL_TTL_SEC)

    # мост approval-хука в ui-поток
    def _thread_approval_hook(self, path: str, mode: str,
                              reason: str = "") -> bool:
        key = self._approval_key(path)
        if mode != "run_shell" and self._approval_cached(key):
            self._log_command("approval_cached", args=key,
                              mode=mode)
            self._approval_counts[2] += 1
            self._sync_approval_ui(pending=False)
            return True
        loop = self._loop
        if loop is None or loop.is_closed():
            return False
        ok = False
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._ask_confirm(path, mode, reason), loop)
            ok = bool(fut.result(timeout=600))
        except TimeoutError:
            self._log_command("approval_timeout", args=key, mode=mode)
            return False
        except Exception as e:
            self._log_command("approval_error", args=key, mode=mode,
                              error=f"{type(e).__name__}: {e}")
            return False
        if ok and mode != "run_shell":
            self._approval_store(key)
        self._log_command(
            "approval_granted" if ok else "approval_denied",
            args=key, mode=mode, reason=(reason or "")[:200])
        self._approval_counts[0 if ok else 1] += 1
        self._sync_approval_ui(pending=False)
        return ok

    # диалог y/n для путей вне workspace
    async def _ask_confirm(self, path: str, mode: str,
                           reason: str = "") -> bool:
        chat = self.query_one("#chat-log", ChatColumn)
        if mode == "run_shell":
            chat.add_warn(
                f"⚠ Требуется подтверждение команды\n"
                f"   reason: {reason}\n"
                f"   $ {path}\n"
                f"   Выполнить команду? (д/н)")
        else:
            chat.add_warn(
                f"⚠ Запрос доступа к файлу\n"
                f"   путь: {path}\n"
                f"   вне workspace ({WORKSPACE_DIR}).\n"
                f"   ответить (д/н)")
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending_confirm = fut
        self._sync_approval_ui(pending=True)
        try:
            inp = self.query_one("#prompt", HistoryInput)
            inp.set_placeholder("ВЫПОЛНИТЬ? д/н  Ctrl+C отказ")
            inp.focus()
        except Exception:
            pass
        try:
            return await asyncio.wait_for(fut, timeout=600)
        except TimeoutError:
            chat.add_system(" таймаут подтверждения  отказ")
            return False
        finally:
            self._pending_confirm = None
            self._sync_approval_ui(pending=False)
            try:
                self.query_one("#prompt", HistoryInput).set_placeholder(
                    "ask matrixcode…")
            except Exception:
                pass

    # --- обработка ввода --------------------------------------------

    def _log_command(self, name: str, args: str = "", **extra) -> None:
        try:
            self.logger.event("command", name=name,
                              args=(args or "")[:300], **extra)
        except Exception:
            pass

    # разбор ввода: /команда или ход
    async def on_history_input_submitted(
        self, event: HistoryInput.Submitted
    ) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.text = ""
        event.input.remember(text)
        chat = self.query_one("#chat-log", ChatColumn)

        # 1. Подтверждение доступа — в приоритете.
        if (self._pending_confirm is not None
                and not self._pending_confirm.done()):
            ans = text.strip().lower()
            if ans in ("y", "yes", "д", "да"):
                ok = True
            elif ans in ("n", "no", "н", "нет"):
                ok = False
            else:
                chat.add_system("ответь д (да) или н (нет)")
                return
            fut = self._pending_confirm
            if not fut.done():
                fut.set_result(ok)
            chat.add_system("разрешено" if ok else "запрещено")
            return

        # 2. Агент занят — не мешаем.
        if self._busy:
            if not self._busy_warned:
                self._busy_warned = True
                chat.add_system("…still cooking — wait a moment.")
            return

        # 3. Выбор модели.
        if self.pending_model_selection:
            if text.isdigit() and 1 <= int(text) <= len(self.models):
                self._set_model(self.models[int(text) - 1])
                chat.add_system(f"model: {self.model}")
                self.query_one("#prompt", HistoryInput).focus()
            else:
                chat.add_system(f"введи число 1-{len(self.models)}")
            return

        # 3b. log every slash-command before branching
        if text.startswith("/"):
            _parts = text.split(maxsplit=1)
            self._log_command(_parts[0].lower(),
                              _parts[1] if len(_parts) > 1 else "")

        # 4. /exit.
        if text in ("/exit", "/quit", "/q"):
            self.exit()
            return

        # 5. Команды из реестра.
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            entry = self.commands.commands.get(cmd)
            if entry is not None:
                try:
                    out = entry["fn"](self, arg)
                    if asyncio.iscoroutine(out):
                        out = await out
                    if out:
                        chat.add_system(out)
                except Exception as e:
                    chat.add_system(
                        f"command error: {type(e).__name__}: {e}")
                self.query_one("#prompt", HistoryInput).focus()
                return

        # 6. Встроенные команды.
        if text == "/clear":
            self.action_clear_chat()
            if self.agent is not None:
                self.agent.reset()
            chat.add_system("── new session ──")
            self.query_one("#prompt", HistoryInput).focus()
            return

        if text in ("/ctx", "/context"):
            if self.agent is None:
                chat.add_system("agent not initialised")
                return
            if self.agent:
                chars = sum(len(m.get("content", ""))
                            for m in self.agent.messages)
                real = sum(1 for m in self.agent.messages
                           if m.get("role") == "user"
                           and not is_tool_result(m.get("content", "")))
                chat.add_system(
                    f"messages={len(self.agent.messages)} · "
                    f"real_turns={real} · "
                    f"chars={chars} · "
                    f"last_p={self.agent.last_prompt_tokens} · "
                    f"threshold={self.agent.compress_threshold} · "
                    f"thinking={self._thinking_label()}")
            return

        if text == "/model":
            chat.add_system("Доступные модели:")
            for i, m in enumerate(self.models, 1):
                chat.add_system(f"   {i}. {m}")
            self.pending_model_selection = True
            return

        if text == "/think" or text.startswith("/think "):
            arg = text[6:].strip().lower()
            if arg in ("on", "1", "true", "yes"):
                self.thinking_budget = (core_paths.THINKING_BUDGET
                                        if core_paths.THINKING_BUDGET > 0
                                        else 2048)
            elif arg in ("off", "0", "false", "no"):
                self.thinking_budget = 0
            elif arg in ("auto", "default", ""):
                self.thinking_budget = -1
            else:
                chat.add_system("usage: /think auto | on | off")
                return
            if self.agent:
                self.agent.thinking_budget = self.thinking_budget
            label = self._thinking_label()
            self.query_one(StatusBar).thinking = label
            chat.add_system(f"thinking: {label}")
            return

        # 7. Обычный ход агента.
        if self._turn_count > 0:
            chat.add_turn_separator()
        chat.add_user(text)
        self._turn_count += 1
        self.run_agent_turn(text)

    @work(exclusive=True)
    async def run_summarize(self) -> None:
        if self.agent is None:
            return
        chat = self.query_one("#chat-log", ChatColumn)
        stats = self.query_one("#stats-scroll", StatsPanel)
        status = self.query_one(StatusBar)
        self.set_busy(True)
        try:
            moved = await self.agent.summarize(CB(chat, stats, status))
            if moved <= 0:
                chat.add_system("nothing to summarize (threshold not reached)")
        except Exception as e:
            chat.add_system(f"summarize failed: {type(e).__name__}: {e}")
        finally:
            self.set_busy(False)

    @work(exclusive=True)
    async def run_summarize_and_continue(self, text: str | None = None) -> None:
        if self.agent is None:
            return
        chat = self.query_one("#chat-log", ChatColumn)
        stats = self.query_one("#stats-scroll", StatsPanel)
        status = self.query_one(StatusBar)
        self.set_busy(True)
        try:
            from core import paths as P
            from core.summarize import needs_summary
            if P.SUMMARY_ENABLED and needs_summary(
                    self.agent.messages,
                    ctx_window=self.agent.ctx_window,
                    pct=P.SUMMARY_AT, min_msgs=P.SUMMARY_MIN_MSGS):
                await self.agent.summarize(CB(chat, stats, status))
            await self.agent.ask(text, CB(chat, stats, status))
        except Exception as e:
            chat.add_system(f"unhandled: {type(e).__name__}: {e}")
        finally:
            chat.finalize_current()
            chat.drop_thinking()
            self.set_busy(False)

    @work(exclusive=True)
    # запуск хода агента
    async def run_agent_turn(self, text: str | None) -> None:
        if self.agent is None:
            return
        chat = self.query_one("#chat-log", ChatColumn)
        stats = self.query_one("#stats-scroll", StatsPanel)
        status = self.query_one(StatusBar)

        self.set_busy(True)

        try:
            await self.agent.ask(text, CB(chat, stats, status))
        except Exception as e:
            chat.add_system(f"unhandled: {type(e).__name__}: {e}")
        finally:
            chat.finalize_current()
            chat.drop_thinking()
            self.set_busy(False)
