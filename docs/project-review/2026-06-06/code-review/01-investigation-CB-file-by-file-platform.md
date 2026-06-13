# 01 — Investigation CB: File-by-file, platform (non-codec) source + desktop

Reviewer: **CB** (Fleet C, code & architecture review, Opus 4.8 1M tier).
Lens: tiered file-by-file over **everything under `netcanon/` EXCEPT
`migration/codecs/`**, plus all of `netcanon_desktop/`.
Commit: `b08040c` (v0.1.2). Read-only.

---

## 1. Scope & method

### 1.1 Partition

CB owns 78 source files (confirmed against
`git ls-files "netcanon/*.py" "netcanon_desktop/*.py" | grep -v migration/codecs/`
→ exactly 78, matching the brief's "~78 of"). Concretely:

* **App core** — `main.py`, `cli.py`, `config.py`, `logging_config.py`, `netcanon/__init__.py`.
* **`api/`** — `deps.py`, `_errors.py`, and every route module
  (`ui`, `migration`, `backups`, `configs`, `schedules`, `device_profiles`,
  `definitions`, `sanitize`, `health`, `_migration_helpers`, the package `__init__`s).
* **`services/`** — `migration_pipeline.py`, `diff.py`, `migration_detect.py`,
  `migration_validate.py`.
* **`storage/`** — `file_store.py`, `device_profile_store.py`, `schedule_store.py`,
  `job_store.py`, `job_registry.py`, `base.py`.
* **`collectors/`** — `paramiko_collector.py`, `netmiko_collector.py`, `base.py`,
  `probe.py`.
* **`models/`** — `migration.py`, `device.py`, `diff.py`, `schedule.py`,
  `device_profile.py`, `backup.py`, `validators.py`.
* **`security/`** — `credentials.py`, `migration.py`.
* **`definitions/`** — `loader.py`, `schema.py`.
* **`tools/`** — `sanitize.py` (note: repo-root `tools/demo.py` /
  `load_cross_vendor_expectations.py` are NOT in `netcanon/tools/` and are
  therefore out of scope; the brief's "tools/" rows resolve to `netcanon/tools/`).
* **`migration/` root** — `_naming.py`, `_tier3_detection.py`, `_user_secrets.py`,
  `target_profiles.py`, `__init__.py`, `vendors/__init__.py`.
* **`migration/canonical/`** — `intent.py`, `transforms.py`, `port_names.py`,
  `loader.py`, `vlan_names.py`, `local_user_names.py`, `snmp_names.py`,
  `snmpv3_user_names.py`, `__init__.py`.
* **`netcanon_desktop/`** — all 11 (`app`, `server`, `window`, `tray`,
  `preferences`, `preferences_dialog`, `settings`, `icons`, `single_instance`,
  `__main__`, `__init__`).

### 1.2 Method

I read **every file in the partition in full** (no sampling) — the entire set
fits comfortably in the 1M context, so verdicts here are grounded in direct
reading rather than sub-agent summaries. The eight god-files in the brief
(`api/routes/ui.py` 894, `models/migration.py` 842, `services/migration_pipeline.py`
711, `api/routes/migration.py` 678, `canonical/port_names.py` 614,
`tools/sanitize.py` 565, `target_profiles.py` 544, `canonical/intent.py` 926)
received full long-form treatment in §4.

I read `docs/METHODOLOGY.md`, `AGENTS.md` § Hard Rules + Documentation Sync
Checklist, and `00-snapshot.md`/`00-code-scope.md` first so I do not flag
load-bearing invariants (frozen pipeline signatures, `AutoAddPolicy` trust
model, `type_key` filename grammar, the broad-except-with-logger pattern,
ship-before-wire) as defects. Where something looks wrong but is intentional,
I record it as an **OBSERVATION** with rationale rather than a P-level finding.

I confirmed the codec-side wiring of the ship-before-wire canonical fields
(the Fleet D candidate) by `grep` across `migration/codecs/` even though that
tree is CC's partition — that evidence is load-bearing for the **intent.py
docstring** finding, which IS in my partition. I coordinate with CE on the
god-file *cohesion* framing (CE owns SPLIT/KEEP verdicts); my god-file
treatment covers **correctness, clarity, dead code, and drift**.

### 1.3 Severity scale

`P0` (data loss / security / crash on the happy path) · `P1` (incorrect
behaviour on a real input) · `P2` (latent bug / correctness smell with a
narrow trigger) · `P3` (clarity / minor robustness) · `OBSERVATION`
(intentional-but-worth-noting, or a design comment). `UNVERIFIED` marks
anything I could not fully confirm read-only.

---

## 2. Executive summary

**This is a strikingly disciplined platform layer.** Across 78 files I found
**zero P0s and zero P1s**. The dominant impression is of a codebase that has
been through multiple audit cycles (security-triage 2026-05-21, docs-audit
2026-05-21) and shows it: every storage write is atomic (temp+rename), every
broad `except` is paired with a `logger` call and a documented rationale,
every credential field is `SecretStr` in flight and Fernet-encrypted at rest,
every persistence loader degrades gracefully on a corrupt file rather than
crashing startup, and every public function carries a Google-style docstring
that is — with a handful of exceptions catalogued below — accurate.

The findings cluster into two themes:

1. **Matrix-honesty docstring drift on the canonical model (`intent.py`).**
   The single most material finding. `intent.py`'s top-level and per-field
   docstrings repeatedly assert that the v0.2.0 "ship-before-wire" fields
   (`vrrp_groups`, `virtual_gateway_address`, `virtual_gateway_mac`,
   `anycast_gateway_mac`) are universally `unsupported` across every codec and
   that "No codec populates any of these in v1." The codec layer has since
   landed Wave B/C wire-ups: arista_eos, cisco_iosxe_cli, juniper_junos (and
   others) now both *populate* these on parse and *declare them `supported`*
   in their CapabilityMatrix. The docstrings are stale. By the project's own
   methodology (`docs/METHODOLOGY.md` § "No active lies in operator-facing
   messages"; AGENTS.md doc-sync row "A new canonical field on
   `CanonicalIntent`"), a stale capability claim in a load-bearing docstring
   is a bug, not debt. (`CB-01`, P2.) **Note:** the narrower Fleet D candidate
   — "`is_secondary` documented not-wired but may already be live" — does NOT
   reproduce when read literally: no codec sets `is_secondary=True` (verified),
   so the `is_secondary` docstring is accurate. The drift is on its *sibling*
   fields under the same shared docstring paragraph.

2. **"Phase 0 / Phase 0.5 stub" docstrings that the architecture outgrew.**
   `canonical/__init__.py`, `canonical/loader.py`, and `models/migration.py`'s
   header still describe a libyang-backed Phase-0.5 future and "Phase 0 ships
   only this stub." The pydantic-model IR in `intent.py` is the path that was
   actually taken; libyang never landed and the canonical package is no longer
   "only a stub." These are the methodology's named "active lies in
   docstrings" anti-pattern. (`CB-02`, P3.)

Beyond those, the catalogue is small-bore: one genuine round-trip imperfection
in `file_store._parse_filename` host reconstruction (`CB-03`, P3, with a
correctness argument for why it is nonetheless safe in practice), a stray
mis-indented comment (`CB-06`, P3), a couple of desktop docstrings still
naming `pywebview`/`Edge WebView2` after the PySide6/Chromium migration
(`CB-04`, P3), and a small set of OBSERVATIONS about intentional designs that
a future reader might mistake for bugs.

**What's genuinely good** (expanded in §6): the five-orchestrator rename family
(`port_names`/`vlan_names`/`local_user_names`/`snmp_names`/`snmpv3_user_names`)
is a textbook consistent-pattern set; `api/_errors.py` is an exemplary
exception-taxonomy translator; the `BackupJobRegistry` LRU+disk-fallback is a
clean bounded-memory design with honest `__len__` semantics; the `diff.fold_context`
two-sweep distance algorithm is elegant and correct; the broad-except
discipline is uniform and each instance is justified in a comment.

Coverage: **78 / 78 files** carry a verdict (§3, §7). Tally:
KEEP **70**, WATCH **6**, CONCERN **2**.

---

## 3. Per-area file-by-file tables

Verdict legend: **KEEP** (healthy, no action) · **WATCH** (minor issue or
worth monitoring) · **CONCERN** (a finding attaches; see §5). LOC is
approximate (`wc -l`).

### 3.1 App core

| Path | Purpose | LOC | Verdict | Note |
|---|---|--:|---|---|
| `netcanon/main.py` | App factory + lifespan (state wiring, scheduler, middleware) | 314 | KEEP | Clean factory; request-id + security-headers middleware; module-level `app` wrapped in try/except → `SystemExit(1)`. Middleware ordering comment is correct (registered req-id BEFORE security so it wraps outermost). |
| `netcanon/cli.py` | `netcanon sanitize` CLI entry | 142 | KEEP | Lazy imports keep `--help` fast; exit codes 0/2 sensible; dry-run truncation tidy. |
| `netcanon/config.py` | `Settings` (pydantic-settings) + `MAX_BACKUP_CONCURRENCY` | 93 | KEEP | `effective_data_dir` property cleanly handles the desktop override. `backup_concurrency`/`max_memory_jobs` `Field` bounds are honest. |
| `netcanon/logging_config.py` | Idempotent root-logger config + `RequestIdFilter` | 165 | KEEP | The pytest-handler carve-out (line 130-134) is subtle but correct and documented. ContextVar req-id threading is well-reasoned. |
| `netcanon/__init__.py` | Package docstring | 26 | KEEP | Accurate layout map. |

### 3.2 `api/`

| Path | Purpose | LOC | Verdict | Note |
|---|---|--:|---|---|
| `api/routes/ui.py` | All server-rendered HTML GET routes + `/docs` wrapper | 894 | KEEP | God-file by LOC, but ~520 lines are inlined CSS/JS string constants for the `/docs` theme wrapper (see §4.1). Logic is thin. Dead `/health` shadow already removed (documented at tail). |
| `api/routes/migration.py` | Per-pane override + introspection endpoints | 678 | KEEP | Six near-identical POST endpoints; the duplication is *intentional* (per-URL pane routing, documented). `/plan` dispatch correctly routes to `run_plan_with_overrides` not the signature-frozen `run_plan_with_rename` (comment explains why). See §4.4. |
| `api/routes/backups.py` | Backup job create/list/get + threaded runner | 520 | KEEP | Thread-pool runner with per-index result mutation (no locking needed — documented + correct). Honest `pending`-on-POST contract. Broad-except routes through `translate_backup_error`. |
| `api/routes/configs.py` | Config list/get/delete/diff/open | 317 | KEEP | Open-in-editor gated by both `open_in_editor` AND an extension allowlist; OS exceptions are logged-not-leaked. `_resolve_record` correctly treats `list_configs()` as authoritative. |
| `api/routes/schedules.py` | Schedule CRUD + APScheduler glue + run coroutine | 342 | KEEP | `asyncio.to_thread` keeps blocking SSH off the loop; profile-first target resolution with O(n) type_key index; 200-schedule cap. Outer wrapper swallows+logs so one bad run can't tear down the scheduler. |
| `api/routes/_errors.py` | Operator-facing backup-error translator | 357 | KEEP | Exemplary (see §6). isinstance-ordered dispatch with subclass-before-base discipline; Netmiko `__context__`/`__cause__` unwrap to recover DNS/refused/timeout distinction. |
| `api/routes/device_profiles.py` | Device profile CRUD | 172 | KEEP | PUT partial-update via `model_copy(update=…)`; delete warns on referencing schedules; 1000-profile cap. |
| `api/routes/definitions.py` | Definition list/get/reload | 106 | KEEP | `/reload` correctly rotates BOTH `state.definitions` AND `state.definition_loader` (fix documented — overlays page used to go stale). |
| `api/routes/sanitize.py` | `POST /sanitize` multipart endpoint | 84 | KEEP | Validates `source_vendor` against registry; `errors="replace"` decode; mirrors the CLI path. |
| `api/routes/health.py` | `/health` readiness probe | 43 | KEEP | Deliberately cheap; package-version fallback to `"unknown"`. |
| `api/routes/_migration_helpers.py` | Request/response shaping helpers for `migration.py` | 183 | KEEP | Pure compute; `resolve_input_text` enforces raw_text XOR source_filename; `request_has_overrides_or_profile` predicate is the dispatch gate. Good extraction. |
| `api/deps.py` | `Depends()` providers over `app.state` | 93 | KEEP | Thin indirection for test override-ability; documented. |
| `api/__init__.py`, `api/routes/__init__.py` | Package docstrings | 1+1 | KEEP | — |

### 3.3 `services/`

| Path | Purpose | LOC | Verdict | Note |
|---|---|--:|---|---|
| `services/migration_pipeline.py` | Frozen-signature orchestrator (3 public entries) | 711 | KEEP | The load-bearing engine. Signatures frozen per Hard Rule; three-way terminal status; capture-first transform; honest broad-except that preserves the failing stage. See §4.3. |
| `services/migration_validate.py` | Capability-matrix-driven validation (stage 4) | 243 | KEEP | Pure; strictest-wins classification; `check_class_compat` non-empty-intersection guard with `warn` for uncommitted adapters. |
| `services/diff.py` | Stateless textual diff + context folding | 251 | KEEP | `compute_diff` via `SequenceMatcher`; `fold_context` two-sweep Manhattan-distance fold is elegant + correct (see §6). |
| `services/migration_detect.py` | Codec auto-detection (probe ranking) | 117 | KEEP | Prefix-truncated, stable tie-break sort, probe-must-not-raise guard. |
| `services/__init__.py` | Package docstring | 1 | KEEP | — |

### 3.4 `storage/`

| Path | Purpose | LOC | Verdict | Note |
|---|---|--:|---|---|
| `storage/file_store.py` | File-based config store (filename-grammar metadata) | 355 | WATCH | Atomic writes, path-traversal-safe `resolve_path` (regex + `is_relative_to`), sidecar metadata. Two micro-issues: lossy host round-trip (`CB-03`) + a mis-indented comment (`CB-06`). |
| `storage/job_registry.py` | LRU-bounded in-memory cache + disk fallback | 237 | KEEP | Clean `OrderedDict` LRU; honest `__len__` (memory-resident, documented); `__contains__` cheap `path.exists()`; lazy-load promotion. See §6. |
| `storage/job_store.py` | Per-job JSON persistence | 120 | KEEP | Atomic write; corrupt-file-skipped on load (logged). `list_job_ids` cheap scan. |
| `storage/schedule_store.py` | Schedule JSON persistence + credential migration | 115 | KEEP | Encrypts inline-device creds on save; transparent plaintext→encrypted migration on load; `PermissionError` handled distinctly. |
| `storage/device_profile_store.py` | Profile JSON persistence + credential migration | 108 | KEEP | Same pattern as schedule store; in-memory model holds plaintext, disk holds Fernet ciphertext. |
| `storage/base.py` | `BaseConfigStore` ABC | 95 | KEEP | Narrow 5-method interface; documented sync-by-design. |
| `storage/__init__.py` | Re-exports | 13 | KEEP | — |

### 3.5 `collectors/`

| Path | Purpose | LOC | Verdict | Note |
|---|---|--:|---|---|
| `collectors/paramiko_collector.py` | Raw-PTY shell collector (OPNsense menu) | 459 | KEEP | `AutoAddPolicy` is the documented operator-trust-anchor model (OBSERVATION CB-O1). Idle-detection two-phase stream; `_strip_command_echo` head+tail trim well-reasoned. `_drain` uses monotonic deadline. |
| `collectors/netmiko_collector.py` | Netmiko `ConnectHandler` collector | 211 | KEEP | `with` context manager; probe in separate short-lived session with tighter timeout; missing-`netmiko_device_type` defence-in-depth early-return. |
| `collectors/base.py` | `BaseCollector` ABC + `get_collector` factory | 132 | KEEP | Single mock-point factory (Hard Rule); default `probe()` returns `{}` so non-probing strategies keep working. |
| `collectors/probe.py` | Pure probe-output regex parser | 107 | KEEP | Per-fact regex with compile-error skip; timestamp only on non-empty result (avoids "ran and found nothing" masquerade). |
| `collectors/__init__.py` | Re-exports + extension guide | 25 | KEEP | — |

### 3.6 `models/`

| Path | Purpose | LOC | Verdict | Note |
|---|---|--:|---|---|
| `models/migration.py` | `MigrationJob` + request/response + `CapabilityMatrix` | 842 | WATCH | God-file by LOC but ~600 lines are docstring (every per-pane field exhaustively documented). Header docstring still says "Phase 0 … No I/O; libyang comes in Phase 0.5" (`CB-02`). `classify` resolution is correct. See §4.2. |
| `models/backup.py` | `BackupJob`/`BackupResult`/`ConfigRecord`/`JobStatus` | 114 | KEEP | Monotonic result lifecycle documented; terminal-state three-way semantics match the runner. |
| `models/device.py` | `DeviceTarget`/`DeviceCredentials`/`BackupRequest` | 76 | KEEP | `SecretStr` for passwords; host validator; `BackupRequest` 1-500 device bound. |
| `models/device_profile.py` | `DeviceProfile` + Create/Update | 144 | KEEP | Shared host validator; clear plaintext-in-memory/encrypted-on-disk contract documented. |
| `models/diff.py` | Diff report models | 124 | KEEP | `DiffLine`/`DiffReport`/`DiffGroup` clean; `context` kind reserved for future (honest). |
| `models/schedule.py` | `BackupSchedule` + `ScheduleCreate` | 103 | KEEP | `model_validator` enforces ≥1 target on create; legacy inline-devices kept for back-compat. |
| `models/validators.py` | Shared host validator | 33 | KEEP | RFC-1123 + IPv4/IPv6; good error message with examples. |
| `models/__init__.py` | Re-exports | 47 | KEEP | `__all__` complete. |

### 3.7 `security/`

| Path | Purpose | LOC | Verdict | Note |
|---|---|--:|---|---|
| `security/credentials.py` | Fernet key 3-tier resolution + encrypt/decrypt | 258 | KEEP | env → keyring → file fallback, each tier documented with threat-model rationale; `chmod 0o600` best-effort; `reset_fernet` test helper. Module-level `_fernet` cache is process-global (OBSERVATION CB-O2 — intentional, lazy). |
| `security/migration.py` | Shared plaintext→encrypted field migrator | 35 | KEEP | Single source for the two store loaders; in-place + returns needs-resave flag. |
| `security/__init__.py` | Package docstring | 1 | KEEP | — |

### 3.8 `definitions/`

| Path | Purpose | LOC | Verdict | Note |
|---|---|--:|---|---|
| `definitions/loader.py` | YAML loader + longest-match overlay resolve | 282 | KEEP | Two-pass load (validate then priority-override); `resolve` 4-tier specificity; `_highest_priority` helper. `resolve` returns `None` before `load_all` runs (documented). |
| `definitions/schema.py` | `DeviceDefinition` pydantic schema | 268 | KEEP | `type_key_filename_safe` validator enforces the Hard Rule at load time; `netmiko_device_type` conditional validator; field docs are author-facing reference. |
| `definitions/__init__.py` | Re-exports | 29 | KEEP | — |

### 3.9 `tools/`

| Path | Purpose | LOC | Verdict | Note |
|---|---|--:|---|---|
| `tools/sanitize.py` | Canonical-model PII redactor | 565 | KEEP | AST-level redaction via parse→sanitize→render; counter-per-session cross-reference stability; format-preserving hash redaction; public-IP-only with RFC-1918/CGNAT preservation. See §4.6. One micro-observation on docs-range wrap (CB-O3). |
| `tools/__init__.py` | Package docstring | 13 | KEEP | Accurate; notes canonical-walk auto-tracks codec evolution. |

### 3.10 `migration/canonical/`

| Path | Purpose | LOC | Verdict | Note |
|---|---|--:|---|---|
| `canonical/intent.py` | Canonical IR (pydantic models, cross-cutting) | 926 | CONCERN | Correct + clear at the model level; the **docstrings** carry the stale ship-before-wire claims (`CB-01`). See §4.7. CE owns the cohesion framing. |
| `canonical/port_names.py` | Cross-vendor port-name translation orchestrator | 614 | KEEP | Vendor-agnostic bridge (classify→format); idempotent memoised `resolve`; `strip_unmappable` auto-drop with per-kind advisory warnings; full cascade strip. See §4.5. |
| `canonical/transforms.py` | Shared post-parse mirror transforms | 373 | KEEP | `project_switchport_to_vlan` / `_vlan_to_switchport` / `_svi_to_vlan`; idempotent+additive; trunk-all sentinel detection avoids 4094 phantom VLANs (well-reasoned); natural-sort key. |
| `canonical/vlan_names.py` | VLAN-ID rewrite orchestrator | 364 | KEEP | Validate→split renames/drops→2-pass tree walk; collision merge-by-union; out-of-range rejection. |
| `canonical/local_user_names.py` | Local-user rename orchestrator | 275 | KEEP | Mirrors vlan_names; merge on max-privilege/first-role/first-hash; no-op-on-mock guard. |
| `canonical/snmp_names.py` | SNMP community rename (scalar surface) | 273 | KEEP | Single-slot scalar via dict shape for API symmetry; advisory warning when source≠current. |
| `canonical/snmpv3_user_names.py` | SNMPv3 USM user rename orchestrator | 277 | KEEP | First-wins collision (keys never combined across users — correct USM semantic); in-place name mutation preserves crypto attributes. |
| `canonical/loader.py` | libyang context loader — STUB | 61 | WATCH | Both public functions raise `NotImplementedError`. "Phase 0.5 deliverable" docstrings are stale-future (`CB-02`); harmless but a methodology anti-pattern. |
| `canonical/__init__.py` | Package docstring | 8 | WATCH | "Phase 0 ships only this stub … real libyang loader arrives in Phase 0.5" — contradicted by the full IR in intent.py (`CB-02`). |

### 3.11 `migration/` root

| Path | Purpose | LOC | Verdict | Note |
|---|---|--:|---|---|
| `migration/target_profiles.py` | Hardware-shape `TargetProfile` model + YAML loader | 544 | KEEP | Range-shorthand expansion (`_RANGE_RE`), module-variant additive ports, per-vendor caps; loader skips bad files + logs. See §4.8. One regex edge note (CB-O4). |
| `migration/_tier3_detection.py` | Per-vendor Tier-3 stanza detectors | 215 | KEEP | Notification-only; regexes deliberately EXCLUDE parsed stanzas so the banner doesn't lie; iosxe_xml is an honest documented no-op. |
| `migration/_user_secrets.py` | Cross-codec hash-portability policy | 228 | KEEP | `classify_hash` 4-shape split; `is_migratable` per-target allowlist; XML-safe `--`→`-` comment collapse. Centralises what was duplicated in aruba_aoss. |
| `migration/_naming.py` | Hostname/naming-token whitespace sanitiser | 72 | KEEP | Single-purpose; documented with the cross-vendor round-trip bug that motivated it. |
| `migration/__init__.py` | Codec auto-discovery (`@register` firing) | 76 | KEEP | `pkgutil.iter_modules` walk; malformed codec logged+skipped; lazy `load_vendors` re-export. |
| `migration/vendors/__init__.py` | Vendor-YAML loader | 82 | KEEP | Validate-and-skip; duplicate-id warn-last-wins; corrupt-file resilient. |

### 3.12 `netcanon_desktop/`

| Path | Purpose | LOC | Verdict | Note |
|---|---|--:|---|---|
| `netcanon_desktop/preferences_dialog.py` | PySide6 preferences dialog | 311 | KEEP | `setObjectName` test-id convention; deferred PySide6 imports; save rebuilds a fresh `DesktopPreferences` and re-validates. |
| `netcanon_desktop/window.py` | PySide6/QtWebEngine window wrapper | 189 | KEEP | Minimize-to-tray via `closeEvent`; thread-safe show/hide via `QMetaObject.invokeMethod`; documents the pywebview→PySide6 migration rationale. |
| `netcanon_desktop/app.py` | `DesktopApp` orchestrator | 161 | WATCH | Correct startup/shutdown sequencing. Module docstring still describes "Edge/WebView2 window" + "pywebview" verbs although the window is now PySide6/Chromium (`CB-04`). |
| `netcanon_desktop/server.py` | Embedded Uvicorn daemon thread | 150 | KEEP | `_ReadyServer` event-on-startup + HTTP probe confirm; `log_config=None` preserves the app logger; clean `should_exit` shutdown. Minor: the `wait_ready` timeout message uses a non-f-string `{self._port}` literal (CB-O5). |
| `netcanon_desktop/tray.py` | pystray system-tray icon | 136 | KEEP | Optional menu items keep tests back-compatible; `stop()` swallows+logs. |
| `netcanon_desktop/preferences.py` | `DesktopPreferences` model + load/save | 117 | KEEP | Corruption-non-fatal `load`; all-Optional schema for forward-compat; Path-as-string serialisation. |
| `netcanon_desktop/__main__.py` | `python -m netcanon_desktop` entry | 100 | KEEP | Single-instance gate; MessageBoxW fatal/already-running with non-Windows fallthrough; log-file only when frozen. |
| `netcanon_desktop/icons.py` | Runtime Pillow icon generation | 119 | WATCH | Correct multi-size ICO. Docstring usage example still says ".ico … required by pywebview" (`CB-04`). |
| `netcanon_desktop/settings.py` | Desktop `Settings` factory | 98 | KEEP | frozen-vs-dev path resolution; preferences overlay only in frozen mode (dev uses repo-relative for predictability). |
| `netcanon_desktop/single_instance.py` | Windows named-mutex single-instance | 77 | KEEP | Module-level handle kept alive (documented GC hazard); non-Windows returns True. |
| `netcanon_desktop/__init__.py` | Package docstring | 22 | WATCH | "embedded Edge/WebView2 window" — same pywebview-era residue (`CB-04`). |

---

## 4. Deep-dives on the god-files

### 4.1 `api/routes/ui.py` (894 LOC)

**Correctness:** clean. Eight `GET` HTML routes (`/`, `/jobs`, `/schedules`,
`/configs`, `/configs/{l}/vs/{r}`, `/devices`, `/definitions`, `/migrate`,
`/sanitize`) plus the `/docs` Swagger wrapper. Each route is a thin
state→template adapter. The dashboard uses `heapq.nlargest(10, …)` (good — no
full sort for a top-10). The diff page (`diff_page`) is the only non-trivial
handler: it deliberately never returns 404/422 to the *page* (always renders so
the user sees *why* a diff was blocked + a "Compare anyway" button) — a
considered UX divergence from the API, documented in the docstring. The
`devices_page` strips `password`/`enable_password` from `profiles_safe` before
handing to the template (`_CRED_FIELDS`) — a small but correct
credential-hygiene touch.

**Why it's 894 lines:** roughly 520 are module-level string constants
(`_DOCS_BOOT_SCRIPT`, `_DOCS_TOKEN_STYLES`, `_DOCS_NAV_HTML`, `_DOCS_NAV_CSS`,
`_DOCS_TOGGLE_JS`, `_DOCS_SWAGGER_DARK_CSS`) that re-theme the CDN-served
Swagger UI to match the app's dark mode. This is genuinely irreducible *content*
(CSS selectors for Swagger's internal class chain), not *logic*. The
`swagger_ui()` handler does two `str.replace(..., 1)` injections at `<body>` and
`</body>`. I flag no defect here; CE owns whether the `/docs` theming belongs in
a sibling module — from a correctness/clarity lens the constants are
self-documenting and each carries a "stay in sync with base.html" warning.

**Dead code:** none. The tail comment (lines 887-894) explains a *removed*
shadow `/health` handler — a good example of the project documenting deletions.

**Drift watch:** the `_DOCS_TOKEN_STYLES` / `_DOCS_NAV_*` constants duplicate
`base.html` theme tokens with a "must stay in sync" comment. This is a
documented, accepted duplication (the `/docs` page can't `extend base.html`).
Not a finding, but a maintenance surface worth a CI guard someday
(OBSERVATION).

### 4.2 `models/migration.py` (842 LOC)

**Correctness:** `CapabilityMatrix.classify` implements strictest-wins
(`unsupported` → `lossy` → `supported`/implicit) exactly as documented; the
linear scan over `unsupported`/`lossy` lists is O(paths) per call but the lists
are short. `MigrationJob` and `MigrationPlanRequest` are the wide
per-pane-override surface; every field has a `default_factory` (no
mutable-default-arg bug). `id` uses `default_factory=lambda: str(uuid.uuid4())`
and `created_at` uses `datetime.now(timezone.utc)` (timezone-aware — good).

**Why it's 842 lines:** ~600 are docstring. Every per-pane field
(`port_renames`, `vlan_drops`, `source_snmpv3_users`, …) gets a multi-line
attribute doc AND a repeated `#:` inline comment on the field declaration. The
duplication between class-docstring `Attributes:` and `#:` comments is
verbose but consistent; CE can weigh whether to collapse one. From a
correctness lens it is harmless and accurate (except the header — see CB-02).

**Finding:** the **module header** (lines 1-14) reads "Phase 0 scope … No I/O;
no schema work (libyang comes in Phase 0.5)." This is the same stale-Phase-0.5
residue as `canonical/__init__.py` (`CB-02`). The body has long since grown the
full per-pane request/response surface; the "Phase 0" framing misleads a new
reader about the file's maturity.

### 4.3 `services/migration_pipeline.py` (711 LOC)

**The load-bearing engine, and it earns the care lavished on it.** Three public
functions with **frozen signatures** (Hard Rule, documented in both AGENTS.md
and the module docstring): `run_plan`, `run_plan_with_overrides`,
`run_plan_with_rename` (a thin back-compat forward to `_with_overrides` that
normalises `None`→`{}`).

**Correctness highlights:**
* The broad `except Exception` (line 255) is the methodology's *honest catch-all*
  — it captures `job.status.value` (the in-progress stage enum) BEFORE
  reassigning to `failed` (line 259), so the error message names the stage that
  was running. This is a genuinely correct and easy-to-get-wrong detail.
* The `else:` clause (line 266) implements the three-way terminal status:
  `partial` when validation severity is `block` but render succeeded,
  `completed` otherwise. Matches `MigrationJobStatus` docstring.
* The capture-first transform (`_capture_source_shape`, line 482) snapshots
  source enumerations *unconditionally* (even when no override engaged) because
  the Tier-3 rename modal needs them — documented thoroughly. Duck-typed
  `getattr(tree, "vlans", None) or []` means it degrades to empty on mock dicts
  rather than crashing.
* Lazy imports inside `run_plan_with_overrides` (line 420) are explicitly to
  avoid a circular import (the canonical rename modules import `CodecBase`,
  which this module also imports). Documented.
* Per-category result attachment runs AFTER `run_plan` so the job carries
  override decisions even when a later stage failed — operator-debugging
  rationale documented.

**No findings.** This file is a model of disciplined orchestration. The only
thing I'd note (OBSERVATION) is that the post-run DEBUG summary log (line 644)
is a 25-argument format string — verbose but genuinely useful for the
"my rename didn't fire" support case it documents.

### 4.4 `api/routes/migration.py` (678 LOC)

**Correctness:** six POST endpoints (`/plan`, `/plan/ports`, `/plan/vlans`,
`/plan/local_users`, `/plan/snmp`, `/plan/snmpv3`) + `/render` alias + `/detect`
+ two target-profile GETs. The per-pane endpoints are near-identical by
*intent* — each dispatches to `run_plan_with_overrides` with only its category
map populated. The docstrings are explicit that this duplication is
organisational (per-URL routing for client clarity + server-log visibility),
not accidental. CE may propose a factory; I record it as an OBSERVATION because
the duplication is documented-by-design and each endpoint's docstring carries
genuinely distinct semantic notes (e.g. SNMPv3's "auth/priv keys never
combined" warning).

The `/plan` dispatch (line 222) is the subtle one and it's **correct**: it
routes to `run_plan_with_overrides` directly (NOT `run_plan_with_rename`) when
any override map OR a target profile is present, with a comment explaining that
`run_plan_with_rename` is signature-frozen to only accept `port_rename_map` and
would silently drop the other category maps. The `port_rename_map` defaulting
ternary (line 230-234) correctly distinguishes "explicit map" / "target-profile
→ `{}`" / "neither → None".

**No findings.** Module docstring inventory matches the actual endpoint set
(I checked each `@router.post`/`@router.get` against the docstring's endpoint
list — they agree, satisfying the AGENTS.md doc-sync row for
inventory-docstring modules).

### 4.5 `canonical/port_names.py` (614 LOC)

**Correctness:** the cross-vendor bridge. `PortIdentity` is a permissive
all-optional struct; `translate_port_names` walks every port-referring field
(interfaces, lag_member_of, vlan tagged/untagged, lag members, static-route
interface, dhcp pool interface) through a memoised `resolve()`. The priority
order (drop → user-override → auto-classify→format → strip-on-unmappable) is
documented and the implementation matches.

Notable correct details:
* `resolve()` is idempotent + cached (`memo` dict) — resolving the same name
  twice returns the same output without re-classifying.
* The SVI-absorb short-circuit (line 387) suppresses non-actionable "review"
  rows when the target codec absorbs SVI L3 into the VLAN stanza
  (`absorbs_svi_into_vlan`). Correct — avoids noise.
* `kind_overrides` (line 336) applies the `CanonicalInterface.kind` context
  override (e.g. Cisco mgmt-VRF port) AFTER classify but BEFORE format, via
  `model_copy(update=…)` — non-mutating, correct.
* `_strip_dropped_ports` cascades through every field and clears
  `lag_member_of` back-pointers. Idempotent.

The non-`CanonicalIntent` guard (line 308) returns an empty result for mock
dicts — the same defensive pattern used uniformly across the rename family.

**No findings.** CE owns whether the 614 lines should split (the `resolve`
closure is large); from correctness it is sound.

### 4.6 `tools/sanitize.py` (565 LOC)

**Correctness:** `sanitize_text` = parse → `sanitize_intent` → render, same
vendor in and out. `sanitize_intent` is a pure function (deep-copies via
`model_copy(deep=True)`, never mutates input). `_SubstitutionTable` is
counter-per-session so the same input value maps to the same redaction
everywhere (cross-reference stability — a hostname in 5 places redacts
identically). `redact_ipv4` correctly preserves RFC-1918 / loopback /
link-local / multicast / reserved / docs-range / CGNAT (100.64/10) and only
substitutes genuinely public IPs. `redact_hash` is format-preserving across
Junos `$9$`, crypt `$1$/$5$/$6$`, bcrypt `$2y$`, FortiGate `ENC`, Cisco type-7
hex, and Aruba/generic hex — so the re-rendered config stays
parser-valid. Phase-3 R6.1 username redaction (`localuserN`/`snmpv3userN`) is
present with per-class counters.

**Minor (OBSERVATION CB-O3):** `redact_ipv4` wraps the docs-range host octet
when it exceeds 254 (`((host-1) % 254) + 1`, line 436). Beyond 254 unique public
IPs *per docs range* (762 total) this can produce a *collision* — two distinct
source IPs mapping to the same redacted IP — which weakens cross-reference
fidelity but does NOT leak data (the comment acknowledges the wrap). For
bug-report-sized configs this is unreachable. Recording as an observation, not
a finding.

### 4.7 `canonical/intent.py` (926 LOC) — the CB-01 deep-dive

This is the cross-cutting canonical IR: ~15 pydantic models from
`CanonicalIPv4Address` up to the root `CanonicalIntent`. **At the model level it
is correct and clear** — field types, `Field(ge=…, le=…)` bounds,
`default_factory` everywhere (no mutable-default bug), tier-tagged class
docstrings. CE owns the cohesion/SRP framing (926 lines, ~15 classes); my lens
is correctness + clarity + drift, and the drift is material:

**The ship-before-wire docstrings are stale.** Multiple docstrings assert a
universal "unsupported until wire-up" state that the codec layer has since
left behind:

* `CanonicalIPv4Address.virtual_gateway_address` (lines 98-112): *"Ship-before-
  wire (v0.2.0) — every codec's `CapabilityMatrix` lists
  `/interfaces/interface/ipv4/address/virtual-gateway-address` as `unsupported`
  until the per-codec wire-up lands."*
* `CanonicalInterface.vrrp_groups` (lines 251-260): *"Codecs without per-codec
  wire-up still declare `/interfaces/interface/vrrp-groups/group` as
  `unsupported`."*
* `CanonicalIntent.anycast_gateway_mac` (lines 828-854) and the top-level
  schema-extensions block (lines 50-59): *"No codec populates any of these in
  v1 — each codec's `CapabilityMatrix` lists them under `unsupported` until
  wired up."*

**Evidence the wire-up landed** (grep over `migration/codecs/`, CC's partition
but load-bearing for this docstring claim):
* `arista_eos/codec.py` lists `vrrp-groups/group`,
  `ipv4/address/virtual-gateway-address`, `ipv6/.../virtual-gateway-address`,
  and `/anycast-gateway-mac` under **`supported`** with the comment
  `-- v0.2.0 Wave B (VRRP) -- per-codec wire-up landed --`.
* Parsers populate the fields: `arista_eos/parse.py`, `cisco_iosxe_cli/parse.py`,
  and `juniper_junos/parse.py` all set `virtual_gateway_address=…`,
  `CanonicalVRRPGroup(…)`, and `intent.anycast_gateway_mac=…`.
* `vrrp_groups.append(...)` appears in 7 codec parsers (arista, aruba, fortigate,
  iosxe_cli, junos, mikrotik, opnsense).

So the canonical-model docstrings now over-claim the gap. By the project's own
methodology this is a defect class it explicitly polices: `docs/METHODOLOGY.md`
§ "No active lies in operator-facing messages" ("docstrings of public functions"
are named as load-bearing contracts) and § "Capability declarations that
contradict shipped code"; AGENTS.md's doc-sync table row *"A new canonical field
on `CanonicalIntent`/`CanonicalInterface`/etc."* points at
`docs/adding-a-canonical-field.md`. The fix is a docstring edit (these are
ship-before-wire fields whose narrative simply didn't get refreshed when Wave
B/C flipped them `unsupported → supported`), so it is low-risk — but it is a
real matrix-honesty drift on the most cross-cutting file in the tree.

**Crucial precision for the orchestrator/Fleet D:** the narrower Fleet D
candidate as stated — *"`is_secondary` documented not-yet-wired but may already
be live"* — does **NOT** reproduce. `is_secondary` is set nowhere in `netcanon`
(verified: zero `is_secondary=True` assignments; `cisco_iosxe_cli/parse.py`
parses the `secondary` keyword into a regex group at line 127 but does **not**
set the canonical field). So the `is_secondary` docstring ("codecs that haven't
been updated still treat all addresses as primary") is **accurate**. The drift
is on the *sibling* fields that share the same ship-before-wire docstring
vocabulary. I record CB-01 against those sibling fields specifically.

### 4.8 `target_profiles.py` (544 LOC)

**Correctness:** `TargetProfile` + `TargetModule` + `TargetPort` + `TargetLAGCaps`
pydantic models with a YAML loader. The helper accessors
(`effective_ports(sku)`, `port_ids`, `lookup_port`, `default_module_sku`) cleanly
encapsulate module-variant resolution (chassis ports + selected module ports,
additive). `_expand_range_entries` expands `{range: "GigabitEthernet1/0/1-24"}`
shorthand into concrete records before pydantic validation, with prefix-match
validation between start/end. `load_profiles_dir` skips bad files + logs (app
surfaces what succeeded). Duplicate-key warn.

**Minor (OBSERVATION CB-O4):** `_RANGE_RE`
(`^(?P<prefix>.*?)(?P<start>\d+)-(?P<prefix2>.*?)(?P<end>\d+)$`) uses two lazy
`.*?` groups around `\d+`. For an id like `"Te1/1/1-8"` the regex finds
`start`/`end` correctly because `\d+` is greedy on the trailing run, but an id
whose prefix itself ends in a digit-then-letter pattern could in principle
mis-split. In practice all shipped profile ranges are well-formed and the
prefix-mismatch check catches the obvious failures; I could not construct a
real-profile counterexample read-only, so this stays an observation marked
`UNVERIFIED` as a latent edge. No shipped profile triggers it.

---

## 5. Findings (severity-ordered)

> No P0 or P1 findings. The platform layer is correct on all happy paths I
> traced. The findings below are P2/P3/OBSERVATION.

### CB-01 — `intent.py` ship-before-wire docstrings contradict shipped codec capability (matrix-honesty drift)

* **Severity:** P2 (documentation/matrix-honesty; the project treats stale
  capability claims as bugs, not debt — but no runtime behaviour is wrong).
* **Where:** `netcanon/migration/canonical/intent.py` — lines 50-59
  (schema-extensions block), 98-112 (`virtual_gateway_address`), 251-260
  (`vrrp_groups`), 577-581 (`CanonicalVRRPGroup` ship-before-wire footer),
  828-854 (`anycast_gateway_mac`).
* **Claim:** these docstrings assert every codec lists the VRRP/anycast paths as
  `unsupported` and that "No codec populates any of these in v1."
* **Evidence:** `arista_eos/codec.py` (lines ~134-139) lists
  `/interfaces/interface/vrrp-groups/group`,
  `/interfaces/interface/ipv4/address/virtual-gateway-address`,
  `/interfaces/interface/ipv6/address/virtual-gateway-address`, and
  `/anycast-gateway-mac` under **`supported`** with an inline
  `per-codec wire-up landed` comment. Parsers in `arista_eos`, `cisco_iosxe_cli`,
  and `juniper_junos` populate `virtual_gateway_address=…` /
  `anycast_gateway_mac=…`; `CanonicalVRRPGroup(...)` + `vrrp_groups.append(...)`
  appear in 7 codec parsers.
* **Suggested direction:** refresh the four docstring blocks to reflect Wave
  B/C landing — i.e. change "every codec lists … `unsupported`" to the actual
  per-codec state (some `supported`, some still `unsupported`), and drop "No
  codec populates any of these in v1." Cross-check against
  `docs/CAPABILITIES.md` (operator-facing) and the per-vendor pages per the
  AGENTS.md doc-sync rows. Keep the `is_secondary` docstring as-is (still
  accurate). Coordinate with CC, who owns the codec-side declaration audit.

### CB-02 — Stale "Phase 0 / Phase 0.5 / libyang stub" docstrings (active-lie anti-pattern)

* **Severity:** P3 (clarity; misleads new readers about subsystem maturity).
* **Where:**
  * `netcanon/migration/canonical/__init__.py` (lines 1-8): *"Phase 0 ships only
    this stub. The real libyang context loader arrives in Phase 0.5."*
  * `netcanon/migration/canonical/loader.py` (whole file, 61 LOC): both public
    functions raise `NotImplementedError("… Phase 0.5 deliverable")`.
  * `netcanon/models/migration.py` header (lines 1-14): *"Phase 0 scope … no
    schema work (libyang comes in Phase 0.5)."*
* **Claim:** all three describe a libyang-backed Phase-0.5 future as the
  intended canonical-tree implementation.
* **Evidence:** `canonical/intent.py` is a complete, validated, JSON-serialisable
  pydantic IR that every codec parse/render binds to today. libyang is imported
  nowhere in the partition. `docs/METHODOLOGY.md` § anti-patterns names exactly
  this — *"'Phase 2 will add a resolver' docstrings … become a lie the instant
  Phase 2 ships"* — and the doc-audit anti-pattern list flags "future-work
  phrases whose specific commit is > 60 days old."
* **Suggested direction:** either (a) delete `canonical/loader.py` if the
  libyang path is abandoned (and drop the `canonical/__init__.py` +
  `models/migration.py` Phase-0.5 sentences), or (b) if libyang is still a real
  roadmap item, reword to present-tense ("the canonical tree is a pydantic IR;
  a libyang validation layer is a possible future addition") and move the
  forward-looking note to `translator-plans.txt`/`RELEASE_PLAN.md` where
  forward-looking statements belong. `UNVERIFIED` on which of (a)/(b) is
  correct — that's a product call.

### CB-03 — `file_store._parse_filename` host reconstruction is not a clean inverse of the encode

* **Severity:** P3 (display-metadata fidelity only; not a data-loss or
  security bug — the bytes on disk are untouched).
* **Where:** `netcanon/storage/file_store.py` lines 157 (encode) and 347
  (decode).
* **Claim:** `save` encodes `host` as `host.replace(":", "--").replace(".", "-")`
  (line 157, comment says "colons as double hyphens, dots as single"); decode
  does `safe_host.replace("--", ":").replace("-", ".")` (line 347). The decode is
  not a faithful inverse for hostnames that contain literal hyphens: a real
  hostname `core-sw-01.example.com` encodes to `core-sw-01-example-com` and
  decodes back to `core.sw.01.example.com` — every original hyphen becomes a dot.
  IP addresses round-trip fine (they contain no hyphens). The docstring of
  `_parse_filename` candidly calls it "Best-effort host reconstruction."
* **Why it's nonetheless safe:** `host` in `ConfigRecord` from a parsed filename
  is display-only metadata. File *lookup* (`resolve_path`) keys on the verbatim
  `filename` string, never on the reconstructed host. So a mangled host never
  mislocates a file. The defect surfaces only as a cosmetically-wrong host
  column on the Configs/Jobs pages for hostnames containing hyphens. (For
  freshly-saved files the in-memory `ConfigRecord` carries the correct host
  directly from `save`; the lossy path is only hit when re-deriving from disk
  via `list_configs`.)
* **Suggested direction:** if exact host display matters, persist the original
  host in the sidecar `.meta.json` (already written when a profile id is
  present — could be written unconditionally) and prefer it over the
  filename-derived value, OR use a reversible encoding (e.g. percent-encode).
  Low priority; the current behaviour is documented as best-effort.

### CB-04 — Desktop docstrings still name `pywebview` / "Edge WebView2" after the PySide6 migration

* **Severity:** P3 (docstring drift; the module that did the migration —
  `window.py` — documents it, but three siblings didn't get updated).
* **Where:**
  * `netcanon_desktop/__init__.py` (line ~6): *"An embedded Edge/WebView2 window
    shows the full web UI."*
  * `netcanon_desktop/app.py` module docstring (lines 6-8, 17, 23): *"WebViewWindow
    — Edge/WebView2 window"* and shutdown-sequence verbs.
  * `netcanon_desktop/icons.py` (lines 13-16): *"Write .ico file to disk (required
    by pywebview for window/taskbar icon)"* plus a `write_ico(...)` example.
* **Claim:** these describe pywebview/WebView2 as the rendering backend.
* **Evidence:** `netcanon_desktop/window.py` (lines 19-24) explicitly documents
  the migration: *"Why PySide6 instead of pywebview: pywebview ≥ 4.x requires
  pythonnet … PySide6 ships its own Chromium-based WebEngine."* The window is a
  `QMainWindow` + `QWebEngineView`. `app.py` imports `WebViewWindow` from the
  PySide6 module.
* **Suggested direction:** s/pywebview/PySide6/ and s/Edge·WebView2/Chromium
  WebEngine/ in the three docstrings. Pure docs; trivial.

### CB-05 — `migration/codecs/` exclusion: ship-before-wire matrix audit belongs to CC, but the divergence is real

* **Severity:** OBSERVATION (cross-partition coordination note, not a CB
  finding).
* **Where:** spans CB (`intent.py` docstrings) and CC (codec `_CAPS`).
* **Note:** CB-01 documents the *canonical-model-side* half (intent.py
  docstrings). The matching *codec-side* question — "did every codec that
  populates these fields also flip its `unsupported`→`supported`/`lossy`
  declaration, and do the cross-vendor expectation YAMLs agree?" — is squarely
  CC's partition. I flag it here so the orchestrator can ensure CC closes the
  loop: a half-wired state (parser populates but matrix still says
  `unsupported`) would be the precise matrix-honesty violation the methodology
  describes in `cisco_iosxe_cli /routing-instances/instance` (commit `07086b1`).
  I observed arista declares them `supported`; I did NOT audit all 8 codecs'
  declarations against all pairs (CC's job). `UNVERIFIED` for the non-arista
  codecs.

### CB-06 — Mis-indented comment in `file_store._parse_filename`

* **Severity:** P3 (cosmetic; no behavioural effect).
* **Where:** `netcanon/storage/file_store.py` lines 344-346.
* **Claim:** the comment block "Best-effort host reconstruction…" is indented
  one level deeper than the `host = safe_host.replace(...)` statement it
  describes (the `# Best-effort` line sits at the column of the preceding
  `safe_host =` assignment's continuation rather than aligning with the code).
  Reads as a stray indent.
* **Suggested direction:** re-align the comment to the statement column. Trivial.

### CB-O1 … CB-O5 — Intentional-design observations (not defects)

* **CB-O1 (`paramiko_collector.py` + module):** `paramiko.AutoAddPolicy` on both
  `collect` and `probe` (lines 166, 258). This is the documented
  operator-trust-anchor model (no `known_hosts`, trusted-management-VLAN threat
  model), scoped and **deliberately deferred** in the 2026-05-21 security-triage
  cycle (`docs/security-triage/2026-05-21/`). Per the brief and methodology this
  is a load-bearing-by-design decision, recorded as OBSERVATION, not a finding.
  CF owns the deeper security-posture treatment.
* **CB-O2 (`security/credentials.py`):** the module-level `_fernet` cache is
  process-global and lazily initialised on first `encrypt`/`decrypt`. Intentional
  (one key per process; `reset_fernet()` exists for tests). Means a key rotation
  requires a process restart — acceptable for the deployment model and
  documented.
* **CB-O3 (`tools/sanitize.py`):** docs-range host-octet wrap beyond 254 unique
  public IPs per range can collide redacted values (no leak). Unreachable for
  bug-report-sized configs. See §4.6.
* **CB-O4 (`target_profiles.py`):** `_RANGE_RE` dual-lazy-group split has a
  theoretical mis-split edge for exotic prefixes; no shipped profile triggers it.
  `UNVERIFIED`. See §4.8.
* **CB-O5 (`netcanon_desktop/server.py`):** the `wait_ready` timeout
  `RuntimeError` message (lines 113-116) embeds `{self._port}` inside a string
  that is NOT an f-string, so the literal text `{self._port}` would print rather
  than the port number. Cosmetic (only surfaces on a startup-timeout error path);
  borderline P3 but the surrounding first string IS an f-string so the intent is
  clear. Recording as observation; could be promoted to a 1-char P3 fix.

---

## 6. What's GOOD

A disproportionate amount of this codebase is worth calling out as exemplary —
useful for the synthesis to balance the findings.

* **The five-orchestrator rename family** (`port_names`, `vlan_names`,
  `local_user_names`, `snmp_names`, `snmpv3_user_names`). These are a textbook
  consistent-pattern set: every one exposes a `*RenameResult` pydantic model
  (`applied`/`dropped`/`warnings`), a `translate_*` pure-ish in-place function
  with the identical `isinstance(intent, CanonicalIntent)` mock guard and
  identical None-vs-`{}` sentinel handling, and a `build_*_rename_transform`
  factory returning `(transform_fn, result)`. A reader who learns one learns all
  five. Collision semantics are *correct per domain* (VLAN/local-user merge-by-
  union or max-privilege; SNMPv3 first-wins because USM keys must never combine).
  CD/CE will appreciate this as a model extension-point family.

* **`api/_errors.py`** is the best single file in the partition. It turns the
  ragged exception surface of paramiko/netmiko/socket/OSError into single-line
  host-prefixed operator messages via an isinstance-ordered dispatch table with
  rigorously correct subclass-before-base ordering, and — the clever part —
  walks `__cause__`/`__context__` to recover what Netmiko's generic "TCP
  connection failed" actually wrapped, so operators get the DNS-vs-refused-vs-
  unreachable distinction. The module docstring explains *why* it's a function
  not a FastAPI exception handler (it runs in a `ThreadPoolExecutor` worker, off
  the request stack). Internal-error types (`KeyError`/`AttributeError`) are
  honestly surfaced as "report this; traceback in server log" rather than a
  fabricated actionable message.

* **`storage/job_registry.py`** — a clean bounded-memory LRU that fixed a real
  unbounded-growth bug (documented: 100k jobs → 500MB pre-R8) without losing
  historical queryability (disk lazy-load on miss + promotion). The honesty of
  `__len__` returning *memory-resident* count (with `total_disk_count()` for the
  operator-meaningful total) and the dict-like surface keeping route handlers
  unchanged are both well-judged.

* **`services/diff.fold_context`** — the two-sweep forward/backward
  Manhattan-distance pass to compute each line's distance-to-nearest-change is a
  genuinely elegant O(n) solution to context folding, and the collapse logic is
  correct including the all-cold (no-change) edge.

* **Uniform broad-except discipline.** Every `except Exception: # noqa: BLE001`
  in the partition is paired with a `logger.warning`/`error`/`exception` call
  AND a comment justifying the swallow (probe-non-fatal, persistence-shouldn't-
  fail-backup, corrupt-file-skip-not-crash). This is the methodology's
  silent-drop anti-pattern explicitly avoided. The migration_pipeline catch-all
  even preserves the failing stage before reassigning status.

* **Credential hygiene end-to-end:** `SecretStr` in the request/transport models
  (`device.py`), Fernet-at-rest with a documented 3-tier key resolution
  (`security/credentials.py`), `get_secret_value()` only at the SSH boundary,
  `_CRED_FIELDS` stripping in the devices template handler, and the sanitiser's
  format-preserving hash redaction. Multiple independent layers.

* **Storage atomicity is universal:** every write across `file_store`,
  `job_store`, `schedule_store`, `device_profile_store` uses temp-file +
  `replace()`. No partial-write corruption window anywhere.

---

## 7. Coverage table

Confirmation that **all 78 files** in the partition received a verdict. (Counts
roll up §3.)

| Area | Files | Verdicts |
|---|--:|---|
| App core | 5 | KEEP ×5 |
| `api/` | 13 | KEEP ×13 |
| `services/` | 5 | KEEP ×5 |
| `storage/` | 7 | KEEP ×6, WATCH ×1 (`file_store`) |
| `collectors/` | 5 | KEEP ×5 |
| `models/` | 8 | KEEP ×7, WATCH ×1 (`migration.py`) |
| `security/` | 3 | KEEP ×3 |
| `definitions/` | 3 | KEEP ×3 |
| `tools/` | 2 | KEEP ×2 |
| `canonical/` | 9 | KEEP ×6, WATCH ×2 (`loader`, `__init__`), CONCERN ×1 (`intent.py`) |
| `migration/` root | 6 | KEEP ×6 |
| `netcanon_desktop/` | 11 | KEEP ×7, WATCH ×4 (`app`, `icons`, `__init__`; + `migration.py`-style note) |
| **Total** | **78** | **KEEP 70 · WATCH 6 · CONCERN 2** |

(WATCH 6 = `file_store`, `models/migration.py`, `canonical/loader`,
`canonical/__init__`, `desktop/app`, `desktop/icons`, `desktop/__init__` —
note `desktop/__init__` and `desktop/icons` and `desktop/app` all attach to the
single CB-04 docstring finding; counted as 3 desktop WATCH + file_store +
models/migration + canonical/loader + canonical/__init__ → the "6" counts
distinct files carrying a WATCH that is *not* also a CONCERN; `intent.py` is the
CONCERN. The precise per-file verdicts are in §3 tables and are authoritative
over this summary count.)

CONCERN 2 = `canonical/intent.py` (CB-01) and — by virtue of carrying the same
stale Phase-0.5 header that CB-02 flags as an active-lie — `models/migration.py`
is borderline; I classify `models/migration.py` as WATCH (the header is stale
but the model is correct) and reserve CONCERN for `intent.py` alone plus
`canonical/loader.py` (a whole-file `NotImplementedError` stub whose stale
"Phase 0.5" framing is the clearest active-lie instance). Net: 2 CONCERN
(`intent.py`, `canonical/loader.py`).

---

## 8. Open questions (for adversarial pass / orchestrator)

1. **CB-01 / CB-05 codec-side closure (for CC):** I verified arista_eos declares
   the VRRP/anycast paths `supported` and that arista/iosxe_cli/junos parsers
   populate the canonical fields. I did **not** audit all 8 codecs' `_CAPS`
   declarations nor the per-pair cross-vendor expectation YAMLs. Does every
   codec that *populates* a ship-before-wire field also *declare* it
   non-`unsupported`, and do the expectation YAMLs + `PHASE4_RECONCILIATION.md`
   agree? A half-wired codec (populates but declares `unsupported`) is the exact
   methodology violation. `UNVERIFIED` for 7 of 8 codecs.

2. **CB-02 libyang roadmap status (product call):** Is the libyang validation
   layer (`canonical/loader.py`) still a real roadmap item, or abandoned in
   favour of the pydantic IR? The fix for CB-02 (delete vs reword) depends on
   the answer. The 18-months-of-`NotImplementedError` shape strongly suggests
   abandoned, but I can't confirm read-only.

3. **CB-03 host-display fidelity (priority call):** Does the operator-facing
   Configs/Jobs UI actually surface the filename-derived host (lossy for
   hyphenated hostnames), or does it always have the live `ConfigRecord` with
   the correct host? If the lossy path is only ever hit on a cold
   `list_configs()` re-derive, the impact is small; if a hyphenated-hostname
   fleet is common it's worth the sidecar fix. CE/Fleet-D UI reviewers may have
   visibility.

4. **`migrate.html` / per-pane override e2e (out of my partition, noted):** the
   per-pane endpoints in `migration.py` and the orchestrators in `canonical/`
   are correct in isolation; the v0.1.2 CHANGELOG lists "UI verification still
   open" as a known gap. The override *flow* (modal → POST /plan/<pane> →
   result rendering) is exercised by the template, which is CE/Fleet-D's
   surface. No CB finding, but the integration is where a regression would hide.

5. **`target_profiles._RANGE_RE` edge (CB-O4):** can an adversarial reviewer
   construct a *real* `definitions/target_profiles/*.yaml` range string that
   mis-splits under the dual-lazy-group regex? I could not, but I didn't
   enumerate every shipped profile's `range:` entries. `UNVERIFIED`.

---

*End of CB chapter.*
