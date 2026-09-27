"""профили политики approval.

Один переключатель через env MATRIXCODE_POLICY (или --policy CLI):

  strict   параноидальный. Read-only команды тоже требуют approval.
            Для запуска чужого кода/демо покажи, что он ничего не сделает.

  normal   дефолт. Read-only без вопроса, остальное  approval.
            То, что уже работает.

  dev      лояльный. Снят шум: del/move/ren/pipe/redirection/chaining
            разрешены, потому что разработчик сам их вызывает. Сеть,
            абсолютные пути, system cmdlet, LOLBin, inline-код
            по-прежнему требуют подтверждения.

  safe     approval-хук всегда возвращает deny. Для демонстраций и
            тестов. Агент получает user denied, но никто не спрошен.

Профиль читается один раз при импорте. Менять на лету  только /policy
командой (см. commands/policy.py), при этом кэш причин в run_shell
сбрасывается.
"""
from __future__ import annotations

import os

PROFILES = ("strict", "normal", "dev", "safe")

_DEFAULT = "normal"


# профиль из env, дефолт normal
def _env_profile() -> str:
    raw = (os.getenv("MATRIXCODE_POLICY") or "").strip().lower()
    return raw if raw in PROFILES else _DEFAULT


# текущий профиль. Меняется функцией set_policy (кэш run_shell её вызовет).
CURRENT = _env_profile()


# причины, которые в dev-профиле НЕ требуют approval.
# read-only (dir/type/echo/git status) не в списке  они и так ALLOW
# через отсутствие правила.
# что в dev-профиле не спрашиваем
_DEV_ALLOWED_REASONS = frozenset({
    "delete files (del/erase)",
    "remove dir (rmdir/rd)",
    "move files (move)",
    "rename (ren)",
    "command chaining",
    "pipe to shell",
    "append redirect",
    "redirect absolute",
    "redirect to parent dir",
    "cd ..",
    "parent dir",
})


# в strict-профиле ЛЮБАЯ команда через run_shell требует approval
# даже `dir`. Смысл профиля: показывать пользователю каждый шаг
# агента, без неявных безопасных исключений. Список оставлен
# пустым намеренно; если понадобится смягчить  добавлять сюда.
_STRICT_ALLOWLIST: frozenset = frozenset()


# смена профиля на лету
def set_policy(name: str) -> bool:
    """Меняет профиль. True  успех, False  неизвестное имя."""
    global CURRENT
    name = (name or "").strip().lower()
    if name not in PROFILES:
        return False
    CURRENT = name
    return True


# спрашивать ли approval под текущий профиль
def should_prompt(reason: str | None) -> bool:
    """Спрашивать ли approval для данной причины в текущем профиле.

    reason=None (команда признана безопасной)  False всегда, кроме
    strict: в strict спрашиваем на любое действие.
    """
    if CURRENT == "safe":
        # safe  всегда deny на уровне хука; сюда доходить не должно,
        # но если дошло  считаем требуется approval, хук откажет.
        return True
    if CURRENT == "strict":
        return True
    if CURRENT == "dev":
        if reason is None:
            return False
        return reason not in _DEV_ALLOWED_REASONS
    # normal
    return reason is not None


# хелперы для ui
def safe_mode() -> bool:
    return CURRENT == "safe"


def strict_mode() -> bool:
    return CURRENT == "strict"


def strict_allowlist() -> frozenset:
    return _STRICT_ALLOWLIST


def describe() -> str:
    return CURRENT
