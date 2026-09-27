"""тесты токенизации команд: _mask_quotes, _split_segments, _classify."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import run_shell as RS

results, passed = [], 0


def check(name, cond):
    global passed
    if cond:
        passed += 1
    else:
        results.append(name)


# --- mask_quotes ---
check("mask: single", RS._mask_quotes("echo 'a&&b'").count("&&") == 0)
check("mask: double", RS._mask_quotes('echo "x||y"').count("||") == 0)
check("mask: outside kept", "&&" in RS._mask_quotes("a && b"))
check("mask: same length",
      len(RS._mask_quotes("a 'b' c")) == len("a 'b' c"))

# --- split_segments ---
segs = RS._split_segments("a && b || c")
check("split: chaining tokens", "&&" in segs and "||" in segs)
check("split: three payloads",
      any(s.strip() == "a" for s in segs)
      and any(s.strip() == "b" for s in segs)
      and any(s.strip() == "c" for s in segs))
segs2 = RS._split_segments("echo 'x;y'")
check("split: semicolon in quotes untouched",
      ";" not in segs2)
segs3 = RS._split_segments("a;b|c&d")
check("split: all separators",
      [s for s in segs3 if s in (";", "|", "&")] == [";", "|", "&"])

# --- classify: quoting kills false positives ---
check("classify: quote kills chaining",
      RS._classify("echo 'a&&b'") is None)
check("classify: quote kills pipe-shell (not the pipe reason)",
      RS._classify("echo '|bash'") != "pipe to shell")

# --- classify: separators with different payloads ---
check("classify: del after semicolon",
      "delete files" in (RS._classify("echo x; del a.txt") or ""))
check("classify: pip after &&",
      "pip install" in (RS._classify("cd . && pip install x") or ""))
check("classify: git clone after ;",
      "git state-changing" in (RS._classify("echo a; git clone http://x") or ""))

# --- fallback chaining ---
check("classify: chain fallback",
      RS._classify("echo a && echo b") == "command chaining")
check("classify: || fallback",
      RS._classify("echo a || echo b") == "command chaining")

# --- pipe-to-shell specific ---
check("classify: pipe to bash",
      RS._classify("cat x | bash") == "pipe to shell")
check("classify: pipe to iex",
      RS._classify("cat x | iex") == "pipe to shell")
check("classify: plain pipe ok",
      RS._classify("dir | more") is None)
check("classify: pipe findstr ok",
      RS._classify("echo a | findstr foo") is None)

print(f"passed {passed}/{passed + len(results)}")
if results:
    print("FAILURES:")
    for r in results:
        print("  -", r)
    sys.exit(1)
print("ALL OK")
