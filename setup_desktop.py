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

Versioning
----------

The Windows MSI ``ProductVersion`` field has a strict ``M.m.b[.r]`` format
that does NOT accept the rc / alpha / beta suffixes the rest of the project
uses (e.g. ``0.1.0rc7``).  Two paths are supported:

* **Local builds**: the default ``MSI_VERSION`` constant below is used —
  bump it manually if you care about the in-installer version.
* **CI builds**: the ``desktop-msi-publish.yml`` workflow derives the
  version from the triggering git tag (stripping the rc-suffix) and
  passes it via the ``NETCANON_MSI_VERSION`` env var.  This script
  honours that override when set so CI doesn't have to edit this file.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from cx_Freeze import Executable, setup

# Default MSI version used when no env override is supplied (i.e. local
# manual builds).  Bump this manually between releases — Windows MSI
# format constraints mean we can't reuse the setuptools_scm rc-suffixed
# version directly.  CI sets NETCANON_MSI_VERSION from the tag.
MSI_VERSION_DEFAULT = "0.1.0"
MSI_VERSION = os.environ.get("NETCANON_MSI_VERSION", MSI_VERSION_DEFAULT)

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
    # static import analysis (dynamic imports, conditional imports, etc.).
    # Every entry must be a runtime dependency installed by the
    # `[desktop]` extra group in pyproject.toml — dev-only deps (e.g.
    # httpx, used by pytest's TestClient) must not be listed here or
    # cx_Freeze fails with ImportError during the build.
    "packages": [
        "netcanon",
        "netcanon.templates",
        "netcanon_desktop",
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
    ],
    # Non-Python files that must be included in the build tree.
    "include_files": [
        # Ship device definitions next to the EXE so desktop_settings()
        # finds them when sys.frozen is True.
        (str(DEFINITIONS_DIR), "definitions"),
        # Jinja2 templates bundled with the netcanon package.
        (str(HERE / "netcanon" / "templates"), "lib/netcanon/templates"),
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
                "[TARGETDIR]netcanon.exe",   # Target
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
        from netcanon_desktop.icons import write_ico

        ico_path = write_ico()
        return str(ico_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[setup_desktop] Warning: could not generate icon: {exc}")
        return None


executables = [
    Executable(
        # Entry point — runs netcanon_desktop.__main__:main()
        script="netcanon_desktop/__main__.py",
        # "gui" suppresses the console window so the app runs silently.
        # cx_Freeze 8.x renamed the old "Win32GUI" base to lowercase
        # "gui" + made it cross-platform (the underlying behaviour on
        # Windows is still the legacy Win32GUI bootstrap).  Old name
        # raised DistutilsOptionError on cx_Freeze >= 8.0.
        base="gui" if sys.platform == "win32" else None,
        target_name="netcanon.exe",
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
    version=MSI_VERSION,
    description="Netcanon — Network Configuration Collector",
    author="Netcanon contributors",
    options={
        "build_exe": build_exe_options,
        "bdist_msi": bdist_msi_options,
    },
    executables=executables,
)
