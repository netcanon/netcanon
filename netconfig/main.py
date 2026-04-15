"""
Application factory and UI route handlers.

The ``create_app`` factory is the primary entry point for both production
and testing.  Pass a custom ``Settings`` instance to inject test-specific
directories and overrides without touching environment variables::

    from netconfig.main import create_app
    from netconfig.config import Settings

    app = create_app(Settings(configs_dir=tmp_path / "configs"))

The module-level ``app`` object is the production instance used by
Uvicorn::

    uvicorn netconfig.main:app --reload
"""

from __future__ import annotations

import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .api.routes import backups as backups_router
from .api.routes import configs as configs_router
from .api.routes import definitions as defs_router
from .api.routes import device_profiles as device_profiles_router
from .api.routes import schedules as schedules_router
from .config import Settings
from .definitions.loader import DefinitionLoader
from .storage.device_profile_store import FileDeviceProfileStore
from .storage.file_store import FileConfigStore
from .storage.job_store import FileJobStore
from .storage.schedule_store import FileScheduleStore

logger = logging.getLogger(__name__)
_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _format_interval(minutes: int) -> str:
    """Human-readable interval string for use in templates."""
    if minutes < 60:
        return f"Every {minutes} min"
    if minutes < 1440:
        h = minutes // 60
        return f"Every {h} hour{'s' if h != 1 else ''}"
    if minutes < 10080:
        d = minutes // 1440
        return f"Every {d} day{'s' if d != 1 else ''}"
    w = minutes // 10080
    return f"Every {w} week{'s' if w != 1 else ''}"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a NetConfig FastAPI application instance.

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
        _app.state.definitions = DefinitionLoader(
            settings.definitions_dir
        ).load_all()
        _app.state.storage = FileConfigStore(settings.configs_dir)

        # Job persistence — sibling directory to configs_dir
        data_root = settings.configs_dir.parent
        _app.state.job_store = FileJobStore(data_root / "jobs")
        _app.state.jobs = _app.state.job_store.load_all()

        # Schedule persistence
        _app.state.schedule_store = FileScheduleStore(data_root / "schedules")
        _app.state.schedules = _app.state.schedule_store.load_all()

        # Device profile persistence
        _app.state.device_profile_store = FileDeviceProfileStore(data_root / "devices")
        _app.state.device_profiles = _app.state.device_profile_store.load_all()

        # APScheduler — purely in-memory; schedules are persisted separately
        scheduler = AsyncIOScheduler(timezone="UTC")
        _app.state.scheduler = scheduler

        # Re-register all enabled schedules
        for schedule in _app.state.schedules.values():
            if schedule.enabled:
                register_schedule_job(scheduler, schedule, _app)
                ap_job = scheduler.get_job(schedule.id)
                if ap_job and ap_job.next_run_time:
                    schedule.next_run_at = ap_job.next_run_time
                    _app.state.schedule_store.save(schedule)

        scheduler.start()
        logger.info(
            "NetConfig started — %d definition(s) loaded, %d schedule(s) active",
            len(_app.state.definitions),
            len([s for s in _app.state.schedules.values() if s.enabled]),
        )

        yield

        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    app = FastAPI(
        title="NetConfig",
        description=(
            "Multi-vendor network configuration backup and translation engine. "
            "See /docs for the interactive API reference."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,   # we serve a nav-wrapped version at /docs below
        redoc_url=None,  # not surfaced in the UI
    )

    # ------------------------------------------------------------------
    # API routes
    # ------------------------------------------------------------------
    app.include_router(defs_router.router, prefix="/api/v1")
    app.include_router(configs_router.router, prefix="/api/v1")
    app.include_router(backups_router.router, prefix="/api/v1")
    app.include_router(schedules_router.router, prefix="/api/v1")
    app.include_router(device_profiles_router.router, prefix="/api/v1")

    # ------------------------------------------------------------------
    # UI routes (Jinja2 server-rendered HTML)
    # ------------------------------------------------------------------
    templates = Jinja2Templates(directory=_TEMPLATES_DIR)
    templates.env.globals["format_interval"] = _format_interval

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request) -> HTMLResponse:
        """Dashboard: recent jobs summary and backup form."""
        jobs = sorted(
            request.app.state.jobs.values(),
            key=lambda j: j.created_at,
            reverse=True,
        )
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "active_page": "home",
                "definitions": request.app.state.definitions,
                "recent_jobs": jobs[:10],
                "device_profiles": sorted(
                    request.app.state.device_profiles.values(), key=lambda p: p.name
                ),
            },
        )

    @app.get("/jobs", response_class=HTMLResponse, include_in_schema=False)
    async def jobs_page(request: Request) -> HTMLResponse:
        """Full job history: all backup jobs with per-device config file links."""
        jobs = sorted(
            request.app.state.jobs.values(),
            key=lambda j: j.created_at,
            reverse=True,
        )
        return templates.TemplateResponse(
            request,
            "jobs.html",
            {
                "active_page": "jobs",
                "jobs": jobs,
                "open_in_editor": request.app.state.settings.open_in_editor,
            },
        )

    @app.get("/schedules", response_class=HTMLResponse, include_in_schema=False)
    async def schedules_page(request: Request) -> HTMLResponse:
        """Schedule manager: create and manage recurring backup schedules."""
        schedules = sorted(
            request.app.state.schedules.values(),
            key=lambda s: s.created_at,
            reverse=True,
        )
        return templates.TemplateResponse(
            request,
            "schedules.html",
            {
                "active_page": "schedules",
                "schedules": schedules,
                "definitions": request.app.state.definitions,
                "device_profiles": sorted(
                    request.app.state.device_profiles.values(), key=lambda p: p.name
                ),
            },
        )

    @app.get("/configs", response_class=HTMLResponse, include_in_schema=False)
    async def configs_page(request: Request) -> HTMLResponse:
        """Config browser: list and delete stored configuration files."""
        configs = request.app.state.storage.list_configs()
        return templates.TemplateResponse(
            request,
            "configs.html",
            {
                "active_page": "configs",
                "configs": configs,
                "open_in_editor": request.app.state.settings.open_in_editor,
            },
        )

    @app.get("/devices", response_class=HTMLResponse, include_in_schema=False)
    async def devices_page(request: Request) -> HTMLResponse:
        """Device profile manager: create and manage persistent device profiles."""
        profiles = sorted(
            request.app.state.device_profiles.values(),
            key=lambda p: p.created_at,
            reverse=True,
        )
        configs = request.app.state.storage.list_configs()
        configs_by_profile: dict[str, list] = defaultdict(list)
        for c in configs:
            if c.device_profile_id:
                configs_by_profile[c.device_profile_id].append(c)
        # Strip credentials before embedding profiles in the DOM.
        _CRED_FIELDS = {"password", "enable_password"}
        profiles_safe = {
            p.id: {k: v for k, v in p.model_dump().items() if k not in _CRED_FIELDS}
            for p in profiles
        }
        return templates.TemplateResponse(
            request,
            "devices.html",
            {
                "active_page": "devices",
                "device_profiles": profiles,
                "profiles_safe": profiles_safe,
                "definitions": request.app.state.definitions,
                "configs_by_profile": dict(configs_by_profile),
            },
        )

    @app.get("/definitions", response_class=HTMLResponse, include_in_schema=False)
    async def definitions_page(request: Request) -> HTMLResponse:
        """Definition browser: inspect all loaded device definitions."""
        defs = sorted(
            request.app.state.definitions.values(), key=lambda d: d.type_key
        )
        return templates.TemplateResponse(
            request,
            "definitions.html",
            {"active_page": "definitions", "definitions": defs},
        )

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui() -> HTMLResponse:
        """Swagger UI wrapped in the NetConfig nav bar."""
        base = get_swagger_ui_html(
            openapi_url="/openapi.json",
            title="NetConfig — API Docs",
        )
        html = base.body.decode("utf-8")
        # Inject nav HTML right after <body> so it appears first in the DOM.
        # Inject our CSS right before </body> so it loads AFTER Swagger UI's
        # stylesheet and wins any specificity ties without needing !important.
        nav_html = (
            '<nav id="nc-nav">'
            '<a href="/" class="brand">NetConfig</a>'
            '<a href="/">Dashboard</a>'
            '<a href="/devices">Devices</a>'
            '<a href="/jobs">Jobs</a>'
            '<a href="/schedules">Schedules</a>'
            '<a href="/configs">Configs</a>'
            '<a href="/definitions">Definitions</a>'
            '<a href="/docs" class="active">API Docs</a>'
            "</nav>"
        )
        nav_css = (
            "<style>"
            # Nuke any body/html margin that creates the white stripe above our nav
            "html,body{margin:0!important;padding:0!important}"
            "nav#nc-nav{"
            "box-sizing:border-box!important;"
            "background:#1a1a2e!important;"
            "padding:.75rem 1.5rem!important;"
            "display:flex!important;"
            "gap:1.5rem!important;"
            "align-items:center!important;"
            "position:sticky!important;"
            "top:0!important;"
            "z-index:10000!important;"
            "box-shadow:0 1px 4px rgba(0,0,0,.4)!important;"
            "font-family:system-ui,sans-serif!important;"
            "margin:0!important;"
            "width:100%!important;"
            "}"
            "nav#nc-nav a{"
            "color:#eee!important;"
            "text-decoration:none!important;"
            "font-size:.95rem!important;"
            "font-family:system-ui,sans-serif!important;"
            "}"
            "nav#nc-nav a:hover{color:#fff!important;text-decoration:underline!important}"
            "nav#nc-nav a.brand{"
            "color:#7eb8f7!important;"
            "font-weight:700!important;"
            "font-size:1.1rem!important;"
            "margin-right:auto!important;"
            "text-decoration:none!important;"
            "}"
            "nav#nc-nav a.active{"
            "color:#fff!important;"
            "border-bottom:2px solid #7eb8f7!important;"
            "padding-bottom:2px!important;"
            "}"
            "</style>"
        )
        html = html.replace("<body>", f"<body>{nav_html}", 1)
        html = html.replace("</body>", f"{nav_css}</body>", 1)
        return HTMLResponse(content=html)

    return app


# Production application instance — used by ``uvicorn netconfig.main:app``
app = create_app()
