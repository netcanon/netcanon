"""
Unit tests for ``netcanon.storage.job_store.FileJobStore`` and
``netcanon.storage.schedule_store.FileScheduleStore``.

All I/O is directed to pytest's ``tmp_path`` — no network, no shared state.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from netcanon.models.backup import BackupJob, JobStatus
from netcanon.models.schedule import BackupSchedule, ScheduleDevice
from netcanon.storage.job_store import FileJobStore
from netcanon.storage.schedule_store import FileScheduleStore

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _make_job(
    *,
    status: JobStatus = JobStatus.completed,
    total_devices: int = 3,
    created_at: datetime | None = None,
) -> BackupJob:
    """Return a minimal ``BackupJob`` suitable for persistence tests."""
    return BackupJob(
        id=str(uuid.uuid4()),
        status=status,
        total_devices=total_devices,
        created_at=created_at or _ts(),
    )


def _make_schedule(
    *,
    name: str = "nightly",
    interval_minutes: int = 60,
) -> BackupSchedule:
    """Return a minimal ``BackupSchedule`` suitable for persistence tests."""
    device = ScheduleDevice(
        type_key="Cisco",
        host="192.168.1.1",
        username="admin",
        password="secret",
    )
    return BackupSchedule(
        name=name,
        interval_minutes=interval_minutes,
        devices=[device],
    )


# ---------------------------------------------------------------------------
# FileJobStore — save()
# ---------------------------------------------------------------------------


class TestFileJobStoreSave:
    def test_save_creates_json_file_named_after_job_id(self, tmp_path: Path):
        store = FileJobStore(tmp_path)
        job = _make_job()
        store.save(job)
        assert (tmp_path / f"{job.id}.json").exists()

    def test_save_creates_store_directory_if_missing(self, tmp_path: Path):
        jobs_dir = tmp_path / "new_jobs_dir"
        assert not jobs_dir.exists()
        store = FileJobStore(jobs_dir)
        job = _make_job()
        store.save(job)
        assert (jobs_dir / f"{job.id}.json").exists()

    def test_save_round_trips_correctly_via_model_validate_json(self, tmp_path: Path):
        store = FileJobStore(tmp_path)
        job = _make_job(status=JobStatus.completed, total_devices=5, created_at=_ts())
        store.save(job)
        raw = (tmp_path / f"{job.id}.json").read_text(encoding="utf-8")
        loaded = BackupJob.model_validate_json(raw)
        assert loaded.id == job.id
        assert loaded.status == job.status
        assert loaded.total_devices == job.total_devices
        assert loaded.created_at == job.created_at


# ---------------------------------------------------------------------------
# FileJobStore — load_all()
# ---------------------------------------------------------------------------


class TestFileJobStoreLoadAll:
    def test_empty_directory_returns_empty_dict(self, tmp_path: Path):
        store = FileJobStore(tmp_path)
        assert store.load_all() == {}

    def test_after_one_save_load_all_returns_one_entry_keyed_by_job_id(
        self, tmp_path: Path
    ):
        store = FileJobStore(tmp_path)
        job = _make_job()
        store.save(job)
        result = store.load_all()
        assert len(result) == 1
        assert job.id in result

    def test_after_two_saves_load_all_returns_both_entries(self, tmp_path: Path):
        store = FileJobStore(tmp_path)
        job_a = _make_job(created_at=_ts(second=0))
        job_b = _make_job(created_at=_ts(second=1))
        store.save(job_a)
        store.save(job_b)
        result = store.load_all()
        assert len(result) == 2
        assert job_a.id in result
        assert job_b.id in result

    def test_load_all_silently_skips_corrupt_json_file(self, tmp_path: Path):
        store = FileJobStore(tmp_path)
        garbage_file = tmp_path / "badjob.json"
        garbage_file.write_text("not valid json }{", encoding="utf-8")
        # must not raise
        result = store.load_all()
        assert result == {}

    def test_load_all_preserves_status_total_devices_and_created_at(
        self, tmp_path: Path
    ):
        store = FileJobStore(tmp_path)
        job = _make_job(
            status=JobStatus.failed,
            total_devices=7,
            created_at=_ts(hour=9, minute=30),
        )
        store.save(job)
        loaded = store.load_all()[job.id]
        assert loaded.status == JobStatus.failed
        assert loaded.total_devices == 7
        assert loaded.created_at == _ts(hour=9, minute=30)


# ---------------------------------------------------------------------------
# FileJobStore — load_one() (R8 lazy-load fallback)
# ---------------------------------------------------------------------------


class TestFileJobStoreLoadOne:
    """``load_one`` powers ``BackupJobRegistry``'s disk fallback for
    get-by-id when the job has been evicted from the in-memory cache.
    Same parse + corrupt-skip semantics as ``load_all`` but for a
    single record."""

    def test_load_one_returns_job_when_file_exists(self, tmp_path: Path):
        store = FileJobStore(tmp_path)
        job = _make_job()
        store.save(job)
        result = store.load_one(job.id)
        assert result is not None
        assert result.id == job.id
        assert result.status == job.status

    def test_load_one_returns_none_when_file_missing(self, tmp_path: Path):
        """No file → ``None``.  Callers (BackupJobRegistry) translate
        this to ``KeyError`` to match dict semantics."""
        store = FileJobStore(tmp_path)
        result = store.load_one("nonexistent-job-id")
        assert result is None

    def test_load_one_returns_none_for_corrupt_file(self, tmp_path: Path):
        """Corrupt JSON → ``None`` (same behaviour as a missing file).
        Corruption is logged for operator visibility but doesn't
        propagate as an exception — same defensive pattern as
        ``load_all``."""
        store = FileJobStore(tmp_path)
        corrupt_id = "corrupt-id"
        (tmp_path / f"{corrupt_id}.json").write_text("not valid JSON")
        result = store.load_one(corrupt_id)
        assert result is None

    def test_load_one_round_trip_preserves_fields(self, tmp_path: Path):
        store = FileJobStore(tmp_path)
        job = _make_job(
            status=JobStatus.partial,
            total_devices=5,
            created_at=_ts(hour=14, minute=22),
        )
        store.save(job)
        result = store.load_one(job.id)
        assert result is not None
        assert result.status == JobStatus.partial
        assert result.total_devices == 5
        assert result.created_at == _ts(hour=14, minute=22)


# ---------------------------------------------------------------------------
# FileJobStore — list_job_ids() (R8 disk-scan diagnostics)
# ---------------------------------------------------------------------------


class TestFileJobStoreListJobIds:
    """Cheap directory scan used by ``BackupJobRegistry.total_disk_count``
    + diagnostic endpoints.  Returns only filenames — does not parse
    the JSON files."""

    def test_list_empty_dir_returns_empty_list(self, tmp_path: Path):
        store = FileJobStore(tmp_path)
        assert store.list_job_ids() == []

    def test_list_returns_one_id_per_json_file(self, tmp_path: Path):
        store = FileJobStore(tmp_path)
        jobs = [_make_job() for _ in range(3)]
        for j in jobs:
            store.save(j)
        result = store.list_job_ids()
        assert sorted(result) == sorted(j.id for j in jobs)

    def test_list_ignores_non_json_files(self, tmp_path: Path):
        store = FileJobStore(tmp_path)
        (tmp_path / "stray.txt").write_text("not a job")
        (tmp_path / "readme.md").write_text("# notes")
        store.save(_make_job())
        result = store.list_job_ids()
        assert len(result) == 1


# ---------------------------------------------------------------------------
# FileScheduleStore — save()
# ---------------------------------------------------------------------------


class TestFileScheduleStoreSave:
    def test_save_creates_json_file_named_after_schedule_id(self, tmp_path: Path):
        store = FileScheduleStore(tmp_path)
        schedule = _make_schedule()
        store.save(schedule)
        assert (tmp_path / f"{schedule.id}.json").exists()

    def test_save_creates_store_directory_if_missing(self, tmp_path: Path):
        schedules_dir = tmp_path / "new_schedules_dir"
        assert not schedules_dir.exists()
        store = FileScheduleStore(schedules_dir)
        schedule = _make_schedule()
        store.save(schedule)
        assert (schedules_dir / f"{schedule.id}.json").exists()

    def test_save_round_trip_preserves_name_and_interval_minutes(
        self, tmp_path: Path
    ):
        store = FileScheduleStore(tmp_path)
        schedule = _make_schedule(name="hourly-backup", interval_minutes=60)
        store.save(schedule)
        result = store.load_all()
        loaded = result[schedule.id]
        assert loaded.name == "hourly-backup"
        assert loaded.interval_minutes == 60


# ---------------------------------------------------------------------------
# FileScheduleStore — delete()
# ---------------------------------------------------------------------------


class TestFileScheduleStoreDelete:
    def test_delete_removes_file_from_disk(self, tmp_path: Path):
        store = FileScheduleStore(tmp_path)
        schedule = _make_schedule()
        store.save(schedule)
        assert (tmp_path / f"{schedule.id}.json").exists()
        store.delete(schedule.id)
        assert not (tmp_path / f"{schedule.id}.json").exists()

    def test_delete_on_nonexistent_id_does_nothing(self, tmp_path: Path):
        store = FileScheduleStore(tmp_path)
        # must not raise FileNotFoundError
        store.delete(str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# FileScheduleStore — load_all()
# ---------------------------------------------------------------------------


class TestFileScheduleStoreLoadAll:
    def test_empty_directory_returns_empty_dict(self, tmp_path: Path):
        store = FileScheduleStore(tmp_path)
        assert store.load_all() == {}

    def test_after_save_load_all_entry_keyed_by_schedule_id(self, tmp_path: Path):
        store = FileScheduleStore(tmp_path)
        schedule = _make_schedule()
        store.save(schedule)
        result = store.load_all()
        assert schedule.id in result

    def test_after_save_and_delete_load_all_returns_empty_dict(self, tmp_path: Path):
        store = FileScheduleStore(tmp_path)
        schedule = _make_schedule()
        store.save(schedule)
        store.delete(schedule.id)
        assert store.load_all() == {}

    def test_load_all_silently_skips_corrupt_json_file(self, tmp_path: Path):
        store = FileScheduleStore(tmp_path)
        garbage_file = tmp_path / "badsched.json"
        garbage_file.write_text("{corrupt: true,,,}", encoding="utf-8")
        # must not raise
        result = store.load_all()
        assert result == {}
