"""
Centralised logging configuration for NetConfig.

Call ``configure_logging()`` once at application startup (before any other
module is imported) to set up handlers, formatters, and third-party
suppression.  The function is **idempotent**: if the root logger already has
handlers (e.g. because uvicorn or a test harness configured logging first),
it returns immediately so duplicate handlers are never added.

Usage (web, from a custom ``__main__.py`` or startup script)::

    from netconfig.logging_config import configure_logging
    configure_logging(level="INFO")

Usage (desktop)::

    from netconfig.logging_config import configure_logging
    from pathlib import Path
    configure_logging(level="INFO", log_file=Path("/path/to/netconfig.log"))

When running under the ``uvicorn`` CLI the CLI configures logging itself via
``dictConfig``; in that case the root logger will already have handlers and
this function is a no-op — the uvicorn log format is used as-is.

Log format::

    2026-04-14 12:34:56 INFO     netconfig.api.routes.backups       Created backup job …
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)-40s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Third-party loggers suppressed to WARNING regardless of the root level.
# These produce excessive output at INFO/DEBUG that obscures application logs.
_SUPPRESS_TO_WARNING = (
    "paramiko",       # SSH key-exchange and transport internals
    "uvicorn.access", # Per-request HTTP access log (too chatty for desktop)
    "multipart",      # HTTP multipart parsing internals
    "asyncio",        # Event-loop debug noise at DEBUG level
)


def configure_logging(
    level: str = "INFO",
    log_file: Path | None = None,
) -> None:
    """Configure the root logger for production use.

    Sets up a ``StreamHandler`` (stderr) and an optional
    ``RotatingFileHandler``.  Both use the same structured format with
    timestamps, level, logger name, and message.

    Args:
        level: Root log level — ``"DEBUG"``, ``"INFO"``, ``"WARNING"``,
            ``"ERROR"``, or ``"CRITICAL"`` (case-insensitive).
            Defaults to ``"INFO"``.
        log_file: If provided, a rotating file handler is added that writes
            to this path.  The parent directory is created if it does not
            exist.  Files rotate at 5 MB; up to 3 backups are kept.
    """
    root = logging.getLogger()

    # Guard against duplicate configuration.  We skip only when the root
    # logger already has handlers from *real* user or framework code
    # (uvicorn CLI, a prior call to this function, etc.).  pytest installs
    # its own ``_pytest.logging.LogCaptureHandler`` instances on the root
    # logger during test runs; those come from the ``_pytest`` package and
    # must not block our setup — otherwise tests cannot observe what this
    # function does.
    if any(
        not type(h).__module__.startswith("_pytest")
        for h in root.handlers
    ):
        return

    root.setLevel(level.upper())
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # ── Console handler (stderr) ─────────────────────────────────────────
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # ── Rotating file handler (desktop / server deployments) ─────────────
    if log_file is not None:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB per file
            backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)

    # ── Suppress noisy third-party loggers ───────────────────────────────
    for name in _SUPPRESS_TO_WARNING:
        logging.getLogger(name).setLevel(logging.WARNING)
