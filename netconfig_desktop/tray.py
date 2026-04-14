"""
System tray icon with Show and Quit actions.

``TrayIcon`` wraps ``pystray.Icon`` and exposes a simple three-method API:

* ``run_detached()`` — starts the tray icon in a background thread (non-blocking).
* ``stop()`` — removes the tray icon and stops the pystray loop.
* Callbacks ``on_show`` and ``on_quit`` are callables supplied by the caller
  (typically ``DesktopApp``) so this module stays decoupled from pywebview.

The pystray icon image is generated at runtime by ``netconfig_desktop.icons``
using Pillow — no binary assets are required.
"""
from __future__ import annotations

from typing import Callable

import pystray

from netconfig_desktop.icons import generate_tray_image


class TrayIcon:
    """System-tray icon with *Show* and *Quit* menu items.

    Args:
        on_show: Callback invoked when the user clicks *Show*.
        on_quit: Callback invoked when the user clicks *Quit*.
        tooltip: Text shown when the user hovers over the tray icon.

    Example::

        tray = TrayIcon(on_show=window.show, on_quit=app.quit)
        tray.run_detached()
        # ... later ...
        tray.stop()
    """

    def __init__(
        self,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
        tooltip: str = "NetConfig",
    ) -> None:
        self._on_show = on_show
        self._on_quit = on_quit

        image = generate_tray_image(size=64)

        menu = pystray.Menu(
            pystray.MenuItem("Show", self._handle_show, default=True),
            pystray.MenuItem("Quit", self._handle_quit),
        )

        self._icon = pystray.Icon(
            name="netconfig",
            icon=image,
            title=tooltip,
            menu=menu,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_detached(self) -> None:
        """Start the tray icon in a background thread (non-blocking).

        ``pystray.Icon.run_detached()`` spawns its own OS thread and returns
        immediately, leaving the tray icon active until ``stop()`` is called.
        """
        self._icon.run_detached()

    def stop(self) -> None:
        """Remove the tray icon and stop the pystray event loop."""
        try:
            self._icon.stop()
        except Exception:  # noqa: BLE001
            # pystray may raise if the icon was never started or already
            # stopped — swallow silently so shutdown is always clean.
            pass

    # ------------------------------------------------------------------
    # Internal menu callbacks
    # ------------------------------------------------------------------

    def _handle_show(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:  # noqa: ARG002
        self._on_show()

    def _handle_quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:  # noqa: ARG002
        self._on_quit()
