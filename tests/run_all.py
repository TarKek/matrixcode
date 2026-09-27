"""запуск всех тестов одной командой: python tests/run_all.py.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = [
    "test_classify.py",
    "test_tokenize.py",
    "test_sandbox.py",
    "test_denied_flow.py",
    "test_approval_cache.py",
    "test_prewrite_check.py",
    "test_network_tools.py",
    "test_policy.py",
]

failed = 0
for name in TESTS:
    path = HERE / name
    print(f"=== {name} ===")
    r = subprocess.run([sys.executable, str(path)], text=True)
    if r.returncode != 0:
        failed += 1

print()
if failed:
    print(f"FAILED: {failed}/{len(TESTS)}")
    sys.exit(1)
print(f"ALL {len(TESTS)} FILES OK")
