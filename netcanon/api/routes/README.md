# API routes — orientation guide

This README is the entry guide for the FastAPI route layer.  If you're
adding a new endpoint (a backup hook, a per-pane migration override,
a new UI page), start here.

---

## Purpose

This directory hosts the FastAPI route handlers.  Each module is a
`APIRouter`; routes call into `netcanon/services/` (or the storage
and definition layers) for business logic.  **Routes orchestrate;
services compute.**  Keep route handlers thin — parse the request,
call a service, return the model.  Anything non-trivial (canonical
translation, diff computation, plan rendering) belongs in a service
module so it stays unit-testable without spinning up a TestClient.

The split mirrors the 4-layer design in `ARCHITECTURE.md`: routes are
the outer layer, services / migration pipeline / storage are the
inner layers.

---

## Route file index

| File | Mount prefix | Concern |
|---|---|---|
| `backups.py` | `/api/v1/backups` | Device backup orchestration via `BackgroundTasks`; job creation + polling |
| `configs.py` | `/api/v1/configs` | Stored config CRUD + plain-text viewer + open-in-editor (desktop only) |
| `definitions.py` | `/api/v1/definitions` | Vendor definition browsing + `POST /reload` |
| `device_profiles.py` | `/api/v1/devices` | Device-class metadata (saved connection profiles) |
| `migration.py` | `/api/v1/migration` | Translation orchestration + per-pane plan endpoints + adapter introspection |
| `schedules.py` | `/api/v1/schedules` | Recurring (APScheduler) backup jobs |
| `ui.py` | (root) | Server-rendered Jinja2 pages (`/`, `/configs`, `/migrate`, `/definitions`, `/jobs`, `/docs`) — `include_in_schema=False` |

The mount prefixes above are the effective paths after
`netcanon/main.py` adds its `/api/v1` prefix on top of each router's
own `prefix=...` declaration.  `device_profiles.py` declares
`prefix="/devices"` (not `/device_profiles`) — its concern is "saved
device targets," not the term "profile."  `ui.py` mounts at root
because pages live at `/`, not `/api/v1/`.

---

## Conventions

### Dependency injection

Services, storage, the definition registry, the job store, and the
APScheduler instance all flow into route handlers via FastAPI
`Depends(...)` factories defined in `netcanon/api/deps.py`.  Don't
import services at module top and call them directly — the test
suite swaps the dependency to inject test fixtures.

```python
def list_configs(storage: BaseConfigStore = Depends(get_storage)) -> ...:
    return storage.list_configs()
```

### Pydantic models

Request and response shapes live in `netcanon/models/`.  Don't
define inline schemas in route files — they should be importable
from tests and from the service layer.  When a route needs a new
shape, add it to `netcanon/models/` and import it.

### `BackgroundTasks` rule

`POST /api/v1/backups` returns a `BackupJob` with status `pending`
**immediately**, before the background task has run.  To read the
final state, GET the job by ID:

```python
resp = client.post("/api/v1/backups", json={...})
job_id = resp.json()["id"]
final = client.get(f"/api/v1/backups/{job_id}").json()
```

This is a **Hard Rule** in `CLAUDE.md`: never assert on the POST
response body for final job state.  Under `TestClient`, background
tasks are executed before the response returns, so the GET reflects
the completed state — but the POST body itself is serialised before
that runs.

### Mock-point for backup tests

The single factory tests patch is
`netcanon.api.routes.backups.get_collector`.  This is a **Hard
Rule** in `CLAUDE.md`: never patch `ConnectHandler` or
`paramiko.SSHClient` directly.  The `get_collector` indirection
exists specifically so that one swap covers every transport
(Netmiko, NETCONF, REST) without leaking transport details into
test code.

### testid discipline

Adding a route that renders a UI element?  Every interactive
element needs a `data-testid` attribute, and the new id must be
documented in `tests/testid_reference.md` in the same commit.  Run
`grep -r 'data-testid="<new-id>"' tests/testid_reference.md` before
committing — empty output means the doc is stale.

### Helper modules

Routes orchestrate; non-trivial computation belongs in
`netcanon/services/`.  When a route module accumulates request-shaping
or response-shaping helpers that don't quite warrant a service
(per-request validation, registry-introspection joins, predicate
helpers consumed only by sibling routes), lift them into a sibling
`_<router>_helpers.py` rather than letting the route file balloon.
`migration.py` + `_migration_helpers.py` is the worked example —
helpers extracted for adapter-name resolution (422-translation),
input-text resolution (`raw_text` XOR `source_filename`),
target-profile lookup, codec-info shaping, and the
"engage-rename-aware-pipeline?" predicate.  The leading underscore
marks the module as routes-only (don't import it from services or
templates) and keeps the public surface — the FastAPI route handlers
themselves — visible at the top of the corresponding non-underscore
module.

### Per-pane migration endpoints

`migration.py` exposes per-category override endpoints under
`/api/v1/migration/plan/{ports|vlans|local_users|snmp|snmpv3}` for
the Tier-3 rename modal.  Each one delegates to a single function,
`run_plan_with_overrides`, with one category map populated and the
others left empty.  This keeps the routes nearly identical and the
service-layer work in one place.

**Hard Rule** (`CLAUDE.md`): never change the
`run_plan_with_overrides` signature.  New rename categories ride on
the existing override-dict shape — add a field, don't add a
parameter.  The `migration.py` module docstring enumerates the
endpoints; update it in the same commit when you add a sibling.

---

## Adding a new route

1. **Pick the right router.**  Match by concern.  Add a new file
   only when the concern doesn't fit any existing router (rare).
2. **Define request / response models** in `netcanon/models/`.
   Don't inline schemas in the route file.
3. **Implement service logic** in `netcanon/services/<concern>.py`
   (or in `netcanon/migration/` for translation work) when it's
   non-trivial.  The route stays thin.
4. **Wire the handler with `Depends`** for everything it needs —
   storage, definitions, jobs, scheduler.  Don't reach into
   `request.app.state` directly when a `Depends` factory exists.
5. **Update `netcanon/main.py`** to `include_router` the new
   router (only when adding a new file).
6. **Add an integration test** in
   `tests/integration/test_<concern>_routes.py` that exercises the
   full request/response cycle through `TestClient`.
7. **Template / UI surfaces:** if the route renders a template or
   serves a snippet consumed by the front-end, update
   `tests/testid_reference.md` and add an e2e test under
   `tests/e2e/`.
8. **Update the module docstring** if it enumerates routes
   (`migration.py` does — see its top-of-file listing).  Stale
   docstrings that promise endpoints that don't exist (or omit ones
   that do) become the worst kind of lie.
9. **Cross-platform check:** new pure API endpoints automatically
   work on the desktop platform (the desktop binds the same
   FastAPI app on `127.0.0.1`).  New UI surfaces still need the
   feature-parity check from `CLAUDE.md` — confirm the desktop
   shell renders the page acceptably inside the embedded WebView.

---

## Frozen surfaces

Some signatures are load-bearing across dozens of tests and route
handlers.  **Never change them**; add new functions instead.

- `migration_pipeline.run_plan`, `run_plan_with_rename`,
  `run_plan_with_overrides` — the three pipeline entry points
  consumed by `migration.py`.  Per-pane endpoints rely on the
  exact override-dict shape; tests rely on the keyword arguments.
  See the module docstring in
  `netcanon/services/migration_pipeline.py` for the
  freeze-and-extend contract.
- `POST /api/v1/backups` response shape — the entire test tier
  assumes the synchronous response is `pending` and that final
  state comes from a follow-up GET.  Changing this would silently
  break the BackgroundTasks timing convention.

If you need different behaviour, ship a NEW endpoint or a NEW
function alongside the frozen one.

---

## See also

- [`../../services/`](../../services/) — service layer (business logic the routes call into)
- [`../../models/`](../../models/) — Pydantic request / response shapes
- [`../../../ARCHITECTURE.md`](../../../ARCHITECTURE.md) — 4-layer design context
- [`../../../tests/testid_reference.md`](../../../tests/testid_reference.md) — interactive-element inventory
- [`../../../tests/integration/`](../../../tests/integration/) — route-level test patterns
- [`../../../docs/glossary.md`](../../../docs/glossary.md) — project-jargon reference (created in the same commit batch)
