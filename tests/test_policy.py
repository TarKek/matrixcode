"""тесты core.policy + интеграция с run_shell.run_shell (safe/dev/strict)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.run_shell as RS
from core import policy as P
from core import sandbox

results, passed = [], 0


def check(name, cond):
    global passed
    if cond:
        passed += 1
    else:
        results.append(name)


def restore():
    P.set_policy("normal")


# --- базовые вызовы ---
check("profiles tuple", set(P.PROFILES) == {"strict", "normal", "dev", "safe"})

restore()
check("normal: None -> no prompt", P.should_prompt(None) is False)
check("normal: reason -> prompt", P.should_prompt("absolute path") is True)

P.set_policy("dev")
check("dev: del -> no prompt",
      P.should_prompt("delete files (del/erase)") is False)
check("dev: pipe to shell -> no prompt",
      P.should_prompt("pipe to shell") is False)
check("dev: abs path -> prompt",
      P.should_prompt("absolute path") is True)
check("dev: system cmdlet -> prompt",
      P.should_prompt("system cmdlet") is True)

P.set_policy("strict")
check("strict: None -> prompt", P.should_prompt(None) is True)
check("strict: reason -> prompt", P.should_prompt("absolute path") is True)

P.set_policy("safe")
check("safe: safe_mode()", P.safe_mode() is True)
check("safe: should_prompt True", P.should_prompt(None) is True)

# --- set_policy возвращает bool ---
restore()
check("set_policy: valid", P.set_policy("dev") is True)
check("set_policy: invalid", P.set_policy("nonsense") is False)
restore()

# --- run_shell: safe-профиль отказывает без хука ---
P.set_policy("safe")
sandbox.set_approval_hook(None)
r = RS.run_shell("echo hello")
check("safe: echo refused", "user denied" in r and "safe policy" in r)

# --- run_shell: dev-профиль пускает `del` без диалога ---
P.set_policy("dev")
# подменяем approval hook на счётчик  если он вызовется, тест провален.
calls = []
sandbox.set_approval_hook(lambda *a, **kw: (calls.append(a), True)[1])
# `del nonexistent_file_xyz.txt`  команда реально безопасна в этом тесте
# (файла нет), но классификатор её видит как delete files. В dev  allowed.
try:
    r = RS.run_shell("del nonexistent_zzz.txt")
except Exception as e:
    r = f"EXC {type(e).__name__}: {e}"
check("dev: del runs without prompt", len(calls) == 0)
check("dev: del produced output", "exit=" in r)

# --- run_shell: strict-профиль спрашивает на `dir` ---
P.set_policy("strict")
calls.clear()
# подменяем hook: он должен спроситься даже на `dir`.
sandbox.set_approval_hook(lambda *a, **kw: (calls.append(a), False)[1])
r = RS.run_shell("dir")
check("strict: dir prompted", len(calls) == 1)
check("strict: dir denied (we said no)", "user denied" in r)

# --- sandbox._request_access: safe mode без вызова hook ---
sandbox.set_approval_hook(lambda *a, **kw: (calls.append(a), True)[1])
calls.clear()
P.set_policy("safe")
ok = sandbox._request_access("C:/Windows/x", "test")
check("sandbox safe: denied", ok is False)
check("sandbox safe: hook not called", len(calls) == 0)

sandbox.set_approval_hook(None)
restore()

print(f"passed {passed}/{passed + len(results)}")
if results:
    print("FAILURES:")
    for r in results:
        print("  -", r)
    sys.exit(1)
print("ALL OK")
