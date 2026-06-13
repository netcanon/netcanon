# CA — Application Architecture (whole-tree lens)

*Read-only, review-grade audit of **netcanon** at commit `b08040c`
(v0.1.2).  Reviewer CA owns the whole-tree application-architecture
lens: the four-layer migration model, the two co-hosted concerns
(backup vs migration), the request lifecycle, dependency direction,
the DI seams, business-logic placement, async/sync boundaries, and
the desktop embedded-server split.  Assessed against the claimed
design in `ARCHITECTURE.md`.*

---

## 1. Scope & method

### What this chapter covers

This is the architecture-as-built reconstruction for netcanon's
Python application tree (`netcanon/` + `netcanon_desktop/`), read
against `ARCHITECTURE.md`'s claimed design.  My remit is structural,
not line-by-line: I do not own per-file correctness verdicts (that is
CB for platform / CC for codecs), nor god-file cohesion (CE), nor the
import-graph mechanics in fine detail (CD), nor error-taxonomy/security
(CF).  Where my findings touch those lenses I name the overlap and
defer the depth to the owning reviewer.

The questions I set out to answer:

1. Does the four-layer model (Vendor Definition ↔ Format Codec ↔
   Canonical Intent ↔ Transport) exist in the code, or only in the
   doc?
2. Are the two co-hosted concerns (backup, migration) genuinely
   decoupled, or do they bleed into each other?
3. What is the real request lifecycle — `main.py` factory → routers →
   services → storage/collectors — and where does business logic
   actually live?
4. **Dependency direction**: does anything import "upward"? Does a
   lower layer reach into a higher one?
5. Are the `get_collector` / `get_storage` DI seams real, single, and
   honoured?
6. The async/sync boundary: FastAPI routes calling synchronous,
   CPU-bound codec/pipeline code — is the thread-pool implication
   handled consistently?
7. Does the desktop embedded-server split (`netcanon_desktop/`) reuse
   the web app honestly, or fork logic?

### How I worked

Read-only throughout: `Read` / `Grep` / `Glob` only; no file mutated;
no sub-agents spawned.  I read the architectural spine in full
(`main.py`, `api/deps.py`, `services/migration_pipeline.py`,
`services/migration_validate.py`, every route module, the codec
contract `base.py` + `registry.py`, the migration package
`__init__.py`, `config.py`, and the desktop `app.py` / `server.py` /
`settings.py` / `__main__.py`).  I then ran targeted dependency-
direction sweeps with `Grep` (upward imports into `api/`; cross-layer
imports from `migration/` into `services`/`collectors`/`storage`;
`app.state` reach-ins outside `api/`; codec → `models` coupling).
Specific `file:line` evidence backs every finding.  Items I could not
fully confirm by static read are marked `UNVERIFIED`.

I read `ARCHITECTURE.md`, `AGENTS.md` § Hard Rules,
`docs/METHODOLOGY.md`, and the review snapshot/scope docs first, so
that load-bearing-by-design invariants (frozen pipeline signatures,
the single `get_collector`/`get_storage` mock points, ship-before-wire,
matrix-honesty) are recorded as OBSERVATIONs with rationale rather
than mis-filed as defects.

---

## 2. Executive summary

**Netcanon's application architecture is genuinely good and the code
agrees with `ARCHITECTURE.md` to an unusually high degree.** The
four-layer migration model is real and visible in the package
boundaries.  The two co-hosted concerns are cleanly separated — the
migration layer never imports the backup/collectors/storage/services
layers, and the backup layer never imports the migration codecs.  The
dependency direction is sound: `models/` is a true leaf (depends only
on stdlib + itself), every higher layer points down at it, and there
is **exactly one** upward import in the whole tree — and it is
*intra-`api/`*, not a cross-layer inversion.  The DI seams
(`get_collector`, `get_storage`, and the rest of `deps.py`) are real,
single, and honoured; `app.state` is confined to `main.py` + `api/`.
The desktop shell reuses the web app verbatim via `create_app(settings)`
with desktop-specific `Settings` — no forked business logic.

The frozen-signature contract on `migration_pipeline.py` holds, the
pipeline is a pure function, and the three public entries
(`run_plan` / `run_plan_with_rename` / `run_plan_with_overrides`) are
exactly the shape the doc and Hard Rules describe.  Route handlers are
overwhelmingly thin — `api/routes/migration.py` (678 LOC) is almost
entirely docstring + thin glue, with computation lifted into
`_migration_helpers.py`; `api/routes/ui.py` (894 LOC) is large mostly
because of ~370 lines of inlined Swagger-UI theming string constants,
not business logic.

The findings are mostly P2/P3/OBSERVATION:

* **CA-01 (P2)** — `POST /api/v1/sanitize` is the **one** route that
  runs heavy, synchronous, CPU-bound codec work (`sanitize_text`, a
  full parse→redact→render) **on the event loop**: it is declared
  `async def` yet calls the blocking function directly.  Every other
  pipeline-grade endpoint is sync `def` (offloaded to the threadpool),
  and the scheduler path is fastidious about `asyncio.to_thread`.
  This one endpoint is the inconsistency.
* **CA-02 (P3)** — the backup background-task *orchestration*
  (`_run_backup_job`, `_process_one_device`) lives **inside the route
  module** `api/routes/backups.py`, whereas the symmetric migration
  orchestration lives in `services/`.  An architectural asymmetry: the
  backup engine has no `services/` home.
* **CA-03 (P3 / cohesion-adjacent)** — `models/migration.py` (842 LOC)
  is an architectural crossroads: it co-locates the web-API request
  DTO (`MigrationPlanRequest`), the job-state aggregate (`MigrationJob`),
  *and* the codec-contract vocabulary (`CapabilityMatrix` / `LossyPath`
  / `UnsupportedPath`) that `migration/codecs/base.py` imports.  The
  codec contract type therefore lives outside the migration package.
* **CA-04 (OBSERVATION)** — the four codec→canonical reach-ins use a
  4-level relative import (`from ....models.migration import …`); deep
  but consistent and a direct consequence of CA-03's type placement.
* **CA-05 (OBSERVATION)** — `ARCHITECTURE.md` Layer 4 (Transport) is
  documented as the migration deploy path but is, as the doc itself
  says, not yet wired for migration; the `render`/`/render` alias and
  `plan_with_deploy` are forward-looking stubs.  Honestly disclosed,
  flagged here only for completeness.

**Verdict on code-vs-`ARCHITECTURE.md`:** strong agreement.  The doc
describes the system that is actually built.  The divergences I found
are (a) the sanitize async footgun, which the doc doesn't address
either way, (b) the backup-orchestration-in-routes asymmetry, which
the doc's "backup layer is architecturally simpler" framing
under-states, and (c) the `models/migration.py` placement of the codec
contract, which the doc's Layer-2 description ("Every codec declares …
`capability_matrix`") implies lives with the codec but actually lives
in `models/`.

---

## 3. The architecture as-built (layer & seam map)

### 3.1 The two concerns

`ARCHITECTURE.md` and `AGENTS.md` both open with "two concerns, one
app": **backup** (devices → SSH/NETCONF/REST → `configs/<host>.<ext>`)
and **migration** (stored config → `CanonicalIntent` → other-vendor
config).  This separation is real at the package level and enforced by
the import graph:

* `netcanon/collectors/` + `api/routes/backups.py` + `api/routes/schedules.py`
  are the backup spine.
* `netcanon/migration/` (codecs + canonical + cross-cutting policies)
  + `services/migration_pipeline.py` + `api/routes/migration.py` are
  the migration spine.
* The two meet only at the *edges*: both persist through `storage/`,
  both are wired by `main.py`, both surface DTOs from `models/`.  The
  migration layer **never** imports `collectors`, `services`, or
  `storage` (verified: `Grep` for those imports under
  `netcanon/migration/` returns nothing).  The backup layer never
  imports `migration/codecs/`.

That mutual non-reference is the load-bearing fact behind AGENTS.md's
"a change to one concern rarely touches the other."  It holds.

### 3.2 The four-layer migration model

`ARCHITECTURE.md` claims four decoupled layers.  As-built:

| Doc layer | Claimed home | As-built home | Verdict |
|---|---|---|---|
| L1 Vendor Definition | `definitions/*.yaml` + `definitions/schema.py` | `netcanon/definitions/` (loader + schema), YAML in repo `definitions/` | matches |
| L2 Format Codec | `migration/codecs/<vendor>/codec.py` | exactly that; `CodecBase` contract in `codecs/base.py`, `@register` auto-discovery via `pkgutil` | matches |
| L3 Canonical Intent | `migration/canonical/intent.py` | `CanonicalIntent` is in `canonical/intent.py` (confirmed via codec imports `from ...canonical.intent import CanonicalIntent`) | matches |
| Schema Validator | (sibling of codec in the diagram) | `services/migration_validate.py` — pure function, stage 4 | matches |
| L4 Transport | `collectors/` (backup only today) | `collectors/`; migration deploy not yet wired (doc admits this) | matches, with stub disclosure |

The model is not aspirational — the boundaries are physical packages,
and the pipeline funnels through them in the documented order
(`migration_pipeline.run_plan`: class-guard → parse → transforms →
validate → render, file `services/migration_pipeline.py:182-292`).

One nuance the doc under-states: the **codec contract metadata type**
(`CapabilityMatrix`, `LossyPath`, `UnsupportedPath`, `DeviceClass`)
lives in `models/migration.py`, not in `migration/codecs/`.  So the
codec layer reaches *sideways/down* into `models/` for its own
contract vocabulary (`codecs/base.py:31`,
`from ...models.migration import CapabilityMatrix`), while pulling the
canonical *tree* from `canonical/intent.py`.  See CA-03/CA-04.

### 3.3 Request lifecycle

The lifecycle matches the doc's "`main.py` factory → routers →
services → storage/collectors" almost exactly:

```
uvicorn netcanon.main:app   (or DesktopApp → create_app(settings))
   │
   ├─ create_app(settings)                         netcanon/main.py:67
   │    ├─ lifespan(): load definitions, vendors, target_profiles,
   │    │   storage, job_store + BackupJobRegistry, schedule_store,
   │    │   device_profile_store, APScheduler            main.py:86-211
   │    ├─ middleware: add_request_id (outermost)         main.py:257
   │    ├─ middleware: add_security_headers               main.py:284
   │    └─ include_router × 8 (+ ui at root)          main.py:294-302
   │
   ├─ Request → router handler  (api/routes/*.py)
   │    ├─ Depends(get_storage / get_jobs / …)           api/deps.py
   │    ├─ thin glue → services or canonical orchestrator
   │    └─ return Pydantic model (models/*)
   │
   └─ services/ (pure) → migration/ (pure) → storage/ (I/O) / collectors/ (I/O)
```

Two registration-order subtleties, both deliberate and documented in
code: `add_request_id` is registered *before* `add_security_headers`
so it wraps the outermost response (Starlette applies middleware in
reverse registration order — `main.py:247-252`), and `health_router`
is included first so its minimal handler wins over the (since-removed)
shadow `/health` in `ui.py` (`ui.py:887-894` carries the tombstone
comment).  These are the kind of load-bearing ordering decisions a
reviewer should *not* "tidy."

### 3.4 The DI seams

`api/deps.py` is the dependency-provider module: every shared object
(`definitions`, `definition_loader`, `storage`, `jobs`, `job_store`,
`schedules`, `schedule_store`, `scheduler`, `device_profiles`,
`device_profile_store`) is pulled from `request.app.state` behind a
`get_*` function injected via `Depends()`.  The module docstring states
the rationale plainly: "handlers never reference `app.state` directly …
swap the dependency override instead of patching `app.state`"
(`deps.py:1-14`).

`get_collector` is the *other* seam — it lives in `collectors/base.py:102`
as the single factory mapping `definition.collector.strategy` →
concrete collector, and AGENTS.md mandates that tests patch
`netcanon.api.routes.backups.get_collector` (the import site) rather
than `ConnectHandler`/`paramiko.SSHClient`.  `backups.py:50`
(`from ...collectors.base import get_collector`) is the canonical mock
point.  This is honoured — `get_collector` is invoked at
`backups.py:266` (probe collector) and `:332` (collect collector).

**Seam integrity check (dependency direction):**

* `app.state` reach-ins outside `main.py` + `api/`: a `Grep` returns
  only one storage-file hit, `storage/job_registry.py:18`, and that is
  inside a *docstring* explaining how the registry mirrors the dict
  surface `app.state.jobs` exposes — not executable code.  So
  `app.state` is correctly confined to the wiring + route layers.
* Upward imports into `api/`: a tree-wide `Grep` for
  `from …api` / `import …api` returns exactly **one** hit —
  `backups.py:366`, `from netcanon.api._errors import translate_backup_error`.
  That is `api/routes/backups.py` importing from `api/_errors.py`:
  intra-layer (both under `api/`), a deferred import inside the
  exception handler.  **Not** a lower layer reaching up.  No layering
  inversion exists.
* `migration/` → `services`/`collectors`/`storage`: zero imports
  (verified).  The migration engine is transport- and
  persistence-agnostic, exactly as the doc's "migration is file-input
  for now" framing requires.
* `models/` imports: only intra-`models` + stdlib
  (`models/diff.py:21` → `.backup`; `device.py`/`device_profile.py` →
  `.validators`).  A true leaf.

This is a clean, acyclic, downward-pointing dependency graph.  (CD owns
the exhaustive import-graph verdict; from the architecture lens the
direction is correct.)

### 3.5 The pipeline orchestrator (frozen-signature core)

`services/migration_pipeline.py` (711 LOC) is the migration engine.
Its three public functions are the frozen surface:

* `run_plan(source, target, raw_text, transforms=…, transform_specs=…, force=…)`
  — minimal pipeline (`:126`).
* `run_plan_with_overrides(... five rename maps ..., transforms=…, …)`
  — the growth-safe per-pane engine (`:295`).
* `run_plan_with_rename(... port_rename_map ...)` — a thin
  compatibility wrapper that normalises `None`→`{}` and forwards to
  `run_plan_with_overrides` (`:670-711`).

This is precisely the shape `ARCHITECTURE.md` § "Pipeline
orchestration" + "Per-pane overrides" and the AGENTS.md Hard Rule
describe.  The module is a **pure function — no I/O, no global state**
(docstring `:98`), and the per-pane categories are composed in the
documented fixed order (ports → vlans → local_users → snmp_community →
snmpv3_user) with the ports-first ordering being the only load-bearing
constraint.  The lazy imports of the canonical orchestrators
(`:418-430`) are an explicit, commented circular-dependency break
(those modules import `CodecBase`; this module imports `CodecBase`) —
load-bearing-by-design, not a smell.

### 3.6 The desktop split

`netcanon_desktop/` (11 modules) is the second platform.  The crucial
architectural fact: `DesktopApp.__init__` calls
`create_app(settings)` from `netcanon.main` (`app.py:36`, `:58`) —
**the exact same ASGI app the web platform serves**, parameterised by
a desktop `Settings` (loopback `127.0.0.1`, fixed internal port 8765,
`%APPDATA%` paths, `open_in_editor=True`) built in `settings.py:35`.
The embedded `ServerThread` (`server.py`) runs Uvicorn in a daemon
thread with `log_config=None` so it doesn't clobber the root logger
`configure_logging` installed.  There is **no forked business logic**:
the desktop is a shell (tray + WebView + embedded server) around the
shared factory.  This validates the doc's "FastAPI app … shared by web
+ desktop" claim and AGENTS.md's parallel-platform parity rule —
because both platforms share one app object, server-side feature parity
is automatic, and only genuinely platform-specific affordances
(`open_in_editor`, preferences dialog, single-instance mutex) diverge,
all of which AGENTS.md lists as sanctioned exceptions.

---

## 4. Findings (severity-ordered)

### CA-01 — `POST /api/v1/sanitize` runs CPU-bound codec work on the event loop  ·  **P2**

**File:** `netcanon/api/routes/sanitize.py:42-58`
(handler `async def post_sanitize`), calling
`netcanon/tools/sanitize.py:109` (`def sanitize_text`, synchronous).

**Claim.** The sanitize endpoint is the single route that violates the
otherwise-consistent async/sync discipline: it is declared `async def`
yet performs the full synchronous parse → redact → render pipeline
inline on the event loop, blocking it for the duration of every
request.

**Evidence.** The endpoint:

```python
# sanitize.py
async def post_sanitize(source_vendor: str = Form(...), config: UploadFile = File(...), dry_run: bool = Form(False)):
    ...
    raw_bytes = await config.read()
    raw = raw_bytes.decode("utf-8", errors="replace")
    result = sanitize_text(raw, source_vendor, dry_run=dry_run)   # ← synchronous, CPU-bound
```

`sanitize_text` is a plain synchronous function whose docstring states
its pipeline is "`parse(raw, source_codec)` → `sanitize_intent` →
`render(sanitized_intent, source_codec)`" (`tools/sanitize.py:109-120`)
— i.e. exactly the same heavy codec work (full parse + full render of
a potentially large config) that the migration endpoints run.  Because
`post_sanitize` is a coroutine, FastAPI runs it **directly on the
event loop**, so the parse/render holds the loop for its whole
duration, stalling all other concurrent requests on that worker.

Contrast the rest of the app, which is meticulous about this:

* Every migration pipeline endpoint is **sync `def`**
  (`migration.py:186` `plan_migration`, `:262` ports, `:319` vlans,
  `:375` local_users, `:439` snmp, `:504` snmpv3, `:593` detect) —
  FastAPI offloads sync defs to its threadpool, so the codec work never
  touches the loop.
* The scheduled-backup path is explicit:
  `schedules.py:75-82` dispatches the blocking SSH work via
  `asyncio.to_thread` with the comment "blocking SSH must not run on
  the event loop", and the module docstring repeats it
  (`schedules.py:7-9`).
* The UI HTML routes are `async def` but only read in-memory
  `app.state` + render Jinja — cheap, non-blocking — which is the
  correct use of `async def`.

So the architecture clearly *knows* the rule (sync def for blocking
work, `asyncio.to_thread` for blocking work inside coroutines).
`post_sanitize` is the one place it's broken.

**Why P2 not P1.** Impact is a single-process event-loop stall under
concurrent load, not a correctness bug; for the desktop platform
(single user, loopback) it is effectively harmless, and for the web
platform sanitize is a low-frequency operator action.  But it is a
real responsiveness footgun on a shared web deployment and an
inconsistency with the codebase's own discipline.

**Suggested direction.** Either (a) drop `async` and make it a plain
`def post_sanitize(...)` so FastAPI threadpools it — but then the
`await config.read()` needs handling (read the upload synchronously via
`config.file.read()`, or keep a tiny async shim that awaits the read
then `await run_in_threadpool(sanitize_text, …)`); or (b) keep `async
def` and wrap the heavy call: `result = await
fastapi.concurrency.run_in_threadpool(sanitize_text, raw,
source_vendor, dry_run=dry_run)`.  Option (b) is the smallest,
most-local fix and matches the `asyncio.to_thread` pattern already used
in `schedules.py`.

---

### CA-02 — Backup orchestration lives in the route module, not in `services/`  ·  **P3**

**File:** `netcanon/api/routes/backups.py:194-521`
(`_process_one_device`, `_run_backup_job`).

**Claim.** The backup engine's core orchestration — per-device collect,
layered-definition resolution, probe, thread-pool fan-out, terminal-
state computation, persistence — is implemented as module-level
functions *inside the route file*, whereas the structurally analogous
migration orchestration lives in `services/migration_pipeline.py`.
This is an architectural asymmetry: backup has no `services/` home.

**Evidence.** `backups.py` is 520 LOC; the two route handlers
(`create_backup`, `list_jobs`, `get_job`) are thin, but
`_run_backup_job` (`:382-521`) and `_process_one_device` (`:194-380`)
together are ~330 LOC of genuine orchestration logic: the
`ThreadPoolExecutor` fan-out (`:473`), the probe → resolve → overlay-
swap → detected-facts-persist sequence (`:263-327`), and the
all-success/all-fail/mixed terminal-status logic (`:499-507`).  In the
migration concern, this class of logic is in `services/`; in the
backup concern it is in `api/routes/`.

The same functions are *also* imported and reused by the scheduler:
`schedules.py:115` does `from .backups import _run_backup_job`.  So a
non-route module (`schedules.py`) reaches into a route module to borrow
the orchestration — a sign the logic wants to live one layer down,
in something like `services/backup_runner.py`, where both the route and
the scheduler would import it without the route module becoming a de
facto service.

**Why P3.** It works, it's tested, and it doesn't violate dependency
direction (both `backups.py` and `schedules.py` are in `api/`).  But it
muddies the "routes orchestrate / services compute" line the migration
side keeps crisp, and it means `ARCHITECTURE.md`'s "the backup layer is
architecturally simpler — see `collectors/README.md`" framing
under-states where the backup *orchestration* actually lives (it's not
in `collectors/`; it's in the route module).

**Suggested direction.** Extract `_run_backup_job` / `_process_one_device`
into `netcanon/services/backup_runner.py` (mirroring
`migration_pipeline.py`), leaving `backups.py` with just the route
handlers + the `get_collector` mock-point import.  This is a pure move-
refactor with no behaviour change; the AGENTS.md mock-point rule is
unaffected because tests patch `…routes.backups.get_collector` at the
*import site*, which would need to become `…services.backup_runner.get_collector`
(a documented hard-rule consequence — flag for CD/CF on the test-impact
side).  Lower priority than CA-01; record as a structural-debt item.

---

### CA-03 — `models/migration.py` is an architectural crossroads (API DTO + job state + codec contract in one module)  ·  **P3 (cohesion-adjacent; CB/CE own depth)**

**File:** `netcanon/models/migration.py` (842 LOC).

**Claim.** This single module co-locates three distinct architectural
roles: (1) the web-API **request DTO** `MigrationPlanRequest` (`:622`)
and response DTO `CodecInfo` (`:799`); (2) the migration **job-state
aggregate** `MigrationJob` (`:318`) + `MigrationJobStatus` (`:294`); and
(3) the **codec-contract vocabulary** `CapabilityMatrix` (`:154`),
`LossyPath` (`:116`), `UnsupportedPath` (`:136`), `DeviceClass` (`:31`),
`VendorInfo` (`:87`) that the codec layer imports as its declaration
shape.  The consequence is that the *codec contract type lives outside
the migration package* — `migration/codecs/base.py:31` imports
`CapabilityMatrix` from `...models.migration`.

**Evidence.** `Grep` for class definitions in the file shows the full
mixed inventory (DeviceClass, VendorInfo, LossyPath, UnsupportedPath,
CapabilityMatrix, XPathDelta, ValidationReport, TransformSpec,
MigrationJobStatus, MigrationJob, MigrationPlanRequest, CodecInfo).
The codec base contract opens with
`from ...models.migration import CapabilityMatrix` (`base.py:31`), and
every one of the 8 codecs + the mock imports `CapabilityMatrix /
LossyPath / UnsupportedPath / DeviceClass` from `....models.migration`
(verified across all `codec.py` files).

**Why this is architecturally relevant (not just cohesion).** The
dependency direction is still *down* (codecs → models is fine; models
is the leaf).  But the placement means the "Format Codec" layer's own
contract metadata is defined in the shared `models/` package alongside
the HTTP request body it has nothing to do with.  `ARCHITECTURE.md`
§ Layer 2 lists `capability_matrix` as something "Every codec
declares", which reads as though the type lives with the codec; in
fact a codec author must reach into `models/migration.py` for it.  This
is defensible — `CapabilityMatrix` is a Pydantic model serialised over
the API (`GET /adapters/{name}/capabilities` returns it directly,
`migration.py:164`), so it has a legitimate API-DTO identity — but the
module is doing three jobs and is a natural split candidate.

**Suggested direction.** This is primarily CB's (correctness/clarity of
the god-file) and CE's (cohesion/SRP) call; from the architecture lens
I'd note one clean seam: the codec-contract cluster (`CapabilityMatrix`
/ `LossyPath` / `UnsupportedPath` / `DeviceClass`) could move to
`migration/codecs/contract.py` (or `migration/_contract.py`) so the
codec layer owns its own vocabulary, leaving `models/migration.py` with
the API DTOs + job state.  That would tighten Layer 2's self-containment
and make `ARCHITECTURE.md`'s Layer-2 description literally true.  Defer
the split decision to CE.

---

### CA-04 — Codec→canonical reach-ins use a 4-level relative import  ·  **OBSERVATION**

**File:** all `migration/codecs/<vendor>/codec.py`, e.g.
`arista_eos/codec.py:42` (`from ....models.migration import …`).

**Claim/Evidence.** Every codec imports its contract metadata four
levels up (`....models.migration`).  This depth is a direct consequence
of CA-03 (the contract type lives in `models/`, four packages away from
`codecs/<vendor>/`).  It is *consistent* across all codecs and not in
itself a defect — but deep relative imports are a readability/refactor-
fragility tax, and they're the visible symptom of the contract-type
placement.  If CA-03's seam move happens, these become
`from ..contract import …` (two levels), which is both shorter and
semantically clearer ("my own layer's contract").  No action
independent of CA-03.  CD owns the import-style verdict.

---

### CA-05 — Layer 4 (Transport) for migration + `/render` split are forward-looking stubs  ·  **OBSERVATION**

**Files:** `ARCHITECTURE.md` § Layer 4; `api/routes/migration.py:560-581`
(`render_migration` is "Currently an alias for `plan_migration`").

**Claim/Evidence.** `ARCHITECTURE.md` says migration is "file → codec →
file" today and the deploy/transport push is "Phase 2+"; the code
agrees — `/render` is an explicit alias retained for a future split
(docstring `:573-580`), and `migration_pipeline.py`'s docstring names
`plan_with_deploy` / `plan_with_diff` as *future* functions, not
shipped ones.  This is honest disclosure consistent with the matrix-
honesty discipline (no active lie: the alias docstring says it's an
alias).  I flag it only so the reviewer set has it on record: the
migration concern's Transport layer is documented-but-unwired, which is
why `collectors/` is referenced under Layer 4 but only the backup side
exercises it.  No defect.

---

## 5. Dependency-direction assessment

This is the heart of my lens, so I state the verdict explicitly.

**The dependency graph is acyclic and points downward.** Concretely:

| From layer | Imports … | Upward? |
|---|---|---|
| `api/routes/*` | `services`, `migration`, `storage`, `collectors`, `models`, `deps`, `api/_errors` | no (all down or intra-`api`) |
| `services/*` | `migration.codecs`, `migration.canonical`, `models`, sibling `services` | no |
| `migration/codecs/*` | `migration.canonical`, `models` (contract types) | no |
| `migration/canonical/*` | sibling `canonical` (`intent`, etc.) only | no |
| `collectors/*` | `definitions`, `models` | no |
| `storage/*` | `models` | no |
| `models/*` | intra-`models` + stdlib | leaf |

**The single upward-looking import** in the entire tree —
`backups.py:366` → `netcanon.api._errors` — is intra-`api/` (a route
importing a sibling error-translation helper), deferred into the
exception handler, and therefore not a layering inversion.  I looked
specifically for the failure modes my brief names: nothing imports
"upward" into `api/` from a lower layer; no lower layer reaches into a
higher one; `migration/` does not reach into `collectors`/`services`/
`storage`; `app.state` does not leak outside `main.py` + `api/`.

**The one place where layering is *muddied* rather than *inverted*** is
CA-03: the codec contract vocabulary lives in `models/` rather than in
the codec package.  That keeps the *direction* correct (codecs → models
is downward) but means Layer 2 doesn't fully own its own contract type.
It's a placement question, not a cycle.

**Net:** dependency direction is healthy.  This is one of the
codebase's strongest architectural properties and it is not accidental
— the lazy-import circular-break in `migration_pipeline.py:418` and the
`TYPE_CHECKING`-guarded `PortIdentity` import in `codecs/base.py:33`
show the authors actively manage import direction.

---

## 6. What's architecturally GOOD

A review that only lists findings would misrepresent this tree.  The
following are genuine strengths, several of them load-bearing-by-design:

1. **The app factory is textbook.** `create_app(settings)` (`main.py:67`)
   produces fully-independent instances with isolated state, which is
   exactly what makes per-test isolation cheap and what lets the
   desktop reuse the web app.  The module docstring documents both the
   production `app` object and the test-injection pattern.

2. **DI is real and single.** `deps.py` providers + the
   `get_collector` / `get_storage` factories give exactly the mock
   points AGENTS.md mandates; `app.state` is confined to the wiring
   layer; route handlers take dependencies via `Depends()` rather than
   reaching into globals.

3. **Routes are thin; computation is lifted.**
   `api/routes/migration.py` (678 LOC) is ~80% docstring + thin glue;
   the actual request/response shaping is in `_migration_helpers.py`
   (`resolve_adapter_or_422`, `resolve_input_text`,
   `request_has_overrides_or_profile`, `build_codec_info_list`), whose
   own docstring states the principle: "Routes orchestrate; these
   helpers compute" (`_migration_helpers.py:26`).  This is the right
   instinct, and it's been applied deliberately (the module header
   names the "refactor/god-file-cleanup" branch that extracted them).

4. **The pipeline is a pure, frozen-signature function** with a
   three-way terminal outcome (`completed` / `partial` / `failed`),
   honest exception taxonomy (`ParseError` / `RenderError` /
   catch-all-with-stage-preservation, `migration_pipeline.py:241-265`),
   and a growth-safe extension point (`run_plan_with_overrides`) that
   has demonstrably scaled five times (ports → vlans → local_users →
   snmp → snmpv3) without touching the frozen signatures.

5. **The codec contract + auto-registration are clean.** `CodecBase`
   (ABC with sensible no-op defaults for `probe`, `classify_port_name`,
   `format_port_identity`, `iter_xpaths`) plus `@register` +
   `pkgutil` discovery means adding a codec is a genuine drop-in, and
   the discovery loop is resilient (a broken codec is logged and
   skipped, `migration/__init__.py:59-67`) — so one bad adapter can't
   take down the registry.

6. **The desktop split reuses, doesn't fork.** `create_app(settings)`
   shared between platforms is the single most important reason the
   parallel-platform parity rule is actually satisfiable rather than
   aspirational.

7. **Concurrency is handled correctly almost everywhere.** Sync `def`
   for codec/pipeline endpoints (threadpool offload), `async def` only
   for cheap in-memory UI reads, `asyncio.to_thread` for blocking SSH
   inside the scheduler coroutine, a bounded `ThreadPoolExecutor` for
   backup fan-out with documented per-index thread-safety
   (`backups.py:429-434`), and an LRU-bounded job registry to cap
   memory.  CA-01 (sanitize) is the lone exception that proves the
   rule.

8. **Middleware ordering and the removed-shadow `/health`** are
   commented with their rationale — the kind of load-bearing detail
   that survives audits precisely because the "why" is inline.

---

## 7. Coverage table

Every architecturally-significant file I read, with a one-line verdict.
(Per the scope doc, CA is a cross-cutting lens; file-by-file *verdicts*
are CB/CC's remit — this table records what I touched for the
architecture assessment, not a substitute for their per-file passes.)

| File | LOC (approx) | Architecture verdict |
|---|---|---|
| `netcanon/main.py` | 315 | Clean factory + lifespan; middleware order deliberate. GOOD. |
| `netcanon/api/deps.py` | 94 | The DI seam; thin, correct, single-purpose. GOOD. |
| `netcanon/api/routes/migration.py` | 678 | Thin handlers + docstrings; computation in helpers. GOOD. |
| `netcanon/api/routes/_migration_helpers.py` | 184 | "Routes orchestrate, helpers compute." Model citizen. GOOD. |
| `netcanon/api/routes/backups.py` | 520 | Handlers thin BUT orchestration (`_run_backup_job`) lives here, not in `services/`. CA-02. |
| `netcanon/api/routes/ui.py` | 894 | Large from ~370 LOC inlined Swagger theming, not logic; handlers thin. WATCH (CE owns size). |
| `netcanon/api/routes/sanitize.py` | 85 | `async def` running sync CPU-bound `sanitize_text` on loop. CA-01 (P2). |
| `netcanon/api/routes/configs.py` | 318 | Sync defs, thin, correct open-in-editor gating + allowlist. GOOD. |
| `netcanon/api/routes/schedules.py` | (read 1-120) | Exemplary `asyncio.to_thread` discipline; borrows `_run_backup_job` (CA-02 corollary). GOOD. |
| `netcanon/services/migration_pipeline.py` | 711 | Pure, frozen-signature core; growth-safe. GOOD. |
| `netcanon/services/migration_validate.py` | (read 1-60) | Pure stage-4 validator; correct layer. GOOD. |
| `netcanon/migration/codecs/base.py` | 365 | Clean ABC contract; sane no-op defaults. Contract type imported from `models/` (CA-03). GOOD. |
| `netcanon/migration/codecs/registry.py` | 73 | Minimal, idempotent, read-only-at-runtime registry. GOOD. |
| `netcanon/migration/__init__.py` | 77 | Resilient `pkgutil` auto-discovery; one bad codec ≠ dead registry. GOOD. |
| `netcanon/migration/canonical/transforms.py` | (import scan) | Imports only `intent` within canonical layer. Clean. GOOD. |
| `netcanon/migration/canonical/port_names.py` | 614 | Orchestrator returns `PortRenameResult(applied/dropped/warnings)` exactly as doc claims. GOOD (CE owns size). |
| `netcanon/models/migration.py` | 842 | Crossroads: API DTO + job state + codec contract. CA-03/CA-04. |
| `netcanon/models/*` (others) | — | Leaf layer; intra-`models` imports only. GOOD. |
| `netcanon/collectors/base.py` | 133 | `get_collector` single factory + `BaseCollector` ABC. The transport seam. GOOD. |
| `netcanon/config.py` | 94 | Pydantic-settings; `effective_data_dir` desktop override. GOOD. |
| `netcanon_desktop/app.py` | 162 | Reuses `create_app(settings)`; no forked logic. GOOD. |
| `netcanon_desktop/server.py` | 151 | Daemon Uvicorn thread, readiness event, `log_config=None`. GOOD. |
| `netcanon_desktop/settings.py` | 99 | Frozen-vs-dev path resolution + prefs overlay. GOOD. |
| `netcanon_desktop/__main__.py` | 101 | Single-instance guard + MessageBox fatal handling. GOOD. |

---

## 8. Open questions (for the adversarial pass / other reviewers)

1. **CA-01 confirmation under load (`UNVERIFIED` at runtime).** I have
   statically confirmed `post_sanitize` is `async def` and
   `sanitize_text` is synchronous CPU-bound work.  I have *not* run a
   concurrency benchmark to measure the actual event-loop stall.  The
   architectural claim (heavy sync work on the loop blocks it) is
   well-established FastAPI behaviour, so the *finding* is solid; the
   *magnitude* is `UNVERIFIED`.  CF (perf lens) may want to quantify.

2. **CA-02 test-impact (`UNVERIFIED`).** I assert that extracting
   `_run_backup_job` to `services/` would shift the AGENTS.md mock
   point from `…routes.backups.get_collector` to a new module.  I have
   not enumerated how many tests patch that exact dotted path; CD/CF
   should count before any refactor is scoped, because the mock-point
   rule is a Hard Rule and the patch target is load-bearing.

3. **CA-03 seam decision deferred to CE.** Whether the codec-contract
   cluster should move out of `models/migration.py` is a cohesion call
   I'm flagging but not deciding.  The question for CE: is
   `CapabilityMatrix`'s dual identity (API DTO *and* codec contract) a
   reason to keep it in `models/`, or a reason to split and re-export?

4. **Vendors-registry seam (not deeply read).** `app.state.vendors` is
   loaded via `load_vendors()` (`main.py:107`) from
   `migration/vendors/`, and `migration/vendors/__init__.py:26` imports
   `VendorInfo` from `models.migration`.  This is consistent with the
   CA-03 pattern (vendor metadata type in `models/`).  I did not read
   the vendors loader in full — CB owns it — but note it as another
   instance of the same models-as-shared-vocabulary pattern, in case
   the adversarial pass wants to check it isn't a hidden cycle (it
   isn't, per my import sweep, but I read the loader only at the import
   line).

5. **Is the `/render` alias drift-safe?** `render_migration` aliases
   `plan_migration` today (CA-05).  When Phase 2 splits them, the
   matrix-honesty discipline requires the docstring to stop saying
   "Currently an alias."  Not a current defect; a future doc-sync
   obligation worth recording so the adversarial pass doesn't re-flag
   the alias as a stale comment.

---

*End of CA chapter.  All findings grounded in `file:line`; runtime-
magnitude claims marked `UNVERIFIED`.  No project file was modified in
the course of this review.*
