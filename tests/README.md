# Netcanon Test Suite

Four-layer test infrastructure: **unit → integration → E2E → desktop**.

## Layout

```
tests/
├── conftest.py              Root fixtures (FakeCollector, test_settings, test_app)
├── fixtures/
│   ├── definitions.py       Pre-built DeviceDefinition factory functions
│   ├── ssh_responses.py     Canned SSH output strings per vendor
│   ├── module_variants.py   Canonical module-variant allowlist shared with integration tier
│   ├── target_profiles/     Synthetic target profiles (never shipped) for grades no shipped profile carries
│   ├── synthetic/<vendor>/  Hand-crafted minimal configs per vendor (parser-feature focus)
│   ├── real/<vendor>/       Real-capture corpus + RESULTS.md + NOTICE.md + CROSS_MESH_RESULTS.md
│   └── cross_vendor_expectations/  Phase 3 mechanical-drift expectation tables
├── unit/                    Pure-function tests, no I/O
│   ├── test_schema.py       Pydantic schema validation (incl. type_key filename-safety)
│   ├── test_loader.py       DefinitionLoader (file parsing, priority resolution)
│   ├── test_storage.py      FileConfigStore (save / list / get / delete + canonical type_key round-trips)
│   ├── test_models.py       BackupJob, DeviceCredentials, etc.
│   ├── definitions/         Per-vendor device-definition YAML lock-in tests
│   ├── tools/               Audit-harness scripts (run_full_mesh, run_phase4_reconciliation)
│   ├── api/                 API helper unit tests
│   ├── audit/               Reconciler-internal unit tests
│   └── migration/           Codec + canonical-layer unit tests
│       └── codecs/          Per-vendor codec deep-dive units (arista_eos, aruba_aoss,
│                            cisco_iosxe, cisco_iosxe_cli, fortigate_cli, juniper_junos,
│                            mikrotik_routeros, opnsense)
├── integration/             API-level tests via FastAPI TestClient
│   ├── conftest.py          TestClient fixture with mocked get_collector
│   ├── test_definitions_api.py
│   ├── test_configs_api.py
│   ├── test_backups_api.py
│   ├── test_backups_<vendor>.py   Per-vendor backup wiring smoke tests
│   ├── test_migration_api.py
│   ├── test_migration_target_profiles_api.py
│   ├── test_device_profiles_api.py
│   ├── test_schedules_api.py
│   └── …                    (etc. — see tests/integration/ for the full set)
├── e2e/                     Full browser tests via Playwright
│   ├── conftest.py          Live Uvicorn server + Playwright base_url
│   ├── helpers.py           Page-object helpers (NavBar, BackupFormPage, …)
│   └── test_backup_flow.py
└── desktop/                 Desktop-shell unit tests (no display required)
    ├── conftest.py          mock_pyside6, mock_pystray, mock_generate_tray_image fixtures
    ├── test_app.py          DesktopApp orchestration and startup order
    ├── test_server.py       ServerThread (real Uvicorn on a free port)
    ├── test_tray.py         TrayIcon construction, callbacks, stop()
    ├── test_window.py       WebViewWindow lifecycle and _handle_close()
    ├── test_settings.py     Path resolution in frozen vs. dev mode
    ├── test_backups_<vendor>_desktop.py  Per-vendor embedded-server smoke tests
    └── …                    (etc. — see tests/desktop/ for the full set)
```

## Running Tests

```bash
# All unit + integration (fast, no browser required)
pytest -m "not e2e"

# Unit tests only
pytest tests/unit -m unit -v

# Integration tests only
pytest tests/integration -m integration -v

# E2E tests (requires Playwright browsers installed)
playwright install chromium
pytest tests/e2e -m e2e -v

# Desktop tests (no display needed — PySide6/pystray fully mocked)
pytest tests/desktop/ -v

# Full suite with coverage
pytest --cov=netcanon --cov-report=term-missing

# Parallel execution (unit + integration only — E2E is session-scoped)
pytest -m "not e2e" -n auto
```

One unit module is slower than its neighbours on purpose:
`tests/unit/test_untrusted_text_cost.py` reads the clock.  It builds a
text for every regex the product holds and times every codec's `probe`
and `parse` on a capture with a run put into it, to find code whose
cost grows faster than its input.  It takes tens of seconds, and far
longer when it fails, because what it has then found is slow.  It is
built not to flake: a reading is the CPU time the test's own thread
had, not time on the wall (on a shared runner the wall clock put
another process's turn into one reading and not the next, and took a
linear parse for a defect); each is the best of several; a text that
looks slow is read again; and a step that still looks steep has to be
steep at another size too before anything is called slow.  So a
failure there is something to look at before it is retried.  The longer
search for the same thing — every line and block of every capture
written many times over — is not a test: `python
tools/stanza_cost_search.py` takes minutes and is run by hand when a
parser's handler changes (`tests/unit/tools/test_stanza_cost_search.py`
pins that it can find what it is for).

Two of its checks read no clock.  `TestNoListIsLookedThroughThenAddedTo`
in the same module reads the source for a list that one function both
looks through and adds to (`if x not in lst: lst.append(x)`); a new one
fails until it is mended (`Uniques`, or a set kept beside the list) or
entered in that module's `LOOKED_THROUGH` with the bound that makes it
harmless.  And `tests/unit/migration/test_projection_makes_what_is_kept.py`
counts memory, in bytes, with `tracemalloc`: what a VLAN id on a port
and a port on a VLAN may cost while a config is parsed, and what a
trunk that states no allowed list — every VLAN, on some platforms —
costs in the tree that is kept.  Those
ceilings are several times what is measured, so one that fails means
an entry has come to cost several times what it did.

## Test Isolation

| Layer       | Isolation mechanism |
|-------------|---------------------|
| Unit        | `pytest tmp_path` — fresh tmp dir per test |
| Integration | `create_app(test_settings)` factory — independent in-memory state per test |
| E2E         | Session-scoped live server; function-scoped Playwright `page` |
| Desktop     | `sys.modules` injection — PySide6, pystray, and Pillow fully mocked per test |

## Mocking Strategy

SSH collection is mocked at a **single entry point**: `get_collector` in
`netcanon.api.routes.backups`.  This function is the sole factory that
maps a definition's strategy to a concrete collector instance.

- **Integration tests**: `unittest.mock.patch` in the `client` fixture
  (function-scoped, reapplied per test).
- **E2E tests**: `unittest.mock.patch` context manager wrapping the entire
  Uvicorn server lifetime (session-scoped, active for all E2E tests).

No test patches `ConnectHandler` or `paramiko.SSHClient` directly.

## Adding Tests

1. **Unit**: add a `test_*.py` file under `tests/unit/`.  Decorate with
   `pytestmark = pytest.mark.unit`.  Avoid any I/O beyond `tmp_path`.

2. **Integration**: add a `test_*.py` file under `tests/integration/`.
   Use the `client` fixture — it provides a `TestClient` with SSH mocked.

3. **E2E**: add a `test_*.py` file under `tests/e2e/`.  Use the `page`
   fixture from pytest-playwright and helpers from `tests/e2e/helpers.py`.
   All selectors should use `data-testid` attributes.  A test of what
   an operator SEES reads what was painted, not a class name or a
   computed style: `tests/e2e/drawn.py` reads an element's background
   from a screenshot, turns a theme token into the colour it paints,
   and gives the contrast of the two (the theme's badge backgrounds are
   translucent, so a tint over a tint is not the colour either was
   asked for).  A bar down an element's edge and a ring round it are
   read from the pixels there as well (`painted_bar`, `painted_ring`):
   a `box-shadow` no pixels wide has a computed colour all the same.
   Read an ink on the element that holds the words, not on the box
   they are in.  It also holds the two helpers for the rename table's
   override lists, whose port options are made when a list is first
   used.  Synthetic definitions a test needs -- an `inferred` profile,
   a model family whose every string is markup -- live under
   `tests/fixtures/target_profiles/` and `tests/fixtures/model_families/`
   and are copied into the tier's definitions directory.

4. **Desktop**: add a `test_*.py` file under `tests/desktop/`.  Use the
   `mock_pyside6`, `mock_pystray`, and `mock_generate_tray_image` fixtures
   from `tests/desktop/conftest.py` to keep tests headless and fast.

### Config limits in tests

A parse that opens no limits scope runs under the `standard` config
limits (`netcanon/migration/limits.py`), in a test as anywhere else.
Two things follow.

* **A test of COST asks for the `no_config_limits` fixture**
  (`tests/conftest.py`).  Such a test builds texts no device has —
  forty thousand ports on one LAG — and the limits refuse some of them;
  a refused text is read quickly whatever the code behind it costs, so
  the test would pass on code that is slow.  `tests/unit/test_untrusted_text_cost.py`
  uses it for every test, and treats a reading that is refused all the
  same as an error.
* **A test of the limits says which limits**: `with
  limits_scope("small"):`, or a `Limits` of its own made with
  `dataclasses.replace` — a few thousand entries are enough to pass a
  limit of a few thousand, and nothing has to be large.
* **`limits_scope` never waits; `server_scope` can.**  Under `small` a
  server works on one request at a time, and the place is the
  PROCESS's: a test that holds it (a thread inside
  `server_scope("small")`) makes every `small` server in that test
  process wait, which is how the tests of "busy" work.  Such a test
  lets go in a `finally`, shows waiting with an event and never a
  sleep, and ends with `limits.in_flight() == (0, 0)`.
* **A place is the process's too** (`limits.places()`): under `small`
  the application counts a request that reads config text when its
  headers arrive.  A test fills the places with
  `limits.Answer().arrived("small")` and gives each back with
  `.sent()` in a `finally`; one that needs a client which stalls,
  leaves or does not read speaks to a real server over a socket
  (`_on_a_socket` in `tests/integration/test_config_limits_api.py`)
  or plays the server itself (`_Wire`, same module), and ends with
  `limits.places() == 0`.

Where the limits themselves are tested: `tests/unit/migration/test_limits.py`
(the mechanism, each limit, the measured texts, the deadline, and three
rules read from the source), `tests/unit/test_limits_docs_truth.py`
(every number a document prints), `tests/integration/test_config_limits_api.py`
(the refusal on every HTTP surface; every handler that takes config
text; one request at a time under `small`; a request counted before
its body is read; an answer nobody reads; the proofs of
`deploy/VERIFY.md`, run from that file),
`tests/integration/test_job_answer.py` (a job's answer, written a piece
at a time, is the framework's byte for byte), `tests/unit/test_cli.py`
(the command line),
`tests/desktop/test_config_limits_desktop.py` and
`test_preferences_dialog.py` (the preference, the control, the embedded
server) and `tests/e2e/test_config_limits_e2e.py` (the sentence as the
migrate and sanitise pages paint it).

## Markers

| Marker        | Meaning |
|---------------|---------|
| `unit`        | Pure-function tests, no I/O |
| `integration` | API-level tests using `TestClient`, no real SSH |
| `e2e`         | Full browser tests via Playwright against a live server |
| `desktop`     | Desktop-shell tests (PySide6 / pystray fully mocked).  Deselect with `-m "not desktop"`. |
| `cross_mesh`  | Cross-codec translation matrix tests (category × source × target).  **Aggregate runtime under this marker must stay under 30 seconds** as the matrix grows; cases running >500ms each should get demoted to Layer A per-codec unit tests.  See [`tests/unit/migration/test_cross_mesh_overrides.py`](unit/migration/test_cross_mesh_overrides.py). |

## See also

| Concern | See |
|---|---|
| Every interactive HTML element's `data-testid` | [`testid_reference.md`](testid_reference.md) — canonical E2E selector inventory |
| Real-capture fixture provenance + licensing | [`fixtures/real/NOTICE.md`](fixtures/real/NOTICE.md) |
| Codec certification state + coverage matrix | [`fixtures/real/RESULTS.md`](fixtures/real/RESULTS.md) |
| Cross-mesh fidelity reconciliation (Phase 4) | [`fixtures/real/PHASE4_RECONCILIATION.md`](fixtures/real/PHASE4_RECONCILIATION.md) |
| Operator-spotted cross-vendor bugs | [`fixtures/real/user_smoke_findings.md`](fixtures/real/user_smoke_findings.md) |
| Codec authoring (how to add a new vendor) | [`../netcanon/migration/codecs/README.md`](../netcanon/migration/codecs/README.md) |
| Device-definition + target-profile schema | [`../netcanon/definitions/library/README.md`](../netcanon/definitions/library/README.md) |
| Project orientation + quickstart | [`../README.md`](../README.md) |
| Contributor rules + hard rules | [`../AGENTS.md`](../AGENTS.md) |
| Phase 4b fix-task prompt drafts | [`fixtures/real/phase4_spawn_tasks.md`](fixtures/real/phase4_spawn_tasks.md) |
