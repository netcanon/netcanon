"""
Tests for :func:`netcanon.api._errors.translate_backup_error`.

The translator is the Phase-3 Round-3 fix for the pre-Round-3
``str(exc)`` antipattern in ``netcanon/api/routes/backups.py:355``.
These tests pin the operator-visible contract per exception class
so the mapping table can evolve without silently regressing on
high-value messages (auth failures, DNS, refused connections, etc.).

Strategy:

* Parametrized happy-path: every mapped exception type produces a
  host-prefixed single-line string under the wire-cap, containing
  the expected actionable substring.
* Targeted regression tests: storage path-leak guard, paramiko SSH
  multi-line trimming, fallback for unknown types.
"""

from __future__ import annotations

import socket

import paramiko
import pytest
from netmiko import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

from netcanon.api._errors import translate_backup_error


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Parametrized happy-path coverage
# ---------------------------------------------------------------------------
#
# (exception_instance, substring_that_must_appear_in_translation).  The
# substring assertion is loose-coupled to copy: it pins the OPERATOR
# CONCEPT (e.g. "DNS lookup failed") not the exact wording, so the
# mapping table can rephrase without breaking the test.

@pytest.mark.parametrize("exc, expected_substring", [
    # Authentication failures — both SSH layers.
    pytest.param(
        paramiko.AuthenticationException("Authentication failed."),
        "SSH authentication failed",
        id="paramiko-auth",
    ),
    pytest.param(
        NetmikoAuthenticationException("Authentication to device failed"),
        "SSH authentication failed",
        id="netmiko-auth",
    ),
    # Timeouts — Netmiko-specific (multi-line "see also" stripper) before
    # generic socket timeout.
    pytest.param(
        NetmikoTimeoutException("read_timeout exceeded"),
        "Connection or command-read timed out",
        id="netmiko-timeout",
    ),
    pytest.param(
        TimeoutError("timed out"),
        "Connection timed out",
        id="socket-timeout",
    ),
    # SSH protocol errors that aren't auth.
    pytest.param(
        paramiko.SSHException("Error reading SSH protocol banner"),
        "SSH protocol error",
        id="paramiko-ssh",
    ),
    # Network reachability.
    pytest.param(
        socket.gaierror(-2, "Name or service not known"),
        "DNS lookup failed",
        id="gaierror",
    ),
    pytest.param(
        ConnectionRefusedError(111, "Connection refused"),
        "Connection refused",
        id="connection-refused",
    ),
    pytest.param(
        ConnectionResetError(104, "Connection reset by peer"),
        "Connection lost",
        id="connection-reset",
    ),
    pytest.param(
        BrokenPipeError(32, "Broken pipe"),
        "Connection lost",
        id="broken-pipe",
    ),
    # Encoding mismatch.
    pytest.param(
        UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "invalid start byte"),
        "valid UTF-8",
        id="unicode-error",
    ),
    # In-house ValueError — passthrough (already operator-readable).
    pytest.param(
        ValueError("Config content exceeds max size (60000000 bytes > 52428800 bytes)"),
        "Config content exceeds max size",
        id="value-error-passthrough",
    ),
    # Generic OSError → storage error mapping.
    pytest.param(
        OSError(28, "No space left on device"),
        "Storage error",
        id="oserror-disk-full",
    ),
    pytest.param(
        PermissionError(13, "Permission denied"),
        "Storage error",
        id="permission-error",
    ),
    # Our-bug catchall (no fabricated actionable message).
    pytest.param(
        KeyError("missing_definition_field"),
        "Internal error (KeyError)",
        id="key-error",
    ),
    pytest.param(
        AttributeError("'NoneType' object has no attribute 'collect'"),
        "Internal error (AttributeError)",
        id="attribute-error",
    ),
    # Fully unknown — fallback path.
    pytest.param(
        RuntimeError("simulated unknown failure"),
        "Backup failed: RuntimeError",
        id="fallback",
    ),
])
class TestTranslateBackupError:
    """Per-exception-type happy-path assertions."""

    def test_host_prefix(self, exc, expected_substring):
        """Every translation is prefixed with ``[host] `` so operators
        running parallel backups can identify which device failed."""
        out = translate_backup_error(exc, host="10.0.0.5")
        assert out.startswith("[10.0.0.5] ")

    def test_contains_expected_substring(self, exc, expected_substring):
        """The mapping produces the right operator concept."""
        out = translate_backup_error(exc, host="10.0.0.5")
        assert expected_substring in out, (
            f"expected {expected_substring!r} in translation, got: {out!r}"
        )

    def test_single_line(self, exc, expected_substring):
        """Translations must be single-line for toast / table-cell display."""
        out = translate_backup_error(exc, host="10.0.0.5")
        assert "\n" not in out, f"multi-line translation: {out!r}"

    def test_under_wire_cap(self, exc, expected_substring):
        """The caller does ``[:500]`` truncation; we should comfortably
        stay under that on natural string length so the cap never
        actually truncates an operator-visible message."""
        out = translate_backup_error(exc, host="10.0.0.5")
        assert len(out) < 500, f"translation length {len(out)} ≥ 500: {out!r}"


# ---------------------------------------------------------------------------
# Targeted regression tests
# ---------------------------------------------------------------------------


def test_storage_error_does_not_leak_server_filesystem_path():
    """Pre-Round-3, the generic ``f"Could not write: {exc}"`` echoed
    the OSError's ``.filename`` to the operator — exposing internal
    server filesystem layout.  The translator must suppress
    server-side paths.
    """
    # OSError with a filename argument — the canonical "path leaks
    # through str(exc)" shape.
    exc = OSError(
        28,
        "No space left on device",
        "/var/lib/secrets/netcanon/configs/Cisco_10.0.0.5_20260512_123456.cfg",
    )
    out = translate_backup_error(exc, host="10.0.0.5")
    assert "/var/lib" not in out
    assert "/secrets" not in out
    assert "configs/Cisco_10.0.0.5_20260512_123456.cfg" not in out


def test_paramiko_ssh_exception_trims_to_first_line():
    """``paramiko.SSHException`` messages occasionally embed embedded
    tracebacks or multi-line context.  The translator must keep the
    output single-line for toast display.
    """
    exc = paramiko.SSHException(
        "Error reading SSH protocol banner\nFull context:\n"
        "  File 'transport.py', line 2000, in _check_banner\n"
        "  buf = self.packetizer.readline(timeout)\n"
        "  ..."
    )
    out = translate_backup_error(exc, host="10.0.0.5")
    assert "\n" not in out
    assert "Error reading SSH protocol banner" in out
    # The embedded traceback lines must NOT appear.
    assert "transport.py" not in out
    assert "_check_banner" not in out


def test_value_error_passthrough_preserves_useful_messages():
    """In-house ValueErrors (file_store cap, missing definition fields)
    are written carefully and should reach the operator verbatim
    after only the host prefix is added."""
    exc = ValueError(
        "netmiko_device_type is not set for definition 'Cisco'"
    )
    out = translate_backup_error(exc, host="10.0.0.5")
    assert "[10.0.0.5] netmiko_device_type is not set" in out
    assert "definition 'Cisco'" in out


def test_unknown_exception_uses_fallback_with_type_hint():
    """Fully novel exception types reach the fallback formatter, which
    surfaces the type name so a maintainer reading the operator's bug
    report can grep the source for the raise-site."""

    class _NeverSeenBefore(Exception):
        pass

    exc = _NeverSeenBefore("opaque error from nowhere")
    out = translate_backup_error(exc, host="10.0.0.5")
    assert out.startswith("[10.0.0.5] Backup failed: _NeverSeenBefore")
    assert "see the server log" in out


def test_socket_timeout_alias_for_TimeoutError():
    """``socket.timeout`` is aliased to ``TimeoutError`` on Python ≥3.10
    (we require ≥3.11 per pyproject.toml), so a raw ``socket.timeout()``
    instance must hit the TimeoutError mapping just like a direct
    ``TimeoutError()`` would."""
    exc = socket.timeout()  # equivalent to TimeoutError() on 3.10+
    out = translate_backup_error(exc, host="10.0.0.5")
    assert "Connection timed out" in out


def test_step_argument_accepted_for_forward_compat():
    """The ``step`` argument is reserved for future per-phase routing
    (connect / collect / save).  Calling with explicit step values
    must not change behaviour today — the test pins the no-op contract
    so the planned follow-up that splits the try/except into per-phase
    blocks can land without breaking existing call sites."""
    exc = TimeoutError("timed out")
    a = translate_backup_error(exc, host="10.0.0.5", step="collect")
    b = translate_backup_error(exc, host="10.0.0.5", step="save")
    c = translate_backup_error(exc, host="10.0.0.5", step="connect")
    assert a == b == c
