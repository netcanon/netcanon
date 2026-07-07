# 16 — Concurrency, State & Error-Handling (merged lens)

Reviewer: Fable fresh-eyes pass, 2026-07-03. Scope per blackboard: Part A =
`netcanon/storage/`, `netcanon/services/` (backup runner, scheduler,
BackgroundTasks), DefinitionLoader, shared mutable state; Part B = swallowed
exceptions, error-path leaks, resource release, assert-as-validation,
None-on-error, silent codec loss.

All claims cited `file:line` against the worktree at repo root
`<repo-root>`
(paths below relative to it). Two claims were verified with `py -c` probes
(marked **[probe-confirmed]**).

## Verdict

**Error-handling discipline is strong** — no bare `except:` anywhere in
`netcanon/`, no runtime `assert` (the single grep hit is a docstring,
`netcanon/migration/codecs/_mock/codec.py:18`), operator-error translation is
careful and deliberately path/trace-suppressing, collectors fail closed on
truncation, corrupt state files log-and-skip with a greppable marker.

**Concurrency is the weak axis.** Two findings I rate **major**, both in code
that changed after the prior review passes: the R8 `BackupJobRegistry` LRU
introduced an unlocked `OrderedDict` that mutates on *every read* (a
regression relative to the pre-R8 plain dict), and the schedules registry
never received the lock treatment that device profiles got for the exact same
delete-then-save resurrection class (review finding #10).

---

## Part A — Concurrency & state

### F1 (MAJOR) — BackupJobRegistry: unlocked OrderedDict mutated on every read → intermittent 500s under routine polling

`netcanon/storage/job_registry.py` has **no lock anywhere** in the class
(`self._cache: OrderedDict`, line 94). FastAPI runs the sync `def` route
handlers in the AnyIO threadpool, and the APScheduler path inserts from the
event-loop thread, so these genuinely interleave:

* **Mutating "reads"**: `__getitem__` calls `self._cache.move_to_end(job_id)`
  on every memory hit (`job_registry.py:167`) and promotes disk lazy-loads via
  `self[job_id] = job` (`:174`) — i.e. **a plain `GET /api/v1/backups/{id}`
  poll mutates the shared OrderedDict**.
* **Writers**: `__setitem__` insert + LRU `popitem` (`job_registry.py:147-150`);
  route insert `jobs[job.id] = job` (`netcanon/api/routes/backups.py:219`);
  scheduler insert `app.state.jobs[job.id] = job` on the event loop
  (`netcanon/api/routes/schedules.py:234`).
* **Iterating readers**: `sorted(jobs.values(), ...)` in the list endpoint
  (`netcanon/api/routes/backups.py:253`); `heapq.nlargest(10,
  request.app.state.jobs.values(), ...)` on the dashboard
  (`netcanon/api/routes/ui.py:178-182`); `sorted(...jobs.values()...)` on the
  jobs page (`ui.py:205-209`).

**[probe-confirmed]** Both `move_to_end` and insertion during a `values()`
iteration raise `RuntimeError: OrderedDict mutated during iteration`
(verified on this machine's Python via `py -c`).

Breaking interleaving (entirely ordinary usage): the Jobs page or dashboard
renders (iterates `values()`) while any concurrent job-detail poll hits
`__getitem__` (→ `move_to_end`), or while a scheduled run inserts its job →
`RuntimeError` → 500 on the dashboard/jobs list. The UI's poll-while-listing
pattern makes this a when-not-if under real concurrent use.

**Regression note:** pre-R8 the registry was a plain `dict` — reads did not
mutate, so the race window was only insert-during-iteration. The R8 LRU
refactor widened it to *any-read*-during-iteration. TestClient runs
background tasks synchronously and single-threaded, which is why the test
suite can't see this.

Fix shape: one `threading.Lock` guarding every method of
`BackupJobRegistry`; have `values()` return a snapshot `list(...)` taken
under the lock. All operations are microseconds; no hot-path cost.

### F2 (MAJOR) — Deleted-schedule resurrection: post-run save has no lock / no existence re-check (the profile fix #10 was never applied to schedules)

`_run_scheduled_backup_inner` re-saves the schedule *after* the backup run
completes — `app.state.schedule_store.save(schedule)` at
`netcanon/api/routes/schedules.py:269`, reached after an
`await asyncio.to_thread(run_backup_job, ...)` that can take minutes
(`schedules.py:245-259`). `delete_schedule` (`schedules.py:334-349`) does
`del schedules[id]` + `schedule_store.delete(id)` + `remove_job(id)` with no
lock.

Breaking interleaving: schedule fires → operator deletes it mid-run → run
finishes → line 269 re-writes `schedules/{id}.json` to disk. The in-memory
registry no longer has it (invisible in the UI), but **on the next restart
`load_all()` reloads it and the lifespan re-registers it enabled**
(`netcanon/main.py:159, 193-207`) — a schedule the operator deleted comes
back from the dead and resumes backing up, with its (legacy inline)
credentials re-persisted. This is the exact delete-then-save resurrection
class fixed for device profiles via `DEVICE_PROFILE_REGISTRY_LOCK`
(`netcanon/storage/device_profile_store.py:31-45`, review finding #10) and
correctly applied in `netcanon/services/backup_runner.py:315-319` — but
schedules got no equivalent.

Related unlocked read-modify-writes on the same registry (fold into one fix):

* `toggle_schedule` non-atomic flip `schedule.enabled = not schedule.enabled`
  (`schedules.py:369-370`) racing the scheduler's own mutations of
  `last_run_at`/`next_run_at` + save (`schedules.py:261-269`).
* Two concurrent saves of the *same* schedule (e.g. toggle at the moment a
  run finishes) share one temp path `{id}.tmp`
  (`netcanon/storage/schedule_store.py:57-60`): A writes tmp, B rewrites tmp,
  A replaces (moves B's bytes), B's `replace` then raises
  `FileNotFoundError` → sporadic 500 from the toggle route.
* `create_schedule` `len(schedules) >= 200` check-then-insert
  (`schedules.py:303-309`) can transiently exceed the cap (cosmetic).

Fix shape: a `SCHEDULE_REGISTRY_LOCK` mirroring the profile lock, held around
every registry-mutate-persist; and re-check `schedule_id in
app.state.schedules` before the post-run save at `schedules.py:261-269`.

### F3 (minor) — FileConfigStore.save: check-then-write collision race silently violates the documented "no file is ever silently overwritten" invariant

`netcanon/storage/file_store.py:171-184`: the collision loop
(`while path.exists(): counter += 1`) and the subsequent
`tmp = path.with_suffix(".tmp"); tmp.write_text(...); tmp.replace(path)` are
not atomic as a unit. Two saves for the same `(device_type, host)` in the
same second — a manual job and a scheduled job covering the same device is
the realistic interleaving; the global limiter does not serialise same-host
work across jobs — both pass the loop with `counter=0`, both write **the same
tmp path**, and the loser's capture is silently lost (its `ConfigRecord` then
reports the winner's size at `:185`), or its `replace` raises
`FileNotFoundError` post-hoc. Low probability (same-second window) but it
contradicts the module's own contract at `file_store.py:39-41`. A per-store
`threading.Lock` around lines 171-195, or `os.open(..., O_CREAT|O_EXCL)`
reservation, closes it.

### F4 (minor) — Orphaned `.tmp` files are listed as real configs **[probe-confirmed]**

`tmp = path.with_suffix(".tmp")` (`file_store.py:182`) turns
`Cisco_192-168-1-1_20260414_120000.cfg` into
`Cisco_192-168-1-1_20260414_120000.tmp`, which **matches `_FILENAME_RE`**
(`file_store.py:87-90`; ext group `[^.]+` accepts `tmp` — probe-confirmed).
A crash between `write_text` (`:183`) and `replace` (`:184`) leaves a tmp
that `list_configs` (`:220-234`) enumerates as a genuine config with
extension "tmp" (and `_migrate_flat_files` at `:313-329` would relocate it).
The `.meta.json` sidecar and its `.meta.tmp` do *not* match (probe-confirmed)
— only the primary tmp collides. Fix: dot-prefix the temp name
(`.{stem}.tmp`) or explicitly skip `*.tmp` in `_parse_filename`.

### F5 (minor) — TOFU known_hosts lost-update in the Paramiko-shell path

The Netmiko pre-flight does load+check+add+save under **one** lock hold
(`netcanon/collectors/hostkey.py:176-206` — correct). The Paramiko-shell
path splits the read-modify-write across two separate lock acquisitions with
the entire SSH connect in between: load in `apply_paramiko_policy`
(`hostkey.py:74-80`), save in `persist_paramiko_host_keys` (`:99-101`), and
`save_host_keys` writes the client's full in-memory set. Two concurrent
collects (job pool is up to 10 workers) that each learn a *different* new
host: last writer wins and silently drops the other's freshly-pinned key.
Self-healing (re-pinned on next connect) but it re-opens a first-use MITM
window for that host and quietly weakens the "pin on first use, reject a
later change" guarantee. Fix: re-load + merge + save inside one lock hold in
`persist_paramiko_host_keys` (mirror `verify_host_key`'s structure).

### F6 (minor) — Running jobs invisible on disk until terminal → 404-while-running and no interrupted-job tombstone

Jobs are persisted only once, at the end of `run_backup_job`
(`netcanon/services/backup_runner.py:554-558`). Consequences:

1. If churn inserts > `max_memory_jobs` newer jobs while one is still
   running, the running job is LRU-evicted (`job_registry.py:148-150`); a
   `GET /api/v1/backups/{id}` then misses memory, `load_one` finds no file,
   `KeyError` → **404 for a job that is actively running**
   (`job_registry.py:169-172`, `backups.py:273-275`). Edge case at default
   cap=1000, plausible at operator-lowered caps.
2. Server restart mid-run: the job record vanishes entirely — the operator
   gets no "interrupted" evidence.

Fix: persist at creation and on status transitions (the save is already
atomic + idempotent per `job_store.py:37-48`).

### F7 (minor) — Scheduler iterates the profiles dict without the profile lock → whole scheduled run silently skipped

`_run_scheduled_backup_inner` iterates `device_profiles.items()` on the event
loop (`netcanon/api/routes/schedules.py:156`) with no
`DEVICE_PROFILE_REGISTRY_LOCK`, while route threads insert/delete under the
lock (`device_profiles.py:98-100, 175-193`). A concurrent create/delete
raises `RuntimeError: dictionary changed size during iteration`, which the
outer wrapper catches and logs (`schedules.py:91-97`) — **the entire
scheduled run is skipped until the next interval**, with only a server-log
error as evidence. Same class, smaller windows: the UI pages iterate
`schedules.values()` / `device_profiles.values()`
(`ui.py:190-192, 205-209, 229-233, 366-370`) against concurrent
route-thread mutation → sporadic 500 on those pages. Taking the profile lock
(or `list(...)` snapshot under it) around `schedules.py:151-163` fixes the
scheduler half.

### F8 (info) — Unbounded jobs/*.json growth; warm-start parses every file

No retention/pruning exists for `jobs/*.json` (one file per job forever;
`FileJobStore` has save/load/delete-nothing), and the registry warm-start
parses every file (`job_registry.py:98-118` — the docstring itself flags the
100k-job startup cost as a follow-up). Caps exist for schedules (200,
`schedules.py:303`), profiles (1000, `device_profiles.py:90`), and devices
per request (500, `netcanon/models/device.py:84`) — job files are the
remaining unbounded surface. Worth a retention setting eventually; not a
defect today.

### F9 (minor) — `_get_fernet` lazy global init is unlocked → first-boot key-generation race can mint two keys

`netcanon/security/credentials.py:245-255` (`global _fernet`, no lock): two
threads performing the first-ever encrypt on a keyless install can both run
`_resolve_key()`, each generate a *different* key
(`credentials.py:208-215, 233-241`), both persist (keyring/file — last write
wins), and each thread encrypts with its own instance. Whatever was encrypted
under the losing key is **permanently undecryptable** (fails closed as
`CredentialDecryptError` on next load, `credentials.py:313-320` — good
failure mode, but the credential is lost). Profile saves are serialised by
the profile lock, but schedule saves (`schedule_store.py:49-54`) are not, so
a first-boot concurrent profile-create + legacy-schedule-save can race.
Narrow window (fresh install, no env var, first concurrent writes) — a
module-level `threading.Lock` around the init closes it.

### DefinitionLoader — checked, no finding

Per the lens brief (recall the rglob-ate-target_profiles bug): `load_all`
excludes reserved subdirs by *any* relative path component
(`netcanon/definitions/loader.py:78, 137-141, 301-316`), so nested
`target_profiles/**` is skipped; no other foreign-schema sibling currently
lives under `definitions_dir` (`main.py:107-121` wires `target_profiles` via
its own loader). `load_all` runs once in the lifespan (single-threaded);
`resolve()` is read-only over `self._variants` afterwards. No over-broad scan
and no runtime mutation. `FileConfigStore`'s `rglob("*")` is regex-filtered —
its only residue is F4.

---

## Part B — Error handling

### Checked, clean (explicit non-findings)

* **No bare `except:`** in `netcanon/` (grep). No `assert` used for runtime
  validation (only a doctest-style docstring line in `_mock/codec.py:18`;
  `-O` stripping is a non-issue).
* **No stack-trace/path leaks to clients**: the global handlers return
  generic bodies and log server-side (`netcanon/api/routes/ui.py:155-167`);
  backup errors funnel through `translate_backup_error`, which deliberately
  suppresses filesystem paths and netmiko multi-line dumps
  (`netcanon/api/_errors.py:221-230, 248-263`) while `exc_info=True` keeps
  the trail in the server log (`backup_runner.py:369-377`); the open-in-editor
  route explicitly withholds raw OS error text (`configs.py:202-213`).
* **Fail-closed collection**: paramiko collector raises `TimeoutError` rather
  than persisting a truncated buffer (`paramiko_collector.py:443-459`);
  Netmiko path uses a context manager for the session
  (`netmiko_collector.py:111-134`).
* **Corrupt-state handling**: all three stores log-and-skip with a uniform
  "CORRUPT FILE SKIPPED" marker (`job_store.py:67-70, 100-104`,
  `device_profile_store.py:120-123`, `schedule_store.py:110-113`); the
  Fernet migration fails closed on token-shaped-but-undecryptable values
  (`credentials.py:292-323`).
* **Codec `except ValueError: pass` sweep** (hundreds of sites): sampled
  arista/junos/aoss/fortigate/sanitize sites — all are narrow int/IP
  conversion guards on already-regex-matched tokens, with the aoss
  non-contiguous-mask fallback commented with its chosen degradation
  (`aruba_aoss/parse.py:982-989`). The support-matrix/walker honesty system
  is the declared mitigation for the residual class; no new silent-loss
  pattern found. `_input_not_recognized` correctly upgrades
  empty-parse-of-nontrivial-input to `partial`
  (`migration_pipeline.py:127-183, 340-354`) — the whole-input silent-success
  hole stays closed.
* **None-on-error**: `DefinitionLoader.resolve` returning `None` is guarded
  at its one production call site (`backup_runner.py:284-289` — `resolved or
  family_base`); the unknown-type_key `definitions.get` guard
  (`backup_runner.py:240-252`) correctly avoids the stranded-at-running bug
  it documents.

### F10 (minor) — Paramiko probe/collect can leak a live SSH session on the persist path

`ParamikoShellCollector.probe`: `client.connect(...)` +
`persist_paramiko_host_keys(...)` sit in a try whose handler returns `{}`
**without closing the client** (`netcanon/collectors/paramiko_collector.py:276-294`)
— the `finally: client.close()` at `:326-327` belongs to the *second* try
block. If connect succeeds and persist then raises (it only swallows
`OSError`, `hostkey.py:102-103`), the live session leaks until GC. Same shape
in `collect()`: connect + persist (`paramiko_collector.py:181-191`) precede
the `try/finally` at `:193-234` entirely. Low probability (persist rarely
raises non-OSError) but the fix is free: move `connect`/`persist` inside the
try that owns the `finally: client.close()`.

### F11 (minor) — Diff surfaces: delete-between-list-and-read returns 500 instead of 404

Both diff paths resolve records from a `list_configs()` snapshot and read the
bytes later: API `diff_configs` (`netcanon/api/routes/configs.py:301` index,
`:319-320` `get_content`) and the HTML `diff_page`
(`ui.py:293-295` index, `:335-336` reads). A `DELETE /api/v1/configs/{name}`
landing in between raises `FileNotFoundError` from `get_content`
(`file_store.py:239-245`) which neither handler catches → generic 500,
where the same condition a moment earlier yields an honest 404 / themed
error view. Interleaving: operator deletes a config in one tab while diffing
in another. Wrap the two `get_content` calls in the same
`FileNotFoundError → 404` treatment `get_config` already has
(`configs.py:83-91`).

### F12 (info) — Live BackupJob torn reads are benign as written; keep the write ordering

`GET /api/v1/backups/{id}` serialises the same mutable object worker threads
are mutating. Verified the success path writes `config_record` →
`duration_seconds` → `status="success"` in that order
(`backup_runner.py:344-346`), and `BackupResult` docs promise terminal rows
are never mutated again (`netcanon/models/backup.py:64-69`), so a reader that
sees a terminal status sees a complete row regardless of pydantic's field
order. This is only true *because* status flips last — worth a comment-level
guard, nothing more. (List growth during serialisation of `job.results` is
also tolerated by CPython list iteration.)

---

## Summary table

| # | Sev | One-liner |
|---|-----|-----------|
| F1 | major | Unlocked `BackupJobRegistry` OrderedDict mutates on every read; iterating endpoints race it → RuntimeError 500s (R8 regression, probe-confirmed) |
| F2 | major | Deleted schedule resurrected on disk by post-run save; schedules registry never got the #10 lock treatment |
| F3 | minor | FileConfigStore same-second save collision → silent capture loss, violates documented invariant |
| F4 | minor | Orphaned `.tmp` matches filename grammar → listed as a config (probe-confirmed) |
| F5 | minor | Paramiko-path TOFU load/save split across lock holds → lost host-key pins under parallel collects |
| F6 | minor | Jobs unpersisted until terminal → 404 for evicted running job; no interrupted-job record after restart |
| F7 | minor | Scheduler iterates profiles dict lockless → whole scheduled run silently skipped on dict-changed race |
| F8 | info | No retention for `jobs/*.json`; warm-start parses all (acknowledged in-code) |
| F9 | minor | `_get_fernet` lazy init unlocked → first-boot double-keygen can orphan ciphertext |
| F10 | minor | Paramiko probe/collect: connect+persist outside the finally-close → SSH session leak on persist failure |
| F11 | minor | Diff TOCTOU: delete between list and read → 500 instead of 404 |
| F12 | info | Live-job torn reads benign only because status is written last — document it |
