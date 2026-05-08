"""
Server-rendered UI routes (Jinja2 HTML pages).

Every ``GET /<page>`` endpoint that returns an ``HTMLResponse`` lives
here.  Extracted from ``main.py`` to keep the application factory
under ~120 lines and give each page a grep-friendly home.

All routes are registered on a single ``APIRouter`` with
``include_in_schema=False`` so they don't pollute the OpenAPI spec.

The Swagger UI wrapper at ``/docs`` is also here because it's a
rendered HTML page even though it wraps an API surface.
"""

from __future__ import annotations

import heapq
import logging
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

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
    from ...services.diff import check_compatibility, compute_diff, fold_context
    from ...models.diff import DiffReport

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
# Swagger UI (custom-wrapped)
# ---------------------------------------------------------------------------


@router.get("/docs")
async def swagger_ui() -> HTMLResponse:
    """Swagger UI wrapped in the Netcanon nav bar."""
    base = get_swagger_ui_html(
        openapi_url="/api/v1/openapi.json",
        title="Netcanon — API Docs",
    )
    html = base.body.decode("utf-8")
    nav_html = (
        '<nav id="nc-nav">'
        '<a href="/" class="brand">Netcanon</a>'
        '<a href="/">Dashboard</a>'
        '<a href="/devices">Devices</a>'
        '<a href="/jobs">Jobs</a>'
        '<a href="/schedules">Schedules</a>'
        '<a href="/configs">Configs</a>'
        '<a href="/definitions">Definitions</a>'
        '<a href="/migrate">Migrate</a>'
        '<a href="/docs" class="active">API Docs</a>'
        "</nav>"
    )
    nav_css = (
        "<style>"
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


# ---------------------------------------------------------------------------
# Health (infrastructure, not UI — but lives here to keep main.py minimal)
# ---------------------------------------------------------------------------


@router.get("/health")
async def health(request: Request):
    """Basic health check for readiness probes."""
    return {
        "status": "ok",
        "definitions": len(request.app.state.definitions),
        "schedules": len(request.app.state.schedules),
        "profiles": len(request.app.state.device_profiles),
        "jobs": len(request.app.state.jobs),
    }
