"""
Fixtures for the netconfig_desktop unit tests.

All pywebview, pystray, and uvicorn interactions are mocked so the tests run
without a display, tray OS service, or live HTTP server.
"""
from __future__ import annotations

import threading
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Low-level library mocks (applied for the whole session so imports resolve)
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_webview() -> Generator[MagicMock, None, None]:
    """Inject a fake ``webview`` module so lazy ``import webview`` calls work.

    ``webview`` is imported lazily inside ``WebViewWindow.create()`` and
    ``start()``, so we inject the mock at the ``sys.modules`` level.  Each
    fake window gets its own ``_EventSlot`` so event-handler registration is
    testable.
    """
    import sys

    fake_window = MagicMock(name="webview.Window")
    fake_window.events = MagicMock()
    fake_window.events.closing = _EventSlot()

    mock_wv = MagicMock(name="webview")
    mock_wv.create_window.return_value = fake_window
    mock_wv.start.return_value = None

    original = sys.modules.get("webview")
    sys.modules["webview"] = mock_wv
    try:
        yield mock_wv
    finally:
        if original is None:
            sys.modules.pop("webview", None)
        else:
            sys.modules["webview"] = original


@pytest.fixture()
def mock_pystray() -> Generator[MagicMock, None, None]:
    """Patch pystray inside ``netconfig_desktop.tray``."""
    with patch("netconfig_desktop.tray.pystray") as mock_pt:
        fake_icon = MagicMock(name="pystray.Icon")
        mock_pt.Icon.return_value = fake_icon
        mock_pt.Menu = MagicMock(return_value=MagicMock())
        mock_pt.MenuItem = MagicMock(side_effect=lambda *a, **kw: MagicMock())
        yield mock_pt


@pytest.fixture()
def mock_generate_tray_image() -> Generator[MagicMock, None, None]:
    """Patch Pillow-backed icon generation so tests need no Pillow."""
    with patch("netconfig_desktop.tray.generate_tray_image") as mock_img:
        mock_img.return_value = MagicMock(name="PIL.Image")
        yield mock_img


@pytest.fixture()
def mock_write_ico() -> Generator[MagicMock, None, None]:
    """Patch ICO writing (``from netconfig_desktop.icons import write_ico`` in start()).

    Because the import happens inside the function body each call, patching the
    function on the ``netconfig_desktop.icons`` module is the correct target.
    """
    with patch("netconfig_desktop.icons.write_ico") as mock_ico:
        mock_ico.return_value = "/tmp/netconfig.ico"
        yield mock_ico


# ---------------------------------------------------------------------------
# Helper: simple event-slot emulator (+=, calls)
# ---------------------------------------------------------------------------


class _EventSlot:
    """Minimal emulation of a pywebview event slot (supports ``+=`` and call)."""

    def __init__(self) -> None:
        self._handlers: list = []

    def __iadd__(self, handler):
        self._handlers.append(handler)
        return self

    def __call__(self, *args, **kwargs):
        results = [h(*args, **kwargs) for h in self._handlers]
        return results[-1] if results else None
