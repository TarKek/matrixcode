# tools/project_info.py
"""project_info — одним вызовом понять, что за проект.

Один вызов заменяет list_dir + 10× read_file. Детектит языки,
манифесты, зависимости, тесты, CI, контейнеры, линтеры, README.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.paths import WORKSPACE_DIR

_README_NAMES = ("README.md", "README.rst", "README.txt", "README")
_MANIFESTS = (
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "Pipfile", "poetry.lock", "package.json", "package-lock.json",
    "yarn.lock", "pnpm-lock.yaml", "Cargo.toml", "Cargo.lock",
    "go.mod", "go.sum", "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "Gemfile.lock", "composer.json", "composer.lock",
    "CMakeLists.txt", "Makefile", "Rakefile",
)
_CONTAINER = ("Dockerfile", "docker-compose.yml", "docker-compose.yaml",
              ".dockerignore")
_LINTERS = (".flake8", "ruff.toml", ".ruff.toml", "mypy.ini",
            ".pylintrc", ".editorconfig",
            ".eslintrc", ".eslintrc.json", ".eslintrc.js",
            ".prettierrc", ".prettierrc.json",
            ".golangci.yml", "rustfmt.toml")
_TEST_DIRS = ("tests", "test", "spec", "__tests__", "Testing")
_CI_PATHS = (
    ".github/workflows", ".gitlab-ci.yml",
    ".circleci/config.yml", "azure-pipelines.yml",
    ".travis.yml", "Jenkinsfile",
)
_SKIP_DIRS = frozenset({
    ".matrixcode", ".checkpoints", ".git", "__pycache__",
    "node_modules", ".venv", "venv", "env", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
})

_EXT_LANG = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".jsx": "JavaScript(JSX)",
    ".rs": "Rust", ".go": "Go", ".rb": "Ruby", ".php": "PHP",
    ".java": "Java", ".kt": "Kotlin", ".swift": "Swift",
    ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++",
    ".cs": "C#", ".sh": "Shell", ".ps1": "PowerShell", ".bat": "Batch",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".sql": "SQL",
}


# первые N байт файла
def _read_head(path: Path, n: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:n]
    except Exception:
        return ""


# текущая git-ветка, если есть
def _git_branch(root: Path) -> str | None:
    head = root / ".git" / "HEAD"
    if not head.is_file():
        return None
    try:
        t = head.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    return t.split("/")[-1] if t.startswith("ref: ") else t[:8]


# стек по расширениям
def _detect_languages(root: Path) -> list[str]:
    counts: dict[str, int] = {}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if len(rel.parts) > 3:
            continue
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        lang = _EXT_LANG.get(p.suffix.lower())
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return [lang for lang, _ in sorted(counts.items(), key=lambda x: -x[1])[:5]]


# зависимости из pyproject.toml
def _extract_pyproject(text: str) -> dict:
    out: dict = {}
    try:
        import tomllib
        data = tomllib.loads(text)
    except Exception:
        # fallback regex
        m = re.search(r'name\s*=\s*"([^"]+)"', text)
        if m:
            out["name"] = m.group(1)
        m = re.search(r'version\s*=\s*"([^"]+)"', text)
        if m:
            out["version"] = m.group(1)
        return out
    proj = data.get("project") or {}
    out["name"] = proj.get("name")
    out["version"] = proj.get("version")
    deps = proj.get("dependencies") or []
    if deps:
        out["deps"] = [
            re.split(r"[<>=!~\s\[]", d, maxsplit=1)[0]
            for d in deps if isinstance(d, str) and d.strip()
        ]
    poet = (data.get("tool") or {}).get("poetry") or {}
    if poet.get("name") and not out.get("name"):
        out["name"] = poet["name"]
    pdeps = [d for d in (poet.get("dependencies") or {})
             if d.lower() != "python"]
    if pdeps and not out.get("deps"):
        out["deps"] = pdeps
    return out


# зависимости из package.json
def _extract_package_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except Exception:
        return {}
    out: dict = {
        "name": data.get("name"),
        "version": data.get("version"),
    }
    deps = list((data.get("dependencies") or {}).keys())
    if deps:
        out["deps"] = deps[:20]
    scripts = list((data.get("scripts") or {}).keys())
    if scripts:
        out["scripts"] = scripts
    return out


# строки из requirements.txt
def _extract_requirements(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("-"):
            continue
        pkg = re.split(r"[<>=!~\[]", s, maxsplit=1)[0].strip()
        if pkg:
            out.append(pkg)
    return out


# ищем тестовый фреймворк
def _detect_tests(root: Path) -> str | None:
    for d in _TEST_DIRS:
        p = root / d
        if not p.is_dir():
            continue
        try:
            if not any(p.iterdir()):
                continue
        except Exception:
            continue
        has_py = bool(next(p.rglob("test_*.py"), None)) or \
                 bool(next(p.rglob("*_test.py"), None))
        has_js = bool(next(p.rglob("*.test.js"), None)) or \
                 bool(next(p.rglob("*.spec.js"), None))
        has_ts = bool(next(p.rglob("*.test.ts"), None)) or \
                 bool(next(p.rglob("*.spec.ts"), None))
        if has_py:
            return f"{d}/ (pytest-style)"
        if has_js or has_ts:
            return f"{d}/ (jest/vitest-style)"
        return f"{d}/"
    for f in ("tests.py", "test_main.py"):
        if (root / f).is_file():
            return f
    return None


# верхний уровень дерева
def _top_level(root: Path, limit: int = 40):
    dirs: list[str] = []
    files: list[str] = []
    try:
        for p in sorted(root.iterdir(),
                        key=lambda x: (not x.is_dir(), x.name.lower())):
            if p.name in _SKIP_DIRS:
                continue
            if p.is_dir():
                dirs.append(p.name + "/")
            else:
                files.append(p.name)
            if len(dirs) + len(files) >= limit:
                break
    except Exception:
        pass
    return dirs, files


# one-shot разведка проекта
def project_info() -> str:
    root = WORKSPACE_DIR
    lines: list[str] = []

    langs = _detect_languages(root)
    if langs:
        lines.append(f"Languages (by file count): {', '.join(langs)}")

    branch = _git_branch(root)
    lines.append(f"Git: {'yes, HEAD -> ' + branch if branch else 'no .git/'}")

    py: dict = {}
    py_reqs: list[str] = []
    js: dict = {}
    found: list[str] = []

    pj = root / "pyproject.toml"
    if pj.is_file():
        py = _extract_pyproject(_read_head(pj, 8000))
        found.append("pyproject.toml")
    rq = root / "requirements.txt"
    if rq.is_file():
        py_reqs = _extract_requirements(_read_head(rq))
        found.append("requirements.txt")
    pkg = root / "package.json"
    if pkg.is_file():
        js = _extract_package_json(_read_head(pkg, 8000))
        found.append("package.json")

    for name in _MANIFESTS:
        if name in ("pyproject.toml", "requirements.txt", "package.json"):
            continue
        if (root / name).is_file():
            found.append(name)

    if py.get("name"):
        lines.append(f"Python project: {py['name']} {py.get('version') or '?'}")
    if py.get("deps"):
        lines.append("  deps: " + ", ".join(py["deps"][:15]))
    elif py_reqs:
        lines.append("  deps: " + ", ".join(py_reqs[:15]))
    if js.get("name"):
        lines.append(f"Node project: {js['name']} {js.get('version') or '?'}")
    if js.get("deps"):
        lines.append("  deps: " + ", ".join(js["deps"][:15]))
    if js.get("scripts"):
        lines.append("  npm scripts: " + ", ".join(js["scripts"]))
    other = [m for m in found if m not in
             ("pyproject.toml", "requirements.txt", "package.json")]
    if other:
        lines.append("Other manifests: " + ", ".join(other))

    t = _detect_tests(root)
    lines.append(f"Tests: {t}" if t else "Tests: none detected")

    ci = []
    for c in _CI_PATHS:
        p = root / c
        if p.is_dir() and any(p.iterdir()):
            ci.append(c + "/")
        elif p.is_file():
            ci.append(c)
    if ci:
        lines.append("CI: " + ", ".join(ci))

    cont = [c for c in _CONTAINER if (root / c).is_file()]
    if cont:
        lines.append("Containers: " + ", ".join(cont))

    lints = [c for c in _LINTERS if (root / c).is_file()]
    if lints:
        lines.append("Configs: " + ", ".join(lints))

    for rn in _README_NAMES:
        rp = root / rn
        if rp.is_file():
            head = _read_head(rp, 2000).strip()
            if head:
                lines.append("")
                lines.append(f"--- {rn} (first 2000 chars) ---")
                lines.append(head)
                lines.append(f"--- end {rn} ---")
            break

    dirs, files = _top_level(root)
    lines.append("")
    lines.append("Top-level:")
    if dirs:
        lines.append("  dirs:  " + " ".join(dirs[:30]))
    if files:
        lines.append("  files: " + " ".join(files[:30]))

    return "\n".join(lines) if lines else "(empty workspace)"


def register(reg):
    reg.add(
        "project_info",
        '<call- project_info: -call>\n'
        "One-shot overview: language, manifests, dependencies, tests, CI, "
        "containers, linters, README head, top-level structure.\n"
        "Call FIRST for any task in an unfamiliar workspace — it replaces "
        "list_dir plus a dozen read_file calls.\n"
        "Result: compact structured report.",
        project_info,
    )
