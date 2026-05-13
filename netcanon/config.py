"""
Application configuration.

All fields can be overridden by environment variables with the ``NETCANON_``
prefix, e.g.::

    NETCANON_PORT=9000 uvicorn netcanon.main:app

Pydantic-settings automatically reads ``.env`` files if present.
"""

from pathlib import Path

from pydantic import Field
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
        host: Bind address for the Uvicorn server.
        port: TCP port for the Uvicorn server.
        log_level: Logging verbosity passed to Uvicorn and the standard-library
            ``logging`` module.  One of ``debug``, ``info``, ``warning``,
            ``error``, ``critical``.
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
    """

    definitions_dir: Path = Path("definitions")
    configs_dir: Path = Path("configs")
    data_dir: Path | None = None
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    open_in_editor: bool = False
    backup_concurrency: int = Field(default=MAX_BACKUP_CONCURRENCY,
                                    ge=1, le=MAX_BACKUP_CONCURRENCY)
    max_memory_jobs: int = Field(default=1000, ge=0)

    model_config = SettingsConfigDict(
        env_prefix="NETCANON_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

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
