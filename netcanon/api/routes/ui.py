"""
Server-rendered UI routes (Jinja2 HTML pages).

Every ``GET /<page>`` endpoint that returns an ``HTMLResponse`` lives
here.  Extracted from ``main.py`` to keep the application factory
under ~120 lines and give each page a grep-friendly home.

All routes are registered on a single ``APIRouter`` with
``include_in_schema=False`` so they don't pollute the OpenAPI spec.

The Swagger UI wrapper at ``/docs`` lives in the sibling
``docs`` module (it's a rendered HTML page even though it wraps an
API surface).
"""

from __future__ import annotations

import heapq
import logging
from collections import defaultdict
from http import HTTPStatus
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"

router = APIRouter(include_in_schema=False)


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

_templates = Jinja2Templates(directory=_TEMPLATES_DIR)


def _format_interval(minutes: int) -> str:
    """Render a schedule interval as a human-readable phrase.

    Registered as the ``format_interval`` Jinja global so templates
    rendering schedule rows don't have to repeat the unit conversion
    inline.  Picks the largest whole-unit phrasing that fits — 90
    minutes is rendered as ``Every 1 hour`` (truncating, not rounding),
    matching the calendar-style "every <n> <unit>s" convention users
    expect for cron-like recurrence.

    Args:
        minutes: Schedule interval, in minutes.  Must be positive.

    Returns:
        A phrase of the form ``"Every N <unit>"`` with the unit chosen
        from ``min`` / ``hour(s)`` / ``day(s)`` / ``week(s)`` based on
        the largest whole division that fits.
    """
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


_templates.env.globals["format_interval"] = _format_interval


# ---------------------------------------------------------------------------
# Error pages (404 / 500)
# ---------------------------------------------------------------------------
#
# A mistyped URL or an uncaught server error used to drop the operator
# onto a raw JSON body (``{"detail":"Not Found"}``) with no nav and no
# theme.  These handlers render a themed ``error.html`` (extends
# ``base.html``) for *browser* navigations while preserving the JSON
# contract for the API surface and programmatic clients.

_ERROR_MESSAGES = {
    404: (
        "We couldn't find that page. It may have moved, or the link "
        "was mistyped."
    ),
    500: (
        "Something went wrong on our end. The error has been logged; "
        "try again, or head back to the dashboard."
    ),
}
_DEFAULT_ERROR_MESSAGE = "An unexpected error occurred."


def _wants_html(request: Request) -> bool:
    """True when the themed error page (not JSON) is the right response.

    Browser navigations to a non-API path send ``Accept: text/html``;
    they get the page.  Anything under ``/api/`` — and any programmatic
    client whose ``Accept`` is ``*/*`` or ``application/json`` (incl.
    the test harness's default) — keeps the JSON ``{"detail": ...}``
    contract untouched.
    """
    if request.url.path.startswith("/api/"):
        return False
    return "text/html" in request.headers.get("accept", "")


def _status_phrase(status_code: int) -> str:
    """Human phrase for an HTTP status (``404`` → ``"Not Found"``)."""
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Error"


def _render_error_page(request: Request, status_code: int) -> Response:
    return _templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": status_code,
            "status_text": _status_phrase(status_code),
            "message": _ERROR_MESSAGES.get(status_code, _DEFAULT_ERROR_MESSAGE),
        },
        status_code=status_code,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the themed 404/500 handlers onto *app*.

    Called from ``create_app`` after the routers are mounted.  Lives
    here (not in ``main.py``) so it can reuse this module's configured
    ``Jinja2Templates`` instance and its registered globals.
    """

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> Response:
        if _wants_html(request):
            return _render_error_page(request, exc.status_code)
        # Preserve FastAPI's default JSON shape for the API surface.
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> Response:
        # The traceback is logged here (with the request path) and again
        # by the framework when it re-raises; we never echo it to the
        # client.
        logger.exception("Unhandled error serving %s", request.url.path)
        if _wants_html(request):
            return _render_error_page(request, 500)
        return JSONResponse(
            {"detail": "Internal Server Error"}, status_code=500
        )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Dashboard: recent jobs summary and backup form."""
    jobs = heapq.nlargest(
        10,
        request.app.state.jobs.values(),
        key=lambda j: j.created_at,
    )
    return _templates.TemplateResponse(
        request,
        "index.html",
        {
            "active_page": "home",
            "definitions": request.app.state.definitions,
            "recent_jobs": jobs,
            "device_profiles": sorted(
                request.app.state.device_profiles.values(), key=lambda p: p.name
            ),
        },
    )


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request) -> HTMLResponse:
    """Full job history: all backup jobs with per-device config file links."""
    jobs = sorted(
        request.app.state.jobs.values(),
        key=lambda j: j.created_at,
        reverse=True,
    )
    return _templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "active_page": "jobs",
            "jobs": jobs,
            "open_in_editor": request.app.state.settings.open_in_editor,
        },
    )


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


@router.get("/schedules", response_class=HTMLResponse)
async def schedules_page(request: Request) -> HTMLResponse:
    """Schedule manager: create and manage recurring backup schedules."""
    schedules = sorted(
        request.app.state.schedules.values(),
        key=lambda s: s.created_at,
        reverse=True,
    )
    return _templates.TemplateResponse(
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


# ---------------------------------------------------------------------------
# Configs
# ---------------------------------------------------------------------------


@router.get("/configs", response_class=HTMLResponse)
async def configs_page(request: Request) -> HTMLResponse:
    """Config browser: list and delete stored configuration files."""
    configs = request.app.state.storage.list_configs()
    return _templates.TemplateResponse(
        request,
        "configs.html",
        {
            "active_page": "configs",
            "configs": configs,
            "open_in_editor": request.app.state.settings.open_in_editor,
        },
    )


# ---------------------------------------------------------------------------
# Config diff
# ---------------------------------------------------------------------------


@router.get("/configs/{left}/vs/{right}", response_class=HTMLResponse)
async def diff_page(
    left: str, right: str, request: Request, force: bool = False
) -> HTMLResponse:
    """Render a line-level textual diff between two stored configs.

    Path params double as a deep-linkable URL — copying the address
    bar reproduces the exact comparison.  The ``force`` query flag
    (``?force=true``) carries the same semantics as the API: it
    overrides an incompatible ``type_key`` / extension block and
    causes the template to surface a red banner above the diff.

    Unlike the API, this view never returns 404 or 422 — we always
    render the page so the user sees WHY the diff was blocked and
    can click the "Compare anyway" override button if appropriate.
    """
    from ...models.diff import DiffReport
    from ...services.diff import check_compatibility, compute_diff, fold_context

    storage = request.app.state.storage
    records_by_name = {r.filename: r for r in storage.list_configs()}
    left_rec = records_by_name.get(left)
    right_rec = records_by_name.get(right)

    # Error view: one or both filenames unknown.
    if left_rec is None or right_rec is None:
        missing = [
            name
            for name, rec in (("left", left_rec), ("right", right_rec))
            if rec is None
        ]
        return _templates.TemplateResponse(
            request,
            "diff.html",
            {
                "active_page": "configs",
                "left_filename": left,
                "right_filename": right,
                "error": f"Config(s) not found: {', '.join(missing)}",
                "force": force,
                "report": None,
            },
            status_code=404,
        )

    compat = check_compatibility(left_rec, right_rec)
    if not compat.compatible and not force:
        return _templates.TemplateResponse(
            request,
            "diff.html",
            {
                "active_page": "configs",
                "left_filename": left,
                "right_filename": right,
                "left": left_rec,
                "right": right_rec,
                "compatibility": compat,
                "force": False,
                "report": None,
            },
        )

    left_text = storage.get_content(left)
    right_text = storage.get_content(right)
    report: DiffReport = compute_diff(
        left_rec, left_text, right_rec, right_text, force=force
    )
    groups = fold_context(report.lines, context=3)
    return _templates.TemplateResponse(
        request,
        "diff.html",
        {
            "active_page": "configs",
            "left_filename": left,
            "right_filename": right,
            "left": left_rec,
            "right": right_rec,
            "compatibility": report.compatibility,
            "force": force,
            "report": report,
            "groups": groups,
        },
    )


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


@router.get("/devices", response_class=HTMLResponse)
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
    _CRED_FIELDS = {"password", "enable_password"}
    profiles_safe = {
        p.id: {k: v for k, v in p.model_dump(mode="json").items() if k not in _CRED_FIELDS}
        for p in profiles
    }
    return _templates.TemplateResponse(
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


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------


@router.get("/definitions", response_class=HTMLResponse)
async def definitions_page(request: Request) -> HTMLResponse:
    """Definition browser: surfaces every Netcanon data-source the
    user cares about.  Four sections:

    1. **Backup device definitions** (family-base) — the legacy view:
       what vendor YAMLs the backup layer recognises (``Cisco``,
       ``Fortigate`` etc.).  Excludes overlays.
    2. **Version / model overlays** — the extra variants loaded
       alongside family bases (e.g. ``Cisco 17.12`` version-pin).
       Explains the "loaded 5 but only 4 top-level rows" split.
    3. **Migration target profiles** — the 50+ hardware-aware
       profiles under ``definitions/target_profiles/``: per-model
       port layouts, module variants (NM-8X etc.), stacking caps,
       VLAN/user limits.  Previously only reachable through the
       Tier-3 rename modal's dropdown.
    4. **Vendors + codec capabilities** — the 8 migration vendors
       with their shipped codecs (direction, certainty tier,
       device classes).
    """
    state = request.app.state
    defs = sorted(state.definitions.values(), key=lambda d: d.type_key)

    # Overlays: loaded variants that have os_version OR model set
    # (the loader filters these out of load_all but keeps them in
    # _variants for priority-resolve).  Absence-guarded for tests
    # that mount a bare app.
    overlays = []
    loader = getattr(state, "definition_loader", None)
    if loader is not None:
        for variant in getattr(loader, "_variants", []):
            if variant.os_version is not None or variant.model is not None:
                overlays.append(variant)
    overlays.sort(key=lambda d: (d.type_key, d.os_version or "", d.model or ""))

    # Target profiles — group by vendor for readable rendering.
    target_profiles = getattr(state, "target_profiles", {}) or {}
    profiles_by_vendor: dict[str, list] = {}
    for profile in target_profiles.values():
        profiles_by_vendor.setdefault(profile.vendor, []).append(profile)
    for vendor_key in profiles_by_vendor:
        profiles_by_vendor[vendor_key].sort(key=lambda p: p.model.lower())
    # Stable vendor order for the outer <details> blocks.
    profiles_by_vendor_sorted = sorted(profiles_by_vendor.items())

    # Vendors + their codec summaries.  Pull codec classes from the
    # registry so the view lists what the app actually exposes today
    # (no stale YAML entries without a codec).
    from ...migration.codecs.registry import _REGISTRY as _CODEC_REGISTRY

    vendors_dict = getattr(state, "vendors", {}) or {}
    vendor_rows = []
    for vendor_id in sorted(vendors_dict.keys()):
        vendor = vendors_dict[vendor_id]
        # Find codecs whose vendor_id matches this vendor.  Class-
        # level capability attribute drives the certainty tier +
        # direction fields; we surface those without instantiating.
        codecs: list[dict] = []
        for codec_name, codec_cls in sorted(_CODEC_REGISTRY.items()):
            # vendor_id comes from the CapabilityMatrix; access
            # without instantiating by inspecting the _CAPS
            # ClassVar.  Fall through gracefully if a codec doesn't
            # declare one (defensive — all shipped codecs do).
            caps = getattr(codec_cls, "_CAPS", None)
            if caps is None or getattr(caps, "vendor_id", "") != vendor_id:
                continue
            codecs.append({
                "name": codec_name,
                "direction": getattr(codec_cls, "direction", ""),
                "certainty": getattr(codec_cls, "certainty", ""),
                "input_format": getattr(codec_cls, "input_format", ""),
                "supported_count": len(getattr(caps, "supported", []) or []),
                "lossy_count": len(getattr(caps, "lossy", []) or []),
                "unsupported_count": len(getattr(caps, "unsupported", []) or []),
            })
        vendor_rows.append({
            "info": vendor,
            "codecs": codecs,
        })

    return _templates.TemplateResponse(
        request,
        "definitions.html",
        {
            "active_page": "definitions",
            "definitions": defs,
            "overlays": overlays,
            "profiles_by_vendor": profiles_by_vendor_sorted,
            "target_profile_count": len(target_profiles),
            "vendor_rows": vendor_rows,
        },
    )


# ---------------------------------------------------------------------------
# Migrate (translator workbench)
# ---------------------------------------------------------------------------


@router.get("/migrate", response_class=HTMLResponse)
async def migrate_page(request: Request) -> HTMLResponse:
    """Translator workbench: pick source + target adapters, paste or
    select a config, submit to ``POST /api/v1/migration/plan``, and
    review the validation report + rendered output in-page.
    """
    configs = request.app.state.storage.list_configs()
    return _templates.TemplateResponse(
        request,
        "migrate.html",
        {
            "active_page": "migrate",
            "configs": configs,
        },
    )


# ---------------------------------------------------------------------------
# Sanitize (PII redaction page)
# ---------------------------------------------------------------------------


@router.get("/sanitize", response_class=HTMLResponse)
async def sanitize_page(request: Request) -> HTMLResponse:
    """Sanitize workbench: pick source vendor, paste or select a
    config, submit to ``POST /api/v1/sanitize``, and review the
    redaction audit + sanitized output in-page.

    Phase-3 Round-6 deliverable: closes the audit-flagged HIGH-severity
    "sanitize is API-only" feature-discovery gap before v0.1.0 launch.
    Mirrors the migrate page's input-mode pattern (paste raw / pick
    stored) so operators familiar with one surface immediately
    understand the other.
    """
    configs = request.app.state.storage.list_configs()
    return _templates.TemplateResponse(
        request,
        "sanitize.html",
        {
            "active_page": "sanitize",
            "configs": configs,
        },
    )


# NOTE: A second ``/health`` handler used to live here returning per-
# resource counts (definitions / schedules / profiles / jobs).  It was
# dead code — ``health_router`` is registered first in ``main.py``
# (see ``app.include_router(health_router.router)``) so its minimal
# ``{"status":"ok","version":...}`` handler always won.  Removed in R8
# along with the registry refactor; if operators want per-resource
# counts in the future, add them as a separate ``/diagnostics``
# endpoint rather than reviving the shadow.
