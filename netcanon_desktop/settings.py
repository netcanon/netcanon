"""
Desktop-specific settings factory.

Resolves the correct ``definitions_dir`` and ``configs_dir`` paths depending
on whether the application is:

* Running from source (development) — definitions are in the repo root, configs
  go to a ``configs/`` sibling directory that is created on first run.
* Running as a frozen cx_Freeze executable — definitions ship next to the EXE
  (included by ``setup_desktop.py``), configs go to
  ``%APPDATA%\\Netcanon\\configs\\`` so they survive upgrades.

In frozen mode, an optional ``preferences.json`` under
``%APPDATA%\\Netcanon\\`` is loaded and overlaid on top of the platform
defaults (see ``DesktopPreferences``).  Only non-``None`` preference
fields override; missing keys keep the defaults.  Dev mode deliberately
ignores the preferences file so the repo-relative paths remain
predictable for contributors.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from netcanon.config import Settings
from netcanon_desktop.preferences import DesktopPreferences

#: Internal loopback port used by the embedded Uvicorn server.
#: Chosen to be outside the IANA well-known and registered ranges and
#: unlikely to conflict with other services on a developer machine.
DESKTOP_PORT: int = 8765


def desktop_settings() -> Settings:
    """Return a ``Settings`` instance appropriate for the desktop application.

    When frozen (``sys.frozen`` is ``True``), the definitions directory is
    resolved relative to the EXE, configs are stored in the user's
    ``%APPDATA%`` folder, AND any operator-saved preferences from
    ``preferences.json`` are overlaid on top.  In development (not
    frozen), both directories live in the repository root and the
    preferences file is ignored so contributor workflow is predictable.

    Returns:
        A configured ``Settings`` instance with loopback host binding.
    """
    if getattr(sys, "frozen", False):
        # Running as a cx_Freeze bundle — exe is in the install directory.
        install_dir = Path(sys.executable).parent
        definitions_dir = install_dir / "definitions"
        configs_dir = _appdata_dir() / "configs"
        prefs = DesktopPreferences.load(_preferences_path())
    else:
        # Running from source — project root is two levels up from this file.
        repo_root = Path(__file__).parent.parent
        definitions_dir = repo_root / "definitions"
        configs_dir = repo_root / "configs"
        # Dev mode deliberately uses factory defaults (no preferences
        # file load) so tests / local development have predictable
        # paths regardless of whatever is in %APPDATA%.
        prefs = DesktopPreferences()

    # Apply non-None preference overrides on top of the platform default.
    if prefs.configs_dir is not None:
        configs_dir = prefs.configs_dir
    if prefs.definitions_dir is not None:
        definitions_dir = prefs.definitions_dir

    configs_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        definitions_dir=definitions_dir,
        configs_dir=configs_dir,
        data_dir=prefs.data_dir,  # None falls through to effective_data_dir derivation
        host="127.0.0.1",
        port=prefs.port,
        log_level="info",
        open_in_editor=prefs.open_in_editor,
    )


def _appdata_dir() -> Path:
    """Return ``%APPDATA%\\Netcanon``, creating it if necessary."""
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    app_dir = base / "Netcanon"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def _preferences_path() -> Path:
    """Path to the operator's ``preferences.json`` under ``%APPDATA%``.

    Always returns the same location regardless of whether the file
    exists; ``DesktopPreferences.load()`` handles the absent-file case
    by returning factory defaults.
    """
    return _appdata_dir() / "preferences.json"
