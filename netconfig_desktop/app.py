"""
``DesktopApp`` — top-level orchestrator for the NetConfig desktop application.

Wires together the three runtime components:

1. ``ServerThread`` — embedded Uvicorn server on 127.0.0.1:8765 (daemon thread).
2. ``TrayIcon`` — system-tray icon with Show / Quit (pystray background thread).
3. ``WebViewWindow`` — Edge/WebView2 window (blocks the main thread).

Startup sequence::

    DesktopApp.run()
    ├── ServerThread.start()          # daemon thread
    ├── ServerThread.wait_ready()     # poll until HTTP is up
    ├── TrayIcon.run_detached()       # pystray background thread
    ├── WebViewWindow.create()        # register event handlers
    └── WebViewWindow.start()         # ← BLOCKS (main thread = WebView2 loop)

Shutdown sequence (Quit menu item)::

    TrayIcon on_quit callback
    ├── TrayIcon.stop()               # remove tray icon
    ├── ServerThread.stop()           # signal Uvicorn to exit
    └── WebViewWindow.destroy()       # unblocks webview.start()

Shutdown sequence (window ✕ button)::

    WebViewWindow._on_closing()
    └── WebViewWindow.hide()          # minimize to tray (does NOT stop app)
"""
from __future__ import annotations

from netconfig.main import create_app
from netconfig_desktop.server import ServerThread
from netconfig_desktop.settings import desktop_settings
from netconfig_desktop.tray import TrayIcon
from netconfig_desktop.window import WebViewWindow


class DesktopApp:
    """Orchestrates the server, tray icon, and WebView window.

    Example::

        app = DesktopApp()
        app.run()   # blocks until Quit
    """

    def __init__(self) -> None:
        settings = desktop_settings()

        asgi_app = create_app(settings)

        self._server = ServerThread(
            app=asgi_app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level,
        )
        self._window = WebViewWindow(
            url=self._server.url,
            title="NetConfig",
            on_closed=self._on_window_closed,
        )
        self._tray = TrayIcon(
            on_show=self._window.show,
            on_quit=self._quit,
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start all components and block until the user quits.

        This method must be called from the **main thread** because
        ``webview.start()`` (called inside ``WebViewWindow.start()``) requires
        the main thread on Windows.
        """
        # 1. Start the embedded HTTP server in a daemon thread.
        self._server.start()

        # 2. Wait until the server is accepting connections.
        #    Raises RuntimeError if it doesn't start within the timeout.
        self._server.wait_ready()

        # 3. Start the system-tray icon in its own thread (non-blocking).
        self._tray.run_detached()

        # 4. Create the WebView2 window and register event handlers.
        self._window.create()

        # 5. Start the pywebview event loop — BLOCKS until destroy() is called.
        self._window.start()

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _quit(self) -> None:
        """Called when the user selects *Quit* from the tray menu."""
        self._tray.stop()
        self._server.stop()
        self._window.destroy()

    def _on_window_closed(self) -> None:
        """Called after the WebView2 event loop exits (window destroyed).

        Ensures the tray icon and server are cleaned up even if the window
        was destroyed through a mechanism other than the Quit menu item
        (e.g. programmatic destroy in tests, or OS session logout).
        """
        self._tray.stop()
        self._server.stop()
