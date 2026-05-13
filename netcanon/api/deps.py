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

from ..definitions.loader import DefinitionLoader
from ..definitions.schema import DeviceDefinition
from ..models.backup import BackupJob
from ..models.device_profile import DeviceProfile
from ..models.schedule import BackupSchedule
from ..storage.base import BaseConfigStore
from ..storage.device_profile_store import FileDeviceProfileStore
from ..storage.job_registry import BackupJobRegistry
from ..storage.job_store import FileJobStore
from ..storage.schedule_store import FileScheduleStore

if TYPE_CHECKING:
    pass


def get_definitions(request: Request) -> dict[str, DeviceDefinition]:
    """Inject the loaded device-definition registry from application state."""
    return request.app.state.definitions


def get_definition_loader(request: Request) -> DefinitionLoader:
    """Inject the DefinitionLoader instance so backup routes can call
    :meth:`DefinitionLoader.resolve` for overlay lookup.  The dict
    returned by :func:`get_definitions` stays as the family-base
    registry for endpoints that iterate type_keys."""
    return request.app.state.definition_loader


def get_storage(request: Request) -> BaseConfigStore:
    """Inject the config storage backend from application state."""
    return request.app.state.storage


def get_jobs(request: Request) -> BackupJobRegistry:
    """Inject the backup-job registry from application state.

    The registry exposes a dict-like surface (``__setitem__`` /
    ``__getitem__`` / ``__contains__`` / ``__len__`` / ``values()`` /
    ``get()``) so route handlers that pre-dated R8 (which used a
    plain ``dict[str, BackupJob]``) keep working with no changes.
    The registry transparently handles LRU eviction + disk lazy-load
    on memory miss — see :class:`BackupJobRegistry` for semantics.
    """
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
