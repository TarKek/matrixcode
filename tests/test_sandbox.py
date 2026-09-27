"""unit-тесты core.sandbox: ApprovalDenied, workspace/temp, guard_kwargs.

Эти тесты НЕ трогают реальную ФС (кроме tempdir): _tls.active управляем
вручную, hook подменяем на локальный.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import sandbox

results: list[str] = []
passed = 0


def check(name: str, cond: bool) -> None:
    global passed
    if cond:
        passed += 1
    else:
        results.append(name)


# --- is_in_workspace --------------------------------------------------
ws = sandbox.WORKSPACE_DIR
check("ws: itself", sandbox.is_in_workspace(ws))
check("ws: child", sandbox.is_in_workspace(ws / "a" / "b.txt"))
check("ws: parent escape",
      not sandbox.is_in_workspace(ws.parent / "x"))
check("ws: abs other", not sandbox.is_in_workspace("C:/Windows"))

# --- is_in_tempdir ----------------------------------------------------
td = Path(tempfile.gettempdir())
check("temp: itself", sandbox.is_in_tempdir(td))
check("temp: child", sandbox.is_in_tempdir(td / "x.txt"))

# --- ApprovalDenied is PermissionError --------------------------------
check("ApprovalDenied subclass",
      issubclass(sandbox.ApprovalDenied, PermissionError))

# --- _guard: deny path raises ApprovalDenied --------------------------
_hook_calls: list[tuple] = []

def deny_hook(path, mode, reason=""):
    _hook_calls.append((path, mode, reason))
    return False

sandbox.set_approval_hook(deny_hook)
sandbox._tls.active = True
raised = None
try:
    sandbox._guard("C:/Windows/System32/calc.exe", "open[r]")
except sandbox.ApprovalDenied as e:
    raised = e
except Exception as e:
    raised = e
sandbox._tls.active = False
check("deny: raised ApprovalDenied", isinstance(raised, sandbox.ApprovalDenied))
check("deny: hook was called", len(_hook_calls) == 1)
check("deny: message mentions retry",
      raised is not None and "retry" in str(raised).lower())

# --- _guard: allow path skips hook ------------------------------------
_hook_calls.clear()
def allow_hook(*a, **kw):
    _hook_calls.append(a)
    return True
sandbox.set_approval_hook(allow_hook)
sandbox._tls.active = True
sandbox._guard(str(ws / "ok.txt"), "open[r]")
sandbox._tls.active = False
check("allow: ws path skipped hook", len(_hook_calls) == 0)

# --- guard_kwargs: PATH_ARG_NAMES honored -----------------------------
_hook_calls.clear()
sandbox.set_approval_hook(deny_hook)
sandbox._tls.active = True
try:
    sandbox.guard_kwargs({"path": "C:/Windows/x", "n": 1,
                          "other": "C:/Windows/y"})
    gk_raised = False
except sandbox.ApprovalDenied:
    gk_raised = True
finally:
    sandbox._tls.active = False
check("guard_kwargs: path checked", gk_raised)
check("guard_kwargs: only path arg checked", len(_hook_calls) == 1)

# --- _guard inactive when _tls.active False ---------------------------
_hook_calls.clear()
sandbox.set_approval_hook(deny_hook)
try:
    sandbox._guard("C:/Windows/System32/calc.exe", "open[r]")
    inactive_ok = True
except Exception:
    inactive_ok = False
check("inactive: no guard", inactive_ok and len(_hook_calls) == 0)

# --- TTL constant present ---------------------------------------------
check("APPROVAL_TTL_SEC present", isinstance(sandbox.APPROVAL_TTL_SEC, int)
      and sandbox.APPROVAL_TTL_SEC > 0)

sandbox.set_approval_hook(None)

print(f"passed {passed}/{passed + len(results)}")
if results:
    print("FAILURES:")
    for r in results:
        print("  -", r)
    sys.exit(1)
print("ALL OK")
