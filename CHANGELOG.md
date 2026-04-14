# Changelog

All notable changes to NetConfig are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added (logging)

- **`netconfig/logging_config.py`** — New `configure_logging(level, log_file)` function.
  Sets up a `StreamHandler` (stderr) plus an optional `RotatingFileHandler` (5 MB, 3
  backups) on the root logger.  Idempotent: skips when real (non-pytest) handlers are
  already present.  Suppresses `paramiko`, `uvicorn.access`, `multipart`, and `asyncio`
  to `WARNING` regardless of root level to reduce noise in INFO/DEBUG runs.
- **`netconfig_desktop/__main__.py`** — `_configure_logging()` called before
  `DesktopApp()`.  In frozen (installed) mode writes to
  `%APPDATA%\NetConfig\netconfig.log`; in dev mode uses console only.  Fatal startup
  exceptions now go through `logger.critical(..., exc_info=True)` before the message
  box so the stack trace is captured in the log file.
- **`netconfig_desktop/server.py`** — `log_config=None` added to `uvicorn.Config` so
  uvicorn's startup does not call `logging.config.dictConfig()` and overwrite the root
  logger configuration set by `configure_logging()`.
- **`netconfig_desktop/settings.py`** — `log_level` default raised from `"warning"` to
  `"info"` so desktop INFO logs reach the file handler.

### Changed (logging)

- **`netconfig/api/routes/backups.py`** — Device backup failures upgraded from
  `WARNING` to `ERROR` and now include `exc_info=True` for full traceback capture.
- **`netconfig/api/routes/configs.py`** — Added module logger; all three endpoints now
  emit structured log records (`DEBUG` for list/get, `INFO` for delete success,
  `WARNING` for 404 paths).
- **`netconfig/api/routes/definitions.py`** — Added module logger; reload endpoint
  logs loaded count and source directory at `INFO`.
- **`netconfig/storage/file_store.py`** — Added module logger; `save()` logs filename
  and byte count at `INFO`, `list_configs()` at `DEBUG`, `delete()` at `INFO`.
- **`netconfig_desktop/app.py`** — Lifecycle events (start, server ready, quit, window
  closed) logged at `INFO`.
- **`netconfig_desktop/tray.py`** — Added module logger; `run_detached()` at `DEBUG`,
  Show/Quit callbacks at `DEBUG`/`INFO`, `stop()` exception swallowed at `DEBUG`
  (was silent).
- **`netconfig_desktop/window.py`** — Added module logger; `create()` and `start()` at
  `INFO`, show/hide/destroy at `DEBUG`, `on_closed` callback exception at `DEBUG`
  (was silent).

### Tests (logging)

- `tests/unit/test_logging_config.py` — 17 new unit tests across three classes:
  `TestConfigureLoggingBasic` (handler type, levels, idempotency),
  `TestFileHandler` (rotating handler, directory creation, write-through),
  `TestNoisyLoggerSuppression` (third-party loggers capped at WARNING, netconfig.*
  left at NOTSET).  `reset_root_logger` autouse fixture restores root logger state
  after each test.

---

### Fixed

- **`configs.html`** — Post-delete empty-check used CSS selector `.config-row`
  (no such class) instead of `[data-testid="config-row"]`, causing the page to
  reload after *every* deletion rather than only when the last config was removed.
- **`base.html`** — Removed orphaned `.badge-success` CSS rule that duplicated
  `.badge-completed` and leaked device-result vocabulary into the job-level badge
  namespace.

### Added

- **`POST /api/v1/definitions/reload`** — New API endpoint that re-reads all YAML
  files from `definitions_dir` and replaces the in-memory registry without a server
  restart.  Returns `{ "loaded": N, "type_keys": [...] }`.
- **Definitions page** — "↻ Reload" button (`data-testid="def-reload-btn"`) that
  calls the new reload endpoint and refreshes the page on success.
- **Configs page** — "View" link (`data-testid="config-view-link"`) and download
  button (`data-testid="config-download-btn"`) are now separate explicit actions in
  the Actions column.  The filename cell is now plain text.
- **Toast notifications** (`data-testid="toast"`) — Global `showToast(msg, type)`
  function in `base.html` replaces all `alert()` calls with a non-blocking,
  auto-dismissing notification (4 s timeout).  Types: `info`, `success`, `error`.
- **Inline job results** — After a backup job completes, per-device results
  (host, type, success/failure, error message) are rendered directly in the status
  banner.  The recent-jobs table row is injected by JS; no full-page reload occurs.
- **Active nav state** — Current page is highlighted in the navbar
  (`class="active"`, `aria-current="page"`).  `active_page` context variable added
  to all three UI route responses in `main.py`.
- **UTC timestamp localisation** — All `[data-utc]` elements are converted to
  browser-local time on `DOMContentLoaded` via a global script in `base.html`.
  Server-rendered fallback (UTC string) is preserved for non-JS contexts.
- **Enable Password conditional visibility** — The Enable Password field is shown
  only for device types where `connection.needs_enable` is `true`.  Driven by
  `data-needs-enable` attributes on `<option>` elements; toggled on type change.
- **Port collapsed to Advanced** — The SSH port field (default 22, rarely changed)
  is now inside a `<details>` summary labelled "⚙ Port", reducing visual noise in
  the backup form.
- **Inline delete confirmation** — The Delete button on the Configs page now shows
  an in-row "Delete? Yes / No" prompt instead of the browser's native `confirm()`
  dialog (which can be suppressed in embedded WebView contexts).
- **Empty-state guidance** — All three pages now include actionable text in their
  empty states rather than bare declarative messages.

### Changed

- **Nav brand** (`data-testid="nav-brand"`) changed from `<span>` to `<a href="/">`
  so clicking the product name navigates home, per standard convention.
- **Submit button** (`data-testid="submit-backup-btn"`) is now disabled and labelled
  "Running…" while a backup job is in flight, preventing double-submission.
- **Polling error handling** — The job-status polling `setInterval` now counts
  consecutive fetch failures and stops after 3, showing a toast instead of silently
  looping forever.
- **Jobs table** — "Devices" column removed (redundant with "Success / Total"
  denominator).  "Job ID" column is now plain text (`data-testid="job-id-text"`)
  rather than a link to the raw JSON API response.  "Created (UTC)" header
  simplified to "Created" (timestamps are localised by JS).
- **Configs table** — "Captured (UTC)" column header simplified to "Captured".
  Filename column is now plain text; view/download actions moved to the Actions
  column.
- **Definitions table** — "Strategy" column renamed to "Collection"; strategy
  values are now human-readable ("SSH (Netmiko)", "SSH (Shell)") rather than
  internal Python identifiers.  "Ext" column header renamed to "File Ext".
  Notes cell gains a `title` tooltip showing the full (untruncated) text.
- **`button:disabled`** CSS rule added to `base.html` — disabled buttons now show
  `opacity: 0.6` and `cursor: not-allowed` globally.
- **E2E test** `test_submit_completes_and_page_reloads` renamed to
  `test_submit_completes_and_shows_job_in_table` and updated to assert that the
  jobs table becomes visible via JS injection (no `wait_for_load_state` needed).
- **Remove device button** gains `aria-label="Remove this device"` for
  accessibility.

### Tests

- `tests/integration/test_definitions_api.py` — Added `TestReloadDefinitions`
  (5 tests): 200 response, loaded count, type_keys list, post-reload registry
  accessibility, idempotency.
- `tests/testid_reference.md` — Updated for all new/changed testids: `toast`,
  `job-id-text` (replaces `job-link`), `config-view-link` (moved to Actions),
  `config-download-btn`, `config-delete-confirm-btn`, `config-delete-cancel-btn`,
  `def-reload-btn`.  Notes added for conditional visibility and `data-utc`.

---

## [0.1.0] — initial release

- Multi-vendor SSH configuration backup via Netmiko and Paramiko Shell strategies
- FastAPI + Jinja2 web UI: Dashboard, Configs browser, Definitions viewer
- Windows desktop shell: PySide6/QtWebEngine window, pystray system-tray icon,
  embedded Uvicorn server (`netconfig_desktop`)
- cx_Freeze MSI installer (`setup_desktop.py`)
- Four-layer test suite: unit, integration, E2E (Playwright), desktop
