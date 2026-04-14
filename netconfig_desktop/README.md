# NetConfig Desktop

Windows desktop shell for the NetConfig web application.

The desktop package wraps the existing `netconfig` FastAPI application in a
native Windows experience without modifying any web-layer code:

* A PySide6/QtWebEngine window shows the full web UI.
* A system-tray icon provides **Show** and **Quit** actions when the window
  is minimized to the tray.
* An embedded Uvicorn server runs on `127.0.0.1:8765` in a daemon thread.

---

## Running from Source

```bash
pip install -e ".[desktop]"
python -m netconfig_desktop
```

## Building an MSI Installer

```bash
pip install -e ".[desktop-build]"
python setup_desktop.py bdist_msi
# Installer written to dist/
```

The MSI:
* Installs to `C:\Program Files\NetConfig\`
* Creates a Start Menu shortcut (pinnable to the taskbar)
* Uses `base="Win32GUI"` — no console window

---

## Architecture

```
netconfig_desktop/
├── __main__.py     Entry point: bootstraps DesktopApp, shows MessageBoxW on fatal error
├── app.py          DesktopApp — top-level orchestrator (server + tray + window)
├── server.py       ServerThread — Uvicorn in a daemon thread, threading.Event readiness
├── tray.py         TrayIcon — pystray Show/Quit menu, run_detached()
├── window.py       WebViewWindow — PySide6 QMainWindow + QWebEngineView
├── settings.py     desktop_settings() — path resolution for frozen vs. dev mode
└── icons.py        Pillow icon generation — no binary assets committed
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

| Context | `definitions_dir` | `configs_dir` |
|---------|------------------|---------------|
| Dev (unfrozen) | `<repo_root>/definitions/` | `<repo_root>/configs/` |
| Frozen (cx_Freeze) | `<install_dir>/definitions/` | `%APPDATA%\NetConfig\configs\` |

`configs_dir` is always created if it does not exist.

---

## Icon

The application icon is generated at runtime by `icons.py` using Pillow:

* Dark navy rounded rectangle (`#1a1a2e`) with light-blue "NC" monogram (`#7eb8f7`)
* Multi-resolution ICO written to `%TEMP%\netconfig.ico` at startup: 16, 32, 48, 128, 256 px
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
