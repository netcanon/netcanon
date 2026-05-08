"""
Unit tests for ``netcanon_desktop.server``.

Uses a real (but tiny) ASGI app running on a free port so we can verify the
readiness polling without mocking Uvicorn internals.
"""
from __future__ import annotations

import socket
import time

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from netcanon_desktop.server import ServerThread

pytestmark = pytest.mark.desktop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _minimal_app() -> Starlette:
    async def health(request):
        return PlainTextResponse("ok")

    return Starlette(routes=[Route("/", health)])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestServerThread:
    def test_server_starts_and_responds(self):
        port = _free_port()
        app = _minimal_app()
        server = ServerThread(app, port=port, log_level="critical")
        server.start()
        try:
            server.wait_ready(timeout=10.0)
            import urllib.request

            body = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3).read()
            assert body == b"ok"
        finally:
            server.stop()

    def test_url_property(self):
        port = _free_port()
        app = _minimal_app()
        server = ServerThread(app, host="127.0.0.1", port=port)
        assert server.url == f"http://127.0.0.1:{port}"

    def test_wait_ready_timeout_raises(self):
        """wait_ready should raise RuntimeError if the event is never set."""
        port = _free_port()
        app = _minimal_app()
        server = ServerThread(app, port=port)
        # Do NOT call server.start() — the ready event will never be set.
        with pytest.raises(RuntimeError, match="did not start"):
            server.wait_ready(timeout=0.1)

    def test_thread_is_daemon(self):
        port = _free_port()
        app = _minimal_app()
        server = ServerThread(app, port=port)
        assert server.daemon is True

    def test_stop_signals_server(self):
        port = _free_port()
        app = _minimal_app()
        server = ServerThread(app, port=port, log_level="critical")
        server.start()
        server.wait_ready(timeout=10.0)
        server.stop()
        # Give Uvicorn a moment to honour the exit flag
        server.join(timeout=5.0)
        assert not server.is_alive()
