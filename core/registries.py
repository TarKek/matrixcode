"""реестры: тулы, скиллы, команды + их загрузка из папок.

Модульная система: любой .py в tools/, skills/, commands/ с функцией
register(reg) подхватывается автоматически при старте. Файлы на _*
игнорируются. Ошибки загрузки НЕ глотаются — печатаются в stdout,
чтобы не было «молча пропало пол-системы».
"""
from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# реестры
# ---------------------------------------------------------------------------

# реестр тулов, отдаёт блок для промпта
class Registry:
    def __init__(self):
        self.tools: dict[str, dict] = {}

    def add(self, name: str, doc: str, fn) -> None:
        if name in self.tools:
            print(f"[registry] WARN: tool '{name}' redefined", flush=True)
        self.tools[name] = {"doc": doc.strip(), "fn": fn}

    def names(self) -> list[str]:
        return list(self.tools)

    def block(self) -> str:
        if not self.tools:
            return ""
        # compact: one example line per tool + first sentence of help.
        lines = ["Available tools (example form):", ""]
        for name, t in self.tools.items():
            doc_lines = [ln for ln in t["doc"].splitlines() if ln.strip()]
            example = (doc_lines[0].strip() if doc_lines else name)[:120]
            desc = " ".join(doc_lines[1:]) if len(doc_lines) > 1 else ""
            desc = desc.replace(chr(10), " ").replace(chr(13), " ")
            dot = desc.find(". ")
            if dot > 0:
                desc = desc[:dot + 1]
            desc = desc[:110]
            lines.append("  " + example)
            if desc:
                lines.append("      " + desc)
        return "\n".join(lines)


# скиллы  это просто куски текста в промпт
class SkillRegistry:
    def __init__(self):
        self.skills: dict[str, str] = {}

    def add(self, name: str, doc: str) -> None:
        self.skills[name] = doc.strip()

    def block(self) -> str:
        if not self.skills:
            return ""
        parts = ["Native skills (NO <call-> — these are prompt-level):"]
        for name, doc in self.skills.items():
            parts.append(f"\n--- {name} ---")
            parts.append(doc)
        return "\n".join(parts)


# слэш-команды tui
class CommandRegistry:
    def __init__(self):
        self.commands: dict[str, dict] = {}

    def add(self, name: str, doc: str, fn) -> None:
        self.commands[name] = {"doc": doc.strip(), "fn": fn}


# ---------------------------------------------------------------------------
# загрузка модулей
# ---------------------------------------------------------------------------

# импорт модулей из папки без ручной регистрации
def _iter_modules(folder: Path, prefix: str, kind: str):
    """Все .py в folder, у которых есть register(). Ошибки — в stdout.

    kind: "tools" / "skills" / "commands" — только для сообщений.
    """
    if not folder.is_dir():
        print(f"[{kind}] folder does not exist: {folder}", flush=True)
        return

    # импортам внутри модулей нужен корень проекта на sys.path,
    # иначе `from core.paths import ...` упадёт при spec-загрузке.
    # корень проекта на sys.path, иначе импорты падают
    root = str(folder.resolve().parent)
    if root not in sys.path:
        sys.path.insert(0, root)

    for p in sorted(folder.glob("*.py")):
        if p.name.startswith("_"):
            continue
        modname = f"{prefix}{p.stem}"
        spec = importlib.util.spec_from_file_location(modname, p)
        if spec is None or spec.loader is None:
            print(f"[{kind}] FAIL {p.name}: no import spec", flush=True)
            continue
        mod = importlib.util.module_from_spec(spec)
        # важно: регистрируем ДО exec, чтобы импорты внутри модуля
        # могли найти друг друга (редкий, но реальный случай).
        # регистрируем до exec  модули видят друг друга
        sys.modules[modname] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            print(f"[{kind}] FAIL {p.name}: "
                  f"{type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            sys.modules.pop(modname, None)
            continue
        if not hasattr(mod, "register"):
            print(f"[{kind}] SKIP {p.name}: no register()", flush=True)
            continue
        yield mod, p.name


# загрузка тулов + отчёт в stdout
def load_tools(folder: Path, registry: Registry) -> None:
    ok = 0
    for mod, fname in _iter_modules(folder, "mxtool_", "tools"):
        try:
            mod.register(registry)
            ok += 1
        except Exception as e:
            print(f"[tools] FAIL register({fname}): "
                  f"{type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
    print(f"[tools] loaded {ok} module(s) → {len(registry.tools)} tool(s)",
          flush=True)


# то же для скиллов
def load_skills(folder: Path, registry: SkillRegistry) -> None:
    ok = 0
    for mod, fname in _iter_modules(folder, "mxskill_", "skills"):
        try:
            mod.register(registry)
            ok += 1
        except Exception as e:
            print(f"[skills] FAIL register({fname}): "
                  f"{type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
    print(f"[skills] loaded {ok} module(s) → {len(registry.skills)} skill(s)",
          flush=True)


# то же для команд
def load_commands(folder: Path, registry: CommandRegistry) -> None:
    ok = 0
    for mod, fname in _iter_modules(folder, "mxcmd_", "commands"):
        try:
            mod.register(registry)
            ok += 1
        except Exception as e:
            print(f"[commands] FAIL register({fname}): "
                  f"{type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
    print(f"[commands] loaded {ok} module(s) → "
          f"{len(registry.commands)} command(s)", flush=True)
