# Netcanon — Contributor Directives

These directives govern all development in this repository.  Follow them in
every session without being asked.

**Project orientation:** if this is your first read, also skim
[`README.md`](README.md) for the quickstart and
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the 4-layer design.
[`CHANGELOG.md`](CHANGELOG.md) is the authoritative current-state
shipping log; [`translator-plans.txt`](translator-plans.txt) is the
slower-changing architectural sketch (most R / GAP / Phase items
now `[SHIPPED]`).  [`tests/fixtures/real/RESULTS.md`](tests/fixtures/real/RESULTS.md)
tracks per-codec certification state.

---

## Two concerns, one FastAPI app

Netcanon handles two independent (but co-hosted) concerns:

1. **Backup** — `netcanon/collectors/` + `netcanon/api/routes/backups.py`.
   Pulls raw `running-config` (or vendor equivalent) from devices over
   SSH / NETCONF / REST and stores in `configs/<host>.<ext>`.  Mocked in
   tests at a single entry point: `get_collector`.
2. **Migration** — `netcanon/migration/`.  Translates a stored backup
   from one vendor's native config to another through a shared
   `CanonicalIntent` tree.  Per-vendor codecs under
   `netcanon/migration/codecs/` — see
   [`netcanon/migration/codecs/README.md`](netcanon/migration/codecs/README.md)
   for authorship guide.

A change to one concern rarely touches the other.  When in doubt about
where code belongs, ask: "does this fetch bytes off a device?" → backup.
"Does this translate canonical representation?" → migration.

---

## Parallel Platform Development

Netcanon ships on two platforms.  Both must always be kept at feature parity.

| Platform | Package | Entry point |
|----------|---------|-------------|
| Web (browser) | `netcanon/` | `uvicorn netcanon.main:app` |
| Desktop (Windows) | `netcanon_desktop/` | `python -m netcanon_desktop` |

**Distribution variants — NOT separate platforms.**  Docker
(`ghcr.io/netcanon/netcanon` GHCR primary + `docker.io/netcanon/netcanon`
Docker Hub mirror), `pip install netcanon`, and the Windows MSI are
all distribution methods, not platforms.  Docker and pip both produce
a **web-platform** install (the container's entrypoint is
`uvicorn netcanon.main:app` — same code path as host-installed web);
the MSI produces a **desktop-platform** install.  None of them require
their own parity test row; a feature that lands on the web platform
automatically reaches Docker + pip users on the next release tag.
The doc-sync table below has a "packaging / distribution workflow
changes" row covering edits to `Dockerfile`, the publish workflows,
and the supply-chain attestation surfaces.

**Rule:** whenever a functional feature is added or changed on one platform, the
equivalent must be implemented on the other platform in the same commit (or the
same branch, if it spans multiple commits).  Never leave one platform behind.

This applies to:
- New API endpoints
- New UI pages or views
- New device definition schema fields
- New collector strategies
- New storage backends
- New application settings that affect behaviour

---

## Platform-Specific Exceptions

The following are intentionally platform-specific and do **not** require
cross-platform equivalents:

**Desktop only**
- System tray icon (Show / Preferences… / Open configs folder / Quit menu)
- MSI installer, Start Menu shortcut, taskbar pinning
- Embedded WebView window management (hide-to-tray on close, restore on show)
- Native window chrome (title bar, window icon via `.ico`)
- `setup_desktop.py` build script and `netcanon_desktop/` package
- **Open in text editor** (`config-open-btn`, `POST /api/v1/configs/{filename}/open`) —
  calls `os.startfile()` on the local filesystem.  Only meaningful when the server runs
  on the same machine as the user.  Enabled via `Settings.open_in_editor = True` in
  `netcanon_desktop/settings.py`.  The web platform equivalent is the existing
  **View** button (`config-view-link`) which renders the file in the browser.
- **Preferences dialog** (`netcanon_desktop/preferences_dialog.py`) — operator-
  configurable paths (configs / definitions / data dir), embedded-server port,
  and toggles.  Persisted to `%APPDATA%\Netcanon\preferences.json`.  Equivalent
  to the web platform's `NETCANON_*` env-var / `.env` configuration surface;
  desktop operators have no shell-level knob, so the dialog is the equivalent
  affordance.  PySide6 widgets carry `setObjectName()` IDs following the
  `pref-dialog-<field>-<action>` convention (the desktop equivalent of
  `data-testid` since Qt has no native test-id attribute).
- **Single-instance enforcement** (`netcanon_desktop/single_instance.py`) —
  Windows named mutex (`Global\NetcanonSingleInstance_v1`) refuses to launch a
  second copy.  Without this guard the duplicate process fails to bind the
  embedded server's TCP port and surfaces as a confusing fatal-error MessageBox;
  the friendly "already running" hint is much more discoverable.  No-op on
  non-Windows platforms.

**Web only**
- Interactive Swagger API docs at `/docs` — the web browser opens this freely;
  it is accessible from the desktop too but not surfaced in the desktop UI
- `--host` / `--port` flags for public network binding — the desktop always
  binds on `127.0.0.1` with a fixed internal port and is never exposed on LAN

**Deliberately omitted (preventive)**

The following are explicitly OUT OF SCOPE for the desktop platform.  They
are listed here so a future contributor doesn't add them speculatively
without an explicit product decision to reverse the call:

- **Telemetry / usage analytics** — no phone-home, no opt-in tracking.
  The desktop is a single-user local utility; analytics would add no
  product value and would surprise privacy-conscious operators.
- **Auto-update** — updates are delivered via fresh MSI download +
  reinstall.  Auto-update would require a code-signing infrastructure
  and persistent background scheduler we deliberately don't ship.
- **File associations** — no `.cfg` → Netcanon handler.  Operators
  open files via the in-app **View** / **Open in editor** affordances
  rather than from File Explorer.
- **Crash reporting** — fatal errors surface via MessageBoxW and the
  log file under `%APPDATA%\Netcanon\netcanon.log`; users can attach
  the log to a bug report.  No automatic crash uploads.

---

## Feature Parity Checklist

When adding a feature, verify all of the following before committing:

- [ ] `netcanon/` — new route, service logic, or model implemented
- [ ] `netcanon/templates/` — new template has `data-testid` on every
      interactive element (buttons, inputs, links, table rows)
- [ ] `netcanon_desktop/` — any new server behaviour is exercised through
      the embedded server (pure UI pages require no extra desktop work)
- [ ] `tests/unit/` — pure-function tests cover new logic
- [ ] `tests/integration/` — API-level tests cover new endpoints
- [ ] `tests/e2e/` — Playwright tests cover new UI flows (web platform)
- [ ] `tests/desktop/` — new server or app behaviour mocked and tested

---

## Documentation Sync Checklist

Code and docs drift silently — the only reliable defence is to treat
docs as part of the definition of "done".  When you change something,
update its documentation in the SAME commit, not a follow-up.  The
mapping below is concrete; audit every applicable row before you run
`git commit`.

| If you change / add … | Then touch … |
|---|---|
| A new interactive HTML element (button, input, link, row, `<select>`, `<option>` inside a form) | `tests/testid_reference.md` — document the new `data-testid` in the appropriate page section.  **Self-check:** run `grep -r 'data-testid="<new-id>"' tests/testid_reference.md` before committing; if it returns nothing, you haven't done the update. |
| A new Jinja partial (`templates/_partials/<name>.js`) | The file-level comment block in the parent template (e.g. `migrate.html`'s "Contents map" comment) **and** the "Template organisation" section of `ARCHITECTURE.md` if the partial introduces a new pattern |
| A new codec under `netcanon/migration/codecs/<vendor>/` | `netcanon/migration/codecs/README.md` — update the "Shape of a codec" codec count + wire-format table; add the vendor to `ARCHITECTURE.md` if it's a new wire-format class |
| A new module inside an existing codec (e.g. `port_names.py`, `vlan_heuristics.py`, `_svi_absorption.py`) | `netcanon/migration/codecs/README.md` "Module layout" section if the pattern is worth propagating to other codecs |
| A new target-profile YAML under `definitions/target_profiles/` | Per-profile unit test in `tests/unit/migration/test_target_profile_shipped.py` asserting exact port-name list + count (regression guard against copy-paste mistakes) |
| A target-profile gains `modules:` (migrates to module-variant shape) | Add its `{vendor}/{model}` key to the canonical allowlist at `tests/fixtures/module_variants.py`.  Both the unit-tier and integration-tier tests import from there; a CI-guard (`test_module_variant_allowlist_shared_with_integration_tier`) enforces the single-source invariant so no manual sync is required. |
| A new canonical field on `CanonicalIntent` / `CanonicalInterface` / etc. | `docs/adding-a-canonical-field.md` — the MTU wire-through is the reference worked example |
| A new route, endpoint, or public function in a module whose top-of-file docstring enumerates contents (e.g. `netcanon/api/routes/migration.py`, `netcanon/services/migration_pipeline.py`) | The module docstring itself — if it lists endpoints / phases / public surface, your addition changes that list.  "Phase 2 *will* add …" comments become lies the instant Phase 2 lands.  Module docstrings that describe *intent* rather than *inventory* are unaffected. |
| A new hard rule / cross-cutting invariant surfaced by a bug | This file (`AGENTS.md`) — add to the "Hard Rules (Never Break)" section with a one-line rationale pointing at the failure mode |
| A codec is promoted to `best_effort` or `certified` | `tests/fixtures/real/RESULTS.md` — update the coverage matrix and certification decision; ARCHITECTURE.md's cert paragraph intentionally defers to RESULTS.md as source of truth |
| A new real-capture fixture under `tests/fixtures/real/<vendor>/` | `tests/fixtures/real/NOTICE.md` — provenance + attribution; `tests/fixtures/real/RESULTS.md` — coverage matrix row |
| A new pytest marker in `pyproject.toml` (`[tool.pytest.ini_options] markers = [...]`) or a new conftest fixture that meaningfully changes how a whole test tier runs | `tests/README.md` — the markers table and/or the "How to run" section.  Markers without doc entries are invisible to contributors running `pytest -m <name>`. |
| A file-tree listing or "contents map" in any doc (`ARCHITECTURE.md` partial inventories, migrate.html header comment, sub-README directory trees) | Either update the listing in the same commit as the new file, OR convert the listing to a pointer ("see `netcanon/templates/_partials/` for the current set").  Exhaustive inventories that enumerate every file become a maintenance tax — prefer one-line pointers unless the enumeration carries load-bearing explanation. |
| A fourth or subsequent commit shipping pieces of the *same* new conceptual subsystem (e.g. target profiles, module variants, per-pane overrides, cross-mesh validation) | `ARCHITECTURE.md` — at the Nth commit of a thematic series, ask: "does the architecture doc have a section describing this concept, or only the piecemeal mechanics?"  If the concept is absent, add a short section in that same commit.  N is a judgement call but 3-5 commits is the rough threshold. |
| A function gains a new parameter or changes return shape | Its docstring (Google-style sections for Args / Returns / Raises) |
| A pipeline-stage signature (anywhere in `migration_pipeline.py`) | **DON'T.**  These are frozen (see Hard Rules).  Add a NEW function instead; the module docstring tracks which are frozen |
| The module-variant schema gets a new field on `TargetProfile` / `TargetModule` | The class docstring in `netcanon/migration/target_profiles.py` — it includes a worked YAML example that must stay accurate |
| In-file references like "see commit abc1234" in a partial or module comment | Fine to include for load-bearing rationale; don't rely on them for discoverability — put the same info in a nearby README if other contributors need it |
| A new CSS colour added to `base.html` (or any template's `<style>` block) | Use `var(--token)` referencing the theme-token set at the top of `base.html`'s `<style>` block.  Add a new token to BOTH the `:root` (light) and `[data-theme="dark"]` (dark) blocks if no existing token fits — a new raw hex that only works in light mode WILL look wrong in dark mode.  See ARCHITECTURE.md "Theming (dark mode)" for the three load-bearing rules |
| A capability-matrix change on a codec (xpath flips between supported / lossy / unsupported) | The matching expectation YAML under `tests/fixtures/cross_vendor_expectations/` for every pair the codec participates in, AND a regen commit for `CROSS_MESH_RESULTS.md` + `PHASE4_RECONCILIATION.md` (run `python tools/run_full_mesh.py --matrix` followed by `python tools/run_phase4_reconciliation.py`) |
| A user-facing feature ships or changes (new codec, capability-matrix delta, sanitization rule, CLI subcommand, HTTP endpoint, supported-vendor list change, UI behaviour change) | The operator-facing docs that describe it: per-vendor page under [`docs/vendors/<vendor>.md`](docs/vendors/) (if vendor-specific), [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) (if capability-matrix delta), [`BUG_REPORTING.md`](BUG_REPORTING.md) (if the sanitiser / submission flow changes), [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) (if a new failure mode), [`docs/HOW_WE_TEST.md`](docs/HOW_WE_TEST.md) (if a new test layer or audit category).  Operator-facing prose drifts faster than code; "the docs lied to me" is the failure mode this row prevents and the matrix-honesty discipline depends on |
| A new variance class added to `tools/run_phase4_reconciliation.py` | `ARCHITECTURE.md` "Cross-mesh fidelity audit harness" subsection — the bullet list of variance classes is exhaustive, not illustrative; missing entries become drift |
| A new backup-side device definition under `definitions/<vendor>/<os>/<ver>.yaml` | Per-vendor unit definition test under `tests/unit/definitions/`, per-vendor integration test, per-vendor desktop test (each pinning schema, probe regexes, codec round-trip).  See BD-Aruba (`de8e0f3`) / BD-Junos (`01f394c`) / BD-Arista (`8c9e9d4`) for the established three-test recipe |
| Render-side codec changes touching field xpaths the matrix declares as `supported` | After landing the code change, regen the cross-mesh artefacts (`CROSS_MESH_RESULTS.md` + `PHASE4_RECONCILIATION.md`) in a separate commit so the diff narrates "codec change" → "matrix delta" cleanly |
| A codec change affects translation behaviour for a pair covered by [`tools/demo.py`](tools/demo.py) (current pairs: `cisco_iosxe_cli` ↔ `juniper_junos`, `fortigate_cli` ↔ `mikrotik_routeros`, `aruba_aoss` ↔ `arista_eos`, `opnsense` ↔ `juniper_junos`) | Re-run `python tools/demo.py --pair <affected>` to verify the embedded synthetic config still translates cleanly.  If the rendered output's *shape* changed (added / dropped / reformatted lines that operators see), update the embedded source in `tools/demo.py` to match what the codec now models, and update the paired walkthrough at [`docs/walkthroughs/<source>_to_<target>.md`](docs/walkthroughs/) — specifically the "What Netcanon does for you", "Tier-3 boundary", and "Manual review checklist" sections.  Operators reading the walkthrough should see what's new, what's gone, and what they should re-verify on devices already migrated under the previous wave's behaviour |
| A new codec ships that opens a narratively-distinct translation pair (different paradigm, different scope, or different operator workflow vs the existing four scenarios) | Add a new scenario to `tools/demo.py` (`SCENARIOS` dict) AND a paired walkthrough at `docs/walkthroughs/<source>_to_<target>.md` in the same wave.  Update [`docs/walkthroughs/README.md`](docs/walkthroughs/README.md)'s table.  The 30-second "show me what this does" path Phase 4 established only stays valuable if the demo set keeps pace with the codec set |
| A change to the canonical model (`netcanon/migration/canonical/intent.py`) that adds a field demos *should* exercise | Update at least one `tools/demo.py` scenario's embedded synthetic config to include the new field, so the demo output visibly shows the new translation surface.  Without this, operators running the demo see translations that look like they did before the canonical-field landed — the "show me what's new" surface goes stale |
| A packaging / distribution workflow change (`Dockerfile`, `.dockerignore`, `.github/workflows/docker-publish.yml`, `.github/workflows/pypi-publish.yml`, base-image bump, action-version bump, registry namespace change, signing / SBOM / attestation surface change) | (1) [`SECURITY.md`](SECURITY.md) "Supply-Chain Integrity" + "Distribution channels" sub-table — every signing / attestation / lock-file change has to surface here so operators in regulated environments see accurate provenance claims.  (2) [`docs/IDENTITY.md`](docs/IDENTITY.md) "Distribution surfaces" table — every registry / namespace change has to update this canonical inventory.  (3) [`README.md`](README.md) Install section — Docker / pip / MSI examples have to match what the workflows actually publish.  (4) If the change adds a NEW Python version to the matrix in `.github/workflows/ci.yml`, also add the matching `Programming Language :: Python :: X.Y` classifier in `pyproject.toml` so package metadata is consistent with what's tested.  Distribution variants (Docker / pip / MSI) are not separate platforms (see "Parallel Platform Development" above), but their publish surface is operator-trust-load-bearing and drifts faster than the platform code itself |

Rule of thumb: if a future contributor could plausibly search for the
thing you just added and not find its rationale, there's a doc gap
to close.

---

## Cross-reference discipline

Every doc in `tests/`, `docs/`, and top-level `*.md` should open with
(or end with) a "See also" line pointing to its two or three closest
peers.  Concretely:

* `tests/README.md` → `testid_reference.md`, `fixtures/real/RESULTS.md`,
  `fixtures/real/NOTICE.md`
* `ARCHITECTURE.md` → `definitions/README.md`,
  `netcanon/migration/codecs/README.md`,
  `netcanon/migration/canonical/README.md`,
  `tests/fixtures/real/RESULTS.md`
* `README.md` → `ARCHITECTURE.md`, `AGENTS.md`, `tests/README.md`

A contributor who lands on one doc should be one hop from the others.
When you add a new sibling doc, add the reciprocal link in the
existing peers in the same commit — one-way cross-references rot
faster than numbers do.

---

## Code Organisation

See [`tests/README.md`](tests/README.md) for the full test-tier
layout (sub-trees under `tests/unit/` for `audit/`, `api/`,
`definitions/`, `migration/`, `tools/`, plus the integration / e2e /
desktop tiers) and the top-level repo tree
(`netcanon/`, `netcanon_desktop/`, `definitions/target_profiles/`,
`tools/`).  Top-level orientation lives in
[`README.md`](README.md)'s "Layout" section.

---

## Selectors

All interactive HTML elements **must** carry `data-testid` attributes.  E2E
tests use these exclusively — never CSS classes or element structure.  See
`tests/testid_reference.md` for the full inventory.

---

## Hard Rules (Never Break)

- **Never** add a feature to one platform without adding it to the other
  (unless explicitly listed under Platform-Specific Exceptions above).
- **Never** use `terminal length 0` for Cisco paging.  Use space-injection
  via `connection.cisco_more_paging: true` in the YAML definition.
- **Never** commit real credentials, device IPs, or secrets.
- **Never** skip `data-testid` attributes on new interactive template elements.
- **Never** author a `type_key` containing `_` or `.` in a device-definition
  YAML.  These characters are the separators the file-store filename grammar
  uses (`{type_key}_{safe_host}_{ts}.{ext}`), so an underscore or dot inside
  `type_key` makes the filename parse mathematically ambiguous (the lazy
  `.+?` would absorb only the leading token, mis-locating the file on
  `resolve_path`).  Use a single-token CamelCase vendor key like `Cisco`,
  `Aruba`, `Juniper`.  Enforced by `DeviceDefinition.type_key_filename_safe`
  at load time and by the file-store regex at parse time — both BD-Aruba
  and BD-Arista independently rediscovered this trap before the validator
  existed (commit `a93bee8`), which is why the rule lives here now.
- **Never** land a code change without updating the docs it renders stale.
  The "Documentation Sync Checklist" above is concrete — if a row applies
  to your change, touch the listed doc in the same commit.  Follow-up
  doc-only commits are acceptable for retroactive audits of pre-existing
  drift (e.g. the audit that added this rule), NOT for fresh code that
  shipped without its docs.  Stale docs are a bug; they just don't crash
  loud enough to be caught by CI, which is why the discipline has to live
  in the workflow.
- **Never** hard-code a count, LOC figure, or test tally in prose
  documentation (`README.md`, `ARCHITECTURE.md`, sub-READMEs) unless the
  same commit adds a CI or test guard that keeps the number honest.
  Use qualitative phrasing ("the largest template in the app", "dozens
  of target profiles across six vendors") or link to the authoritative
  source (`pytest --collect-only`, the file itself, `RESULTS.md`).
  Numbers in *test assertions* fail loudly and are fine; numbers in
  *prose* rot silently.  Retroactive purge of existing stale numbers is
  encouraged — removal counts as fixing.  Archival records in
  `CHANGELOG.md` (as-of-this-commit pass counts, historical LOC deltas)
  are exempt — they're timestamps, not current-state claims.
- **Never** patch `ConnectHandler` or `paramiko.SSHClient` directly in tests —
  patch `netcanon.api.routes.backups.get_collector` instead (the single
  factory used by the backup route).
- **Never** assert on the POST `/api/v1/backups` response body for final job
  state — it always returns `pending` (serialised before background task runs).
  Always GET the job by ID to read the completed state.
- **Never** change the signatures of the existing pipeline-stage functions
  in `netcanon/services/migration_pipeline.py`.  API routes and dozens of
  tests depend on their exact shape.  Later phases add NEW public
  functions; existing stages stay frozen.  See the module docstring.
- **Never** commit real credential hashes to test fixtures.  Synthetic
  hashes in test input should LOOK like real hashes but be obviously
  fake (e.g. `$9$fake$hash`, `ENC fakeEncodedHash==`).  Third-party
  real captures from published repos are OK — their hashes are already
  public.  See `tests/fixtures/real/NOTICE.md` for provenance conventions.
- **Never** ship a user-facing feature or capability change without
  updating the operator-facing docs that describe it.  The doc-sync
  table's "user-facing feature ships or changes" row enumerates the
  targets: `docs/vendors/<vendor>.md`, `docs/CAPABILITIES.md`,
  `BUG_REPORTING.md`, `docs/TROUBLESHOOTING.md`, `docs/HOW_WE_TEST.md`.
  Touch every one that's affected in the same commit / wave as the
  feature — operator-facing prose drifts faster than code, and
  "the docs lied to me" is what differentiates Netcanon's
  matrix-honesty discipline from the over-claiming alternatives in
  this space.
- **Never** push to an online / public repository (GitHub, GitLab,
  Bitbucket, GHCR, Docker Hub, PyPI, or any other off-machine
  destination — including private repos that may later go public,
  including container images and PyPI distributions) without first
  explicitly reviewing the diff for PII and identifying network
  information.  Scope of review:
  * **Operator personal data** — emails, names, geographic
    identifiers in author / committer metadata; banner / comment /
    description text; hostname patterns tied to the operator
    (`<operator-id>-fortigate`, `<operator-domain>.lan`).
  * **Real-world network identifiers** — public WAN IPs, real
    device hostnames, real MAC addresses, real serial numbers,
    internal-domain references.
  * **Encrypted secrets and key material** — `ENC <base64>` blobs,
    `$9$` / `$5$` / `$6$` / `$2y$` hashes, SSH public/private keys,
    certificate chains.  These are **operator-traceable even when
    encrypted** — never assume "encrypted" = safe to publish.
  * **Accidentally-tracked operator backups** under `configs/` /
    `devices/` / `schedules/` / `jobs/` (gitignore is not
    retroactive — files added before the ignore rule landed stay
    tracked).
  * **Narrative-exposure** — docs / CHANGELOG / NOTICE prose that
    describes what was sanitised by *naming* the real value
    (`real WAN IP <X> replaced with...`).  The sanitisation
    narrative itself must not leak the value it claims to redact.

  Sanitise via the Phase 4.5 helper (`netcanon sanitize` or
  `POST /api/v1/sanitize`) where the operator-data shape applies;
  hand-redact narrative / metadata refs the helper doesn't cover;
  use `git filter-repo` to scrub history when a secret has already
  been committed (Phase 1 wave is the reference workflow — see the
  `[Unreleased]` CHANGELOG entry for the four-pass recipe).

  After sanitisation, **judge whether a test re-run is warranted**:
  if the changes touched code or fixtures the test suite exercises,
  re-run the affected tier (`pytest tests/unit` for code-only
  changes; `pytest tests/integration` if API surface is touched;
  full suite for substantive changes).  Sanitisation edits can
  break tests in subtle ways (renamed fields, redacted-marker
  introduction in narrative-asserting tests).  Always verify
  rather than assume.

---

## See also

- [`README.md`](README.md) — project orientation and quickstart
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — four-layer design and migration pipeline
- [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) — operator-facing capabilities + known limitations (cross-referenced against in-app limitation messages)
- [`docs/RELEASE_PLAN.md`](docs/RELEASE_PLAN.md) — forward-looking plan for taking the project public (not yet started; documents the strategic plan so it survives compaction and is discoverable cold)
- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — distilled matrix-honesty discipline (the patterns this project operates under, with worked-example citations into the live tree); portable to other projects
- [`docs/templates/`](docs/templates/) — starter scaffolding (AGENTS.md / ARCHITECTURE.md / CHANGELOG.md / CAPABILITIES.md / RELEASE_PLAN.md / SECURITY.md / CONTRIBUTING.md + GitHub issue forms) for cloning the methodology into a new project; future-extractable to a standalone repo
- [`docs/IDENTITY.md`](docs/IDENTITY.md) — project identity surfaces (tagline, GitHub repo description, GitHub Topics list, logo design brief); update when any of those surfaces change
- [`docs/COMPARISON.md`](docs/COMPARISON.md) — positioning vs adjacent tools (Batfish, Capirca/Aerleon, NAPALM, Netmiko/Nornir, NetBox/Nautobot, ciscoconfparse) — what we compete with, what we complement, what we won't do
- [`docs/vendors/`](docs/vendors/) — per-vendor "what works for me?" pages (one per vendor family); update the relevant page when a codec's capability changes
- [`docs/walkthroughs/`](docs/walkthroughs/) — narrative walkthroughs of real-world migration scenarios (Cisco→Junos, FortiGate→MikroTik, Aruba→Arista, OPNsense→Junos); paired 1:1 with scenarios in `tools/demo.py`
- [`docs/HOW_WE_TEST.md`](docs/HOW_WE_TEST.md) — operator-facing narrative of the cross-mesh audit + 8-class variance taxonomy; update if a new test layer or audit category lands
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — diagnostic flowchart for "my translation didn't go cleanly" (Tier-3 vs Lossy vs CODEC_BUG)
- [`BUG_REPORTING.md`](BUG_REPORTING.md) — operator-facing fixture-submission + bug-report workflow (sanitise → verify → submit); references the Phase 4.5 sanitiser
- [`tests/README.md`](tests/README.md) — test-suite layout and mocking strategy
