"""
``/api/v1/backups`` routes.

Backup jobs are created immediately (synchronously) and then run in a
FastAPI ``BackgroundTask``.  Callers receive a job ID and poll
``GET /api/v1/backups/{job_id}`` for status.

During testing, FastAPI's ``TestClient`` executes background tasks
synchronously before returning the response, so integration tests see
a completed job immediately after ``POST /api/v1/backups``.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ...collectors.base import get_collector
from ...definitions.schema import DeviceDefinition
from ...models.backup import BackupJob, BackupResult, JobStatus
from ...models.device import BackupRequest
from ...storage.base import BaseConfigStore
from ..deps import get_definitions, get_jobs, get_storage

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
    definitions: dict[str, DeviceDefinition] = Depends(get_definitions),
    storage: BaseConfigStore = Depends(get_storage),
    jobs: dict[str, BackupJob] = Depends(get_jobs),
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
    background_tasks.add_task(
        _run_backup_job, job, request_body, definitions, storage
    )
    logger.info(
        "Created backup job %s for %d device(s)",
        job.id,
        job.total_devices,
    )
    return job


@router.get(
    "/",
    response_model=list[BackupJob],
    summary="List all backup jobs",
)
def list_jobs(
    jobs: dict[str, BackupJob] = Depends(get_jobs),
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
    jobs: dict[str, BackupJob] = Depends(get_jobs),
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


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------


def _run_backup_job(
    job: BackupJob,
    request: BackupRequest,
    definitions: dict[str, DeviceDefinition],
    storage: BaseConfigStore,
) -> None:
    """Execute all device backups for *job* and update its state.

    Runs in a background thread (via ``BackgroundTasks``).  Each device
    is processed independently; a failure on one device does not prevent
    others from running.  Job ``status`` becomes ``completed`` when all
    devices have been attempted, even if some failed.

    Args:
        job: The ``BackupJob`` to update in-place.
        request: Original backup request containing device targets.
        definitions: Loaded definition registry.
        storage: Config storage backend.
    """
    job.status = JobStatus.running
    logger.info("Backup job %s starting (%d devices)", job.id, job.total_devices)

    for device in request.devices:
        definition = definitions[device.type_key]
        collector = get_collector(definition)
        start = time.monotonic()

        try:
            raw_output = collector.collect(device, definition)
            record = storage.save(
                device_type=device.type_key,
                host=device.host,
                timestamp=datetime.now(timezone.utc),
                extension=definition.file_extension,
                content=raw_output,
            )
            job.results.append(
                BackupResult(
                    device_type=device.type_key,
                    host=device.host,
                    status="success",
                    config_record=record,
                    duration_seconds=time.monotonic() - start,
                )
            )
            logger.info(
                "Job %s: backed up %s/%s → %s",
                job.id,
                device.type_key,
                device.host,
                record.filename,
            )
        except Exception as exc:  # noqa: BLE001
            job.results.append(
                BackupResult(
                    device_type=device.type_key,
                    host=device.host,
                    status="failed",
                    error=str(exc),
                    duration_seconds=time.monotonic() - start,
                )
            )
            logger.error(
                "Job %s: device %s/%s failed — %s",
                job.id,
                device.type_key,
                device.host,
                exc,
                exc_info=True,
            )

    job.status = JobStatus.completed
    job.completed_at = datetime.now(timezone.utc)
    success = sum(1 for r in job.results if r.status == "success")
    logger.info(
        "Backup job %s completed: %d/%d succeeded",
        job.id,
        success,
        job.total_devices,
    )
