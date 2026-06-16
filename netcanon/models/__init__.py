"""Domain models for devices, backup jobs, and stored configuration records."""

from __future__ import annotations

from .backup import BackupJob, BackupResult, ConfigRecord, JobStatus
from .device import BackupRequest, DeviceCredentials, DeviceTarget
from .diff import CompatibilityReport, DiffGroup, DiffLine, DiffReport, DiffRequest
from .migration import (
    CapabilityMatrix,
    CodecInfo,
    DeviceClass,
    LossyPath,
    MigrationJob,
    MigrationJobStatus,
    MigrationPlanRequest,
    TransformSpec,
    UnsupportedPath,
    ValidationReport,
    VendorInfo,
    XPathDelta,
)

__all__ = [
    "BackupJob",
    "BackupRequest",
    "BackupResult",
    "CapabilityMatrix",
    # Migration models (Phase 0)
    "CodecInfo",
    "CompatibilityReport",
    "ConfigRecord",
    "DeviceClass",
    "DeviceCredentials",
    "DeviceTarget",
    "DiffGroup",
    "DiffLine",
    "DiffReport",
    "DiffRequest",
    "JobStatus",
    "LossyPath",
    "MigrationJob",
    "MigrationJobStatus",
    "MigrationPlanRequest",
    "TransformSpec",
    "UnsupportedPath",
    "ValidationReport",
    "VendorInfo",
    "XPathDelta",
]
