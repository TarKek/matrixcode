"""cB — мост между Agent и виджетами TUI.

Agent общается только через методы on_*. Здесь они превращаются
в обновления чата, статистики и статус-бара.
"""
from __future__ import annotations

from textual.widgets import Static

from ui.chat import ChatColumn


# мост agent -> виджеты, без знания агента про ui
class CB:
    _SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, chat: ChatColumn, stats, status):
        self.chat = chat
        self.stats = stats
        self.status = status

        self._tool_widget: Static | None = None
        self._tool_brief = ""
        self._inflight_info: dict | None = None
        self._spin_i = 0
        self._thinking_seen = False

    # --- thinking ----------------------------------------------------

    async def on_thinking_so_far(self, t: str) -> None:
        if t and t.strip():
            self._thinking_seen = True
            self.chat.start_or_update_thinking(t)

    async def on_thinking_final(self, text: str, ms: int) -> None:
        if text:
            self.chat.finalize_thinking(len(text), ms)
        elif self._thinking_seen:
            self.chat.drop_thinking()

    # --- обычный текст / стриминг вызова ----------------------------

    async def on_text_so_far(self, t: str) -> None:
        if t and t.strip():
            self.chat.start_or_update_stream(
                ChatColumn.fmt_assistant(t))

    async def on_call_stream(self, info: dict | None) -> None:
        if info is None:
            self._inflight_info = None
            return
        self._spin_i = (self._spin_i + 1) % len(self._SPIN)
        spin_ch = self._SPIN[self._spin_i]
        txt = ChatColumn.fmt_tool_stream(
            spin_ch,
            info.get("name", "?"),
            info.get("arg_hint", ""),
            info.get("chars", 0),
        )
        if self._tool_widget is None:
            self._tool_widget = self.chat.add_line(txt, "msg-tool")
        else:
            try:
                self._tool_widget.update(txt)
            except Exception:
                self._tool_widget = self.chat.add_line(txt, "msg-tool")
        self._inflight_info = info

    async def on_text_final(self, t: str) -> None:
        if t and t.strip():
            self.chat.finalize_stream(ChatColumn.fmt_assistant(t))
        else:
            self.chat.finalize_stream(None)

    # --- конец хода --------------------------------------------------

    async def on_turn_end(self, hit_limit: bool = False) -> None:
        self.chat.finalize_current()
        self.chat.drop_thinking()
        if self._tool_widget is not None and not self._tool_brief:
            try:
                self._tool_widget.remove()
            except Exception:
                pass
        self._tool_widget = None
        self._tool_brief = ""
        self._inflight_info = None

    # --- вызовы тулов -----------------------------------------------

    # тул начался  рисуем строку
    async def on_tool_call(self, brief: str, name: str) -> None:
        self._tool_brief = brief
        if self._tool_widget is not None:
            try:
                self._tool_widget.update(
                    ChatColumn.fmt_tool_calling(brief))
            except Exception:
                self._tool_widget = self.chat.add_tool_calling(brief)
        else:
            self._tool_widget = self.chat.add_tool_calling(brief)
        self._inflight_info = None

    # тул завершён  обновляем строку
    async def on_tool_result(self, brief: str, is_err: bool,
                             name: str) -> None:
        if self._tool_widget is not None:
            try:
                self._tool_widget.update(ChatColumn.fmt_tool_done(
                    self._tool_brief, is_err))
            except Exception:
                pass
            self._tool_widget = None

    async def on_tool_output(self, text: str, name: str = "") -> None:
        self.chat.add_tool_output(text, name)

    async def on_tool_diff(self, path: str, old_text: str,
                           new_text: str) -> None:
        self.chat.add_tool_diff(path, old_text, new_text)

    async def on_tool_error(self, text: str, name: str = "") -> None:
        self.chat.add_tool_error(text)

    async def on_file_touched(self, path: str, kind: str = "") -> None:
        self.stats.file_touched(path, kind)

    # --- системные события ------------------------------------------

    async def on_compression(self, n: int, before: int, after: int) -> None:
        self.chat.add_system(f"⚡ compressed {n} result(s) "
                             f"({before} → {after} chars)")

    async def on_status(self, pt: int, ct: int, ms: int, pct: float,
                        thinking_chars: int = 0,
                        thinking_ms: int = 0) -> None:
        self.stats.turn_stats(pt, ct, ms, pct,
                              thinking_chars, thinking_ms)

    async def on_error(self, msg: str) -> None:
        self.chat.add_system(f"error: {msg}")
