# 42 — Platform verification (adversarial pass over 16, 18, 20)

Verifier: Fable adversarial pass, 2026-07-03. Method: every claim re-traced against
the worktree source (file:line re-read, not trusted from the peer report); four
independent `py -c` probes re-run on this machine (marked **[re-probed]**); packaging
claims verified by reading the actual globs/manifests/workflow YAML (no wheel built,
per brief — the git-less-wheel conclusion is derived from the packaging config and
is unambiguous). Posture: default REFUTED unless reachable under the app's real
concurrency model (uvicorn single event loop + AnyIO threadpool for sync `def`
routes + BackgroundTasks in that threadpool + APScheduler coroutines on the loop)
at realistic scale.

**Headline: zero refutations.** All three peer reports survived adversarial
re-verification intact — every load-bearing citation was accurate, every probe
reproduced. The five MAJORs stand: 16-F1, 16-F2, 18-F1, 18-F2, 20-PERF-1.
I recorded a handful of immaterial line-number drifts and two severity nuances
(noted inline) but no verdict changes.

---

## Report 16 — Concurrency & error handling

### F1 — CONFIRMED, MAJOR
Unlocked `BackupJobRegistry` OrderedDict mutated on every read.
- Evidence: read the entire `netcanon/storage/job_registry.py` — **no lock exists
  anywhere in the class**. `__getitem__` calls `self._cache.move_to_end(job_id)` on
  every memory hit (job_registry.py:167) and promotes disk loads via `self[job_id] =
  job` (:174); `values()` returns the **live** `self._cache.values()` view (:202-204);
  `__setitem__` insert + LRU `popitem` (:147-150).
- Concurrency model verified: `app.state.jobs` IS this registry (main.py:151-155).
  Iterating readers are sync `def` routes running in the AnyIO threadpool —
  `sorted(jobs.values(), ...)` (backups.py:249-253), dashboard `heapq.nlargest(10,
  ...jobs.values()...)` (ui.py:176-182), jobs page sorted (ui.py:202-209). Concurrent
  mutators: any `GET /api/v1/backups/{id}` poll (backups.py:261-275 → `__getitem__` →
  `move_to_end`), route insert (backups.py:219), and the scheduler coroutine's insert
  **on the event-loop thread** (schedules.py:234) — genuinely different threads.
- **[re-probed]**: both `move_to_end` and insert during a `values()` iteration raise
  `RuntimeError: OrderedDict mutated during iteration` on this machine's Python.
- Regression claim verified: the module docstring itself says pre-R8 the cache was a
  plain dict (job_registry.py:9-14) — the LRU widened the race to any-read.
- The UI poll-while-listing pattern makes the interleaving routine, and the failure
  is a user-visible 500 on the dashboard/jobs page. MAJOR stands.

### F2 — CONFIRMED, MAJOR
Deleted-schedule resurrection; schedules never got the #10 lock.
- Post-run save traced: `_run_scheduled_backup_inner` captures the schedule object at
  schedules.py:143, suspends for minutes at `await asyncio.to_thread(run_backup_job,
  ...)` (:245-259), then unconditionally `app.state.schedule_store.save(schedule)`
  (:269) — **no re-check that the schedule still exists**. `delete_schedule` does
  `del schedules[id]` + `schedule_store.delete(id)` + `remove_job(id)` with no lock
  (:334-349). Delete-mid-run → :269 rewrites `schedules/{id}.json`.
- Resurrection completes on restart: lifespan `load_all()` (main.py:159) +
  re-register-if-enabled loop (main.py:193-207). An operator-deleted schedule
  resumes firing, with legacy inline credentials re-persisted
  (schedule_store.py:49-54 re-encrypts `devices[].password`).
- Asymmetry verified: `DEVICE_PROFILE_REGISTRY_LOCK` exists with a docstring
  describing this exact class (device_profile_store.py:31-45), is held by the profile
  routes (device_profiles.py:98, :135, :175) and by the runner's post-probe save
  (backup_runner.py:315-319). **No schedule equivalent exists anywhere** (grep).
- Sub-claims all verified: toggle's unlocked flip (:369-370) racing the scheduler's
  `last_run_at`/`next_run_at` save (:261-269); the shared `{id}.tmp` path
  (schedule_store.py:55-60 — `path.with_suffix(".tmp")`, so two concurrent saves of
  the same schedule collide, loser's `replace` raises FileNotFoundError); the 200-cap
  check-then-insert (schedules.py:303-309). MAJOR stands.

### F3 — CONFIRMED, minor
FileConfigStore same-second save collision.
- `while path.exists()` loop (file_store.py:172-179) and `tmp =
  path.with_suffix(".tmp"); write; replace` (:182-184) verified non-atomic as a unit;
  same stem → same tmp path. The documented invariant "no file is ever silently
  overwritten" is at file_store.py:39-41 verbatim.
- Realism check: `run_backup_job`'s own thread-safety docstring concedes the gap —
  "**distinct** `(device_type, host)` pairs produce distinct paths so there is no
  contention **in the common case**" (backup_runner.py:441-443). Nothing serialises
  same-host work across a manual job + a scheduled job. Narrow (same-second) window
  → minor is correct.

### F4 — CONFIRMED, minor **[re-probed]**
- `Cisco_192-168-1-1_20260414_120000.tmp` matches `_FILENAME_RE` with `ext="tmp"`
  (the `[^.]+` ext group, file_store.py:87-90); `.cfg.meta.json` and `.cfg.meta.tmp`
  do NOT match (internal dots) — exactly as the peer reported. A crash between
  `write_text` (:183) and `replace` (:184) leaves a tmp that `list_configs`
  (:220-234, rglob + regex filter) enumerates as a real config.

### F5 — CONFIRMED, minor
- Paramiko path: load under lock-hold #1 in `apply_paramiko_policy`
  (hostkey.py:74-80), save under a **separate** lock-hold in
  `persist_paramiko_host_keys` (:99-101), the whole SSH connect in between;
  `save_host_keys` writes the client's full in-memory set → concurrent collects each
  learning a different new host lose the other's pin (last-writer-wins). Contrast
  verified: the Netmiko pre-flight `verify_host_key` does load+check+add+save under
  ONE lock hold (:176-206). Self-healing but re-opens the first-use window — minor.

### F6 — CONFIRMED, minor
- Jobs persisted exactly once, at the end of `run_backup_job`
  (backup_runner.py:554-558). LRU-evicted running job → `__contains__` falls to a
  disk `exists()` check (job_registry.py:184-188) → False → 404 from
  backups.py:273-275 for an actively-running job. Restart mid-run → no record at
  all. Edge case at default cap 1000 (needs 1000 newer inserts mid-run); real at
  operator-lowered `NETCANon_MAX_MEMORY_JOBS`. Minor is right.

### F7 — CONFIRMED, minor
- `_run_scheduled_backup_inner` iterates `device_profiles.items()` on the event loop
  (schedules.py:157) with no `DEVICE_PROFILE_REGISTRY_LOCK`, while the profile routes
  insert/delete **under** the lock in threadpool threads (device_profiles.py:98,
  :135, :175) — the lock does not help a lockless reader; dict-changed-size
  RuntimeError propagates to the outer wrapper's catch (schedules.py:91-97) and the
  entire scheduled run is silently skipped. Same class on the UI pages (ui.py:190-192,
  :205-209, :229-243 iterate live dicts). Confirmed.

### F8 — CONFIRMED, info
- Grep of `netcanon/storage/job_store.py`: no `delete`/`prune`/`remove` method exists;
  warm-start parses every file (job_registry.py:98-118, docstring self-flags the
  100k cost). Unbounded-by-design today; info is right.

### F9 — CONFIRMED, minor
- `_get_fernet` (credentials.py:245-255): module global, no lock; `_resolve_key()`
  can generate a fresh key on both tiers (:208-215, :233-242). Two first-ever
  concurrent encrypts (fresh install, no env key) can mint two keys; loser's
  ciphertext fails closed later as `CredentialDecryptError` (:313-320). Profile saves
  are behind the profile lock but schedule saves are not — the race exists. Narrow
  window; minor.

### F10 — CONFIRMED, minor
- `probe()`: `client.connect` (:277-285) + `persist_paramiko_host_keys` (:286) sit in
  a try whose handler `return {}` **without closing the client**
  (paramiko_collector.py:276-294); the `finally: client.close()` (:326-327) belongs
  to the second try. `collect()`: connect (:181-189) + persist (:191) precede the
  try/finally (:193-233) entirely. `persist` swallows only OSError (hostkey.py:102) —
  any other exception leaks the live session until GC. Low-probability, free fix;
  minor.

### F11 — CONFIRMED, minor
- `diff_configs`: snapshot at configs.py:301, `get_content` at :319-320 with **no**
  FileNotFoundError catch (grep confirms the only catches in configs.py are at :87,
  :114, :174 — the get/download/delete routes); HTML `diff_page` reads at
  ui.py:335-336 likewise uncaught → delete-between-list-and-read yields a 500 where
  a moment earlier it's a 404. Confirmed.

### F12 — CONFIRMED, info
- Success-path write order verified: `config_record` → `duration_seconds` →
  `status="success"` (backup_runner.py:344-346); status flips last, so a reader
  seeing terminal status sees a complete row. Comment-level guard suggestion is
  appropriate.

### Part B non-findings — spot-checked, hold
- Grep: **zero** bare `except:` in `netcanon/` — confirmed. Corrupt-file skip
  markers, translate_backup_error path-suppression, and the resolve-or-family_base
  guard (backup_runner.py:240-252, :284-289) all verified at the cited lines.

---

## Report 18 — CI / supply-chain / packaging

### F1 — CONFIRMED, MAJOR (highest-stakes claim; independently re-derived from config)
Docker (and almost certainly MSI) ships zero `migration/vendors/*.yaml`.
- Source layout: exactly 12 vendor YAMLs + `__init__.py` live at
  `netcanon/migration/vendors/` (glob-verified).
- `pyproject.toml:163-177` `[tool.setuptools.package-data]` lists ONLY
  `templates/*.html`, `templates/_partials/*.js`, `definitions/library/**/*.yaml` —
  **no glob covers `migration/vendors/`**. No `setup.py`/`setup.cfg` exists to add
  more. `MANIFEST.in` contains only `prune tests` (no include directives).
- Docker path: `Dockerfile:39-40` COPYs only pyproject/README/LICENSE/lock +
  `netcanon/`; `.dockerignore:2` excludes `.git/` and `:15` excludes `*.egg-info/`;
  `Dockerfile:53` runs `pip wheel --no-deps .` — a direct PEP 517 `build_wheel` with
  **no sdist round-trip**. With no VCS in the context, the setuptools_scm file-finder
  contributes nothing, so wheel data = the explicit globs only → the 12 YAMLs are
  omitted. The PyPI channel is unaffected because `python -m build`
  (pypi-publish.yml:148) goes sdist-first and setuptools_scm's VCS finder populates
  the sdist. This reasoning is airtight from the config; it independently reaches the
  peer's build-probe result.
- Silent degradation verified: `load_vendors` warns only when the directory is
  **missing** (vendors/__init__.py:54-56) — in the installed wheel the dir exists
  (it holds `__init__.py`), so it logs "Loaded 0 vendor(s)" and returns `{}`.
  Runtime effect verified: `vendor_display_name = vendor.display_name if vendor else
  ""` (_migration_helpers.py:143) → empty for every codec; the definitions page's
  vendor section iterates `vendors_dict` (ui.py:449-452) → zero rows.
- CI blindness verified: the clean-room wheel job asserts DefinitionLoader + /health
  only and tests a `python -m build` wheel (ci.yml:255-296); docker smoke curls
  /health + / only (ci.yml:337-376).
- MSI: `setup_desktop.py:100-114` `include_files` hand-ships definitions + templates
  + license notices — vendors absent. Consistent with the peer's "almost certainly
  affected (unverified)"; the config-level evidence supports it.
- Severity note: today's functional blast radius is degraded metadata (translation
  itself works — codecs are Python-registered), but this is a silent shipped-artifact
  divergence, the **third occurrence** of the exact regression class the pyproject
  comment warns about (pyproject.toml:152-162), and every gate is blind. MAJOR
  stands; the three-line fix + a smoke assertion is the right shape.

### F2 — CONFIRMED, MAJOR (guard gap)
- `.gitignore` read end-to-end: **no entry** for `docs/codebase-review/` or
  `docs/reviews/2026-06-19-run3-verification/` (only `local/`, runtime dirs,
  build artefacts, etc.). The session-start git status independently shows both dirs
  as `??` (untracked, NOT ignored) — matching the peer's check-ignore result.
- `pii-guard.yml:27-29` states the dossier "is gitignored, so git grep never sees
  it" — **false in-tree**. The guard is content-pattern-only
  (`samuelr[i]pp09|C:[\]Users`, pii-guard.yml:50).
- Nuance (does not change the verdict): `docs/codebase-review/` quotes the email, so
  the content guard would likely catch THAT dir at PR time; the truly exposed surface
  is `run3-verification/` (unlicensed third-party config content that plausibly
  matches neither pattern) — and `MANIFEST.in` prunes only `tests/`, so a committed
  copy auto-ships in the next PyPI sdist (the T0-5 failure mode). One `git add docs/`
  deep — a realistic slip. The stated defense being factually false plus the
  missing path-based layer justifies MAJOR.

### F3 — CONFIRMED, minor
- Verbatim drift: `gen_requirements_lock.sh:25` `BASE="python:3.14.5-slim-bookworm@
  sha256:a9bee155..."` under the comment "Keep this digest in lock-step with the FROM
  lines in Dockerfile" vs `Dockerfile:12/:60` `python:3.14.6-slim-bookworm@
  sha256:4ff4b92a...`. Comment rot also verified: Dockerfile:9 says "3.14.5" above
  the 3.14.6 tag; :14-16 says "Python 3.13" in a 3.14 image.

### F4 — CONFIRMED, minor
- `desktop-msi-publish.yml:191-197`: `pip install -e ".[desktop-build]"` — no lock,
  no hashes, full dep-tree resolution at release time; :199-201 comment confirms
  cx_Freeze auto-downloads WiX; the workflow carries `contents: write` at workflow
  level (:41-43). Contrast with the Docker `--require-hashes` path is real.

### F5 — CONFIRMED, minor
- `desktop-msi-publish.yml:41-43` workflow-level `contents: write` reaches the
  pytest-only `test` job (:71-91); `docker-publish.yml:10-15` workflow-level
  `packages/id-token/security-events: write` reaches its `test` job (:49-68).
  `pypi-publish.yml` is the correct model (read-only at :10-12; `id-token: write`
  scoped to `publish-pypi` at :170-171).

### F6 — CONFIRMED, minor (footgun)
- `pypi-publish.yml:8` bare `workflow_dispatch`; dispatched on main, the ancestry
  check (:89-98) passes trivially and the CI-success poll (:107-131) queries the
  push-event run for main HEAD (typically green); `local_scheme = "no-local-version"`
  (pyproject.toml:141) makes the resulting `.devN` PyPI-legal. `docker-publish.yml:8`
  same trigger shape. Maintainer-only; footgun severity is right.

### F7 — CONFIRMED, note
- `ci.yml:8-10` `cancel-in-progress: true` keyed on ref, applying to main pushes;
  the publish gate treats a completed-but-cancelled run as refuse (fail-closed,
  pypi-publish.yml:123-125). Operational confusion risk only — note is right.

### F8 — CONFIRMED, nit
- The self-contradictory Trivy comment is verbatim at docker-publish.yml:236-242
  ("Pinned at v0.36.0 (latest stable)" vs "vulnerable ... exact `= 0.69.4` ... do NOT
  bump to 0.69.x"). SHA pin matches ci.yml:329.

### F9 — CONFIRMED, nit
- `.gitattributes` covers only `requirements.lock` + the lock-gen script (:6-7);
  `scripts/git-hooks/pre-push` is bash with `set -euo pipefail` (pre-push:25) and is
  not listed → CRLF materialization on autocrlf Windows clones breaks it fail-closed.

### F10 — CONFIRMED, observation (within adjudicated policy)
- `actions/upload-artifact@v7` (pypi-publish.yml:154) and
  `actions/download-artifact@v8` (:175) are floating majors; download executes inside
  the job holding `id-token: write` (:170-171). The pypa publish action itself IS
  SHA-pinned (:181). Cosign identity regexp anchored + dot-escaped verified
  (docker-publish.yml:316-318).

---

## Report 20 — Architecture / performance

### PERF-1 — CONFIRMED, MAJOR **[re-probed]**
- Independent reproduction: a 5-line AOS-S config whose single body line is
  `untagged 1-200000` materializes **200,000 port-name strings in 0.35 s** via
  `parse_intent` (count verified == 200000). Growth is linear; the shape gate
  `_AOS_PORT_SHAPE_RE` (`aruba_aoss/parse.py:367-369`, `\d+` unbounded) accepts
  `3000000000` (probe-verified) → a 22-char line drives ~3×10⁹ string allocations →
  worker OOM.
- `_expand_port_range` has no span bound (parse.py:447-455); reachable call sites all
  fed by raw config text: trunk lines (:461) and VLAN `untagged`/`no untagged`/
  `tagged` lines (:527, :532, :539, :544 — the peer's cites plus one).
- The 10M-char `raw_text` cap (models/migration.py:658-663) is amplification-blind,
  exactly as claimed. The VLAN-clamp sweep precedent makes the fix contour obvious.
  MAJOR stands — this is the one finding in the three reports with direct
  small-input DoS reachability from `POST /plan`.

### PERF-2 — CONFIRMED, minor **[re-probed]**
- `_add_unique` linear membership (transforms.py:129-131), projection call sites
  (:153, :178, :181, :185), reverse-projection `vid not in trunk_allowed_vlans`
  (:290-292) all verified. My probe: 96 trunk ifaces × 4000 VLANs = **0.35 s**
  (peer: 0.46 s — same order); the trunk-all sentinel exact-set condition
  (:144-158) that prevents short-circuit on real-world `1-4000` verified in code.
  Quadratic-in-port-count mechanism (per-VLAN tagged_ports scan grows with each
  port) is real; multiplies PERF-1. Minor at today's scale is honest.

### PERF-3 — CONFIRMED, minor
- `_vlan_parent_for` (opnsense/render.py:592-642) is called once per VLAN from the
  render loop (:308); pass 1 is lags × interfaces plus lags × members × interfaces,
  and `lag_member_set` is rebuilt per call (:631-633). O(V·L·M·I) shape confirmed;
  firewall-target realism keeps it minor.

### PERF-4 — CONFIRMED, note
- `classify` is a linear scan over both lists (models/migration.py:221-228);
  `classify_tree` builds `lossy_by_path`/`unsupp_by_path` dicts (:77-78) and then
  still calls `caps.classify(xpath)` per path (:80-81) — the O(1) fix genuinely is
  two lines in a function that half-implements it. Measured-fine claim accepted
  (peer probe 21 ms / 16k paths; consistent with ~90 string compares per path).

### PERF-5 — CONFIRMED, note (documented design)
- Per-occurrence duplication is stated policy at migration_validate.py:66-68.
  Correctly filed as a future-citation, not a bug.

### misc (target_profiles) — CONFIRMED, minor
- `_expand_range_entries`: `range(start, end + 1)` with no span cap
  (target_profiles.py:446-447); prefix/order validation exists (:434-444) but no
  size bound. Boot-time, operator-authored YAML, fail-visible — minor is right.

### ARCH-1 — CONFIRMED, minor
- Grep: exactly **11** codec files import `_walk_canonical` from
  `..cisco_iosxe_cli.codec` (arista:430, aoscx:680, cisco_iosxe:978, aoss:466,
  mikrotik:487, nxos:605, opnsense:591, iosxr:598, junos:416, fortigate:542,
  vyos:620); the shim re-export is cisco_iosxe_cli/codec.py:60 pointing at
  `canonical/xpath_walker`. Half-finished relocation confirmed; the CodecBase-default
  suggestion is sound.

### ARCH-2 — CONFIRMED, minor
- `def run_plan_with_overrides(  # noqa: C901` at migration_pipeline.py:370 verified;
  the four-copies-per-category shape and the planned-panes docstring are as
  described. Advisory refactor timing ("before pane #6") is reasonable.

### ARCH-3 — CONFIRMED, note **[re-probed]**
- Independent AST measurement: junos `render_intent` **1143** lines, junos
  `parse_intent` **741**, arista `render_intent` **808** (peer's numbers ±1 —
  counting convention, immaterial). Ratchet constant 25 present in
  test_complexity_ratchet.py. The size-vs-count observation holds.

### ARCH-4 / ARCH-5 — ACCEPTED (no-findings; spot-checked consistent)
- Sampled citations (helpers near-twins, scan_stanzas opt-in docstring, lazy-import
  cycle breaks) matched; nothing contradicts the clean sweeps. No counter-evidence.

---

## Final scoreboard

| Finding | Verdict | Final severity |
|---|---|---|
| 16-F1 unlocked job-registry OrderedDict | CONFIRMED | **major** |
| 16-F2 deleted-schedule resurrection / no schedule lock | CONFIRMED | **major** |
| 16-F3 same-second config-save collision | CONFIRMED | minor |
| 16-F4 orphaned .tmp listed as config | CONFIRMED | minor |
| 16-F5 paramiko TOFU lost-update | CONFIRMED | minor |
| 16-F6 running jobs unpersisted until terminal | CONFIRMED | minor |
| 16-F7 scheduler iterates profiles lockless | CONFIRMED | minor |
| 16-F8 unbounded jobs/*.json | CONFIRMED | info |
| 16-F9 _get_fernet double-keygen race | CONFIRMED | minor |
| 16-F10 paramiko session leak on persist failure | CONFIRMED | minor |
| 16-F11 diff TOCTOU 500-not-404 | CONFIRMED | minor |
| 16-F12 torn-read ordering dependency | CONFIRMED | info |
| 18-F1 Docker/MSI ship zero vendor YAMLs | CONFIRMED | **major** |
| 18-F2 PII dirs not gitignored; guard comment false | CONFIRMED | **major** |
| 18-F3 lock-gen base digest drift | CONFIRMED | minor |
| 18-F4 MSI build unpinned supply chain | CONFIRMED | minor |
| 18-F5 workflow-level write perms in test jobs | CONFIRMED | minor |
| 18-F6 dispatch can publish .devN | CONFIRMED | minor |
| 18-F7 cancel-in-progress vs release gate | CONFIRMED | note |
| 18-F8 contradictory Trivy comment | CONFIRMED | nit |
| 18-F9 pre-push hook CRLF gap | CONFIRMED | nit |
| 18-F10 floating artifact-action majors in OIDC job | CONFIRMED | observation |
| 20-PERF-1 aoss port-range OOM amplification | CONFIRMED | **major** |
| 20-PERF-2 quadratic VLAN projection | CONFIRMED | minor |
| 20-PERF-3 opnsense per-VLAN parent rescan | CONFIRMED | minor |
| 20-PERF-4 linear classify (dicts one frame up) | CONFIRMED | note |
| 20-PERF-5 per-occurrence report bloat | CONFIRMED | note (design) |
| 20-misc target_profiles boot-time range | CONFIRMED | minor |
| 20-ARCH-1 walker imported via iosxe_cli shim ×11 | CONFIRMED | minor |
| 20-ARCH-2 rename-pane boilerplate growth | CONFIRMED | minor |
| 20-ARCH-3 ratchet pins count not size | CONFIRMED | note |

Refuted: none. Downgraded: none. The two peer reports with probes (16, 20) had
every probe reproduce on re-run; report 18's central packaging claim re-derives
cleanly from the committed config alone.
