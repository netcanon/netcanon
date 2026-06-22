"""
Application configuration.

All fields can be overridden by environment variables with the ``NETCANON_``
prefix, e.g.::

    NETCANON_PORT=9000 uvicorn netcanon.main:app

Pydantic-settings automatically reads ``.env`` files if present.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Hard ceiling on per-job parallel device workers.  Chosen conservatively
#: to protect the SSH target devices (most vendors cap concurrent sessions
#: between 5 and 16) and to bound thread count on the backup server.
MAX_BACKUP_CONCURRENCY: int = 10


class Settings(BaseSettings):
    """Runtime configuration for the Netcanon application.

    Attributes:
        definitions_dir: Directory tree containing ``*.yaml`` device definition
            files.  Defaults to ``definitions/`` relative to the working
            directory so the shared definition library is used out of the box.
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
            caching entirely (every read hits disk).
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

            * ``"auto_add"`` (default): trust-on-first-use *without*
              persistence — any host key is accepted, every time.  This is
              the historical behaviour; no change for existing deployments.
            * ``"tofu"``: trust-on-first-use *with* persistence — the first
              key seen for a host is recorded under
              ``{effective_data_dir}/known_hosts`` and a later **changed**
              key is rejected (paramiko ``BadHostKeyException``), catching
              MITM / re-key.  Re-trust a legitimately re-keyed device by
              removing its line from that file.
            * ``"reject"``: only connect to hosts already present in the
              ``known_hosts`` store; unknown hosts are refused.

            Override via ``NETCANON_SSH_HOST_KEY_CHECKING``.  The Netmiko
            collector honours ``tofu`` / ``reject`` as strict checking
            against the *OS* ``~/.ssh/known_hosts`` (it has no custom-store
            / TOFU-persist API); the Paramiko shell collector uses the
            netcanon data-dir store described above.  See SECURITY.md.
    """

    definitions_dir: Path = Path("definitions")
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
    ssh_host_key_checking: Literal["auto_add", "tofu", "reject"] = "auto_add"
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
