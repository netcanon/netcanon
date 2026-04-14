"""
Entry point for ``python -m netconfig_desktop``.

Bootstraps the ``DesktopApp`` and hands control to it.  Any fatal startup
error (server timeout, WebView2 not available, etc.) is reported in a message
box rather than a traceback to the console, since the application runs without
a visible console when built with ``base="Win32GUI"``.
"""
from __future__ import annotations

import sys


def main() -> None:
    """Bootstrap the NetConfig desktop application."""
    try:
        from netconfig_desktop.app import DesktopApp

        app = DesktopApp()
        app.run()
    except Exception as exc:  # noqa: BLE001
        _fatal(str(exc))


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
