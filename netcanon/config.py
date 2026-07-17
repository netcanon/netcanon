"""
Application configuration.

All fields can be overridden by environment variables with the ``NETCANON_``
prefix, e.g.::

    NETCANON_PORT=9000 uvicorn netcanon.main:app

Pydantic-settings automatically reads ``.env`` files if present.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Hard ceiling on per-job parallel device workers.  Chosen conservatively
#: to protect the SSH target devices (most vendors cap concurrent sessions
#: between 5 and 16) and to bound thread count on the backup server.
MAX_BACKUP_CONCURRENCY: int = 10


def _resolve_global_backup_ceiling() -> int:
    """Read the process-wide backup-collection ceiling from the environment.

    Module-level (not a :class:`Settings` field) because the limiter it
    sizes is a single *process-wide* object created once, independent of any
    per-job ``Settings`` snapshot.  Reads ``NETCANON_MAX_GLOBAL_BACKUP_CONCURRENCY``,
    falling back to :data:`MAX_BACKUP_CONCURRENCY` when unset or unparseable;
    floored at 1.
    """
    raw = os.environ.get("NETCANON_MAX_GLOBAL_BACKUP_CONCURRENCY")
    if raw is None:
        return MAX_BACKUP_CONCURRENCY
    try:
        return max(1, int(raw))
    except ValueError:
        warnings.warn(
            f"NETCANON_MAX_GLOBAL_BACKUP_CONCURRENCY={raw!r} is not an "
            f"integer; falling back to {MAX_BACKUP_CONCURRENCY}",
            stacklevel=2,
        )
        return MAX_BACKUP_CONCURRENCY


#: Process-wide ceiling on the number of device collections in flight at
#: once, summed across *all* concurrently-running backup jobs.  The per-job
#: :data:`MAX_BACKUP_CONCURRENCY` cap only bounds a single job; nothing
#: bounded the sum, so N simultaneous jobs (several schedules firing
#: together, or a schedule firing during a manual run) could open N×cap
#: SSH/NETCONF sessions and exhaust threads / file descriptors on the backup
#: host (blind-audit 3ec11f3 r7).  A module-level ``BoundedSemaphore`` in
#: :mod:`netcanon.services.backup_runner` enforces this ceiling: a worker
#: that can't get a permit blocks (back-pressure) until one frees — never a
#: failure, the device just stays ``queued`` until its turn.
#:
#: Defaults to :data:`MAX_BACKUP_CONCURRENCY` so a *single* job's behaviour
#: is unchanged (it can still fill every worker slot) while the multi-job
#: blow-up is capped.  Raise it for large deployments with capacity to spare
#: via ``NETCANON_MAX_GLOBAL_BACKUP_CONCURRENCY``.
MAX_GLOBAL_BACKUP_CONCURRENCY: int = _resolve_global_backup_ceiling()


#: Default ceiling on the number of *backup jobs* dispatched concurrently.
#: Distinct from the two device-level caps above: those bound how many
#: *devices* a job (or the whole process) collects at once; this bounds how
#: many whole jobs run in parallel on the dedicated backup executor.  A job
#: submitted while the executor is saturated waits in its FIFO queue (stays
#: ``pending`` until a slot frees — back-pressure, never a failure).
#:
#: The executor exists to keep minutes-long backup runs off the shared pools
#: that serve the rest of the app: pre-fix the manual (``POST /backups``)
#: path ran each job on one of anyio's ~40 default worker-thread tokens — so
#: ~40 in-flight jobs starved *every* synchronous route — and the scheduled
#: path shared asyncio's default executor with ``/sanitize`` and the egress
#: filter (2026-07-06 review MEDIUM #27).  8 is a conservative default; raise
#: it (8-16 typical) for large deployments via
#: ``NETCANON_MAX_CONCURRENT_BACKUP_JOBS``.
_DEFAULT_MAX_CONCURRENT_BACKUP_JOBS: int = 8


def _resolve_max_concurrent_backup_jobs() -> int:
    """Read the max-concurrent-*jobs* ceiling from the environment.

    Module-level (not a :class:`Settings` field) because the executor it
    sizes is a single *process-wide* object created once, independent of any
    per-job ``Settings`` snapshot — exactly like
    :func:`_resolve_global_backup_ceiling`.  Reads
    ``NETCANON_MAX_CONCURRENT_BACKUP_JOBS``, falling back to
    :data:`_DEFAULT_MAX_CONCURRENT_BACKUP_JOBS` when unset or unparseable;
    floored at 1 so the executor always has at least one worker.
    """
    raw = os.environ.get("NETCANON_MAX_CONCURRENT_BACKUP_JOBS")
    if raw is None:
        return _DEFAULT_MAX_CONCURRENT_BACKUP_JOBS
    try:
        return max(1, int(raw))
    except ValueError:
        warnings.warn(
            f"NETCANON_MAX_CONCURRENT_BACKUP_JOBS={raw!r} is not an integer; "
            f"falling back to {_DEFAULT_MAX_CONCURRENT_BACKUP_JOBS}",
            stacklevel=2,
        )
        return _DEFAULT_MAX_CONCURRENT_BACKUP_JOBS


#: Resolved at import.  ``netcanon.services.backup_runner`` binds this value
#: via ``from ..config import MAX_CONCURRENT_BACKUP_JOBS`` at ITS import time
#: and reads that module-level binding when it lazily builds its pool — so a
#: test must monkeypatch ``backup_runner.MAX_CONCURRENT_BACKUP_JOBS`` (not
#: ``config.MAX_CONCURRENT_BACKUP_JOBS``, which the runner never re-reads) for
#: a new size to take effect (HEAD-review F9).
MAX_CONCURRENT_BACKUP_JOBS: int = _resolve_max_concurrent_backup_jobs()


#: Intake cap on the number of *in-flight* (pending / running) backup jobs —
#: the ceiling for POST /api/v1/backups (HEAD-review Conc-F4).  The per-job /
#: global limiters above bound device fan-out and concurrent whole jobs, but
#: nothing bounded the NUMBER of jobs a client could enqueue: a runaway retry
#: loop could pile up an unbounded executor queue (each entry pinning decrypted
#: credentials in memory), unbounded non-terminal registry entries, and
#: unbounded ``pending`` JSON files.  Sized generously — comfortably above the
#: 200-schedule cap plus manual headroom, at the registry's own 1000-job
#: memory sizing (~5 MB of BackupJob) — so legitimate bursts never trip it;
#: only a flood is shed with a 429 + Retry-After.  Queueing UNDER the cap is
#: still never a failure (#333/#334).  Override via
#: ``NETCANON_MAX_PENDING_BACKUP_JOBS``.
_DEFAULT_MAX_PENDING_BACKUP_JOBS: int = 1000


def _resolve_max_pending_backup_jobs() -> int:
    """Read the in-flight backup-job intake cap from the environment.

    Reads ``NETCANON_MAX_PENDING_BACKUP_JOBS``, falling back to
    :data:`_DEFAULT_MAX_PENDING_BACKUP_JOBS` when unset or unparseable; floored
    at 1 so at least one job can always be enqueued.
    """
    raw = os.environ.get("NETCANON_MAX_PENDING_BACKUP_JOBS")
    if raw is None:
        return _DEFAULT_MAX_PENDING_BACKUP_JOBS
    try:
        return max(1, int(raw))
    except ValueError:
        warnings.warn(
            f"NETCANON_MAX_PENDING_BACKUP_JOBS={raw!r} is not an integer; "
            f"falling back to {_DEFAULT_MAX_PENDING_BACKUP_JOBS}",
            stacklevel=2,
        )
        return _DEFAULT_MAX_PENDING_BACKUP_JOBS


#: Resolved at import.  The POST /backups route binds this via
#: ``from ...config import MAX_PENDING_BACKUP_JOBS`` at ITS import time, so a
#: test overriding the cap must monkeypatch the ROUTE module's binding
#: (``netcanon.api.routes.backups.MAX_PENDING_BACKUP_JOBS``), not this one
#: (mirrors the MAX_CONCURRENT_BACKUP_JOBS note above).
MAX_PENDING_BACKUP_JOBS: int = _resolve_max_pending_backup_jobs()


#: Default ceiling on a single ``POST /api/v1/sanitize`` upload (16 MiB).
#: Network configs are well under a megabyte even for large chassis, so 16 MiB
#: is generous headroom while still bounding the work an unauthenticated /
#: anonymous caller can force: without a cap the endpoint read the entire body
#: into memory and ran the synchronous parse→redact→render pipeline on it, so a
#: multi-gigabyte upload was an availability footgun (blind-audit 276eaeb #19).
_DEFAULT_MAX_SANITIZE_UPLOAD_BYTES: int = 16 * 1024 * 1024


def _resolve_sanitize_upload_cap() -> int:
    """Read the ``/sanitize`` upload ceiling from the environment.

    Module-level (not a :class:`Settings` field) so the route can read it at
    request time and a test can monkeypatch it cheaply.  Reads
    ``NETCANON_MAX_SANITIZE_UPLOAD_BYTES``, falling back to
    :data:`_DEFAULT_MAX_SANITIZE_UPLOAD_BYTES` when unset or unparseable;
    floored at 1 KiB so an operator can't accidentally set a cap that rejects
    every real config.
    """
    raw = os.environ.get("NETCANON_MAX_SANITIZE_UPLOAD_BYTES")
    if raw is None:
        return _DEFAULT_MAX_SANITIZE_UPLOAD_BYTES
    try:
        return max(1024, int(raw))
    except ValueError:
        warnings.warn(
            f"NETCANON_MAX_SANITIZE_UPLOAD_BYTES={raw!r} is not an integer; "
            f"falling back to {_DEFAULT_MAX_SANITIZE_UPLOAD_BYTES}",
            stacklevel=2,
        )
        return _DEFAULT_MAX_SANITIZE_UPLOAD_BYTES


#: Resolved at import; the route reads ``config.MAX_SANITIZE_UPLOAD_BYTES`` at
#: request time (see :mod:`netcanon.api.routes.sanitize`).
MAX_SANITIZE_UPLOAD_BYTES: int = _resolve_sanitize_upload_cap()


def _default_definitions_dir() -> Path:
    """Resolve the default device-definition library root.

    Returns the library bundled *inside the installed package*
    (:data:`netcanon.definitions.LIBRARY_DIR`, i.e.
    ``netcanon/definitions/library/``) rather than a working-directory-relative
    ``definitions/``.  This is what makes a plain ``pip install netcanon`` +
    ``uvicorn netcanon.main:app`` boot from *any* directory — previously the
    server crashed on startup with ``FileNotFoundError`` because the wheel
    shipped no definition tree and the default pointed at ``./definitions``.

    Operators relocate the library with ``NETCANON_DEFINITIONS_DIR`` (env
    sources still take precedence over this default).  Imported lazily so
    ``netcanon.config`` stays import-light and free of an import cycle with
    the definitions package.
    """
    from .definitions import LIBRARY_DIR

    return LIBRARY_DIR


class Settings(BaseSettings):
    """Runtime configuration for the Netcanon application.

    Attributes:
        definitions_dir: Directory tree containing ``*.yaml`` device definition
            files.  Defaults to the library bundled inside the installed
            package (``netcanon/definitions/library/``, see
            :func:`_default_definitions_dir`) so a plain ``pip install`` works
            from any working directory.  Override with
            ``NETCANON_DEFINITIONS_DIR`` to point at a custom tree.
        configs_dir: Directory where captured configuration files are stored.
        data_dir: Optional explicit override for the *data root* — the parent
            directory under which ``jobs/``, ``schedules/``, and ``devices/``
            stores live.  When ``None`` (the default), ``effective_data_dir``
            falls back to ``configs_dir.parent`` for backward compatibility.
            Setting this explicitly lets the desktop preferences UI relocate
            the per-user data root independently of ``configs_dir``.
        host: Bind address for the Uvicorn server.  Defaults to
            ``127.0.0.1`` (loopback) so the zero-config posture is never
            network-exposed by accident; binding all interfaces is an
            explicit opt-in via ``NETCANON_HOST=0.0.0.0`` (which the Docker
            image sets) or ``uvicorn … --host 0.0.0.0``.  ``netcanon serve``
            then gates a non-loopback bind behind ``NETCANON_API_KEY`` or
            ``NETCANON_ALLOW_INSECURE_BIND`` (see netcanon/api/auth.py).
        port: TCP port for the Uvicorn server.
        log_level: Logging verbosity.  Sets the stdlib root logger level via
            ``configure_logging`` (so application logs honour it on every
            entry point, incl. the bare-uvicorn Docker path) and is passed
            to Uvicorn on the desktop server path.  One of ``debug``,
            ``info``, ``warning``, ``error``, ``critical``.
        open_in_editor: Enable the ``POST /api/v1/configs/{filename}/open``
            endpoint that opens a config file in the OS default text editor
            via ``os.startfile()``.  Disabled by default because it only
            makes sense when the server process runs on the same machine as
            the user (i.e. the desktop application).  Set to ``True`` in
            ``netcanon_desktop/settings.py``; can also be enabled for a
            local web deployment via the ``NETCANON_OPEN_IN_EDITOR=true``
            environment variable.
        backup_concurrency: Maximum number of devices a single backup job
            processes in parallel.  Devices beyond this limit wait in a
            FIFO queue and start as earlier slots free up.  Capped at
            ``MAX_BACKUP_CONCURRENCY`` (10) to protect the SSH target
            devices and bound thread count on the backup server.
        max_memory_jobs: Cap on the number of ``BackupJob`` objects held
            in memory.  Disk (``jobs/{id}.json`` via ``FileJobStore``) is
            the source of truth — every job is persisted there regardless
            of this setting.  Jobs evicted from memory remain accessible
            by ID via the registry's transparent disk lazy-load.  Default
            1000 caps memory at ~5 MB.  Set to 0 to disable in-memory
            caching entirely: get-by-id still works (it hits disk), but the
            ``GET /backups`` LIST endpoint reflects only the cache and so
            returns empty at 0 (#29) — jobs are still persisted.
        block_private_egress: When ``True``, the backup entry points
            reject targets that resolve to loopback (``127.0.0.0/8``,
            ``::1``) or link-local (``169.254.0.0/16`` — which includes the
            cloud metadata endpoint ``169.254.169.254`` — and ``fe80::/10``)
            addresses.  Defaults to ``False`` so the desktop / trusted
            management-VLAN deployments see no behaviour change; turn it on
            (``NETCANON_BLOCK_PRIVATE_EGRESS=true``) for a network-exposed
            web deployment to blunt the SSRF surface noted in SECURITY.md.
            RFC-1918 ranges stay allowed — that is where real managed
            devices live.
        ssh_host_key_checking: SSH host-key verification policy for the
            backup collectors.  One of:

            * ``"tofu"`` (default since v0.4.5): trust-on-first-use *with*
              persistence — the first key seen for a host is recorded under
              ``{effective_data_dir}/known_hosts`` and a later **changed**
              key is rejected (paramiko ``BadHostKeyException``), catching
              MITM / re-key.  Re-trust a legitimately re-keyed device by
              removing its line from that file.
            * ``"auto_add"``: trust-on-first-use *without* persistence — any
              host key is accepted, every time (the pre-v0.4.5 behaviour;
              MITM-able).  An explicit opt-OUT of host-key verification; a
              startup warning fires while it is selected.
            * ``"reject"``: only connect to hosts already present in the
              ``known_hosts`` store; unknown hosts are refused.

            Override via ``NETCANON_SSH_HOST_KEY_CHECKING``.  Both collectors
            use the netcanon data-dir ``known_hosts`` store: the Paramiko
            shell collector inline, the Netmiko collector via an auth-less
            paramiko pre-flight (Netmiko has no native TOFU-persist API).
            See SECURITY.md.
    """

    definitions_dir: Path = Field(default_factory=_default_definitions_dir)
    configs_dir: Path = Path("configs")
    data_dir: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: Literal[
        "debug", "info", "warning", "error", "critical"
    ] = "info"
    open_in_editor: bool = False
    backup_concurrency: int = Field(default=MAX_BACKUP_CONCURRENCY,
                                    ge=1, le=MAX_BACKUP_CONCURRENCY)
    max_memory_jobs: int = Field(default=1000, ge=0)
    block_private_egress: bool = False
    ssh_host_key_checking: Literal["auto_add", "tofu", "reject"] = "tofu"
    # ── SEC-01 — opt-in API auth + bind safety ──
    # When set, every /api/v1 route requires `Authorization: Bearer
    # <api_key>`.  Empty (default) disables auth — the zero-config
    # loopback / desktop posture is unchanged.
    api_key: str = ""
    # `netcanon serve` refuses to bind a non-loopback host with no
    # api_key unless this opt-out is set (acknowledging that a reverse
    # proxy terminates auth).  See netcanon/api/auth.py.
    allow_insecure_bind: bool = False

    model_config = SettingsConfigDict(
        env_prefix="NETCANON_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, v: object) -> object:
        """Coerce ``NETCANON_LOG_LEVEL`` case/whitespace; fall back to
        ``info`` for an unknown value.

        ``configure_logging`` runs at import time (``main.py``), outside the
        graceful-startup handler, and passes this value to
        ``logging.setLevel`` (and ``netcanon serve`` to ``uvicorn.run``).  A
        mistyped value (``verbose``, ``warn``, a stray-whitespace
        ``"DEBUG "``, an empty string) would otherwise raise an unhandled
        ``ValueError`` and crash every entry path with a raw traceback
        (v0.4.0 self-audit).  Normalising here guarantees a valid level
        reaches both sinks; an unknown value warns and degrades to ``info``
        rather than failing closed on a non-security setting.
        """
        if not isinstance(v, str):
            return v
        norm = v.strip().lower()
        valid = {"debug", "info", "warning", "error", "critical"}
        if norm in valid:
            return norm
        warnings.warn(
            f"Unknown NETCANON_LOG_LEVEL {v!r}; falling back to 'info' "
            "(valid: debug, info, warning, error, critical).",
            stacklevel=2,
        )
        return "info"

    @property
    def effective_data_dir(self) -> Path:
        """Resolved data-root directory used by job / schedule / device stores.

        When ``data_dir`` is set explicitly (typically via the desktop
        preferences dialog or the ``NETCANON_DATA_DIR`` env var) it is
        returned verbatim.  Otherwise we fall back to the historical
        derivation ``configs_dir.parent`` so existing deployments see no
        behaviour change.
        """
        if self.data_dir is not None:
            return self.data_dir
        return self.configs_dir.parent
