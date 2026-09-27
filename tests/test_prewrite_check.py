"""pre-write syntax check: write_file / edit_file / core.verify."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.edit_file as E
import tools.write_file as W
from core import verify

results, passed = [], 0


def check(name, cond):
    global passed
    if cond:
        passed += 1
    else:
        results.append(name)


# --- check_source ---
check("check_source: valid", verify.check_source("x.py", "a=1") is None)
check("check_source: nonpy passthrough",
      verify.check_source("x.txt", "any (( ((") is None)
bad = verify.check_source("x.py", "def f(:\n  pass")
check("check_source: bad returns str", isinstance(bad, str))
check("check_source: bad has line", bad is not None and "line 1" in bad)
check("check_source: bad has caret", bad is not None and "^" in bad)

# --- write_file ---
td = Path(tempfile.mkdtemp(prefix="mc_test_pf_"))
bad_f = td / "bad.py"
r = W._run(str(bad_f), "def f(:\n  pass\n")
check("wf: bad refused", r.startswith("error: refusing to write"))
check("wf: bad file absent", not bad_f.exists())
check("wf: bad mentions unchanged", "UNCHANGED" in r)

good_f = td / "good.py"
r = W._run(str(good_f), "x = 1\n")
check("wf: good written", good_f.is_file() and good_f.read_text() == "x = 1\n")
check("wf: good ok prefix", r.startswith("ok: wrote"))
check("wf: good syntax ok suffix", "syntax: OK" in r)

txt_f = td / "a.txt"
r = W._run(str(txt_f), "not python (( ( fine")
check("wf: txt written", txt_f.is_file())

bin_f = td / "a.png"
r = W._run(str(bin_f), "not really a png")
check("wf: binary refused", r.startswith("error: refusing to write text"))
check("wf: binary not written", not bin_f.exists())

# --- edit_file ---
py_f = td / "e.py"
orig = "x = 1\ny = 2\n"
py_f.write_text(orig, encoding="utf-8")
r = E._run(str(py_f), "x = 1\n", "x = 1\ndef f(:\n")
check("ef: bad edit refused", r.startswith("error: refusing to apply edit"))
check("ef: file unchanged", py_f.read_text(encoding="utf-8") == orig)

r = E._run(str(py_f), "y = 2\n", "y = 42\n")
check("ef: good edit applied",
      py_f.read_text(encoding="utf-8") == "x = 1\ny = 42\n")
check("ef: good ok prefix", r.startswith("ok: replaced"))

# non-python: no syntax gate
txt2 = td / "t.txt"
txt2.write_text("foo\n", encoding="utf-8")
r = E._run(str(txt2), "foo", "bar ((")
check("ef: nonpy edit allowed", txt2.read_text(encoding="utf-8") == "bar ((\n")

print(f"passed {passed}/{passed + len(results)}")
if results:
    print("FAILURES:")
    for r_ in results:
        print("  -", r_)
    sys.exit(1)
print("ALL OK")
