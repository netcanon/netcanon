# result-RA-18 — R-18 / CA-02: extract backup orchestration → `services/backup_runner.py`

**Finding:** `findings-register.md` R-18 (code-review CA-02).
**Type:** behavior-preserving move-refactor.
**Confidence:** **HIGH** (pure move; the one subtle point — the
`get_collector` mock-point — is handled explicitly and verified against
all ~60 patch sites).

---

## 1. Finding + current state

Backup orchestration lives **inside the route module**
`netcanon/api/routes/backups.py`:

- `_process_one_device` — `netcanon/api/routes/backups.py:194-379`
  (per-device collect, probe → resolve → overlay-swap → detected-facts
  persist, terminal per-device status, operator-error translation).
- `_run_backup_job` — `netcanon/api/routes/backups.py:382-521`
  (`ThreadPoolExecutor` fan-out, serial fast-path, terminal
  all-success/all-fail/mixed status, optional `job_store.save`).

Together ~330 LOC of genuine orchestration in a route file, asymmetric
with migration (which has `netcanon/services/migration_pipeline.py`).

The scheduler **reaches into the route module** to borrow it:
`netcanon/api/routes/schedules.py:115` does
`from .backups import _run_backup_job` (function-local import inside
`_run_scheduled_backup_inner`).

### Callers of the moved functions (complete map)

Verified via grep across the whole tree (excluding `build/`, docs,
CHANGELOG):

| Caller | Site | How it calls |
|---|---|---|
| `create_backup` route | `backups.py:134` | `background_tasks.add_task(_run_backup_job, …)` — **same module today**, becomes a cross-module import after the move |
| `_run_backup_job` | `backups.py:466, 479` | calls `_process_one_device` (serial + pool paths) — **moves with it; stays intra-module inside `backup_runner`** |
| `_run_scheduled_backup_inner` | `schedules.py:115, 202` | function-local `from .backups import _run_backup_job`; dispatches via `asyncio.to_thread(_run_backup_job, …)` |

**No test imports `_run_backup_job` or `_process_one_device` directly**
(grep for `import … _run_backup_job` / `from …backups import` across
`tests/` → no matches). Every test exercises them **transitively
through the HTTP endpoints** while patching
`netcanon.api.routes.backups.get_collector`. This is the load-bearing
fact for the whole refactor (see §5).

### `get_collector` call sites inside the moved code

Both inside `_process_one_device`:
- `backups.py:266` — `base_collector = get_collector(family_base)` (probe collector)
- `backups.py:332` — `collector = get_collector(definition)` (main collect collector)

Today `get_collector` is resolved from the module-level import at
`backups.py:50` (`from ...collectors.base import get_collector`). Tests
patch the **name in the `routes.backups` namespace**, so the patch takes
effect because the call looks the name up there.

---

## 2. The mock-point problem and the chosen solution (READ FIRST)

**Hard rule (AGENTS.md):** tests mock SSH at exactly
`netcanon.api.routes.backups.get_collector`. There are **~60 patch
sites** at that literal string across
`tests/integration/`, `tests/e2e/`, `tests/desktop/`, plus the canonical
fixture at `tests/integration/conftest.py:37`. The factory's own
docstring (`netcanon/collectors/base.py:108`) and four `*.md` docs name
this exact target. **It must not change.**

Naïve move breaks it: if `_process_one_device` moves to
`backup_runner.py` and calls a `get_collector` imported into
`backup_runner`'s namespace, then
`patch("netcanon.api.routes.backups.get_collector", …)` patches a name
the service never reads — every mocked test would attempt real SSH and
fail. (The CA-02 investigation flagged this exact risk at
`01-investigation-CA-app-architecture.md:427-431`, suggesting the patch
target would have to migrate to `…services.backup_runner.get_collector`.
**We do NOT take that option** — migrating ~60 patch sites + 5 docs is
high-blast-radius churn and breaks the documented Hard Rule contract.)

**Chosen solution — preserve the patch target with zero test changes:**

1. `backup_runner.py` does **not** import `get_collector` at module
   level. Inside `_process_one_device` it does a **function-local**
   `from ..api.routes import backups as _backups_route` and calls
   `_backups_route.get_collector(...)`. Attribute access on the module
   object is resolved **at call time**, so
   `patch("netcanon.api.routes.backups.get_collector", …)` (which
   replaces that attribute on the module object) is honoured exactly as
   before.
2. `backups.py` **keeps** its module-level
   `from ...collectors.base import get_collector` (line 50) so the
   attribute `netcanon.api.routes.backups.get_collector` continues to
   exist as a patchable name. It is no longer *called* in `backups.py`,
   but it remains the canonical, documented mock seam.

This also breaks the import cycle: `backups.py` imports `backup_runner`
at module level (for `add_task`), and `backup_runner` imports the
`backups` route module **lazily inside the function** — never at module
load. This mirrors the codebase's established lazy-import discipline
(`schedules.py:115`, every `migration_pipeline.py` builder import).

> Trade-off note for the orchestrator: the *purist* fix is to move the
> mock seam to the service and re-point all tests. The *contract-stable*
> fix (this one) keeps the seam where AGENTS.md, 5 docs, and 60 tests
> already point it, at the cost of one documented "service reaches back
> to the route module for the patchable `get_collector` attribute"
> indirection. Given R-18 is a **P3 structural-debt** item and the Hard
> Rule is explicit, contract-stable is the right call. The residual
> oddity (service importing from the route layer) is annotated in the
> `backup_runner` docstring. If a future change wants to invert this
> (move the seam down), that is a separate, larger PR that must touch all
> 60 sites + docs in lockstep — out of scope here.

---

## 3. New file — **full content** of `netcanon/services/backup_runner.py`

> This is the verbatim move of `_process_one_device` + `_run_backup_job`
> from `backups.py:194-521`, with imports relocated and the two
> `get_collector(...)` calls rewritten to `_backups_route.get_collector(...)`
> via a function-local import. Logic, control flow, threadpool boundary,
> terminal-status computation, and the `translate_backup_error` local
> import are byte-for-byte preserved.

```python
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
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone

from ..config import MAX_BACKUP_CONCURRENCY
from ..definitions.loader import DefinitionLoader
from ..definitions.schema import DeviceDefinition
from ..models.backup import BackupJob, BackupResult, JobStatus
from ..models.device import BackupRequest, DeviceTarget
from ..models.device_profile import DeviceProfile
from ..storage.base import BaseConfigStore
from ..storage.device_profile_store import FileDeviceProfileStore
from ..storage.job_store import FileJobStore

logger = logging.getLogger(__name__)


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
    # Resolve the collector factory through the route module so the
    # documented mock-point (``netcanon.api.routes.backups.get_collector``)
    # is honoured from this service layer.  Lazy import keeps the
    # route → service dependency acyclic (the route module imports this
    # module at load time).
    from ..api.routes import backups as _backups_route

    family_base = definitions[device.type_key]
    # Use the family-base collector for probe — connection-layer
    # settings (netmiko_device_type, auth) are stable across overlays.
    base_collector = _backups_route.get_collector(family_base)

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
    collector = _backups_route.get_collector(definition)
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
```

### Note on the public rename `_run_backup_job` → `run_backup_job`

The dispatched function is now part of a service's public surface (two
modules import it), so it loses the leading underscore: **`run_backup_job`**.
`_process_one_device` stays underscore-private (only `run_backup_job`
calls it, intra-module). This matches `migration_pipeline.py`'s
convention (public `run_plan*`, no private helpers exported). All call
sites updated below reflect the rename. *(If the orchestrator prefers a
zero-rename diff, keep the name `_run_backup_job` and import it under
that name everywhere — the refactor is otherwise identical. Renaming is
the cleaner choice and there are only two call sites + one new import.)*

---

## 4. Edits to existing files (literal old → new)

### 4a. `netcanon/api/routes/backups.py`

**Edit 1 — module docstring: note where the engine now lives.** Append
to the existing mocking-convention paragraph (lines 34-37).

OLD:
```python
Mocking convention: tests mock collection by patching
``netcanon.api.routes.backups.get_collector`` — the single factory
this route delegates to.  Never patch ``ConnectHandler`` or
``paramiko.SSHClient`` directly.
"""
```
NEW:
```python
Mocking convention: tests mock collection by patching
``netcanon.api.routes.backups.get_collector`` — the single factory
this route delegates to.  Never patch ``ConnectHandler`` or
``paramiko.SSHClient`` directly.  The orchestration that *calls* this
factory now lives in :mod:`netcanon.services.backup_runner`; it
resolves the factory back through this module
(``backups.get_collector``) so this patch target is unchanged.
"""
```

**Edit 2 — imports.** The orchestration's transport/threadpool imports
move out; add the service import. Several model/storage imports are now
used only by `create_backup` (which still needs `BackupJob`, `JobStatus`,
`BackupRequest`, the `Depends` providers' type hints) — keep those;
drop the ones used *only* by the moved functions (`time`,
`ThreadPoolExecutor`/`wait`, `BackupResult`, `DeviceTarget`,
`BaseConfigStore`). **Verify each before deletion (see the per-symbol
table after this block).**

OLD (lines 40-69):
```python
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
```
NEW:
```python
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
```

Per-symbol justification for the import diff (verified against the
remaining route handlers `create_backup` / `list_jobs` / `get_job`):

| Symbol | Kept? | Reason |
|---|---|---|
| `time` | **removed** | only `_process_one_device` used `time.monotonic()` |
| `ThreadPoolExecutor, wait` | **removed** | only `run_backup_job` |
| `get_collector` | **kept (F401)** | mock-point seam; no longer called here but must remain a patchable attribute |
| `MAX_BACKUP_CONCURRENCY` | **kept** | `create_backup:132` default for `getattr(...,"backup_concurrency", MAX_BACKUP_CONCURRENCY)` |
| `DefinitionLoader` | **kept** | `create_backup` `Depends(get_definition_loader)` type hint (`:86`) |
| `DeviceDefinition` | **kept** | `create_backup` `definitions: dict[str, DeviceDefinition]` hint (`:85`) |
| `BackupJob` | **kept** | `create_backup` builds it (`:124`); response_model on all three routes |
| `BackupResult` | **removed** | only `run_backup_job` pre-populates results |
| `JobStatus` | **kept** | `create_backup:126` `status=JobStatus.pending` |
| `BackupRequest` | **kept** | `create_backup` `request_body: BackupRequest` (`:82`) |
| `DeviceTarget` | **removed** | only `_process_one_device` annotated it |
| `DeviceProfile` | **kept** | `create_backup` `device_profiles: dict[str, DeviceProfile]` hint (`:90`) |
| `BaseConfigStore` | **removed** | only used as `storage` hint inside moved funcs; `create_backup` uses `storage: BaseConfigStore = Depends(get_storage)` — **SEE BLOCKER B1** |
| `FileDeviceProfileStore` | **kept** | `create_backup` `Depends(get_device_profile_store)` hint (`:91`) |
| `BackupJobRegistry` | **kept** | `list_jobs`/`get_job`/`create_backup` `jobs` hint |
| `FileJobStore` | **kept** | `create_backup` `job_store` hint (`:89`) |
| `run_backup_job` (new) | **added** | dispatched by `create_backup` |

> **BLOCKER B1 (must verify at actuation):** `create_backup`'s signature
> annotates `storage: BaseConfigStore = Depends(get_storage)`
> (`backups.py:87`). So **`BaseConfigStore` IS still used** by the route
> and must be **KEPT**, contradicting the "removed" row above. I am
> 95% sure it stays. Resolution: **keep `from ...storage.base import
> BaseConfigStore`** in `backups.py`. I flag it rather than silently
> deciding because the import-pruning is the one place a stray
> unused-import (F401) lint could trip. Safe rule for the orchestrator:
> run `ruff`/`flake8` after applying and let it report any truly-unused
> import; only `time`, `ThreadPoolExecutor`, `wait`, `BackupResult`,
> `DeviceTarget` are *guaranteed* unused post-move. Keep `BaseConfigStore`.

**Corrected NEW imports block (with `BaseConfigStore` retained):**
```python
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
```

**Edit 3 — `create_backup` dispatch call: `_run_backup_job` → `run_backup_job`.**

OLD (lines 134-145):
```python
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
```
NEW:
```python
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
```

**Edit 4 — delete the moved functions.** Remove **everything from line
189 through line 521** (the section banner comment + both functions):

DELETE (backups.py:189-521):
```python
# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------


def _process_one_device(
    ...   # entire body
) -> None:
    ...


def _run_backup_job(
    ...   # entire body
) -> None:
    ...
```
After this deletion, `backups.py` ends at the `get_job` handler
(originally line 186). The file becomes ~155 LOC of pure route handlers
+ the mock-point import.

### 4b. `netcanon/api/routes/schedules.py`

**Edit 5 — rewire the borrow + the dispatch call.** The function-local
import switches from the route module to the service, and the
`asyncio.to_thread` target follows the rename.

OLD (lines 110-115):
```python
    # Local imports to avoid circular dependency at module load time
    from pydantic import SecretStr

    from ...models.device import BackupRequest, DeviceCredentials, DeviceTarget
    from ...models.device_profile import DeviceProfile
    from .backups import _run_backup_job
```
NEW:
```python
    # Local imports to avoid circular dependency at module load time
    from pydantic import SecretStr

    from ...models.device import BackupRequest, DeviceCredentials, DeviceTarget
    from ...models.device_profile import DeviceProfile
    from ...services.backup_runner import run_backup_job
```

OLD (lines 201-215):
```python
    await asyncio.to_thread(
        _run_backup_job,
        job,
        request,
        app.state.definitions,
        app.state.storage,
        job_store,
        max_workers,
        # P1C3 layered-definition + probe wiring — schedule-triggered
        # backups get the same overlay resolution + detected_facts
        # persistence as interactive ones.
        getattr(app.state, "definition_loader", None),
        getattr(app.state, "device_profiles", None),
        getattr(app.state, "device_profile_store", None),
    )
```
NEW:
```python
    await asyncio.to_thread(
        run_backup_job,
        job,
        request,
        app.state.definitions,
        app.state.storage,
        job_store,
        max_workers,
        # P1C3 layered-definition + probe wiring — schedule-triggered
        # backups get the same overlay resolution + detected_facts
        # persistence as interactive ones.
        getattr(app.state, "definition_loader", None),
        getattr(app.state, "device_profiles", None),
        getattr(app.state, "device_profile_store", None),
    )
```

> Note: the `schedules.py` import can now be promoted to module level
> (no cycle: `schedules.py` does not import `backups.py`, and
> `backup_runner` imports the route only inside its function). The
> docstring at `schedules.py:110` still says "to avoid circular
> dependency at module load time" — leaving the import function-local is
> the **minimal, behavior-identical** change and keeps that comment
> truthful, so I keep it local. Optional cleanup, not required.

### 4c. Doc/comment de-stale (optional, low priority — within R-18 scope)

These reference the old location; behavior-preserving but worth a touch
so the next reader isn't misled. **Not required for tests to pass.**

- `netcanon/api/_errors.py:46` — `:func:\`netcanon.api.routes.backups._run_backup_job\`` → `:func:\`netcanon.services.backup_runner.run_backup_job\``.
- `netcanon/api/routes/schedules.py:62,76,78,106` (docstrings) — "runs `_run_backup_job`" phrasing → "runs `run_backup_job`" (mention `services.backup_runner`).
- `ARCHITECTURE.md` — the "backup layer is architecturally simpler" framing (referenced in CA-02) can note `services/backup_runner.py` now houses the orchestration. **Defer to RA-docs / orchestrator** — don't expand scope here.

The **mock-point docs** (`collectors/README.md`, `api/routes/README.md`,
`AGENTS.md`, `glossary.md`, `collectors/base.py:108` docstring) all name
`netcanon.api.routes.backups.get_collector` — **these stay correct and
must NOT change**, because the patch target is preserved.

---

## 5. Test plan

**Net test-source changes required: ZERO.** The entire value of the
chosen design is that the mock-point string is unchanged, and no test
imports the moved functions by name. Validation is "run the existing
suites and confirm green."

### Why no test edits are needed (the proof)

- Patch sites all use the literal `"netcanon.api.routes.backups.get_collector"`:
  `tests/integration/conftest.py:37`, `tests/e2e/conftest.py:140`,
  `tests/desktop/test_backups_aruba_desktop.py:81`,
  `tests/desktop/test_backups_juniper_desktop.py:82`, and the per-test
  patches in `test_backup_probe_wiring.py` (8×), `test_backups_api.py`
  (5×), `test_backups_juniper.py`, `test_backups_aruba.py` (2×),
  `test_backups_arista.py` (2×), `test_load_and_memory.py` (5×),
  `test_configs_api.py`, `test_ui_routes.py` (4×). All resolve the
  attribute on the `routes.backups` module **at call time**; the moved
  `_process_one_device` reads it from that same module object via the
  function-local import → patch intercepts unchanged.
- No `from …backups import _run_backup_job` / `_process_one_device` in
  `tests/` (grep confirmed zero matches), so the rename + move touches
  no test imports.

### Exact commands to run (orchestrator, after applying)

```powershell
# 1. Import-graph / circular-import smoke (fastest signal):
py -c "import netcanon.api.routes.backups, netcanon.api.routes.schedules, netcanon.services.backup_runner; print('import OK')"

# 2. Lint the pruned imports (catches stray F401 — confirms BLOCKER B1):
py -m ruff check netcanon/api/routes/backups.py netcanon/services/backup_runner.py
#   (or: py -m flake8 netcanon/api/routes/backups.py)

# 3. Backup integration suite — the core mock-point coverage:
py -m pytest tests/integration/test_backups_api.py tests/integration/test_backup_probe_wiring.py -q

# 4. Per-vendor backup round-trips (same get_collector patch):
py -m pytest tests/integration/test_backups_juniper.py tests/integration/test_backups_aruba.py tests/integration/test_backups_arista.py -q

# 5. Scheduler path (transitively dispatches run_backup_job via asyncio.to_thread):
py -m pytest tests/e2e/test_jobs_schedules.py -q

# 6. Concurrency / persistence invariants (relies on FileJobStore.save in run_backup_job):
py -m pytest tests/integration/test_load_and_memory.py -q

# 7. Full sweep last:
py -m pytest -q
```

### Coverage map — which test asserts which moved behavior

| Moved behavior (orig line) | Covering test | What it proves |
|---|---|---|
| `get_collector` resolution (266, 332) | every backup test via the conftest patch | **mock-point preserved** — if broken, ALL mocked tests attempt real SSH and fail/hang |
| probe → resolve → overlay swap (263-306) | `test_backup_probe_wiring.py::TestLayeredResolveFromDetectedFacts` | overlay selection from detected facts / pins |
| probe non-fatality (272-278) | `test_backup_probe_wiring.py::TestProbeFailureIsNonFatal` | probe raises → backup still completes |
| detected_facts persistence (311-327) | `test_backup_probe_wiring.py::TestDetectedFactsPersistence` | facts saved to profile; not saved w/o profile_id |
| `translate_backup_error` on failure (356-369) | `test_backups_api.py` failure cases | operator-error string shape |
| terminal status all/none/mixed (499-507) | `test_backups_api.py`, per-vendor suites | completed / failed / partial |
| threadpool fan-out + serial fast-path (463-496) | `test_load_and_memory.py` (multi-device) | parallel + serial paths |
| `job_store.save` after completion (516-520) | `test_load_and_memory.py:146` | persistence call fires |
| scheduler dispatch via `asyncio.to_thread` (schedules) | `test_jobs_schedules.py` | async→thread boundary intact |

If steps 3–6 are green, the move is behavior-identical.

---

## 6. Risk + blast radius

**Overall: LOW.** Pure move; no logic touched.

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Mock-point breakage** (the only real risk) | Low | Chosen design keeps the patch string identical; `_process_one_device` reads `get_collector` from the `routes.backups` module at call time. Step 3 of the test plan is the canary — if it's green, the seam holds. |
| Circular import at load | Very low | `backups.py` imports `backup_runner` at module level; `backup_runner` imports `backups` **only inside `_process_one_device`** (function-local). Step 1 smoke-import proves acyclicity. |
| Stray unused-import lint (F401) in `backups.py` | Low | Step 2 ruff/flake8; per-symbol table above; `get_collector` deliberately `# noqa: F401`. **Keep `BaseConfigStore`** (BLOCKER B1). |
| `async`/threadpool boundary change | None | `run_backup_job` body is byte-identical incl. `ThreadPoolExecutor`; callers still wrap it (`add_task` / `to_thread`). Not moved into/out of any async context. |
| Public-name rename ripples | Very low | Only 2 call sites + 1 new import reference `run_backup_job`; no test imports the symbol. Rename is mechanical. |

**Additive / unchanged:** the FastAPI route signatures, response models,
HTTP status codes, `Depends` providers, `get_collector`/`get_storage`
seams, AGENTS.md Hard Rule, and all 5 mock-point docs are untouched.

---

## 7. Self-assessment

**Confidence: HIGH** that this is behavior-preserving and the
mock-point is intact, conditioned on the test plan running green
(steps 3–6 are the real proof — orchestrator validates at actuation).

**Open questions / decisions for the orchestrator:**

1. **B1 — keep `BaseConfigStore` import in `backups.py`.** `create_backup`
   still type-annotates `storage: BaseConfigStore`. The corrected NEW
   imports block (end of §4a) keeps it. Confirm with ruff (step 2).
2. **Rename `_run_backup_job` → `run_backup_job`?** I chose the rename
   (matches `migration_pipeline.py`'s public-surface convention; only
   2 call sites + 1 import affected, 0 tests). If you prefer a
   strictly-minimal diff, keep the underscore name everywhere — the move
   is otherwise identical. Your call; everything in §3/§4 reflects the
   rename.
3. **Promote `schedules.py` import to module level?** Now safe (no
   cycle). I kept it function-local to stay minimal and keep the
   "avoid circular dependency" comment truthful. Optional cleanup.
4. **Doc de-stale (§4c) — bundle here or hand to RA-docs?** The
   `_errors.py:46` and `schedules.py` docstring refs point at the old
   `routes.backups._run_backup_job` location. Low priority; not needed
   for green tests. The ARCHITECTURE.md "backup layer simpler" framing
   that CA-02 calls out is a natural companion edit but I left it to
   avoid scope creep with RA-docs.

**No blockers beyond B1.** The refactor is ready to actuate.
