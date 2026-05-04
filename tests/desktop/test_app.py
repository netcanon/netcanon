"""
Unit tests for ``netconfig_desktop.app``.

All three subsystems (server, tray, window) are mocked so no real threads,
GUI, or HTTP server are created.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from netconfig_desktop.app import DesktopApp

pytestmark = pytest.mark.desktop


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_server():
    with patch("netconfig_desktop.app.ServerThread") as cls:
        instance = MagicMock(name="ServerThread")
        instance.url = "http://127.0.0.1:8765"
        cls.return_value = instance
        yield instance


@pytest.fixture()
def mock_tray():
    with patch("netconfig_desktop.app.TrayIcon") as cls:
        instance = MagicMock(name="TrayIcon")
        cls.return_value = instance
        yield instance


@pytest.fixture()
def mock_window():
    with patch("netconfig_desktop.app.WebViewWindow") as cls:
        instance = MagicMock(name="WebViewWindow")
        cls.return_value = instance
        yield instance


@pytest.fixture()
def mock_settings():
    settings = MagicMock(name="Settings")
    settings.host = "127.0.0.1"
    settings.port = 8765
    settings.log_level = "warning"
    with patch("netconfig_desktop.app.desktop_settings", return_value=settings):
        yield settings


@pytest.fixture()
def mock_create_app():
    with patch("netconfig_desktop.app.create_app") as mock_ca:
        mock_ca.return_value = MagicMock(name="FastAPI")
        yield mock_ca


@pytest.fixture()
def app(mock_server, mock_tray, mock_window, mock_settings, mock_create_app):
    """Return a DesktopApp with all subsystems mocked."""
    return DesktopApp()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDesktopAppConstruction:
    def test_server_created(self, app, mock_server, mock_settings):
        # ServerThread was constructed with the settings values
        from netconfig_desktop.app import ServerThread

        ServerThread.assert_called_once()

    def test_window_created_with_server_url(self, app, mock_window, mock_server):
        from netconfig_desktop.app import WebViewWindow

        _, kwargs = WebViewWindow.call_args
        assert kwargs.get("url") == "http://127.0.0.1:8765"

    def test_tray_created(self, app, mock_tray):
        from netconfig_desktop.app import TrayIcon

        TrayIcon.assert_called_once()


class TestDesktopAppRun:
    def test_run_starts_server(self, app, mock_server):
        app.run()
        mock_server.start.assert_called_once()

    def test_run_waits_for_ready(self, app, mock_server):
        app.run()
        mock_server.wait_ready.assert_called_once()

    def test_run_detaches_tray(self, app, mock_tray):
        app.run()
        mock_tray.run_detached.assert_called_once()

    def test_run_creates_window(self, app, mock_window):
        app.run()
        mock_window.create.assert_called_once()

    def test_run_starts_window(self, app, mock_window):
        app.run()
        mock_window.start.assert_called_once()

    def test_run_order(self, app, mock_server, mock_tray, mock_window):
        """Server must be ready before tray is shown, tray before window opens."""
        call_order = []
        mock_server.start.side_effect = lambda: call_order.append("server.start")
        mock_server.wait_ready.side_effect = lambda: call_order.append("server.wait_ready")
        mock_tray.run_detached.side_effect = lambda: call_order.append("tray.run_detached")
        mock_window.create.side_effect = lambda: call_order.append("window.create")
        mock_window.start.side_effect = lambda: call_order.append("window.start")

        app.run()

        assert call_order == [
            "server.start",
            "server.wait_ready",
            "tray.run_detached",
            "window.create",
            "window.start",
        ]


class TestDesktopAppQuit:
    def test_quit_stops_tray(self, app, mock_tray):
        app._quit()
        mock_tray.stop.assert_called_once()

    def test_quit_stops_server(self, app, mock_server):
        app._quit()
        mock_server.stop.assert_called_once()

    def test_quit_destroys_window(self, app, mock_window):
        app._quit()
        mock_window.destroy.assert_called_once()


class TestDesktopAppOnWindowClosed:
    def test_on_window_closed_stops_tray(self, app, mock_tray):
        app._on_window_closed()
        mock_tray.stop.assert_called_once()

    def test_on_window_closed_stops_server(self, app, mock_server):
        app._on_window_closed()
        mock_server.stop.assert_called_once()
