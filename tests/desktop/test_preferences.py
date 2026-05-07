"""
Unit tests for ``netconfig_desktop.preferences.DesktopPreferences``.

Pure model + filesystem round-trip tests.  No Qt, no PySide6.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from netconfig_desktop.preferences import DesktopPreferences

pytestmark = pytest.mark.desktop


class TestDesktopPreferencesDefaults:
    def test_path_fields_default_to_none(self):
        prefs = DesktopPreferences()
        assert prefs.configs_dir is None
        assert prefs.definitions_dir is None
        assert prefs.data_dir is None

    def test_port_default(self):
        assert DesktopPreferences().port == 8765

    def test_open_in_editor_default_true(self):
        assert DesktopPreferences().open_in_editor is True

    def test_open_browser_on_start_default_false(self):
        assert DesktopPreferences().open_browser_on_start is False


class TestDesktopPreferencesValidation:
    def test_port_below_unprivileged_range_rejected(self):
        with pytest.raises(ValidationError):
            DesktopPreferences(port=80)

    def test_port_above_max_rejected(self):
        with pytest.raises(ValidationError):
            DesktopPreferences(port=70000)

    def test_port_within_range_accepted(self):
        # Both ends of the allowed range
        assert DesktopPreferences(port=1024).port == 1024
        assert DesktopPreferences(port=65535).port == 65535


class TestDesktopPreferencesLoad:
    def test_missing_file_returns_defaults(self, tmp_path):
        path = tmp_path / "no-such-file.json"
        prefs = DesktopPreferences.load(path)
        assert prefs.port == 8765
        assert prefs.configs_dir is None

    def test_corrupted_json_returns_defaults(self, tmp_path):
        path = tmp_path / "preferences.json"
        path.write_text("{not valid json", encoding="utf-8")
        prefs = DesktopPreferences.load(path)
        # No exception, fall back to factory defaults
        assert prefs.port == 8765

    def test_schema_mismatch_returns_defaults(self, tmp_path):
        path = tmp_path / "preferences.json"
        # port out of range — would raise ValidationError on direct
        # construction, but load() must swallow it.
        path.write_text(
            json.dumps({"port": 99999, "open_in_editor": False}),
            encoding="utf-8",
        )
        prefs = DesktopPreferences.load(path)
        assert prefs.port == 8765
        # open_in_editor falls back too — entire load is rejected
        assert prefs.open_in_editor is True

    def test_extra_fields_in_file_ignored_or_tolerated(self, tmp_path):
        # Pydantic's default is to ignore extras unless model_config
        # is strict.  We don't enforce strict, so unknown keys should
        # not cause load() to fall back to defaults.
        path = tmp_path / "preferences.json"
        path.write_text(
            json.dumps({"port": 9000, "future_unknown_key": "xyz"}),
            encoding="utf-8",
        )
        prefs = DesktopPreferences.load(path)
        assert prefs.port == 9000


class TestDesktopPreferencesRoundTrip:
    def test_save_then_load_preserves_all_fields(self, tmp_path):
        original = DesktopPreferences(
            configs_dir=Path("/tmp/configs"),
            definitions_dir=Path("/tmp/definitions"),
            data_dir=Path("/tmp/data"),
            port=9001,
            open_in_editor=False,
            open_browser_on_start=True,
        )
        path = tmp_path / "preferences.json"
        original.save(path)
        loaded = DesktopPreferences.load(path)
        assert loaded.configs_dir == Path("/tmp/configs")
        assert loaded.definitions_dir == Path("/tmp/definitions")
        assert loaded.data_dir == Path("/tmp/data")
        assert loaded.port == 9001
        assert loaded.open_in_editor is False
        assert loaded.open_browser_on_start is True

    def test_save_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "dir" / "preferences.json"
        prefs = DesktopPreferences(port=12345)
        prefs.save(nested)
        assert nested.exists()

    def test_path_fields_serialised_as_strings(self, tmp_path):
        prefs = DesktopPreferences(configs_dir=Path("/some/path"))
        path = tmp_path / "preferences.json"
        prefs.save(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Path -> string after JSON round-trip
        assert isinstance(raw["configs_dir"], str)
        assert raw["configs_dir"] in ("/some/path", "\\some\\path")

    def test_save_writes_indented_json(self, tmp_path):
        path = tmp_path / "preferences.json"
        DesktopPreferences().save(path)
        text = path.read_text(encoding="utf-8")
        # Should be pretty-printed (contain newlines), not minified
        assert "\n" in text

    def test_save_includes_none_fields_so_dialog_can_reset(self, tmp_path):
        path = tmp_path / "preferences.json"
        DesktopPreferences().save(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        # configs_dir is None in defaults — exclude_none=False keeps it
        assert "configs_dir" in raw
        assert raw["configs_dir"] is None
