"""команда /continue — продолжить ход ассистента без нового user-сообщения.

Использование: когда модель оборвала мысль на полуслове или ты хочешь,
чтобы она дописала ответ / сделала следующий шаг, но не хочешь
добавлять в контекст лишнюю user-реплику.
"""


# /continue  продолжить без нового ввода
def cmd_continue(app, arg: str):
    if app.agent is None:
        return "no agent yet"
    # только system — продолжать нечего
    if len(app.agent.messages) <= 1:
        return "nothing to continue (session is empty)"
    if app._busy:
        return "busy — wait for the current turn to finish"
    # запускаем новый ход агента без user-сообщения;
    # run_agent_turn — @work, поэтому возвращается сразу,
    # UI сам отрисует стрим.
    app.run_summarize_and_continue(None)
    return None


def register(reg):
    reg.add("/continue",
            "/continue — continue assistant turn (no user message added)",
            cmd_continue)
    reg.add("/cont",
            "/cont — alias for /continue",
            cmd_continue)
