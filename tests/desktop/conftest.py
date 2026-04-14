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
def mock_pyside6() -> Generator[MagicMock, None, None]:
    """Inject fake PySide6 sub-modules so Qt GUI is never created in tests.

    ``WebViewWindow.create()`` and the thread-safe helpers do lazy
    ``from PySide6.QtXxx import ...`` imports; injecting mocks via
    ``sys.modules`` intercepts all of them.

    The fixture yields a namespace object with attributes:
      .QApplication  .QMainWindow  .QWebEngineView
      .QUrl  .QIcon  .QMetaObject  .Qt
    """
    import sys

    fake_app = MagicMock(name="QApplication_instance")
    fake_app.exec.return_value = 0

    QApplication_cls = MagicMock(name="QApplication")
    QApplication_cls.instance.return_value = None
    QApplication_cls.return_value = fake_app

    QMainWindow_cls = MagicMock(name="QMainWindow")

    QWebEngineView_cls = MagicMock(name="QWebEngineView")

    qt_core = MagicMock(name="PySide6.QtCore")
    qt_core.QUrl = MagicMock(name="QUrl")
    qt_core.QMetaObject = MagicMock(name="QMetaObject")
    qt_core.Qt = MagicMock(name="Qt")
    qt_core.Qt.ConnectionType = MagicMock(name="ConnectionType")
    qt_core.Qt.ConnectionType.QueuedConnection = 2  # Qt::QueuedConnection value

    qt_gui = MagicMock(name="PySide6.QtGui")
    qt_gui.QIcon = MagicMock(name="QIcon")

    qt_widgets = MagicMock(name="PySide6.QtWidgets")
    qt_widgets.QApplication = QApplication_cls
    qt_widgets.QMainWindow = QMainWindow_cls

    qt_webengine = MagicMock(name="PySide6.QtWebEngineWidgets")
    qt_webengine.QWebEngineView = QWebEngineView_cls

    pyside6 = MagicMock(name="PySide6")

    modules_to_inject = {
        "PySide6": pyside6,
        "PySide6.QtCore": qt_core,
        "PySide6.QtGui": qt_gui,
        "PySide6.QtWidgets": qt_widgets,
        "PySide6.QtWebEngineWidgets": qt_webengine,
    }

    originals = {k: sys.modules.get(k) for k in modules_to_inject}
    sys.modules.update(modules_to_inject)

    class _NS:
        QApplication = QApplication_cls
        app_instance = fake_app
        QMainWindow = QMainWindow_cls
        QWebEngineView = QWebEngineView_cls
        QUrl = qt_core.QUrl
        QIcon = qt_gui.QIcon
        QMetaObject = qt_core.QMetaObject
        Qt = qt_core.Qt

    try:
        yield _NS()
    finally:
        for k, v in originals.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


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
