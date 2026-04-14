"""
Unit tests for ``netconfig_desktop.tray``.

pystray and Pillow are mocked so these run without a display or OS tray service.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from netconfig_desktop.tray import TrayIcon


@pytest.fixture()
def patched_tray(mock_pystray, mock_generate_tray_image):
    """Return a TrayIcon with pystray and Pillow fully mocked."""
    on_show = MagicMock(name="on_show")
    on_quit = MagicMock(name="on_quit")
    tray = TrayIcon(on_show=on_show, on_quit=on_quit, tooltip="Test")
    return tray, on_show, on_quit, mock_pystray


class TestTrayIconConstruction:
    def test_icon_created(self, patched_tray):
        tray, _, _, mock_pystray = patched_tray
        mock_pystray.Icon.assert_called_once()

    def test_menu_has_two_items(self, patched_tray):
        _, _, _, mock_pystray = patched_tray
        # Menu was called with two MenuItem calls
        assert mock_pystray.Menu.call_count == 1
        assert mock_pystray.MenuItem.call_count == 2

    def test_show_is_default_menu_item(self, patched_tray):
        _, _, _, mock_pystray = patched_tray
        # First MenuItem call should have default=True
        first_call_kwargs = mock_pystray.MenuItem.call_args_list[0]
        assert first_call_kwargs.kwargs.get("default") is True

    def test_tooltip_passed_to_icon(self, patched_tray):
        tray, _, _, mock_pystray = patched_tray
        _, kwargs = mock_pystray.Icon.call_args
        assert kwargs.get("title") == "Test"


class TestTrayIconRunDetached:
    def test_run_detached_calls_icon(self, patched_tray):
        tray, _, _, mock_pystray = patched_tray
        fake_icon = mock_pystray.Icon.return_value
        tray.run_detached()
        fake_icon.run_detached.assert_called_once()


class TestTrayIconStop:
    def test_stop_calls_icon_stop(self, patched_tray):
        tray, _, _, mock_pystray = patched_tray
        fake_icon = mock_pystray.Icon.return_value
        tray.stop()
        fake_icon.stop.assert_called_once()

    def test_stop_swallows_exceptions(self, patched_tray):
        tray, _, _, mock_pystray = patched_tray
        fake_icon = mock_pystray.Icon.return_value
        fake_icon.stop.side_effect = RuntimeError("already stopped")
        # Should not raise
        tray.stop()


class TestTrayMenuCallbacks:
    def test_show_callback_invokes_on_show(self, patched_tray):
        tray, on_show, on_quit, mock_pystray = patched_tray
        # Extract the callback passed to the first MenuItem (Show)
        show_callback = mock_pystray.MenuItem.call_args_list[0].args[1]
        show_callback(MagicMock(), MagicMock())
        on_show.assert_called_once()

    def test_quit_callback_invokes_on_quit(self, patched_tray):
        tray, on_show, on_quit, mock_pystray = patched_tray
        quit_callback = mock_pystray.MenuItem.call_args_list[1].args[1]
        quit_callback(MagicMock(), MagicMock())
        on_quit.assert_called_once()
