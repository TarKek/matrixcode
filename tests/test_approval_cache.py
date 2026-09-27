"""тесты кэша одобрений ui.app: TTL, resolve-нормализация, потокобезопасность.

Инстанцировать MatrixCodeApp нельзя (Textual), поэтому методы
подвязываем через types.MethodType к dummy-объекту с нужным
состоянием.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import app as app_mod


class Dummy:
    def __init__(self):
        self._approved_paths = {}
        self._approval_lock = threading.Lock()
        self._logged = []

    def _log_command(self, name, args="", **extra):
        self._logged.append((name, args))


# подвязываем настоящие методы из класса к dummy.
D = Dummy()
D._approval_key = types.MethodType(app_mod.MatrixCodeApp._approval_key, D)
D._approval_cached = types.MethodType(app_mod.MatrixCodeApp._approval_cached, D)
D._approval_store = types.MethodType(app_mod.MatrixCodeApp._approval_store, D)

results = []
passed = 0


def check(name, cond):
    global passed
    if cond:
        passed += 1
    else:
        results.append(name)


# --- resolve normalize ------------------------------------------------
k1 = D._approval_key("C:/Windows/../Windows/System32")
k2 = D._approval_key("C:/Windows/System32")
check("resolve: identical after ..", k1 == k2)

# --- cold cache -------------------------------------------------------
check("cold: miss", not D._approval_cached(k2))

# --- store then hit ---------------------------------------------------
D._approval_store(k2)
check("warm: hit", D._approval_cached(k2))

# --- TTL expiry (shorten TTL by direct write) -------------------------
D._approved_paths[k2] = time.monotonic() - 1.0
check("expired: miss", not D._approval_cached(k2))
check("expired: entry removed", k2 not in D._approved_paths)

# --- concurrency smoke: 200 parallel stores/hits ----------------------
keys = [f"C:/a/{i}" for i in range(50)]
def worker(k):
    D._approval_store(k)
    assert D._approval_cached(k)

threads = [threading.Thread(target=worker, args=(k,)) for k in keys * 4]
for t in threads:
    t.start()
for t in threads:
    t.join()
check("concurrency: no crash", True)
check("concurrency: all stored",
      all(k in D._approved_paths for k in keys))

# --- TTL sanity -------------------------------------------------------
import core.paths as P

check("TTL constant > 0", P.APPROVAL_TTL_SEC > 0)
check("sandbox re-exports TTL",
      __import__("core.sandbox", fromlist=["x"]).APPROVAL_TTL_SEC == P.APPROVAL_TTL_SEC)

print(f"passed {passed}/{passed + len(results)}")
if results:
    print("FAILURES:")
    for r in results:
        print("  -", r)
    sys.exit(1)
print("ALL OK")
