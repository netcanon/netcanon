"""
Unit tests for ``netconfig_desktop.preferences_dialog.PreferencesDialog``.

PySide6 is mocked via the shared ``mock_pyside6`` fixture (which extends
the namespace with QSpinBox / QCheckBox / QFormLayout / QFileDialog /
QDialog so the dialog's lazy imports resolve to MagicMocks).

The tests assert the *wiring* (callbacks connected, save persists,
cancel discards) without requiring a real Qt event loop.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from netconfig_desktop.preferences import DesktopPreferences

pytestmark = pytest.mark.desktop


# ---------------------------------------------------------------------------
# Local Qt mocks specific to the dialog.  These augment the conftest-level
# ``mock_pyside6`` fixture by attaching the extra widget classes the dialog
# imports lazily.
# ---------------------------------------------------------------------------


class _SignalStub:
    """Minimal QtCore.Signal stand-in supporting ``.connect(handler)``."""

    def __init__(self) -> None:
        self.handlers: list = []

    def connect(self, handler) -> None:  # noqa: D401
        self.handlers.append(handler)

    def emit(self, *args, **kwargs):
        for h in self.handlers:
            h(*args, **kwargs)


def _make_widget_with_signal(*signal_names: str) -> MagicMock:
    """Return a MagicMock instance with named ``_SignalStub`` attributes."""
    mock = MagicMock()
    for name in signal_names:
        setattr(mock, name, _SignalStub())
    return mock


@pytest.fixture()
def mock_qt_dialog(mock_pyside6):
    """Augment ``mock_pyside6.QtWidgets`` with dialog-specific widgets.

    Returns a namespace exposing the extra fakes for assertion.
    """
    qt_widgets = sys.modules["PySide6.QtWidgets"]

    # Build classes that return widgets with ``clicked`` signals etc.
    def make_qdialog(*args, **kwargs):
        d = _make_widget_with_signal()
        d.exec.return_value = 1  # QDialog.Accepted
        d.accept = MagicMock()
        d.reject = MagicMock()
        return d

    def make_qpushbutton(*args, **kwargs):
        b = _make_widget_with_signal("clicked")
        return b

    def make_qlineedit(*args, **kwargs):
        edit = MagicMock()
        edit._text = ""
        edit.setText.side_effect = lambda v: setattr(edit, "_text", v)
        edit.text.side_effect = lambda: edit._text
        return edit

    def make_qspinbox(*args, **kwargs):
        spin = MagicMock()
        spin._value = 0
        spin.setValue.side_effect = lambda v: setattr(spin, "_value", v)
        spin.value.side_effect = lambda: spin._value
        return spin

    def make_qcheckbox(*args, **kwargs):
        cb = MagicMock()
        cb._checked = False
        cb.setChecked.side_effect = lambda v: setattr(cb, "_checked", v)
        cb.isChecked.side_effect = lambda: cb._checked
        return cb

    qt_widgets.QDialog = MagicMock(side_effect=make_qdialog)
    # Constants used as flags
    qt_widgets.QDialog.Accepted = 1
    qt_widgets.QDialog.Rejected = 0
    qt_widgets.QPushButton = MagicMock(side_effect=make_qpushbutton)
    qt_widgets.QLineEdit = MagicMock(side_effect=make_qlineedit)
    qt_widgets.QSpinBox = MagicMock(side_effect=make_qspinbox)
    qt_widgets.QCheckBox = MagicMock(side_effect=make_qcheckbox)
    qt_widgets.QLabel = MagicMock(side_effect=lambda *a, **kw: MagicMock())
    qt_widgets.QFormLayout = MagicMock(side_effect=lambda *a, **kw: MagicMock())
    qt_widgets.QHBoxLayout = MagicMock(side_effect=lambda *a, **kw: MagicMock())
    qt_widgets.QVBoxLayout = MagicMock(side_effect=lambda *a, **kw: MagicMock())
    qt_widgets.QWidget = MagicMock(side_effect=lambda *a, **kw: MagicMock())

    # QDialogButtonBox + flags + .button() lookup
    def make_button_box(*args, **kwargs):
        box = _make_widget_with_signal("accepted", "rejected")
        save_btn = make_qpushbutton()
        cancel_btn = make_qpushbutton()
        box._buttons = {"save": save_btn, "cancel": cancel_btn}
        box.button = MagicMock(
            side_effect=lambda flag: (
                save_btn if flag == qt_widgets.QDialogButtonBox.Save
                else cancel_btn if flag == qt_widgets.QDialogButtonBox.Cancel
                else None
            )
        )
        return box

    qt_widgets.QDialogButtonBox = MagicMock(side_effect=make_button_box)
    qt_widgets.QDialogButtonBox.Save = 0x800
    qt_widgets.QDialogButtonBox.Cancel = 0x400000

    # QFileDialog returns a path string
    qt_widgets.QFileDialog = MagicMock()
    qt_widgets.QFileDialog.getExistingDirectory = MagicMock(
        return_value="/picked/dir"
    )

    qt_widgets.QMessageBox = MagicMock()

    return qt_widgets


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def dialog(mock_qt_dialog, tmp_path):
    """Return a created PreferencesDialog with default preferences."""
    from netconfig_desktop.preferences_dialog import PreferencesDialog

    prefs = DesktopPreferences()
    d = PreferencesDialog(
        prefs=prefs,
        prefs_path=tmp_path / "preferences.json",
        configs_dir_default=tmp_path / "default_configs",
    )
    d.create()
    return d


class TestDialogConstruction:
    def test_dialog_created(self, dialog):
        assert dialog._dialog is not None

    def test_port_spinner_seeded_from_prefs(self, dialog):
        assert dialog._port_spin.value() == 8765

    def test_open_in_editor_check_seeded_true(self, dialog):
        assert dialog._open_in_editor_check.isChecked() is True

    def test_open_browser_check_seeded_false(self, dialog):
        assert dialog._open_browser_check.isChecked() is False

    def test_object_names_set(self, dialog):
        # Each interactive widget carries a setObjectName() call
        dialog._port_spin.setObjectName.assert_any_call(
            "pref-dialog-port-spinner"
        )
        dialog._open_in_editor_check.setObjectName.assert_any_call(
            "pref-dialog-open-in-editor-toggle"
        )
        dialog._open_browser_check.setObjectName.assert_any_call(
            "pref-dialog-open-browser-on-start-toggle"
        )


class TestBrowseButtons:
    def test_browse_uses_current_value_as_starting_dir(
        self, mock_qt_dialog, tmp_path
    ):
        from netconfig_desktop.preferences_dialog import PreferencesDialog

        # Path is normalised to native separators by str(Path(...));
        # use the round-trip so the assertion works on both posix and win32.
        seed = str(Path("/existing/value"))
        prefs = DesktopPreferences(configs_dir=Path(seed))
        d = PreferencesDialog(
            prefs=prefs,
            prefs_path=tmp_path / "preferences.json",
            configs_dir_default=tmp_path / "default_configs",
        )
        d.create()

        # Trigger the browse callback for configs by invoking
        # _browse_into directly on the configs edit
        d._browse_into(d._configs_edit, "Select configs directory")
        mock_qt_dialog.QFileDialog.getExistingDirectory.assert_called_once()
        args = mock_qt_dialog.QFileDialog.getExistingDirectory.call_args[0]
        # 3rd positional arg is the starting directory; it should match
        # the seeded value as written into the line edit.
        assert args[2] == seed

    def test_browse_falls_back_to_default_when_field_empty(
        self, mock_qt_dialog, dialog, tmp_path
    ):
        # configs_edit is empty (default DesktopPreferences has None)
        dialog._browse_into(dialog._configs_edit, "Select")
        args = mock_qt_dialog.QFileDialog.getExistingDirectory.call_args[0]
        assert args[2] == str(tmp_path / "default_configs")

    def test_browse_writes_picked_path_to_edit(self, mock_qt_dialog, dialog):
        mock_qt_dialog.QFileDialog.getExistingDirectory.return_value = (
            "/new/picked"
        )
        dialog._browse_into(dialog._configs_edit, "Select")
        assert dialog._configs_edit.text() == "/new/picked"

    def test_browse_cancel_does_not_overwrite(self, mock_qt_dialog, dialog):
        dialog._configs_edit.setText("/keep/me")
        mock_qt_dialog.QFileDialog.getExistingDirectory.return_value = ""
        dialog._browse_into(dialog._configs_edit, "Select")
        assert dialog._configs_edit.text() == "/keep/me"


class TestSavePersistence:
    def test_save_writes_preferences_json(
        self, mock_qt_dialog, dialog, tmp_path
    ):
        # Modify the form state
        dialog._configs_edit.setText(str(tmp_path / "user_configs"))
        dialog._port_spin.setValue(9001)
        dialog._open_in_editor_check.setChecked(False)

        dialog._on_save()

        path = tmp_path / "preferences.json"
        assert path.exists()
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["port"] == 9001
        assert raw["open_in_editor"] is False
        # Path serialised as string
        assert str(tmp_path / "user_configs") in raw["configs_dir"]

    def test_save_calls_dialog_accept(self, mock_qt_dialog, dialog):
        dialog._on_save()
        dialog._dialog.accept.assert_called_once()

    def test_save_invalid_port_does_not_persist(
        self, mock_qt_dialog, dialog, tmp_path
    ):
        # The QSpinBox enforces range, but we bypass it by stubbing
        # the value() to return out-of-range — the model's validator
        # then rejects the construction.
        dialog._port_spin._value = 70000
        dialog._on_save()
        # File should not have been written
        assert not (tmp_path / "preferences.json").exists()
        # And the dialog should not have been accepted
        dialog._dialog.accept.assert_not_called()


class TestOpenConfigsFolder:
    def test_open_configs_uses_default_when_field_empty(
        self, mock_qt_dialog, dialog, tmp_path
    ):
        with patch("netconfig_desktop.preferences_dialog.os.startfile",
                   create=True) as mock_startfile:
            dialog._open_configs_folder()
        mock_startfile.assert_called_once_with(
            str(tmp_path / "default_configs")
        )

    def test_open_configs_uses_form_value_when_set(
        self, mock_qt_dialog, dialog, tmp_path
    ):
        dialog._configs_edit.setText(str(tmp_path / "from_form"))
        with patch("netconfig_desktop.preferences_dialog.os.startfile",
                   create=True) as mock_startfile:
            dialog._open_configs_folder()
        mock_startfile.assert_called_once_with(
            str(tmp_path / "from_form")
        )

    def test_open_configs_swallows_exceptions(
        self, mock_qt_dialog, dialog
    ):
        with patch(
            "netconfig_desktop.preferences_dialog.os.startfile",
            create=True, side_effect=OSError("not on Windows"),
        ):
            # Should not raise
            dialog._open_configs_folder()


class TestExecRequiresCreate:
    def test_exec_before_create_raises(self, mock_qt_dialog, tmp_path):
        from netconfig_desktop.preferences_dialog import PreferencesDialog

        d = PreferencesDialog(
            prefs=DesktopPreferences(),
            prefs_path=tmp_path / "preferences.json",
            configs_dir_default=tmp_path / "configs",
        )
        with pytest.raises(RuntimeError, match="create"):
            d.exec()
