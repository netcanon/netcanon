"""
pywebview window wrapper.

``WebViewWindow`` encapsulates the ``webview.Window`` object and the
``webview.create_window()`` / ``webview.start()`` lifecycle.

Key behaviours:

* **Minimize-to-tray on close** — the ``events.closing`` handler returns
  ``True`` (which cancels the default close action) and calls ``window.hide()``
  instead.  The window is only actually destroyed when ``destroy()`` is called
  explicitly (e.g. from the Quit menu item).
* **Thread-safe show/hide** — ``webview.Window.show()`` and ``hide()`` are
  thread-safe in pywebview 5.x and can be called from the pystray background
  thread.
* **Blocking ``start()``** — ``webview.start()`` blocks the calling thread
  until the window is destroyed.  ``DesktopApp.run()`` calls this on the main
  thread.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import webview as _webview_type


class WebViewWindow:
    """Embedded Edge/WebView2 window for the NetConfig web UI.

    Args:
        url: The URL to load on startup (e.g. ``"http://127.0.0.1:8765"``).
        title: Window title bar text.
        width: Initial window width in pixels.
        height: Initial window height in pixels.
        on_closed: Optional callback invoked when the window is *actually*
            destroyed (not merely hidden).  Used by ``DesktopApp`` to perform
            final cleanup.

    Example::

        win = WebViewWindow("http://127.0.0.1:8765", on_closed=server.stop)
        win.create()
        win.start()       # blocks until destroy() is called
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
        self._window: "_webview_type.Window | None" = None
        self._destroying = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def create(self) -> None:
        """Create the webview window object (does not start the event loop).

        Must be called before ``start()``.  Registers the ``closing`` event
        handler that implements minimize-to-tray behaviour.
        """
        import webview  # lazy import so the module loads without pywebview installed

        self._window = webview.create_window(
            title=self._title,
            url=self._url,
            width=self._width,
            height=self._height,
            resizable=True,
            text_select=False,
            confirm_close=False,
        )
        # Intercept the window-close button: hide instead of destroy.
        self._window.events.closing += self._on_closing

    def start(self) -> None:
        """Start the pywebview event loop (blocks until the window is destroyed).

        ``webview.start()`` must be called from the **main thread**.

        Args:
            None

        Returns:
            None — this method blocks until ``destroy()`` is called.
        """
        if self._window is None:
            raise RuntimeError("create() must be called before start()")

        import webview  # lazy import (see create())

        from netconfig_desktop.icons import write_ico

        ico_path = write_ico()
        webview.start(icon=str(ico_path), debug=False)

        # The event loop has exited — fire the on_closed callback if provided.
        if self._on_closed is not None:
            try:
                self._on_closed()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Thread-safe window operations (called from pystray thread)
    # ------------------------------------------------------------------

    def show(self) -> None:
        """Restore and bring the window to the foreground."""
        if self._window is not None:
            self._window.show()

    def hide(self) -> None:
        """Hide the window without destroying it (minimize to tray)."""
        if self._window is not None:
            self._window.hide()

    def destroy(self) -> None:
        """Destroy the window, causing ``start()`` to unblock and return.

        Sets a flag so the ``_on_closing`` handler does not intercept the
        programmatic destroy (which would loop back into hide-to-tray).
        """
        self._destroying = True
        if self._window is not None:
            self._window.destroy()

    # ------------------------------------------------------------------
    # Internal event handlers
    # ------------------------------------------------------------------

    def _on_closing(self) -> bool:
        """Handle the window-close button.

        Returns:
            ``True`` to **cancel** the default close action (pywebview
            interprets a truthy return value as "abort the close"), after
            hiding the window to the system tray.
            ``False`` (implicitly, when ``_destroying`` is set) to allow the
            destroy to proceed normally.
        """
        if self._destroying:
            # Programmatic destroy — let it proceed.
            return False  # type: ignore[return-value]
        # User clicked the ✕ button — hide to tray instead.
        self.hide()
        return True  # type: ignore[return-value]
