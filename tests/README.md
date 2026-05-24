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
    └── test_backups_<vendor>_desktop.py  Per-vendor embedded-server smoke tests
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
   All selectors should use `data-testid` attributes.

4. **Desktop**: add a `test_*.py` file under `tests/desktop/`.  Use the
   `mock_pyside6`, `mock_pystray`, and `mock_generate_tray_image` fixtures
   from `tests/desktop/conftest.py` to keep tests headless and fast.

## Markers

| Marker        | Meaning |
|---------------|---------|
| `unit`        | Pure-function tests, no I/O |
| `integration` | API-level tests using `TestClient`, no real SSH |
| `e2e`         | Full browser tests via Playwright against a live server |
| `desktop`     | Desktop-shell tests (PySide6 / pystray fully mocked).  Deselect with `-m "not desktop"`. |
| `slow`        | Tests that take longer than ~5 seconds |
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
| Device-definition + target-profile schema | [`../definitions/README.md`](../definitions/README.md) |
