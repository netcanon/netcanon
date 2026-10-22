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
`netcanon serve`, which starts uvicorn on `netcanon.main:app` — the same
application as host-installed web; under the `small` config limits
`netcanon serve` also asks the system to end connections nobody reads,
which a server started as `uvicorn netcanon.main:app` does not have);
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
  the config size limit (the twin of `NETCANON_CONFIG_LIMITS`), and toggles.
  Persisted to `%APPDATA%\Netcanon\preferences.json`.  Equivalent
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
| A new file under `netcanon/templates/` with a non-`.html` extension OR in a new subdirectory not covered by the existing globs | `pyproject.toml` `[tool.setuptools.package-data]` — extend the `netcanon = [...]` list with a glob covering the new pattern (e.g. `templates/_partials/*.js`, `templates/_components/*.svg`).  Editable installs (`pip install -e`) hide this because they import from the source tree directly; production wheels do not.  Missing template files in the wheel result in `jinja2.exceptions.TemplateNotFound` 500-on-render at runtime — the bug that broke v0.1.0-rc1 / rc2.  The CI `docker-build-smoke` job catches dashboard-rendering regressions of this class but only for the dashboard page; if your new pattern only affects a different page, also add a smoke-test step that visits that page. |
| A new codec under `netcanon/migration/codecs/<vendor>/` | `netcanon/migration/codecs/README.md` — update the "Shape of a codec" codec count + wire-format table; add the vendor to `ARCHITECTURE.md` if it's a new wire-format class.  And state `port_names_case_sensitive` in the codec's own class body (there is no safe default; see the Hard Rule on port names) — `test_the_codecs_say_which_they_are` in `tests/unit/migration/test_run_plan_with_models.py` fails for a public codec that leaves it to the base class.  Set `ports_keep_a_factory_name = True` ONLY if its parser records a factory name beside a port's own; every other codec leaves it to the base class (`test_the_flag_is_what_the_captures_show` in `tests/unit/migration/test_port_name_universe.py` fails for a codec whose captures and flag disagree).  And say what a trunk that states no allowed list carries on the platform: a row in `TRUNK_THAT_STATES_NO_LIST` (`netcanon/migration/codecs/_helpers.py`), which the parser fills an unstated list from — through `TrunksByName`, which keeps what an interface states by its name, so that a stanza met twice is one interface and only a port that SAYS it is a trunk is given the default — or — if the platform has no allowed list, or the parser reads none — the codec's name and the reason in `NO_ALLOWED_LIST` in `tests/unit/migration/test_a_trunk_says_none_nothing_or_all.py`.  `test_each_codec_is_in_the_table_or_named` fails for a public codec that is in neither (see the Hard Rule on "not stated") |
| A new codec under `netcanon/migration/codecs/<vendor>/` | `netcanon/migration/codecs/README.md` — update the "Shape of a codec" codec count + wire-format table; add the vendor to `ARCHITECTURE.md` if it's a new wire-format class.  And state `port_names_case_sensitive` in the codec's own class body (there is no safe default; see the Hard Rule on port names) — `test_the_codecs_say_which_they_are` in `tests/unit/migration/test_run_plan_with_models.py` fails for a public codec that leaves it to the base class.  Set `ports_keep_a_factory_name = True` ONLY if its parser records a factory name beside a port's own; every other codec leaves it to the base class (`test_the_flag_is_what_the_captures_show` in `tests/unit/migration/test_port_name_universe.py` fails for a codec whose captures and flag disagree).  A codec that declares the `vendor_id` of another is one PLATFORM with it: a name the port translator leaves between the two is taken for the platform's own and holds no job.  `test_which_codecs_are_one_platform` in `tests/unit/migration/test_run_plan_checked_names.py` pins the pairs and fails for a new one until it is added there |
| A new module inside an existing codec (e.g. `port_names.py`, `vlan_heuristics.py`, `_svi_absorption.py`) | `netcanon/migration/codecs/README.md` "Module layout" section if the pattern is worth propagating to other codecs |
| A new target-profile YAML under `netcanon/definitions/library/target_profiles/` | (1) Per-profile unit test in `tests/unit/migration/test_target_profile_shipped.py` asserting exact port-name list + count (regression guard against copy-paste mistakes).  (2) Provenance per [`docs/adding-a-target-profile.md`](docs/adding-a-target-profile.md) §4: `deployment_state` whenever `stacking` is set, `evidence` + `evidence_ref`, and the key added to the pinned set for its grade in `tests/unit/migration/test_target_profile_evidence.py` — `CAPTURE_MODEL_MARKER` (with a line only a capture of that model contains), `EXPECTED_VENDOR_DOC_GRADED`, or `KNOWN_DOUBTFUL`.  The sets are compared for equality with what the YAMLs declare, so a graded profile that skips this fails CI |
| A new or changed model-family YAML under `netcanon/definitions/library/model_families/` (a family, a model, a mode, a module) | Per [`docs/adding-a-device-model.md`](docs/adding-a-device-model.md): (1) the hand-typed `(access names, uplink names)` entry for every model × mode × module combination in `EXPECTED_INVENTORIES` in `tests/unit/migration/test_device_models_shipped.py` — the test fails for any shipped combination that is not pinned; (2) each part number in `EXPECTED_PART_NUMBERS`, and a part graded `inferred` in `KNOWN_INFERRED_PARTS`, in the same file; (3) a `captures:` claim if a committed capture of that exact model exists AND names every port of it, mirrored whole in `EXPECTED_CLAIMS` and listed in `PROVEN_CAPTURE_CLAIMS` in `netcanon/migration/device_models.py` — a claim not in that list grants nothing (never grade a part `capture`; the schema refuses it); (4) the pair in `PROFILE_AGREES_WITH` if a flat target profile describes the same device.  Port groups go in port-NUMBER order, not left-to-right on the faceplate.  Write every `ref` so it stands on its own — it is served to API clients, who cannot read a legend in a YAML comment |
| A new deployment detector in `_detectors()` (`netcanon/migration/deployment_detect.py`), or a change to one | The detector lives beside the vendor's codec (`deployment_detect.py`) and reads what a config STATES — part numbers, member ids, modules — never a model inferred from port names.  It reads text nobody vouches for: anchor every pattern to a line, bound what it takes, apply none to a fragment another matched unless that fragment is itself bounded, and say in the notes what was left out or chosen — a few member numbers and a count, never every one.  A detection with no members puts the REASON first in its notes: a proposal with no deployment shows its first note as why.  Name the vendor's codec in `_CODEC_OF` in `tests/unit/migration/test_deployment_detect.py` — the tests that walk every detector (the cross-check against that vendor's capture claims, the text made to be slow, the factory-name guard) fail until it is there.  Tests in that module over every stanza form the vendor documents and over the committed captures; the "what the lines do not prove" notes; no MAC or serial in the evidence lines.  `docs/CAPABILITIES.md` § G names the vendors detection reads; `SECURITY.md` "Input Validation — Device Declarations" lists the detector's file |
| A new naming rule in `_naming_rules()` (`netcanon/migration/device_models.py`), or a change to one | The rule itself lives beside the vendor's codec; give it the set of roles it can name (a role it cannot name is refused at load).  Tests against the vendor's own printed examples, including one whose member number is not 1, in `tests/unit/migration/test_device_models.py`; `ARCHITECTURE.md` "Device models and inventories" if the rule introduces a new idea (a lane, a per-group prefix) |
| A new place that turns a token into many entries (a range, a keyword for "every", a platform default that stands for a list, a product of two lists), or a new loop over config lines, in any module under `netcanon/migration/` | Charge it before the entries are made (`limits.charge`) and put the loop through `limits.ticked` -- the Hard Rule on counting has the three parts.  A `range(...)`, a slice of `VLAN_IDS` or a `vlan_id_run(...)` under `codecs/` goes in `RUNS_OF_ENTRIES` in `tests/unit/migration/test_limits.py` with its answer; a text that is refused BEFORE it is made goes in that module's `WIDE` (for a VLAN id list) or gets a test beside the others; `netcanon/migration/codecs/README.md` "Adding a codec" step 4 |
| A new limit, a changed number, or a new kind in `netcanon/migration/limits.py` | The tables in [`SECURITY.md`](SECURITY.md) "Input Validation — Config Text" and [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) § H (`tests/unit/test_limits_docs_truth.py` fails until they agree); [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) "The job says `refused:`" for a new kind; `Refusal.limit` in `netcanon/models/migration.py`; and for `small`, a measurement in a container shaped like a demo instance, recorded in [`docs/demo-plan/07-budget.md`](docs/demo-plan/07-budget.md) |
| A new handler that takes config text (a `raw_text` body field, an upload) | Open the SERVER's scope with the server's setting and the request's answer (`with server_scope(request_limits(request), answer=request_answer(request)):`) -- it takes the request's turn where the limits say how many work at once -- and answer a `LimitExceeded` in words, the one raised where the scope is opened included (the request did not get a turn: `refusal_as_http`, or the job `run_translation` makes); add the path to `READS_CONFIG_TEXT` in `_migration_helpers.py` -- a request is counted by its method and path when its headers arrive, before its body is read, and a handler that is not there has every body read first -- and to `TAKES_CONFIG_TEXT` in `tests/integration/test_config_limits_api.py`, which finds such handlers by what they take and fails until the new one is there, is counted at its arrival, takes its turn and answers "busy" in words.  A handler that returns a job returns `job_answer(job, response)`, never the job |
| A new job-running migration handler in `netcanon/api/routes/migration.py` | Dispatch through `_migration_helpers.run_translation`, never the pipeline directly, and add the path to the parametrised endpoint tests in `tests/integration/test_migration_models_api.py` (`test_every_plan_endpoint_renders_the_same_port_names`, `test_the_operators_port_map_applies_on_every_plan_endpoint`, `test_acknowledged_drops_clear_partial_on_every_plan_endpoint`, and — by adding it to `_PLAN_PATHS` — the tests of a request that declares no devices: `TestPortNamesWithNoDevices`, `TestABlankTarget`, `TestForceOnEveryPlanEndpoint`) — otherwise the same request body renders different port names, or stays `partial` after the operator has decided every port, depending on which endpoint it is posted to.  The first of those alone cannot see it: it posts no port map.  A handler passes its own category map and nothing for ports: `run_translation` takes the port map from the body on every endpoint, since an entry there is what settles a job that is `partial` for its port names.  A blank target in that map is refused where the request is read (`MigrationPlanRequest`), so a new endpoint that takes another body has to refuse it too |
| A target-profile gains `modules:` (migrates to module-variant shape) | Add its `{vendor}/{model}` key to the canonical allowlist at `tests/fixtures/module_variants.py`.  Both the unit-tier and integration-tier tests import from there; a CI-guard (`test_module_variant_allowlist_shared_with_integration_tier`) enforces the single-source invariant so no manual sync is required. |
| A new canonical field on `CanonicalIntent` / `CanonicalInterface` / etc. | `docs/adding-a-canonical-field.md` — the MTU wire-through is the reference worked example.  A field that holds a PORT NAME also goes in `_swept_names` (see the Hard Rule on port names), and — where the config only REFERS to an interface there, as a route does — in `_only_referred_to` in `netcanon/migration/canonical/port_names.py`: left out, a name the translator cannot read in that field holds the job, which is the safe side |
| A new route, endpoint, or public function in a module whose top-of-file docstring enumerates contents (e.g. `netcanon/api/routes/migration.py`, `netcanon/services/migration_pipeline.py`) | The module docstring itself — if it lists endpoints / phases / public surface, your addition changes that list.  "Phase 2 *will* add …" comments become lies the instant Phase 2 lands.  Module docstrings that describe *intent* rather than *inventory* are unaffected. |
| A new hard rule / cross-cutting invariant surfaced by a bug | This file (`AGENTS.md`) — add to the "Hard Rules (Never Break)" section with a one-line rationale pointing at the failure mode |
| A codec is promoted to `best_effort` or `certified` | `tests/fixtures/real/RESULTS.md` — update the coverage matrix and certification decision; ARCHITECTURE.md's cert paragraph intentionally defers to RESULTS.md as source of truth |
| A new real-capture fixture under `tests/fixtures/real/<vendor>/` | (1) `tests/fixtures/real/NOTICE.md` — provenance + attribution row; (2) `tests/fixtures/real/RESULTS.md` — per-codec coverage matrix row + Summary table count refresh; (3) `tests/fixtures/real/WANTED.md` — "Current corpus snapshot" count if the new fixture changes it; (4) `docs/vendors/<vendor>.md` — fixtures-section enumeration (if the new fixture exercises a notable grammar surface — e.g. a new VRRP form, a new EVPN type, the first MSI-build example); (5) the pinned table `_MOVES` in `tests/unit/migration/test_run_plan_checked_names.py` when a job of the new capture, onto any codec, is `partial` for its port names where the validation report alone would have passed it, and `_STANDS` beside it when the translator leaves a name of the capture that is not listed because it is the target's own — the test fails with the numbers it found; for `_STANDS`, read the line of the output the name is on before changing the table.  Item (4) is here because fixtures have landed in NOTICE/RESULTS without reaching their vendor page. |
| A new pytest marker in `pyproject.toml` (`[tool.pytest.ini_options] markers = [...]`) or a new conftest fixture that meaningfully changes how a whole test tier runs | `tests/README.md` — the markers table and/or the "How to run" section.  Markers without doc entries are invisible to contributors running `pytest -m <name>`. |
| A file-tree listing or "contents map" in any doc (`ARCHITECTURE.md` partial inventories, `definitions.html` header comment, sub-README directory trees) | Either update the listing in the same commit as the new file, OR convert the listing to a pointer ("see `netcanon/templates/_partials/` for the current set").  Exhaustive inventories that enumerate every file become a maintenance tax — prefer one-line pointers unless the enumeration carries load-bearing explanation. |
| A fourth or subsequent commit shipping pieces of the *same* new conceptual subsystem (e.g. target profiles, module variants, per-pane overrides, cross-mesh validation) | `ARCHITECTURE.md` — at the Nth commit of a thematic series, ask: "does the architecture doc have a section describing this concept, or only the piecemeal mechanics?"  If the concept is absent, add a short section in that same commit.  N is a judgement call but 3-5 commits is the rough threshold. |
| A function gains a new parameter or changes return shape | Its docstring (Google-style sections for Args / Returns / Raises) |
| A pipeline-stage signature (anywhere in `migration_pipeline.py`) | **DON'T.**  These are frozen (see Hard Rules).  Add a NEW function instead; the module docstring tracks which are frozen |
| The module-variant schema gets a new field on `TargetProfile` / `TargetModule` | The class docstring in `netcanon/migration/target_profiles.py` — it includes a worked YAML example that must stay accurate |
| In-file references like "see commit abc1234" in a partial or module comment | Fine to include for load-bearing rationale; don't rely on them for discoverability — put the same info in a nearby README if other contributors need it |
| A new CSS colour added to `base.html` (or any template's `<style>` block) | Use `var(--token)` referencing the theme-token set at the top of `base.html`'s `<style>` block.  Add a new token to BOTH the `:root` (light) and `[data-theme="dark"]` (dark) blocks if no existing token fits — a new raw hex that only works in light mode WILL look wrong in dark mode.  See ARCHITECTURE.md "Theming (dark mode)" for the three load-bearing rules |
| A capability-matrix change on a codec (xpath flips between supported / lossy / unsupported) | The matching expectation YAML under `tests/fixtures/cross_vendor_expectations/` for every pair the codec participates in, AND a regen commit for `CROSS_MESH_RESULTS.md` + `PHASE4_RECONCILIATION.md` + `latest.json` (run `python tools/run_full_mesh.py --matrix` followed by `python tools/run_phase4_reconciliation.py --write-baseline` — the `--write-baseline` flag is REQUIRED to overwrite the committed `latest.json` + `PHASE4_RECONCILIATION.md`; a bare run writes only the gitignored timestamped archive so inspecting drift never silently moves the ratchet) |
| A user-facing feature ships or changes (new codec, capability-matrix delta, sanitization rule, CLI subcommand, HTTP endpoint, supported-vendor list change, UI behaviour change) | The operator-facing docs that describe it: per-vendor page under [`docs/vendors/<vendor>.md`](docs/vendors/) (if vendor-specific), [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) (if capability-matrix delta), [`BUG_REPORTING.md`](BUG_REPORTING.md) (if the sanitiser / submission flow changes), [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) (if a new failure mode), [`docs/HOW_WE_TEST.md`](docs/HOW_WE_TEST.md) (if a new test layer or audit category).  Operator-facing prose drifts faster than code; "the docs lied to me" is the failure mode this row prevents and the matrix-honesty discipline depends on |
| A new variance class added to `tools/run_phase4_reconciliation.py` | `ARCHITECTURE.md` "Cross-mesh fidelity audit harness" subsection — the bullet list of variance classes is exhaustive, not illustrative; missing entries become drift |
| A new backup-side device definition under `netcanon/definitions/library/<vendor>/<os>/<ver>.yaml` | Per-vendor unit definition test under `tests/unit/definitions/`, per-vendor integration test, per-vendor desktop test (each pinning schema, probe regexes, codec round-trip).  See BD-Aruba (`7b3d7ed`) / BD-Junos (`271f196`) / BD-Arista (`a5441b9`) for the established three-test recipe |
| Render-side codec changes touching field xpaths the matrix declares as `supported` | After landing the code change, regen the cross-mesh artefacts (`CROSS_MESH_RESULTS.md` + `PHASE4_RECONCILIATION.md`) in a separate commit so the diff narrates "codec change" → "matrix delta" cleanly |
| A codec change affects translation behaviour for a pair covered by [`tools/demo.py`](tools/demo.py) (current pairs: `cisco_iosxe_cli` ↔ `juniper_junos`, `fortigate_cli` ↔ `mikrotik_routeros`, `aruba_aoss` ↔ `arista_eos`, `opnsense` ↔ `juniper_junos`) | Re-run `python tools/demo.py --pair <affected>` to verify the embedded synthetic config still translates cleanly.  If the rendered output's *shape* changed (added / dropped / reformatted lines that operators see), update the embedded source in `netcanon/tools/demo.py` to match what the codec now models, and update the paired walkthrough at [`docs/walkthroughs/<source>_to_<target>.md`](docs/walkthroughs/) — specifically the "What Netcanon does for you", "Tier-3 boundary", and "Manual review checklist" sections.  Operators reading the walkthrough should see what's new, what's gone, and what they should re-verify on devices already migrated under the previous wave's behaviour |
| A new codec ships that opens a narratively-distinct translation pair (different paradigm, different scope, or different operator workflow vs the existing four scenarios) | Add a new scenario to `netcanon/tools/demo.py` (`SCENARIOS` dict) AND a paired walkthrough at `docs/walkthroughs/<source>_to_<target>.md` in the same wave.  Update [`docs/walkthroughs/README.md`](docs/walkthroughs/README.md)'s table.  The 30-second "show me what this does" path Phase 4 established only stays valuable if the demo set keeps pace with the codec set |
| A change to the canonical model (`netcanon/migration/canonical/intent.py`) that adds a field demos *should* exercise | Update at least one `netcanon/tools/demo.py` scenario's embedded synthetic config to include the new field, so the demo output visibly shows the new translation surface.  Without this, operators running the demo see translations that look like they did before the canonical-field landed — the "show me what's new" surface goes stale |
| A demo-scenario change alters the rendered OUTPUT of `demo --pair cisco__junos` or `demo --pair fortigate__mikrotik` (the two landing-page hero pairs) | Regenerate the hero panes in [`site/index.html`](site/index.html) from the real command output AND re-author `site/og.png` as a crop of the default pane with the Tier-3 banner visible.  The landing page prints "this pane is the unedited output of" above a reproduce command — that sentence is only true while the panes track the scenarios, and `printed-commands-smoke.yml` re-proves it against `:latest` on every release publish |
| A packaging / distribution workflow change (`Dockerfile`, `.dockerignore`, `.github/workflows/docker-publish.yml`, `.github/workflows/pypi-publish.yml`, base-image bump, action-version bump, registry namespace change, signing / SBOM / attestation surface change, **new supply-chain integrity control such as a scanner, signing tool, allowlist, or workflow-hardening control**) | (1) [`SECURITY.md`](SECURITY.md) — verify every item in its own [§ "Updating This Document"](SECURITY.md#updating-this-document) trigger list: new dependency with security relevance → Dependency Supply Chain table; new untrusted-input handling → Input Validation section; new redaction category → Sanitiser section; new supply-chain integrity control → Supply-Chain Integrity section + Distribution channels sub-table.  Round-tripping SECURITY.md after release is the most common drift class — the v0.1.2 audit (`docs/docs-audit/2026-05-21/`) found 3 of 7 triggers met without SECURITY.md being updated.  (2) [`docs/IDENTITY.md`](docs/IDENTITY.md) "Distribution surfaces" table — every registry / namespace change has to update this canonical inventory.  (3) [`README.md`](README.md) Install section — Docker / pip / MSI examples have to match what the workflows actually publish.  (4) If the change adds a NEW Python version to the matrix in `.github/workflows/ci.yml`, also add the matching `Programming Language :: Python :: X.Y` classifier in `pyproject.toml` so package metadata is consistent with what's tested.  (5) [`ARCHITECTURE.md`](ARCHITECTURE.md) Evolution roadmap "What's shipped" — add a release-anchored bullet when the change ships as part of a tagged release.  Distribution variants (Docker / pip / MSI) are not separate platforms (see "Parallel Platform Development" above), but their publish surface is operator-trust-load-bearing and drifts faster than the platform code itself |
| Cutting a new release | **Tag, push, done.**  No manual `pyproject.toml` version bump required — `setuptools_scm` derives the package version from the git tag automatically (`v0.1.0-rc5` → package version `0.1.0rc5` per PEP 440 normalization).  The publishing workflows pass the metadata-action's parsed version into the Docker builder stage as a `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NETCANON` build-arg so the container build doesn't need `.git/` in its context.  PyPI publish runs `python -m build` against the checked-out source tree (with `fetch-depth: 0` for the tag history) so setuptools_scm reads the tag directly there.  If a CI checkout step is added that runs `pip install -e .` or `python -m build`, it MUST set `fetch-depth: 0` — default shallow checkouts have no tags and setuptools_scm will fall back to `0.0.0`, which is a misleading silent-degradation rather than a loud failure.  The auto-generated `netcanon/_version.py` file is gitignored — never commit it. |
| A new wave of GitHub Code Scanning / Dependabot / secret-scanning alerts arrives (e.g. new scanner enabled, scanner version bump surfaces newly-covered rules, > 10 new alerts since last triage, pre-release gate) | Run a triage cycle per [`docs/security-triage/README.md`](docs/security-triage/README.md).  The process is dated-folder scaffolded so verdicts are reproducible: snapshot → cluster → parallel read-only agents → orchestrator synthesis → dismissals applied via `gh api` with `dismissed_reason` + `dismissed_comment`.  For one-off alerts arriving during normal development, fix or dismiss inline — don't spin up the full process.  Always set a free-text `dismissed_comment` so the next reader sees *why*; "won't fix" alone is opaque six months later |
| A sustained run of substantive change waves has landed (security cycle, codec wave, canonical-model expansion) or > 1 quarter has passed since the last hygiene pass, OR a release is being prepared and the "did the docs keep up" question is live | Run a documentation hygiene audit per [`docs/docs-audit/README.md`](docs/docs-audit/README.md).  Same scaffolding shape as `docs/security-triage/`: snapshot → 6-cluster taxonomy (interlinking / user-docs / developer-docs / codec-docstrings / platform-docstrings / tests-changelog) → parallel read-only Opus 4.7 1M agents → orchestrator synthesis → Stage 2 fix execution commit-by-commit.  Cluster labels are stable across runs so future-you searching for "the codec-docstring audit pattern" finds prior investigations under the same name.  For one-off doc updates landing alongside their code change, just use the rows in this Documentation Sync Checklist — don't spin up the full process |
| A new redaction category lands in `netcanon/tools/sanitize.py` (a new canonical field added to `_SubstitutionTable` + matching `sanitize_intent` walk + corresponding `_REDACTION_RULES` entry) | (1) [`SECURITY.md`](SECURITY.md) § "Sanitiser (Bug-Reporting Workflow)" — list the new category in the redaction-rule table; (2) [`BUG_REPORTING.md`](BUG_REPORTING.md) § "What gets sanitised" — operator-facing rule list + per-category counter scheme; (3) [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) if the category exposes a new sanitised surface operators see in the migrate-page banners.  This row exists because SECURITY.md's own "Updating This Document" trigger list demands it but the round-trip through SECURITY.md is brittle — contributors find this row in the doc-sync table first |
| A new shared transform under `netcanon/migration/canonical/transforms.py` (e.g. `project_svi_to_vlan`, `_natural_port_sort_key`) | (1) [`netcanon/migration/codecs/README.md`](netcanon/migration/codecs/README.md) "Cross-codec shared utilities" — every codec that consumes the transform should be greppable from one place; (2) [`ARCHITECTURE.md`](ARCHITECTURE.md) "Cross-cutting render-time policies" — add a one-paragraph entry if the transform introduces a new policy class (rather than a per-codec utility).  Pattern: this row exists because transforms.py additions have shipped in Wave 7c + Wave 10γ-3 with codecs/README updates but no doc-sync row demanding it; the next addition shouldn't need maintainer memory to keep the chain intact |
| A new top-level migration-package sibling at `netcanon/migration/_*.py` (e.g. `_user_secrets.py`, `_naming.py`, `_tier3_detection.py`) | (1) [`ARCHITECTURE.md`](ARCHITECTURE.md) "Cross-cutting render-time policies" — add a one-paragraph entry naming the new sibling + its rationale; (2) [`netcanon/migration/codecs/README.md`](netcanon/migration/codecs/README.md) "Cross-codec shared utilities" if codecs consume the new sibling.  All three current siblings (`_user_secrets.py`, `_naming.py`, `_tier3_detection.py`) ARE documented but the row that demands it has been absent — close that gap |
| A codec gains an entry in `unsupported_rename_categories` (a Tier-2 category that the codec's parse + render don't yet round-trip end-to-end, surfacing as a per-pane-overrides banner for that codec as target) | (1) [`ARCHITECTURE.md`](ARCHITECTURE.md) "Per-pane overrides" § "Current state" — list the codec + category + reason (parse doesn't capture / render doesn't emit / both); (2) The codec's own `__init__.py` or `codec.py` module docstring — note the limitation so contributors reading the codec see it without round-tripping through ARCHITECTURE.md.  The 2026-05-21 audit caught OPNsense + Cisco IOS-XE NETCONF declaring `{"snmpv3"}` while ARCHITECTURE.md claimed every codec was empty post-Option-A; this row exists so the next addition doesn't repeat the drift |
| A new fixture-research catalogue lands at `docs/fixture-research-<year>/` or a substantial WANTED.md update marks new shipped / closed items | (1) [`README.md`](README.md) "What's next" section — pointer to the catalogue if it's load-bearing for the v0.X.Y backlog; (2) [`docs/RELEASE_PLAN.md`](docs/RELEASE_PLAN.md) Status block — mark items shipped that have actually shipped (don't carry "Next: v0.1.0 final" forward after v0.1.1 / v0.1.2 / etc. tag).  Low-priority row: typically the v0.X.Y-planning folder is the source of truth and updates land via cluster-C dev-doc audits |

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
* `ARCHITECTURE.md` → `netcanon/definitions/library/README.md`,
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
(`netcanon/`, `netcanon_desktop/`, `netcanon/definitions/library/target_profiles/`,
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
  existed (commit `ba72502`), which is why the rule lives here now.
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
  state — it always returns `pending` (the job runs in the background).  Since
  #27 the job runs on a dedicated executor (`backup_runner.submit_backup_job`),
  NOT synchronously before the response — even under `TestClient` — so do not
  assume it has finished the instant the POST returns.  **Poll** `GET /{id}`
  until the status is terminal (`completed`/`partial`/`failed`): use the
  `wait_for_job(client, job_id)` helper in `tests/conftest.py` (the integration
  `client` fixture applies it automatically after a backups POST).
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
- **Never** let a failable step sit between publishing an artifact and
  signing it.  `Build and push` in `docker-publish.yml` makes every tag
  live — `:latest` included — the instant it completes, and a failing step
  aborts the job *with the tag still moved*, so the unsigned window is
  permanent rather than transient.  Install prerequisite tooling BEFORE the
  push; put sign / SBOM / attest / verify immediately after it; demote
  scanning and reporting to the end and mark them `continue-on-error`.
  Failure mode: three failable steps once sat in that window and a GitHub
  Code Scanning outage alone was sufficient to ship an unsigned release
  (#441).  Note `if: always()` does NOT make a step non-fatal — it governs
  whether the step RUNS after an earlier failure, not whether its own
  failure propagates.  This rule is GENERAL, not about one file:
  `demo-publish.yml` had drifted into all three violations while the
  guard named only `docker-publish.yml`, so nothing caught it.  Guarded
  by `tests/unit/test_docker_publish_signing_window.py`, which is
  parametrised over both workflows — add any new publishing workflow to
  its `_CASES` table in the same PR that creates it.
- **Never** let an unrecognised secret classify as plaintext.  A classifier
  whose final branch is "anything I don't recognise is a literal password"
  fails OPEN on credential material: the digest is then re-emitted under the
  target's cleartext marker and BECOMES the password.  A bare crypt string
  carrying no algorithm tag — the form VyOS stores natively — did exactly
  this on 14 of 14 records, while both capability matrices declared the
  field SUPPORTED so the migration reported no loss at all.  Classify
  structured secrets by prefix, and make the default for an unmodelled
  `$id$` shape REFUSE migration.  Order matters when fixing this: recognise
  the known forms FIRST, then close the default — flipping the default
  first refuses every real record at once, which is a false-positive blast
  rather than a fix.  Note that refusing a secret drops the whole account,
  so the paired expectation YAMLs must be re-authored in the same change
  (doc-sync 178).  Guarded by
  `tests/unit/migration/test_secret_fail_open.py`.
  Classification is only half of it: **every codec that renders a local
  user must call `is_migratable()`**.  Four did not until #461, and two of
  them wrote foreign digests behind a cleartext marker regardless of how
  well the secret was classified.  A new user-rendering codec goes in
  `_USER_RENDERING_TARGETS` in that test file, which fails for any render
  path that skips the gate.
  And the gate is only half of a refusal: **the account goes with its
  secret.**  FortiOS, RouterOS and OPNsense called the gate, wrote the
  review line, and then wrote the account without its password --
  `edit` and an access profile, `add group=full`, a `<user>` element --
  and a RouterOS user added with no password has a blank one: on the
  committed captures, 93 accounts onto FortiOS and 99 onto RouterOS
  were written with no password, in jobs that reported the review
  line and nothing else.  Every check asked whether the SECRET reached
  the output; none asked whether the ACCOUNT did.
  `test_a_refused_secret_takes_its_account_with_it` reads every
  target's output for the account's name outside a comment.
  And never let a TAG decide the algorithm when the tag cannot be trusted:
  a vendor envelope (`junos:`) or a parser that tags everything one way
  (OPNsense `bcrypt:` over a `$6$` body) must defer to the payload's own
  crypt(3) id (#462).  Fails closed, but refuses every account it mislabels.
  And never take a TYPED password to be accepted everywhere: `plaintext`
  is an algorithm like any other, in a target's accept set only where
  the target has a line that takes a typed password and hashes it
  itself.  The policy called it "implicitly accepted by every target",
  and Junos and OPNsense, whose config holds a password only as a hash,
  wrote the typed string as the hash -- an account no password opens.
  Guarded by `tests/unit/migration/test_a_typed_password_is_not_a_hash.py`,
  which reads each target's output as text against that vendor's form
  for a typed password, typed by hand, not asked of the renderer.  The
  same holds for anything that REPLACES a secret: the sanitiser faked
  every tagged hash (`arista:sha512:`, `5 `, `junos:`, `sha1:`) and every
  AOS-CX ciphertext as `fake-hash-NNNN`, which the policy reads as typed,
  so a sanitised config held typed passwords where the device held
  hashes, and on Junos lost the account.  A fake is the same kind of
  secret as what it replaces (`tests/unit/tools/test_sanitize_keeps_a_secrets_kind.py`).
- **Never** re-emit a credential that is SALTED TO ITS SOURCE DEVICE.  An
  SNMPv3 USM key is localised against the agent's engine ID, so writing another
  vendor's key into the target's key leaf yields a config that commits cleanly
  and authenticates nobody — 30 records on the corpus before #463.  Where the
  canonical value is an opaque blob on both sides, gate on PROVENANCE
  (`tree.source_vendor`), not on the value's shape, and refuse rather than
  invent a plaintext form the target does not accept.
  Corollary (#464): where the target DOES have a portable form, use it rather
  than refusing — NX-OS localises a passphrase itself, so a passphrase must
  render WITHOUT `localizedkey`.  Classify the key by the SOURCE CODEC'S
  GRAMMAR, never by the value's shape: a sanitised fixture makes a localised
  digest look like a word.  Shared policy: `netcanon/migration/_usm_keys.py`.
  Corollary (#465): the portable form may be a DIFFERENT LEAF, not merely the
  same leaf without a keyword.  Junos derives the key from
  `authentication-password`, so a passphrase routes there while
  `authentication-key` stays reserved for Junos's own value; Arista's slot
  takes a passphrase and DERIVES the key, so feeding it a digest is the same
  defect wearing the opposite shape.  When a render starts emitting a leaf,
  teach the parser to read it back in the SAME change, or the recovery path is
  itself a silent loss.  And refusing a v3 user means refusing every line that
  composes it: a Junos VACM `security-to-group` binding left behind without a
  usable key is a half-configured account.  Gate on
  `auth_protocol or priv_protocol` -- gating on auth alone lets a
  privacy-only user carry a foreign key straight through.
- **Never** assume a credential surface is gated because its NEIGHBOURS are.
  Local-user password hashes (#460-#462) and SNMPv3 USM keys (#463-#472)
  each got a shared portability policy; RADIUS shared secrets, the third
  credential class on the canonical tree, had **no gate at all** until
  #482 -- every render path wrote `CanonicalRADIUSServer.key` verbatim
  into the target's key slot.  Five of the six leaked a FortiGate
  `fortios:ENC <blob>` -- a secret encrypted under the SOURCE device's
  own key -- into a field the target reads as the LITERAL shared secret,
  and the sixth ran it backwards, stamping `ENC` onto a plaintext secret
  from Aruba or OPNsense and so asserting a provenance the value never
  had.  Policy now lives in `netcanon/migration/_radius_secrets.py`.
  When adding ANY new secret-bearing canonical field, the question is
  not "does a policy module exist" but "does THIS field route through
  one".  Guarded by `tests/unit/migration/
  test_radius_secret_portability.py`, whose completeness test walks
  `list_public_codecs()` and fails for any target that emits a foreign
  encrypted secret.
  Two corollaries this class keeps re-teaching.  (1) Refusal granularity
  is per-surface, not universal: refusing a v3 user means dropping every
  line composing it (#465), but refusing a RADIUS secret must KEEP the
  server record -- a keyless `radius-server host <ip>` is a
  half-configured server the operator can see and finish, while a
  vanished one is an invisible hole in their AAA config.  (2) Closing a
  default must not become a false-positive blast: classify by envelope
  and PROVENANCE, so a plaintext secret that merely CONTAINS a colon
  (`my:secret`) stays migratable while an unregistered envelope from an
  unvouched source is refused.  (3) A gate reads what the parsers hand
  it, and is no better than their reading.  The IOS-XE CLI parser kept
  a `key 7` type IN the value (`7 <blob>`) and dropped it on the
  one-line form, the EOS parser read `key 7 <blob>` as the secret `7`,
  and the AOS-S parser read `encrypted-key "<blob>"` as the plaintext
  `<blob>`: none carried an envelope, so the gate called each a typed
  secret and every target wrote the stored form into its
  literal-secret slot, in jobs that said `completed`.  And the
  FortiGate parser put EVERY `set secret` behind `fortios:`, so a
  secret typed without `ENC` was refused everywhere.  What a value is
  is said by the grammar it was read from, which only its parser has:
  each parser envelopes its platform's stored form (`iosxe:`, `eos:`,
  `aoss:`, `fortios:`) and only that platform's renderer writes it
  back.  **The blind spot:** the gate's tests built their trees with
  the envelope already on, or parsed the FortiOS `ENC` form alone, so
  every value they handed it was already right -- and a parser test
  pinned the IOS-XE value `7 <blob>` as the key.  Guarded by
  `tests/unit/migration/test_a_radius_key_says_its_form.py`, which
  sends each stored form of each grammar through its parser onto
  every target and reads the output as text and with the target's
  parser; and the envelope-registry test now fails for a snippet its
  parser reads no keyed server from.
- **Never** put a value of the tree into a comment that a terminator
  ends without breaking the terminator in it.  A review comment names
  what was left out, as the source holds the name, and a block comment
  ends at its terminator, not at its line: on OPNsense a source account
  named `x--><user>...</user><!--`, refused for its password, came out
  as an account the source never had, holding whatever elements the
  name spelled out; `svc--backup` (XML allows no `--` in a comment) failed
  the render; on VyOS `a*/system{...}/*` left `system{...}` on the line
  as nodes.  The account was refused, so every check of accounts looked
  past it, and every check of a review line read that it was there.
  Build such a comment with `netcanon/migration/_comments.py`
  (`comment` / `comment_text`); a line comment is left as it is, since
  a value with a line break is another rule's.  Guarded by
  `tests/unit/migration/test_a_value_stays_in_its_comment.py`, which
  reads each block-comment target's output with a reader of its own
  (an XML parser; the `/* */` grammar) and reads the source for a block
  comment built around a value anywhere but there -- a table that is
  compared for equality, so a new one fails until it is mended or
  listed with why it may.
- **Never** hand text nobody vouches for to code whose cost you have not
  measured.  A config is whatever was pasted, a request carries megabytes
  of it, and a pattern at work does not let the server's other threads
  run.  Five shapes took time that grew with the SQUARE of the text, each
  in shipped code, each found after the one before it had been declared
  fixed:
  (1) **a line-anchored pattern that begins with `\s`**, applied to a
  whole text under `re.MULTILINE`.  `^\s+X` does not mean "X, indented":
  `\s` matches a newline, so from every line start the pattern walks to
  the end of the run of blank lines it is in.  A probe window of lines of
  spaces held `/detect` for about a minute.  Write `[^\S\n]` (white space
  that is not a newline — `arista_eos/parse.py` already called it `_WS`).
  It was also not what the pattern meant: `^\s+bgp\b` matched a
  top-level `bgp` line that followed a blank one.
  (2) **a lazy value in front of trailing white space** — `(\S.*?)\s*$`
  re-reads the rest of the line for every character it takes.  Write
  `(\S(?:.*\S)?)\s*$`: from the first character that is not white space
  to the last.  And its cousin, two runs that can each take the separator
  between them (`\S+:\S+`, `[ \t]+.*`): make one of them unable to.
  (3) **a search that fails and starts again inside the run it has just
  crossed** — `(\d+)$` on digits and then a letter, `([\w-]+)=` on a long
  word.  Say where the thing begins: `(?<!\d)(\d+)$`.
  (4) **code that is no pattern at all**: a continued line joined with
  `buffer += ...` and trimmed with `buffer.rstrip()[:-1]` copies everything
  gathered so far for every line it grows by.  Parsing three megabytes of
  RouterOS lines that each end in a backslash took two and a half minutes.
  Gather pieces and join once.
  (5) **a handler that runs once per line and looks through everything
  the earlier lines made** — `next(r for r in intent.routing_instances
  if r.name == name)`, `any(...)` over the routes so far, `name in
  a_list`, `{i.name: i for i in intent.interfaces}` built for every
  `trunk` line, a pass over every interface at the end of every block.
  Nothing about one such line is slow; the cost is the square of the
  NUMBER of stanzas, on a config with nothing odd in it.  Six thousand
  RouterOS DHCP networks and their pools took 37 seconds; an Arista
  `interface Vxlan1` stanza written six thousand times, 9; sixteen
  thousand Junos static routes, 7.  Find the record by key:
  `GrowingIndex` (`netcanon/migration/codecs/_helpers.py`) reads each
  record of a growing list once, whoever appended it, and a pass over the
  whole tree is made once, after the last line.
  The first of these was fixed as "the class", with a test that timed
  whole filler lines and short units repeated from the first character;
  it passed, and the next three were then found by reading — one of
  them in a file that change had edited.  The fifth was found after the
  test had been rewritten to build its texts from each pattern: no text
  built from a pattern or a run has many stanzas in it.  **A check does
  not reach further than the texts it builds**, so
  `tests/unit/test_untrusted_text_cost.py` builds each text from the thing
  it is for: for every regex the product holds (source literals, compiled
  patterns and pattern-shaped strings a module or class keeps, patterns in
  the shipped device definitions) what the pattern needs before one of its
  repeats, then a run of what that repeat accepts, then something the rest
  refuses; and for every public codec's `probe` and `parse`, a real capture
  with a run put into it — of empty lines, of lines that go on (a
  continuation, an open quote, an open brace), of white space inside each
  of its own lines.  The fifth shape has a search of its own, which
  takes minutes and is run by hand: `tools/stanza_cost_search.py` writes
  every line and block of every capture many times over.  **Run it when
  you change a parser's handler or add a codec**; what it found is pinned
  in the same test module, a text for each handler that was mended, and
  a new finding is added there with its fix.  None of it is a proof.
  Not reached: a pattern assembled at call time from parts that are not
  literals and not kept; a handler no capture has a line for; work that
  needs two kinds of stanza to grow together; a shape nobody thought to
  build.  A sixth shape was known when that list was written, and is
  mended: a list of ONE record that a line adds to after reading it
  (`if pair not in entry["ipv4"]: entry["ipv4"].append(pair)` — the
  addresses of one interface, the members of one LAG, the route targets
  of one VRF).  No index of the records helps, there being one; use
  `Uniques` (beside `GrowingIndex`), or keep a set beside the list.  The
  test module reads the source for that idiom, and a new one fails
  until it is mended or listed there with the bound that makes it
  harmless.  None of this is about what a config EXPANDS to (`1-4094`
  is seven bytes) or the product of two kinds of stanza that grow
  together: those are counted and limited, by the rule after this
  one.  When you find a
  shape the search missed, add it to the search in the same change as
  the fix.  A pattern that is slow and safe (it reads only data the
  server ships) goes in that module's `KNOWN_SLOW` with the reason; an
  `re` call whose pattern is not a literal, or whose flags are not
  written out, goes in `NOT_LITERAL` with what covers it.  Earlier fixes
  of single patterns are pinned in
  `tests/unit/migration/test_redos_hardening.py` and
  `test_parse_quadratic_scan_perf.py`.
- **Never** turn a few bytes of a config into many entries without
  counting them first, never loop over a config's lines without looking
  at the deadline, and never catch broadly between the two and their
  caller.  A range is thousands of entries, `all` is 4,094, two honest
  counts multiply, and an interface stanza is one line: the size of a
  text bounds neither the memory a request takes nor its time.  One
  AOS-S line of 800 port ranges (11 KB) was 295 MB to parse; 1,000
  trunks that allow `2-4000` were gigabytes; 50,000 one-line interface
  stanzas (0.9 MB) were 240 MB.  `netcanon/migration/limits.py` counts
  what a request makes and refuses past a limit, in a sentence:
  (1) **an expander charges before it makes** -- `charge("vlan_ids",
  high - low + 1, token)` on the line before the list -- so that the
  refusal comes before the memory is spent.  The count of every
  finished parse (`census`, at the boundary every `parse` crosses)
  holds a tree whose expander nobody found to the same limits, after
  the fact; a test tells the two apart, and fails a parser that is
  refused only there.  What stands for many entries is not always a
  token.  A trunk that states NO allowed list is the 4,094 ids on
  four platforms, from a stanza of two lines: it is charged as `all`
  is, where its list is made (`unstated_trunk_list`), and so are the
  copy a first `add` or `remove` starts from and the list each
  record of a stanza met again is given (`TrunksByName`).  When a
  value is given a meaning that is thousands of entries, look for
  every place that now MAKES them: the rule that reads the source
  finds a new `range(...)`, not a copy of a list that has grown.
  (2) **a loop over lines goes through `ticked(...)`** (a `while`
  calls `tick()`), in every module that reads config text.  A thread
  cannot be stopped from outside; only work that looks at the clock
  stops.  A text that is not read a line at a time is walked all the
  same: hierarchical Junos is cut into tokens a character at a time,
  and whoever takes the tokens takes them through `ticked(...)` --
  the rule that reads the source knows a loop over lines, and does
  not know that walk, so it has a test of its own
  (`TestJunosAsPrinted`).
  (3) **a broad `except` on the way names `LimitExceeded` first.**  The
  handler round the Junos block-form conversion turned a refusal into
  advice to run `display set`; the per-probe net in detection would
  turn "out of time" into "no codec knows this text".
  And a refusal is a RESULT, with the same care a translation gets: a
  `failed` job whose `error` begins `refused:` (never `parse failed`,
  which the migrate page answers with "did you mean another vendor?")
  and whose `refusal` says the same as data; HTTP 413 from the
  sanitiser; a note from `detect-deployment`; exit 2 from the command
  line.  It names what was large, how large, and the limit, and under
  the public demo's limits it names no setting, because a visitor
  cannot change one.  What a refusal quotes from the config goes to
  the client and NEVER to a log.  Every handler that takes config text
  opens the SERVER's scope with the server's own setting
  (`limits.server_scope`, `_migration_helpers.request_limits`): work
  that opens none runs under `standard`, which on the demo is several
  times what an instance holds.
  (4) **every limit is for ONE request, and "one request fits" was
  measured one request at a time.**  Two of the largest requests the
  demo's limits admit, at once, ended an instance either fitted in --
  and the sanitise page itself sent two at once.  Under `small` a
  server therefore works on one request at a time, the turn taken
  where the scope is opened.  Serialising the WORK was not enough, and
  the measurement said why, three times: the answer was made after the
  handler returned, by the framework, at several times its size (a
  job handler returns `job_answer(...)`, and the turn stays with the
  request until its answer has gone out); memory a thread freed was
  kept for that thread (a request with its turn trims first); and a
  body was read before its request could ask for a turn, so a burst
  of bodies ended an instance that refused nearly all of them (a
  request is counted when its HEADERS arrive, in the outermost
  middleware, and one more than may work and wait is answered there,
  unread).  Two more of the same kind, each found by a client that
  did not behave.  **A limit that gives a turn back and keeps the
  memory has limited nothing**: the turn lent to an answer nobody
  read was taken back at the deadline and the answer stayed, so four
  of them ended the instance one at a time -- at its request's
  deadline an answer that has not gone out is abandoned.  And **"the
  server took it" is not "it went out"**: a server takes a whole body
  into its buffer at once, so an answer is handed over a little at a
  time.  And "the server closed the connection" is not "the connection
  is closed": a server closes one when what it wrote has been taken,
  and a client that takes nothing kept megabytes of socket buffer for
  as long as it stayed -- which only the system can end, so the
  launchers ask it to (`listening_sockets`).  Read what the CONTAINER
  holds (`memory.stat`: `sock` is the server's too), not what the
  process holds.  Measure a memory limit in a container shaped
  like the target, with requests AT ONCE, with clients that leave,
  stall and do not read, and many times over -- an
  instance does not come back down, and four rounds do not show where
  it levels off.  And say busy as busy: a request that waited for its
  turn and then ran out of time was refused as slow, with advice to
  run a server that allows more time.
  The deadline does not stop a renderer; SECURITY.md
  says so, and a test pins that the document says no more than the
  code does.  Guarded by `tests/unit/migration/test_limits.py` (each
  limit; every codec's parse stopped at a deadline it has passed;
  the three rules above read from the source, each with a table a new
  case fails until it is in) and
  `tests/integration/test_config_limits_api.py` (every handler that
  takes text, found by what it takes).  A number changes in
  `limits.py`, in the documents and with the measurement that says
  why: `tests/unit/test_limits_docs_truth.py` holds the three together,
  and `small` was sized in a container shaped like a demo instance
  (`docs/demo-plan/07-budget.md`).
- **Never** express a CI tool version as a RANGE and call it pinned, and
  never repeat that version in a second file.  CI installs fresh on every
  run and pip resolves to the newest match, so a range silently adopts
  releases: `ruff>=0.15,<0.16` took 0.15.18 through 0.15.22 with no PR and
  no review (#442).  Pin exactly, in the manifest Dependabot watches
  (`pyproject.toml` — a pin buried in a workflow `run:` block is invisible
  to it and freezes the tool instead), and have the workflow DERIVE the
  value rather than restate it — a duplicated constraint is what makes a
  dependency-bump PR inert, since the gate and the declared dependency can
  disagree with nothing noticing.  Guarded by
  `tests/unit/test_ruff_pin_is_exact.py`.
- **Never** author or change a codec's `device_classes[0]` without applying
  the scope test.  A codec's **first** entry in `device_classes` — declared in
  `netcanon/migration/vendors/<vendor>.yaml` and mirrored in its
  `CapabilityMatrix` — is its **primary device class**, and that single field
  is the project's authoritative scope declaration for the platform.  Order is
  therefore load-bearing: re-ordering an existing codec's classes is a scope
  change, not a tidy-up.

  A platform is **`firewall`-primary** when **both** hold:
  **(a)** the modal *real* config of that platform is majority Tier-3 by
  volume — the canonical model covers a minority of what an operator actually
  wrote; **and**
  **(b)** the platform is not deployed as a switching or routing NOS in its own
  right, so its L2/L3 surface is incidental rather than the reason the box
  exists.

  Both clauses are required.  Clause (a) alone would take `cisco_iosxr`
  (MPLS / IS-IS / route-policy dominate real SP configs) — clause (b) saves it.
  Clause (b) alone would take nothing.  Junos is the worked example of why the
  test is two-clause and not one: Junos ships on SRX firewalls and declares
  `firewall`, but it is `switch`-primary because EX / QFX / MX are Junos boxes
  in their own right.

  **What `firewall`-primary means, operationally.**  Netcanon translates that
  platform's L2/L3 layer only.  Such a codec **must not** be a landing-page
  hero pane, **must not** be the landing-page capability-matrix excerpt, and
  **must not** be more than one of the four `netcanon/tools/demo.py` scenarios.
  It **may** ship, be certified, hold fixtures, be auto-detected, be
  sanitisable, and participate fully in the cross-mesh audit as a source.
  Enforced by [`tests/unit/migration/test_scope_boundary.py`](tests/unit/migration/test_scope_boundary.py),
  which pins the roster, asserts the codec ↔ vendor-YAML agreement, and
  ratchets the demo-scenario count.  ⚠️ The scenario clause is **not yet met**:
  HEAD carries two firewall-primary scenarios (`fortigate__mikrotik`,
  `opnsense__junos`) and the guard ratchets at 2 with a target of 1, because
  closing it re-authors a demo scenario and drags the hero pane, `og.png` and
  the paired walkthrough with it.  Lower the ratchet when that wave lands;
  never raise it.

  Rationale: the scope complaint this rule answers was *perception weight*,
  not correctness — nothing over-claimed, but two of twelve codecs held a
  disproportionate share of the product's shop window.  Encoding the answer in
  `device_classes[0]` means it is read from a declaration rather than
  re-derived from a measurement every time someone asks.  Full workings in
  `docs/reviews/2026-08-10-firewall-scope-exit/`.
- **Never** take a target-profile port id from `format_port_identity`, a
  sibling model, or recall.  A profile id is written **verbatim** into the
  generated config when an operator picks it, so it must be the name the
  hardware itself prints: take it from a capture of that exact model or the
  vendor's own documentation, and grade it (`evidence` + `evidence_ref`).  If
  the right name is not established for that model, **flag** the profile
  (`evidence: inferred` + `caveat`) rather than swapping one plausible name
  for another.  Failure mode: a third of the shipped profiles named ports the
  device does not have — `1/A1` uplinks on a switch with no module slot, a
  stacking module and a power supply offered as 40G uplink modules, an
  AOS-CX switch filed under AOS-S — because the authoring guide said to
  derive ids from the formatter, and because part numbers were paired with
  the wrong row of a vendor table.  Two corollaries.  (1) A port's name is a
  function of the model **and** its deployment state (stacking, breakout,
  port speed), so a profile describes one state and says which.  (2) A
  self-consistency check is worthless here: a profile that agrees with the
  codec proves nothing, since both can be wrong together.  Guarded by
  `tests/unit/migration/test_target_profile_evidence.py`, which re-proves
  every `capture` grade against a fixture that must identify itself as that
  model.
  The same rule governs the model families under
  `definitions/library/model_families/`, whose names are computed and
  then written into a config just the same.  More corollaries from
  building those.  (3) `capture` is GRANTED to one exact deployment
  (model, mode, member id, module), never inherited: a sibling with
  identical port names, a TAA twin, or the same model as member 2 is a
  deployment no capture shows.  (4) A capture can prove NAMES and
  nothing else — on a grammar with no role in the name, two port
  groups written in the wrong order produce a byte-identical name list
  with the uplinks on the wrong ports — so every shipped model's
  `(name, role)` sequence is also pinned by hand.  (5) `capture` means
  "a test re-proves it on every run", so only the claims that test
  re-proves grant it (`PROVEN_CAPTURE_CLAIMS`): a claim in an
  operator's own family file names a fixture nothing reads, and
  grants nothing; and an entry is the WHOLE claim, so a proven fixture
  cited for another model grants nothing either.  Guarded by
  `tests/unit/migration/test_device_models_shipped.py`.
- **Never** leave a port name to the name-shape translator without
  checking what it made of it.  Positional mapping decides the ports it
  pairs and the data ports it cannot place; an off-inventory name and
  an unplaced management port go to the translator instead, and its
  answer can be a port the pairing already assigned — two source ports
  on one target name, in a job that reports success.  Failure mode,
  caught in review before release: between two shipped MikroTik
  profiles a management `ether1` and a paired SFP+ port both ended on
  `ether1`, two addresses on one interface, `completed`; and the test
  suite's own Catalyst scenario put `AppGigabitEthernet1/0/1` on the
  port `TenGigabitEthernet1/0/1` was paired to.  "The map is total
  over the ports I decide" is not "no two ports share a name in the
  output".  The mapper cannot predict the translator without
  re-deriving it, so `run_plan_with_models` asks the finished run
  (`fused_targets`), drops any name nobody decided that collides, runs
  once more, and records the outcome on the plan (`settle_plan`).
  **The check must read the universe the translator rewrites, not the
  set the plan was made for**: the first version of it looked only at
  the hardware ports, and a FortiGate aggregate whose codec classifies
  its name as a physical port still landed on a paired port, unseen —
  the same defect one level down (#498).  **And that universe is a
  set of FIELDS, not of names**: the next version read every name the
  rename pass rewrites, and RouterOS keeps a port's hardware identity
  in a field the pass did not rewrite (`default_name`), which its
  renderer uses to find the port — every moved port came out as
  "find the port with the OLD name", in a job that reported success,
  on a committed capture.  **And a fix made in shared code is a change
  for every caller of it**: that field was then rewritten by the
  translator itself, which is right for two declared devices and wrong
  for the commonest entry of a rename map on RouterOS — one that gives
  a port a NAME.  `{"ether1": "WAN"}` had always rendered
  `find default-name=ether1 ] name=WAN`; it rendered
  `find default-name=WAN`, a lookup no device matches, with no devices
  declared and nothing reported — and "the ordinary path did not move"
  had been measured with an empty port map only.  A port's factory
  name says which hardware it IS; it is not a reference to the port.
  And it is a name the DEVICE gives, whole: the parser took any name
  that began `ether` and a digit for one, in any letter case, and
  looked `ether1_ADMIN` up as hardware no device has, while an SFP
  port the config named only in `/ip address` had none and was
  looked up by its new name.  The shapes come from the vendor's
  manual and exports (`is_factory_port_name`), never from a prefix.
  The translator leaves it alone, and `run_plan_with_models` — the one
  caller that knows the target device — sets it, and reads back from
  the tree that is rendered where each port's hardware ended.  Nothing
  else can tell a name from a move: `sfp1` is a port of one RouterOS
  model and a short name for a port of another.  When a change touches
  `translate_port_names`, replay requests that CARRY a port map against
  the base branch, not only requests without one — every committed
  capture through `run_plan_with_overrides` on both branches, with
  maps built from the names the capture holds.
  **And "the case I built it for" is a narrowing too**: that handling
  first acted only between two RouterOS configs, and only on a port
  whose factory name the config happened to state, so a port named
  from any other vendor — and any port an export gives no
  `/interface ethernet` line of its own — still came out as "find
  the port with this name".  What decides whether a target
  needs a factory name is the TARGET (`ports_keep_a_factory_name`),
  not where the config came from.  **And the tree is not the
  output**: a factory name set on the tree is not a line that finds
  the port — the RouterOS renderer writes none for a name shaped like
  a VLAN, a bridge, a LAG or a loopback — so the rendered output is
  parsed again with the target's own parser, and a port no line of
  its own looks up is reported (`unbound_ports`) rather than said to
  be where the tree put it.  **And a check must not inherit the reach
  of what it checks**: that read-back first walked only the ports
  recorded by the step that sets the factory name on the tree
  (`_hardware_binder`), so a paired port the config has no interface
  for — a LAG member, a route's interface — was written under an
  operator's name into `slaves=` or `gateway=`, defined by nothing,
  and reported only as a name the device model does not list, in a
  job that said `completed`; and it asked whether ANY line looked a
  piece of hardware up, not whether the port's own did.  Feed a check
  from the widest list there is (the pairing, not that step's
  record), and judge each item by its own evidence.  **And what a
  parser cannot give back, it cannot give back anywhere**: one half
  of that read-back allowed for a name the parser reads otherwise
  than it was written, the other looked a name up as an exact string
  — and a port named `my port`, written into an unquoted list, went
  unreported once more, past a test oracle that asked the same
  parser the same question.  Where a check compares a name with what
  was read back, allow for the reader's losses in every branch and
  for every list (a member list and a next hop are not cut at the
  same characters), and give its oracle another way to look (the
  text).
  **And a job from a codec to itself changes no name unless an entry
  says so.**  The translator asks the source codec to classify a
  name and the target codec to write it, and that round trip is not
  the identity on several codecs' own names (AOS-S, IOS-XE CLI,
  OS10, FortiOS, Junos and VyOS, over the committed inputs; the
  guard below keeps that list).  A Junos config translated
  to Junos came back with `fxp0` as `em0` and with the tagged unit
  `ge-0/0/1.54` on `ge-0/0/1`, its `vlan-id` gone; FortiOS `dmz` came
  back `dmz1`; a Catalyst's management port and every OS10 breakout
  lane were dropped — all on committed captures, on the commonest
  request there is (no port map at all), in jobs that said
  `completed`.  Every guard compared one output of the translator
  with another, and a loss common to both cancels: the experiment
  below pins each port to its own name first, which is an entry.  A
  name nobody mapped stands between two configs of one codec, and a
  sub-interface goes where its port goes with its unit — no
  classifier keeps one.  Compare the translator's output with
  something it had no hand in: the bare pipeline's output for every
  committed input, and each sub-interface found in the output by its
  address, from every grammar that names one onto every codec.
  Guarded by
  `tests/unit/migration/test_units_follow_their_port.py`.
  **And a name that moves does not carry what is not in the name.**
  A sub-interface's 802.1Q tag is a field of the tree, and some
  parsers read none (AOS-CX, OS10): sent after its port, such a
  unit was an interface with no VLAN on a target that would have
  carried the tag, in a job that said `completed` — where the
  stranded name it replaced had at least been said.  There is no
  tag for the validation report to list, so the translator says it
  (one warning a unit) and, with devices declared, the unit is not
  counted as having followed (`untagged_units`) and the job is
  `partial`.  When a rule starts to move a name, ask what the name
  stood for that the rule does not move, and what said so before.
  **And ask what reads the name where it lands.**  A unit sent after
  its port arrives as `<port>.<unit>`, which the FortiOS and VyOS
  renderers make a VLAN id of.  A pasted config can write more digits
  after a dot than an integer is converted from.  A translator that
  makes a number of the unit, to ask whether it is 0, fails the job
  on every target; and with no conversion of its own the same name
  still fails the job in those two renderers.  A unit is read as text, and
  across vendors one of more than ten digits (`UNIT_MAX_DIGITS`) is
  not sent after its port: no longer run of digits reaches another
  vendor's renderer by this rule.
  **And a warning is not a status.**  Every check above was built
  where devices are declared.  With none, what the translator found
  reached the job as warning lines and the status was the validation
  report's alone: two source names on one name of the output, a name
  dropped because the target has none for it, or a name the
  translator could not read written into another vendor's config as
  the source has it, in a job that said `completed` — more than a
  third of the jobs that said so over the committed captures, each
  onto each codec with no port map (the guard below pins the count,
  by source codec and reason).  `run_plan_with_checked_names` reads
  the finished run for all three and makes such a job `partial`,
  with the names as fields (`fused_ports`, `unresolved_ports`,
  `untranslated_ports`), and every plan endpoint reaches it through
  `run_translation`.  What it took.  The
  condition is over EVERY name the translator rewrites: with no
  pairing to protect, the model path's reason for looking only at a
  clash that has a hardware port in it does not apply, and the two
  loopbacks of two routing instances on one loopback are in no
  port's clash.  What shares a name is not always two interfaces —
  Junos refers to `lo0` as `lo0.0` — and what tells them apart is
  the tree that was RENDERED (how many interfaces it holds under the
  name), not the shape of the names: a VyOS `vif 0` is unit 0 with a
  stanza of its own.  **"Hardware port" was a narrowing too**: the
  first version listed a dropped name only where it was a hardware
  port, and a FortiGate hardware switch that holds the LAN address —
  an aggregate, to its classifier — was dropped in a job that said
  `completed`, past a test oracle that asked the same classifier
  which interfaces were ports.  A loopback, a tunnel or a hardware
  switch is as lost as a port, and the oracle asks after every
  interface that has an address.  **And what the translator does not
  say as data, nothing can hold a job for**: a name it could not
  classify stayed in the tree under its source name with a warning
  line and nothing else.  `PortRenameResult.untranslated` says it —
  for a name the config CONFIGURES something under; one it only
  refers to (a route to `Null0`, a VXLAN source address) is listed
  apart, since what those places hold is not always an interface,
  and a job is not held for every route to nowhere.  A canonical
  field that holds a port name is a place the config configures one
  unless `_only_referred_to` is told otherwise: the reading that
  reports more.  An entry decides such a name: another name, `None`,
  or the name ITSELF.  **And "left as it was" is not "under a
  foreign name"**: listing every name the classifier could not read
  made every AOS-S config with a VLAN address `partial` on every
  target — the three whose own name for that interface is exactly
  the `Vlan<id>` that was left included — and listed
  `GigabitEthernet1` between the two codecs of IOS-XE.  A status
  that is raised over a right output teaches its reader to click
  through it.  A name the translator left is not listed between two
  codecs of one platform (one `vendor_id`), nor where the target
  itself WRITES that very name for the kind of thing the source
  parser read from context (`_the_targets_own`).  "The target
  reads it" was not enough to ask: OS10 reads `Vlan10` and prints
  `vlan10`, OPNsense reads any `<name>.<n>`, and on FortiOS or
  RouterOS every string reads.  Nor is a hardware port ever
  vouched for by a name, nor a name from a platform where names are
  free text (a RouterOS `vlan100` may carry VLAN 20).  How many
  names are not listed is pinned by pair of codecs (`_STANDS`): a
  number that moves there is a name that left the list, and its
  line of the output is read before the table is changed.  **A
  status an entry cannot clear is a trap**:
  four of the per-pane endpoints set a posted port map aside, so a
  job that was `partial` there for its names could not be settled
  there, and every plan endpoint applies the body's port map now.
  **So is a status that something short of an entry clears**:
  `{"mgmt0": ""}` was an entry, so it cleared `partial`, and was a
  name, so it wrote an interface with none.  A value is a name or
  `None` (`names_a_target`), and the API refuses a blank one — and
  blank is what DRAWS nothing, not what `strip()` empties: a
  zero-width space passed that, and wrote an interface whose name
  nobody can see.
  **And advice is a claim about another path**: the sentence ended
  "or declare both devices", and for two loopbacks on one loopback
  the path with devices says `completed` for the same output.  Offer
  a way out only where it settles what is listed (`_names_message`
  asks whether a hardware port is among it).  **And advice is
  mended wherever it is given**: with the sentence corrected, the
  strip of the rename modal still ended "Choose the target device
  to pair ports by position" beside one chosen device, whatever
  was listed — the same claim, made by other code.  It now says
  there that the pairing settles none of the names when none is a
  hardware port; and an offer needs something to choose from, so no
  pair is offered for a vendor nobody has described a device of.
  The page obeys the
  same authority: with no plan on the job, rows that are as the job
  was made collide only where the job lists them (`jobFusedRows`),
  or Apply is held on a job the server called `completed` until the
  operator breaks something to free it.
  The guard does not ask the function it guards, nor take its list
  of names: it reads the rendered output back with the target's
  parser and finds interfaces BY ADDRESS — no interface of a
  `completed` job carries the addresses of two source interfaces,
  and no interface that has an address is missing — and reads the
  translator's own warnings for a name the source config configures
  that was left under a foreign name, over every committed capture
  onto every codec.  Which names left are the target's own it
  decides for itself, from the text of the output and a table typed
  by hand (`_OPENS_A_VLAN_INTERFACE`), not by asking the codec the
  question the pipeline asks it.  It counts how often it was asked,
  since a loop that reads
  nothing back passes; and it is itself handed a job with each
  defect.  It sees what an address shows and no more; two access
  ports on one name are the condition's own tests'.
  Guarded by `tests/unit/migration/test_run_plan_checked_names.py`.
  A list of places written by reading the tree cannot show that it is
  complete, and a test that walks the same list agrees with it.  So
  completeness is also checked by experiment:
  `tests/unit/migration/test_port_name_universe.py` sends port names to
  one another through the translator on the committed captures and
  compares the two outputs, parsed again.  It needs no list of fields —
  and it reaches a field only where a capture puts a moved name in it
  and the codec's own parser reads that field back, and only for names
  the device already has.  The same module breaks the translator at
  each place in turn and pins which places a capture catches; each of
  the others has a small config there that does.  A canonical field
  that holds a port name goes in `collect_port_names` and in the rename
  pass, and — unless a committed capture fills it — gets a small config
  in that module; the table, the pass and the collector are compared
  on a tree built from the schema (a name in every `str` and
  `list[str]` field; a field holding text in another shape fails the
  builder until it is taught the shape), so no hand-kept fixture
  stands between them.  Whether a name in another letter case can be another
  interface is a fact about the platform, and there is no safe default
  for it: every codec states `port_names_case_sensitive` in its own
  class body (`True` only where an operator chooses interface names as
  free text, as on FortiOS and RouterOS — an override typed `1/a1`
  cannot hide behind its spelling on AOS-S, and `DMZ` is not folded
  into the port `dmz` on FortiOS), and
  `test_the_codecs_say_which_they_are` fails for one that leaves it to
  the base class.  The same goes
  for what a plan SAYS: build its warnings and its dropped/kept flags
  from the run, not from the intention — a port the operator kept must
  not be reported as dropped, nor a port the translator dropped as
  kept, nor a route that went with a dropped port left unmentioned.
  Guarded on the jobs of
  `tests/unit/migration/test_run_plan_with_models.py`, whose wrapper
  recomputes the grouping for itself — written out in the test,
  because a guard that calls the function it guards shares its blind
  spot (the list of names it groups is still the engine's) — and reads
  each job's RENDERED OUTPUT back with the target codec: an interface
  that can be recognised by its address must be on the port the job
  reports, the output must name no port the job does not report, no
  name that moved may still be in it, and no interface may carry the
  addresses of two source interfaces.  A check nobody has seen fail is
  not known to check anything: each of those is handed a job with the
  defect it is for, in the same module, and has to fail — and so is
  the wrapper, once per assertion, because a check that is never
  CALLED passes every test too.
- **Never** write a target's word for "everything" for a list that is
  not everything.  `vlan members all` is every VLAN the switch has and
  every VLAN it is given later; the Junos renderer wrote it for any
  trunk list of 4,000 ids or more, so `switchport trunk allowed vlan
  1-99,101-4094` — a line whose whole point is VLAN 100 — came out as
  `all`, VLAN 100 back on the trunk, in a job that said `completed`
  with nothing to report.  The shared projection read `2-4094` as
  "all" as well and stamped the trunk onto a declared VLAN 1.  A
  shorthand is right for the exact set it names and for nothing near
  it: "long enough" is not "all", "all this config declares" is not
  "all", and the ids a nearly-full list leaves out are the ones the
  operator wrote the list for.  Where the target can state the list
  as it stands (Junos takes ids and ranges as members), write that.
  The audit had the evidence and it was explained away: the only
  committed trunks that leave a VLAN out are two Arista `2-4094`
  peer links, and the VLAN 1 they gained on Junos was pinned by a
  test as "a documented one-VID asymmetry".  Guarded by
  `tests/unit/migration/test_a_vlan_left_out_stays_out.py`, which
  renders such trunks onto every public codec and reads the OUTPUT
  three ways — the target's parser for the VLAN left out and for the
  declared VLANs the list holds; the whole list as a set where the
  target's parser reads one (the declared VLANs are a handful of
  ids, and a renderer that lost thousands of the others passed the
  first reading alone); and the text for the word itself, since a
  parser can read its own word for "all" as something a check of ids
  does not see (AOS-CX read it as an empty list).  The same class was
  open one step on — an EMPTY list written as every VLAN on four
  targets — and that module pinned which.  It is mended, the pin is
  gone, and the assertion that no target does it stays there; what
  made it is the rule on "not stated" below.
- **Never** translate a statement the source device holds and does not
  run, and never read a form of a platform's config you do not parse as
  an empty config.  Junos prints `inactive:` ahead of a deactivated
  statement (`deactivate <path>` in set form), and the parser read both
  as configuration: a deactivated BGP neighbour, firewall term or port
  came out live on the target, in a job that said `completed`.  And a
  `show configuration` pasted as the device prints it (braces, where the
  parser's own form is `display set`) was read as nothing at all on
  every public capture tried — an empty config and a bare scaffold for
  output, or a refusal — while detection offered no codec.
  A statement that is not in force is LEFT OUT AND SAID: one row in
  `dropped_tier3_sections`, which shows the path and never a value (a
  row is painted on a page and returned to every client, and a path is
  keyed by its secret often enough), in a list that is bounded.  Such a
  row is not a sign that the parser recognised the text
  (`is_left_out_row`): a config that is all deactivated is not
  `completed`.  What it took to get wrong twice: a form is not read
  until every wrapping a terminal puts around it is (a prompt, a pager
  line, a byte-order mark, carriage returns), and a comment begins only
  where the grammar lets one begin — `member ge-0/*/*;` holds no
  comment.  Each form a parser reads is held beside the other, typed by
  hand, so that neither is the oracle for itself:
  `tests/unit/migration/codecs/juniper_junos/test_two_forms_one_tree.py`
  and `test_statements_left_out.py`.
  **And a stanza ends where the DEVICE ends it, not where the printer
  happens to indent.**  The AOS-S parser ended a `vlan`, `interface`
  or `vrrp vrid` stanza at its `exit` or at any line in column 0, and
  skipped every indented line after that: a KB.15.15 capture committed
  with every line at column 0, its indentation lost between the switch
  and the repository, was three empty VLANs and no interface, in jobs
  that said `completed` onto most targets (AOS-S itself among them),
  no job said a line was not read, and its RESULTS row gave another
  cause for the empty tree.  HPE describes a context by commands --
  `exit` returns to the previous one, `end` to the Manager level, a
  command that enters another context leaves the open one -- and no
  HPE switch guide says anything of indentation.  So the stanza ends
  at its `exit` or an `end`, or at a line in column 0 that enters a
  context or that the top reads (`_ends_the_stanza`: ONE predicate,
  built from the top's own patterns, which a test holds to the loop),
  and a context whose words the top reads otherwise (`oobm`'s `ip
  default-gateway`) is a stanza none of whose words a handler of the
  top sees.  **The blind spot:** every check read the captures as
  printed, and the one test that pinned the old rule pinned a shape
  the renderer writes.  A form the device takes is a form to read: the
  parse of every AOS-S input with its indentation removed is held to
  the parse of the input
  (`tests/unit/migration/codecs/aruba_aoss/test_where_a_stanza_ends.py`).
  The other block parsers refuse such a text in words (below), and
  VyOS keeps its tree and loses a Tier-3 row; the CHANGELOG's known
  limitations say so.  **And where the device places a line BY its
  indentation, a text without it is a form the device takes but does
  not apply as written: it is refused in words, never read.**  IOS XR
  loads a file by its indentation (its vendor page says what that
  rests on), so a flat IOS XR text was interfaces and VRFs made of
  lines nested under routing protocols, users with no secret, and not
  one address, in jobs that said `completed` -- and the router would
  have misplaced the same lines.  A form of the platform's own that
  the parser was not written for is refused the same way (the `show
  running-config formal` form of a whole config: a setting on its
  `interface` lines).  The sentence names a line and quotes nothing of
  the text, for a parse failure is logged.  And a submode's `!` does
  not end the stanza it is in: the IOS XR interface parser ended an
  interface at the `!` of its `ptp` block and lost every address after
  it, on a committed capture of a certified codec.  **The blind
  spot:** every check read that capture through the parser that lost
  the lines -- the mesh compares the source's tree with the target's,
  and an address neither holds is no drift -- and the scanner's own
  test pinned "an indented `!` closes a stanza" as its rule; the guard
  counts each interface's address lines by its indentation, by hand
  (`tests/unit/migration/test_cisco_iosxr_indentation.py`).
  **And where the device reads a text without its indentation by the
  mode each command leaves open, reading it needs every mode's
  words, which the vendor does not list: it is a form the device
  takes, and still not one to read -- unlike AOS-S, whose printed
  `exit` closes each context, the text says nowhere where a mode
  ends -- so it is refused in words, with the parser's reason, not
  the device's.**  EOS runs a typed or pasted line in the deepest open
  mode that accepts it (Arista's transcripts show it), and Arista's
  own generator deploys a config through eAPI as a flat stream, so a
  flat EOS text has a meaning to the switch (inferred) -- but no
  Arista page lists the words each mode takes, and the parser had
  read such a text as a second VLAN for each `vlan` block under
  `router bgp` and not one address, in jobs that said `completed` or
  were `partial` for another reason, none saying a line was not read.
  The sentence says what the parser cannot do, never what the switch
  would do.  The AOS-CX, IOS-XE CLI, NX-OS and OS10 parsers refuse
  such a text the same way, and the check counts as indentation what
  their READERS count: they take any white space for it, and a check
  that knew a space or a tab alone would have refused a text indented
  with no-break spaces that they read whole
  (`first_flat_stanza(..., any_white_space=True)`,
  `tests/unit/migration/test_a_flat_text_is_refused.py`).  Nor is a depth rule a reading where the device places a
  line by its mode: inside an EOS interface no depth tells a
  submode's line from the interface's own, so every indented line is
  the interface's (a known limitation), and only `router bgp`, whose
  blocks are real, is read by depth.  **And a body that runs to its
  own end (`EOF`) is text, never lines of the config: unread, a
  banner became an administrator account.**  A printed `banner motd`
  body is as it was typed and ends at `EOF` in column 0 (Arista's
  pyeapi reads it so), so every reader took its lines for the top
  level, and a line `username <name> privilege 15 nopassword` in it
  was a privilege-15 account with no secret on the target.  Every
  such body is emptied, its lines keeping their numbers, before any
  reader of the parse -- the Tier-3 rows included -- and a body with
  no `EOF` is refused.  A body that only a generator is seen to print
  (a certificate and its key) is opened only where its own first
  line proves it (PEM): taken on the generator's word, a printout
  with one body lost every line after it (caught before release).
  **The blind spot:** no
  committed capture has a banner, and every check read the captures
  as printed; the guard writes the banner and reads every target's
  output for its words
  (`tests/unit/migration/test_arista_eos_indentation.py`).
  **And the rule is every parser's, each ending a body its own way,
  from its vendor**: IOS-XE and NX-OS at the delimiter anywhere (an
  IOSv printout puts the closing `^C` after the text, so "alone on a
  line" never ends its banners), AOS-CX at a line that ends with its
  delimiter, OS10 at a line of the delimiter alone, AOS-S at a quote no
  backslash escapes, IOS XR at the one character after its type,
  anywhere (XR prints the delimiter that was typed, never a fixed
  `^C`).  A body's lines are a device's lines: one that
  ends in a form feed or the like is refused (EOS's pass too).  Where
  a printout cannot say where a banner ends, the code refuses what it
  can see -- AOS-S text after its quote, and the end a device printed
  left outside every body because the banner's own text held it
  (IOS-XE, AOS-S, OS10) -- and the rest is a stated limitation, not a
  guarantee: a text that holds its end at the end of a line on AOS-CX,
  or holds it and then opens another banner, ends there unseen; and
  an IOS XR banner set through NETCONF can be printed with no end, and
  runs on over the configuration after it -- read by nothing, and
  counted in the banner's row, but not translated.  Where two readings
  of the vendor's grammar end a banner on different lines (IOS XR's
  `^C`, one delimiter or two), the line is refused, never one reading
  picked (`_scanner.without_text_bodies`;
  `tests/unit/migration/test_a_banner_is_text.py`).
- **Never** let one value stand for "not stated".  The canonical tree
  had ONE value, an empty list, for three statements: a trunk that
  allows no VLAN (`switchport trunk allowed vlan none`, a list a
  `remove` emptied, an OS10 or Junos trunk with no list, a list the
  operator emptied by dropping its VLANs), a trunk that states no
  list (every VLAN on IOS-XE, NX-OS and EOS), and AOS-CX's own `vlan
  trunk allowed all`.  Each renderer then picked one reading for all
  three.  Failure mode: a trunk that carried one VLAN came out as a
  trunk for every VLAN on four targets (IOS-XE, NX-OS, EOS, AOS-CX),
  and a trunk for every VLAN — a vPC peer link — came out carrying
  none on the other three, in jobs that said `completed` and reported
  nothing.  What a platform does with a statement that is not there
  is a fact about the SOURCE, and only its parser knows it.  So the
  parser resolves "not stated" to what its platform does — from one
  table, `TRUNK_THAT_STATES_NO_LIST` in
  `netcanon/migration/codecs/_helpers.py` — the tree holds what is
  meant (on a trunk `[]` is no VLAN, every id is every VLAN, any other
  list is the list), and a renderer writes its target's form for
  each: its word for none, its word or its default for every VLAN.
  Where the target has no form, the cell is a pinned, documented
  limitation, never a silent pick, and the output says so where there
  is a line to say it beside: AOS-CX cannot be told "none" and OS10
  cannot be told "all", and each writes a `! review:` line in the
  stanza.  AOS-S cannot be told "and any VLAN made later" either,
  and has no such line: a trunk of every VLAN is tagged in each VLAN
  the output declares and nothing in the output says more was meant
  (its vendor page does).  And a limitation says what IS written as
  well as what is not: the AOS-CX stanza for "none" is a switched
  port with no `vlan` line, which is something on the switch, and
  what that is has to be said, or said to be unknown.  A
  marker for "not stated" carried to the renderer is the same defect
  with a flag on it: every reader of the value has to remember to
  ask.  **The blind spot that hid it:** a guard that reads the output
  with the TARGET's parser reads the target's default.  That parser
  read its own "no allowed line", and AOS-CX its own `all`, as the
  same empty list the source had, so every wrong cell agreed with
  itself and passed.  Whatever a default can spell is read as TEXT,
  by a reader the test owns for each target's grammar, beside the
  parser.  And a pass that EDITS the
  value has to know what it means: a list of every id is the
  statement "every VLAN", which a VLAN drop or renumber leaves as it
  is (rewritten id by id, a trunk that said `all` came out as
  `1-99,101-4094`, and so would every trunk of a config that states
  no list, for one edit), and a list a drop empties is "none", which
  the job says in a warning.  The same holds for a reader that
  took "has a list" to mean "carries something": a default trunk has
  a list now, and is in the list of every VLAN there is, so where one
  port is chosen for a VLAN a trunk that NAMES it is looked for before
  a trunk of every VLAN.  Three corollaries, each found after the
  rule was built.  (1) **What is stated is stated by the INTERFACE,
  not by a stanza.**  Four parsers make a record a stanza, and
  resolved "no allowed line" a stanza: a trunk of VLAN 10 whose
  stanza was met again with only its mode line got a second record of
  the platform's default — every VLAN, or from OS10 none.  Keep what
  an interface states by its NAME (`TrunksByName` in
  `codecs/_helpers.py`), and resolve "not stated" when the whole
  config has been read.  The name is the one the config WRITES, the
  stanza's header line, not the one the parser reads from it: two
  parsers read `interface port-channel 1` and `interface
  port-channel 2` as one name (the NX-OS parser still does), and
  keyed by that name a trunk with no list of its own would be given
  its neighbour's.  (2) **A default is given to what the config
  STATES, never to what the parser inferred.**  The NX-OS and EOS
  parsers take a port for a trunk from a trunk line with no
  `switchport mode trunk`; filling "every VLAN" into a trunk the
  parser guessed turned a guess about the mode into every VLAN on
  every target.  Such a trunk keeps what its lines name, or nothing:
  when a default has to rest on an inference, choose the reading that
  carries fewer.  (3) **A value that now holds thousands of entries
  is read once.**  A list of every id costs 4,094 comparisons to
  recognise; asked of every port again for every VLAN, it was half a
  minute for a config of a thousand trunks and a thousand VLAN
  interfaces, and no cost test rendered.  Ask once a port, and time
  the render (`TestARenderFitsTheTrunksItIsGiven`).  And it is
  COUNTED where it is made, before it is made: a default trunk is
  two lines of text and 35 KB of tree (the rule on counting;
  `TestATrunkThatStatesNoList` in `tests/unit/migration/test_limits.py`).
  And a reader
  that counts what a value "references" has to skip the statement
  that names nothing in particular: every id of a default trunk
  counted as a reference, and a VLAN map entry for a VLAN the config
  does not have was no longer reported.  Guarded by
  `tests/unit/migration/test_a_trunk_says_none_nothing_or_all.py` —
  every public codec as a target; sources that say none, nothing and
  all in their own grammar, with what each means written out by hand
  and compared with the table; the output read as text and with the
  parser; the gaps that remain as named sets compared for EQUALITY
  with what is measured, so closing one fails until its pin is taken
  out; a stanza met twice and a trunk line with no mode line, from
  each parser of the table; and a public codec is in the table or is
  named with its reason — and by
  `test_a_vlan_drop_and_a_trunks_list.py` and
  `test_the_trunk_that_names_a_vlan.py`.  Still open, and in the
  CHANGELOG's known limitations: on a port that is NOT a trunk an
  empty list is still two statements, `none` and no list at all.
  (Whether a trunk's list holds its native VLAN was a third thing
  the tree did not state; the next rule is what it cost.)
- **Never** let two fields of the tree hold one fact each in its own
  platform's way.  A trunk's untagged VLAN is in the tree twice over:
  `trunk_native_vlan` says which VLAN, `trunk_allowed_vlans` what the
  trunk carries.  Whether the second has to name the first is not one
  grammar.  On IOS-XE, NX-OS, EOS, AOS-CX and Junos the native VLAN
  is a line of its own, which the allowed line may name or leave
  out; on OS10 it is the trunk's access VLAN, and the allowed line
  names tagged VLANs only; AOS-S lists a VLAN's untagged ports apart
  from its tagged ones.  Each parser put what its text lists, each
  renderer wrote the list as it stood, and the two projections
  between a port's fields and the VLANs' member lists answered the
  question differently from each other.  Failure mode: every AOS-S
  and OS10 trunk that has an untagged VLAN was written for the other
  five with a native line beside an allowed list that left the VLAN
  out -- on AOS-CX, by HPE's own sentence, a port that drops its
  untagged traffic -- in jobs that said `completed` and reported
  nothing; and the other way a native VLAN its list left out was
  written `untagged` on AOS-S and as the access VLAN on OS10.  The
  convention is ONE, and the tree holds it: a trunk's list is what
  the trunk carries, its native VLAN among them, and a native VLAN
  the list does not hold is stated and not carried
  (`trunk_untagged_vlan` in `canonical/transforms.py`: read a trunk
  through it, never from `trunk_native_vlan` alone).  A platform's
  text is brought to it at the platform's edge, by one table
  (`NATIVE_VLAN_AND_THE_LIST` in `codecs/_helpers.py`): the parser of
  a platform that states the untagged VLAN beside its list puts it
  INTO the list, and its renderer takes it out again, in the same
  change.  And a pass that rewrites a trunk's native VLAN or its
  list asks what the trunk carried untagged BEFORE and AFTER
  (`trunk_untagged_vlan`), so that no rewrite turns "stated and not
  carried" into "carried" -- the VLAN rename pass renumbered the two
  fields one after the other, and a native VLAN outside its list
  that a map moved onto an id of the list came out as the trunk's
  untagged VLAN: a VLAN the source carried tagged, or one it did not
  carry at all.  **The blind spot that hid it:** every check read both
  trees the tree's way.  A native VLAN counted as a membership
  whatever the list said, on the source's tree and on the output
  parsed again, so the two always agreed and the guard that looks
  for every membership in the output passed.  A check of a
  convention must not read by the convention: read what the DEVICE
  carries on each side by its own platform's grammar, written out
  by hand in the test, from the output's text as well as from its
  parse.  Two corollaries.
  (1) **What a device does with the statement is the vendor's to
  say.**  That a native VLAN outside the list is not carried is a
  vendor's sentence for AOS-CX and, for the default VLAN 1, for
  IOS-XE and NX-OS; it is an inference for another VLAN there, a
  stated requirement to receive in the Junos ELS grammar, and not
  established for EOS.  Say which, with the sentence, in the vendor
  reference -- and say "not established" in the comment, the
  `review:` line and the document where no page says it (what `no
  switchport access vlan` leaves an OS10 trunk with is one such:
  Dell's pages disagree, and the line is written under a review
  line that says so).  (2) **Right where the list decides is not
  "harmless" everywhere else.**  On a Junos switch that takes the
  older grammar a native VLAN that is ALSO on `vlan members` is sent
  tagged.  The codec writes the ELS grammar only, so no output is
  touched, and its vendor page says the output is not for such a
  switch; a rule for five platforms is a rule for those five.
  Guarded by
  `tests/unit/migration/test_the_list_holds_the_native_vlan.py`:
  every committed capture onto every codec whose parser states
  memberships, each side read by its own row, the output twice;
  each shape of trunk through every pair, with what its source
  carries written beside it by hand; each check handed the defect it
  is for; and a codec that is in one of the three trunk tables and
  not in all of them fails.
  (3) **A native VLAN that is not stated is the defect of the rule
  above, and was mended the same way.**  A trunk that states no
  native VLAN has its platform's default -- VLAN 1 on IOS-XE, NX-OS,
  EOS and AOS-CX, none on Junos -- and the tree had "not stated"
  for it: VLAN 1 of such a trunk was a tagged VLAN like any other,
  and came out TAGGED on Junos, OS10 and AOS-S, in jobs that said
  nothing.  The parser puts the default
  (`TRUNK_THAT_STATES_NO_NATIVE` in `codecs/_helpers.py`), for an
  interface, AFTER its list is resolved -- a trunk with no allowed
  line holds VLAN 1 by the platform's list and not by a line -- and
  before the ports are mirrored onto the VLANs.  In a tree a parser
  made, no native VLAN is no untagged VLAN.  What it cost to get
  there.  A default belongs to what it is the default OF: this
  one is a trunk's, and is put only for a port that SAYS it is a
  trunk.  Given to any port that had a list (caught before
  release), it made an untagged VLAN 1 of an access port that
  keeps a trunk line -- which two parsers already took for a
  trunk -- and the guard, which read the source through the same
  parser, agreed: who says it is a trunk is now read from the
  TEXT, in the test.  A default is put only where the text does
  not say otherwise in words the parser does not read: under `vlan
  dot1q tag native` a native VLAN in the tree would be read as
  untagged, so nothing is filled in.  Where the id of a default is
  not in the
  text (an OS10 switch's default VLAN, a setting) nothing is filled
  in either, and the table says so rather than guess 1.  And a
  renderer leaves out the line its device does not print -- but
  what a device prints is read from the captures, in a test, never
  recalled: no real capture of IOS-XE, NX-OS or EOS prints
  `switchport trunk native vlan 1`, every AOS-CX trunk of the
  captures states `vlan trunk native 1`.  And where the new VLAN 1
  record puts a `vlan 1` line into an IOS-XE output whose capture
  has none, the line is left in and SAID: the tree does not keep
  whether the text had it, and a rule that rebuilds that from the
  tree departs from the text in both directions.
  **The blind spot that hid it:** both readings of an output left
  the default out, the target's parser and the reader of text, so
  they agreed with each other and with the source's tree, which
  left it out as well.  A reader of text applies the platform's
  default itself, typed in the test and compared with the table,
  and a tree is held to its platform's default before anything is
  compared.
  (4) **The TARGET's half: a port that carries NO VLAN untagged**,
  written for a platform whose trunk has a default native VLAN, is
  given that default by the switch unless the output says
  otherwise.  IOS-XE, NX-OS, EOS and AOS-CX are written their own
  form for it (`wants_no_untagged_vlan`), and the parsers read the
  same words back: a trunk whose native VLAN is sent tagged has no
  native VLAN in the tree, a stated one included.  Where a form
  says it of the whole switch (`vlan dot1q tag native`) it is
  written only where no port the check reads blocks it
  (`every_native_vlan_tagged`: the ports in trunk mode, the ports
  with trunk lines and no mode, and the ports in a mode no mode line
  is written for -- dynamic, private-vlan, dot1q-tunnel, fex-fabric
  and the like; a port with no mode and no trunk line is not
  counted, though on a Catalyst it is in dynamic auto by default and
  the line would tag it should it become a trunk), and otherwise the
  port gets a review line -- a line for one port is not a line for
  the switch.  The guard holds each such cell to its review line,
  whole, compared for equality.  OS10 and AOS-S are asked another
  way.  OS10's default VLAN has no id the list can be asked about, so
  an OS10 trunk with no native VLAN is written `no switchport access
  vlan` under a review line -- unless another record of the interface
  states its untagged VLAN (a native VLAN, or an access VLAN), which
  the line would take back.  AOS-S is told VLAN by VLAN, so each name
  the output tags somewhere, lists untagged nowhere and names on no
  line of VLAN 1 is taken out of VLAN 1 with `no untagged` (a trunk
  that carries VLAN 1 tagged is written `tagged` there).  The readers
  of text give each target's default itself.  Open, and in the
  CHANGELOG's known limitations: an AOS-S trunk that carries nothing
  (AOS-S has no form for a port in no VLAN, and it stays in VLAN 1),
  what `no switchport access vlan` leaves an OS10 trunk with, and
  whether OS10 takes VLAN 1 on the allowed line of such a trunk.
- **Never** put a word of the config where a port name goes, and never
  make an interface record for a name the config configures nothing
  under.  A parser that takes the first word after a keyword for a
  name writes that word into every target's output, and the job says
  `completed`: IOS XR `interface preconfigure TenGigE0/0/0/12` —
  configuration the router holds for an interface it does not have —
  was an interface called `preconfigure`; `interface ethernet 1/11`
  was one called `ethernet`, and two such stanzas one name; `ip route
  ... loopback 66 100` a route out `loopback` at distance 66; an
  OPNsense pool under `<dhcpd><lan>` was on `interface lan` in a
  Junos output; and `set interfaces irb unit 100` made an empty `irb`
  that no platform has a name for.  In each chain the classifier
  answering `unknown` was the one right thing, so such a name is not
  mended by teaching a classifier to read it.  The PARSER has the
  whole config: it resolves a keyword, a zone or a spaced name to the
  port it stands for, or to nothing, and what is then not translated
  is said in a row of `dropped_tier3_sections`, never left out in
  silence.  Which row is not a detail: a stanza held for hardware
  that is absent is a statement the device does not run, so its row
  is a left-out row (the rule above on such statements — bounded,
  and a text that is all such stanzas is not `completed`), while an
  `interface range` or `interface breakout` header or an OPNsense
  pool whose zone has no device is in force and not in the output, a
  section.  And joining two words is itself a reading that can be
  wrong: a second word is joined to a type only where it can be the
  type's number, so a keyword is no type, and an address after a
  type word (`ip route ... Dialer 10.0.0.1`) is the route's gateway.
  Before making a record for the first word of a line, ask what the
  config STATES under that name, not what the parser read of it --
  and of what KIND: `interface Port-channel1.10` states a unit of a
  LAG, and three parsers that took any header with the LAG's prefix
  for a LAG made an empty LAG of it, which Junos wrote as `ae10` and
  FortiOS as an aggregate holding the unit's address.  A
  Junos line under `unit N` configures `<name>.<N>` and states
  nothing on the device the unit hangs off; a line on the device or
  on its unit 0 makes the record whether or not any handler reads
  it; and a name the classifier READS as a port or a LAG keeps its
  record whatever the config says — which is not yet every port:
  `xe-0/0/6:2`, `so-0/0/0` and `reth0` are names it does not read,
  and with nothing but units above 0 they have no record.  The
  first version of this mend asked whether the parser's own bucket
  for the name was empty, and `set interfaces st0 unit 0 family
  inet` — the usual unnumbered tunnel — made no record: jobs went
  from `partial` to `completed` with the route to `st0.0` still in
  the output.
  And a record taken out is no longer there to be counted on:
  re-measure what stood on it.  An empty `st0` was the only evidence
  one declared loss had (the placeholder comment a RouterOS output
  has for a tunnel with no description, read back as one).  And an
  empty `irb`, which an EOS output has no line for, had made a
  cell's interface COUNT differ, and a cell whose count differs is
  not compared record by record: with the `irb` gone the comparison
  showed that the EOS output for a Junos address with a virtual
  gateway beside it — `ip address virtual <gateway>`, then `ip
  address <own>` — reads back as two address records.
  Still open, each a change of its own: IOS-XE `ip route ... dhcp`,
  which keeps the keyword in the route's interface so that the line
  is written back to IOS-XE as it was (a canonical route cannot say
  "from DHCP"); an EOS DHCP pool's NAME where the pool's interface
  goes; a VTEP's source ADDRESS in `vxlan_vnis[].source_interface`
  on AOS-CX and VyOS; and the parsers that still read a spaced name
  a word at a time (NX-OS headers, IOS XR and AOS-CX route lines).
  Guarded by
  `tests/unit/migration/test_a_word_is_not_a_name.py`, which sends
  each form through the plan path onto every public codec and reads
  the rendered output as text and with the target's own parser.
- **Never** leave a port the config names with no record of its own.
  The tree states a port's VLANs and its LAG twice — in the VLAN's
  and the LAG's member lists, and on the port's interface record —
  and most renderers write a port from its record and never read the
  lists.  The AOS-S parser made a record only for an `interface`
  stanza, which the device prints only for a port with a setting of
  its own: a switch's access ports, named only under `vlan ...
  untagged`, came out on NX-OS, AOS-CX, OS10 and IOS-XR with no line
  at all, their VLANs with them, in jobs that said `completed` — 181
  of 182 memberships on one committed capture.  Nothing said so:
  `port_renames` listed each port, the validation report counted the
  membership as supported (it walks the tree, before a line is
  written), a same-codec round trip never sees a tree its own parser
  does not make, and the cross-mesh audit, which HAD measured the
  drift, held it as an expected loss on the word of a sentence about
  another path that nobody had run.  A parser gives a record to
  every port one of its lists names — a VLAN's `tagged_ports` /
  `untagged_ports`, a LAG's `members` — and it is the record its own
  empty stanza makes, so that a config and its own rendering parse
  alike.  "The matrix says `supported`" and "two trees agree" are
  not "the line is in the output".  Guarded by
  `tests/unit/migration/test_vlan_members_reach_the_output.py`, which
  looks for every membership of every committed capture in the
  OUTPUT of every target, three ways (the target's parser, the text
  by a reader of its own, the port's name in a line), holds every
  parser to the record on the captures, and pins by name what it
  knows is still open — the change that mends one empties its pin.
  The same holds the other way: a renderer that leaves a port's
  stanza out because another line of its output names the port asks
  the target's own reader whether that line gives the port back.
  Before it asked, the AOS-S renderer left out `interface 1` on the
  strength of `trunk 1,my port trk1 lacp`, a line the parser does
  not read, and port 1 came back in no record.  Guarded by
  `tests/unit/migration/codecs/aruba_aoss/test_no_stanza_for_enable_alone.py`.
- **Never** write a value of the tree on more than one line.  Every
  renderer writes a config a line at a time and puts a value into its
  line as it stands, so a value that held a line break was written as
  lines of its own, and the text after the break was a command: an
  interface description holding a break and then `username <name>
  privilege 15 nopassword` came out with that line on its own onto 12
  of the 13 public codecs.  The OPNsense and IOS-XE NETCONF parsers
  keep such a value from an element's text, and the FortiOS parser
  made one of the device's own printout as well -- FortiOS prints a
  certificate, a key or a replacement message's HTML between its
  quotes, over several lines, and the parser read each line of it as a
  statement: a line `end` in the HTML closed the block it was in, and
  a line `config system admin` after it was an account with no
  password on IOS-XE and EOS, in jobs that said `completed`.  The rule
  is ONE for every field of every target, never a list of the fields a
  target may hold a break in, since a value in the wrong place on such
  a list is an account: the pipeline (and the sanitiser, before it
  renders) writes each run of breaks as a space after the transforms
  -- an operator's map puts values into the tree too -- and says each
  place in the job's warnings (`one_line_each`), and `CodecBase.render`
  refuses a tree that still holds one, naming the field and nothing of
  the value (`netcanon/migration/_one_line.py`).  A break is every
  character `str.splitlines` ends a line at, not the line feed alone.
  The walk reads every field a record HOLDS, not the fields the schema
  declares, and a dict's keys with its values: a value in a place the
  schema does not name is written all the same.  The parsers' half is
  the rule on a body that runs to its own end, above: a FortiOS quoted
  value is read whole, up to the line whose quote no backslash escapes,
  and the Tier-3 rows and the release are read from the text with its
  lines emptied (`without_quoted_values`).  **The blind spot that hid
  it:** every check read a capture, no committed capture's tree holds a
  value of several lines, and a codec's round trip to itself writes
  the break and reads the same value back.  `raw_sections`, the one
  field built for text of several lines, is under the rule too; no
  parser fills it.  Guarded by
  `tests/unit/migration/test_a_value_is_one_line.py`, which puts a
  break into every place of a tree built from the schema and sends the
  sources that keep one onto every public codec; with the mend taken
  out the render refuses, and with both gates out the line comes back
  on every codec it is pinned for; and by
  `tests/unit/migration/codecs/fortigate_cli/test_a_quoted_value_is_text.py`,
  which holds where each quoted value of every committed input ends to
  a reader of its own, a character at a time.
- **Never** write a value of the tree where the target reads it as
  more than a value.  RouterOS imports an `.rsc` as a script: outside
  a string white space parts two words, `;` ends the command, and
  `$`, `[ ]`, `( )` and `{ }` substitute a variable, run a command or
  an expression, or open a scope -- and inside a string `$[...]` and
  `$(...)` run as well.  The renderer escaped `\` and `"` in a string
  and wrote most values bare, so a description `$[/system
  reset-configuration]` from any source vendor came out as that
  command on the router that imported the output, a value holding `;`
  ended its command there, and a RADIUS secret `7 <blob>` was a secret
  `7` and a stray word -- in jobs that said `completed`.  A value is
  written as it stands only when it is made of characters the
  vendor's own printout leaves bare (letters, digits and
  `- . _ / : , %` for RouterOS), and as a string otherwise, escaped
  by the vendor's rules -- `$` included, as an export escapes it
  (`_quote_if_needed` and `_escape` in the RouterOS renderer) -- and
  the parser reads back every form the renderer writes (a quoted
  `[ find name="..." ]`), in the same change.  An allow-list, never a
  list of the characters known to be dangerous: what a grammar gives a
  meaning to is the vendor's to say, and a value nobody vouches for
  finds the one left off.  **The blind spot that hid it:** every check
  read the output with the codec's own parser, which reads `$[...]`
  inside a string as text and a bare value up to its first space as
  the whole of it -- so a description that runs a command
  round-tripped, and a secret cut to `7` was a loss the mesh had
  measured and put down to the secret's encoding.  The guard reads the
  output with a reader of its own, typed from MikroTik's "Scripting"
  page, over a tree built from the schema with such text in every
  place it has and over every committed input, and each of its checks
  is handed the old rule and fails
  (`tests/unit/migration/codecs/mikrotik_routeros/test_a_value_is_not_code.py`).
  Still open: the renderers whose lines a device reads a word at a
  time have not been read for a value with white space in it written
  bare (SECURITY.md, "Known Limitations").
- **Never** write a credential where one value goes unless it IS one
  value there.  A renderer puts a value into its line as it stands,
  and a word-at-a-time CLI reads a value that holds white space as two
  words, the second as whatever that place takes next: NX-OS
  `snmp-server community public rw` is a READ-WRITE community
  `public`, an EOS community's second word is an ACL name, a password
  `secret scrypt` sets `secret`.  Every line-grammar renderer did this
  for every password, community, SNMPv3 user and VRRP/HSRP key, and
  AOS-S, which quotes and documents no escape, ended a value at its
  `"`.  Which places quote, and with what escape, is the VENDOR's to
  say: no word-at-a-time CLI documents a quoted credential, so such a
  value is not written there, and a secret is never altered to fit (a
  secret with a space replaced is another secret).  It is left out
  with the granularity the credential rules above set, and said in a
  line that names the place and never the value -- three review lines
  quoted the very key they could not write.  Where the target quotes,
  escape as it documents (`_one_value.py`; FortiOS and Junos `\"`,
  VyOS none at all).  **The blind spot that hid it:** no committed
  input holds such a value, every check read the captures, and a
  codec's round trip to itself writes the two words and reads the
  same two back.  And a check of "the secret is in no comment" has to
  run whether or not the target writes the field: the first version of
  the guard looked only where the one-word value was written, and the
  AOS-S line that quoted an MD5 key it could not write passed it.
  Guarded by `tests/unit/migration/test_a_secret_is_one_value.py`,
  which reads every target's output as text, and is handed each
  defect it is for.  Not yet under the rule: RADIUS keys.
  **What is not a secret is under the same rule, by what it is**
  (`one_value_tree`, which each line renderer runs on the tree before
  its first line).  A NAME that labels (host name, VLAN, VRF, route
  name) may be written as one word (`_` for each run of white space,
  `'` for a `"`) and said; an ADDRESS (a server, a domain, a gateway)
  is never altered, so it is left out and said, and a static route
  whose gateway it is goes WHOLE (a route that keeps its destination
  without its next hop is another route); a TEXT is written to the end
  of the line where the vendor documents that place so, written and
  said where no page does, and quoted where the target quotes (OS10's
  description: Dell does not keep the spaces of an unquoted one).  A
  name is changed ON THE TREE, once, never at the line that writes it:
  a VRF is named on its own stanza, on every interface in it and on
  every route of it, and a name relabelled at one of those lines and
  not at another is two VRFs; and a relabel that would give a VRF
  another VRF's name is told apart.  **The blind spot:** two
  renderers already wrote the host name with `_`, from a helper whose
  own docstring said to extend it only after auditing each codec's
  grammar; nobody did, the other six wrote `hostname a b`, and the
  IOS-XE route name holding a space was left out with nothing said.
  Guarded by `tests/unit/migration/test_a_name_is_one_word.py`, which
  reads every target's output as text with a table of the places
  that read to the end of the line typed from the vendor references
  (or a committed capture that prints such a line),
  counts the places a name goes before and after, and is handed each
  defect it is for.
- **Never** fill a slot of the target's grammar with what the slot
  does not take.  AOS-S takes an address, `vlan <id>`, `reject` or
  `blackhole` as a static route's next hop (HPE's routing guide), and
  its renderer wrote whatever the tree held there: a route out an
  interface came out as `ip route <dest>` with nothing after it, a
  route to `Null0` the same, a next hop `Trk1` as itself -- 33 such
  lines over the committed captures, and a config whose one route
  went to `Null0` made a job that said `completed` -- and a route in a
  VRF went into the switch's one table.  A slot is filled from the
  target's grammar, read from the vendor: each value the tree can hold
  there is written in the form that means it, or left out under a
  `review:` line in a job that is not `completed`.  And a parser reads
  the forms its device takes, not the forms its renderer wrote: the
  AOS-S parser read `ip route <dest> Trk1` back, so a round trip agreed
  with itself over a line the switch refuses.  Still open, each a
  change of its own: the tree's only spelling of a discard route is
  `Null0` in its interface (a FortiOS `blackhole` route parses as a
  route with no next hop), several renderers write `Null0` as it
  stands where a next hop goes, not yet held to each vendor's grammar,
  and the FortiOS, RouterOS and VyOS renderers write a route in a VRF
  into the global table.  Guarded by
  `tests/unit/migration/codecs/aruba_aoss/test_a_route_the_switch_takes.py`,
  which reads the output with a reader of HPE's grammar typed in the
  test and works out each route's next hop from the source's tree.
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

## Ultracode runs (multi-agent reviews)

Multi-agent reviews, audits, and research follow netcanon's two-stage process:
**read-only agents each write one report into `docs/reviews/<UTC-date>-<slug>/`
→ the main thread reconciles into a synthesis + fix-plan and is the sole actor
that verifies and commits.** The full process, run-folder convention, seed
template, cluster taxonomy, and dispatch heuristics live in
[`docs/agent-workflow.md`](docs/agent-workflow.md) (the
[`docs/security-triage/`](docs/security-triage/) and
[`docs/docs-audit/`](docs/docs-audit/) processes are worked instances).

**Ultracode runs use the reusable file-per-agent blackboard runner**
([`.claude/workflows/blackboard.js`](.claude/workflows/blackboard.js), via the
`Workflow` tool with `scriptPath: .claude/workflows/blackboard.js`) — never
hand-rolled. Each agent writes ONE long-form report under the run dir, reads
peers' reports for cross-phase comms, and returns only a short pointer/summary;
the main thread writes the `00-blackboard.md` seed up front and the
`99-synthesis.md` reconciliation after, then actuates under the Hard Rules
above (pseudonym identity, explicit staging, the cross-mesh proof bar,
confirm-before-merge). The runner bakes the read-only contract in so it can't
drift. See [`docs/agent-workflow.md`](docs/agent-workflow.md) § Ultracode runs.

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
- [`docs/agent-workflow.md`](docs/agent-workflow.md) — the binding multi-agent / ultracode process (read-only agents → orchestrator synthesis → main-thread actuation) + the reusable `.claude/workflows/blackboard.js` runner; security-triage and docs-audit are worked instances
- [`docs/security-triage/`](docs/security-triage/) — process + per-run evidence trail for triaging Code Scanning / Dependabot / secret-scanning alert waves; cluster taxonomy + read-only Stage-1 agents + orchestrator-applied dismissals
- [`docs/docs-audit/`](docs/docs-audit/) — sister process to security-triage applied to documentation hygiene; 6-cluster taxonomy (interlinking / user-docs / developer-docs / codec-docstrings / platform-docstrings / tests-changelog); read-only Stage-1 Opus 4.7 1M agents + orchestrator-executed Stage-2 fixes
- [`tests/README.md`](tests/README.md) — test-suite layout and mocking strategy
