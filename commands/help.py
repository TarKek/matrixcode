"""help — список команд и подсказки."""
from __future__ import annotations

from core.sandbox import WORKSPACE_DIR

_BUILTIN = [
    ("/help",            "это сообщение"),
    ("/clear",           "очистить чат и контекст агента"),
    ("/ctx",             "показать статистику контекста"),
    ("/model",           "сменить модель"),
    ("/think auto|on|off", "режим размышлений"),
    ("/exit",            "выход"),
]

# команды, которые регистрируются отдельными модулями в commands/.
# показываем их в /help  иначе про них никто не узнает.
_EXTRA = [
    ("/approvals [clear]", "активные разрешения путей (TTL)"),
    ("/audit [last N]",    "сводка из лога сессии"),
    ("/policy [name]",     "профиль approval: strict/normal/dev/safe"),
]


# /help  список команд
def _run(app, arg: str = "") -> str:
    lines: list[str] = []
    lines.append("matrixcode — команды")
    lines.append("")

    reg = getattr(app, "commands", None)
    reg_names: set[str] = set()
    if reg is not None and hasattr(reg, "commands"):
        reg_names = set(reg.commands.keys())

    lines.append("Built-in:")
    for name, desc in _BUILTIN:
        lines.append(f"  {name:<22} {desc}")
    lines.append("")

    if reg_names:
        extra = sorted(n for n in reg_names if n not in ("/help",))
        if extra:
            lines.append("Registered:")
            for name in extra:
                lines.append(f"  {name}")
            lines.append("")

    lines.append("Safety:")
    for name, desc in _EXTRA:
        lines.append(f"  {name:<22} {desc}")
    lines.append("")

    lines.append("Keyboard:")
    lines.append("  ↑ / ↓        история ввода")
    lines.append("  Ctrl+L       очистить экран (без сброса контекста)")
    lines.append("  Ctrl+C       выход")
    lines.append("")
    lines.append(f"Workspace: {WORKSPACE_DIR}")

    return "\n".join(lines)


def register(reg):
    reg.add("/help", "список команд", _run)
