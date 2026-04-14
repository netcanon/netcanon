"""
Unit tests for ``netconfig.storage.file_store.FileConfigStore``.

All I/O is directed to pytest's ``tmp_path`` — no network, no shared state.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from netconfig.storage.file_store import FileConfigStore

pytestmark = pytest.mark.unit


def _ts(
    year: int = 2026,
    month: int = 4,
    day: int = 14,
    hour: int = 12,
    minute: int = 0,
    second: int = 0,
) -> datetime:
    """Return a UTC datetime for use as a stable timestamp in tests."""
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# save() — basic contract
# ---------------------------------------------------------------------------


class TestFileConfigStoreSave:
    def test_save_creates_file_on_disk(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        record = store.save("Cisco", "192.168.1.1", _ts(), "cfg", "hostname R1\n!")
        assert store.resolve_path(record.filename).exists()

    def test_save_filename_follows_convention(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        record = store.save("Cisco", "192.168.1.1", _ts(), "cfg", "x")
        assert record.filename == "Cisco_192-168-1-1_20260414_120000.cfg"

    def test_save_creates_subdirectory(self, tmp_path: Path):
        """Files must land in {device_type}/{safe_host}/ not in the root."""
        store = FileConfigStore(tmp_path)
        record = store.save("Cisco", "192.168.1.1", _ts(), "cfg", "x")
        expected_dir = tmp_path / "Cisco" / "192-168-1-1"
        assert (expected_dir / record.filename).exists()

    def test_save_dots_in_host_become_hyphens(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        record = store.save("Cisco", "10.0.0.1", _ts(), "cfg", "x")
        assert "10-0-0-1" in record.filename
        assert "." not in record.filename.split("_")[1]

    def test_save_colons_in_host_become_hyphens(self, tmp_path: Path):
        """IPv6 addresses contain colons — they must be replaced."""
        store = FileConfigStore(tmp_path)
        record = store.save("Cisco", "::1", _ts(), "cfg", "x")
        assert ":" not in record.filename

    def test_save_returns_correct_metadata(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        record = store.save("Cisco", "10.0.0.1", _ts(), "cfg", "some config")
        assert record.device_type == "Cisco"
        assert record.host == "10.0.0.1"
        assert record.timestamp == _ts()
        assert record.file_extension == "cfg"

    def test_save_records_correct_size(self, tmp_path: Path):
        content = "hostname Router\n!"
        store = FileConfigStore(tmp_path)
        record = store.save("Cisco", "1.2.3.4", _ts(), "cfg", content)
        saved_path = store.resolve_path(record.filename)
        assert record.size_bytes == saved_path.stat().st_size

    def test_save_file_content_is_preserved(self, tmp_path: Path):
        content = "hostname Router\ninterface Gi0\n!"
        store = FileConfigStore(tmp_path)
        record = store.save("Cisco", "1.2.3.4", _ts(), "cfg", content)
        assert store.resolve_path(record.filename).read_text(encoding="utf-8") == content

    def test_save_xml_extension(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        record = store.save("OPNsense", "192.168.1.1", _ts(), "xml", "<config/>")
        assert record.filename.endswith(".xml")
        assert record.file_extension == "xml"

    def test_save_creates_storage_dir_if_missing(self, tmp_path: Path):
        store = FileConfigStore(tmp_path / "new_subdir")
        record = store.save("Cisco", "1.2.3.4", _ts(), "cfg", "x")
        assert store.resolve_path(record.filename).exists()

    def test_save_different_devices_different_files(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        r1 = store.save("Cisco", "1.1.1.1", _ts(second=0), "cfg", "cisco")
        r2 = store.save("OPNsense", "2.2.2.2", _ts(second=1), "xml", "<op/>")
        assert r1.filename != r2.filename


# ---------------------------------------------------------------------------
# save() — collision safety
# ---------------------------------------------------------------------------


class TestCollisionSafety:
    def test_same_second_backup_gets_unique_filename(self, tmp_path: Path):
        """Two saves within the same second must not overwrite each other."""
        store = FileConfigStore(tmp_path)
        r1 = store.save("Cisco", "1.1.1.1", _ts(), "cfg", "first")
        r2 = store.save("Cisco", "1.1.1.1", _ts(), "cfg", "second")
        assert r1.filename != r2.filename

    def test_collision_suffix_appended(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        store.save("Cisco", "1.1.1.1", _ts(), "cfg", "first")
        r2 = store.save("Cisco", "1.1.1.1", _ts(), "cfg", "second")
        assert "_1" in r2.filename

    def test_both_collision_files_readable(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        r1 = store.save("Cisco", "1.1.1.1", _ts(), "cfg", "first")
        r2 = store.save("Cisco", "1.1.1.1", _ts(), "cfg", "second")
        assert store.get_content(r1.filename) == "first"
        assert store.get_content(r2.filename) == "second"

    def test_triple_collision(self, tmp_path: Path):
        """Suffix counter must increment correctly past _1."""
        store = FileConfigStore(tmp_path)
        store.save("Cisco", "1.1.1.1", _ts(), "cfg", "a")
        store.save("Cisco", "1.1.1.1", _ts(), "cfg", "b")
        r3 = store.save("Cisco", "1.1.1.1", _ts(), "cfg", "c")
        assert "_2" in r3.filename


# ---------------------------------------------------------------------------
# resolve_path()
# ---------------------------------------------------------------------------


class TestResolvePath:
    def test_resolve_finds_subdirectory_file(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        record = store.save("Cisco", "192.168.1.1", _ts(), "cfg", "x")
        path = store.resolve_path(record.filename)
        assert path.exists()
        assert path.parent.name == "192-168-1-1"

    def test_resolve_flat_fallback(self, tmp_path: Path):
        """Files placed directly in the root (pre-migration) must still be found."""
        store = FileConfigStore(tmp_path)
        flat_file = tmp_path / "Cisco_192-168-1-1_20260414_120000.cfg"
        flat_file.write_text("flat", encoding="utf-8")
        path = store.resolve_path("Cisco_192-168-1-1_20260414_120000.cfg")
        assert path == flat_file

    def test_resolve_missing_raises_file_not_found(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        with pytest.raises(FileNotFoundError, match="ghost.cfg"):
            store.resolve_path("ghost.cfg")


# ---------------------------------------------------------------------------
# Startup migration
# ---------------------------------------------------------------------------


class TestStartupMigration:
    def test_flat_files_moved_to_subdir_on_init(self, tmp_path: Path):
        """Flat config files in the root must be moved into subdirs at startup."""
        flat = tmp_path / "Cisco_192-168-1-1_20260414_120000.cfg"
        flat.write_text("config", encoding="utf-8")
        FileConfigStore(tmp_path)  # triggers migration
        assert not flat.exists()
        moved = tmp_path / "Cisco" / "192-168-1-1" / "Cisco_192-168-1-1_20260414_120000.cfg"
        assert moved.exists()

    def test_flat_files_content_preserved_after_migration(self, tmp_path: Path):
        flat = tmp_path / "Cisco_10-0-0-1_20260414_120000.cfg"
        flat.write_text("preserved content", encoding="utf-8")
        store = FileConfigStore(tmp_path)
        moved = tmp_path / "Cisco" / "10-0-0-1" / "Cisco_10-0-0-1_20260414_120000.cfg"
        assert moved.read_text(encoding="utf-8") == "preserved content"

    def test_non_config_flat_files_not_moved(self, tmp_path: Path):
        readme = tmp_path / "README.txt"
        readme.write_text("not a config", encoding="utf-8")
        logfile = tmp_path / "backup.log"
        logfile.write_text("log", encoding="utf-8")
        FileConfigStore(tmp_path)
        assert readme.exists()
        assert logfile.exists()

    def test_multiple_flat_files_all_migrated(self, tmp_path: Path):
        files = [
            "Cisco_1-1-1-1_20260414_120000.cfg",
            "OPNsense_2-2-2-2_20260414_120001.xml",
        ]
        for f in files:
            (tmp_path / f).write_text("x", encoding="utf-8")
        FileConfigStore(tmp_path)
        for f in files:
            assert not (tmp_path / f).exists()

    def test_migration_idempotent(self, tmp_path: Path):
        """Constructing FileConfigStore twice must not error."""
        flat = tmp_path / "Cisco_1-1-1-1_20260414_120000.cfg"
        flat.write_text("x", encoding="utf-8")
        FileConfigStore(tmp_path)
        FileConfigStore(tmp_path)  # second init — file is already in subdir


# ---------------------------------------------------------------------------
# list_configs()
# ---------------------------------------------------------------------------


class TestFileConfigStoreList:
    def test_empty_store_returns_empty_list(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        assert store.list_configs() == []

    def test_saved_file_appears_in_list(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        store.save("Cisco", "1.2.3.4", _ts(), "cfg", "x")
        records = store.list_configs()
        assert len(records) == 1
        assert records[0].device_type == "Cisco"

    def test_list_sorted_newest_first(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        old_ts = _ts(day=1)
        new_ts = _ts(day=2)
        store.save("Cisco", "1.1.1.1", old_ts, "cfg", "old")
        store.save("Cisco", "2.2.2.2", new_ts, "cfg", "new")
        records = store.list_configs()
        assert records[0].timestamp == new_ts
        assert records[1].timestamp == old_ts

    def test_list_ignores_non_matching_filenames(self, tmp_path: Path):
        (tmp_path / "README.txt").write_text("ignore", encoding="utf-8")
        (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
        (tmp_path / "partial_name.cfg").write_text("partial", encoding="utf-8")
        store = FileConfigStore(tmp_path)
        assert store.list_configs() == []

    def test_list_multiple_device_types(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        store.save("Cisco", "1.1.1.1", _ts(second=0), "cfg", "cisco")
        store.save("OPNsense", "2.2.2.2", _ts(second=1), "xml", "<op/>")
        records = store.list_configs()
        device_types = {r.device_type for r in records}
        assert device_types == {"Cisco", "OPNsense"}

    def test_list_returns_all_saved(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        for i in range(5):
            store.save("Cisco", f"1.1.1.{i}", _ts(second=i), "cfg", f"content{i}")
        assert len(store.list_configs()) == 5

    def test_list_finds_files_in_subdirectories(self, tmp_path: Path):
        """rglob must pick up files regardless of nesting depth."""
        store = FileConfigStore(tmp_path)
        store.save("Cisco", "1.1.1.1", _ts(), "cfg", "nested")
        assert len(store.list_configs()) == 1


# ---------------------------------------------------------------------------
# get_content()
# ---------------------------------------------------------------------------


class TestFileConfigStoreGetContent:
    def test_get_existing_file(self, tmp_path: Path):
        content = "hostname Test\n!"
        store = FileConfigStore(tmp_path)
        record = store.save("Cisco", "1.2.3.4", _ts(), "cfg", content)
        assert store.get_content(record.filename) == content

    def test_get_missing_file_raises_file_not_found(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        with pytest.raises(FileNotFoundError, match="nonexistent.cfg"):
            store.get_content("nonexistent.cfg")

    def test_get_preserves_multiline_content(self, tmp_path: Path):
        content = "line1\nline2\nline3\n"
        store = FileConfigStore(tmp_path)
        record = store.save("Cisco", "1.2.3.4", _ts(), "cfg", content)
        assert store.get_content(record.filename) == content


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------


class TestFileConfigStoreDelete:
    def test_delete_removes_file_from_disk(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        record = store.save("Cisco", "1.2.3.4", _ts(), "cfg", "x")
        store.delete(record.filename)
        with pytest.raises(FileNotFoundError):
            store.resolve_path(record.filename)

    def test_delete_removes_from_list(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        record = store.save("Cisco", "1.2.3.4", _ts(), "cfg", "x")
        store.delete(record.filename)
        assert store.list_configs() == []

    def test_delete_missing_file_raises_file_not_found(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        with pytest.raises(FileNotFoundError, match="ghost.cfg"):
            store.delete("ghost.cfg")

    def test_delete_one_leaves_others(self, tmp_path: Path):
        store = FileConfigStore(tmp_path)
        r1 = store.save("Cisco", "1.1.1.1", _ts(second=0), "cfg", "a")
        r2 = store.save("Cisco", "2.2.2.2", _ts(second=1), "cfg", "b")
        store.delete(r1.filename)
        remaining = store.list_configs()
        assert len(remaining) == 1
        assert remaining[0].filename == r2.filename
