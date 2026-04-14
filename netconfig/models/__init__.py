"""Domain models for devices, backup jobs, and stored configuration records."""

from .backup import BackupJob, BackupResult, ConfigRecord, JobStatus
from .device import BackupRequest, DeviceCredentials, DeviceTarget

__all__ = [
    "BackupJob",
    "BackupResult",
    "BackupRequest",
    "ConfigRecord",
    "DeviceCredentials",
    "DeviceTarget",
    "JobStatus",
]
