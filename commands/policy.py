"""команда /policy  показать/сменить профиль approval.

  /policy             показать текущий
  /policy dev         переключить
  /policy list        список профилей с описанием
"""
from __future__ import annotations

from core import policy as P

_DESC = {
    "strict": "всё требует approval (демо/чужой код)",
    "normal": "read-only без вопроса, остальное  approval (дефолт)",
    "dev":    "del/move/ren/pipe/redirect/chaining разрешены",
    "safe":   "approval всегда deny, диалога нет (для тестов)",
}


# /policy  показать/сменить профиль
def _run(app, arg: str = "") -> str:
    arg = (arg or "").strip().lower()
    if not arg:
        lines = [f"policy: {P.describe()}"]
        for name in P.PROFILES:
            mark = "*" if name == P.describe() else " "
            lines.append(f"  {mark} {name:<7} {_DESC.get(name, '')}")
        return "\n".join(lines)
    if arg == "list":
        return "\n".join(f"{n}: {_DESC.get(n, '')}" for n in P.PROFILES)
    if arg in P.PROFILES:
        old = P.describe()
        P.set_policy(arg)
        return f"policy: {old} -> {P.describe()}"
    return f"usage: /policy [{' | '.join(P.PROFILES)} | list]"


def register(reg):
    reg.add("/policy", "профиль approval: strict/normal/dev/safe", _run)
