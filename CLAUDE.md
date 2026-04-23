# NetConfig — Contributor Directives

These directives govern all development in this repository.  Follow them in
every session without being asked.

**Project orientation:** if this is your first read, also skim
[`README.md`](README.md) for the quickstart and
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the 4-layer design.
[`translator-plans.txt`](translator-plans.txt) carries the active
roadmap; [`tests/fixtures/real/RESULTS.md`](tests/fixtures/real/RESULTS.md)
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
| A new interactive HTML element (button, input, link, row) | `tests/testid_reference.md` — document the new `data-testid` in the appropriate page section |
| A new Jinja partial (`templates/_partials/<name>.js`) | The file-level comment block in the parent template (e.g. `migrate.html`'s "Contents map" comment) **and** the "Template organisation" section of `ARCHITECTURE.md` if the partial introduces a new pattern |
| A new codec under `netconfig/migration/codecs/<vendor>/` | `netconfig/migration/codecs/README.md` — update the "Shape of a codec" codec count + wire-format table; add the vendor to `ARCHITECTURE.md` if it's a new wire-format class |
| A new module inside an existing codec (e.g. `port_names.py`, `vlan_heuristics.py`, `_svi_absorption.py`) | `netconfig/migration/codecs/README.md` "Module layout" section if the pattern is worth propagating to other codecs |
| A new target-profile YAML under `definitions/target_profiles/` | Per-profile unit test in `tests/unit/migration/test_target_profiles.py` asserting exact port-name list + count (regression guard against copy-paste mistakes) |
| A target-profile gains `modules:` (migrates to module-variant shape) | Update BOTH `MODULE_VARIANT_PROFILES` allowlists — one in `tests/unit/migration/test_target_profiles.py`, one in `tests/integration/test_migration_target_profiles_api.py` (kept in sync manually) |
| A new canonical field on `CanonicalIntent` / `CanonicalInterface` / etc. | `docs/adding-a-canonical-field.md` — the MTU wire-through is the reference worked example |
| A new hard rule / cross-cutting invariant surfaced by a bug | This file (`CLAUDE.md`) — add to the "Hard Rules (Never Break)" section with a one-line rationale pointing at the failure mode |
| A codec is promoted to `best_effort` or `certified` | `tests/fixtures/real/RESULTS.md` — update the coverage matrix and certification decision; ARCHITECTURE.md's cert paragraph intentionally defers to RESULTS.md as source of truth |
| A new real-capture fixture under `tests/fixtures/real/<vendor>/` | `tests/fixtures/real/NOTICE.md` — provenance + attribution; `tests/fixtures/real/RESULTS.md` — coverage matrix row |
| A function gains a new parameter or changes return shape | Its docstring (Google-style sections for Args / Returns / Raises) |
| A pipeline-stage signature (anywhere in `migration_pipeline.py`) | **DON'T.**  These are frozen (see Hard Rules).  Add a NEW function instead; the module docstring tracks which are frozen |
| The module-variant schema gets a new field on `TargetProfile` / `TargetModule` | The class docstring in `netconfig/migration/target_profiles.py` — it includes a worked YAML example that must stay accurate |
| In-file references like "see commit abc1234" in a partial or module comment | Fine to include for load-bearing rationale; don't rely on them for discoverability — put the same info in a nearby README if other contributors need it |

Rule of thumb: if a future contributor could plausibly search for the
thing you just added and not find its rationale, there's a doc gap
to close.

---

## Code Organisation

```
netconfig/              FastAPI application (shared by both platforms)
netconfig_desktop/      Windows desktop shell (tray, webview, server lifecycle)
definitions/            Device definition YAML files (shared by both)
tests/unit/             Pure-function tests, no I/O, platform-agnostic
tests/integration/      API tests via TestClient, platform-agnostic
tests/e2e/              Playwright E2E tests (web platform)
tests/desktop/          Desktop-specific tests (mocked tray/webview)
```

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
- **Never** land a code change without updating the docs it renders stale.
  The "Documentation Sync Checklist" above is concrete — if a row applies
  to your change, touch the listed doc in the same commit.  Follow-up
  doc-only commits are acceptable for retroactive audits of pre-existing
  drift (e.g. the audit that added this rule), NOT for fresh code that
  shipped without its docs.  Stale docs are a bug; they just don't crash
  loud enough to be caught by CI, which is why the discipline has to live
  in the workflow.
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
