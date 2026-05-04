"""
Unit tests for ``netconfig_desktop.window``.

PySide6 is mocked via ``sys.modules`` injection so no display is required.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from netconfig_desktop.window import WebViewWindow

pytestmark = pytest.mark.desktop


@pytest.fixture()
def win(mock_pyside6, mock_write_ico):
    """Return an uncreated WebViewWindow with PySide6 fully mocked."""
    return WebViewWindow(url="http://127.0.0.1:8765", title="Test", width=800, height=600)


@pytest.fixture()
def created_win(win, mock_pyside6):
    """Return a created (but not started) WebViewWindow."""
    win.create()
    return win, mock_pyside6


class TestWebViewWindowCreate:
    def test_qapplication_created(self, created_win):
        win, ns = created_win
        assert win._app is not None

    def test_qmainwindow_created(self, created_win):
        win, ns = created_win
        assert win._win is not None

    def test_title_set_on_window(self, created_win):
        win, ns = created_win
        win._win.setWindowTitle.assert_called_once_with("Test")

    def test_size_set_on_window(self, created_win):
        win, ns = created_win
        win._win.resize.assert_called_once_with(800, 600)

    def test_web_view_loaded_with_url(self, created_win, mock_pyside6):
        win, ns = created_win
        view_instance = ns.QWebEngineView.return_value
        view_instance.load.assert_called_once()
        url_arg = view_instance.load.call_args[0][0]
        # QUrl was called with the correct URL string
        ns.QUrl.assert_called_once_with("http://127.0.0.1:8765")

    def test_web_view_set_as_central_widget(self, created_win, mock_pyside6):
        win, ns = created_win
        view_instance = ns.QWebEngineView.return_value
        win._win.setCentralWidget.assert_called_once_with(view_instance)

    def test_icon_written_and_set(self, created_win, mock_pyside6, mock_write_ico):
        win, ns = created_win
        mock_write_ico.assert_called_once()
        ns.QIcon.assert_called_once_with("/tmp/netconfig.ico")


class TestWebViewWindowStart:
    def test_start_calls_show(self, created_win):
        win, ns = created_win
        win.start()
        win._win.show.assert_called_once()

    def test_start_calls_app_exec(self, created_win):
        win, ns = created_win
        win.start()
        ns.app_instance.exec.assert_called_once()

    def test_start_without_create_raises(self, mock_pyside6, mock_write_ico):
        win = WebViewWindow(url="http://127.0.0.1:8765")
        with pytest.raises(RuntimeError, match="create\\(\\)"):
            win.start()

    def test_on_closed_callback_fired_after_exec(self, mock_pyside6, mock_write_ico):
        on_closed = MagicMock()
        win = WebViewWindow(url="http://127.0.0.1:8765", on_closed=on_closed)
        win.create()
        win.start()
        on_closed.assert_called_once()


class TestWebViewWindowShowHide:
    def test_show_posts_invoke_method(self, created_win, mock_pyside6):
        win, ns = created_win
        win.show()
        assert ns.QMetaObject.invokeMethod.call_count >= 1

    def test_hide_posts_invoke_method(self, created_win, mock_pyside6):
        win, ns = created_win
        win.hide()
        ns.QMetaObject.invokeMethod.assert_called_once()

    def test_show_noop_before_create(self, mock_pyside6, mock_write_ico):
        win = WebViewWindow(url="http://127.0.0.1:8765")
        win.show()  # should not raise

    def test_hide_noop_before_create(self, mock_pyside6, mock_write_ico):
        win = WebViewWindow(url="http://127.0.0.1:8765")
        win.hide()  # should not raise


class TestWebViewWindowDestroy:
    def test_destroy_sets_destroying_flag(self, created_win):
        win, _ = created_win
        win.destroy()
        assert win._destroying is True

    def test_destroy_posts_quit(self, created_win, mock_pyside6):
        win, ns = created_win
        win.destroy()
        ns.QMetaObject.invokeMethod.assert_called_once()
        call_args = ns.QMetaObject.invokeMethod.call_args
        assert call_args[0][1] == "quit"

    def test_destroy_noop_before_create(self, mock_pyside6, mock_write_ico):
        win = WebViewWindow(url="http://127.0.0.1:8765")
        win.destroy()  # should not raise


class TestHandleClose:
    """Test WebViewWindow._handle_close — the close-event handler.

    Calls the method directly (bypassing Qt) so no real QMainWindow is needed.
    """

    def test_close_button_ignores_event_and_hides(self, created_win, mock_pyside6):
        """When _destroying is False, the event is ignored and the window hides."""
        win, ns = created_win
        fake_event = MagicMock()
        win._handle_close(fake_event)
        fake_event.ignore.assert_called_once()
        fake_event.accept.assert_not_called()
        # hide() posts an invokeMethod call
        ns.QMetaObject.invokeMethod.assert_called()

    def test_programmatic_destroy_accepts_event(self, mock_pyside6, mock_write_ico):
        """When _destroying is True, the event is accepted."""
        win = WebViewWindow(url="http://127.0.0.1:8765")
        win._destroying = True
        fake_event = MagicMock()
        win._handle_close(fake_event)
        fake_event.accept.assert_called_once()
        fake_event.ignore.assert_not_called()
