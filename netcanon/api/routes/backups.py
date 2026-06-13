"""
``/api/v1/backups`` routes.

Endpoints:

    POST /api/v1/backups/
        → Create a backup job.  Validates every device's ``type_key``
          against loaded definitions, creates the :class:`BackupJob`
          synchronously in ``pending`` state, then enqueues the actual
          SSH / NETCONF / REST collection as a FastAPI
          ``BackgroundTask``.  Returns the freshly-created job (always
          ``pending`` at this point — see test-mocking note below).

    GET  /api/v1/backups/
        → List every :class:`BackupJob` in memory, newest first.

    GET  /api/v1/backups/{job_id}
        → Fetch one job's current state.  Callers poll this endpoint
          to observe progression through ``running`` → ``completed`` /
          ``partial`` / ``failed``.

Backup jobs are created immediately (synchronously) and then run in a
FastAPI ``BackgroundTask``.  Callers receive a job ID and poll
``GET /api/v1/backups/{job_id}`` for status.

During testing, FastAPI's ``TestClient`` executes background tasks
synchronously before returning the response, so integration tests see
a completed job immediately after ``POST /api/v1/backups`` — but the
POST response body itself is always serialised in ``pending`` state
(it's built before the background task runs).  Tests that need the
final job state must always GET the job by ID after POSTing — never
assert on the POST response body.  See AGENTS.md "Hard Rules".

Mocking convention: tests mock collection by patching
``netcanon.api.routes.backups.get_collector`` — the single factory
this route delegates to.  Never patch ``ConnectHandler`` or
``paramiko.SSHClient`` directly.  The orchestration that *calls* this
factory now lives in :mod:`netcanon.services.backup_runner`; it
resolves the factory back through this module
(``backups.get_collector``) so this patch target is unchanged.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

# ``get_collector`` is imported here — and only here — to preserve the
# documented mock-point ``netcanon.api.routes.backups.get_collector``.
# The backup engine in :mod:`netcanon.services.backup_runner` calls it
# back through this module, so tests still patch it at this import site.
from ...collectors.base import get_collector  # noqa: F401  (mock-point seam)
from ...config import MAX_BACKUP_CONCURRENCY
from ...definitions.loader import DefinitionLoader
from ...definitions.schema import DeviceDefinition
from ...models.backup import BackupJob, JobStatus
from ...models.device import BackupRequest
from ...models.device_profile import DeviceProfile
from ...services.backup_runner import run_backup_job
from ...storage.base import BaseConfigStore
from ...storage.device_profile_store import FileDeviceProfileStore
from ...storage.job_registry import BackupJobRegistry
from ...storage.job_store import FileJobStore
from ..deps import (
    get_definition_loader,
    get_definitions,
    get_device_profile_store,
    get_device_profiles,
    get_job_store,
    get_jobs,
    get_storage,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/backups", tags=["backups"])


@router.post(
    "/",
    status_code=202,
    response_model=BackupJob,
    summary="Create a backup job",
)
def create_backup(
    request_body: BackupRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    definitions: dict[str, DeviceDefinition] = Depends(get_definitions),
    definition_loader: DefinitionLoader = Depends(get_definition_loader),
    storage: BaseConfigStore = Depends(get_storage),
    jobs: BackupJobRegistry = Depends(get_jobs),
    job_store: FileJobStore = Depends(get_job_store),
    device_profiles: dict[str, DeviceProfile] = Depends(get_device_profiles),
    device_profile_store: FileDeviceProfileStore = Depends(
        get_device_profile_store
    ),
) -> BackupJob:
    """Validate devices, create a job, and enqueue the backup task.

    All ``type_key`` values in the request are validated against loaded
    definitions before the job is created.  Unknown keys return HTTP 422.

    The job is returned immediately with ``status: pending``.  The actual
    SSH collection runs in the background.

    Args:
        request_body: List of devices to back up.

    Returns:
        The newly created ``BackupJob`` in ``pending`` state.

    Raises:
        HTTPException 422: If any device ``type_key`` is not loaded.
    """
    unknown = [
        d.type_key for d in request_body.devices if d.type_key not in definitions
    ]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown type_key(s): {unknown}. "
                f"Loaded definitions: {sorted(definitions.keys())}"
            ),
        )

    job = BackupJob(
        id=str(uuid.uuid4()),
        status=JobStatus.pending,
        created_at=datetime.now(timezone.utc),
        total_devices=len(request_body.devices),
    )
    jobs[job.id] = job
    max_workers = getattr(
        request.app.state.settings, "backup_concurrency", MAX_BACKUP_CONCURRENCY
    )
    background_tasks.add_task(
        run_backup_job,
        job,
        request_body,
        definitions,
        storage,
        job_store,
        max_workers,
        definition_loader,
        device_profiles,
        device_profile_store,
    )
    logger.info(
        "Created backup job %s for %d device(s) (max_workers=%d)",
        job.id,
        job.total_devices,
        max_workers,
    )
    return job


@router.get(
    "/",
    response_model=list[BackupJob],
    summary="List all backup jobs",
)
def list_jobs(
    jobs: BackupJobRegistry = Depends(get_jobs),
) -> list[BackupJob]:
    """Return all backup jobs, sorted newest-first."""
    return sorted(jobs.values(), key=lambda j: j.created_at, reverse=True)


@router.get(
    "/{job_id}",
    response_model=BackupJob,
    summary="Get a backup job by ID",
)
def get_job(
    job_id: str,
    jobs: BackupJobRegistry = Depends(get_jobs),
) -> BackupJob:
    """Return the current state of a backup job.

    Args:
        job_id: UUID returned by ``POST /api/v1/backups``.

    Raises:
        HTTPException 404: If no job with *job_id* exists.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id!r}")
    return jobs[job_id]
