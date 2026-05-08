"""
Unit tests for ``netcanon_desktop.single_instance``.

Mocks ``ctypes.windll.kernel32`` so the tests run on Linux / macOS CI
without a real Win32 layer.  Verifies:

* Fresh acquisition returns True.
* When ``GetLastError`` reports ``ERROR_ALREADY_EXISTS`` the function
  returns False.
* On non-Windows platforms the function returns True unconditionally.
* The module-level handle reference outlives the function call so the
  mutex isn't immediately released by Python's garbage collector.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.desktop


# A sentinel value standing in for the Win32 mutex HANDLE.
FAKE_HANDLE = 0xDEADBEEF


@pytest.fixture(autouse=True)
def _reset_module_handle():
    """Clear the module-level handle between tests so each test sees
    a clean slate."""
    import netcanon_desktop.single_instance as si

    si._mutex_handle = None
    yield
    si._mutex_handle = None


class TestNonWindowsAlwaysReturnsTrue:
    def test_linux_returns_true_without_calling_kernel32(self):
        from netcanon_desktop import single_instance

        with patch.object(sys, "platform", "linux"):
            assert single_instance.acquire_singleton() is True

    def test_darwin_returns_true_without_calling_kernel32(self):
        from netcanon_desktop import single_instance

        with patch.object(sys, "platform", "darwin"):
            assert single_instance.acquire_singleton() is True

    def test_handle_remains_none_on_non_windows(self):
        from netcanon_desktop import single_instance

        with patch.object(sys, "platform", "linux"):
            single_instance.acquire_singleton()
        assert single_instance._mutex_handle is None


class TestWindowsAcquisition:
    def _patch_kernel32(self, last_error: int):
        """Build a fake ``ctypes.windll`` whose CreateMutexW returns
        FAKE_HANDLE and GetLastError returns *last_error*.
        """
        kernel32 = MagicMock(name="kernel32")
        kernel32.CreateMutexW.return_value = FAKE_HANDLE
        kernel32.GetLastError.return_value = last_error
        # Provide argtypes/restype slots that the implementation
        # assigns to (so MagicMock doesn't raise on attribute set).
        kernel32.CreateMutexW.argtypes = []
        kernel32.CreateMutexW.restype = None
        kernel32.GetLastError.argtypes = []
        kernel32.GetLastError.restype = None

        windll = MagicMock(name="windll")
        windll.kernel32 = kernel32
        return windll, kernel32

    def test_first_instance_returns_true(self):
        from netcanon_desktop import single_instance

        windll, kernel32 = self._patch_kernel32(last_error=0)
        with (
            patch.object(sys, "platform", "win32"),
            patch("ctypes.windll", windll),
        ):
            assert single_instance.acquire_singleton() is True
        kernel32.CreateMutexW.assert_called_once()

    def test_second_instance_returns_false(self):
        from netcanon_desktop import single_instance

        windll, kernel32 = self._patch_kernel32(
            last_error=single_instance.ERROR_ALREADY_EXISTS
        )
        with (
            patch.object(sys, "platform", "win32"),
            patch("ctypes.windll", windll),
        ):
            assert single_instance.acquire_singleton() is False

    def test_handle_persisted_at_module_level(self):
        """Regression guard against the GC-foot-gun: the implementation
        MUST stash the handle on the module so it isn't released when
        the function returns."""
        from netcanon_desktop import single_instance

        windll, kernel32 = self._patch_kernel32(last_error=0)
        with (
            patch.object(sys, "platform", "win32"),
            patch("ctypes.windll", windll),
        ):
            single_instance.acquire_singleton()

        assert single_instance._mutex_handle == FAKE_HANDLE

    def test_mutex_name_uses_global_namespace(self):
        """The mutex name is in the ``Global\\`` namespace so it works
        across user sessions on the same machine."""
        from netcanon_desktop import single_instance

        assert single_instance._MUTEX_NAME.startswith("Global\\")

    def test_mutex_name_includes_version_suffix(self):
        """The name includes a version suffix so we can bump it later
        without colliding with the old name."""
        from netcanon_desktop import single_instance

        assert "_v" in single_instance._MUTEX_NAME

    def test_create_mutex_called_with_global_name(self):
        from netcanon_desktop import single_instance

        windll, kernel32 = self._patch_kernel32(last_error=0)
        with (
            patch.object(sys, "platform", "win32"),
            patch("ctypes.windll", windll),
        ):
            single_instance.acquire_singleton()
        # Third positional arg is the LPCWSTR mutex name
        args = kernel32.CreateMutexW.call_args[0]
        assert args[2] == single_instance._MUTEX_NAME
