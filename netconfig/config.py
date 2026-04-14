"""
Application configuration.

All fields can be overridden by environment variables with the ``NETCONFIG_``
prefix, e.g.::

    NETCONFIG_PORT=9000 uvicorn netconfig.main:app

Pydantic-settings automatically reads ``.env`` files if present.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    """

    definitions_dir: Path = Path("definitions")
    configs_dir: Path = Path("configs")
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    model_config = SettingsConfigDict(
        env_prefix="NETCONFIG_",
        env_file=".env",
        env_file_encoding="utf-8",
    )
