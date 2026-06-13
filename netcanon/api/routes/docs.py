"""
Custom-wrapped Swagger UI ``/docs`` page.

FastAPI's built-in docs are disabled in the application factory
(``FastAPI(docs_url=None)``); this module serves a replacement at the
same ``/docs`` path that wraps ``get_swagger_ui_html()`` in the
Netcanon nav bar + dark-mode theme.  It's a rendered HTML page even
though it wraps an API surface, which is why it lives next to the UI
routes rather than under ``/api/v1``.

Split out of ``netcanon.api.routes.ui`` (which was ~48% this one
concern) so the 8 thin HTML page handlers and this large CSS/JS
reskin each have a grep-friendly home.  Registered on its own
``APIRouter(include_in_schema=False)`` at root (no prefix) in
``main.py`` so the public URL ``/docs`` is unchanged.

The ``_DOCS_*`` token/CSS/JS constants below duplicate base.html's
theme tokens because the Swagger UI page does NOT extend base.html.
Keep them in sync with ``templates/base.html`` — drift here means
``/docs`` renders different colours than the rest of the app.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)


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
