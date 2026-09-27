"""команда /summarize  семантически сжать старую часть истории.

В отличие от /compact (механический stubs, 0 LLM-вызовов), тут один
вызов модели генерирует 5-10 строк резюме и вся старая история
заменяется на него. Порог  SUMMARY_AT (по умолчанию 0.55 окна).
"""


# /summarize  семантическое резюме
def cmd_summarize(app, arg: str):
    if app.agent is None:
        return "no agent yet"
    if app._busy:
        return "busy  wait for the current turn to finish"
    app.run_summarize()
    return None


def register(reg):
    reg.add("/summarize",
            "/summarize  LLM-summarize old history into one system msg",
            cmd_summarize)
    reg.add("/sum",
            "/sum  alias for /summarize",
            cmd_summarize)
