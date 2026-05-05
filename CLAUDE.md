# NetConfig — Contributor Directives

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

NetConfig handles two independent (but co-hosted) concerns:

1. **Backup** — `netconfig/collectors/` + `netconfig/api/routes/backups.py`.
   Pulls raw `running-config` (or vendor equivalent) from devices over
   SSH / NETCONF / REST and stores in `configs/<host>.<ext>`.  Mocked in
   tests at a single entry point: `get_collector`.
2. **Migration** — `netconfig/migration/`.  Translates a stored backup
   from one vendor's native config to another through a shared
   `CanonicalIntent` tree.  Per-vendor codecs under
   `netconfig/migration/codecs/` — see
   [`netconfig/migration/codecs/README.md`](netconfig/migration/codecs/README.md)
   for authorship guide.

A change to one concern rarely touches the other.  When in doubt about
where code belongs, ask: "does this fetch bytes off a device?" → backup.
"Does this translate canonical representation?" → migration.

---

## Parallel Platform Development

NetConfig ships on two platforms.  Both must always be kept at feature parity.

| Platform | Package | Entry point |
|----------|---------|-------------|
| Web (browser) | `netconfig/` | `uvicorn netconfig.main:app` |
| Desktop (Windows) | `netconfig_desktop/` | `python -m netconfig_desktop` |

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
- System tray icon (Show / Quit menu)
- MSI installer, Start Menu shortcut, taskbar pinning
- Embedded WebView window management (hide-to-tray on close, restore on show)
- Native window chrome (title bar, window icon via `.ico`)
- `setup_desktop.py` build script and `netconfig_desktop/` package
- **Open in text editor** (`config-open-btn`, `POST /api/v1/configs/{filename}/open`) —
  calls `os.startfile()` on the local filesystem.  Only meaningful when the server runs
  on the same machine as the user.  Enabled via `Settings.open_in_editor = True` in
  `netconfig_desktop/settings.py`.  The web platform equivalent is the existing
  **View** button (`config-view-link`) which renders the file in the browser.

**Web only**
- Interactive Swagger API docs at `/docs` — the web browser opens this freely;
  it is accessible from the desktop too but not surfaced in the desktop UI
- `--host` / `--port` flags for public network binding — the desktop always
  binds on `127.0.0.1` with a fixed internal port and is never exposed on LAN

---

## Feature Parity Checklist

When adding a feature, verify all of the following before committing:

- [ ] `netconfig/` — new route, service logic, or model implemented
- [ ] `netconfig/templates/` — new template has `data-testid` on every
      interactive element (buttons, inputs, links, table rows)
- [ ] `netconfig_desktop/` — any new server behaviour is exercised through
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
| A new codec under `netconfig/migration/codecs/<vendor>/` | `netconfig/migration/codecs/README.md` — update the "Shape of a codec" codec count + wire-format table; add the vendor to `ARCHITECTURE.md` if it's a new wire-format class |
| A new module inside an existing codec (e.g. `port_names.py`, `vlan_heuristics.py`, `_svi_absorption.py`) | `netconfig/migration/codecs/README.md` "Module layout" section if the pattern is worth propagating to other codecs |
| A new target-profile YAML under `definitions/target_profiles/` | Per-profile unit test in `tests/unit/migration/test_target_profile_shipped.py` asserting exact port-name list + count (regression guard against copy-paste mistakes) |
| A target-profile gains `modules:` (migrates to module-variant shape) | Add its `{vendor}/{model}` key to the canonical allowlist at `tests/fixtures/module_variants.py`.  Both the unit-tier and integration-tier tests import from there; a CI-guard (`test_module_variant_allowlist_shared_with_integration_tier`) enforces the single-source invariant so no manual sync is required. |
| A new canonical field on `CanonicalIntent` / `CanonicalInterface` / etc. | `docs/adding-a-canonical-field.md` — the MTU wire-through is the reference worked example |
| A new route, endpoint, or public function in a module whose top-of-file docstring enumerates contents (e.g. `netconfig/api/routes/migration.py`, `netconfig/services/migration_pipeline.py`) | The module docstring itself — if it lists endpoints / phases / public surface, your addition changes that list.  "Phase 2 *will* add …" comments become lies the instant Phase 2 lands.  Module docstrings that describe *intent* rather than *inventory* are unaffected. |
| A new hard rule / cross-cutting invariant surfaced by a bug | This file (`CLAUDE.md`) — add to the "Hard Rules (Never Break)" section with a one-line rationale pointing at the failure mode |
| A codec is promoted to `best_effort` or `certified` | `tests/fixtures/real/RESULTS.md` — update the coverage matrix and certification decision; ARCHITECTURE.md's cert paragraph intentionally defers to RESULTS.md as source of truth |
| A new real-capture fixture under `tests/fixtures/real/<vendor>/` | `tests/fixtures/real/NOTICE.md` — provenance + attribution; `tests/fixtures/real/RESULTS.md` — coverage matrix row |
| A new pytest marker in `pyproject.toml` (`[tool.pytest.ini_options] markers = [...]`) or a new conftest fixture that meaningfully changes how a whole test tier runs | `tests/README.md` — the markers table and/or the "How to run" section.  Markers without doc entries are invisible to contributors running `pytest -m <name>`. |
| A file-tree listing or "contents map" in any doc (`ARCHITECTURE.md` partial inventories, migrate.html header comment, sub-README directory trees) | Either update the listing in the same commit as the new file, OR convert the listing to a pointer ("see `netconfig/templates/_partials/` for the current set").  Exhaustive inventories that enumerate every file become a maintenance tax — prefer one-line pointers unless the enumeration carries load-bearing explanation. |
| A fourth or subsequent commit shipping pieces of the *same* new conceptual subsystem (e.g. target profiles, module variants, per-pane overrides, cross-mesh validation) | `ARCHITECTURE.md` — at the Nth commit of a thematic series, ask: "does the architecture doc have a section describing this concept, or only the piecemeal mechanics?"  If the concept is absent, add a short section in that same commit.  N is a judgement call but 3-5 commits is the rough threshold. |
| A function gains a new parameter or changes return shape | Its docstring (Google-style sections for Args / Returns / Raises) |
| A pipeline-stage signature (anywhere in `migration_pipeline.py`) | **DON'T.**  These are frozen (see Hard Rules).  Add a NEW function instead; the module docstring tracks which are frozen |
| The module-variant schema gets a new field on `TargetProfile` / `TargetModule` | The class docstring in `netconfig/migration/target_profiles.py` — it includes a worked YAML example that must stay accurate |
| In-file references like "see commit abc1234" in a partial or module comment | Fine to include for load-bearing rationale; don't rely on them for discoverability — put the same info in a nearby README if other contributors need it |
| A new CSS colour added to `base.html` (or any template's `<style>` block) | Use `var(--token)` referencing the theme-token set at the top of `base.html`'s `<style>` block.  Add a new token to BOTH the `:root` (light) and `[data-theme="dark"]` (dark) blocks if no existing token fits — a new raw hex that only works in light mode WILL look wrong in dark mode.  See ARCHITECTURE.md "Theming (dark mode)" for the three load-bearing rules |
| A capability-matrix change on a codec (xpath flips between supported / lossy / unsupported) | The matching expectation YAML under `tests/fixtures/cross_vendor_expectations/` for every pair the codec participates in, AND a regen commit for `CROSS_MESH_RESULTS.md` + `PHASE4_RECONCILIATION.md` (run `python tools/run_full_mesh.py --matrix` followed by `python tools/run_phase4_reconciliation.py`) |
| A new variance class added to `tools/run_phase4_reconciliation.py` | `ARCHITECTURE.md` "Cross-mesh fidelity audit harness" subsection — the bullet list of variance classes is exhaustive, not illustrative; missing entries become drift |
| A new backup-side device definition under `definitions/<vendor>/<os>/<ver>.yaml` | Per-vendor unit definition test under `tests/unit/definitions/`, per-vendor integration test, per-vendor desktop test (each pinning schema, probe regexes, codec round-trip).  See BD-Aruba (`de8e0f3`) / BD-Junos (`01f394c`) / BD-Arista (`8c9e9d4`) for the established three-test recipe |
| Render-side codec changes touching field xpaths the matrix declares as `supported` | After landing the code change, regen the cross-mesh artefacts (`CROSS_MESH_RESULTS.md` + `PHASE4_RECONCILIATION.md`) in a separate commit so the diff narrates "codec change" → "matrix delta" cleanly |

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
  `netconfig/migration/codecs/README.md`,
  `netconfig/migration/canonical/README.md`,
  `tests/fixtures/real/RESULTS.md`
* `README.md` → `ARCHITECTURE.md`, `CLAUDE.md`, `tests/README.md`

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
(`netconfig/`, `netconfig_desktop/`, `definitions/target_profiles/`,
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
  patch `netconfig.api.routes.backups.get_collector` instead (the single
  factory used by the backup route).
- **Never** assert on the POST `/api/v1/backups` response body for final job
  state — it always returns `pending` (serialised before background task runs).
  Always GET the job by ID to read the completed state.
- **Never** change the signatures of the existing pipeline-stage functions
  in `netconfig/services/migration_pipeline.py`.  API routes and dozens of
  tests depend on their exact shape.  Later phases add NEW public
  functions; existing stages stay frozen.  See the module docstring.
- **Never** commit real credential hashes to test fixtures.  Synthetic
  hashes in test input should LOOK like real hashes but be obviously
  fake (e.g. `$9$fake$hash`, `ENC fakeEncodedHash==`).  Third-party
  real captures from published repos are OK — their hashes are already
  public.  See `tests/fixtures/real/NOTICE.md` for provenance conventions.

---

## See also

- [`README.md`](README.md) — project orientation and quickstart
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — four-layer design and migration pipeline
- [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) — operator-facing capabilities + known limitations (cross-referenced against in-app limitation messages)
- [`docs/RELEASE_PLAN.md`](docs/RELEASE_PLAN.md) — forward-looking plan for taking the project public (not yet started; documents the strategic plan so it survives compaction and is discoverable cold)
- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — distilled matrix-honesty discipline (the patterns this project operates under, with worked-example citations into the live tree); portable to other projects
- [`docs/templates/`](docs/templates/) — starter scaffolding (CLAUDE.md / ARCHITECTURE.md / CHANGELOG.md / CAPABILITIES.md / RELEASE_PLAN.md / SECURITY.md / CONTRIBUTING.md + GitHub issue forms) for cloning the methodology into a new project; future-extractable to a standalone repo
- [`tests/README.md`](tests/README.md) — test-suite layout and mocking strategy
