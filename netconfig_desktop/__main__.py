"""
Entry point for ``python -m netconfig_desktop``.

Bootstraps the ``DesktopApp`` and hands control to it.  Any fatal startup
error (server timeout, WebView2 not available, etc.) is reported in a message
box rather than a traceback to the console, since the application runs without
a visible console when built with ``base="Win32GUI"``.
"""
from __future__ import annotations

import logging
import sys


def main() -> None:
    """Bootstrap the NetConfig desktop application."""
    _configure_logging()
    logger = logging.getLogger(__name__)
    try:
        from netconfig_desktop.app import DesktopApp

        app = DesktopApp()
        app.run()
    except Exception as exc:  # noqa: BLE001
        logger.critical("Fatal startup error", exc_info=True)
        _fatal(str(exc))


def _configure_logging() -> None:
    """Set up the root logger before any other module is imported.

    Uses the frozen-vs-dev detection from ``netconfig_desktop.settings`` to
    decide whether to write a log file.  In frozen (installed) mode the log
    goes to ``%APPDATA%\\NetConfig\\netconfig.log``; in dev mode only the
    console handler is added.
    """
    import os
    from pathlib import Path

    from netconfig.logging_config import configure_logging

    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        log_file = base / "NetConfig" / "netconfig.log"
    else:
        log_file = None  # console only in development

    configure_logging(level="INFO", log_file=log_file)


def _fatal(message: str) -> None:
    """Show a message box and exit — works even without a console window."""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0,
            f"NetConfig failed to start:\n\n{message}",
            "NetConfig — Fatal Error",
            0x10,  # MB_ICONERROR
        )
    except Exception:  # noqa: BLE001
        print(f"FATAL: {message}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
