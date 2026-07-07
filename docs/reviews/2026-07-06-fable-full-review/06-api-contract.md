# 06 — Public API & contract fidelity

Reviewer: Fable max-effort pass, 2026-07-06, target main @ 8598d74 (v0.5.3).
Scope: `netcanon/api/routes/*.py`, `netcanon/api/{auth,deps,_errors}.py`, `netcanon/models/{backup,device,device_profile,schedule,migration,diff}.py`, `netcanon/cli.py`, `netcanon/main.py` (OpenAPI wiring). Cross-checked against the 2026-07-03 review's `21-cli-api.md` (API-1..API-7) so remediated items are not re-reported; live probes ran against an in-process `TestClient` app (lifespan-complete) plus a dumped `/api/v1/openapi.json`.

**Verdict: one MAJOR documented-affordance-that-silently-no-ops (reproduced over HTTP), one MEDIUM list-endpoint truthfulness gap (reproduced at registry level incl. a degenerate documented setting that empties the endpoint permanently), plus five minors — two of which are unfixed residue of the previous review's API-3/API-6.**

---

### F-1 (MAJOR, confirmed) — `PUT /api/v1/devices/{id}`: documented "pass `None` to clear" is a silent no-op; there is no way to clear `enable_password` / `notes` / `os_version` / `model` at all

**Where:** `netcanon/api/routes/device_profiles.py:141` vs `netcanon/models/device_profile.py:155-159` (the `DeviceProfileUpdate` docstring), compounded by `netcanon/templates/devices.html:458-462`.

The update model's contract explicitly promises null-to-clear:

```
enable_password: New privileged-exec password; pass ``None`` to clear.
notes: New free-text notes; pass ``None`` to clear.
os_version: New OS-version pin; pass ``None`` to clear the pin ...
model: New model pin; pass ``None`` to clear.
```

The handler makes that impossible:

```python
updates = {k: v for k, v in body.model_dump().items() if v is not None}
```

`model_dump()` (without `exclude_unset=True`) cannot distinguish "field omitted" from "field explicitly null", and the `is not None` filter then drops both. **Reproduced over HTTP**: create a profile with `enable_password="SECRET"`, `os_version="17.12"`, then `PUT {"enable_password": null, "os_version": null, "notes": null}` → **200 OK**, response still shows `os_version: "17.12"`, internal state still holds `enable_password='SECRET'`. A misleading success: the client asked for a clear, got a 200, and nothing changed.

**Compounding trap:** the UI deliberately doesn't offer clearing and its code comment sends operators to exactly this broken path — `devices.html:460-462`: *"Operators who need to CLEAR a pin after setting it must do so via the API directly."* The API directly ignores it. The only real workaround is delete + recreate the profile, which mints a new UUID and silently orphans every schedule referencing the old id in `target_device_ids` (schedule runs then skip the device with only a server-side log line).

**Failure scenario:** operator pins `os_version: "17.12"` on a profile; device is later downgraded / replaced; operator PUTs `{"os_version": null}` per the documented contract → 200, pin persists → every subsequent backup silently resolves the 17.12 definition overlay against a device that no longer runs it. Same shape for a decommissioned enable password.

**Fix:** in `update_device_profile`, use `updates = body.model_dump(exclude_unset=True)` so explicit nulls survive; reject `None` for the non-nullable fields (`name`, `type_key`, `host`, `port`, `username`, `password`) with a 422; apply `None` as a genuine clear for `enable_password` / `notes` / `os_version` / `model`. Add an integration test `test_update_clears_pin_with_explicit_null` (the existing `test_update_without_pin_fields_preserves_pins` at `tests/integration/test_device_profiles_api.py:98` locks only the omitted-field half; no test covers explicit null). Then delete the devices.html comment's false referral or add a real "clear pin" affordance.

Confidence: **confirmed** (reproduced at pydantic level and end-to-end over HTTP).

---

### F-2 (MEDIUM, confirmed) — `GET /api/v1/backups/` claims "Return all backup jobs" but returns only the memory-resident LRU cache; with the documented `NETCANON_MAX_MEMORY_JOBS=0` the endpoint is permanently empty

**Where:** `netcanon/api/routes/backups.py:266-275` (OpenAPI summary "List all backup jobs", description "Return all backup jobs, sorted newest-first.") vs `netcanon/storage/job_registry.py:222-231` (`values()` — "memory-resident jobs only") and `netcanon/storage/job_registry.py:149-152` (`__setitem__` drops everything when `max_memory_jobs == 0`). Also `netcanon/config.py:171-177`.

The registry is explicit that `values()` never touches disk; the route's public contract (which is what flows into `/api/v1/openapi.json` — verified in the dumped schema) says "all". Two reproduced consequences:

1. **Truncation at the cap** — registry with `max_memory_jobs=2`, 4 jobs inserted (all persisted to disk): `values()` returns 2. On a default install (cap 1000, project's own sizing note says ~10k jobs/year) the list endpoint silently sheds history after ~5 weeks; there is no pagination parameter, no `X-Total-Count`, no indicator that the list is partial. Get-by-id still finds evicted jobs (disk lazy-load), so automation that lists-then-filters behaves differently from automation that GETs by id — an invisible inconsistency.
2. **Degenerate documented setting** — `Settings.max_memory_jobs` allows `ge=0` and its docstring says "Set to 0 to disable in-memory caching entirely (**every read hits disk**)" (`config.py:176-177`). Reproduced: with cap 0, insert + persist a job → `values()` returns `[]`, `get(id)` works. So an operator who sets `NETCANON_MAX_MEMORY_JOBS=0` gets 202s from POST, working by-id GETs, and a **permanently empty** `GET /api/v1/backups/` — plus an empty Jobs page and dashboard (`ui.py:178-209` iterate the same `values()`). "Every read hits disk" is false for the list read.

**Fix (minimum, honest-docs):** change the route summary/docstring to "List recent backup jobs (the most-recent `max_memory_jobs` held in memory; older jobs remain retrievable by id)" and fix the `config.py` docstring ("get-by-id reads hit disk; the list endpoint serves only memory-resident jobs, so 0 empties it"). **Fix (better):** make `list_jobs` fall back to / merge with `job_store` (e.g. when `len(cache) < total_disk_count()`), or add explicit `limit/offset` paging over the disk store; forbid `0` (`ge=1`) if the empty-list mode isn't intended to be supported.

Confidence: **confirmed** (registry behavior reproduced both ways; route/OpenAPI text read from the generated schema).

---

### F-3 (MINOR, confirmed) — CLI `netcanon sanitize -o <unwritable-path>` still dies with a raw traceback (the unfixed half of prior-review API-3)

**Where:** `netcanon/cli.py:182-183`.

The 2026-07-03 review's F-3/API-3 had two halves; commit `059883f` (#285) fixed only the `RenderError` half (both CLI and HTTP route now catch it). The `write_text` half was never applied — the output write still sits outside any try:

```python
if args.output:
    Path(args.output).write_text(result.sanitized_text, encoding="utf-8")
```

**Reproduced today:** `py -m netcanon.cli sanitize -i ok.txt -s cisco_iosxe_cli -o C:/definitely/no/such/dir/out.txt` → raw `FileNotFoundError` traceback, exit code **1**. Contrast the input side (`cli.py:137-139`): unreadable input → `error: cannot read ...`, exit **2**. Asymmetric operator contract: read errors are clean exit-2 one-liners, write errors are stack traces — and the sanitized output is lost.

**Fix:** wrap the write in `try/except OSError` → `print(f"error: cannot write {args.output!r}: {e}", file=sys.stderr); return 2` (mirroring the read guard).

Confidence: **confirmed** (reproduced; commit diff of #285 shows the write guard was never added).

---

### F-4 (MINOR, confirmed) — Same error class, different status codes: unknown codec name is 400 on `/sanitize` but 422 on every migration endpoint

**Where:** `netcanon/api/routes/sanitize.py:49-54` (unknown `source_vendor` → **400**) vs `netcanon/api/routes/_migration_helpers.py:56-62` (`resolve_adapter_or_422`: unknown `source`/`target` adapter → **422**, with an explicit rationale comment "adapter name is REQUEST-PAYLOAD data; callers should fix their body").

Reproduced live: `POST /api/v1/sanitize` with `source_vendor=nope` → 400; `POST /api/v1/migration/plan` with `source=nope` → 422. Both are "you named a codec that doesn't exist" against the same registry. A programmatic client (or gateway retry policy) that keys off status class gets two different answers for one mistake. Within `/sanitize` itself the split continues: `ParseError` → 400 (`sanitize.py:82-86`) but `RenderError` → 422 (`sanitize.py:87-94`).

**Fix:** align `/sanitize`'s unknown-vendor rejection to 422 via the same helper (or document the 400 deliberately in the route's `responses=`). Cheap; no behavioral risk beyond the status code itself (grep shows no test pins the 400 status specifically — `tests/integration/test_sanitize_api.py` should be updated in the same commit).

Confidence: **confirmed** (both statuses reproduced in one session).

---

### F-5 (MINOR, confirmed) — OpenAPI declaration gaps: `/sanitize` 200 declared as `application/json` (actually `text/plain`), undeclared custom header, and undeclared 4xx/5xx across the CRUD routes

**Where:** `netcanon/api/routes/sanitize.py:33-47, 110-115`; `netcanon/api/routes/configs.py:65-118, 121-213`; `netcanon/api/routes/backups.py:148-153, 278-308`; `netcanon/api/routes/device_profiles.py`; `netcanon/api/routes/schedules.py`; `netcanon/api/routes/definitions.py:38-63`.

From the generated `/api/v1/openapi.json` (dumped from a live app):

* **`POST /api/v1/sanitize`** declares 200 with `application/json` + empty schema. The actual default success is a `PlainTextResponse` (text/plain) carrying the `X-Netcanon-Substitution-Count` header (undeclared); the `dry_run=true` JSON audit shape (`{substitutions:[{category,field,original,redacted}], total}`) appears nowhere in the schema; the real 400 (unknown vendor / parse failure) and 413 (upload cap) are undeclared. This is the one endpoint the docs push Docker users toward (`sanitize.py:5-7`) — and it's the least accurately described. Notably the migration routes DO declare their custom header (`X-Netcanon-Job-Status`, `migration.py:150-168`) — the project standard exists; sanitize just doesn't follow it.
* **404s undeclared on every resource route that raises them**: `GET/DELETE /configs/{filename}`, `POST /configs/{filename}/open` (also 403/400/501/500 undeclared), `GET /backups/{job_id}`, `GET/PUT/DELETE /devices/{id}`, `DELETE /schedules/{id}`, `POST /schedules/{id}/toggle`, `GET /definitions/{type_key}`. The dumped schema shows these ops declaring only `[2xx, 422]`. `POST /backups/` can return 400 (egress-blocked, `backups.py:208-218`) and 409-ish limits on devices/schedules (`device_profiles.py:90-94`, `schedules.py:334-338`) — all undeclared. Migration + diff routes declare their 404/422s; the rest of the surface doesn't. Generated clients model half the API's error space.

**Fix:** add `responses={...}` maps mirroring the migration-route pattern; for sanitize add `response_class=PlainTextResponse` plus an explicit 200 content override documenting both modes and the header.

Confidence: **confirmed** (read from the generated schema, not just source).

---

### F-6 (MINOR, confirmed) — `request_has_overrides_or_profile` docstring still claims the no-override path is "plain `run_plan` … unchanged" (missed site of API-6 remediation)

**Where:** `netcanon/api/routes/_migration_helpers.py:173-174`.

> "Legacy callers that supply none of these get the plain :func:`run_plan` path unchanged."

False since v0.3.2: the `/plan` else-branch calls `run_plan_with_overrides(source, target, raw_text, port_rename_map={}, force=...)` (`migration.py:294-296`), i.e. auto port-name translation IS engaged for bare requests. The 2026-07-03 synthesis listed this exact line under API-6; the #285 fix patched `models/migration.py` and `migration.py` but not this helper. A developer extending the predicate from its docstring will mis-model the routing (the precise confusion that produced the original API-1 MAJOR).

**Fix:** one-line docstring correction: "Callers that supply none of these still get auto port-name translation via `run_plan_with_overrides(port_rename_map={})` — see the route's else-branch."

Confidence: **confirmed** (code read; both sites quoted).

---

### F-7 (MINOR, confirmed) — Device-profile docs say `type_key` "Must match a loaded definition"; create/update never validate it — a typo'd profile 201s and only fails at backup run-time

**Where:** `netcanon/models/device_profile.py:33, 113` (docstrings) vs `netcanon/api/routes/device_profiles.py:71-148` (no registry check on POST or PUT). Contrast `POST /api/v1/backups/` which DOES 422 unknown `type_key`s up front (`backups.py:185-195`).

The runtime half is deliberately handled — `backup_runner.py:232-246` explicitly notes "device profiles and schedules do NOT validate it against the loaded library" and converts the miss into an honest per-device `failed` result — so this is not a crash bug. But the model docs (the API's written contract) imply create-time enforcement that doesn't exist. Failure scenario: `POST /api/v1/devices/` with `type_key: "Ciscoo"` → 201; profile is attached to a schedule; every scheduled run marks the device failed with "unknown device type" — discovered days later on the Jobs page instead of at creation. The UI dropdown prevents this for browser users; direct API/automation users (the ones reading the docstrings) get no guard.

**Fix:** either (a) validate `type_key` against `get_definitions` in create/update → 422 with the loaded-keys list (matching the backups route's message shape), or (b) soften the two docstrings to "should match a loaded definition `type_key`; validated when a backup runs, not at profile creation."

Confidence: **confirmed** (behavioral path read end-to-end; deliberate-runtime-handling comment quoted).

---

## Checked, no finding (for the synthesis pass)

* **Prior-review remediations verified live**: `/plan` else-branch auto-translate fix (API-1) present (`migration.py:275-296`); `X-Netcanon-Job-Status` set + OpenAPI-declared on all 7 job-running POSTs; sanitize wrong-vendor now raises `ParseError` (API-4) and `RenderError` → 422/exit-2 (API-3 render half); demo partial → non-zero (API-5); `/plan/snmpv3` docstring (API-2); `port_rename_map` docstring (API-6, `models/migration.py` site); API-7 affordance dropped in #292 (`strip_unsupported` gone from `netcanon/` — only CHANGELOG/plan/test references remain).
* **Write-only credential contracts hold**: `DeviceProfilePublic` / `BackupSchedulePublic` / `ScheduleDevicePublic` on every response path incl. list/create/toggle; `_resolve_credentials` server-side resolution 422s cleanly when neither inline creds nor a resolvable profile exist.
* **`resolve_input_text` XOR contract** (422 both/neither, 404 missing file) consistent across `/plan*`, `/render`, `/detect`; `/detect` now carries the same 10M `max_length` cap as `/plan` (prior F-8 fixed).
* **Auth**: `require_api_key` constant-time compare, 401 + `WWW-Authenticate: Bearer`; OpenAPI BearerAuth scheme injected only when a key is configured (schema honesty), `/api/v1/openapi.json` deliberately open (documented in `auth.py`).
* **Legacy schedule shape**: `POST /schedules/` with old inline `devices` fails loud (422 "At least one of target_type_keys or target_device_ids…"), and the reshape was CHANGELOG-documented — no silent break.
* **`BackupRequest`** `min_length=1, max_length=500`; job-id path pattern guard (422 for non-UUID ids) is the documented SEC-3 choice; POST-returns-pending is a frozen, documented surface (`routes/README.md`).
* **Error envelope for HTML vs API**: `_wants_html` keeps `{"detail": ...}` JSON for `/api/*` under the themed-page handlers, headers preserved. Diff endpoint's structured 422 detail (`{message, reasons, hint}`) is a deliberate richer shape, declared in its `responses=` description.
* **`/health`**, definitions reload (refreshes both `state.definitions` and `state.definition_loader`), target-profiles 404, adapters list/capabilities 404 — all consistent with their declared contracts.
