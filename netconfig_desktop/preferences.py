"""
Desktop-only preferences — operator-configurable settings persisted
to ``%APPDATA%\\NetConfig\\preferences.json``.

The web platform configures equivalent values via ``NETCONFIG_*`` env
vars or ``.env`` files.  Desktop operators have no shell-level config
surface; this model is their equivalent.

When a field is ``None``, ``desktop_settings()`` falls back to the frozen-
mode default.  Operators set values via the Preferences dialog
(``preferences_dialog.py``).

Persistence rules:

* Corruption is non-fatal — ``load()`` swallows JSON / schema errors and
  returns factory defaults so the desktop never refuses to start because
  of a botched preferences file.  The operator can reopen the dialog
  and re-save to repair.
* Path values are serialised as strings (``model_dump(mode="json")``)
  so the JSON file is human-readable / editable.
* The schema is intentionally permissive — every field is Optional —
  so adding a new preference in a later release does not invalidate
  older preferences.json files.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class DesktopPreferences(BaseModel):
    """Operator-configurable desktop preferences.

    Each path field is Optional with a ``None`` default meaning "use the
    desktop-platform default" (the values returned by
    ``netconfig_desktop.settings.desktop_settings()`` for the current
    frozen-vs-dev mode).  The non-Optional fields ``port``,
    ``open_in_editor`` and ``open_browser_on_start`` carry direct factory
    defaults.

    Attributes:
        configs_dir: Override for the directory storing captured config
            files.  ``None`` → use the platform default
            (``%APPDATA%\\NetConfig\\configs\\`` when frozen).
        definitions_dir: Override for the YAML device-definitions tree.
            ``None`` → use the platform default (next to the EXE when
            frozen, repo root when dev).
        data_dir: Override for the data-root directory holding the
            ``jobs/``, ``schedules/`` and ``devices/`` JSON stores.
            ``None`` → fall back to ``Settings.effective_data_dir``
            which derives from ``configs_dir.parent``.
        port: TCP port the embedded Uvicorn server binds on the
            loopback interface.  Restricted to the unprivileged range
            (1024–65535).  Changes only take effect on the next start.
        open_in_editor: Whether the "Open in editor" UI surface
            (``POST /api/v1/configs/{filename}/open``) is enabled.
            Defaults True for desktop because the server runs locally.
        open_browser_on_start: Reserved for a future feature — open
            the system browser to the embedded server URL on launch
            instead of (or in addition to) the WebView window.  Not
            currently wired; preserved here so the schema is forward-
            compatible.
    """

    configs_dir: Path | None = None
    definitions_dir: Path | None = None
    data_dir: Path | None = None
    port: int = Field(default=8765, ge=1024, le=65535)
    open_in_editor: bool = True
    open_browser_on_start: bool = False

    @classmethod
    def load(cls, path: Path) -> "DesktopPreferences":
        """Load preferences from a JSON file.

        Returns factory defaults when the file does not exist OR fails
        to parse / validate.  Preferences are non-essential application
        state; the desktop must never fail to start because of
        preferences-file corruption.

        Args:
            path: Absolute path to the JSON preferences file.

        Returns:
            A ``DesktopPreferences`` instance — never raises.
        """
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**data)
        except Exception:
            # Corrupted or schema-mismatched file — return defaults.
            # Operator will see frozen-mode defaults; they can re-save
            # via the Preferences dialog to repair the file.
            return cls()

    def save(self, path: Path) -> None:
        """Write preferences to a JSON file.

        Creates parent directories as needed.  ``Path`` values are
        serialised as strings via ``model_dump(mode="json")`` so the
        resulting file is straightforward to inspect and hand-edit.

        Args:
            path: Absolute path to write to.  Existing contents are
                replaced wholesale.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        # mode="json" + default=str ensures Path objects survive the
        # round-trip through json.dumps as plain strings.
        data = self.model_dump(mode="json", exclude_none=False)
        path.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )
