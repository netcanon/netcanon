"""
cx_Freeze build script for the Netcanon Windows desktop application.

Usage::

    python setup_desktop.py bdist_msi

This produces an MSI installer under ``dist/``.  The installer:

* Installs the application to ``C:\\Program Files\\Netcanon\\``
* Creates a Start Menu shortcut (pinnable to the taskbar)
* Bundles Python, all dependencies, and the device definitions

Requirements::

    pip install cx_Freeze

See https://cx-freeze.readthedocs.io/en/stable/setup_script.html for full
option documentation.
"""
from __future__ import annotations

import sys
from pathlib import Path

from cx_Freeze import Executable, setup

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
DEFINITIONS_DIR = HERE / "definitions"

# ---------------------------------------------------------------------------
# MSI upgrade code — MUST remain constant across releases so the installer
# can upgrade an existing installation.  Generate once with:
#     python -c "import uuid; print(uuid.uuid4())"
# and never change it.
# ---------------------------------------------------------------------------
UPGRADE_CODE = "{A3F2C1B0-7E4D-4A9F-8B3C-2D5E6F7A8B9C}"

# ---------------------------------------------------------------------------
# Build options
# ---------------------------------------------------------------------------

build_exe_options: dict = {
    # Extra packages that cx_Freeze cannot discover automatically through
    # static import analysis (dynamic imports, conditional imports, etc.)
    "packages": [
        "netconfig",
        "netconfig.templates",
        "netconfig_desktop",
        "uvicorn",
        "fastapi",
        "starlette",
        "jinja2",
        "pydantic",
        "pydantic_core",
        "anyio",
        "anyio._backends",
        "asyncio",
        "netmiko",
        "paramiko",
        "pystray",
        "PySide6",
        "PIL",
        "yaml",
        "httpx",
    ],
    # Non-Python files that must be included in the build tree.
    "include_files": [
        # Ship device definitions next to the EXE so desktop_settings()
        # finds them when sys.frozen is True.
        (str(DEFINITIONS_DIR), "definitions"),
        # Jinja2 templates bundled with the netconfig package.
        (str(HERE / "netconfig" / "templates"), "lib/netconfig/templates"),
    ],
    # Exclude large packages that are not needed at runtime to keep the
    # installer size reasonable.
    "excludes": [
        "test",
        "tests",
        "pytest",
        "playwright",
        "setuptools",
        "distutils",
        "cx_Freeze",
        "tkinter",
    ],
    # Optimise .pyc files.
    "optimize": 1,
}

bdist_msi_options: dict = {
    "upgrade_code": UPGRADE_CODE,
    "add_to_path": False,
    "initial_target_dir": r"[ProgramFilesFolder]\Netcanon",
    # All shortcuts defined in the Executable below end up here.
    "data": {
        "Shortcut": [
            # Start Menu shortcut (also appears in taskbar pin list)
            (
                "StartMenuShortcut",          # Shortcut id
                "StartMenuFolder",            # Directory_ (Start Menu)
                "Netcanon",                  # Name (display name)
                "TARGETDIR",                  # Component_
                "[TARGETDIR]netconfig.exe",   # Target
                None,                         # Arguments
                "Netcanon — Network Config Collector",  # Description
                None,                         # Hotkey
                None,                         # Icon (uses exe icon)
                None,                         # IconIndex
                None,                         # ShowCmd
                "TARGETDIR",                  # WkDir
            ),
        ],
    },
}

# ---------------------------------------------------------------------------
# Executable definition
# ---------------------------------------------------------------------------

def _build_icon() -> str | None:
    """Generate a temporary ICO file for embedding in the EXE.

    Returns the path to the ICO file, or ``None`` if Pillow is not installed
    (icon embedding is optional for the build to succeed).
    """
    try:
        from netconfig_desktop.icons import write_ico

        ico_path = write_ico()
        return str(ico_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[setup_desktop] Warning: could not generate icon: {exc}")
        return None


executables = [
    Executable(
        # Entry point — runs netconfig_desktop.__main__:main()
        script="netconfig_desktop/__main__.py",
        # Win32GUI suppresses the console window so the app runs silently.
        base="Win32GUI" if sys.platform == "win32" else None,
        target_name="netconfig.exe",
        # The icon embedded in the EXE itself (taskbar / alt-tab).
        icon=_build_icon(),
        shortcut_name="Netcanon",
        shortcut_dir="StartMenuFolder",
        copyright="Netcanon contributors",
    ),
]


# ---------------------------------------------------------------------------
# setup() call
# ---------------------------------------------------------------------------

setup(
    name="Netcanon",
    version="0.1.0",
    description="Netcanon — Network Configuration Collector",
    author="Netcanon contributors",
    options={
        "build_exe": build_exe_options,
        "bdist_msi": bdist_msi_options,
    },
    executables=executables,
)
