# NetConfig — Contributor Directives

These directives govern all development in this repository.  Follow them in
every session without being asked.

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
  via `connection.handle_paging: true` in the YAML definition.
- **Never** commit real credentials, device IPs, or secrets.
- **Never** skip `data-testid` attributes on new interactive template elements.
- **Never** patch `ConnectHandler` or `paramiko.SSHClient` directly in tests —
  patch `netconfig.api.routes.backups.get_collector` instead (the single
  factory used by the backup route).
- **Never** assert on the POST `/api/v1/backups` response body for final job
  state — it always returns `pending` (serialised before background task runs).
  Always GET the job by ID to read the completed state.
