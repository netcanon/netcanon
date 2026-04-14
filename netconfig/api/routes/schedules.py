"""
``/api/v1/schedules`` routes.

Schedules define recurring automatic backup jobs.  Each schedule is
persisted to disk as JSON and re-registered with APScheduler on startup.

The APScheduler ``AsyncIOScheduler`` executes ``_run_scheduled_backup``
as an async coroutine.  The actual SSH work runs in a thread pool via
``asyncio.to_thread`` so it never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from ...models.backup import BackupJob, JobStatus
from ...models.schedule import BackupSchedule, ScheduleCreate
from ...storage.job_store import FileJobStore
from ...storage.schedule_store import FileScheduleStore
from ..deps import get_job_store, get_schedule_store, get_schedules, get_scheduler

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/schedules", tags=["schedules"])


# ---------------------------------------------------------------------------
# Scheduler helpers (also called from main.py lifespan)
# ---------------------------------------------------------------------------


def register_schedule_job(scheduler, schedule: BackupSchedule, app) -> None:
    """Add or replace the APScheduler job for *schedule*.

    Uses an ``IntervalTrigger`` so the job fires every
    ``schedule.interval_minutes`` minutes.  Passing ``replace_existing=True``
    makes this safe to call on re-registration after a restart.
    """
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler.add_job(
        _run_scheduled_backup,
        trigger=IntervalTrigger(minutes=schedule.interval_minutes),
        id=schedule.id,
        replace_existing=True,
        kwargs={"schedule_id": schedule.id, "app": app},
    )
    logger.debug(
        "Registered APScheduler job for schedule '%s' (every %d min)",
        schedule.name,
        schedule.interval_minutes,
    )


async def _run_scheduled_backup(schedule_id: str, app) -> None:
    """Coroutine executed by APScheduler for each scheduled run.

    Creates a ``BackupJob``, runs ``_run_backup_job`` in a thread pool
    (blocking SSH must not run on the event loop), persists the job, and
    updates the schedule's ``last_run_at`` / ``next_run_at``.
    """
    # Local imports to avoid circular dependency at module load time
    from pydantic import SecretStr

    from ...models.device import BackupRequest, DeviceCredentials, DeviceTarget
    from .backups import _run_backup_job

    schedules = app.state.schedules
    schedule = schedules.get(schedule_id)
    if not schedule or not schedule.enabled:
        return

    devices = [
        DeviceTarget(
            type_key=d.type_key,
            host=d.host,
            port=d.port,
            credentials=DeviceCredentials(
                username=d.username,
                password=SecretStr(d.password),
                enable_password=(
                    SecretStr(d.enable_password) if d.enable_password else None
                ),
            ),
        )
        for d in schedule.devices
    ]
    request = BackupRequest(devices=devices)

    job = BackupJob(
        id=str(uuid.uuid4()),
        status=JobStatus.pending,
        created_at=datetime.now(timezone.utc),
        total_devices=len(devices),
        schedule_id=schedule.id,
        schedule_name=schedule.name,
    )
    app.state.jobs[job.id] = job
    logger.info(
        "Schedule '%s' triggered job %s (%d device(s))",
        schedule.name,
        job.id[:8],
        len(devices),
    )

    job_store: FileJobStore = app.state.job_store
    await asyncio.to_thread(
        _run_backup_job,
        job,
        request,
        app.state.definitions,
        app.state.storage,
        job_store,
    )

    schedule.last_run_at = datetime.now(timezone.utc)
    schedule.last_job_id = job.id

    # Refresh next_run_at from the live scheduler
    ap_job = app.state.scheduler.get_job(schedule_id)
    if ap_job and ap_job.next_run_time:
        schedule.next_run_at = ap_job.next_run_time

    app.state.schedule_store.save(schedule)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=list[BackupSchedule],
    summary="List all backup schedules",
)
def list_schedules(
    schedules: dict[str, BackupSchedule] = Depends(get_schedules),
) -> list[BackupSchedule]:
    """Return all schedules sorted newest-first."""
    return sorted(schedules.values(), key=lambda s: s.created_at, reverse=True)


@router.post(
    "/",
    status_code=201,
    response_model=BackupSchedule,
    summary="Create a backup schedule",
)
def create_schedule(
    body: ScheduleCreate,
    request: Request,
    schedules: dict[str, BackupSchedule] = Depends(get_schedules),
    schedule_store: FileScheduleStore = Depends(get_schedule_store),
    scheduler=Depends(get_scheduler),
) -> BackupSchedule:
    """Create a new recurring backup schedule and register it immediately."""
    schedule = BackupSchedule(**body.model_dump())
    schedules[schedule.id] = schedule
    schedule_store.save(schedule)

    register_schedule_job(scheduler, schedule, request.app)

    # Capture the first calculated next_run_at
    ap_job = scheduler.get_job(schedule.id)
    if ap_job and ap_job.next_run_time:
        schedule.next_run_at = ap_job.next_run_time
        schedule_store.save(schedule)

    logger.info(
        "Created schedule '%s' (every %d min, id=%s)",
        schedule.name,
        schedule.interval_minutes,
        schedule.id[:8],
    )
    return schedule


@router.delete(
    "/{schedule_id}",
    status_code=204,
    summary="Delete a backup schedule",
)
def delete_schedule(
    schedule_id: str,
    schedules: dict[str, BackupSchedule] = Depends(get_schedules),
    schedule_store: FileScheduleStore = Depends(get_schedule_store),
    scheduler=Depends(get_scheduler),
) -> None:
    """Delete a schedule and remove its APScheduler job."""
    if schedule_id not in schedules:
        raise HTTPException(
            status_code=404, detail=f"Schedule not found: {schedule_id!r}"
        )
    del schedules[schedule_id]
    schedule_store.delete(schedule_id)
    if scheduler.get_job(schedule_id):
        scheduler.remove_job(schedule_id)
    logger.info("Deleted schedule %s", schedule_id[:8])


@router.post(
    "/{schedule_id}/toggle",
    response_model=BackupSchedule,
    summary="Enable or disable a schedule",
)
def toggle_schedule(
    schedule_id: str,
    request: Request,
    schedules: dict[str, BackupSchedule] = Depends(get_schedules),
    schedule_store: FileScheduleStore = Depends(get_schedule_store),
    scheduler=Depends(get_scheduler),
) -> BackupSchedule:
    """Flip ``enabled`` on a schedule; registers or removes the APScheduler job."""
    if schedule_id not in schedules:
        raise HTTPException(
            status_code=404, detail=f"Schedule not found: {schedule_id!r}"
        )
    schedule = schedules[schedule_id]
    schedule.enabled = not schedule.enabled

    if schedule.enabled:
        register_schedule_job(scheduler, schedule, request.app)
        ap_job = scheduler.get_job(schedule_id)
        if ap_job and ap_job.next_run_time:
            schedule.next_run_at = ap_job.next_run_time
    else:
        if scheduler.get_job(schedule_id):
            scheduler.remove_job(schedule_id)
        schedule.next_run_at = None

    schedule_store.save(schedule)
    logger.info(
        "Schedule '%s' %s", schedule.name, "enabled" if schedule.enabled else "disabled"
    )
    return schedule
