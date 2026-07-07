# 99 — Synthesis: netcanon Fable full-project review (2026-07-03)

Target: netcanon `v0.4.15`, main @ `79c29a0`. Twelve lens agents → four adversarial
verifiers → this synthesis. **Every finding below was produced AND independently
verified by Fable-5 agents.** This was a deliberately Fable-only pass, run separately
from the prior Opus swarm / blind-audit reviews, to see what a different model family
surfaces on the same code.

---

## 1. Executive summary & verdict

The codebase is **healthy**. Across web/API, secrets, SSH, all 12 codecs, schema/matrix
honesty, concurrency, tests, CI/packaging, docs, architecture and CLI, the verifiers found
**zero blockers**, **zero refuted-away false alarms of consequence** (2 downgrades to nit, 3
security downgrades to minor), and no systemic rot. The hardened cores the prior passes
built — 127.0.0.1 default bind, fail-closed `netcanon serve`, Fernet 3-tier at rest,
`DeviceProfilePublic` write-only, TOFU host keys, opt-in egress allow-list, the
support-matrix/walker honesty system, `safe_load`/no-`eval`/no-`shell=True` — all held up
under adversarial re-probing. What remains is a set of **edge and sibling gaps**: places
where one code path was hardened and its twin was not, plus doc/matrix drift and one
shipped-artifact packaging defect. **Verdict: GO-WITH-FIXES.** None of these is a
"the-product-is-broken" defect; they are the second-order cleanup that a mature codebase
accretes.

---

## 2. THE HEADLINE PATTERN — "a hardened path with an un-hardened sibling"

The single most useful lens on this review: most real findings are **not** novel bug
classes. They are cases where the codebase already invented and applied the correct
defense in one place, then a sibling surface was added or left without it. Fixing them is
mostly "apply the pattern you already wrote, over there too." One mental model closes a
large fraction of the list.

| Hardened path (already correct) | Un-hardened sibling (the finding) | ID | Sev |
|---|---|---|---|
| `FileConfigStore.resolve_path` — `_FILENAME_RE` + `is_relative_to` guard | `FileJobStore` / `BackupJobRegistry` take raw `job_id` into a path, no guard | 10-MAJOR-1 | MINOR* |
| `DeviceProfilePublic` write-only response model | `BackupSchedule`/`ScheduleDevice` serve `password`+`enable_password` as plain `str` over the read API | 11-F1 | MAJOR |
| `codecs/base.py` `_validation_error_as_parse_error` logs loc+msg only | profile/schedule stores log `str(ValidationError)` → decrypted creds in `input_value` at ERROR | 11-F2 | MAJOR |
| `_collect_output` sets an absolute `_MAX_SECONDS` deadline once, fails closed | `_drain` resets its deadline on every chunk, no size cap → hang + OOM | 12-MAJOR-1 | MINOR* |
| `DEVICE_PROFILE_REGISTRY_LOCK` guards the profile registry | schedule store has **no** lock → deleted-schedule resurrection, torn saves | 16-F2 | MAJOR |
| profile registry is lock-guarded | `BackupJobRegistry` OrderedDict LRU-mutated on every read, unlocked → `RuntimeError` 500 | 16-F1 | MAJOR |
| VLAN-**id** range clamps (`_parse_vlan_list`, `_expand_vlan_list`) | aoss port-**name** range `_expand_port_range` unclamped → 1e9 alloc OOM | 13-F1 / 20-PERF-1 | MAJOR |
| base wrapper turns `ValidationError`→`ParseError` (clean 400) | 2 XML `int()` sites raise raw `ValueError` (not a `ValidationError` subclass) → 500 | 13-F2 | MEDIUM |
| junos `_quote_always` escapes `"`; opnsense uses ElementTree | fortigate_cli / aruba_aoss / vyos interpolate raw value into `"..."` → breakout | 14-MAJOR-1 | MAJOR |
| interface-mount walker: `if idx > 0 or addr.is_secondary` (patched 276eaeb) | VLAN-mount walker: `if addr.is_secondary:` only — same hole class, unpatched | 15-F6 | MINOR |
| ship-before-wire `_WIRED_UP_BY_CODEC` invariant (8 codecs) | codecs 9–12 (nxos, iosxr, aoscx, vyos) absent from the roster → guard blind on ⅓ of fleet | 15-F3 | MEDIUM |

\* = security-downgraded to MINOR because `netcanon serve` refuses a keyless non-loopback bind (see §3 note).

**Argument:** eight of the twelve most serious findings are instances of this one pattern.
A reviewer or fixer who internalizes "find the hardened twin, port the guard" resolves the
credential-scrub, the lock-coverage, the fail-closed-timeout, the traversal-guard, and the
clamp findings as a single coordinated cluster rather than five unrelated tickets.

---

## 3. Ranked findings

Severity scale: **BLOCKER > HIGH > MAJOR > MEDIUM > MINOR > NIT**. "Verified?" reflects the
adversarial verifier verdict (reports 40–43); the Docker-vendors row reflects a main-thread
ground-truth check against real build config (supersedes reports 18/42 on severity).

### HIGH / MAJOR

| ID | Sev | Finding | file:line | Verified? | Fix sketch |
|---|---|---|---|---|---|
| PKG-1 (18-F1) | **HIGH** | **Docker image ships an EMPTY vendor registry** — `vendors/*.yaml` not in `package-data`; git-less wheel (Docker builder condition) = 0 vendors; `load_vendors()` logs "Loaded 0 vendor(s)", translator core non-functional in Docker. PyPI unaffected (sdist carries files). MSI probably affected. | `pyproject.toml:163-177` (glob); `migration/vendors/__init__.py:33-82`; `Dockerfile:53`; `.dockerignore:2`; smoke gate `ci.yml:364`; `setup_desktop.py:100-114` | CONFIRMED (main-thread, real-artifact) | Add `"migration/vendors/*.yaml"` to the package-data glob (one line). Tighten docker-smoke to assert a vendor actually loaded (dropdown non-empty), not just `/`→200. Check the MSI build. |
| SEC-1 (11-F1) | MAJOR | Legacy inline **SSH + enable passwords echoed in plaintext** over `GET /api/v1/schedules/` (and POST/toggle echoes) — `ScheduleDevice.password/enable_password` are plain `str`, no scrub; store decrypts in place at load. Bounded: legacy-only (needs a pre-profile schedule file). | `models/schedule.py:38-39`; `schedules.py:279,292,354`; `schedule_store.py:90-95` | CONFIRMED (probe) | Add a `BackupSchedulePublic` response model that blanks device creds; use on all 3 `response_model=` sites + a guard test mirroring `test_device_profile_public.py`. |
| SEC-2 (11-F2) | MAJOR | **Decrypted creds reach ERROR logs** — corrupt-file `except` logs `str(ValidationError)`; pydantic middle-truncation leaves the tail credential (`enable_password`) verbatim in `input_value`. A future required-field upgrade would dump every profile at startup. This is the CodeQL clear-text-logging HIGH class the project's own CI gates against. | `device_profile_store.py:105-123`; `schedule_store.py:110-113` | CONFIRMED (probe) | Special-case `ValidationError`: log `exc.errors(include_input=False, include_url=False)`, or scrub cred keys before formatting. |
| PERF-1 (13-F1 / 20-PERF-1) | MAJOR | **aoss port-range OOM** — `_expand_port_range` materializes `range(lo, hi+1)` with no clamp; `_AOS_PORT_SHAPE_RE` accepts unbounded `\d+`. A ~35-byte `tagged 1-999999999` in a VLAN stanza drives ~1e9 allocations. **Directly reachable from `POST /plan`**; 10M-char body cap is amplification-blind. *(One finding — appears in 13/20/41/42.)* | `aruba_aoss/parse.py:367-369,447-455` (+ call sites 406,461,527,532,539,544) | CONFIRMED (re-probed, 200k in 0.35s, linear) | Clamp span (mirror the VLAN-id clamp precedent), e.g. reject/limit spans > a few thousand ports before materializing. |
| CODEC-1 (14-MAJOR-1) | MAJOR | **Unescaped `"` breakout** in quoted free-text on **fortigate_cli, aruba_aoss, vyos** — raw value interpolated into `"..."` (description / SNMP location / contact / community / hostname). Cross-vendor reachable (CLI parsers capture description-to-EOL). Corrupts the deliverable (non-security). | `vyos/render.py:105-107`; `fortigate_cli/render.py:433,457,555,761,763,778`; aruba_aoss render sites | CONFIRMED (probe) | Add the in-tree escaping pattern (junos `_quote_always` doubles/backslashes `"`) to all three; central `_q` helper. |
| CODEC-2 (15-F5) | MAJOR | **vyos `vif` under-parse → broken IOS sub-interface, clean report.** `dot1q_vlan` never populated on source-side parse, so the walker never yields `/dot1q-vlan`; render to iosxe emits `interface eth1.100 / ip address …` with **no `encapsulation dot1Q`** (IOS rejects) and `validate_against` reports severity ok. Honesty system structurally blind. | `vyos/parse.py:461,486` | CONFIRMED (probe) | Populate `dot1q_vlan` from the `vif N` id on parse so the walker + honesty layer see it. |
| CONC-1 (16-F1) | MAJOR | **Unlocked job-registry OrderedDict** — `__getitem__` `move_to_end` on every read, `values()` returns the live view; a `GET /backups/{id}` poll (or scheduler-thread insert) during a dashboard/jobs-page list raises `RuntimeError: OrderedDict mutated during iteration` → user-visible 500. Regressed when R8 made the cache an LRU. | `job_registry.py:147-150,167,174,202-204`; readers `backups.py:249-253`, `ui.py:176-182,202-209` | CONFIRMED (re-probed) | Wrap registry mutations/iterations in a lock; or snapshot `list(values())` under lock before sorting. |
| CONC-2 (16-F2) | MAJOR | **Deleted-schedule resurrection** — `_run_scheduled_backup_inner` captures the schedule, awaits a minutes-long backup, then unconditionally `schedule_store.save(schedule)` with no existence re-check; a mid-run delete is rewritten to disk and resumes firing on restart (re-persisting legacy inline creds). Schedules never got the `#10` registry lock. Also: shared `{id}.tmp` collision, unlocked toggle flip, check-then-insert 200-cap. | `schedules.py:143,245-259,269,303-309,334-349,369-370`; `schedule_store.py:49-60` | CONFIRMED | Add a schedule-registry lock mirroring `DEVICE_PROFILE_REGISTRY_LOCK`; re-check existence before the post-run save; per-save unique tmp path. |
| TEST-1 (17-F-1) | MAJOR | **Dead integration test** — the only /detect+`source_filename` happy-path test skips on `!= 200`, but the route returns **202**, so it has never run past the skip. Distinct from API-1 below. *(Note: fixing to `!= 202` alone trades the skip for a wrong-content failure because the shared FakeCollector returns Cisco output for every type_key.)* | `test_migration_api.py:1780-1800`; route `backups.py:143` | CONFIRMED | Assert `== 202` **and** wire an OPNsense-outputting collector (`OPNSENSE_FAKE_OUTPUT` exists in `tests/conftest.py`). |
| UX-1 (19-M-1) | MAJOR | **"undefined" in the migrate-page error banner/button** — `adapterEntry` omits `vendor_display_name`/`name`; the parse-failed enrichment path dereferences both → literal `"undefined"` shown to the operator. Reachable in the normal parse-failure case; no test asserts the label. | `migrate.html:860-875,1373-1375,1384-1399,1629`; trigger `migration_pipeline.py:303` | CONFIRMED | One-line JS fix (use `adapters.find` like `:1147`, or add the fields to `adapterEntry`); add an e2e assertion on the button text. |
| DOC-1 (19-M-2) | MAJOR | **dot1q doc/matrix drift** — junos supported list carries `/dot1q-vlan` (wired for real in parse.py) but the same file's subinterface `LossyPath.reason` still says "`unit N vlan-id 100` still parses-and-ignores" (and lossy reasons render to operators); `CAPABILITIES.md:278` repeats the stale sentence. Drift, not the parked honesty concept. | `juniper_junos/codec.py:135-139,264-277`; `parse.py:1516-1528`; `CAPABILITIES.md:278` | CONFIRMED | Rewrite the junos subinterface lossy reason + sync CAPABILITIES (fold m-2/m-4/m-5 into one doc PR). |
| LIC-1 (19-M-3) | MAJOR (borderline) | **THIRD-PARTY-NOTICES.txt missing 7 deps** — pydantic-settings, aiofiles, apscheduler, tzlocal (direct) + rich/pygments/ruamel-yaml (via netmiko, land in the MSI freeze) absent, though the file claims MSI-redistribution completeness. Low practical legal risk (all permissive), trivial fix. | `pyproject.toml:63,69,74,83`; `requirements.lock:588,7,25,756,718,722`; `THIRD-PARTY-NOTICES.txt` | CONFIRMED | Add the 7 entries before the next MSI-bearing release. |
| API-1 (21-F-1) | MAJOR | **`/plan` port-rename-map dispatch trap** — a vlan-only override (no `port_rename_map`) leaves the sentinel `None`, which **disengages the translator entirely**, so `GigabitEthernet1/0/1` renders verbatim to junos with zero warnings — violating the shipped v0.3.2 auto-translate-by-default contract. UI is immune (always sets the key). Distinct from TEST-1 (different endpoint, different failure). | route `migration.py:262-266`; pipeline `migration_pipeline.py:592-599` (doc self-contradiction at `:426-427`) | CONFIRMED (reproduced) | One-token route fix (`else {}`); add an integration test posting a vlan-only override and asserting translated names. |
| GUARD-1 (18-F2) | MAJOR | **PII dirs not gitignored; guard's own claim is false** — `docs/codebase-review/` and `docs/reviews/2026-06-19-run3-verification/` are untracked-not-ignored; `pii-guard.yml:27-29` claims they are gitignored (false in-tree) and the guard is content-pattern-only. `run3-verification/` (unlicensed third-party config, matches neither PII pattern) is the truly exposed surface; `MANIFEST.in` prunes only `tests/`, so a stray `git add docs/` auto-ships it in the next sdist. | `.gitignore` (no entry); `pii-guard.yml:27-29,50`; `MANIFEST.in` | CONFIRMED | Add both paths to `.gitignore`; add a path-based guard layer; correct the false comment. |

### MEDIUM

| ID | Sev | Finding | file:line | Verified? | Fix sketch |
|---|---|---|---|---|---|
| MTX-1 (15-F1) | MEDIUM | nxos declares `/vxlan-vnis/udp-port` **supported** but normalizes any value to 4789; a source carrying 8472 (vyos default) silently changes with `validate_against` reporting severity ok. Inverse of "declared-lossy is honest". | `cisco_nxos` udp-port render/classify; `vyos/parse.py:801` | CONFIRMED (probe) | Declare udp-port lossy (or unsupported) on nxos, or preserve the value. |
| MTX-2 (15-F2) | MEDIUM | aruba_aoscx has **no declaration** for `/vxlan-vnis/udp-port` → `classify()` fail-opens to supported; same silent-drop-with-clean-report as MTX-1. | `aruba_aoscx/codec.py` (path absent) | CONFIRMED (probe) | Add an explicit lossy/unsupported declaration. |
| MTX-3 (15-F3) | MEDIUM | ship-before-wire invariant roster hardcoded at **8 codecs**; nxos/iosxr/aoscx/vyos absent from the parametrize list and `_WIRED_UP_BY_CODEC` — the two-sided guard is blind for ⅓ of the fleet (root cause of the F4/F7 honesty gaps). | `test_canonical_vrrp_anycast_schema.py:339-417` | CONFIRMED | Derive the roster from `list_codecs()`; add a guard-the-guard test. |
| ROB-1 (13-F2) | MEDIUM | 2 XML codecs leak a raw `ValueError` from `parse()` (a plain `int("abc")` isn't a `ValidationError` subclass, so the base safety net misses it) → `/sanitize` returns **500** instead of a clean 400, violating the `Raises: ParseError` contract. | `opnsense/parse.py:424`; `cisco_iosxe/codec.py:1151`; net `base.py:275-281`, `sanitize.py:82` | CONFIRMED (probe) | Wrap both `int()` sites in `try/except ValueError → ParseError` (their in-function siblings already do). |

### MINOR (grouped; all CONFIRMED unless noted)

**Security — downgraded majors (the known-good posture holds):**
| ID | Finding | file:line | Note |
|---|---|---|---|
| SEC-3 (10-MAJOR-1) | `job_id` path traversal (Windows `\`), existence oracle + bounded `BackupJob` disclosure | `job_store.py:43,93,120`; `job_registry.py:188`; `backups.py:261-275` | **Downgraded MAJOR→MINOR**: `netcanon serve` refuses a keyless non-loopback bind (`cli.py:201-206`, `Dockerfile:118`); local-only on default bind, post-auth on exposed. Real defect, cheap fix (mirror the config-store guard / `pattern=UUID`). |
| SEC-4 (10-MAJOR-2) | `NETCANON_API_KEY` gates `/api/v1` but not the UI pages rendering the same host/username/inventory | `main.py:307,319`; `ui.py:202,253,363` | **Downgraded MAJOR→MINOR**: documented intended behavior (`auth.py:16-21` — key is orthogonal to the reverse proxy). Residual = misconfig; fix is a loud doc note or extend the gate to UI routes. |
| SEC-5 (12-MAJOR-1) | `_drain` unbounded read loop (deadline reset every chunk, no size cap) → hung worker + OOM | `paramiko_collector.py:342-361` | **Downgraded MAJOR→MINOR**: requires pointing at a hostile/broken device (trust-anchor) or first-connect MITM; availability-only. Fix: absolute cap + idle-only reset (mirror `_MAX_SECONDS`). |

**Security — minor as filed:**
| ID | Finding | file:line |
|---|---|---|
| SEC-6 (11-F3) | SNMP community logged verbatim at DEBUG (`current=%r`); all sibling orchestrators log counts only | `snmp_names.py:149-154` |
| SEC-7 (11-F4) | SECURITY.md cites a test that has 0 credential assertions (false citation; the claim itself is false in the SEC-2 path) | `SECURITY.md:192-193` |
| SEC-8 (10-MINOR-3) | CSRF on no-body `POST /open` (simple request, no CORS middleware); gated on `open_in_editor` (off/desktop/loopback) | `configs.py:126` |
| SEC-9 (10-MINOR-4) | No Content-Security-Policy header (defense-in-depth; autoescape already mitigates) | `main.py:297-302` |
| SEC-10 (10-MINOR-5 = 21-F-8) | `/migration/detect` `raw_text` has no `max_length` vs `/plan`'s 10M cap (pydantic buffers full body). *One finding — merged.* | `migration.py:131` vs `models/migration.py:658-663` |
| SEC-11 (12-MINOR-1) | Egress allow-list lets `0.0.0.0`/`::` through → loopback bypass on connect (metadata endpoint stays blocked) | `egress.py:38-51` |
| SEC-12 (12-MINOR-2 = 16-F5) | `known_hosts`/TOFU write race — AutoAddPolicy saves inside `connect()`, outside `_KNOWN_HOSTS_LOCK`; last-writer-wins on concurrent first-time TOFU. *One finding — merged.* | `paramiko_collector.py:181,277`; `hostkey.py:74,99` |

**Codec / matrix:**
| ID | Finding | file:line |
|---|---|---|
| CODEC-3 (14-MINOR-2) | mikrotik `_escape` handles `"` but not `\`; trailing backslash escapes the closing quote → unterminated string | `mikrotik/render.py:881-883` |
| CODEC-4 (14-MINOR-3) | SNMP community with whitespace emitted as bare token → target syntax error (arista/iosxe_cli/nxos/aoscx/vyos) | `vyos` + siblings |
| MTX-4 (15-F4) | `/anycast-gateway-mac` undeclared on iosxr+vyos → classifies supported but drops (**downgraded MAJOR→MINOR**: per-address VGA `unsupported` co-fires except chassis-MAC-only source) | `cisco_iosxr` + `vyos` codec |
| MTX-5 (15-F6) | VLAN-mount `secondary-ip` walk `is_secondary`-only vs interface-mount `idx>0 or is_secondary` (latent, no silent loss today) | `xpath_walker.py:96` vs `:226` |
| MTX-6 (15-F7) | interface-mount `virtual-gateway-mac` (v4+v6) undeclared across the 6 no-anycast codecs (co-flagged by the VGA `unsupported`, mis-itemized) | classify sweep |

**Concurrency (all confirmed minor):**
| ID | Finding | file:line |
|---|---|---|
| CONC-3 (16-F3) | FileConfigStore same-second save collision (non-atomic `exists`-loop + shared tmp) | `file_store.py:172-184` |
| CONC-4 (16-F4) | orphaned `.tmp` from a crash matches `_FILENAME_RE`, listed as a real config | `file_store.py:87-90,220-234` |
| CONC-5 (16-F6) | LRU-evicted running job → `__contains__` disk-miss → 404 for an active job | `job_registry.py:184-188`; `backups.py:273-275` |
| CONC-6 (16-F7) | scheduler iterates `device_profiles.items()` on the loop with no lock → dict-changed RuntimeError silently skips the run | `schedules.py:157` |
| CONC-7 (16-F9) | `_get_fernet` double-keygen race on fresh install (no env key) → loser's ciphertext fails closed later | `credentials.py:245-255,208-242` |
| CONC-8 (16-F10) | paramiko session leak — `probe()` returns `{}` on connect/persist failure without `client.close()` | `paramiko_collector.py:276-294` |
| CONC-9 (16-F11) | diff TOCTOU — delete-between-list-and-read yields 500 (no FileNotFoundError catch) where a moment earlier it's 404 | `configs.py:301,319-320`; `ui.py:335-336` |

**CI / packaging / supply-chain (minor):**
| ID | Finding | file:line |
|---|---|---|
| PKG-2 (18-F3) | lock-gen base digest drift — `3.14.5` in gen script vs `3.14.6` in Dockerfile (+ comment rot "Python 3.13") | `gen_requirements_lock.sh:25` vs `Dockerfile:12,60,9,14-16` |
| PKG-3 (18-F4) | MSI build `pip install -e ".[desktop-build]"` — no lock, no hashes at release time; auto-downloads WiX | `desktop-msi-publish.yml:191-201` |
| PKG-4 (18-F5) | workflow-level `contents: write` / `packages: write` reaches pytest-only test jobs (pypi-publish is the correct scoped model) | `desktop-msi-publish.yml:41-43`; `docker-publish.yml:10-15` |
| PKG-5 (18-F6) | bare `workflow_dispatch` can publish a `.devN` (ancestry check passes trivially on main; `no-local-version` makes it PyPI-legal) — maintainer-only footgun | `pypi-publish.yml:8`; `pyproject.toml:141` |

**Docs honesty (minor drift):**
| ID | Finding | file:line |
|---|---|---|
| DOC-2 (19-m-1) | SECURITY.md claims browser-fetched passwords; code does server-side resolution (`DeviceProfilePublic`) — understates security + internally inconsistent | `SECURITY.md:232-240` vs `device_profiles.py:33,49` |
| DOC-3 (19-m-2) | CAPABILITIES.md "255 unrepresentable"; code maps owner↔255 both ways ("now representable") | `CAPABILITIES.md:257` vs `aruba_aoss/parse.py:604-659` |
| DOC-4 (19-m-3) | CONTRIBUTING says `--matrix` regenerates PHASE4_RECONCILIATION.md; tool actually writes CROSS_MESH_RESULTS.md | `CONTRIBUTING.md:50-52` vs `run_full_mesh.py:24-29` |
| DOC-5 (19-m-4) | CAPABILITIES lists only `"snmpv3"`; code declares `{"snmpv3","ports"}` | `CAPABILITIES.md:549-551` vs `cisco_iosxe/codec.py:220-223` |
| DOC-6 (19-m-5) | CAPABILITIES hard-codes "all seven bidirectional codecs" in a 12-codec registry (violates the no-hard-coded-counts rule) | `CAPABILITIES.md:93-95` |

**CLI / API contract (minor):**
| ID | Finding | file:line |
|---|---|---|
| API-2 (21-F-2) | per-pane routes render verbatim names with a fictional "UI pane-switch" rationale; `:314` names a `/plan/snmpv3_users` route that ships as `/plan/snmpv3` | `migration.py:314,322-326,339-343,397-399` |
| API-3 (21-F-3) | `cli.py` sanitize `write_text` sits outside the try; `RenderError` from `codec.render` is uncaught (HTTP route → 500) | `cli.py:173-174`; `sanitize.py:241`; `routes/sanitize.py:82-86` |
| API-4 (21-F-4) | `sanitize_text` has no input-recognition guard (the pipeline has `_input_not_recognized`); wrong-codec sanitize silently emits a scaffold with 0 substitutions | `tools/sanitize.py:184-245` |
| API-5 (21-F-5) | demo string-suffix status check misses `partial` → demo prints success + exits 0 on a partial job (prospective) | `demo.py:274` |
| API-6 (21-F-6) | stale compat docs — else-branch actually calls `run_plan_with_overrides(..., port_rename_map={})` but 3 docs still promise "plain run_plan unchanged / no translation" | `_migration_helpers.py:173-174`; `migration_pipeline.py:27`; `models/migration.py:666-671` |
| API-7 (21-F-7) | `force` doesn't clear a block (only threaded, never clears block-severity → partial); model docstrings over-promise | `migration_pipeline.py:246,331-339` vs `models/migration.py:128-143` |

**Test quality (minor):**
| ID | Finding | file:line |
|---|---|---|
| TEST-2 (17-F-2) | cross-mesh CI guard compares only total codec-bug count + pair membership; a 2→3-while-1→0 regression passes green | `test_cross_mesh_ci_guard.py:136,148-156` |
| TEST-3 (17-F-3) | vyos vrrp-groups-unsupported not pinned by a codec test (ship-before-wire roster only 8; relates to MTX-3) | `test_vyos.py:837-846` |
| TEST-4 (17-F-4) | mccabe ratchet keys on the literal `# noqa: C901`; `PGH004` not in ruff select (codebase currently clean) | `test_complexity_ratchet.py:36,49`; `pyproject.toml:214-226` |
| TEST-5 (17-F-5) | memory test labelled "flaky in CI" but asserts a hard `< 5MB` delta; with `-x` one flake aborts the whole run | `test_load_and_memory.py:334-368` |

**Performance / architecture (minor / note):**
| ID | Finding | file:line |
|---|---|---|
| PERF-2 (20-PERF-2) | quadratic VLAN projection (`_add_unique` linear membership); 96 ifaces × 4000 VLANs = 0.35s; multiplies PERF-1 | `transforms.py:129-158,290-292` |
| PERF-3 (20-PERF-3) | opnsense `_vlan_parent_for` rebuilds `lag_member_set` per VLAN → O(V·L·M·I) | `opnsense/render.py:592-642,308` |
| PERF-4 (20-misc) | `target_profiles` `_expand_range_entries` boot-time range, no span cap (operator YAML, fail-visible) | `target_profiles.py:446-447` |
| ARCH-1 (20-ARCH-1) | `_walk_canonical` imported via the `cisco_iosxe_cli` shim by 11 codecs (half-finished relocation) | 11 codec files → `cisco_iosxe_cli/codec.py:60` |
| ARCH-2 (20-ARCH-2) | `run_plan_with_overrides` `# noqa: C901`, 4-copies-per-category boilerplate (advisory refactor before pane #6) | `migration_pipeline.py:370` |

### NIT / INFO / NOTE (recorded, no action urged)

`19-m-6` sanitize label/category count mismatch (deliberate documented fallback — **downgraded to NIT**) ·
`19-m-7` SECURITY.md line-anchor rot on a true defusedxml claim (**downgraded to NIT**) ·
`19-m-8` CONTRIBUTING says "pre-commit hooks" but only a git-hook exists ·
`18-F7` `cancel-in-progress` vs release gate (operational confusion) ·
`18-F8` self-contradictory Trivy pin comment ·
`18-F9` `pre-push` hook not in `.gitattributes` → CRLF break on Windows clones ·
`18-F10` floating `upload/download-artifact` majors in the OIDC job (publish action itself SHA-pinned) ·
`17-F-6` stale render-failure allowlist entry ·
`17-F-7` e2e conditional skip / `_find_free_port` TOCTOU ·
`17-F-8` windows-only config test (ubuntu CI) ·
`16-F8` unbounded `jobs/*.json` (by design) ·
`16-F12` torn-read ordering dependency (status flips last — safe) ·
`20-PERF-5` per-occurrence report duplication (documented policy) ·
`20-PERF-4`/`ARCH-3` linear `classify` (dicts one frame up) / ratchet pins count-not-size.

---

## 4. CONFIRMED CLEAN — checked and passed (not bugs)

The verifiers spot-checked the reviewers' negative claims and independently confirmed these
are sound — recorded so nobody re-hunts them:

- **Error-handling axis:** zero bare `except:` in `netcanon/`; corrupt-file skip markers,
  `translate_backup_error` path-suppression, and the resolve-or-family_base guard all verified.
- **Architecture axis:** helpers near-twins / `scan_stanzas` opt-in / lazy-import cycle-breaks
  all consistent; **no circular imports**; **no in-definition `re.compile`** anti-pattern.
- **v0.3–0.4 code is well-tested** — the new arcs did not introduce a runtime defect the
  suites miss (beyond the specific drift/dead-test items above).
- **IPv6 prefix-length crash class is genuinely CLOSED** — `ip address …/40` and `ipv6 …/200`
  surface as clean `ParseError` via the wrapped `codec.parse` (only raw `parse_intent()` shows
  the underlying `ValidationError`, and no production path calls it).
- **CHANGELOG ↔ tags reconciled** (changelog guard exists and runs in CI).
- **Demo is honest** (the earlier "bare run_plan" front-page discrepancy was fixed; demo prints
  renames).
- **Core security posture intact:** `bind_refusal_reason` enforced before `uvicorn.run`; Docker
  ENTRYPOINT is `netcanon serve`; `require_api_key` fail-closed + `hmac.compare_digest`; YAML
  `safe_load` everywhere; no `pickle`/`eval`/`exec`/`shell=True`; Fernet 3-tier fail-closed;
  `SecretStr` in transit; IPv4-mapped-IPv6 unwrap blocks `::ffff:169.254.169.254`; decimal/octal
  integer IP forms rejected; config-store traversal guard solid.

---

## 5. Recommended fix order

**Tier 0 — one-liners / one-paragraph (do first, highest value-per-minute):**
1. **PKG-1** — add `"migration/vendors/*.yaml"` to the package-data glob (restores the Docker
   translator core) **+** tighten docker-smoke to assert a vendor loaded. *(HIGH.)*
2. **API-1** — the `else {}` route fix on `/plan` (restores auto-translate for API callers).
3. **UX-1** — the `migrate.html` `undefined`-banner one-line JS fix.
4. **SEC-7 / DOC-1 / DOC-2..6** — the doc/matrix drift cluster: SECURITY.md false test citation,
   the dot1q junos lossy-reason + CAPABILITIES sync, the CAPABILITIES/CONTRIBUTING drift rows,
   THIRD-PARTY-NOTICES 7 missing deps (**LIC-1**), lock-gen digest (**PKG-2**). Batch as one doc PR.
5. **GUARD-1** — add both PII dirs to `.gitignore` + fix the false pii-guard comment.

**Tier 1 — the sibling-hardening cluster (§2 pattern; each is "port a guard you already wrote"):**
6. **SEC-1** — `BackupSchedulePublic` response model + guard test.
7. **SEC-2** — special-case `ValidationError` in the two store `except` blocks.
8. **CONC-1 / CONC-2** — a schedule-registry lock + job-registry lock/snapshot (fixes both, plus
   CONC-6/CONC-7 fall out of the same lock discipline).
9. **PERF-1** — clamp the aoss port-range span (mirror the VLAN-id clamp).
10. **CODEC-1** — the `"`-escaping helper on fortigate_cli / aruba_aoss / vyos (+ CODEC-3 backslash).
11. **SEC-3 / SEC-5** — mirror the config-store traversal guard onto the job store; give `_drain`
    an absolute cap (both downgraded, both cheap, both close a real defect).

**Tier 2 — MEDIUM matrix/robustness + test-guard coverage:**
12. **CODEC-2 / ROB-1** — populate vyos `dot1q_vlan`; wrap the 2 XML `int()` sites in `ParseError`.
13. **MTX-1..3** — declare nxos/aoscx udp-port lossy; derive the ship-before-wire roster from
    `list_codecs()` (closes MTX-3 → and the MTX-4/5/6 + TEST-3 honesty gaps it gates).
14. **TEST-1 / TEST-2** — un-skip the /detect test with a real OPNsense collector; make the
    cross-mesh guard per-pair.

The MINOR/NIT tail (CI perms, TOCTOU 404s, demo status check, perf O(n²) at today's scale) is
genuine but low-urgency — batch opportunistically.

---

*Prepared by the Fable-5 synthesis pass over 12 lens reports + 4 adversarial verifiers. Every
finding was authored and independently verified by Fable-5 agents; this pass was run separately
from the prior Opus reviews by design, as a different-model-family cross-check.*
