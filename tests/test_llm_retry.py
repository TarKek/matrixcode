"""тесты llm.client retry: _backoff, RETRY_COUNT, интеграция с mock httpx."""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from llm import client as C

results, passed = [], 0


def check(name, cond):
    global passed
    if cond:
        passed += 1
    else:
        results.append(name)


# --- backoff ---
check("backoff: grows", C._backoff(0) < C._backoff(3))
check("backoff: bounded", C._backoff(10) < 30)
check("backoff: retry-after respected", C._backoff(0, 2.0) == 2.0)
check("backoff: retry-after capped", C._backoff(0, 100.0) == 30.0)
check("backoff: jitter makes them differ (probabilistic)",
      len({C._backoff(0) for _ in range(50)}) > 1)

# --- reset + bump ---
C.reset_retry_count()
check("reset: zero", C.RETRY_COUNT == 0)
C._bump_retry()
C._bump_retry()
check("bump: 2", C.RETRY_COUNT == 2)
C.reset_retry_count()
check("reset: again zero", C.RETRY_COUNT == 0)

# --- integration: httpx mock returning 429 then 200 with a small stream ---
class FakeStream:
    def __init__(self, status_code, headers=None, body=b"data: [DONE]\n"):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("POST", "http://x")
            resp = httpx.Response(self.status_code,
                                  request=req, headers=self.headers)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=req, response=resp)

    async def aread(self):
        return self._body

    async def aiter_lines(self):
        for line in self._body.decode().splitlines():
            yield line


class FakeClient:
    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, *a, **kw):
        code = self._statuses[min(self.calls, len(self._statuses) - 1)]
        self.calls += 1
        return FakeStream(code)


async def test_retry():
    C.reset_retry_count()
    # 500, 500, 200  2 retry, успех.
    fake = FakeClient([500, 500, 200])
    with patch.object(C.httpx, "AsyncClient", return_value=fake):  # noqa: SIM117
        # ускорить  backoff без сна
        with patch.object(C.asyncio, "sleep",
                          new=lambda *a, **kw: asyncio.sleep(0)):
            _content, *_ = await C.chat_stream(
                [{"role": "user", "content": "hi"}], "m", use_grammar=False)
    check("retry: succeeded", _content == "")
    check("retry: count == 2", C.RETRY_COUNT == 2)


asyncio.run(test_retry())

print(f"passed {passed}/{passed + len(results)}")
if results:
    print("FAILURES:")
    for r in results:
        print("  -", r)
    sys.exit(1)
print("ALL OK")
