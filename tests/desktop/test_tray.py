"""
Unit tests for ``netconfig_desktop.tray``.

pystray and Pillow are mocked so these run without a display or OS tray service.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from netconfig_desktop.tray import TrayIcon

pytestmark = pytest.mark.desktop


@pytest.fixture()
def patched_tray(mock_pystray, mock_generate_tray_image):
    """Return a TrayIcon with pystray and Pillow fully mocked.

    The tray is constructed with all four callbacks (Show, Preferences,
    Open configs folder, Quit) so the menu has its full surface.  Tests
    that need the legacy two-item shape can call the constructor
    directly with only ``on_show`` + ``on_quit``.
    """
    on_show = MagicMock(name="on_show")
    on_quit = MagicMock(name="on_quit")
    on_preferences = MagicMock(name="on_preferences")
    on_open_configs = MagicMock(name="on_open_configs")
    tray = TrayIcon(
        on_show=on_show,
        on_quit=on_quit,
        on_preferences=on_preferences,
        on_open_configs=on_open_configs,
        tooltip="Test",
    )
    return tray, on_show, on_preferences, on_open_configs, on_quit, mock_pystray


class TestTrayIconConstruction:
    def test_icon_created(self, patched_tray):
        tray, *_, mock_pystray = patched_tray
        mock_pystray.Icon.assert_called_once()

    def test_menu_has_four_items(self, patched_tray):
        *_, mock_pystray = patched_tray
        # Menu was called once with four MenuItem calls (Show,
        # Preferences, Open configs folder, Quit)
        assert mock_pystray.Menu.call_count == 1
        assert mock_pystray.MenuItem.call_count == 4

    def test_show_is_default_menu_item(self, patched_tray):
        *_, mock_pystray = patched_tray
        # First MenuItem call should have default=True
        first_call_kwargs = mock_pystray.MenuItem.call_args_list[0]
        assert first_call_kwargs.kwargs.get("default") is True

    def test_menu_item_labels(self, patched_tray):
        *_, mock_pystray = patched_tray
        labels = [
            call.args[0] for call in mock_pystray.MenuItem.call_args_list
        ]
        assert labels == [
            "Show",
            "Preferences…",  # ellipsis
            "Open configs folder",
            "Quit",
        ]

    def test_tooltip_passed_to_icon(self, patched_tray):
        tray, *_, mock_pystray = patched_tray
        _, kwargs = mock_pystray.Icon.call_args
        assert kwargs.get("title") == "Test"


class TestTrayIconBackwardCompat:
    """Constructing TrayIcon without the new callbacks must still work
    and produce a two-item menu."""

    def test_two_callback_construction_yields_two_item_menu(
        self, mock_pystray, mock_generate_tray_image
    ):
        TrayIcon(on_show=MagicMock(), on_quit=MagicMock())
        # Menu has only Show + Quit when prefs callbacks are absent
        assert mock_pystray.MenuItem.call_count == 2


class TestTrayIconRunDetached:
    def test_run_detached_calls_icon(self, patched_tray):
        tray, *_, mock_pystray = patched_tray
        fake_icon = mock_pystray.Icon.return_value
        tray.run_detached()
        fake_icon.run_detached.assert_called_once()


class TestTrayIconStop:
    def test_stop_calls_icon_stop(self, patched_tray):
        tray, *_, mock_pystray = patched_tray
        fake_icon = mock_pystray.Icon.return_value
        tray.stop()
        fake_icon.stop.assert_called_once()

    def test_stop_swallows_exceptions(self, patched_tray):
        tray, *_, mock_pystray = patched_tray
        fake_icon = mock_pystray.Icon.return_value
        fake_icon.stop.side_effect = RuntimeError("already stopped")
        # Should not raise
        tray.stop()


class TestTrayMenuCallbacks:
    """Each menu item's callback wires through to the right caller-supplied
    function.  The MenuItem call list is now 4 items: Show, Preferences,
    Open configs folder, Quit (in that order)."""

    def test_show_callback_invokes_on_show(self, patched_tray):
        _, on_show, on_preferences, on_open_configs, on_quit, mock_pystray = (
            patched_tray
        )
        show_callback = mock_pystray.MenuItem.call_args_list[0].args[1]
        show_callback(MagicMock(), MagicMock())
        on_show.assert_called_once()

    def test_preferences_callback_invokes_on_preferences(self, patched_tray):
        _, on_show, on_preferences, on_open_configs, on_quit, mock_pystray = (
            patched_tray
        )
        cb = mock_pystray.MenuItem.call_args_list[1].args[1]
        cb(MagicMock(), MagicMock())
        on_preferences.assert_called_once()

    def test_open_configs_callback_invokes_on_open_configs(self, patched_tray):
        _, on_show, on_preferences, on_open_configs, on_quit, mock_pystray = (
            patched_tray
        )
        cb = mock_pystray.MenuItem.call_args_list[2].args[1]
        cb(MagicMock(), MagicMock())
        on_open_configs.assert_called_once()

    def test_quit_callback_invokes_on_quit(self, patched_tray):
        _, on_show, on_preferences, on_open_configs, on_quit, mock_pystray = (
            patched_tray
        )
        quit_callback = mock_pystray.MenuItem.call_args_list[3].args[1]
        quit_callback(MagicMock(), MagicMock())
        on_quit.assert_called_once()
