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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from fastapi import Depends, FastAPI, Request

# Side-effect import — registers all built-in migration adapters.
from . import migration as _migration_pkg  # noqa: F401
from .api.auth import require_api_key
from .api.routes import backups as backups_router
from .api.routes import configs as configs_router
from .api.routes import definitions as defs_router
from .api.routes import device_profiles as device_profiles_router
from .api.routes import docs as docs_router
from .api.routes import health as health_router
from .api.routes import migration as migration_router
from .api.routes import sanitize as sanitize_router
from .api.routes import schedules as schedules_router
from .api.routes import ui as ui_router
from .config import Settings
from .definitions.loader import DefinitionLoader

# Configure application-level logging once, at module import time.  The
# level comes from ``Settings().log_level`` (env ``NETCANON_LOG_LEVEL``,
# default ``info``) so the operator's verbosity reaches the stdlib root
# logger on every entry point — including the bare ``uvicorn
# netcanon.main:app`` Docker path, where uvicorn configures only its own
# ``uvicorn.*`` loggers and leaves the root logger to us (so this call is
# NOT a no-op there).  ``configure_logging`` is idempotent and skips only
# when real (non-pytest) root handlers already exist.  Previously the
# level was hardcoded ``INFO`` and NETCANON_LOG_LEVEL was silently ignored
# for application logs (audit finding OBS-01).
from .logging_config import configure_logging
from .storage.device_profile_store import FileDeviceProfileStore
from .storage.file_store import FileConfigStore
from .storage.job_registry import BackupJobRegistry
from .storage.job_store import FileJobStore
from .storage.schedule_store import FileScheduleStore

configure_logging(level=Settings().log_level)


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Content-Security-Policy (SEC-9)
# --------------------------------------------------------------------------
# Defense-in-depth on top of Jinja2 autoescape.  The hand-written UI is
# inline-heavy (inline <script>/<style> blocks, `onclick=` handlers and
# `style=` attributes across every template + the JS partials that build
# DOM), so a nonce/hash policy would need a full template refactor and is
# out of scope here — hence `'unsafe-inline'` on script-src/style-src.  The
# value this policy DOES add is real and non-breaking: it forbids loading
# or connecting to any off-origin host (`default-src 'self'`,
# `connect-src 'self'`), kills plugins (`object-src 'none'`), blocks
# `<base>` hijacking (`base-uri 'self'`), pins form submission to same
# origin so an injected form can't exfiltrate (`form-action 'self'`), and
# blocks framing (`frame-ancestors 'none'` — the modern companion to the
# `X-Frame-Options: DENY` set below).
_CSP_DEFAULT = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

# The custom /docs page wraps FastAPI's ``get_swagger_ui_html()``, which
# pulls the Swagger UI bundle + stylesheet from jsDelivr and a favicon
# from fastapi.tiangolo.com.  A same-origin-only policy would blank the
# page, so /docs gets a variant that additionally allows exactly those
# CDN hosts (and only those).  Everything else stays as strict as the
# default policy.
_CSP_DOCS = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://cdn.jsdelivr.net https://fastapi.tiangolo.com; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


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

        # Job persistence — sibling directory to configs_dir.  The
        # FileJobStore is the source of truth (every job is persisted
        # to {jobs_dir}/{id}.json).  BackupJobRegistry wraps it with
        # an LRU-bounded in-memory cache: pre-R8 the in-memory dict
        # was unbounded and grew indefinitely as jobs ran, so a server
        # that handled 100k jobs over its lifetime held ~500 MB of
        # BackupJob objects.  The registry caps memory at
        # settings.max_memory_jobs (default 1000, ~5 MB) and falls
        # through to disk lazy-load on get-by-id misses, so historical
        # jobs remain queryable without the unbounded memory cost.
        _app.state.job_store = FileJobStore(data_root / "jobs")
        _app.state.jobs = BackupJobRegistry(
            _app.state.job_store,
            max_memory_jobs=settings.max_memory_jobs,
            warm_cache=True,
        )

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

        # Surface an insecure SSH host-key posture once at startup so
        # 'auto_add' (the back-compat default) is a conscious choice, not
        # a silent one (audit T0-4 — the "most repeatable miss").
        from .collectors.hostkey import host_key_warning_reason
        if hk_warning := host_key_warning_reason(settings):
            logger.warning(hk_warning)

        yield

        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    # Resolve the package version from installed metadata so the
    # OpenAPI doc / Swagger UI tracks the actual release rather than
    # a hard-coded string that rots on every tag.  Falls back to a
    # sentinel when the package isn't installed (e.g. running from a
    # raw source tree without `pip install -e .`); this only affects
    # the `/docs` banner, never request handling.
    try:
        _app_version = _pkg_version("netcanon")
    except PackageNotFoundError:  # pragma: no cover - dev-only fallback
        _app_version = "0.0.0+unknown"

    app = FastAPI(
        title="Netcanon",
        description=(
            "Multi-vendor network configuration backup and translation engine. "
            "See /docs for the interactive API reference."
        ),
        version=_app_version,
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
        # SEC-9: Content-Security-Policy. The /docs Swagger page needs the
        # CDN-permitting variant; every other route (UI pages + JSON API)
        # gets the strict same-origin policy.
        response.headers["Content-Security-Policy"] = (
            _CSP_DOCS if request.url.path == "/docs" else _CSP_DEFAULT
        )
        return response

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    app.include_router(health_router.router)  # /health (no prefix; conventional probe path)
    # SEC-01: opt-in bearer-token gate on the whole /api/v1 surface.
    # No-op when NETCANON_API_KEY is unset (zero-config local UX).
    _api_v1_auth = [Depends(require_api_key)]
    app.include_router(defs_router.router, prefix="/api/v1", dependencies=_api_v1_auth)
    app.include_router(configs_router.router, prefix="/api/v1", dependencies=_api_v1_auth)
    app.include_router(backups_router.router, prefix="/api/v1", dependencies=_api_v1_auth)
    app.include_router(schedules_router.router, prefix="/api/v1", dependencies=_api_v1_auth)
    app.include_router(device_profiles_router.router, prefix="/api/v1", dependencies=_api_v1_auth)
    app.include_router(migration_router.router, prefix="/api/v1", dependencies=_api_v1_auth)
    app.include_router(sanitize_router.router, prefix="/api/v1", dependencies=_api_v1_auth)
    app.include_router(docs_router.router)  # custom Swagger UI at /docs (no prefix)
    app.include_router(ui_router.router)  # UI routes at root (/, /jobs, …)

    # Themed 404/500 pages for browser navigations (API surface keeps
    # its JSON error contract — see ui._wants_html).  Registered last so
    # it wraps the fully-mounted router set.
    ui_router.register_exception_handlers(app)

    # ------------------------------------------------------------------
    # OpenAPI security scheme (audit 276eaeb #9)
    # ------------------------------------------------------------------
    # require_api_key enforces an `Authorization: Bearer <key>` on /api/v1
    # when NETCANON_API_KEY is set, but it's a plain dependency (not a
    # fastapi Security scheme), so the generated OpenAPI never advertised
    # it: /docs had no "Authorize" button and a client couldn't discover
    # the requirement from the schema.  Inject the BearerAuth scheme — but
    # ONLY when a key is configured, so the schema stays honest (open with
    # no key, bearer-gated with one) and the zero-config local schema is
    # unchanged.  Applied to /api/v1 operations only; /health and the UI
    # routes are not bearer-gated.
    from fastapi.openapi.utils import get_openapi

    def _custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        # Read the live settings the enforcement uses (state is set in
        # lifespan; fall back to the resolved closure value otherwise).
        active = getattr(app.state, "settings", None) or settings
        if (getattr(active, "api_key", "") or "").strip():
            schema.setdefault("components", {}).setdefault(
                "securitySchemes", {}
            )["BearerAuth"] = {
                "type": "http",
                "scheme": "bearer",
                "description": (
                    "Static token from NETCANON_API_KEY, sent as "
                    "`Authorization: Bearer <token>`. Required on /api/v1 "
                    "when the key is configured (SEC-01)."
                ),
            }
            for path, item in schema.get("paths", {}).items():
                if not path.startswith("/api/v1"):
                    continue
                for operation in item.values():
                    if isinstance(operation, dict):
                        operation.setdefault("security", []).append(
                            {"BearerAuth": []}
                        )
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi

    return app


# Production application instance — used by ``uvicorn netcanon.main:app``
try:
    app = create_app()
except Exception as _exc:
    import sys

    print(f"Netcanon failed to start: {_exc}", file=sys.stderr)
    raise SystemExit(1) from _exc
