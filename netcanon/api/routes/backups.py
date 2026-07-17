"""
``/api/v1/backups`` routes.

Endpoints:

    POST /api/v1/backups/
        → Create a backup job.  Validates every device's ``type_key``
          against loaded definitions, creates the :class:`BackupJob`
          synchronously in ``pending`` state, then submits the actual
          SSH / NETCONF / REST collection to the dedicated backup-job
          executor (:func:`netcanon.services.backup_runner.submit_backup_job`).
          Returns the freshly-created job (always ``pending`` at this
          point — the job runs in the background; see test-mocking note
          below).

    GET  /api/v1/backups/
        → List every :class:`BackupJob` in memory, newest first.

    GET  /api/v1/backups/{job_id}
        → Fetch one job's current state.  Callers poll this endpoint
          to observe progression through ``running`` → ``completed`` /
          ``partial`` / ``failed``.

Backup jobs are created immediately (synchronously) and then run on a
dedicated, capped background thread pool
(:func:`netcanon.services.backup_runner.submit_backup_job`, #27).
Callers receive a job ID and poll ``GET /api/v1/backups/{job_id}`` for
status.

Async contract (changed by #27): the job runs *truly* in the
background, so ``POST /api/v1/backups`` returns while the job is still
``pending`` — it is NOT run synchronously before the response, even
under ``TestClient`` (the pre-#27 behaviour, where FastAPI
``BackgroundTasks`` ran the job before the next request).  Tests that
need the final job state must poll ``GET /{id}`` until it is terminal —
never assert final state on the POST body, and never assume the job has
finished the instant the POST returns.  The ``wait_for_job`` helper
(``tests/conftest.py``) does the poll; the integration ``client``
fixture applies it automatically after a backups POST.  See AGENTS.md
"Hard Rules".

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
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Request,
)
from pydantic import SecretStr

# ``get_collector`` is imported here — and only here — to preserve the
# documented mock-point ``netcanon.api.routes.backups.get_collector``.
# The backup engine in :mod:`netcanon.services.backup_runner` calls it
# back through this module, so tests still patch it at this import site.
from ...collectors.base import get_collector  # noqa: F401  (mock-point seam)
from ...config import MAX_BACKUP_CONCURRENCY
from ...definitions.loader import DefinitionLoader
from ...definitions.schema import DeviceDefinition
from ...models.backup import BackupJob, JobStatus
from ...models.device import BackupRequest, DeviceCredentials, DeviceTarget
from ...models.device_profile import DeviceProfile
from ...services.backup_runner import submit_backup_job
from ...services.egress import EgressBlocked, assert_egress_allowed
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


def _resolve_credentials(
    devices: list[DeviceTarget],
    device_profiles: dict[str, DeviceProfile],
) -> list[DeviceTarget]:
    """Fill missing per-device credentials from the linked profile, server-side.

    A device may omit inline ``credentials`` when it carries a
    ``device_profile_id`` that resolves to a stored profile — the credentials
    are then read from that profile (decrypted in memory, never sent to or
    received from the client).  This mirrors the scheduled-trigger path in
    :mod:`netcanon.api.routes.schedules` and lets the web "run backup now"
    flows operate without the plaintext password ever crossing the API
    boundary.  Inline credentials, when present, win (ad-hoc backup or an
    explicit per-run override).

    Args:
        devices: The request's device targets (credentials may be ``None``).
        device_profiles: In-memory profile registry (``app.state``).

    Returns:
        A new list of ``DeviceTarget`` with ``credentials`` populated.

    Raises:
        HTTPException 422: A device has neither inline credentials nor a
            resolvable ``device_profile_id``.
    """
    resolved: list[DeviceTarget] = []
    for idx, device in enumerate(devices):
        if device.credentials is not None:
            resolved.append(device)
            continue
        profile = (
            device_profiles.get(device.device_profile_id)
            if device.device_profile_id
            else None
        )
        if profile is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"devices[{idx}] (host={device.host!r}): no credentials "
                    "supplied and no resolvable device_profile_id. Provide "
                    "credentials inline or reference an existing device profile."
                ),
            )
        creds = DeviceCredentials(
            username=profile.username,
            password=SecretStr(profile.password),
            enable_password=(
                SecretStr(profile.enable_password)
                if profile.enable_password
                else None
            ),
        )
        resolved.append(device.model_copy(update={"credentials": creds}))
    return resolved


@router.post(
    "/",
    status_code=202,
    response_model=BackupJob,
    summary="Create a backup job",
    responses={
        400: {
            "description": (
                "A device address is blocked by the egress allow-list "
                "(NETCANON_BLOCK_PRIVATE_EGRESS)."
            )
        },
    },
)
def create_backup(
    request_body: BackupRequest,
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

    # Resolve any omitted credentials from the linked device profile,
    # server-side — so callers (notably the web "run backup now" flows)
    # never have to fetch or relay the plaintext password.  Raises 422 for
    # any device with neither inline credentials nor a resolvable profile.
    resolved_request = BackupRequest(
        devices=_resolve_credentials(request_body.devices, device_profiles)
    )

    # Egress allow-list (opt-in via Settings.block_private_egress): refuse
    # targets that resolve to loopback / link-local (incl. the cloud
    # metadata endpoint) to blunt the SSRF surface (review finding #3).
    if request.app.state.settings.block_private_egress:
        for device in resolved_request.devices:
            try:
                assert_egress_allowed(device.host)
            except EgressBlocked as exc:
                logger.warning(
                    "Backup request rejected by egress allow-list (host %r): %s",
                    device.host,
                    exc,
                )
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    job = BackupJob(
        id=str(uuid.uuid4()),
        status=JobStatus.pending,
        created_at=datetime.now(UTC),
        total_devices=len(resolved_request.devices),
    )
    jobs[job.id] = job
    # Persist the pending job to disk immediately so it survives an LRU
    # eviction from the in-memory cache during its run.  The runner only
    # saves on completion (backup_runner terminal save), so without this a
    # job evicted while still running would disk-miss and poll as a 404
    # for an active job (CONC-5).  The runner's terminal save later
    # overwrites this pending snapshot with the final state.
    try:
        job_store.save(job)
    except OSError as exc:
        # Non-fatal: the job still runs and is saved on completion — we
        # only lose the mid-run disk fallback for this one.  Don't fail
        # the request over it.
        logger.warning(
            "Could not persist pending job %s at creation: %s", job.id, exc
        )
    max_workers = getattr(
        request.app.state.settings, "backup_concurrency", MAX_BACKUP_CONCURRENCY
    )
    # (#27) Snapshot the pending job for the response BEFORE handing the live
    # object to the executor.  The worker thread flips job.status to `running`
    # and appends results the instant it is scheduled — which can happen before
    # FastAPI finishes serialising the response — so returning the live `job`
    # would race a non-deterministic pending/running/completed status into the
    # POST body.  The registry + disk hold the LIVE object (GET /{id} reflects
    # real-time state); the response is a frozen `pending` acknowledgement,
    # preserving the documented "POST always returns pending" contract.
    pending_snapshot = job.model_copy(deep=True)
    # Dispatch onto the dedicated backup-job executor rather than FastAPI
    # BackgroundTasks.  BackgroundTasks ran the minutes-long, blocking
    # run_backup_job on one of anyio's ~40 shared worker-thread tokens — the
    # same pool that serves every synchronous route — so ~40 in-flight jobs
    # froze the whole sync API.  submit_backup_job runs the job on a dedicated,
    # capped pool instead.  The job now runs truly in the background, so
    # callers must poll GET /backups/{id} for the terminal state; the job is
    # already in the registry + persisted above, so the poll sees it
    # immediately.  See AGENTS.md "Hard Rules".
    submit_backup_job(
        job,
        resolved_request,
        definitions,
        storage,
        job_store,
        max_workers,
        definition_loader,
        device_profiles,
        device_profile_store,
        # (HEAD-review F5) Pass the app's live Settings so the job's collectors
        # use the app-configured data dir (and thus the TOFU known_hosts store)
        # instead of the worker re-resolving ``Settings()`` from env.  On the
        # desktop the app builds Settings programmatically with no env bridge,
        # so the fallback resolved ``configs_dir=Path("configs")`` -> a
        # CWD-relative known_hosts that silently broke changed-key detection.
        settings=request.app.state.settings,
    )
    logger.info(
        "Created backup job %s for %d device(s) (max_workers=%d)",
        job.id,
        job.total_devices,
        max_workers,
    )
    return pending_snapshot


@router.get(
    "/",
    response_model=list[BackupJob],
    summary="List recent (memory-resident) backup jobs",
)
def list_jobs(
    jobs: BackupJobRegistry = Depends(get_jobs),
) -> list[BackupJob]:
    """Return the most-recent memory-resident backup jobs, newest-first (#29).

    NOT full disk history: this reflects only the LRU cache (up to
    ``max_memory_jobs``, default 1000).  Older jobs are evicted from this
    list but remain retrievable by ID via ``GET /{job_id}`` (disk lazy-load).
    With ``max_memory_jobs=0`` the cache is disabled, so this list is always
    empty even though jobs are still persisted and get-by-id works.
    """
    return sorted(jobs.values(), key=lambda j: j.created_at, reverse=True)


@router.get(
    "/{job_id}",
    response_model=BackupJob,
    summary="Get a backup job by ID",
    responses={
        404: {
            "description": (
                "No job with this id exists (or its on-disk snapshot is "
                "corrupt/empty)."
            )
        },
        422: {
            "description": (
                "`job_id` is not a well-formed UUID — rejected by the path "
                "pattern guard (SEC-3) before the lookup (C5)."
            )
        },
    },
)
def get_job(
    job_id: str = Path(
        ...,
        # Job ids are `str(uuid.uuid4())`; constrain to the exact UUID shape
        # so a crafted id (e.g. a URL-encoded `\`, a real path separator on
        # Windows) can never reach the file-store path join as a traversal /
        # existence-oracle vector.  Mirrors the FileConfigStore filename
        # guard on the sibling config routes (SEC-3).
        pattern=(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
    ),
    jobs: BackupJobRegistry = Depends(get_jobs),
) -> BackupJob:
    """Return the current state of a backup job.

    Args:
        job_id: UUID returned by ``POST /api/v1/backups``.

    Raises:
        HTTPException 404: If no job with *job_id* exists, OR its on-disk
            snapshot is corrupt/empty (a power-loss / hand-edit artifact).
        HTTPException 422: If *job_id* is not a well-formed UUID — the path
            ``pattern`` guard rejects it before this handler runs (SEC-3).
    """
    # Use ``.get()`` rather than ``in`` + ``[]``: ``__contains__`` answers via a
    # cheap ``path.exists()`` (no JSON parse) while ``__getitem__`` raises
    # ``KeyError`` when ``load_one`` yields ``None`` for a corrupt file — so the
    # two disagreed for a truncated/zero-byte ``jobs/{uuid}.json`` and the read
    # 500'd after passing the membership guard (C2).  ``.get()`` lazy-loads and
    # returns ``None`` on both "missing" and "corrupt", so both map to 404.
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id!r}")
    return job
