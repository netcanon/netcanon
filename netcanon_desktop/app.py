"""
``DesktopApp`` — top-level orchestrator for the Netcanon desktop application.

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

import logging
import os

from netcanon.main import create_app
from netcanon_desktop.server import ServerThread
from netcanon_desktop.settings import _preferences_path, desktop_settings
from netcanon_desktop.tray import TrayIcon
from netcanon_desktop.window import WebViewWindow

logger = logging.getLogger(__name__)


class DesktopApp:
    """Orchestrates the server, tray icon, and WebView window.

    Example::

        app = DesktopApp()
        app.run()   # blocks until Quit
    """

    def __init__(self) -> None:
        settings = desktop_settings()
        self._settings = settings

        asgi_app = create_app(settings)

        self._server = ServerThread(
            app=asgi_app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level,
        )
        self._window = WebViewWindow(
            url=self._server.url,
            title="Netcanon",
            on_closed=self._on_window_closed,
        )
        self._tray = TrayIcon(
            on_show=self._window.show,
            on_quit=self._quit,
            on_preferences=self._show_preferences,
            on_open_configs=self._open_configs_folder,
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
        logger.info("Netcanon desktop starting")

        # 1. Start the embedded HTTP server in a daemon thread.
        self._server.start()

        # 2. Wait until the server is accepting connections.
        #    Raises RuntimeError if it doesn't start within the timeout.
        self._server.wait_ready()
        logger.info("Embedded server ready at %s", self._server.url)

        # 3. Start the system-tray icon in its own thread (non-blocking).
        self._tray.run_detached()

        # 4. Create the WebView2 window and register event handlers.
        self._window.create()

        # 5. Start the pywebview event loop — BLOCKS until destroy() is called.
        self._window.start()
        logger.info("Netcanon desktop exited cleanly")

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _quit(self) -> None:
        """Called when the user selects *Quit* from the tray menu."""
        logger.info("Quit requested — stopping tray, server, and window")
        self._tray.stop()
        self._server.stop()
        self._window.destroy()

    def _on_window_closed(self) -> None:
        """Called after the WebView2 event loop exits (window destroyed).

        Ensures the tray icon and server are cleaned up even if the window
        was destroyed through a mechanism other than the Quit menu item
        (e.g. programmatic destroy in tests, or OS session logout).
        """
        logger.info("Window closed — stopping tray and server")
        self._tray.stop()
        self._server.stop()

    def _show_preferences(self) -> None:
        """Open the Preferences dialog, marshalling onto the Qt GUI thread.

        This is wired as the tray ``on_preferences`` callback, so it fires
        on **pystray's background thread**.  The dialog is a ``QWidget`` and
        Qt forbids constructing or ``exec``-ing widgets off the GUI thread
        (cross-thread UB / hard crash).  When we detect we're not on the GUI
        thread we post the work to the GUI thread's event loop via
        ``QMetaObject.invokeMethod`` (the same marshalling ``window.py`` uses
        for ``show`` / ``hide`` / ``quit``); the call returns immediately and
        the modal dialog runs on the GUI thread, keeping the tray responsive.
        On the GUI thread already (or with no ``QApplication`` yet, e.g. unit
        tests) we run inline.
        """
        from PySide6.QtCore import QMetaObject, Qt, QThread
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None and app.thread() is not QThread.currentThread():
            QMetaObject.invokeMethod(
                app,
                self._open_preferences_dialog,
                Qt.ConnectionType.QueuedConnection,
            )
        else:
            self._open_preferences_dialog()

    def _open_preferences_dialog(self) -> None:
        """Construct + exec the Preferences dialog (modal, blocks until
        closed).  MUST run on the Qt GUI thread — ``_show_preferences``
        marshals here when invoked from the pystray background thread.
        """
        from netcanon_desktop.preferences import DesktopPreferences
        from netcanon_desktop.preferences_dialog import PreferencesDialog

        prefs_path = _preferences_path()
        prefs = DesktopPreferences.load(prefs_path)
        dialog = PreferencesDialog(
            prefs=prefs,
            prefs_path=prefs_path,
            configs_dir_default=self._settings.configs_dir,
        )
        dialog.create()
        dialog.exec()

    def _open_configs_folder(self) -> None:
        """Open the configs directory in the OS file explorer."""
        try:
            os.startfile(str(self._settings.configs_dir))  # type: ignore[attr-defined]
        except Exception:
            logger.debug(
                "os.startfile failed for configs_dir=%s",
                self._settings.configs_dir,
                exc_info=True,
            )
