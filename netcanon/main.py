"""
Application factory.

The ``create_app`` factory is the primary entry point for both production
and testing.  Pass a custom ``Settings`` instance to inject test-specific
directories and overrides without touching environment variables::

    from netcanon.main import create_app
    from netcanon.config import Settings

    app = create_app(Settings(configs_dir=tmp_path / "configs"))

The module-level ``app`` object is the production instance used by
Uvicorn::

    uvicorn netcanon.main:app --reload

UI routes (all ``GET /<page>`` HTML endpoints) live in
``netcanon.api.routes.ui`` — this module only wires routers and
configures the lifespan.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request

from .api.routes import backups as backups_router
from .api.routes import configs as configs_router
from .api.routes import definitions as defs_router
from .api.routes import device_profiles as device_profiles_router
from .api.routes import migration as migration_router
from .api.routes import schedules as schedules_router
from .api.routes import ui as ui_router
# Side-effect import — registers all built-in migration adapters.
from . import migration as _migration_pkg  # noqa: F401
from .config import Settings
from .definitions.loader import DefinitionLoader
from .storage.device_profile_store import FileDeviceProfileStore
from .storage.file_store import FileConfigStore
from .storage.job_store import FileJobStore
from .storage.schedule_store import FileScheduleStore

# Configure application-level logging once, at module import time.  The
# ``configure_logging`` helper (netcanon/logging_config.py) is idempotent
# and a no-op under uvicorn's own log config / under pytest's harness, so
# calling it here gives ``logger.info(...)`` output everywhere except
# environments that have already installed a root-logger config.  This
# replaces the prior state where our app-level INFO logs (most visibly
# the migration pipeline's "Migration plan X: src -> tgt = status" line)
# were silently dropped by the default WARNING threshold.
from .logging_config import configure_logging
configure_logging(level="INFO")


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a Netcanon FastAPI application instance.

    Calling this multiple times produces independent application instances,
    each with its own state (definitions, storage, job registry, scheduler).
    This is essential for test isolation — each test fixture calls
    ``create_app(test_settings)`` to get a fresh, isolated instance.

    Args:
        settings: Optional ``Settings`` instance.  When ``None``, settings
            are loaded from environment variables and ``.env`` files.

    Returns:
        A fully configured ``FastAPI`` application ready for ``uvicorn``
        or ``TestClient``.
    """
    if settings is None:
        settings = Settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Initialise shared state on startup; clean up on shutdown."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from .api.routes.schedules import register_schedule_job

        logger.info(
            "Loading device definitions from %s", settings.definitions_dir
        )
        _app.state.settings = settings
        # Keep the loader around so backup routes can call
        # :meth:`DefinitionLoader.resolve` for version/model-pinned
        # overlay lookup.  The dict-shaped ``definitions`` is kept
        # alongside for backwards compatibility with endpoints that
        # iterate type_keys (schedules page, definitions list).
        _definition_loader = DefinitionLoader(settings.definitions_dir)
        _app.state.definitions = _definition_loader.load_all()
        _app.state.definition_loader = _definition_loader
        _app.state.storage = FileConfigStore(settings.configs_dir)

        # Load vendor declarations from YAML files.
        from .migration.vendors import load_vendors
        _app.state.vendors = load_vendors()

        # Load target-device profiles (Tier 3 port-rename UI data).
        # Profiles are optional — the UI falls back to free-form target
        # naming when none are defined.
        from .migration.target_profiles import load_profiles_dir
        _app.state.target_profiles = load_profiles_dir(
            settings.definitions_dir / "target_profiles"
        )

        # Verify storage directories are writable before proceeding.
        # ``effective_data_dir`` honours an explicit Settings.data_dir
        # override (used by desktop preferences) and otherwise falls back
        # to the historical ``configs_dir.parent`` derivation.
        data_root = settings.effective_data_dir
        for check_dir in [settings.configs_dir, data_root]:
            try:
                check_dir.mkdir(parents=True, exist_ok=True)
                probe = check_dir / ".write_test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
            except OSError as exc:
                logger.warning(
                    "Storage directory %s may not be writable: %s", check_dir, exc
                )

        # Job persistence — sibling directory to configs_dir
        _app.state.job_store = FileJobStore(data_root / "jobs")
        _app.state.jobs = _app.state.job_store.load_all()

        # Schedule persistence
        _app.state.schedule_store = FileScheduleStore(data_root / "schedules")
        _app.state.schedules = _app.state.schedule_store.load_all()

        # Device profile persistence
        _app.state.device_profile_store = FileDeviceProfileStore(data_root / "devices")
        _app.state.device_profiles = _app.state.device_profile_store.load_all()

        # APScheduler — purely in-memory; schedules are persisted separately
        scheduler = AsyncIOScheduler(
            timezone="UTC",
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 300,
            },
        )
        _app.state.scheduler = scheduler

        # Log APScheduler errors so a single job failure doesn't go unnoticed.
        from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED

        def _on_job_event(event):
            if hasattr(event, "exception") and event.exception:
                logger.error(
                    "Scheduled job %s failed: %s",
                    event.job_id,
                    event.exception,
                    exc_info=event.traceback is not None,
                )
            else:
                logger.warning("Scheduled job %s missed its fire time", event.job_id)

        scheduler.add_listener(_on_job_event, EVENT_JOB_ERROR | EVENT_JOB_MISSED)

        # Re-register all enabled schedules
        for schedule in _app.state.schedules.values():
            if schedule.enabled:
                try:
                    register_schedule_job(scheduler, schedule, _app)
                    ap_job = scheduler.get_job(schedule.id)
                    if ap_job and ap_job.next_run_time:
                        schedule.next_run_at = ap_job.next_run_time
                        _app.state.schedule_store.save(schedule)
                except Exception as exc:
                    logger.error(
                        "Failed to register schedule '%s': %s",
                        schedule.name, exc,
                    )

        scheduler.start()
        logger.info(
            "Netcanon started — %d definition(s) loaded, %d schedule(s) active",
            len(_app.state.definitions),
            len([s for s in _app.state.schedules.values() if s.enabled]),
        )

        yield

        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    app = FastAPI(
        title="Netcanon",
        description=(
            "Multi-vendor network configuration backup and translation engine. "
            "See /docs for the interactive API reference."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,                      # we serve a nav-wrapped version at /docs
        redoc_url=None,                     # not surfaced in the UI
        openapi_url="/api/v1/openapi.json", # non-default path
    )

    # ------------------------------------------------------------------
    # Request-ID middleware (Phase 9 logging audit)
    # ------------------------------------------------------------------
    # Sets a contextvar that flows through to every log record via the
    # RequestIdFilter installed by configure_logging().  Inbound
    # X-Request-ID is honoured when present (lets upstream proxies /
    # clients supply their own correlation id); otherwise we generate
    # a short UUID prefix.  The id is echoed on the response header
    # so clients can reference the same id in bug reports.
    #
    # Middlewares are applied in *reverse* registration order per
    # Starlette semantics — this one is registered BEFORE the
    # security-headers middleware below so it wraps the outermost
    # response, guaranteeing the contextvar is set before any
    # downstream code (including other middleware + route handlers)
    # writes a log line.
    import uuid

    from .logging_config import REQUEST_ID_CTX

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        # Honour an upstream-supplied id when it's short + printable;
        # otherwise ignore (defence against header-injected garbage
        # bloating log lines).  Accept 8-36 chars of ASCII alnum +
        # hyphen + underscore — covers short UUID prefixes, full
        # UUIDs, and typical trace-id formats.
        inbound = request.headers.get("x-request-id", "")
        if 8 <= len(inbound) <= 36 and all(
            c.isalnum() or c in "-_" for c in inbound
        ):
            req_id = inbound
        else:
            req_id = uuid.uuid4().hex[:8]
        token = REQUEST_ID_CTX.set(req_id)
        try:
            response = await call_next(request)
        finally:
            REQUEST_ID_CTX.reset(token)
        # Always echo the id on the response so log-stitching works
        # from the client side (bug reports can cite "X-Request-ID").
        response.headers["X-Request-ID"] = req_id
        return response

    # ------------------------------------------------------------------
    # Security headers middleware
    # ------------------------------------------------------------------
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    app.include_router(defs_router.router, prefix="/api/v1")
    app.include_router(configs_router.router, prefix="/api/v1")
    app.include_router(backups_router.router, prefix="/api/v1")
    app.include_router(schedules_router.router, prefix="/api/v1")
    app.include_router(device_profiles_router.router, prefix="/api/v1")
    app.include_router(migration_router.router, prefix="/api/v1")
    app.include_router(ui_router.router)  # UI routes at root (/, /jobs, …)

    return app


# Production application instance — used by ``uvicorn netcanon.main:app``
try:
    app = create_app()
except Exception as _exc:
    import sys

    print(f"Netcanon failed to start: {_exc}", file=sys.stderr)
    raise SystemExit(1) from _exc
