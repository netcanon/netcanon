"""
PySide6/QtWebEngine window wrapper.

``WebViewWindow`` encapsulates a ``QMainWindow`` with an embedded
``QWebEngineView`` and exposes the same API used by ``DesktopApp``:
``create()``, ``start()``, ``show()``, ``hide()``, ``destroy()``.

Key behaviours:

* **Minimize-to-tray on close** — ``closeEvent`` hides the window and
  ignores the Qt close, so the window disappears to the tray.  The window
  is only actually destroyed when ``destroy()`` is called explicitly (e.g.
  from the Quit menu item).
* **Thread-safe show/hide** — calls are posted via ``QMetaObject.invokeMethod``
  so pystray's background thread can call ``show()`` / ``hide()`` safely.
* **Blocking ``start()``** — ``QApplication.exec()`` blocks until
  ``destroy()`` posts ``QApplication.quit()``.

Why PySide6 instead of pywebview:
    pywebview ≥ 4.x requires ``pythonnet`` on Windows for its WebView2
    backend, which has no pre-built wheel for Python ≥ 3.13 and fails to
    compile without a .NET SDK.  PySide6 ships its own Chromium-based
    WebEngine with pre-built wheels for Python 3.14.
"""
from __future__ import annotations

import logging
import sys
from typing import Callable

logger = logging.getLogger(__name__)


class WebViewWindow:
    """PySide6 + QtWebEngine window for the NetConfig web UI.

    Args:
        url: The URL to load on startup (e.g. ``"http://127.0.0.1:8765"``).
        title: Window title bar text.
        width: Initial window width in pixels.
        height: Initial window height in pixels.
        on_closed: Optional callback invoked after ``QApplication.exec()``
            returns (i.e. after the event loop exits).

    Example::

        win = WebViewWindow("http://127.0.0.1:8765", on_closed=server.stop)
        win.create()
        win.start()   # blocks until destroy() is called
    """

    def __init__(
        self,
        url: str,
        title: str = "NetConfig",
        width: int = 1280,
        height: int = 800,
        on_closed: Callable[[], None] | None = None,
    ) -> None:
        self._url = url
        self._title = title
        self._width = width
        self._height = height
        self._on_closed = on_closed
        # Set after create(); _win is a QMainWindow subclass instance.
        self._app = None
        self._win = None   # QMainWindow subclass instance
        self._destroying = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def create(self) -> None:
        """Create the Qt application and main window (does not start the loop).

        All PySide6 imports happen here so the module is importable even
        when PySide6 is not installed (e.g. in unit tests that mock this).

        Must be called before ``start()``.
        """
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QIcon
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWidgets import QApplication, QMainWindow

        from netconfig_desktop.icons import write_ico

        # QApplication must be created before any widgets.
        self._app = QApplication.instance() or QApplication(sys.argv)
        ico_path = write_ico()
        self._app.setWindowIcon(QIcon(str(ico_path)))

        # Define the QMainWindow subclass here so it closes over
        # self._destroying without needing module-level Qt imports.
        handle_close = self._handle_close

        class _Win(QMainWindow):
            def closeEvent(self, event):  # noqa: N805
                handle_close(event)

        win = _Win()
        win.setWindowTitle(self._title)
        win.resize(self._width, self._height)

        view = QWebEngineView()
        view.load(QUrl(self._url))
        win.setCentralWidget(view)

        self._win = win
        logger.info("WebView window created (%dx%d) → %s", self._width, self._height, self._url)

    def start(self) -> None:
        """Start the Qt event loop (blocks until ``destroy()`` is called).

        Must be called from the **main thread**.

        Raises:
            RuntimeError: If ``create()`` has not been called first.
        """
        if self._app is None or self._win is None:
            raise RuntimeError("create() must be called before start()")

        logger.info("Starting Qt event loop")
        self._win.show()
        self._app.exec()
        logger.info("Qt event loop exited")

        if self._on_closed is not None:
            try:
                self._on_closed()
            except Exception:  # noqa: BLE001
                logger.debug("on_closed callback raised during shutdown", exc_info=True)

    # ------------------------------------------------------------------
    # Thread-safe window operations (called from pystray thread)
    # ------------------------------------------------------------------

    def show(self) -> None:
        """Restore and bring the window to the foreground."""
        if self._win is None:
            return
        logger.debug("Window show requested")
        from PySide6.QtCore import QMetaObject, Qt

        QMetaObject.invokeMethod(self._win, "show", Qt.ConnectionType.QueuedConnection)
        QMetaObject.invokeMethod(self._win, "raise_", Qt.ConnectionType.QueuedConnection)
        QMetaObject.invokeMethod(
            self._win, "activateWindow", Qt.ConnectionType.QueuedConnection
        )

    def hide(self) -> None:
        """Hide the window without destroying it (minimize to tray)."""
        if self._win is None:
            return
        logger.debug("Window hide requested (minimize to tray)")
        from PySide6.QtCore import QMetaObject, Qt

        QMetaObject.invokeMethod(self._win, "hide", Qt.ConnectionType.QueuedConnection)

    def destroy(self) -> None:
        """Quit the Qt event loop, causing ``start()`` to return."""
        logger.debug("Window destroy requested")
        self._destroying = True
        if self._app is None:
            return
        from PySide6.QtCore import QMetaObject, Qt

        QMetaObject.invokeMethod(self._app, "quit", Qt.ConnectionType.QueuedConnection)

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _handle_close(self, event) -> None:
        """Handle a Qt ``closeEvent`` from the main window.

        Exposed as a named method (rather than a closure) so it is testable
        without requiring a real Qt QMainWindow subclass instance.

        Args:
            event: The Qt ``QCloseEvent``.  ``event.ignore()`` cancels the
                close; ``event.accept()`` allows it.
        """
        if self._destroying:
            event.accept()
        else:
            event.ignore()
            self.hide()
