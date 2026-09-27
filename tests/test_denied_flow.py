"""интеграционный тест: ApprovalDenied -> executor -> result с 'user denied'.

Не требует ни Textual, ни реальной ФС: подменяем approval hook
на отказ и прогоняем тул, который ходит по абсолютному пути.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import sandbox
from core.logger import Logger
from core.registries import Registry
from execution.executor import execute_one


def _deny(path, mode, reason=""):
    return False


async def main() -> int:
    sandbox.set_approval_hook(_deny)

    reg = Registry()
    reg.add("read_file", "read a file",
            lambda path: open(path, encoding="utf-8").read())  # noqa: SIM115

    import tempfile
    log = Logger(Path(tempfile.gettempdir()) / "mc_test_log.jsonl")
    call = {
        "raw": 'read_file: path:"C:/Windows/System32/drivers/etc/hosts"',
        "parsed": {
            "name": "read_file",
            "args": {"path": "C:/Windows/System32/drivers/etc/hosts"},
            "error": None,
        },
    }
    res, is_err, name = await execute_one(call, reg, log)
    sandbox.set_approval_hook(None)

    print("tool:", name, "is_err:", is_err)
    print("result:", res[:300])
    assert name == "read_file"
    assert is_err is True, "must be error"
    assert "user denied" in res, "must mention user denied"
    assert "Do NOT retry" in res, "must instruct not to retry"
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
