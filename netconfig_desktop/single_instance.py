"""
Single-instance enforcement using a Windows named mutex.

Prevents the user from accidentally launching a second NetConfig
process — the second copy would fail to bind the embedded server's
TCP port (8765 by default) and surface as a fatal-error MessageBox.
That's confusing for non-technical users because tray icons are easy
to overlook; refusing to start a duplicate up-front is friendlier.

Design notes:

* The mutex is opened with ``CreateMutexW`` and **must remain held**
  for the lifetime of the process.  Releasing the handle (e.g. via
  Python's GC) frees the name and lets a second instance acquire it.
  We therefore stash the handle in a module-level variable.
* The mutex name is in the ``Global\\`` namespace so the check works
  across user sessions on the same machine; this matches the desktop
  workflow where one user installs and launches NetConfig.
* On non-Windows platforms (Linux / macOS test runs) the function
  always returns True — desktop is Windows-only per the
  Platform-Specific Exceptions in CLAUDE.md.

Usage::

    if not acquire_singleton():
        # Already running.  Show a friendly hint and exit.
        sys.exit(0)
"""
from __future__ import annotations

import sys
from typing import Any

#: Win32 ``GetLastError()`` value indicating CreateMutex found an
#: existing object with the same name.
ERROR_ALREADY_EXISTS: int = 183

#: Globally-visible mutex name.  The ``v1`` suffix lets us bump the
#: name in a future release if we ever want to coexist with old
#: installs deliberately.
_MUTEX_NAME: str = "Global\\NetConfigSingleInstance_v1"

#: Module-level reference so the mutex handle stays alive for the
#: full process lifetime.  Do NOT replace with a local — Python GC
#: would close the handle and release the name.
_mutex_handle: Any | None = None


def acquire_singleton() -> bool:
    """Acquire the single-instance mutex on Windows.

    Returns True if this is the first instance.  Returns False if
    another instance is already running (the Win32 layer reported
    ``ERROR_ALREADY_EXISTS`` after ``CreateMutexW``).

    On non-Windows platforms returns True unconditionally so the
    test suite can run on Linux / macOS CI without faking a Win32
    layer.
    """
    global _mutex_handle
    if sys.platform != "win32":
        return True

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD

    _mutex_handle = kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    last_error = kernel32.GetLastError()
    return last_error != ERROR_ALREADY_EXISTS
