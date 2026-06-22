"""
Device definition loading and schema validation.

A *device definition* is a YAML file that describes everything needed to
connect to a particular vendor/OS/version combination and retrieve its
running configuration.  The loader assembles these files into a
``dict[type_key, DeviceDefinition]`` that drives both the collection engine
and the web UI.

See ``library/README.md`` for the file format and extension guide.

The shipped definition library (the per-vendor ``*.yaml`` tree) lives at
:data:`LIBRARY_DIR` — a ``library/`` subdirectory *inside this package* so
that it is included in the built wheel as package data and resolvable after
a plain ``pip install`` (no working-directory or checkout assumptions).  See
``pyproject.toml`` ``[tool.setuptools.package-data]`` and
:func:`netcanon.config.Settings`'s ``definitions_dir`` default.
"""

from __future__ import annotations

from pathlib import Path

from .loader import DefinitionLoader
from .schema import (
    CollectorConfig,
    CommandConfig,
    ConnectionConfig,
    DeviceDefinition,
    PromptConfig,
)

#: Absolute path to the bundled device-definition library shipped inside the
#: package (``netcanon/definitions/library/``).  This is the default root the
#: application loads from, so a wheel-installed server works out of the box.
#: Operators override it with ``NETCANON_DEFINITIONS_DIR`` (or the desktop
#: preferences dialog).  Resolved relative to this file rather than the CWD so
#: it is correct regardless of where the process is launched.
LIBRARY_DIR: Path = Path(__file__).resolve().parent / "library"

__all__ = [
    "LIBRARY_DIR",
    "CollectorConfig",
    "CommandConfig",
    "ConnectionConfig",
    "DefinitionLoader",
    "DeviceDefinition",
    "PromptConfig",
]
