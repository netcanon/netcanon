# Lens 02 — Concurrency & shared-state (netcanon @ 8598d74 / v0.5.3)

Seven findings survived verification: one MAJOR (TOFU known_hosts lost update on the paramiko
collector path, reproduced), two MEDIUM job-registry lifecycle races (both reproduced or
code-confirmed, both siblings of the already-fixed CONC-5), one MEDIUM shared-executor
starvation hazard, and three MINORs. The prior CONC-3/5/6/7/8/9 remediations were re-verified
and hold; the new findings are all "hardened-path / un-hardened-sibling" instances of those
same patterns. Reproduction scripts live in the session scratchpad
(`repro_tofu_lost_key.py`, `repro_registry_stale.py`, `repro_listcomp_race.py`).

---

### CONC-10 — TOFU known_hosts: concurrent paramiko saves are last-writer-wins, silently dropping freshly pinned host keys

- **Severity:** MAJOR  **Confidence:** confirmed (reproduced with real paramiko clients + the real hostkey module)
- **File:** `netcanon/collectors/hostkey.py:101` (`persist_paramiko_host_keys`), with the paired load at `hostkey.py:74-80` (`apply_paramiko_policy`)

`_KNOWN_HOSTS_LOCK` serialises each individual `load_host_keys` / `save_host_keys` call, but the
paramiko collector's read-modify-write spans **two separate lock acquisitions** with the whole SSH
connect in between (`paramiko_collector.py:182` load → `client.connect` auto-add → `paramiko_collector.py:207`
persist). `client.save_host_keys()` writes the client's private snapshot (keys loaded at connect
time ∪ its own newly learned key), so it overwrites — not merges — the store.

**Failure scenario:** first backup of a fleet containing ≥2 devices not yet in the store, with
`workers > 1` and at least one `paramiko_shell` device (OPNsense), `ssh_host_key_checking=tofu`
(the default). Worker A and worker B both load the store before either saves; A pins devA and
saves `{devA}`; B then saves its own snapshot `{devB}` → **devA's pinned key is gone**. Reproduced:
final store contained only `10.0.0.2` after two TOFU connects. The same stale-snapshot save also
clobbers keys a concurrent Netmiko `verify_host_key` pre-flight just persisted for a *different*
device (the Netmiko path is atomic under one lock hold — `hostkey.py:176-206` — and is not itself
lossy, but its writes can be erased by a later paramiko save whose load pre-dates them). Net
effect: the device is silently re-TOFU'd on the next run — an unverified trust decision in exactly
the window the v0.4.5 TOFU-default (breaking change) was shipped to close. No error is surfaced.

**Fix:** make `persist_paramiko_host_keys` read-merge-write under a single lock hold: inside
`_KNOWN_HOSTS_LOCK`, load the current file into a fresh `paramiko.HostKeys`, union in
`client.get_host_keys()` entries, and `merged.save(str(kh))` — never `client.save_host_keys()`.
(~8 lines; mirrors the already-correct single-lock-hold structure of `verify_host_key`.)

---

### CONC-11 — BackupJobRegistry can evict a *running* job; a poll then promotes the stale disk snapshot, which masks the live job forever (permanently "pending" completed job)

- **Severity:** MEDIUM  **Confidence:** confirmed (reproduced end-to-end against the real registry + store)
- **File:** `netcanon/storage/job_registry.py:162` (unconditional LRU `popitem`), promote path `job_registry.py:185-190`; runner never re-inserts (`netcanon/services/backup_runner.py:554-558`)

`run_backup_job` mutates the in-memory `BackupJob` object in place and persists only at terminal;
the CONC-5 fix (`backups.py:233`) persists a *pending* snapshot at creation so an evicted running
job doesn't 404. But eviction of a running job now splits identity: `__setitem__` evicts the LRU
entry **regardless of status**; the next `GET /api/v1/backups/{id}` misses memory, lazy-loads the
stale *pending* snapshot from disk, and **promotes it into the cache**. From then on every read is
a memory hit on the stale object. The worker's terminal `job_store.save(job)` updates disk only —
nothing re-inserts the live/terminal state into the registry.

**Failure scenario (reproduced):** job created (pending snapshot saved) → worker sets it running →
`max_memory_jobs` newer insertions evict it → UI progress panel polls (it polls every couple of
seconds, so this step is near-certain once evicted) → stale pending copy promoted → job completes,
disk says `completed` → **registry keeps answering `pending` indefinitely**; the jobs list shows the
stale row too. Operator sees a backup wedged at pending forever; only server restart or cache churn
clears it. Trigger needs cache-cap insertions during one job's runtime — unlikely at the default
cap of 1000, realistic when `NETCANON_MAX_MEMORY_JOBS` is tuned low (the setting is advertised for
memory-constrained deployments, `ge=0`).

**Fix:** in `__setitem__`, never evict non-terminal jobs — scan from the LRU end for the first job
with status in `{completed, partial, failed}` and evict that (allow temporarily exceeding the cap
if all resident jobs are in flight; in-flight count is inherently small). This keeps the live
object resident, so the stale-promote path can't engage. Optionally also have `run_backup_job`
re-insert the job into the registry after the terminal save (requires threading the registry in)
as a belt-and-braces convergence guarantee.

---

### CONC-12 — Scheduled jobs are never persisted at creation: the CONC-5 fix was applied to the manual path only (evicted/uncached scheduled jobs 404 while running)

- **Severity:** MEDIUM  **Confidence:** confirmed (direct code contradiction with the CONC-5 comment on the sibling path)
- **File:** `netcanon/api/routes/schedules.py:249` (`app.state.jobs[job.id] = job` with no `job_store.save(job)`); contrast `netcanon/api/routes/backups.py:226-241`

`create_backup` saves the pending job to disk immediately, precisely so "a job evicted while still
running would [not] disk-miss and poll as a 404 for an active job (CONC-5)". The schedule trigger
`_run_scheduled_backup_inner` inserts the job into the registry and dispatches `run_backup_job`
without any pending save — the first disk write for a scheduled job is the runner's terminal save.

**Failure scenario:** (a) a schedule-triggered job is LRU-evicted mid-run (same trigger economics
as CONC-11) → `GET /api/v1/backups/{id}` → memory miss → disk miss → 404 for a genuinely running
job, and it vanishes from the jobs list; (b) with the documented `max_memory_jobs=0` configuration
("disable caching entirely"), **every** scheduled run is invisible for its whole duration — jobs
page empty, get-by-id 404 — then pops into existence already terminal; (c) a crash mid-run leaves
no trace the scheduled run ever started (manual jobs at least leave the pending record).

**Fix:** mirror backups.py: after `app.state.jobs[job.id] = job`, call
`app.state.job_store.save(job)` in a try/except OSError (warn, non-fatal), before dispatching
`run_backup_job`.

---

### CONC-13 — Long-running backup jobs execute on shared default thread pools: enough concurrent jobs starve every sync route (manual path) or the /sanitize endpoint + other to_thread users (scheduled path)

- **Severity:** MEDIUM  **Confidence:** plausible (mechanism verified from Starlette/asyncio semantics; not load-tested)
- **File:** `netcanon/api/routes/backups.py:245` (`background_tasks.add_task(run_backup_job, ...)`) and `netcanon/api/routes/schedules.py:260` (`await asyncio.to_thread(run_backup_job, ...)`)

Two different shared pools, same hazard:

* **Manual path:** Starlette runs a sync background task via `run_in_threadpool` → anyio's default
  limiter of **40 tokens — the same budget every sync `def` route handler draws from** (every
  netcanon route except `/health` and `/sanitize` is sync). Each in-flight backup job holds one
  token for its entire duration — minutes, and *longer under load* because the r7 global SSH
  limiter (default 10) intentionally queues devices across jobs. An operator/script creating ~40
  single-device jobs across a fleet (the devices page's per-profile "backup now" shape) freezes the
  whole API — every UI page, every poll, even new POSTs — until jobs drain, while the async
  `/health` keeps answering OK so orchestrators see a healthy server.
* **Scheduled path:** `asyncio.to_thread` uses the loop's default executor
  (`min(32, cpu_count + 4)` threads — **8 on a 4-core box**). All enabled schedules are
  re-registered in one startup loop (`main.py:241-253`), so their `IntervalTrigger`s share an
  anchor and fire in synchronized bursts. More than ~8 simultaneous scheduled runs queue behind
  each other — and `/sanitize`'s `asyncio.to_thread(sanitize_text, ...)` (`sanitize.py:79`) plus
  the egress filter (`schedules.py:228`) queue behind minutes-long backups on that same executor.

**Fix:** run `run_backup_job` on a dedicated module-level `ThreadPoolExecutor` in
`backup_runner.py` (sized to a deliberate max-concurrent-jobs cap, e.g. 8–16), used by both entry
points: the route submits to it instead of `BackgroundTasks`, and the scheduler awaits
`loop.run_in_executor(BACKUP_EXECUTOR, ...)`. This also puts a real, intentional ceiling on
concurrent jobs (today only *devices* are capped, not jobs).

---

### CONC-14 — `delete_device_profile` iterates the live schedules dict under the *device-profile* lock; a concurrent schedule create/delete raises RuntimeError → 500 and the profile is not deleted

- **Severity:** MINOR  **Confidence:** confirmed (pattern reproduced: RuntimeError after 0.03 s of contention)
- **File:** `netcanon/api/routes/device_profiles.py:181-185`

The referencing-schedules warning listcomp
(`[s.name for s in request.app.state.schedules.values() if profile_id in s.target_device_ids]`)
runs while holding `DEVICE_PROFILE_REGISTRY_LOCK`, but schedule mutators hold
`SCHEDULE_REGISTRY_LOCK` — a different lock. Unlike the `sorted(d.values(), key=...)` list
endpoints (whose list-copy phase is a single C call and therefore GIL-atomic — checked, **not**
flagged), a listcomp executes Python bytecode per item, so the GIL can hand over to a schedule
create/delete mid-iteration: `RuntimeError: dictionary changed size during iteration`. The
iteration sits *before* `del device_profiles[profile_id]`, so the DELETE 500s without deleting
(retry succeeds). Same failure class the CONC-6 fix (schedules.py:155-162) called out and fixed
for the scheduler's own iteration.

**Fix:** snapshot under the right lock — before acquiring the profile lock:
`with SCHEDULE_REGISTRY_LOCK: schedule_snapshot = list(request.app.state.schedules.values())`,
then run the listcomp over the snapshot. (Avoid nesting the schedule lock inside the profile lock
so no lock-order edge is introduced.)

---

### CONC-15 — Device-profile 1000-cap check is outside the registry lock (the schedules route fixed exactly this race; the profiles sibling didn't)

- **Severity:** MINOR  **Confidence:** confirmed (code read; contrast with the fixed sibling)
- **File:** `netcanon/api/routes/device_profiles.py:90` vs `netcanon/api/routes/schedules.py:333-341`

`create_device_profile` checks `len(device_profiles) >= 1000` *before* entering
`DEVICE_PROFILE_REGISTRY_LOCK`; two concurrent creates at 999 both pass and both insert → cap
exceeded. `create_schedule` explicitly moved its 200-cap check inside `SCHEDULE_REGISTRY_LOCK`
("so the 200-limit can't be raced past") — the profiles route kept the pre-fix shape. Overshoot is
bounded by request concurrency (a few entries), so the DoS-guard erosion is small.

**Fix:** move the cap check inside the `with DEVICE_PROFILE_REGISTRY_LOCK:` block.

---

### CONC-16 — No startup reconciliation of non-terminal persisted jobs: after a crash/restart, interrupted jobs show "pending" forever

- **Severity:** MINOR  **Confidence:** confirmed (code read: `_warm_from_disk` / `load_one` / lifespan have no reconciliation path)
- **File:** `netcanon/main.py:199-203` (registry built + warmed) / `netcanon/storage/job_registry.py:109-136`

Jobs are persisted as `pending` at creation (CONC-5) and only re-persisted at terminal. If the
process dies mid-run, the disk snapshot stays `pending`; on restart the warm cache (and any later
lazy-load) serves it verbatim. The UI/API then shows a forever-pending job indistinguishable from
a live one — and with CONC-12 fixed, scheduled jobs will join this class too.

**Fix:** in lifespan after the registry is built (or inside `_warm_from_disk`/`load_one`), flip any
loaded job with status `pending`/`running` to `failed` with error "interrupted by server restart"
and re-persist. Cheap for the warmed subset; a `load_one` guard covers evicted stragglers.

---

## Verified-clean (checked, not findings)

* CONC-3/5/6/7/8/9 remediations all re-verified in place (file-store save lock, pending-snapshot
  save on the manual path, scheduler profile-registry snapshot, Fernet double-checked lock,
  paramiko client close on connect failure, diff TOCTOU 404s).
* `sorted(live_dict.values(), key=...)` list endpoints (`device_profiles.py:44`,
  `schedules.py:313`, `ui.py:190/230/242/375`): `sorted()` copies the iterable in one GIL-atomic C
  call before invoking the Python key, so these do **not** race under CPython-with-GIL (empirically
  confirmed: 200k contended iterations, zero errors; the listcomp variant errored in 0.03 s).
  Would need revisiting only for a free-threaded build.
* Codec registry: populated at import time, read-only at runtime; `get_codec` instantiates per
  call; migration pipeline is stateless ("no I/O, no global state" holds).
* `_drain` caps (SEC-5): hard wall-clock + byte caps verified; `_collect_output` fails closed;
  probe variant bounded by deadline arithmetic (~9.6 MB worst case).
* Global collection limiter: acquire-before-running + `with`-scoped release; no leak path found.
* `reload_definitions` swaps `app.state.definitions` by reference (never mutates in place) —
  in-flight readers keep a consistent snapshot.
* Egress guard, sanitize route, collectors' `get_collector` factory: stateless / per-call
  instances; the per-instance `collector.settings` injection does not share instances across
  threads.
* Job store `.tmp` naming: per-job-ID paths; per-job save sequence is single-threaded
  (create-thread → runner-thread), no shared-tmp collision.
