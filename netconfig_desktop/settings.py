"""
Desktop-specific settings factory.

Resolves the correct ``definitions_dir`` and ``configs_dir`` paths depending
on whether the application is:

* Running from source (development) — definitions are in the repo root, configs
  go to a ``configs/`` sibling directory that is created on first run.
* Running as a frozen cx_Freeze executable — definitions ship next to the EXE
  (included by ``setup_desktop.py``), configs go to
  ``%APPDATA%\\NetConfig\\configs\\`` so they survive upgrades.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from netconfig.config import Settings

#: Internal loopback port used by the embedded Uvicorn server.
#: Chosen to be outside the IANA well-known and registered ranges and
#: unlikely to conflict with other services on a developer machine.
DESKTOP_PORT: int = 8765


def desktop_settings() -> Settings:
    """Return a ``Settings`` instance appropriate for the desktop application.

    When frozen (``sys.frozen`` is ``True``), the definitions directory is
    resolved relative to the EXE, and configs are stored in the user's
    ``%APPDATA%`` folder.  In development (not frozen), both directories
    live in the repository root.

    Returns:
        A configured ``Settings`` instance with loopback host binding.
    """
    if getattr(sys, "frozen", False):
        # Running as a cx_Freeze bundle — exe is in the install directory.
        install_dir = Path(sys.executable).parent
        definitions_dir = install_dir / "definitions"
        configs_dir = _appdata_dir() / "configs"
    else:
        # Running from source — project root is two levels up from this file.
        repo_root = Path(__file__).parent.parent
        definitions_dir = repo_root / "definitions"
        configs_dir = repo_root / "configs"

    configs_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        definitions_dir=definitions_dir,
        configs_dir=configs_dir,
        host="127.0.0.1",
        port=DESKTOP_PORT,
        log_level="info",
        open_in_editor=True,
    )


def _appdata_dir() -> Path:
    """Return ``%APPDATA%\\NetConfig``, creating it if necessary."""
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    app_dir = base / "NetConfig"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir
