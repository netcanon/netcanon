"""
Embedded Uvicorn server running in a daemon thread.

The ``ServerThread`` class starts the FastAPI application on the loopback
interface and exposes a ``wait_ready()`` method that blocks until the HTTP
server is accepting connections (or until a timeout elapses).

Design notes:

* ``_ReadyServer`` overrides ``uvicorn.Server.startup()`` to set a
  ``threading.Event`` *after* the socket is bound and the server loop is
  ready, giving a reliable readiness signal without polling.
* The thread is started as a **daemon** so it is automatically killed when
  the main thread (``webview.start()``) exits.
* ``stop()`` sets ``server.should_exit = True``; Uvicorn's internal loop
  picks this up and performs a clean shutdown (draining in-flight requests).
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import uvicorn

if TYPE_CHECKING:
    from starlette.applications import Starlette


class _ReadyServer(uvicorn.Server):
    """Uvicorn Server subclass that signals a threading.Event on startup."""

    def __init__(self, config: uvicorn.Config, ready_event: threading.Event) -> None:
        super().__init__(config)
        self._ready_event = ready_event

    async def startup(self, sockets=None) -> None:  # type: ignore[override]
        await super().startup(sockets=sockets)
        # Set the event *after* the socket is bound and the lifespan has
        # started — at this point the server will accept HTTP connections.
        self._ready_event.set()


class ServerThread(threading.Thread):
    """Daemon thread that runs the embedded Uvicorn HTTP server.

    Args:
        app: The ASGI application (FastAPI instance) to serve.
        host: IP address to bind (default ``"127.0.0.1"``).
        port: TCP port to listen on (default ``8765``).
        log_level: Uvicorn log level string (default ``"warning"``).

    Example::

        server = ServerThread(app, port=8765)
        server.start()
        server.wait_ready()          # blocks until HTTP is up
        ...
        server.stop()
    """

    def __init__(
        self,
        app: "Starlette",
        host: str = "127.0.0.1",
        port: int = 8765,
        log_level: str = "warning",
    ) -> None:
        super().__init__(name="netconfig-uvicorn", daemon=True)
        self._ready = threading.Event()
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level=log_level,
            # Disable signal handlers — the main thread owns signal handling.
            # Without this, uvicorn's SIGINT/SIGTERM handlers conflict with
            # pywebview's own signal management on Windows.
            use_colors=False,
            loop="asyncio",
        )
        self._server = _ReadyServer(config, self._ready)
        self._host = host
        self._port = port

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def url(self) -> str:
        """Base URL of the embedded server, e.g. ``http://127.0.0.1:8765``."""
        return f"http://{self._host}:{self._port}"

    def wait_ready(self, timeout: float = 15.0) -> None:
        """Block until the server is accepting connections.

        Waits for the internal readiness event set by ``_ReadyServer.startup``
        and then does a single HTTP probe to confirm the socket is truly
        reachable from the application layer.

        Args:
            timeout: Maximum seconds to wait before raising ``RuntimeError``.

        Raises:
            RuntimeError: If the server does not become ready within *timeout*
                seconds.
        """
        if not self._ready.wait(timeout):
            raise RuntimeError(
                f"Embedded server did not start within {timeout}s. "
                "Check that port {self._port} is not already in use."
            )
        # Brief poll to confirm the socket is reachable at the HTTP layer.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                import urllib.request

                urllib.request.urlopen(self.url, timeout=1)  # noqa: S310
                return
            except Exception:
                time.sleep(0.05)
        # If we reach here the socket event fired but the HTTP layer is not
        # responding — surface a clear error rather than silently opening a
        # blank WebView window.
        raise RuntimeError(
            f"Embedded server at {self.url} is not responding to HTTP "
            "requests after the readiness event was set."
        )

    def stop(self) -> None:
        """Request a clean Uvicorn shutdown.

        Sets ``server.should_exit = True``, which causes Uvicorn's event loop
        to finish in-flight requests and exit.  The daemon thread will then
        terminate naturally.
        """
        self._server.should_exit = True

    # ------------------------------------------------------------------
    # threading.Thread interface
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Run the Uvicorn event loop (called by ``threading.Thread.start``)."""
        self._server.run()
