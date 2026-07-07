"""
Backup orchestration — the load-bearing backup engine.

This module is THE backup orchestrator: every code path that turns a
list of :class:`~netcanon.models.device.DeviceTarget` into persisted
config records funnels through :func:`run_backup_job`.  The
``POST /api/v1/backups`` route (:mod:`netcanon.api.routes.backups`) and
the APScheduler-driven scheduler
(:mod:`netcanon.api.routes.schedules`) both dispatch this function into
a worker thread; integration / e2e / desktop tests drive it
transitively through those endpoints.

Structural sibling of :mod:`netcanon.services.migration_pipeline`:
routes orchestrate the HTTP lifecycle, this service does the actual
multi-device collection work.  Pulling it here (out of the route
module) removes the asymmetry where the scheduler had to reach *into*
a route module to borrow the engine.

Mock-point contract (AGENTS.md "Hard Rules" — load-bearing):

    Tests mock SSH / NETCONF / REST collection by patching
    ``netcanon.api.routes.backups.get_collector`` — the single factory
    seam.  Never patch ``ConnectHandler`` or ``paramiko.SSHClient``
    directly.

    That patch target is preserved even though the collection code now
    lives here: :func:`_process_one_device` resolves the factory via a
    function-local ``from ..api.routes import backups`` and calls
    ``backups.get_collector(...)``.  Because the attribute is looked up
    on the route module *at call time*, ``patch(
    "netcanon.api.routes.backups.get_collector", ...)`` continues to
    intercept every collection — no test or doc change required.  The
    lazy import (rather than a module-level one) also keeps the route
    module → service-module dependency acyclic: ``backups.py`` imports
    this module at load time to dispatch the background task; this
    module imports the route module only inside the function body.

Thread-safety / async-boundary contract (unchanged from the original
route-module home):

    * Runs in a worker thread, never on the event loop.  The route
      dispatches via FastAPI ``BackgroundTasks``; the scheduler via
      ``asyncio.to_thread`` — blocking SSH must not run on the loop.
    * ``job.results`` is pre-populated before dispatch and never
      resized; each worker mutates exactly one element, so no locking
      is required (the GIL makes the individual attribute writes
      atomic).
    * ``storage.save`` writes atomically via temp+rename; distinct
      ``(device_type, host)`` pairs produce distinct paths.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime

from ..config import (
    MAX_BACKUP_CONCURRENCY,
    MAX_CONCURRENT_BACKUP_JOBS,
    MAX_GLOBAL_BACKUP_CONCURRENCY,
    Settings,
)
from ..definitions.loader import DefinitionLoader
from ..definitions.schema import DeviceDefinition
from ..models.backup import BackupJob, BackupResult, JobStatus
from ..models.device import BackupRequest, DeviceTarget
from ..models.device_profile import DeviceProfile
from ..storage.base import BaseConfigStore
from ..storage.device_profile_store import (
    DEVICE_PROFILE_REGISTRY_LOCK,
    FileDeviceProfileStore,
)
from ..storage.job_store import FileJobStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Process-wide collection ceiling (blind-audit 3ec11f3 r7)
# ---------------------------------------------------------------------------
# The per-job ``ThreadPoolExecutor`` below bounds ONE job to ``max_workers``
# (<= MAX_BACKUP_CONCURRENCY).  It does NOT bound the *number of jobs* in
# flight: several schedules firing together — or a schedule firing during a
# manual run — each spin up their own pool, so the total SSH/NETCONF session
# count was unbounded (N jobs × cap → thread / file-descriptor exhaustion on
# the backup host).  This module-level ``BoundedSemaphore`` caps the SUM of
# in-flight device collections across every concurrent job; a worker that
# can't get a permit blocks until one frees (back-pressure — the device just
# stays ``queued`` until its turn, never a failure).
_GLOBAL_LIMITER: threading.BoundedSemaphore | None = None
_GLOBAL_LIMITER_LOCK = threading.Lock()


def _global_collection_limiter() -> threading.BoundedSemaphore:
    """Return the process-wide collection semaphore, building it once.

    Sized from :data:`MAX_GLOBAL_BACKUP_CONCURRENCY`.  Lazily created (with a
    double-checked lock) so the size can be monkeypatched before first use in
    tests; :func:`reset_global_limiter` drops the cached instance so a later
    call rebuilds at the patched size.
    """
    global _GLOBAL_LIMITER
    if _GLOBAL_LIMITER is None:
        with _GLOBAL_LIMITER_LOCK:
            if _GLOBAL_LIMITER is None:
                _GLOBAL_LIMITER = threading.BoundedSemaphore(
                    MAX_GLOBAL_BACKUP_CONCURRENCY
                )
    return _GLOBAL_LIMITER


def reset_global_limiter() -> None:
    """Drop the cached process-wide limiter (test helper only).

    The next :func:`_global_collection_limiter` call rebuilds it from the
    current :data:`MAX_GLOBAL_BACKUP_CONCURRENCY`, letting a test set a small
    ceiling and observe the back-pressure deterministically.
    """
    global _GLOBAL_LIMITER
    with _GLOBAL_LIMITER_LOCK:
        _GLOBAL_LIMITER = None


# ---------------------------------------------------------------------------
# Dedicated backup-job executor (2026-07-06 review MEDIUM #27)
# ---------------------------------------------------------------------------
# ``run_backup_job`` is a minutes-long, blocking (SSH/NETCONF) call.  Both
# entry points used to dispatch it onto a *shared* pool:
#
#   * the manual ``POST /api/v1/backups`` route via FastAPI ``BackgroundTasks``
#     — which runs sync tasks on anyio's ~40-token default worker pool, the
#     SAME pool that serves every synchronous route, so ~40 in-flight jobs
#     froze the whole sync API while async ``/health`` stayed green;
#   * the scheduler via ``asyncio.to_thread`` — asyncio's default executor,
#     shared with ``/sanitize`` and the egress DNS filter.
#
# Neither capped the *number of jobs* (only the per-job / global device
# fan-out).  This module-level ``ThreadPoolExecutor`` is a dedicated pool for
# whole jobs: work runs off the shared pools, and ``max_workers`` gives an
# explicit ceiling on concurrent jobs (extra submissions queue FIFO and start
# as slots free — the job just stays ``pending`` until its turn, never a
# failure).  It mirrors the ``_GLOBAL_LIMITER`` idiom above: a lazily-built
# process-wide singleton behind a double-checked lock, with a reset helper so
# the size can be monkeypatched before first use in tests.
_JOB_EXECUTOR: ThreadPoolExecutor | None = None
_JOB_EXECUTOR_LOCK = threading.Lock()


def _job_executor() -> ThreadPoolExecutor:
    """Return the process-wide backup-job executor, building it once.

    Sized from :data:`~netcanon.config.MAX_CONCURRENT_BACKUP_JOBS`.  Lazily
    created (double-checked lock) so the size can be monkeypatched before
    first use in tests; :func:`reset_job_executor` drops the cached instance
    so a later call rebuilds at the patched size.  ``thread_name_prefix`` is
    ``"backup-job"`` so the dedicated threads are identifiable in logs / a
    thread dump (and assertable in tests).
    """
    global _JOB_EXECUTOR
    if _JOB_EXECUTOR is None:
        with _JOB_EXECUTOR_LOCK:
            if _JOB_EXECUTOR is None:
                _JOB_EXECUTOR = ThreadPoolExecutor(
                    max_workers=MAX_CONCURRENT_BACKUP_JOBS,
                    thread_name_prefix="backup-job",
                )
    return _JOB_EXECUTOR


def reset_job_executor(*, wait: bool = False, cancel_futures: bool = True) -> None:
    """Drop and shut down the cached backup-job executor.

    Called from the application lifespan on shutdown (clean thread release)
    and from tests (to rebuild the pool at a monkeypatched size).  The
    reference is cleared *inside* the lock and the (potentially blocking)
    ``shutdown`` runs *outside* it, so a concurrent :func:`_job_executor`
    immediately builds a fresh pool rather than handing back one that is
    being torn down.

    Args:
        wait: Passed to ``ThreadPoolExecutor.shutdown``.  Defaults to
            ``False`` so neither server shutdown nor a test teardown blocks
            behind an in-flight (possibly minutes-long) backup.
        cancel_futures: Passed to ``shutdown``.  Defaults to ``True`` so
            queued-but-not-started jobs are dropped on reset; the lifespan
            passes ``cancel_futures=False`` to let already-queued runs drain.
    """
    global _JOB_EXECUTOR
    with _JOB_EXECUTOR_LOCK:
        executor = _JOB_EXECUTOR
        _JOB_EXECUTOR = None
    if executor is not None:
        executor.shutdown(wait=wait, cancel_futures=cancel_futures)


def submit_backup_job(*args, **kwargs) -> Future:
    """Submit :func:`run_backup_job` to the dedicated backup-job executor.

    The single dispatch seam for the manual ``POST /api/v1/backups`` route
    (the scheduler uses ``loop.run_in_executor(_job_executor(), ...)`` so it
    can *await* completion on the event loop).  Positional / keyword arguments
    are forwarded verbatim to :func:`run_backup_job`.  Returns the
    :class:`~concurrent.futures.Future`; the route fires and forgets (the job
    mutates its own ``BackupJob`` state, persisted by ``run_backup_job``), so
    the caller need not hold the future — but returning it keeps the function
    testable and lets a caller wait if it wants to.

    Unlike the old ``BackgroundTasks`` dispatch, this does **not** run
    synchronously before the POST response: the job runs truly in the
    background, so ``POST /backups`` returns while the job is still
    ``pending`` and callers must poll ``GET /backups/{id}`` for the terminal
    state (see AGENTS.md "Hard Rules").
    """
    return _job_executor().submit(run_backup_job, *args, **kwargs)


def _process_one_device_limited(*args, **kwargs) -> None:
    """Run :func:`_process_one_device` while holding one global permit.

    The acquire is the cross-job ceiling (r7); the per-job pool's FIFO queue
    is the in-job ceiling.  The permit is taken *before* the wrapped call
    flips the result to ``running``, so a device waiting on a permit stays
    ``queued`` (accurate UI state).  The ``with`` block releases on every
    path — including the "should never happen" escape documented on
    :func:`_process_one_device` — so a permit can't leak.

    ``_process_one_device`` is referenced as a module global so test patches
    of that name (the documented collection seam) are still honoured through
    this wrapper.
    """
    with _global_collection_limiter():
        _process_one_device(*args, **kwargs)


def _process_one_device(
    job: BackupJob,
    idx: int,
    device: DeviceTarget,
    definitions: dict[str, DeviceDefinition],
    storage: BaseConfigStore,
    definition_loader: DefinitionLoader | None = None,
    device_profiles: dict[str, DeviceProfile] | None = None,
    device_profile_store: FileDeviceProfileStore | None = None,
    settings: Settings | None = None,
) -> None:
    """Run the backup for a single device and mutate ``job.results[idx]``.

    Extracted from :func:`run_backup_job` so the same code path runs
    whether a job uses the thread pool or executes sequentially
    (single-device jobs skip the pool for cleaner traces).

    Tests patch ``netcanon.api.routes.backups.get_collector`` to mock
    SSH/NETCONF/REST collection — see AGENTS.md "Hard Rules".  Never
    patch ``ConnectHandler`` or ``paramiko.SSHClient`` directly.  The
    factory is resolved via the route module (``backups.get_collector``)
    so that documented patch target keeps working from this service
    layer.

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
        settings: Job-level :class:`Settings` snapshot resolved once by
            :func:`run_backup_job` and injected onto the probe + collect
            collectors so each device doesn't re-read env / .env per SSH
            session.  ``None`` (direct callers / tests) leaves the
            collectors to resolve on demand.

    All exceptions are caught and recorded on the ``BackupResult``; this
    function therefore never raises under normal operation.  Ordinary
    operator-data problems (e.g. an unknown ``type_key`` absent from the
    definition library) are converted to a per-device ``failed`` result, not
    raised.  Any exception that does still escape indicates a programming bug
    in the backup runner itself and should surface.

    Thread safety: ``job.results[idx]`` is mutated only by the single
    worker assigned to index *idx*.  Other workers touch other indices,
    so no locking is required.  Python's GIL makes the individual attribute
    writes atomic.  Device-profile persistence uses the profile store's
    own atomic-write guarantees.
    """
    # Resolve the collector factory through the route module so the
    # documented mock-point (``netcanon.api.routes.backups.get_collector``)
    # is honoured from this service layer.  Lazy import keeps the
    # route → service dependency acyclic (the route module imports this
    # module at load time).
    from ..api.routes import backups as _backups_route

    result = job.results[idx]
    # Guard the definition lookup. A typo'd / renamed type_key is ordinary
    # operator data — device profiles and schedules do NOT validate it against
    # the loaded library — not a programming bug. A bare definitions[type_key]
    # KeyError here escapes the per-device try/except below: serial path leaves
    # the job stranded at "running" forever; parallel path leaves this device
    # "queued" so the terminal logic counts no failure and marks the job a
    # false "completed". Resolve an unknown type to an honest per-device
    # failure instead (blind audit 81d9740 T0-2).
    family_base = definitions.get(device.type_key)
    if family_base is None:
        result.status = "failed"
        result.error = (
            f"{device.host}: unknown device type {device.type_key!r} — not in "
            f"the loaded definition library. Check the device profile's type."
        )[:500]
        logger.error(
            "Job %s: device %s/%s has an unknown type_key %r (not in the "
            "definition library) — marking the device failed.",
            job.id, device.type_key, device.host, device.type_key,
        )
        return
    # Use the family-base collector for probe — connection-layer
    # settings (netmiko_device_type, auth) are stable across overlays.
    base_collector = _backups_route.get_collector(family_base)
    # Share the job-level Settings snapshot so probe + collect don't each
    # re-resolve env / .env on every SSH session (real collectors read
    # ``self.settings``; mock collectors ignore the attribute).
    base_collector.settings = settings

    detected_facts: dict[str, str] = {}
    if family_base.probe.command and definition_loader is not None:
        try:
            detected_facts = base_collector.probe(device, family_base)
        except Exception as exc:
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
            # Re-check membership and persist atomically: this worker thread
            # races route handlers that may delete/update the same profile.
            # The lock + in-loop re-fetch prevents a delete-then-save from
            # resurrecting a just-deleted profile to disk (review finding #10).
            with DEVICE_PROFILE_REGISTRY_LOCK:
                profile = device_profiles.get(device.device_profile_id)
                if profile is not None:
                    profile.detected_facts = detected_facts
                    device_profile_store.save(profile)
        except Exception as exc:
            logger.warning(
                "Failed to persist detected_facts for profile %s: %s",
                device.device_profile_id,
                exc,
            )

    # Use a per-definition collector for the actual collect — the
    # resolved overlay may have different commands or prompts than
    # the family base even though connection params are stable.
    collector = _backups_route.get_collector(definition)
    collector.settings = settings  # share the job-level snapshot (see above)
    result.status = "running"
    start = time.monotonic()
    try:
        raw_output = collector.collect(device, definition)
        record = storage.save(
            device_type=device.type_key,
            host=device.host,
            timestamp=datetime.now(UTC),
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
    except Exception as exc:
        # Route the raw exception through the operator-error translator
        # before persisting on the result row.  ``str(exc)`` pre-Round-3
        # produced wildly varying quality (good for in-house ValueError,
        # opaque for socket.timeout, leaky for OSError-on-save); the
        # translator collapses that surface into a host-prefixed
        # single-line operator-readable message with the underlying
        # exception type as a hint where helpful.  The full exception
        # still goes to the server log below via exc_info=True — the
        # diagnostic trail is preserved.
        from netcanon.api._errors import translate_backup_error
        result.error = translate_backup_error(
            exc, host=device.host, step="collect",
        )[:500]
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


def run_backup_job(
    job: BackupJob,
    request: BackupRequest,
    definitions: dict[str, DeviceDefinition],
    storage: BaseConfigStore,
    job_store: FileJobStore | None = None,
    max_workers: int = MAX_BACKUP_CONCURRENCY,
    definition_loader: DefinitionLoader | None = None,
    device_profiles: dict[str, DeviceProfile] | None = None,
    device_profile_store: FileDeviceProfileStore | None = None,
    settings: Settings | None = None,
) -> None:
    """Execute all device backups for *job* and update its state.

    Runs in a worker thread (FastAPI ``BackgroundTasks`` for the route,
    ``asyncio.to_thread`` for the scheduler); never returns to the route
    response — see AGENTS.md "Hard Rules".  ``POST /api/v1/backups``
    always returns ``status=pending`` and the caller polls
    ``GET /api/v1/backups/{id}`` for the terminal state this function
    writes.  Tests rely on TestClient executing background tasks
    synchronously before the POST response is returned.

    Device work is dispatched to a bounded ``ThreadPoolExecutor`` so up
    to *max_workers* devices are processed in parallel; additional
    devices wait in the executor's FIFO queue and start as slots free up.
    A *second*, process-wide ceiling
    (:data:`~netcanon.config.MAX_GLOBAL_BACKUP_CONCURRENCY`, enforced by the
    module-level limiter inside :func:`_process_one_device_limited`) caps the
    SUM of in-flight collections across *all* concurrent jobs, so N
    simultaneous jobs can't open N×*max_workers* sessions at once (r7).

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
            through to :func:`_process_one_device` for probe + overlay
            resolution.
        device_profiles: Optional in-memory profile registry threaded
            through for ``detected_facts`` persistence.
        device_profile_store: Optional persistence backend paired with
            ``device_profiles``.
        settings: Optional pre-resolved :class:`Settings`.  Resolved once
            here (``settings or Settings()``) and injected onto every
            device's collectors so the whole job shares one snapshot
            instead of re-reading env / .env per SSH session.

    Thread safety:
        * ``job.results`` is pre-populated before dispatch and is never
          resized after.  Each worker mutates exactly one element.
        * ``storage.save`` writes atomically via temp+rename; distinct
          ``(device_type, host)`` pairs produce distinct paths so there
          is no contention in the common case.
    """
    # Resolve Settings once for the whole job and inject it onto each
    # device's collectors (via _process_one_device) so probe + collect don't
    # each re-read env / .env per SSH session — and the whole job sees one
    # consistent snapshot even if the environment changes mid-run.
    job_settings = settings or Settings()

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
        # Still gated by the process-wide limiter so a single-device job
        # respects the global ceiling when other jobs are saturating it.
        for idx, device in enumerate(request.devices):
            _process_one_device_limited(
                job, idx, device, definitions, storage,
                definition_loader, device_profiles, device_profile_store,
                job_settings,
            )
    else:
        # Parallel path: up to `workers` devices in flight at once; the
        # executor itself queues the rest and drains FIFO.  The global
        # limiter (inside _process_one_device_limited) caps the SUM of
        # in-flight collections across this and every other live job.
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix=f"backup-{job.id[:8]}",
        ) as pool:
            futures = [
                pool.submit(
                    _process_one_device_limited, job, idx, device, definitions,
                    storage, definition_loader, device_profiles,
                    device_profile_store, job_settings,
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

    # Safety net: any device still non-terminal (queued/running) here never
    # reached a success/failed verdict — e.g. an unexpected worker escape
    # before its per-device try/except. The parallel path above logs such an
    # exception without re-raising, which would otherwise leave the device
    # "queued" so the terminal logic below counts zero failures and marks a
    # never-ran device a clean "completed". Force any non-terminal result to
    # "failed" so "the device never ran" can never read as success (blind
    # audit 81d9740 T0-2).
    for r in job.results:
        if r.status not in ("success", "failed"):
            r.status = "failed"
            if not r.error:
                r.error = (
                    f"{r.host}: backup did not run to completion "
                    "(the worker did not reach a terminal state)."
                )

    job.completed_at = datetime.now(UTC)
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
