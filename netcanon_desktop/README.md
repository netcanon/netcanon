# Netcanon Desktop

Windows desktop shell for the Netcanon web application.

The desktop package wraps the existing `netcanon` FastAPI application in a
native Windows experience without modifying any web-layer code:

* A PySide6/QtWebEngine window shows the full web UI.
* A system-tray icon provides **Show** and **Quit** actions when the window
  is minimized to the tray.
* An embedded Uvicorn server runs on `127.0.0.1:8765` in a daemon thread.

---

## Running from Source

```bash
pip install -e ".[desktop]"
python -m netcanon_desktop
```

## Building an MSI Installer

```bash
pip install -e ".[desktop-build]"
python setup_desktop.py bdist_msi
# Installer written to dist/
```

The MSI:
* Installs to `C:\Program Files\Netcanon\`
* Creates a Start Menu shortcut (pinnable to the taskbar)
* Uses `base="Win32GUI"` — no console window

---

## Architecture

```
netcanon_desktop/
├── __main__.py             Entry point: bootstraps DesktopApp, single-instance guard, MessageBoxW on fatal error
├── app.py                  DesktopApp — top-level orchestrator (server + tray + window)
├── server.py               ServerThread — Uvicorn in a daemon thread, threading.Event readiness
├── tray.py                 TrayIcon — pystray Show/Preferences/Open configs/Quit menu, run_detached()
├── window.py               WebViewWindow — PySide6 QMainWindow + QWebEngineView
├── settings.py             desktop_settings() — path resolution for frozen vs. dev mode + preferences overlay
├── preferences.py          DesktopPreferences — operator-configurable Pydantic model + JSON load/save
├── preferences_dialog.py   PreferencesDialog — PySide6 QDialog (paths / port / toggles / Open Configs Folder)
├── single_instance.py      acquire_singleton() — Windows named-mutex guard against duplicate launches
└── icons.py                Pillow icon generation — no binary assets committed
```

### Threading Model

| Thread | Owns | Blocks? |
|--------|------|---------|
| Main | `QApplication.exec()` — Qt/WebEngine event loop | Yes — until `destroy()` |
| Daemon | Uvicorn HTTP server (`ServerThread`) | Yes — killed on main exit |
| Detached | pystray tray icon (`TrayIcon.run_detached()`) | No |

### Startup Sequence

```
DesktopApp.run()
├── ServerThread.start()          # spin up Uvicorn daemon thread
├── ServerThread.wait_ready()     # block until HTTP socket is accepting
├── TrayIcon.run_detached()       # spin up pystray (non-blocking)
├── WebViewWindow.create()        # build QMainWindow + QWebEngineView
└── WebViewWindow.start()         # ← BLOCKS (Qt event loop on main thread)
```

### Shutdown Sequences

**User clicks Quit in tray menu:**
```
TrayIcon._handle_quit()
├── TrayIcon.stop()
├── ServerThread.stop()
└── WebViewWindow.destroy()   → posts QApplication.quit() → unblocks start()
```

**User clicks ✕ on window:**
```
QMainWindow.closeEvent → WebViewWindow._handle_close(event)
└── event.ignore() + WebViewWindow.hide()   (window hides to tray, app keeps running)
```

---

## Settings

`desktop_settings()` in `settings.py` returns a `Settings` instance with paths
appropriate for the current execution context:

| Context | `definitions_dir` | `configs_dir` | Data root (`jobs/`, `schedules/`, `devices/`, logs) |
|---------|------------------|---------------|-----|
| Dev (unfrozen) | `<repo_root>/definitions/` | `<repo_root>/configs/` | `<repo_root>/` |
| Frozen (cx_Freeze) | `<install_dir>/definitions/` | `%APPDATA%\Netcanon\configs\` | `%APPDATA%\Netcanon\` |

The data root holds the operational JSON state stores derived under it as
`jobs/`, `schedules/`, and `devices/` subdirectories.  By default the root
is `configs_dir.parent`, but an explicit `Settings.data_dir` (or a
`data_dir` field in `preferences.json`) overrides that derivation via the
`Settings.effective_data_dir` property.

`configs_dir` is always created if it does not exist.

### Preferences

Operators can override the platform defaults via a Preferences dialog
reachable from the system-tray menu (**Preferences…**).  Settings are
persisted to `%APPDATA%\Netcanon\preferences.json` as a small JSON
document:

| Field | Effect when set |
|-------|-----------------|
| `configs_dir` | Override the captured-config storage directory |
| `definitions_dir` | Override the YAML device-definitions directory |
| `data_dir` | Override the data root for `jobs/` / `schedules/` / `devices/` |
| `port` | Embedded server TCP port (1024–65535; restart required) |
| `open_in_editor` | Enable the "Open in editor" UI surface |
| `open_browser_on_start` | Reserved — currently no-op, kept forward-compatible |

The file is written by `DesktopPreferences.save()` and re-read by
`desktop_settings()` on startup.  Dev mode (running from source)
deliberately ignores `preferences.json` so contributor workflow stays
predictable regardless of `%APPDATA%` contents.

`DesktopPreferences.load()` is corruption-tolerant: a malformed JSON
file returns factory defaults rather than crashing the app.  The
operator can re-open the dialog and re-save to repair it.

### Uninstall behaviour

The MSI installer deliberately preserves `%APPDATA%\Netcanon\` on
uninstall so user-captured configurations, jobs history, schedules,
and preferences survive a reinstall / upgrade cycle.  To remove all
user data after uninstalling, delete that folder manually.

---

## Icon

The application icon is generated at runtime by `icons.py` using Pillow:

* Dark navy rounded rectangle (`#1a1a2e`) with light-blue "NC" monogram (`#7eb8f7`)
* Multi-resolution ICO written to `%TEMP%\netcanon.ico` at startup: 16, 32, 48, 128, 256 px
* No binary image assets are committed to the repository

---

## Platform Notes

pywebview was the original backend choice but requires `pythonnet` on Windows,
which has no pre-built wheel for Python ≥ 3.13 and fails to compile without a
.NET SDK.  PySide6 6.7+ ships pre-built Chromium WebEngine wheels for Python
3.14 and is used instead.

All `show()` / `hide()` / `destroy()` calls are posted via
`QMetaObject.invokeMethod(..., QueuedConnection)` so they are safe to call from
the pystray background thread.

---

## See also

- [`../README.md`](../README.md) — project orientation and quickstart (web + desktop share the same FastAPI backend)
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — the four-layer design that desktop wraps
- [`../CLAUDE.md`](../CLAUDE.md) — parallel-platform contributor directives (the "feature parity" rule lives here)
