"""
Backup job and result models.

A ``BackupJob`` is created when ``POST /api/v1/backups`` is called.  It is
stored in ``app.state.jobs`` (in-memory) and updated in the background as
each device is processed.  Callers poll ``GET /api/v1/backups/{job_id}``
for status.
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Lifecycle states of a backup job.

    Values are also used as display strings in the web UI.

    Terminal-state semantics for a job with multiple devices:
        * ``completed`` — every device succeeded.
        * ``partial``   — at least one device succeeded AND at least one failed.
        * ``failed``    — every device failed (zero successes).
    """

    pending = "pending"
    running = "running"
    completed = "completed"
    partial = "partial"
    failed = "failed"


class ConfigRecord(BaseModel):
    """Metadata for a configuration file that has been saved to disk.

    Attributes:
        device_type: The ``type_key`` of the source device definition.
        host: IP address or hostname of the source device.
        timestamp: UTC wall-clock time when collection completed.
        filename: Bare filename (no directory component) under the
            configured ``configs_dir``.
        file_extension: Extension without the leading dot (e.g. ``cfg``).
        size_bytes: File size at the time of writing.
        device_profile_id: UUID of the linked DeviceProfile, or None for
            ad-hoc backups.
    """

    device_type: str
    host: str
    timestamp: datetime
    filename: str
    file_extension: str
    size_bytes: int
    device_profile_id: str | None = None  # UUID of the linked DeviceProfile, or None for ad-hoc backups.


class BackupResult(BaseModel):
    """Outcome of a single device backup attempt within a job.

    Status follows a monotonic lifecycle:
        ``queued`` -> ``running`` -> ``success`` | ``failed``
    A result is created in ``queued`` state when the job starts and the
    backup runner mutates it in place as execution proceeds.  Once a
    terminal state (``success`` / ``failed``) is reached the result is
    never mutated again.  Polling clients can safely snapshot the list.

    Attributes:
        device_type: Source definition ``type_key``.
        host: Device address.
        status: Current lifecycle state — see above.
        config_record: Populated on ``success``; ``None`` otherwise.
        error: Human-readable error message on ``failed``; ``None`` otherwise.
        duration_seconds: Wall-clock time for the collection attempt;
            ``0.0`` while the device is still ``queued`` or ``running``.
    """

    device_type: str
    host: str
    status: Literal["queued", "running", "success", "failed"]
    config_record: ConfigRecord | None = None
    error: str | None = None
    duration_seconds: float


class BackupJob(BaseModel):
    """An in-progress or completed backup job.

    Jobs are created synchronously by the ``POST /api/v1/backups`` endpoint
    and run to completion in a FastAPI ``BackgroundTask``.

    Attributes:
        id: UUID4 string, generated at job creation.
        status: Current lifecycle state.
        results: Per-device results appended as each device completes.
        created_at: UTC time of job creation.
        completed_at: UTC time all devices finished; ``None`` while running.
        total_devices: Total device count (used for progress reporting).
        schedule_id: UUID of the schedule that triggered this job;
            ``None`` for manually triggered jobs.
        schedule_name: Snapshot of the schedule's name at run time
            (preserved even if the schedule is later renamed or
            deleted); ``None`` for manually triggered jobs.
    """

    id: str
    status: JobStatus = JobStatus.pending
    results: list[BackupResult] = Field(default_factory=list)
    created_at: datetime
    completed_at: datetime | None = None
    total_devices: int = 0
    schedule_id: str | None = None
    schedule_name: str | None = None
