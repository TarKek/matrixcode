"""команда /iters  менять MAX_ITERS на лету.

0 или -1 = без жёсткого лимита (защита  FP/LOOP detectors).
N > 0   = hard cap на тул-итерации за один ход.

Важно: агент читает модульную глобальную agent.agent.MAX_ITERS в своём
цикле, поэтому меняем именно её, а НЕ core.paths.MAX_ITERS.
"""
import agent.agent as _agent_mod


# /iters  счётчик итераций
def cmd_iters(app, arg: str) -> str:
    arg = arg.strip()
    cur = _agent_mod.MAX_ITERS
    if not arg:
        mode = "unlimited" if cur <= 0 else f"hard limit {cur}"
        return f"max iters = {cur} ({mode}); usage: /iters N (0 = unlimited)"
    try:
        n = int(arg)
    except ValueError:
        return "usage: /iters N (0 = unlimited, N>0 = hard limit)"
    if n < -1:
        return "usage: /iters N (0 = unlimited, N>0 = hard limit)"
    _agent_mod.MAX_ITERS = n
    if n <= 0:
        return "max iters = unlimited"
    return f"max iters = {n}"


def register(reg):
    reg.add("/iters",
            "/iters N  set max tool iterations (0 = unlimited)",
            cmd_iters)
