"""Domain models for devices, backup jobs, and stored configuration records."""

from .backup import BackupJob, BackupResult, ConfigRecord, JobStatus
from .device import BackupRequest, DeviceCredentials, DeviceTarget
from .diff import CompatibilityReport, DiffGroup, DiffLine, DiffReport, DiffRequest

__all__ = [
    "BackupJob",
    "BackupResult",
    "BackupRequest",
    "CompatibilityReport",
    "ConfigRecord",
    "DeviceCredentials",
    "DeviceTarget",
    "DiffGroup",
    "DiffLine",
    "DiffReport",
    "DiffRequest",
    "JobStatus",
]
