"""Backup runner: an unknown ``type_key`` must produce an honest per-device
failure, never a false ``completed`` or a job stranded at ``running``
(blind audit ``81d9740`` T0-2).

Before the fix, ``family_base = definitions[device.type_key]`` was a bare dict
subscript *outside* the per-device try/except. A typo'd / renamed ``type_key``
is ordinary operator data — device profiles and schedules do not validate it
against the loaded library — so it raised ``KeyError``:

* the **serial** path let it escape ``run_backup_job`` entirely, so the job was
  stranded at ``running`` forever and never persisted; and
* the **parallel** path logged-but-did-not-raise the future exception, leaving
  the device ``queued`` so the terminal logic counted zero failures and marked
  the job ``completed`` though the device never ran.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from netcanon.config import Settings
from netcanon.models.backup import BackupJob, ConfigRecord, JobStatus
from netcanon.models.device import BackupRequest, DeviceCredentials, DeviceTarget
from netcanon.services import backup_runner

pytestmark = pytest.mark.unit

# No probe command (skips the probe branch without a loader) + a file extension.
_STUB_DEF = SimpleNamespace(probe=SimpleNamespace(command=""), file_extension="txt")


class _OkCollector:
    """Returns a config without touching the network (known-type devices)."""

    def collect(self, device, definition) -> str:
        return "synthetic-config"


class _StubStorage:
    def save(self, *, device_type, host, timestamp, extension, content,
             device_profile_id=None) -> ConfigRecord:
        return ConfigRecord(
            device_type=device_type, host=host, timestamp=timestamp,
            filename=f"{host}.{extension}", file_extension=extension,
            size_bytes=len(content), device_profile_id=device_profile_id,
        )


def _job() -> BackupJob:
    return BackupJob(id="job", created_at=datetime.now(UTC))


def _device(type_key: str, host: str) -> DeviceTarget:
    return DeviceTarget(
        type_key=type_key, host=host,
        credentials=DeviceCredentials(username="u", password="p"),
    )


def _run(job: BackupJob, devices: list[DeviceTarget],
         definitions: dict) -> None:
    # get_collector is only reached for KNOWN types — the unknown-type guard
    # returns before any collector is built; patch it anyway for the mixed case.
    with patch("netcanon.api.routes.backups.get_collector",
               return_value=_OkCollector()):
        backup_runner.run_backup_job(
            job, BackupRequest(devices=devices), definitions,
            storage=_StubStorage(), settings=Settings(),
        )


def test_unknown_type_key_serial_marks_job_failed_not_stuck_running():
    # Single device -> serial fast-path. Must not raise; must not strand the
    # job at `running`.
    job = _job()
    _run(job, [_device("NOPE", "10.0.0.1")], {"X": _STUB_DEF})
    assert job.status is JobStatus.failed
    assert job.completed_at is not None          # reached the terminal block
    assert job.results[0].status == "failed"
    assert "unknown device type" in (job.results[0].error or "").lower()


def test_unknown_type_key_parallel_not_false_completed():
    # >1 device -> parallel path, where the future exception was historically
    # logged-not-raised and the device left `queued` -> false `completed`.
    job = _job()
    _run(job, [_device("NOPE", "10.0.0.1"), _device("NOPE", "10.0.0.2")],
         {"X": _STUB_DEF})
    assert job.status is JobStatus.failed
    assert all(r.status == "failed" for r in job.results)
    # No device may be left in a non-terminal state at the end of the job.
    assert all(r.status in ("success", "failed") for r in job.results)


def test_mixed_known_and_unknown_type_key_is_partial():
    # One good device + one unknown type -> partial, never a clean completed.
    job = _job()
    _run(job, [_device("X", "10.0.0.1"), _device("NOPE", "10.0.0.2")],
         {"X": _STUB_DEF})
    assert job.status is JobStatus.partial
    by_host = {r.host: r for r in job.results}
    assert by_host["10.0.0.1"].status == "success"
    assert by_host["10.0.0.2"].status == "failed"
