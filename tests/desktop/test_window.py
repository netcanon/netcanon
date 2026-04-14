"""
Unit tests for ``netconfig_desktop.window``.

pywebview and Pillow are mocked — no GUI is created.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.desktop.conftest import _EventSlot
from netconfig_desktop.window import WebViewWindow


@pytest.fixture()
def win(mock_webview, mock_write_ico):
    """Return a WebViewWindow with webview fully mocked."""
    return WebViewWindow(url="http://127.0.0.1:8765", title="Test")


@pytest.fixture()
def created_win(win, mock_webview):
    """Return a created (but not started) WebViewWindow."""
    win.create()
    return win, mock_webview


class TestWebViewWindowCreate:
    def test_create_calls_create_window(self, created_win):
        win, mock_wv = created_win
        mock_wv.create_window.assert_called_once()

    def test_create_passes_url(self, created_win):
        win, mock_wv = created_win
        _, kwargs = mock_wv.create_window.call_args
        assert kwargs.get("url") == "http://127.0.0.1:8765"

    def test_create_passes_title(self, created_win):
        win, mock_wv = created_win
        _, kwargs = mock_wv.create_window.call_args
        assert kwargs.get("title") == "Test"

    def test_closing_handler_registered(self, created_win):
        win, mock_wv = created_win
        fake_window = mock_wv.create_window.return_value
        # The _EventSlot should contain our handler
        assert win._on_closing in fake_window.events.closing._handlers


class TestWebViewWindowStart:
    def test_start_calls_webview_start(self, created_win, mock_write_ico):
        win, mock_wv = created_win
        win.start()
        mock_wv.start.assert_called_once()

    def test_start_passes_ico_path(self, created_win, mock_write_ico):
        win, mock_wv = created_win
        win.start()
        _, kwargs = mock_wv.start.call_args
        assert kwargs.get("icon") == "/tmp/netconfig.ico"

    def test_start_without_create_raises(self, mock_webview, mock_write_ico):
        win = WebViewWindow(url="http://127.0.0.1:8765")
        with pytest.raises(RuntimeError, match="create\\(\\)"):
            win.start()

    def test_on_closed_callback_fired_after_start(self, mock_webview, mock_write_ico):
        on_closed = MagicMock()
        win = WebViewWindow(url="http://127.0.0.1:8765", on_closed=on_closed)
        win.create()
        win.start()
        on_closed.assert_called_once()


class TestWebViewWindowShowHide:
    def test_show_delegates_to_window(self, created_win):
        win, mock_wv = created_win
        fake_window = mock_wv.create_window.return_value
        win.show()
        fake_window.show.assert_called_once()

    def test_hide_delegates_to_window(self, created_win):
        win, mock_wv = created_win
        fake_window = mock_wv.create_window.return_value
        win.hide()
        fake_window.hide.assert_called_once()

    def test_show_noop_before_create(self, mock_webview, mock_write_ico):
        win = WebViewWindow(url="http://127.0.0.1:8765")
        # Should not raise
        win.show()

    def test_hide_noop_before_create(self, mock_webview, mock_write_ico):
        win = WebViewWindow(url="http://127.0.0.1:8765")
        win.hide()


class TestWebViewWindowDestroy:
    def test_destroy_delegates_to_window(self, created_win):
        win, mock_wv = created_win
        fake_window = mock_wv.create_window.return_value
        win.destroy()
        fake_window.destroy.assert_called_once()

    def test_destroy_sets_destroying_flag(self, created_win):
        win, _ = created_win
        win.destroy()
        assert win._destroying is True


class TestOnClosingHandler:
    def test_close_button_hides_window(self, created_win):
        win, mock_wv = created_win
        fake_window = mock_wv.create_window.return_value
        result = win._on_closing()
        # Should return True (cancel close) and call hide
        assert result is True
        fake_window.hide.assert_called_once()

    def test_programmatic_destroy_allows_close(self, created_win):
        win, mock_wv = created_win
        win._destroying = True
        result = win._on_closing()
        # Should return False (allow the destroy to proceed)
        assert result is False
