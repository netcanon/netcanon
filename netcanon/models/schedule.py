"""
Backup schedule models.

A ``BackupSchedule`` defines an automatic recurring backup job.
Schedules are persisted to disk as JSON and loaded at startup so that
automatic backups survive server restarts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator


class ScheduleDevice(BaseModel):
    """A device entry stored inside a schedule definition.

    Credentials are stored as plain strings so the schedule can be
    persisted to disk and executed without user interaction.  The data
    lives only on the local filesystem (``schedules/`` directory).

    Attributes:
        type_key: Must match a loaded definition ``type_key``.
        host: Hostname or IP address.
        port: SSH port.
        username: SSH login name.
        password: SSH login password (plain text for persistence).
        enable_password: Enable/privileged-mode password; ``None`` if not
            required for this device type.
    """

    type_key: str
    host: str
    port: int = Field(22, ge=1, le=65535)
    username: str
    password: str
    enable_password: str | None = None


class BackupSchedule(BaseModel):
    """A recurring backup schedule.

    Attributes:
        id: UUID4 string generated at creation.
        name: Human-readable label shown in the UI.
        enabled: When ``False`` the schedule is paused — the APScheduler
            job is removed but the definition is kept on disk.
        interval_minutes: How often the backup runs, in minutes.
        devices: Devices to back up on each run (legacy inline list, kept
            for backward compatibility with pre-profile schedules).
        target_type_keys: Back up all profiles whose ``type_key`` is in
            this list.
        target_device_ids: Back up the specific profile UUIDs in this list.
        created_at: UTC time the schedule was created.
        last_run_at: UTC time of the most recent triggered run.
        next_run_at: UTC time APScheduler will next fire this schedule;
            updated after each registration and each run.
        last_job_id: ID of the most recently triggered ``BackupJob``.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    enabled: bool = True
    interval_minutes: int = Field(ge=1)
    devices: list[ScheduleDevice] = []
    target_type_keys: list[str] = []   # back up all profiles of these type_keys
    target_device_ids: list[str] = []  # back up these specific profile UUIDs
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_job_id: str | None = None


class ScheduleCreate(BaseModel):
    """Request body for ``POST /api/v1/schedules/``.

    Attributes:
        name: Human-readable label.
        interval_minutes: Run frequency in minutes (minimum 1).
        target_type_keys: Back up all profiles whose ``type_key`` is in
            this list.
        target_device_ids: Back up the specific profile UUIDs in this list.

    At least one of ``target_type_keys`` or ``target_device_ids`` must be
    non-empty.
    """

    name: str
    interval_minutes: int = Field(ge=1, description="Interval between runs, in minutes")
    target_type_keys: list[str] = []
    target_device_ids: list[str] = []

    @model_validator(mode="after")
    def _at_least_one_target(self) -> "ScheduleCreate":
        if not self.target_type_keys and not self.target_device_ids:
            raise ValueError(
                "At least one of target_type_keys or target_device_ids must be non-empty"
            )
        return self
