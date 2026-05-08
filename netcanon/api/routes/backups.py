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
``paramiko.SSHClient`` directly.
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from ...collectors.base import get_collector
from ...config import MAX_BACKUP_CONCURRENCY
from ...definitions.loader import DefinitionLoader
from ...definitions.schema import DeviceDefinition
from ...models.backup import BackupJob, BackupResult, JobStatus
from ...models.device import BackupRequest, DeviceTarget
from ...models.device_profile import DeviceProfile
from ...storage.base import BaseConfigStore
from ...storage.device_profile_store import FileDeviceProfileStore
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
    jobs: dict[str, BackupJob] = Depends(get_jobs),
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
        _run_backup_job,
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


def _process_one_device(
    job: BackupJob,
    idx: int,
    device: DeviceTarget,
    definitions: dict[str, DeviceDefinition],
    storage: BaseConfigStore,
    definition_loader: DefinitionLoader | None = None,
    device_profiles: dict[str, DeviceProfile] | None = None,
    device_profile_store: FileDeviceProfileStore | None = None,
) -> None:
    """Run the backup for a single device and mutate ``job.results[idx]``.

    Extracted from ``_run_backup_job`` so the same code path runs whether
    a job uses the thread pool or executes sequentially (single-device
    jobs skip the pool for cleaner traces).

    Tests patch ``netcanon.api.routes.backups.get_collector`` to mock
    SSH/NETCONF/REST collection — see AGENTS.md "Hard Rules".  Never
    patch ``ConnectHandler`` or ``paramiko.SSHClient`` directly.

    Layered-definition resolution (P1C3):
      1. Family-base definition looked up via ``definitions[type_key]``
         is always the starting point.
      2. If the definition declares a ``probe.command`` AND
         ``definition_loader`` was provided, run the collector's
         probe to populate detected_facts.
      3. Pinned values (``device.os_version`` / ``device.model``)
         win over detected facts in the resolve() call.
      4. If the loader yields a more-specific overlay, swap to it
         for the main collect.
      5. If the device carries a ``device_profile_id``, persist the
         fresh detected_facts onto the profile so the UI's edit form
         reflects what the device actually reports.

    Each step is independent and gracefully degrades: probe failure
    → empty facts → family-base wins; no loader → no resolve();
    no profile_id → no persistence.  Existing callers that don't
    supply the new optional params get legacy single-definition
    behaviour.

    Args:
        job: Parent ``BackupJob`` whose ``results[idx]`` is mutated.
        idx: Position of this device in ``job.results``; the worker
            for index *idx* is the only writer of that slot.
        device: Connection target (host, type_key, credentials,
            optional pinned os_version/model and device_profile_id).
        definitions: Loaded family-base definition registry, keyed by
            ``type_key``.
        storage: Backend that persists collected config bytes.
        definition_loader: Optional layered-definition resolver.  When
            provided, enables probe + overlay resolution; absence
            forces legacy single-definition behaviour.
        device_profiles: Optional in-memory profile registry.  Required
            alongside ``device_profile_store`` to persist
            ``detected_facts`` for UI display.
        device_profile_store: Optional persistence backend for the
            profile registry.

    All exceptions are caught and recorded on the ``BackupResult``; this
    function therefore never raises under normal operation.  Any exception
    that does escape indicates a programming bug in the backup runner
    itself (e.g. an invalid definition lookup) and should surface.

    Thread safety: ``job.results[idx]`` is mutated only by the single
    worker assigned to index *idx*.  Other workers touch other indices,
    so no locking is required.  Python's GIL makes the individual attribute
    writes atomic.  Device-profile persistence uses the profile store's
    own atomic-write guarantees.
    """
    family_base = definitions[device.type_key]
    # Use the family-base collector for probe — connection-layer
    # settings (netmiko_device_type, auth) are stable across overlays.
    base_collector = get_collector(family_base)

    detected_facts: dict[str, str] = {}
    if family_base.probe.command and definition_loader is not None:
        try:
            detected_facts = base_collector.probe(device, family_base)
        except Exception as exc:  # noqa: BLE001 — probe NEVER fails the backup
            logger.warning(
                "Probe of %s raised unexpectedly; continuing with "
                "family-base definition: %s",
                device.host,
                exc,
            )

    # Resolution precedence: operator pins win over detected facts.
    # Operator wrote os_version="17.12" on the profile → use that;
    # only consult detected_facts when the pin is empty.
    resolve_os_version = device.os_version or detected_facts.get(
        "detected_os_version"
    )
    resolve_model = device.model or detected_facts.get("detected_model")

    if definition_loader is not None and (
        resolve_os_version or resolve_model
    ):
        resolved = definition_loader.resolve(
            device.type_key,
            os_version=resolve_os_version,
            model=resolve_model,
        )
        definition = resolved or family_base
        if resolved and resolved is not family_base:
            logger.info(
                "Backup of %s: resolved layered definition "
                "(os_version=%r, model=%r)",
                device.host,
                resolve_os_version,
                resolve_model,
            )
    else:
        definition = family_base

    # Persist detected_facts onto the linked profile for UI display.
    # Swallow persistence errors — a successful backup is not worth
    # failing because we couldn't update the display panel.
    if (
        detected_facts
        and device.device_profile_id
        and device_profiles is not None
        and device_profile_store is not None
    ):
        try:
            profile = device_profiles.get(device.device_profile_id)
            if profile is not None:
                profile.detected_facts = detected_facts
                device_profile_store.save(profile)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to persist detected_facts for profile %s: %s",
                device.device_profile_id,
                exc,
            )

    # Use a per-definition collector for the actual collect — the
    # resolved overlay may have different commands or prompts than
    # the family base even though connection params are stable.
    collector = get_collector(definition)
    result = job.results[idx]
    result.status = "running"
    start = time.monotonic()
    try:
        raw_output = collector.collect(device, definition)
        record = storage.save(
            device_type=device.type_key,
            host=device.host,
            timestamp=datetime.now(timezone.utc),
            extension=definition.file_extension,
            content=raw_output,
            device_profile_id=device.device_profile_id,
        )
        result.config_record = record
        result.duration_seconds = time.monotonic() - start
        result.status = "success"
        logger.info(
            "Job %s: backed up %s/%s → %s",
            job.id,
            device.type_key,
            device.host,
            record.filename,
        )
    except Exception as exc:  # noqa: BLE001
        result.error = str(exc)[:500]
        result.duration_seconds = time.monotonic() - start
        result.status = "failed"
        logger.error(
            "Job %s: device %s/%s failed — %s",
            job.id,
            device.type_key,
            device.host,
            exc,
            exc_info=True,
        )


def _run_backup_job(
    job: BackupJob,
    request: BackupRequest,
    definitions: dict[str, DeviceDefinition],
    storage: BaseConfigStore,
    job_store: FileJobStore | None = None,
    max_workers: int = MAX_BACKUP_CONCURRENCY,
    definition_loader: DefinitionLoader | None = None,
    device_profiles: dict[str, DeviceProfile] | None = None,
    device_profile_store: FileDeviceProfileStore | None = None,
) -> None:
    """Execute all device backups for *job* and update its state.

    Runs in BackgroundTasks; never returns to the route response — see
    AGENTS.md "Hard Rules".  ``POST /api/v1/backups`` always returns
    ``status=pending`` and the caller polls ``GET /api/v1/backups/{id}``
    for the terminal state this function writes.  Tests rely on
    TestClient executing background tasks synchronously before the POST
    response is returned.

    Device work is dispatched to a bounded ``ThreadPoolExecutor`` so up
    to *max_workers* devices are processed in parallel; additional
    devices wait in the executor's FIFO queue and start as slots free up.

    Each device is processed independently; a failure on one device does
    not prevent others from running.  Job ``status`` becomes
    ``completed`` / ``partial`` / ``failed`` once every device has been
    attempted, based on per-device outcomes.

    Args:
        job: The ``BackupJob`` to update in-place.
        request: Original backup request containing device targets.
        definitions: Loaded definition registry.
        storage: Config storage backend.
        job_store: Optional persistence store; called once after all
            devices complete.
        max_workers: Maximum concurrent device workers for this job.
            Clamped to ``[1, MAX_BACKUP_CONCURRENCY]`` (10).  Jobs with
            a single device bypass the pool entirely.
        definition_loader: Optional layered-definition resolver, threaded
            through to ``_process_one_device`` for probe + overlay
            resolution.
        device_profiles: Optional in-memory profile registry threaded
            through for ``detected_facts`` persistence.
        device_profile_store: Optional persistence backend paired with
            ``device_profiles``.

    Thread safety:
        * ``job.results`` is pre-populated before dispatch and is never
          resized after.  Each worker mutates exactly one element.
        * ``storage.save`` writes atomically via temp+rename; distinct
          ``(device_type, host)`` pairs produce distinct paths so there
          is no contention in the common case.
    """
    # Pre-populate every device as "queued" so polling clients see the full
    # device list immediately — they can render placeholder rows before any
    # collection has started.  Each result is mutated in place (never
    # replaced) so indexed references stay valid across threads.
    for device in request.devices:
        job.results.append(
            BackupResult(
                device_type=device.type_key,
                host=device.host,
                status="queued",
                duration_seconds=0.0,
            )
        )

    # Clamp max_workers defensively; callers should already enforce this
    # via pydantic validation on Settings.backup_concurrency.
    workers = max(1, min(max_workers, MAX_BACKUP_CONCURRENCY, len(request.devices)))

    job.status = JobStatus.running
    logger.info(
        "Backup job %s starting (%d devices, %d worker%s)",
        job.id,
        job.total_devices,
        workers,
        "" if workers == 1 else "s",
    )

    if workers == 1:
        # Serial fast-path: single device, or deployment pinned to 1.
        for idx, device in enumerate(request.devices):
            _process_one_device(
                job, idx, device, definitions, storage,
                definition_loader, device_profiles, device_profile_store,
            )
    else:
        # Parallel path: up to `workers` devices in flight at once; the
        # executor itself queues the rest and drains FIFO.
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix=f"backup-{job.id[:8]}",
        ) as pool:
            futures = [
                pool.submit(
                    _process_one_device, job, idx, device, definitions, storage,
                    definition_loader, device_profiles, device_profile_store,
                )
                for idx, device in enumerate(request.devices)
            ]
            # Wait for ALL to finish. Per-device exceptions are caught
            # inside _process_one_device; anything that surfaces here is
            # a bug in the runner itself and we want it to propagate.
            wait(futures)
            for f in futures:
                exc = f.exception()
                if exc is not None:
                    # Log but don't raise — we still want to compute the
                    # terminal job status and persist what we have.
                    logger.error(
                        "Job %s: worker raised unexpected exception: %s",
                        job.id, exc, exc_info=exc,
                    )

    job.completed_at = datetime.now(timezone.utc)
    success = sum(1 for r in job.results if r.status == "success")
    failed_hosts = [r.host for r in job.results if r.status == "failed"]
    # Terminal-state logic: all-success=completed, all-fail=failed, mixed=partial.
    if not failed_hosts:
        job.status = JobStatus.completed
    elif success == 0:
        job.status = JobStatus.failed
    else:
        job.status = JobStatus.partial
    logger.info(
        "Backup job %s %s: %d/%d succeeded%s",
        job.id,
        job.status.value,
        success,
        job.total_devices,
        f" (failed: {failed_hosts})" if failed_hosts else "",
    )
    if job_store is not None:
        try:
            job_store.save(job)
        except OSError as exc:
            logger.error("Failed to persist job %s: %s", job.id, exc)
