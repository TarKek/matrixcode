"""левая панель: чат + инлайн-строки вызовов инструментов."""
from __future__ import annotations

import difflib

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from ui.markup import safe_markup


# скролл-колонка с авто-скроллом
class ScrollColumn(VerticalScroll):
    """Базовый скролл с поддержкой одного живого (стримящегося) виджета."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._stream_widget: Static | None = None

    def add_line(self, content, cls: str = "") -> Static:
        w = Static(content)
        if cls:
            w.add_class(cls)
        self.mount(w)
        self.call_after_refresh(self.scroll_end, animate=False)
        return w

    def start_or_update_stream(self, content) -> None:
        if self._stream_widget is None:
            self._stream_widget = Static("")
            self._stream_widget.add_class("msg-assistant")
            self.mount(self._stream_widget)
        self._stream_widget.update(content)
        self.call_after_refresh(self.scroll_end, animate=False)

    def finalize_stream(self, content) -> None:
        if self._stream_widget is None:
            return
        if content is not None:
            self._stream_widget.update(content)
            self.call_after_refresh(self.scroll_end, animate=False)
        else:
            try:
                self._stream_widget.remove()
            except Exception:
                pass
        self._stream_widget = None

    def finalize_current(self) -> None:
        self._stream_widget = None


# чат с форматтерами сообщений
class ChatColumn(ScrollColumn):
    """Чат + все fmt_* функции для строк."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._thinking_widget: Static | None = None

    # --- форматтеры (статические, чтобы ui.callbacks мог их звать) -----

    @staticmethod
    def fmt_user(text: str) -> Text:
        t = Text()
        t.append("▶ ", style="bold green")
        t.append(text)
        return t

    @staticmethod
    def fmt_assistant(text: str) -> Text:
        t = Text()
        t.append("◆ ", style="bold cyan")
        t.append_text(safe_markup(text))
        return t

    @staticmethod
    def fmt_system(text: str) -> Text:
        return Text(text, style="dim")

    @staticmethod
    def fmt_warn(text: str) -> Text:
        t = Text()
        for i, line in enumerate(text.splitlines()):
            if i:
                t.append("\n")
            t.append(line, style="bold yellow")
        return t

    @staticmethod
    def fmt_thinking_stream(text: str) -> Text:
        t = Text()
        t.append("  🧠 ", style="grey35")
        preview = text.replace("\n", " ").strip()
        if len(preview) > 110:
            preview = preview[:107] + "…"
        t.append(preview, style="grey50 italic")
        return t

    @staticmethod
    def fmt_thinking_done(chars: int, ms: int) -> Text:
        t = Text()
        t.append("  🧠 ", style="grey35")
        t.append(f"thought {chars} chars in {ms} ms", style="grey50")
        return t

    @staticmethod
    def fmt_tool_calling(brief: str) -> Text:
        t = Text()
        t.append("  ⚙ ", style="grey50")
        t.append(brief, style="grey50")
        t.append(" …", style="grey50")
        return t

    @staticmethod
    def fmt_tool_done(brief: str, is_err: bool) -> Text:
        t = Text()
        t.append("  ⚙ ", style="grey50")
        t.append(brief, style="grey50")
        t.append(" — ", style="grey50")
        if is_err:
            t.append("err", style="bold red")
        else:
            t.append("ok", style="bold green")
        return t

    @staticmethod
    def fmt_tool_stream(spin_ch: str, name: str, arg_hint: str,
                        chars: int) -> Text:
        t = Text()
        t.append(f"  {spin_ch} ", style="bold yellow")
        t.append(name or "?", style="grey50")
        if arg_hint:
            t.append(f" {arg_hint}", style="grey50")
        t.append(f"  receiving {chars} chars…", style="grey35")
        return t

    @staticmethod
    def fmt_tool_output(text: str, name: str = "") -> Text:
        # для show_image не добавляем префикс — он ломает картинку.
        is_image = (name == "show_image")
        prefix = "" if is_image else "    │ "
        lines = text.rstrip("\n").splitlines() or [""]
        out = Text()
        for i, line in enumerate(lines):
            if i:
                out.append("\n")
            if prefix:
                out.append(prefix, style="grey35")
            if not line:
                continue
            try:
                sub = Text.from_ansi(line)
            except Exception:
                sub = Text(line, style="grey62")
            if not is_image and all(span.style is None for span in sub.spans):
                sub.stylize("grey62")
            out.append_text(sub)
        return out

    # --- diff / error / separator ------------------------------------

    @staticmethod
    # рендер diff файла в чат
    def fmt_tool_diff(path: str, old_text: str, new_text: str,
                      max_lines: int = 20) -> Text:
        """Unified diff старого и нового содержимого файла."""
        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()
        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile="", tofile="", lineterm="", n=1,
        ))
        # пропускаем заголовки --- и +++ (они пустые после fromfile="")
        diff = [ln for ln in diff
                if not (ln.startswith("--- ") or ln.startswith("+++ "))]
        t = Text()
        if not diff:
            return t
        shown = 0
        for line in diff:
            if shown >= max_lines:
                t.append(f"      … +{len(diff) - shown} more diff lines\n",
                         style="grey50")
                break
            if line.startswith("@@"):
                t.append(f"    {line}\n", style="grey50")
            elif line.startswith("+"):
                t.append(f"    {line}\n", style="green")
            elif line.startswith("-"):
                t.append(f"    {line}\n", style="red")
            else:
                t.append(f"    {line}\n", style="grey62")
        return t

    @staticmethod
    def fmt_tool_error(text: str, max_lines: int = 3) -> Text:
        """Хвост текста ошибки — последние max_lines строк.

        У трейсбеков самое важное в конце (UnboundLocalError: ...),
        поэтому показываем хвост, а не начало.
        """
        inner = text
        if inner.startswith("<result>"):
            inner = inner[len("<result>"):]
        if inner.endswith("</result>"):
            inner = inner[:-len("</result>")]
        # убираем одинарный префикс "error: " если есть.
        if inner.startswith("error: "):
            inner = inner[len("error: "):]
        inner = inner.strip()
        if not inner:
            return Text()
        lines = [ln for ln in inner.splitlines() if ln.strip()]
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        skipped = len(lines) - len(tail)
        t = Text()
        if skipped > 0:
            t.append(f"      … {skipped} lines above\n", style="grey50")
        for ln in tail:
            t.append(f"      {ln}\n", style="red")
        return t

    @staticmethod
    def fmt_turn_separator() -> Text:
        t = Text()
        t.append("─" * 60, style="grey27")
        return t

    # --- thinking widget ----------------------------------------------

    # стрим thinking в отдельный блок
    def start_or_update_thinking(self, text: str) -> None:
        if self._thinking_widget is None:
            self._thinking_widget = Static("")
            self._thinking_widget.add_class("msg-thinking")
            self.mount(self._thinking_widget)
        self._thinking_widget.update(self.fmt_thinking_stream(text))
        self.call_after_refresh(self.scroll_end, animate=False)

    def finalize_thinking(self, chars: int, ms: int) -> None:
        if self._thinking_widget is None:
            return
        self._thinking_widget.update(self.fmt_thinking_done(chars, ms))
        self.call_after_refresh(self.scroll_end, animate=False)
        self._thinking_widget = None

    def drop_thinking(self) -> None:
        if self._thinking_widget is not None:
            try:
                self._thinking_widget.remove()
            except Exception:
                pass
            self._thinking_widget = None

    # --- обычные строки -----------------------------------------------

    def add_user(self, text: str) -> None:
        self.add_line(self.fmt_user(text), "msg-user")

    def add_system(self, text: str) -> None:
        self.add_line(self.fmt_system(text), "msg-system")

    def add_warn(self, text: str) -> None:
        self.add_line(self.fmt_warn(text), "msg-warn")

    def add_tool_calling(self, brief: str) -> Static:
        return self.add_line(self.fmt_tool_calling(brief), "msg-tool")

    def update_tool_done(self, widget: Static, brief: str,
                         is_err: bool) -> None:
        widget.update(self.fmt_tool_done(brief, is_err))

    def add_tool_output(self, text: str, name: str = "") -> None:
        self.add_line(self.fmt_tool_output(text, name), "msg-tool-output")

    def add_tool_diff(self, path: str, old_text: str, new_text: str) -> None:
        body = self.fmt_tool_diff(path, old_text, new_text)
        if body.plain:
            self.add_line(body, "msg-tool-output")

    def add_tool_error(self, text: str) -> None:
        body = self.fmt_tool_error(text)
        if body.plain:
            self.add_line(body, "msg-tool-output")

    def add_turn_separator(self) -> None:
        self.add_line(self.fmt_turn_separator(), "msg-separator")
