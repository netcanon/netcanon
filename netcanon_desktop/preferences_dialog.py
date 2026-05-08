"""
Preferences dialog — operator-facing UI for editing
``DesktopPreferences``.

Surfaces the operator's three path overrides (configs / definitions /
data root), the embedded server port, the open-in-editor toggle, and
two convenience buttons (Open Configs Folder / Save / Cancel).

The dialog NEVER restarts the embedded server itself.  All changes
are persisted to ``preferences.json`` via ``DesktopPreferences.save``;
a "Restart Netcanon for changes to take effect" notice is shown on
save so the operator knows when the new values will take hold.

PySide6 widgets do not have a native ``data-testid`` attribute, so we
use ``setObjectName()`` on each interactive widget per the
``pref-dialog-<field>-<action>`` convention.  Tests then locate widgets
via ``QDialog.findChild(QWidget, "<name>")``.

All PySide6 imports are deferred to method bodies so this module is
importable in tests that mock PySide6 via ``sys.modules`` injection.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from netcanon_desktop.preferences import DesktopPreferences

logger = logging.getLogger(__name__)


class PreferencesDialog:
    """Modal preferences dialog backed by ``DesktopPreferences``.

    Args:
        prefs: The current ``DesktopPreferences`` to seed the form with.
        prefs_path: Absolute path of ``preferences.json`` — the dialog
            writes here on Save.
        configs_dir_default: The current effective configs directory.
            Used as the starting directory for the "Open Configs Folder"
            button when ``prefs.configs_dir`` is None (no override set).
        parent: Optional Qt parent widget (typically the main window).

    Example::

        dialog = PreferencesDialog(prefs, prefs_path, configs_dir)
        dialog.create()
        if dialog.exec() == QDialog.Accepted:
            # operator clicked Save
            ...
    """

    def __init__(
        self,
        prefs: DesktopPreferences,
        prefs_path: Path,
        configs_dir_default: Path,
        parent: Optional[object] = None,
    ) -> None:
        self._prefs = prefs
        self._prefs_path = prefs_path
        self._configs_dir_default = configs_dir_default
        self._parent = parent
        # Populated by create()
        self._dialog = None
        self._configs_edit = None
        self._definitions_edit = None
        self._data_edit = None
        self._port_spin = None
        self._open_in_editor_check = None
        self._open_browser_check = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def create(self) -> None:
        """Build the QDialog and all child widgets.

        Must be called before ``exec()`` or ``show()``.  Imports PySide6
        lazily so the module remains importable in test environments
        that mock PySide6 via ``sys.modules``.
        """
        from PySide6.QtWidgets import (
            QCheckBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QSpinBox,
            QVBoxLayout,
            QWidget,
        )

        dlg = QDialog(self._parent)
        dlg.setObjectName("pref-dialog")
        dlg.setWindowTitle("Netcanon Preferences")

        outer = QVBoxLayout(dlg)
        form = QFormLayout()

        # ---- Configs directory row ----
        configs_row, configs_edit, configs_browse = self._build_path_row(
            initial=self._prefs.configs_dir,
            edit_name="pref-dialog-configs-edit",
            browse_name="pref-dialog-configs-browse",
        )
        configs_browse.clicked.connect(
            lambda: self._browse_into(configs_edit, "Select configs directory")
        )
        form.addRow(QLabel("Configs directory:"), configs_row)
        self._configs_edit = configs_edit

        # ---- Definitions directory row ----
        definitions_row, definitions_edit, definitions_browse = (
            self._build_path_row(
                initial=self._prefs.definitions_dir,
                edit_name="pref-dialog-definitions-edit",
                browse_name="pref-dialog-definitions-browse",
            )
        )
        definitions_browse.clicked.connect(
            lambda: self._browse_into(
                definitions_edit, "Select definitions directory"
            )
        )
        form.addRow(QLabel("Definitions directory:"), definitions_row)
        self._definitions_edit = definitions_edit

        # ---- Data directory row ----
        data_row, data_edit, data_browse = self._build_path_row(
            initial=self._prefs.data_dir,
            edit_name="pref-dialog-data-edit",
            browse_name="pref-dialog-data-browse",
        )
        data_browse.clicked.connect(
            lambda: self._browse_into(data_edit, "Select data directory")
        )
        form.addRow(QLabel("Data directory:"), data_row)
        self._data_edit = data_edit

        # ---- Port spinner ----
        port_spin = QSpinBox()
        port_spin.setObjectName("pref-dialog-port-spinner")
        port_spin.setRange(1024, 65535)
        port_spin.setValue(self._prefs.port)
        form.addRow(QLabel("Port (restart required):"), port_spin)
        self._port_spin = port_spin

        # ---- Toggles ----
        open_in_editor_check = QCheckBox("Enable 'Open in editor' button")
        open_in_editor_check.setObjectName("pref-dialog-open-in-editor-toggle")
        open_in_editor_check.setChecked(self._prefs.open_in_editor)
        form.addRow(open_in_editor_check)
        self._open_in_editor_check = open_in_editor_check

        open_browser_check = QCheckBox("Open browser on start")
        open_browser_check.setObjectName(
            "pref-dialog-open-browser-on-start-toggle"
        )
        open_browser_check.setChecked(self._prefs.open_browser_on_start)
        form.addRow(open_browser_check)
        self._open_browser_check = open_browser_check

        outer.addLayout(form)

        # ---- Open Configs Folder convenience button ----
        open_btn = QPushButton("Open Configs Folder")
        open_btn.setObjectName("pref-dialog-open-configs-folder")
        open_btn.clicked.connect(self._open_configs_folder)
        outer.addWidget(open_btn)

        # ---- Save / Cancel ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.setObjectName("pref-dialog-button-box")
        save_btn = buttons.button(QDialogButtonBox.Save)
        if save_btn is not None:
            save_btn.setObjectName("pref-dialog-save")
        cancel_btn = buttons.button(QDialogButtonBox.Cancel)
        if cancel_btn is not None:
            cancel_btn.setObjectName("pref-dialog-cancel")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)

        self._dialog = dlg

    def exec(self) -> int:
        """Show the dialog modally.  Returns the QDialog result code."""
        if self._dialog is None:
            raise RuntimeError("create() must be called before exec()")
        return self._dialog.exec()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_path_row(
        self,
        initial: Path | None,
        edit_name: str,
        browse_name: str,
    ):
        """Compose a (QWidget container, QLineEdit, QPushButton) tuple
        representing a path field with a Browse… button.
        """
        from PySide6.QtWidgets import (
            QHBoxLayout,
            QLineEdit,
            QPushButton,
            QWidget,
        )

        container = QWidget()
        layout = QHBoxLayout(container)
        # Tight margins so the row doesn't dominate the form layout
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit()
        edit.setObjectName(edit_name)
        edit.setText(str(initial) if initial is not None else "")
        edit.setPlaceholderText("(use default)")
        browse = QPushButton("Browse…")
        browse.setObjectName(browse_name)
        layout.addWidget(edit)
        layout.addWidget(browse)
        return container, edit, browse

    def _browse_into(self, edit, caption: str) -> None:
        """Open a QFileDialog directory picker and write the selection
        back to *edit* if the user picked something."""
        from PySide6.QtWidgets import QFileDialog

        starting = edit.text() or str(self._configs_dir_default)
        chosen = QFileDialog.getExistingDirectory(
            self._dialog, caption, starting
        )
        if chosen:
            edit.setText(chosen)

    def _open_configs_folder(self) -> None:
        """Open the current configs directory in the OS file manager."""
        target = (
            self._configs_dir_from_form() or self._configs_dir_default
        )
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]  # Windows-only
        except Exception:  # noqa: BLE001
            # Non-Windows platforms or missing directory — log and skip.
            logger.debug(
                "os.startfile failed for %s", target, exc_info=True
            )

    def _configs_dir_from_form(self) -> Path | None:
        text = (self._configs_edit.text() if self._configs_edit else "").strip()
        return Path(text) if text else None

    def _on_save(self) -> None:
        """Build a fresh ``DesktopPreferences`` from form state and persist."""
        from PySide6.QtWidgets import QMessageBox

        try:
            new_prefs = DesktopPreferences(
                configs_dir=self._configs_dir_from_form(),
                definitions_dir=self._path_from(self._definitions_edit),
                data_dir=self._path_from(self._data_edit),
                port=self._port_spin.value() if self._port_spin else 8765,
                open_in_editor=(
                    self._open_in_editor_check.isChecked()
                    if self._open_in_editor_check
                    else True
                ),
                open_browser_on_start=(
                    self._open_browser_check.isChecked()
                    if self._open_browser_check
                    else False
                ),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self._dialog,
                "Invalid preferences",
                f"Could not save preferences: {exc}",
            )
            return

        new_prefs.save(self._prefs_path)
        # Cache the saved snapshot for callers that re-read .prefs
        self._prefs = new_prefs
        QMessageBox.information(
            self._dialog,
            "Preferences saved",
            "Restart Netcanon for changes to take effect.",
        )
        if self._dialog is not None:
            self._dialog.accept()

    def _path_from(self, edit) -> Path | None:
        text = (edit.text() if edit else "").strip()
        return Path(text) if text else None

    @property
    def prefs(self) -> DesktopPreferences:
        """Return the most recently loaded / saved preferences object."""
        return self._prefs
