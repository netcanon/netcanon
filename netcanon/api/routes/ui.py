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


# ---------------------------------------------------------------------------
# Swagger UI (custom-wrapped)
# ---------------------------------------------------------------------------


# Boot script — duplicates base.html's <head> theme-detect so the
# /docs page paints in the right theme without a flash of light
# content.  Must stay in sync with base.html.  Reads localStorage,
# falls back to prefers-color-scheme, mutates <html data-theme>
# before any CSS applies.
_DOCS_BOOT_SCRIPT = """<script>
(function() {
  try {
    var stored = localStorage.getItem('netcanon.theme.v1');
    var theme;
    if (stored === 'dark' || stored === 'light') {
      theme = stored;
    } else if (window.matchMedia &&
               window.matchMedia('(prefers-color-scheme: dark)').matches) {
      theme = 'dark';
    } else {
      theme = 'light';
    }
    document.documentElement.setAttribute('data-theme', theme);
  } catch (_) { /* sandboxed iframe; fall through */ }
})();
</script>"""


# Theme tokens — duplicated from base.html so /docs (which doesn't
# extend base.html) can still re-theme.  Only the tokens referenced
# by the docs page nav + Swagger UI overrides are listed; not the
# full base.html set.  Token names + dark-mode values match base.html
# exactly — drift here means /docs renders different colours than the
# rest of the app.
_DOCS_TOKEN_STYLES = """<style>
:root {
  --page-bg: #f5f5f5;
  --surface: #ffffff;
  --surface-alt: #fafafa;
  --surface-elev: #e8e8f0;
  --surface-hover: #d0d0d8;
  --text-primary: #222222;
  --text-muted: #555555;
  --text-faint: #888888;
  --border: #eeeeee;
  --border-strong: #cccccc;
  --nav-bg: #1a1a2e;
  --nav-fg: #eeeeee;
  --nav-fg-hover: #ffffff;
  --nav-accent: #7eb8f7;
  --nav-accent-hov: #a8d0ff;
  --accent: #7eb8f7;
  --btn-secondary-bg: #e2e3e5;
  --btn-secondary-fg: #383d41;
  --pre-bg: #1e1e1e;
  --pre-fg: #d4d4d4;
  --shadow-card: 0 1px 3px rgba(0,0,0,.1);
}
[data-theme="dark"] {
  --page-bg: #121212;
  --surface: #1e1e1e;
  --surface-alt: #262626;
  --surface-elev: #2a2a38;
  --surface-hover: #333344;
  --text-primary: #e8e8ea;
  --text-muted: #b0b0b8;
  --text-faint: #808088;
  --border: #333338;
  --border-strong: #555560;
  --nav-bg: #0d0d18;
  --nav-fg: #e8e8ea;
  --nav-fg-hover: #ffffff;
  --nav-accent: #7eb8f7;
  --nav-accent-hov: #a8d0ff;
  --accent: #7eb8f7;
  --btn-secondary-bg: #333344;
  --btn-secondary-fg: #e8e8ea;
  --pre-bg: #181818;
  --pre-fg: #d4d4d4;
  --shadow-card: 0 1px 3px rgba(0,0,0,.4);
}
html, body { margin: 0 !important; padding: 0 !important; }
body { background: var(--page-bg) !important; color: var(--text-primary) !important; }
</style>"""


# Nav bar — mirrors base.html's nav structure (page-nav cluster +
# spacer + right-rail buttons) but using inline styles + !important
# because Swagger UI's CDN CSS otherwise wins specificity.  The
# theme-toggle button calls a locally-defined toggleTheme() (Swagger
# UI doesn't load base.html's JS).  The "?" button links to
# /?show-shortcuts=1 — the docs page has no per-page shortcuts of
# its own, so navigating home + auto-opening the cheatsheet is the
# right "I want to see shortcuts" UX.
_DOCS_NAV_HTML = (
    '<nav id="nc-nav" data-testid="nav">'
    '<a href="/" class="brand" data-testid="nav-brand">Netcanon</a>'
    '<a href="/" data-testid="nav-home">Dashboard</a>'
    '<a href="/devices" data-testid="nav-devices">Devices</a>'
    '<a href="/jobs" data-testid="nav-jobs">Jobs</a>'
    '<a href="/schedules" data-testid="nav-schedules">Schedules</a>'
    '<a href="/configs" data-testid="nav-configs">Configs</a>'
    '<a href="/definitions" data-testid="nav-definitions">Definitions</a>'
    '<a href="/migrate" data-testid="nav-migrate">Migrate</a>'
    '<a href="/sanitize" data-testid="nav-sanitize">Sanitize</a>'
    '<a href="/docs" class="active" data-testid="nav-api-docs">API Docs</a>'
    '<span class="nc-spacer" aria-hidden="true"></span>'
    '<a href="/?show-shortcuts=1" id="nav-kbd-cheatsheet"'
    ' data-testid="kbd-cheatsheet-open-btn"'
    ' aria-label="Show keyboard shortcuts"'
    ' title="Keyboard shortcuts (?) — shown on the main app pages">'
    '<span aria-hidden="true">?</span></a>'
    '<button type="button" id="nav-theme-toggle"'
    ' data-testid="nav-theme-toggle"'
    ' aria-label="Switch theme"'
    ' title="Switch between light and dark theme"'
    ' onclick="toggleTheme()">'
    '<span class="moon" aria-hidden="true">&#x263D;</span>'
    '<span class="sun" aria-hidden="true">&#x2600;</span>'
    '</button>'
    "</nav>"
)


# Nav CSS — uses --nav-* tokens defined above, !important because
# Swagger UI's CDN CSS otherwise wins.  Mirror's base.html's nav
# styling (spacer, right-rail icon buttons, sun/moon glyph swap via
# CSS attribute selector).
_DOCS_NAV_CSS = """<style>
nav#nc-nav {
  box-sizing: border-box !important;
  background: var(--nav-bg) !important;
  padding: .75rem 1.5rem !important;
  display: flex !important;
  gap: 1.5rem !important;
  align-items: center !important;
  position: sticky !important;
  top: 0 !important;
  z-index: 10000 !important;
  box-shadow: 0 1px 4px rgba(0,0,0,.4) !important;
  font-family: system-ui, sans-serif !important;
  margin: 0 !important;
  width: 100% !important;
}
nav#nc-nav a {
  color: var(--nav-fg) !important;
  text-decoration: none !important;
  font-size: .95rem !important;
  font-family: system-ui, sans-serif !important;
}
nav#nc-nav a:hover { color: var(--nav-fg-hover) !important; text-decoration: underline !important; }
nav#nc-nav a.brand {
  color: var(--nav-accent) !important;
  font-weight: 700 !important;
  font-size: 1.1rem !important;
  text-decoration: none !important;
}
nav#nc-nav a.active {
  color: var(--nav-fg-hover) !important;
  border-bottom: 2px solid var(--nav-accent) !important;
  padding-bottom: 2px !important;
}
nav#nc-nav .nc-spacer { flex: 1 1 auto !important; }
nav#nc-nav #nav-kbd-cheatsheet,
nav#nc-nav #nav-theme-toggle {
  background: transparent !important;
  color: var(--nav-fg) !important;
  border: 1px solid transparent !important;
  border-radius: 4px !important;
  padding: .3rem .55rem !important;
  font-size: 1rem !important;
  line-height: 1 !important;
  cursor: pointer !important;
  font-weight: normal !important;
  text-decoration: none !important;
  display: inline-flex !important;
  align-items: center !important;
  transition: background-color .12s ease, color .12s ease, border-color .12s ease !important;
}
nav#nc-nav #nav-kbd-cheatsheet:hover,
nav#nc-nav #nav-kbd-cheatsheet:focus-visible,
nav#nc-nav #nav-theme-toggle:hover,
nav#nc-nav #nav-theme-toggle:focus-visible {
  background: rgba(255,255,255,.08) !important;
  color: var(--nav-fg-hover) !important;
  border-color: rgba(255,255,255,.18) !important;
  outline: none !important;
}
nav#nc-nav #nav-theme-toggle .moon,
nav#nc-nav #nav-theme-toggle .sun { display: none !important; }
[data-theme="light"] nav#nc-nav #nav-theme-toggle .moon { display: inline !important; }
[data-theme="dark"]  nav#nc-nav #nav-theme-toggle .sun  { display: inline !important; }
</style>"""


# Local toggleTheme() — Swagger UI page doesn't load base.html's JS
# partials, so we inline a stripped-down toggle that flips
# data-theme + persists to localStorage.  No aria-label live-update
# (the underlying CSS selector swap handles the glyph; the title
# attribute is good-enough for screen readers on a developer page).
_DOCS_TOGGLE_JS = """<script>
function toggleTheme() {
  var html = document.documentElement;
  var current = html.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  var next = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  try { localStorage.setItem('netcanon.theme.v1', next); } catch (_) {}
}
</script>"""


# Swagger UI dark-mode CSS overrides — applied via the
# `[data-theme="dark"] .swagger-ui` selector chain which has higher
# specificity than the CDN's `.swagger-ui` rules.  Covers the high-
# visibility surfaces operators see when browsing the API:
# info / opblock cards / tag headings / parameter & response
# tables / model explorer / try-it-out inputs.  Doesn't try to
# theme every Swagger surface — that's a v0.2.0 polish concern.
_DOCS_SWAGGER_DARK_CSS = """<style>
[data-theme="dark"] body { background: var(--page-bg) !important; }
[data-theme="dark"] .swagger-ui,
[data-theme="dark"] .swagger-ui .scheme-container,
[data-theme="dark"] .swagger-ui .info .title,
[data-theme="dark"] .swagger-ui .info p,
[data-theme="dark"] .swagger-ui .info li,
[data-theme="dark"] .swagger-ui .info table,
[data-theme="dark"] .swagger-ui .opblock-tag,
[data-theme="dark"] .swagger-ui .opblock-tag small,
[data-theme="dark"] .swagger-ui .opblock .opblock-summary-description,
[data-theme="dark"] .swagger-ui .opblock-description-wrapper p,
[data-theme="dark"] .swagger-ui .opblock-description-wrapper h4,
[data-theme="dark"] .swagger-ui .opblock-external-docs-wrapper h4,
[data-theme="dark"] .swagger-ui .opblock-section-header,
[data-theme="dark"] .swagger-ui .opblock-section-header h4,
[data-theme="dark"] .swagger-ui .opblock-section-header label,
[data-theme="dark"] .swagger-ui table thead tr th,
[data-theme="dark"] .swagger-ui table thead tr td,
[data-theme="dark"] .swagger-ui .parameters-col_description p,
[data-theme="dark"] .swagger-ui .parameter__name,
[data-theme="dark"] .swagger-ui .parameter__type,
[data-theme="dark"] .swagger-ui .parameter__in,
[data-theme="dark"] .swagger-ui .response-col_status,
[data-theme="dark"] .swagger-ui .response-col_description,
[data-theme="dark"] .swagger-ui .responses-inner h4,
[data-theme="dark"] .swagger-ui .responses-inner h5,
[data-theme="dark"] .swagger-ui .model,
[data-theme="dark"] .swagger-ui .model-title,
[data-theme="dark"] .swagger-ui .model-toggle,
[data-theme="dark"] .swagger-ui section.models h4,
[data-theme="dark"] .swagger-ui section.models h5,
[data-theme="dark"] .swagger-ui .markdown p,
[data-theme="dark"] .swagger-ui .renderedMarkdown p,
[data-theme="dark"] .swagger-ui .tab li,
[data-theme="dark"] .swagger-ui label { color: var(--text-primary) !important; }

[data-theme="dark"] .swagger-ui .scheme-container,
[data-theme="dark"] .swagger-ui .opblock,
[data-theme="dark"] .swagger-ui section.models,
[data-theme="dark"] .swagger-ui section.models.is-open,
[data-theme="dark"] .swagger-ui .model-container,
[data-theme="dark"] .swagger-ui .responses-table { background: var(--surface) !important; }

[data-theme="dark"] .swagger-ui .opblock-tag { border-bottom: 1px solid var(--border) !important; }
[data-theme="dark"] .swagger-ui .opblock { border: 1px solid var(--border) !important; box-shadow: var(--shadow-card) !important; }
[data-theme="dark"] .swagger-ui .opblock-section-header { background: var(--surface-alt) !important; box-shadow: none !important; }
[data-theme="dark"] .swagger-ui table thead tr th,
[data-theme="dark"] .swagger-ui table thead tr td { background: var(--surface-elev) !important; border-bottom: 1px solid var(--border) !important; }
[data-theme="dark"] .swagger-ui .responses-table .response { border-bottom: 1px solid var(--border) !important; }
[data-theme="dark"] .swagger-ui section.models { border: 1px solid var(--border) !important; }
[data-theme="dark"] .swagger-ui .model-container { border-bottom: 1px solid var(--border) !important; }

/* Inputs inside Try it out */
[data-theme="dark"] .swagger-ui input[type="text"],
[data-theme="dark"] .swagger-ui input[type="email"],
[data-theme="dark"] .swagger-ui input[type="password"],
[data-theme="dark"] .swagger-ui input[type="number"],
[data-theme="dark"] .swagger-ui input[type="search"],
[data-theme="dark"] .swagger-ui textarea,
[data-theme="dark"] .swagger-ui select {
  background: var(--surface) !important;
  color: var(--text-primary) !important;
  border: 1px solid var(--border-strong) !important;
}

/* Code samples + highlighted response bodies (already dark on most
   palettes, but force consistency). */
[data-theme="dark"] .swagger-ui .highlight-code,
[data-theme="dark"] .swagger-ui .microlight,
[data-theme="dark"] .swagger-ui pre {
  background: var(--pre-bg) !important;
  color: var(--pre-fg) !important;
}

/* Secondary text — descriptions, deprecation notes, schema types. */
[data-theme="dark"] .swagger-ui .opblock-description-wrapper,
[data-theme="dark"] .swagger-ui .response-col_description__inner div.markdown,
[data-theme="dark"] .swagger-ui small,
[data-theme="dark"] .swagger-ui .parameter__deprecated { color: var(--text-muted) !important; }

/* ── Schema explorer (Schemas section + inline model trees) ──────────
   These selectors target the long tail of model-property chrome that
   wasn't in the initial override pass: the white pill-buttons on
   `BackupJob ^ Collapse all` / `Enum ^ Collapse all` / nested
   property rows, plus the low-contrast enum-value list and Default=
   text the model explorer renders.  Selectors are intentionally
   broad — Swagger UI's schema explorer uses many overlapping classes
   per property row and pinning each individually would balloon this
   block.  */
[data-theme="dark"] .swagger-ui .model-toggle,
[data-theme="dark"] .swagger-ui .model-toggle:after,
[data-theme="dark"] .swagger-ui .expand-operation,
[data-theme="dark"] .swagger-ui section.models .model-container,
[data-theme="dark"] .swagger-ui .model-box,
[data-theme="dark"] .swagger-ui .model-box-control,
[data-theme="dark"] .swagger-ui .json-schema-2020-12,
[data-theme="dark"] .swagger-ui .json-schema-2020-12-head,
[data-theme="dark"] .swagger-ui .json-schema-2020-12-body,
[data-theme="dark"] .swagger-ui .json-schema-2020-12-property,
[data-theme="dark"] .swagger-ui .json-schema-2020-12-expand-deep-button,
[data-theme="dark"] .swagger-ui .json-schema-2020-12-keyword,
[data-theme="dark"] .swagger-ui .json-schema-2020-12-keyword__name,
[data-theme="dark"] .swagger-ui .json-schema-2020-12-keyword__value {
  background: transparent !important;
  color: var(--text-primary) !important;
}

/* The "BackupJob ^ Collapse all" style pill chrome — these specific
   buttons render with a visible boxed background even with the
   "transparent" override above because their `.swagger-ui` class
   chain is more specific.  Force surface-elev so they read as
   subtle chips rather than glaring light pills. */
[data-theme="dark"] .swagger-ui .json-schema-2020-12-expand-deep-button,
[data-theme="dark"] .swagger-ui .json-schema-2020-12-accordion,
[data-theme="dark"] .swagger-ui .json-schema-2020-12 button,
[data-theme="dark"] .swagger-ui .model-box .model-toggle,
[data-theme="dark"] .swagger-ui section.models .model-box {
  background: var(--surface-elev) !important;
  color: var(--text-primary) !important;
  border-color: var(--border) !important;
}

/* Enum value lists ("#0=pending", "#1=running", ...) and Default=
   text.  These render in a dimmed-grey palette by Swagger which
   matches light-mode but disappears against dark-mode surface.  Lift
   to --text-muted so they're readable while still secondary. */
[data-theme="dark"] .swagger-ui .prop-enum,
[data-theme="dark"] .swagger-ui .prop-format,
[data-theme="dark"] .swagger-ui .renderedMarkdown,
[data-theme="dark"] .swagger-ui .property.primitive,
[data-theme="dark"] .swagger-ui .json-schema-2020-12__title,
[data-theme="dark"] .swagger-ui .json-schema-2020-12-keyword__value--secondary,
[data-theme="dark"] .swagger-ui .model .property.primitive,
[data-theme="dark"] .swagger-ui .model .property,
[data-theme="dark"] .swagger-ui .model-deprecated-warning {
  color: var(--text-muted) !important;
}

/* Type-name chips (string / object / array<...>) — these are the
   small lowercase type indicators next to each property.  Default
   palette renders them as faint italic grey that disappears. */
[data-theme="dark"] .swagger-ui .model .property-type,
[data-theme="dark"] .swagger-ui .model-title__text,
[data-theme="dark"] .swagger-ui .prop-type,
[data-theme="dark"] .swagger-ui .json-schema-2020-12__attribute,
[data-theme="dark"] .swagger-ui .json-schema-2020-12__attribute--primary,
[data-theme="dark"] .swagger-ui .json-schema-2020-12__attribute--muted {
  color: var(--accent) !important;
}

/* Header-button surfaces (Authorize, Try it out, Execute, Cancel)
   — when not in their semantic green/red state, give them the
   secondary-button tokens so they read as chips not raised buttons. */
[data-theme="dark"] .swagger-ui .btn {
  background: var(--surface-elev) !important;
  color: var(--text-primary) !important;
  border-color: var(--border-strong) !important;
}
[data-theme="dark"] .swagger-ui .btn:hover {
  background: var(--surface-hover) !important;
}
</style>"""


@router.get("/docs")
async def swagger_ui() -> HTMLResponse:
    """Swagger UI wrapped in the Netcanon nav bar.

    The vanilla `get_swagger_ui_html()` page is post-processed to
    inject:

    1. A theme-detect boot script (sets `<html data-theme>` from
       `localStorage["netcanon.theme.v1"]` + `prefers-color-scheme`).
       Must paint before any CSS applies, so injected right after
       `<body>` open.
    2. Token definitions (`:root` + `[data-theme="dark"]` blocks)
       — Swagger UI page doesn't extend base.html, so we duplicate
       the tokens here.  Stay in sync with base.html.
    3. The Netcanon nav bar (page-nav cluster + spacer + right-rail
       `?` cheatsheet trigger + sun/moon theme toggle).
    4. Nav CSS using `var(--*)` tokens.
    5. A local `toggleTheme()` JS function (base.html's partial isn't
       loaded here).
    6. Swagger UI dark-mode CSS overrides — `[data-theme="dark"]
       .swagger-ui ...` selectors with `!important` to beat the CDN
       stylesheet.

    The `?` cheatsheet button links to `/?show-shortcuts=1` rather
    than opening an inline modal — the docs page has no per-page
    shortcuts of its own, so navigating to a page that actually has
    shortcuts is the right UX.
    """
    base = get_swagger_ui_html(
        openapi_url="/api/v1/openapi.json",
        title="Netcanon — API Docs",
    )
    html = base.body.decode("utf-8")
    # Boot script + tokens go at <body> open so they paint before
    # Swagger UI's bundle initializes.
    html = html.replace(
        "<body>",
        "<body>"
        + _DOCS_BOOT_SCRIPT
        + _DOCS_TOKEN_STYLES
        + _DOCS_NAV_HTML,
        1,
    )
    # CSS + toggle JS go at </body> close so the cascade applies
    # over Swagger UI's CDN stylesheet.
    html = html.replace(
        "</body>",
        _DOCS_NAV_CSS
        + _DOCS_TOGGLE_JS
        + _DOCS_SWAGGER_DARK_CSS
        + "</body>",
        1,
    )
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
