"""
Application configuration.

All fields can be overridden by environment variables with the ``NETCONFIG_``
prefix, e.g.::

    NETCONFIG_PORT=9000 uvicorn netconfig.main:app

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
    """Runtime configuration for the NetConfig application.

    Attributes:
        definitions_dir: Directory tree containing ``*.yaml`` device definition
            files.  Defaults to ``definitions/`` relative to the working
            directory so the shared definition library is used out of the box.
        configs_dir: Directory where captured configuration files are stored.
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
            ``netconfig_desktop/settings.py``; can also be enabled for a
            local web deployment via the ``NETCONFIG_OPEN_IN_EDITOR=true``
            environment variable.
        backup_concurrency: Maximum number of devices a single backup job
            processes in parallel.  Devices beyond this limit wait in a
            FIFO queue and start as earlier slots free up.  Capped at
            ``MAX_BACKUP_CONCURRENCY`` (10) to protect the SSH target
            devices and bound thread count on the backup server.
    """

    definitions_dir: Path = Path("definitions")
    configs_dir: Path = Path("configs")
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    open_in_editor: bool = False
    backup_concurrency: int = Field(default=MAX_BACKUP_CONCURRENCY,
                                    ge=1, le=MAX_BACKUP_CONCURRENCY)

    model_config = SettingsConfigDict(
        env_prefix="NETCONFIG_",
        env_file=".env",
        env_file_encoding="utf-8",
    )
