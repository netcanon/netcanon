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
from ..storage.base import BaseConfigStore

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
