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
from .config import Settings
from .definitions.loader import DefinitionLoader
from .storage.file_store import FileConfigStore

logger = logging.getLogger(__name__)
_TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure a NetConfig FastAPI application instance.

    Calling this multiple times produces independent application instances,
    each with its own state (definitions, storage, job registry).  This
    is essential for test isolation — each test fixture calls
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
        logger.info("Loading device definitions from %s", settings.definitions_dir)
        _app.state.settings = settings
        _app.state.definitions = DefinitionLoader(settings.definitions_dir).load_all()
        _app.state.storage = FileConfigStore(settings.configs_dir)
        _app.state.jobs: dict = {}
        logger.info(
            "NetConfig started — %d definition(s) loaded",
            len(_app.state.definitions),
        )
        yield
        # Nothing to clean up for file-based storage.

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

    # ------------------------------------------------------------------
    # UI routes (Jinja2 server-rendered HTML)
    # ------------------------------------------------------------------
    templates = Jinja2Templates(directory=_TEMPLATES_DIR)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request) -> HTMLResponse:
        """Dashboard: recent jobs and backup form."""
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
        nav_css = (
            "<style>"
            "#nc-nav{background:#1a1a2e;padding:.75rem 1.5rem;display:flex;"
            "gap:1.5rem;align-items:center;position:sticky;top:0;z-index:10000;"
            "box-shadow:0 1px 4px rgba(0,0,0,.4)}"
            "#nc-nav a{color:#eee;text-decoration:none;font-size:.95rem}"
            "#nc-nav a:hover{color:#fff;text-decoration:underline}"
            "#nc-nav .brand{color:#7eb8f7;font-weight:700;font-size:1.1rem;"
            "margin-right:auto;text-decoration:none}"
            "#nc-nav .active{color:#fff;border-bottom:2px solid #7eb8f7;padding-bottom:2px}"
            "</style>"
        )
        nav_html = (
            '<nav id="nc-nav">'
            '<a href="/" class="brand">NetConfig</a>'
            '<a href="/">Dashboard</a>'
            '<a href="/configs">Configs</a>'
            '<a href="/definitions">Definitions</a>'
            '<a href="/docs" class="active">API Docs</a>'
            "</nav>"
        )
        html = html.replace("</head>", f"{nav_css}</head>", 1)
        html = html.replace("<body>", f"<body>{nav_html}", 1)
        return HTMLResponse(content=html)

    return app


# Production application instance — used by ``uvicorn netconfig.main:app``
app = create_app()
