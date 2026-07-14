"""Direct unit test for the ``wait_for_job`` test helper (HEAD-review T9).

``wait_for_job`` (and the ``AutoWaitTestClient`` that calls it) is load-bearing
for every backups-tier test since #27 moved dispatch off FastAPI
``BackgroundTasks`` — yet its correctness was only ever inferred from downstream
side-effect asserts.  Pin it directly: it must poll until terminal and return
that body, and it must raise ``AssertionError`` (not hang) on a job that never
terminalises.
"""

from __future__ import annotations

import pytest

from tests.conftest import wait_for_job

pytestmark = pytest.mark.unit


class _Resp:
    def __init__(self, status_code: int, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict:
        return self._body


class _StubClient:
    """A ``.get(url)`` stub that returns a scripted sequence of responses,
    repeating the last one once the script is exhausted."""

    def __init__(self, responses: list[_Resp]) -> None:
        self._responses = responses
        self.calls = 0

    def get(self, _url: str) -> _Resp:
        resp = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return resp


def test_returns_terminal_body_after_polling():
    client = _StubClient([
        _Resp(200, {"status": "pending"}),
        _Resp(200, {"status": "running"}),
        _Resp(200, {"status": "completed", "id": "abc"}),
    ])
    body = wait_for_job(client, "abc", timeout=1.0, poll=0.0)
    assert body["status"] == "completed"
    assert client.calls == 3  # polled until terminal, then returned


def test_raises_on_never_terminal_job():
    client = _StubClient([_Resp(200, {"status": "pending"})])  # never terminalises
    with pytest.raises(AssertionError, match="did not reach a terminal state"):
        wait_for_job(client, "stuck", timeout=0.05, poll=0.0)


def test_404_before_terminal_is_tolerated_then_heals():
    # A brief 404 (e.g. the corrupt-file / eviction window) must not crash the
    # poll — it keeps trying until the terminal 200 lands.
    client = _StubClient([
        _Resp(404),
        _Resp(200, {"status": "running"}),
        _Resp(200, {"status": "failed", "id": "z"}),
    ])
    body = wait_for_job(client, "z", timeout=1.0, poll=0.0)
    assert body["status"] == "failed"
