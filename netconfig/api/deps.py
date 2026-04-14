"""
FastAPI dependency providers.

These functions are injected via ``Depends()`` into route handlers so
that handlers never reference ``app.state`` directly.  Indirection makes
unit testing easier: swap the dependency override instead of patching
``app.state``.

Usage::

    @router.get("/definitions")
    def list_defs(definitions: Definitions = Depends(get_definitions)):
        ...
"""

from typing import TYPE_CHECKING

from fastapi import Request

from ..definitions.schema import DeviceDefinition
from ..models.backup import BackupJob
from ..models.device_profile import DeviceProfile
from ..models.schedule import BackupSchedule
from ..storage.base import BaseConfigStore
from ..storage.device_profile_store import FileDeviceProfileStore
from ..storage.job_store import FileJobStore
from ..storage.schedule_store import FileScheduleStore

if TYPE_CHECKING:
    pass


def get_definitions(request: Request) -> dict[str, DeviceDefinition]:
    """Inject the loaded device-definition registry from application state."""
    return request.app.state.definitions


def get_storage(request: Request) -> BaseConfigStore:
    """Inject the config storage backend from application state."""
    return request.app.state.storage


def get_jobs(request: Request) -> dict[str, BackupJob]:
    """Inject the in-memory backup-job registry from application state."""
    return request.app.state.jobs


def get_job_store(request: Request) -> FileJobStore:
    """Inject the job persistence store from application state."""
    return request.app.state.job_store


def get_schedules(request: Request) -> dict[str, BackupSchedule]:
    """Inject the in-memory schedule registry from application state."""
    return request.app.state.schedules


def get_schedule_store(request: Request) -> FileScheduleStore:
    """Inject the schedule persistence store from application state."""
    return request.app.state.schedule_store


def get_scheduler(request: Request):
    """Inject the APScheduler instance from application state."""
    return request.app.state.scheduler


def get_device_profiles(request: Request) -> dict[str, DeviceProfile]:
    """Inject the in-memory device profile registry from application state."""
    return request.app.state.device_profiles


def get_device_profile_store(request: Request) -> FileDeviceProfileStore:
    """Inject the device profile persistence store from application state."""
    return request.app.state.device_profile_store
