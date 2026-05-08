"""
System tray icon with Show, Preferences, Open configs folder, and Quit
actions.

``TrayIcon`` wraps ``pystray.Icon`` and exposes a simple three-method API:

* ``run_detached()`` — starts the tray icon in a background thread (non-blocking).
* ``stop()`` — removes the tray icon and stops the pystray loop.
* Callbacks (``on_show``, ``on_preferences``, ``on_open_configs``, ``on_quit``)
  are callables supplied by the caller (typically ``DesktopApp``) so this
  module stays decoupled from pywebview.

The pystray icon image is generated at runtime by ``netconfig_desktop.icons``
using Pillow — no binary assets are required.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

import pystray

from netconfig_desktop.icons import generate_tray_image

logger = logging.getLogger(__name__)


class TrayIcon:
    """System-tray icon with *Show*, *Preferences*, *Open configs folder*,
    and *Quit* menu items.

    Args:
        on_show: Callback invoked when the user clicks *Show*.
        on_quit: Callback invoked when the user clicks *Quit*.
        on_preferences: Optional callback invoked when the user clicks
            *Preferences…*.  When ``None``, the menu item is omitted —
            this keeps tray construction backward-compatible for tests
            that haven't been updated.
        on_open_configs: Optional callback invoked when the user clicks
            *Open configs folder*.  When ``None``, the menu item is
            omitted (same backward-compat reasoning).
        tooltip: Text shown when the user hovers over the tray icon.

    Example::

        tray = TrayIcon(
            on_show=window.show,
            on_quit=app.quit,
            on_preferences=app.show_preferences,
            on_open_configs=app.open_configs,
        )
        tray.run_detached()
        # ... later ...
        tray.stop()
    """

    def __init__(
        self,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
        on_preferences: Optional[Callable[[], None]] = None,
        on_open_configs: Optional[Callable[[], None]] = None,
        tooltip: str = "Netcanon",
    ) -> None:
        self._on_show = on_show
        self._on_quit = on_quit
        self._on_preferences = on_preferences
        self._on_open_configs = on_open_configs

        image = generate_tray_image(size=64)

        menu_items = [pystray.MenuItem("Show", self._handle_show, default=True)]
        if on_preferences is not None:
            menu_items.append(
                pystray.MenuItem("Preferences…", self._handle_preferences)
            )
        if on_open_configs is not None:
            menu_items.append(
                pystray.MenuItem(
                    "Open configs folder", self._handle_open_configs
                )
            )
        menu_items.append(pystray.MenuItem("Quit", self._handle_quit))

        menu = pystray.Menu(*menu_items)

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
        logger.debug("Starting system-tray icon")
        self._icon.run_detached()

    def stop(self) -> None:
        """Remove the tray icon and stop the pystray event loop."""
        try:
            self._icon.stop()
        except Exception:  # noqa: BLE001
            # pystray may raise if the icon was never started or already
            # stopped — log at DEBUG so shutdown is always clean.
            logger.debug("pystray stop() raised during shutdown", exc_info=True)

    # ------------------------------------------------------------------
    # Internal menu callbacks
    # ------------------------------------------------------------------

    def _handle_show(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:  # noqa: ARG002
        logger.debug("User selected Show from tray menu")
        self._on_show()

    def _handle_quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:  # noqa: ARG002
        logger.info("User selected Quit from tray menu")
        self._on_quit()

    def _handle_preferences(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:  # noqa: ARG002
        logger.debug("User selected Preferences from tray menu")
        if self._on_preferences is not None:
            self._on_preferences()

    def _handle_open_configs(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:  # noqa: ARG002
        logger.debug("User selected Open configs folder from tray menu")
        if self._on_open_configs is not None:
            self._on_open_configs()
