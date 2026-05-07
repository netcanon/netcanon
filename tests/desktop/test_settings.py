"""
Unit tests for ``netconfig_desktop.settings``.

Covers path resolution in both *dev* (unfrozen) and *frozen* modes,
including the ``DesktopPreferences`` overlay applied in frozen mode.
No real filesystem paths outside ``tmp_path`` are accessed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from netconfig_desktop.settings import DESKTOP_PORT, desktop_settings

pytestmark = pytest.mark.desktop


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


class TestDesktopSettingsPreferencesOverlay:
    """In frozen mode, ``preferences.json`` overrides platform defaults."""

    def _frozen_env(self, tmp_path):
        """Construct the standard frozen-mode patch context tuple."""
        fake_exe = tmp_path / "netconfig.exe"
        fake_exe.touch()
        fake_appdata = tmp_path / "AppData" / "Roaming"
        fake_appdata.mkdir(parents=True)
        return fake_exe, fake_appdata

    def test_no_preferences_file_uses_defaults(self, tmp_path):
        """Regression guard: frozen mode without preferences.json is
        unchanged from the pre-overlay behaviour."""
        fake_exe, fake_appdata = self._frozen_env(tmp_path)
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(fake_exe)),
            patch.dict(os.environ, {"APPDATA": str(fake_appdata)}),
        ):
            settings = desktop_settings()

        # Defaults: configs under APPDATA, definitions beside EXE,
        # port == DESKTOP_PORT, open_in_editor True, data_dir None.
        assert settings.configs_dir == fake_appdata / "NetConfig" / "configs"
        assert settings.definitions_dir == tmp_path / "definitions"
        assert settings.port == DESKTOP_PORT
        assert settings.open_in_editor is True
        assert settings.data_dir is None

    def test_preferences_overrides_paths_and_port(self, tmp_path):
        fake_exe, fake_appdata = self._frozen_env(tmp_path)
        prefs_path = fake_appdata / "NetConfig" / "preferences.json"
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
        custom_configs = tmp_path / "custom_configs"
        custom_definitions = tmp_path / "custom_definitions"
        custom_data = tmp_path / "custom_data"
        prefs_path.write_text(
            json.dumps({
                "configs_dir": str(custom_configs),
                "definitions_dir": str(custom_definitions),
                "data_dir": str(custom_data),
                "port": 9100,
                "open_in_editor": False,
            }),
            encoding="utf-8",
        )

        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(fake_exe)),
            patch.dict(os.environ, {"APPDATA": str(fake_appdata)}),
        ):
            settings = desktop_settings()

        assert settings.configs_dir == custom_configs
        assert settings.definitions_dir == custom_definitions
        assert settings.data_dir == custom_data
        assert settings.port == 9100
        assert settings.open_in_editor is False

    def test_partial_preferences_overlay_keeps_other_defaults(self, tmp_path):
        """Only fields present in the file should override; the rest
        keep platform defaults."""
        fake_exe, fake_appdata = self._frozen_env(tmp_path)
        prefs_path = fake_appdata / "NetConfig" / "preferences.json"
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
        prefs_path.write_text(
            json.dumps({"port": 9200}),  # only port specified
            encoding="utf-8",
        )

        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(fake_exe)),
            patch.dict(os.environ, {"APPDATA": str(fake_appdata)}),
        ):
            settings = desktop_settings()

        assert settings.port == 9200
        # Platform defaults still apply for the unspecified path fields
        assert settings.configs_dir == fake_appdata / "NetConfig" / "configs"
        assert settings.definitions_dir == tmp_path / "definitions"

    def test_corrupted_preferences_falls_back_to_defaults(self, tmp_path):
        """Preferences corruption must never block desktop startup."""
        fake_exe, fake_appdata = self._frozen_env(tmp_path)
        prefs_path = fake_appdata / "NetConfig" / "preferences.json"
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
        prefs_path.write_text("{ not valid json", encoding="utf-8")

        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(fake_exe)),
            patch.dict(os.environ, {"APPDATA": str(fake_appdata)}),
        ):
            settings = desktop_settings()  # Must not raise

        assert settings.port == DESKTOP_PORT
        assert settings.configs_dir == fake_appdata / "NetConfig" / "configs"

    def test_dev_mode_ignores_preferences_file(self, tmp_path):
        """Dev mode uses repo-relative defaults regardless of the
        preferences file; this keeps contributor workflow predictable."""
        fake_appdata = tmp_path / "AppData" / "Roaming"
        fake_appdata.mkdir(parents=True)
        prefs_path = fake_appdata / "NetConfig" / "preferences.json"
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
        prefs_path.write_text(
            json.dumps({"port": 9500, "configs_dir": str(tmp_path / "x")}),
            encoding="utf-8",
        )

        with (
            patch.object(sys, "frozen", False, create=True),
            patch.dict(os.environ, {"APPDATA": str(fake_appdata)}),
        ):
            settings = desktop_settings()

        # Dev defaults survive
        repo_root = Path(__file__).parent.parent.parent
        assert settings.configs_dir == repo_root / "configs"
        assert settings.port == DESKTOP_PORT
