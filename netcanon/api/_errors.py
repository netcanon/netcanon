"""
Operator-facing error translation for the backup-execute surface.

When a backup-collect or save fails, the per-device error string ends
up in :attr:`netcanon.models.backup.BackupResult.error` and is rendered
verbatim in the operator UI (Jobs page → per-device row).  Pre-Round-3
every exception funneled through ``str(exc)`` in the broad except at
``netcanon/api/routes/backups.py:355``, producing widely varying
quality:

* **GOOD** — already operator-readable: ``ValueError`` raised in-house
  with a concrete cap (``Config content exceeds max size (X bytes >
  52,428,800 bytes)``) or a named field
  (``netmiko_device_type is not set for definition 'Cisco'``).
* **OPAQUE** — ``socket.timeout``'s empty ``str``,
  ``socket.gaierror``'s bare ``[Errno -2] Name or service not known``.
* **LEAKY** — ``NetmikoAuthenticationException``'s multi-line "see also"
  troubleshooting block (10+ lines for a single-line toast); ``OSError``
  on save exposing the server's internal filesystem paths.

This module collapses that surface into a single short operator-readable
line per exception type, **host-prefixed** so operators running backups
against many devices in parallel can identify which one failed.

Scope is intentionally narrow:

* **Only** the backup-collect / save surface.  Migration's
  parse/render errors are already prefixed by
  :mod:`netcanon.services.migration_pipeline` (``parse failed:`` /
  ``render failed:``) and don't need translation here.  The
  ``POST /api/v1/configs/{filename}/open`` endpoint has its own
  per-error-type formatting (Phase 3, Round 1).
* The full exception still goes to the server log via the existing
  ``logger.error(..., exc_info=True)`` at the caller site — this
  module only shapes operator-visible **text**, never the diagnostic
  trail.

The mapping table is checked in :func:`isinstance` order; ordering
matters because subclass relationships matter
(``NetmikoAuthenticationException`` before the generic ``OSError``
catch; ``ConnectionRefusedError`` before generic ``OSError`` since
the former is an ``OSError`` subclass).

Design rationale: a helper function — not a FastAPI exception handler
— because the failing code runs inside a ``BackgroundTasks`` worker
thread (see :func:`netcanon.api.routes.backups._run_backup_job` via
:class:`ThreadPoolExecutor`), not in an HTTP request lifecycle.
FastAPI's ``@app.exception_handler`` only fires on the request stack;
it cannot intercept exceptions inside a background worker that writes
to ``BackupResult.error``.  A function call from the broad-except is
the only shape that reaches the right code path.
"""

from __future__ import annotations

import socket
from typing import Callable

import paramiko
import paramiko.ssh_exception
from netmiko import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)


__all__ = ["translate_backup_error"]


# ---------------------------------------------------------------------------
# Per-type formatters
# ---------------------------------------------------------------------------
#
# Signature: ``(exc, host) -> str``.  Each formatter returns the
# operator-visible message body without the host prefix; the top-level
# :func:`translate_backup_error` applies the ``[host]`` tag.
#
# Formatters intentionally do NOT echo ``str(exc)`` unless the
# underlying message is known to be operator-readable.  Where we DO
# include underlying text (e.g. ``paramiko.SSHException``), we trim
# to the first line to keep toasts single-line and to suppress
# multi-line tracebacks that some upstreams embed in their messages.


def _first_line(s: str) -> str:
    """Return the first non-empty line of *s*, stripped.

    Netmiko's exception messages often span 10+ lines with "see also"
    troubleshooting blocks; keeping only the headline produces a
    toast-friendly single line.  Returns ``""`` for empty / whitespace
    input rather than ``IndexError``.
    """
    for line in (s or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _humanize_paramiko_auth(exc: BaseException, host: str) -> str:
    return (
        "SSH authentication failed — check the username/password on the "
        "device profile."
    )


def _humanize_paramiko_ssh(exc: BaseException, host: str) -> str:
    underlying = _first_line(str(exc))
    if not underlying:
        return (
            "SSH protocol error — the device closed the connection or "
            "refused the SSH banner; no further detail was provided."
        )
    return (
        f"SSH protocol error: {underlying} — the device may have "
        f"closed the connection or refused the SSH banner."
    )


def _humanize_socket_timeout(exc: BaseException, host: str) -> str:
    return (
        "Connection timed out — host unreachable, SSH port blocked, or "
        "the device is overloaded."
    )


def _humanize_socket_gaierror(exc: BaseException, host: str) -> str:
    return (
        "DNS lookup failed — verify the hostname spelling, or use an IP "
        "address directly."
    )


def _humanize_connection_refused(exc: BaseException, host: str) -> str:
    return (
        "Connection refused — SSH is not running on the target port, or "
        "the port is wrong (default is 22)."
    )


def _humanize_connection_lost(exc: BaseException, host: str) -> str:
    # BrokenPipeError, ConnectionResetError, ConnectionAbortedError.
    return (
        "Connection lost mid-session — the device may have rebooted, "
        "rate-limited the session, or terminated the SSH connection."
    )


def _humanize_netmiko_auth(exc: BaseException, host: str) -> str:
    return (
        "SSH authentication failed — check the username/password on the "
        "device profile.  Some vendors also require an enable password."
    )


def _netmiko_underlying_cause(exc: BaseException) -> BaseException | None:
    """Walk the exception chain to recover what Netmiko actually wrapped.

    Netmiko's ``establish_connection`` catches
    :class:`paramiko.ssh_exception.NoValidConnectionsError`, ``socket.gaierror``,
    ``socket.timeout`` / :class:`TimeoutError`, and a handful of other
    network-layer exceptions, then re-raises a single
    :class:`netmiko.NetmikoTimeoutException` with a generic
    "TCP connection to device failed.  Common causes are: 1. Incorrect
    hostname or IP address. 2. Wrong TCP port. ..." message.  That
    message is useful for shell users debugging a connection one-off,
    but useless to an operator reading a failure toast for one device
    out of ten in a batch backup — three radically different failure
    modes (DNS, refused, unreachable) all read identically.

    Python preserves the original exception via the implicit
    :attr:`BaseException.__context__` attribute set automatically when
    you ``raise NewError(...)`` inside an ``except`` block (vs. the
    explicit ``__cause__`` set by ``raise NewError(...) from
    other_exc``).  Walk both, prefer ``__cause__`` if explicitly set,
    then fall back to ``__context__``; this works whether the wrapping
    library uses ``from`` chaining or not.

    Returns the deepest non-Netmiko underlying exception (or ``None``
    if the chain is empty).  Translators inspect the type and route
    to the per-cause formatter.
    """
    cause = exc.__cause__ if exc.__cause__ is not None else exc.__context__
    # Walk one level deep — Netmiko's wrapping is shallow (always
    # exactly one re-raise).  Don't recurse arbitrarily; that risks
    # picking up unrelated context from outer try/except blocks.
    return cause


def _humanize_netmiko_timeout(exc: BaseException, host: str) -> str:
    # Netmiko's generic "TCP connection to device failed" branch is the
    # main caller of this formatter.  Recover the underlying exception
    # via __context__ and dispatch to the per-cause formatter — that
    # gives operators the actionable DNS / refused / unreachable
    # distinction instead of three identical timeout strings.
    cause = _netmiko_underlying_cause(exc)
    if isinstance(cause, socket.gaierror):
        return _humanize_socket_gaierror(cause, host)
    if isinstance(cause, paramiko.ssh_exception.NoValidConnectionsError):
        # paramiko raises NoValidConnectionsError when every address
        # for the host either refused the connection or wasn't
        # listening — operator action is the same as a plain
        # ConnectionRefusedError.
        return _humanize_connection_refused(cause, host)
    if isinstance(cause, ConnectionRefusedError):
        return _humanize_connection_refused(cause, host)
    if isinstance(cause, TimeoutError):
        # Real connect-timeout — host accepted the SYN but didn't
        # complete the handshake within paramiko's timeout window.
        return _humanize_socket_timeout(cause, host)
    # No useful chain (or chain has a type we don't specifically
    # handle — e.g. an actual Netmiko-only read timeout after a
    # successful connect).  Fall back to the generic message that
    # also covers read-side timeouts.
    return (
        "Connection or command-read timed out — the device is slow to "
        "respond, the link is degraded, or the configured read timeout "
        "is too short for this device."
    )


def _humanize_storage_error(exc: BaseException, host: str) -> str:
    # OSError + PermissionError + IsADirectoryError + FileNotFoundError.
    # The collector layer reaches this branch via file_store.save's
    # tmp.write_text/tmp.replace.  Deliberately suppresses the server
    # filesystem path — it's worthless to the operator and reveals
    # server layout.  The full path is in the server log via exc_info.
    return (
        "Storage error while writing the captured config — check disk "
        "space and write permissions on the server's configs directory."
    )


def _humanize_unicode_error(exc: BaseException, host: str) -> str:
    return (
        "Device output was not valid UTF-8 — possible terminal-encoding "
        "mismatch.  Check the device's session encoding or try the "
        "alternate collector strategy."
    )


def _humanize_value_error(exc: BaseException, host: str) -> str:
    # In-house ValueErrors (file_store 50MB cap, missing
    # netmiko_device_type, etc.) are already operator-readable by
    # design — pass through unchanged.
    return _first_line(str(exc)) or "Invalid configuration encountered."


def _humanize_internal_error(exc: BaseException, host: str) -> str:
    # KeyError / AttributeError surfacing through the collect path
    # are bugs in our own code, not operator misconfigurations.
    # Don't fabricate an actionable message; the server log carries
    # the stack trace, which is what a maintainer needs to diagnose.
    return (
        f"Internal error ({type(exc).__name__}) — please report; the "
        f"full traceback is in the server log."
    )


def _humanize_fallback(exc: BaseException, host: str) -> str:
    return (
        f"Backup failed: {type(exc).__name__} — see the server log for "
        f"details."
    )


# ---------------------------------------------------------------------------
# Type → formatter dispatch table
# ---------------------------------------------------------------------------
#
# Ordering matters: each entry is checked via :func:`isinstance` in
# order, so subclasses MUST come before their bases.  In particular:
#
#   * NetmikoAuthenticationException / NetmikoTimeoutException are
#     subclasses of Exception (not OSError), but listed early so they
#     win before any future re-parenting of the Netmiko hierarchy.
#   * ConnectionRefusedError / ConnectionResetError / BrokenPipeError
#     are OSError subclasses — they must precede the generic OSError
#     storage-error mapping below.
#   * ``socket.timeout`` is aliased to ``TimeoutError`` on Python ≥3.10
#     (and we require ≥3.11 per pyproject.toml), so listing TimeoutError
#     alone covers both.

_TRANSLATIONS: list[tuple[type, Callable[[BaseException, str], str]]] = [
    # Authentication failures — most actionable, check first.
    (paramiko.AuthenticationException, _humanize_paramiko_auth),
    (NetmikoAuthenticationException, _humanize_netmiko_auth),
    # Netmiko timeout (multi-line "see also" suppressor) before
    # generic TimeoutError so the Netmiko-specific message wins.
    (NetmikoTimeoutException, _humanize_netmiko_timeout),
    # Paramiko SSH errors that aren't auth — banner, no-kex, etc.
    (paramiko.SSHException, _humanize_paramiko_ssh),
    # Network-layer reachability before generic OSError.
    (socket.gaierror, _humanize_socket_gaierror),
    # paramiko.NoValidConnectionsError is what paramiko raises when
    # every address for the host either refused the connection or
    # wasn't listening — surface as "connection refused" to operators
    # (same actionable response as a plain ConnectionRefusedError).
    # Listed BEFORE ConnectionRefusedError because NoValidConnectionsError
    # is a SSHException subclass, not a ConnectionRefusedError subclass.
    (paramiko.ssh_exception.NoValidConnectionsError,
     _humanize_connection_refused),
    (ConnectionRefusedError, _humanize_connection_refused),
    (ConnectionError, _humanize_connection_lost),  # BrokenPipe, Reset, Aborted
    (TimeoutError, _humanize_socket_timeout),  # also covers socket.timeout
    # Encoding mismatch (rare; OPNsense console quirk).
    (UnicodeError, _humanize_unicode_error),
    # In-house ValueErrors (already operator-readable).
    (ValueError, _humanize_value_error),
    # Generic OSError after all subclasses above — last storage net.
    (OSError, _humanize_storage_error),
    # Our-bug catchalls.
    (KeyError, _humanize_internal_error),
    (AttributeError, _humanize_internal_error),
]


def translate_backup_error(
    exc: BaseException, *, host: str, step: str = "collect"
) -> str:
    """Translate a backup-execute exception into a short operator line.

    Returns a host-prefixed, single-line operator-readable string
    suitable for :attr:`netcanon.models.backup.BackupResult.error` and
    rendering in a UI table cell.  The caller is responsible for the
    ``[:500]`` truncation that preserves the existing wire contract
    on ``BackupResult.error`` (this function never returns a string
    longer than ~400 chars, but the truncation is part of the
    historical contract).

    Args:
        exc: The exception that escaped the collect / save sequence.
        host: The device's host string (IP or hostname).  Prefixed on
            the returned message so operators with multiple in-flight
            devices can identify which one failed without scanning
            the line for hostnames.
        step: Operational phase (``"collect"`` or ``"save"``) — carried
            in the function signature for future per-phase routing
            (a planned follow-up that adds separate try/excepts for
            connect / collect / save).  Not currently used for
            branching; included here so callers can be written against
            the final signature without churn.

    Returns:
        A single-line operator-readable message in the form
        ``"[<host>] <translation>"``.  Always non-empty; the fallback
        branch handles unknown exception types.

    Example:
        >>> import socket
        >>> translate_backup_error(socket.gaierror(-2, "not found"), host="bad.example.com")
        '[bad.example.com] DNS lookup failed — verify the hostname spelling, or use an IP address directly.'
    """
    for exc_type, formatter in _TRANSLATIONS:
        if isinstance(exc, exc_type):
            return f"[{host}] {formatter(exc, host)}"
    return f"[{host}] {_humanize_fallback(exc, host)}"
