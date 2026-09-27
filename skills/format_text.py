"""format_text — Rich-разметка прямо в тексте ответа, без тула."""


# rich-разметка прямо в тексте ответа
def register(reg):
    reg.add("format_text", """
Format your text with Rich markup inline (NO tool call). Colors:
  [red] [green] [blue] [yellow] [magenta] [cyan] [white] [black]
  [bright_red] [bright_green] [bright_blue] [bright_yellow]
  [bright_magenta] [bright_cyan] [bright_white]
  [grey50] [grey70] [grey85]  (any greyN)
Styles:   [bold] [italic] [underline] [dim] [strike] [reverse]
Combined: [bold red]hot[/bold red]
256/true color: [color(208)]x[/color(208)]  [#ff8800]x[/#ff8800]
NO named "orange"/"pink"/"purple"/"brown" — use hex or color(N).
Escape a literal '[' as \\[.
""".strip())
