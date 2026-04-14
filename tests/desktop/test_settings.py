"""
Unit tests for ``netconfig_desktop.settings``.

Covers path resolution in both *dev* (unfrozen) and *frozen* modes.
No real filesystem paths outside ``tmp_path`` are accessed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from netconfig_desktop.settings import DESKTOP_PORT, desktop_settings


class TestDesktopPort:
    def test_port_value(self):
        assert DESKTOP_PORT == 8765


class TestDesktopSettingsDev:
    """When ``sys.frozen`` is absent the settings use the repo-relative paths."""

    def test_definitions_dir_is_repo_relative(self, tmp_path):
        # Ensure sys.frozen is not set
        with patch.object(sys, "frozen", False, create=True):
            settings = desktop_settings()
        # definitions_dir should be <repo_root>/definitions
        repo_root = Path(__file__).parent.parent.parent
        assert settings.definitions_dir == repo_root / "definitions"

    def test_configs_dir_is_repo_relative(self, tmp_path):
        with patch.object(sys, "frozen", False, create=True):
            settings = desktop_settings()
        repo_root = Path(__file__).parent.parent.parent
        assert settings.configs_dir == repo_root / "configs"

    def test_configs_dir_is_created(self, tmp_path):
        # Even in dev mode the configs dir must exist after desktop_settings()
        with patch.object(sys, "frozen", False, create=True):
            settings = desktop_settings()
        assert settings.configs_dir.exists()

    def test_host_is_loopback(self):
        with patch.object(sys, "frozen", False, create=True):
            settings = desktop_settings()
        assert settings.host == "127.0.0.1"

    def test_port(self):
        with patch.object(sys, "frozen", False, create=True):
            settings = desktop_settings()
        assert settings.port == DESKTOP_PORT


class TestDesktopSettingsFrozen:
    """When ``sys.frozen`` is ``True`` (cx_Freeze) use APPDATA-based paths."""

    def test_configs_dir_under_appdata(self, tmp_path):
        fake_exe = tmp_path / "netconfig.exe"
        fake_exe.touch()
        fake_appdata = tmp_path / "AppData" / "Roaming"
        fake_appdata.mkdir(parents=True)

        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(fake_exe)),
            patch.dict(os.environ, {"APPDATA": str(fake_appdata)}),
        ):
            settings = desktop_settings()

        assert settings.configs_dir == fake_appdata / "NetConfig" / "configs"

    def test_definitions_dir_beside_exe(self, tmp_path):
        fake_exe = tmp_path / "netconfig.exe"
        fake_exe.touch()
        fake_appdata = tmp_path / "AppData" / "Roaming"
        fake_appdata.mkdir(parents=True)

        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(fake_exe)),
            patch.dict(os.environ, {"APPDATA": str(fake_appdata)}),
        ):
            settings = desktop_settings()

        assert settings.definitions_dir == tmp_path / "definitions"

    def test_configs_dir_created_in_frozen_mode(self, tmp_path):
        fake_exe = tmp_path / "netconfig.exe"
        fake_exe.touch()
        fake_appdata = tmp_path / "AppData" / "Roaming"
        fake_appdata.mkdir(parents=True)

        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(fake_exe)),
            patch.dict(os.environ, {"APPDATA": str(fake_appdata)}),
        ):
            settings = desktop_settings()

        assert settings.configs_dir.exists()
