# RA-12 result — R-12 / CE-01: extract `/docs` Swagger reskin out of `api/routes/ui.py`

- **Finding:** R-12 (CE-01) — `netcanon/api/routes/ui.py` is ~48% the `/docs` Swagger-UI
  dark-mode reskin interleaved with 8 unrelated thin HTML page handlers.
- **Action:** Behavior-preserving extraction of the `/docs` concern into a new
  `netcanon/api/routes/docs.py`. New router registered in `netcanon/main.py` with the
  SAME root prefix (none) so the URL `/docs` is byte-for-byte unchanged.
- **Result file:** `docs/project-review/2026-06-06/remediation-sweep/result-RA-12.md`
- **Confidence:** HIGH. **Blocker:** none.

> NOTE ON PATHS. The task brief writes paths as `api/routes/ui.py` and `main.py`; in this
> repo those live under the `netcanon/` package: `netcanon/api/routes/ui.py` and
> `netcanon/main.py`. All edits below use the real on-disk paths. (`build/lib/netcanon/...`
> is a stale build artifact — do NOT touch it.)

---

## Investigation summary (what moves vs. what stays)

`ui.py` is 895 lines. The `/docs` concern is one contiguous, cleanly-delimited block:

- **Lines 447-449** — `# Swagger UI (custom-wrapped)` section banner.
- **Lines 457-473** — `_DOCS_BOOT_SCRIPT`
- **Lines 482-531** — `_DOCS_TOKEN_STYLES`
- **Lines 542-569** — `_DOCS_NAV_HTML`
- **Lines 576-640** — `_DOCS_NAV_CSS`
- **Lines 648-656** — `_DOCS_TOGGLE_JS`
- **Lines 666-828** — `_DOCS_SWAGGER_DARK_CSS`
- **Lines 831-884** — the `@router.get("/docs")` handler `swagger_ui()`.

**Exact span moved: lines 447 through 884** (the section banner through the close of
`swagger_ui()`). Everything moves as one block.

**Stays in `ui.py`:**
- The module docstring's line about `/docs` (lines 11-12) is left as-is — see "Ambiguity"
  below; it is a comment, behavior-neutral, and trimming it is out of scope for a
  behavior-preserving cut.
- The 8 page handlers: `index` (`/`), `jobs_page` (`/jobs`), `schedules_page`
  (`/schedules`), `configs_page` (`/configs`), `diff_page` (`/configs/{left}/vs/{right}`),
  `devices_page` (`/devices`), `definitions_page` (`/definitions`), `migrate_page`
  (`/migrate`), `sanitize_page` (`/sanitize`).
  (That is 9 `@router.get` HTML routes; the brief's "8 page handlers" counts the diff view
  as part of configs. Either way, all of them stay.)
- Shared helpers used by the page handlers: `_TEMPLATES_DIR`, `_templates`
  (`Jinja2Templates`), `_format_interval` + its `_templates.env.globals` registration.
  **None of these are used by `swagger_ui()`** — the Swagger handler does not touch
  `_templates` at all (it builds HTML from `get_swagger_ui_html()` and string-replaces).
  So no shared template state crosses the cut.
- The trailing NOTE comment (lines 886-895) about the removed shadow `/health` handler —
  unrelated to `/docs`; stays.

**Import analysis (verified by grep over `ui.py`):**

| Import (ui.py line)                | Used by `/docs`? | Used by page handlers? | Disposition |
|------------------------------------|------------------|------------------------|-------------|
| `heapq` (17)                       | no               | yes (`index`)          | stays in ui.py |
| `logging` / `logger` (18, 27)      | no               | no (only the `getLogger` line itself; `logger.` is never called) | stays in ui.py — pre-existing dead import, NOT part of this concern; leave for a separate cleanup |
| `defaultdict` (19)                 | no               | yes (`devices_page`)   | stays in ui.py |
| `Path` (20)                        | no               | yes (`_TEMPLATES_DIR`) | stays in ui.py |
| `APIRouter` (22)                   | yes (its own router) | yes               | stays in ui.py; `docs.py` imports its own |
| `Request` (22)                     | no (handler takes no args) | yes          | stays in ui.py only |
| `get_swagger_ui_html` (23)         | **yes**          | no                     | **moves to docs.py; remove from ui.py** |
| `HTMLResponse` (24)                | yes (return type) | yes (`response_class`)| **shared** — stays in ui.py AND imported in docs.py |
| `Jinja2Templates` (25)             | no               | yes                    | stays in ui.py |

Only `get_swagger_ui_html` becomes unused in `ui.py` after the move. `HTMLResponse` is
used by both, so it stays in both files.

**Cross-module references:** grep confirms the `_DOCS_*` constants and `swagger_ui` are
referenced ONLY inside `ui.py`. No other module imports them, so the move is fully
self-contained. No `__init__.py` re-export to update (`netcanon/api/routes/__init__.py`
is a bare docstring; routers are imported directly in `main.py`).

**Route-path / registration facts:**
- `/docs` is currently served from `ui.router` (`APIRouter(include_in_schema=False)`),
  registered in `main.py:302` as `app.include_router(ui_router.router)` — no prefix, so
  the path is exactly `/docs`.
- FastAPI's built-in docs are disabled: `main.py:232` `docs_url=None`. So this custom
  handler is the SOLE `/docs` route. The split must keep `docs_url=None` and register the
  new router at root with no prefix → `/docs` stays identical.
- The new `docs.py` router is also `APIRouter(include_in_schema=False)` so `/docs` stays
  out of the OpenAPI spec exactly as today.

---

## 1. NEW FILE — full content of `netcanon/api/routes/docs.py`

```python
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
```

> The handler body, all six constants, and the section banner are copied **verbatim** from
> `ui.py` — no logic changes. Only the surrounding module docstring + imports are new.

---

## 2. EDITS to `netcanon/api/routes/ui.py`

### 2a. Remove the now-unused `get_swagger_ui_html` import

`HTMLResponse` MUST remain (it's the `response_class` on the page handlers). Only the
Swagger import is dropped.

**OLD (lines 22-25):**
```python
from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
```

**NEW:**
```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
```

### 2b. Update the module docstring (optional, behavior-neutral — recommended for accuracy)

The docstring currently claims the Swagger wrapper lives here. After the move that is
false. Editing a docstring is behavior-preserving. **If the orchestrator wants the minimal
possible diff, this edit may be SKIPPED** (it is a comment only). Recommended replacement:

**OLD (lines 11-12):**
```python
The Swagger UI wrapper at ``/docs`` is also here because it's a
rendered HTML page even though it wraps an API surface.
```

**NEW:**
```python
The Swagger UI wrapper at ``/docs`` lives in the sibling
``docs`` module (it's a rendered HTML page even though it wraps an
API surface).
```

### 2c. Delete the entire `/docs` block — section banner through end of `swagger_ui()`

Remove **lines 447 through 884 inclusive** (the `# Swagger UI (custom-wrapped)` banner,
all six `_DOCS_*` constants, and the `swagger_ui()` handler). The blank lines that
preceded the banner (445-446) and the blank lines (885-886) before the trailing NOTE
comment collapse to the standard two-blank-line separation.

Because the block is large, anchor the deletion on its unique first and last lines:

- **First line to delete (447):**
  ```python
  # ---------------------------------------------------------------------------
  # Swagger UI (custom-wrapped)
  # ---------------------------------------------------------------------------
  ```
- **Last line to delete (884):**
  ```python
      return HTMLResponse(content=html)
  ```

**What immediately follows the deleted block and STAYS** (was lines 887-895 — the
unrelated `/health` NOTE comment):
```python
# NOTE: A second ``/health`` handler used to live here returning per-
# resource counts (definitions / schedules / profiles / jobs).  It was
# dead code — ``health_router`` is registered first in ``main.py``
# (see ``app.include_router(health_router.router)``) so its minimal
# ``{"status":"ok","version":...}`` handler always won.  Removed in R8
# along with the registry refactor; if operators want per-resource
# counts in the future, add them as a separate ``/diagnostics``
# endpoint rather than reviving the shadow.
```

After 2c, the last real route in `ui.py` is `sanitize_page` (ends at old line 444);
two blank lines, then the `/health` NOTE comment is the file's tail. `sanitize_page` is
unchanged.

> Implementation note for the orchestrator: the cleanest mechanical way to apply 2c is to
> delete from the start of the `# ----... / # Swagger UI (custom-wrapped) / # ----...`
> banner up to and including the `return HTMLResponse(content=html)` line, leaving the two
> blank lines that separated `sanitize_page` from the banner as the separator before the
> `# NOTE:` comment. Net: `ui.py` drops from 895 → ~455 lines.

---

## 3. EDIT to `netcanon/main.py` — register the new `docs` router

### 3a. Add the import (alongside the other `from .api.routes import ...` lines)

**OLD (lines 33-41):**
```python
from .api.routes import backups as backups_router
from .api.routes import configs as configs_router
from .api.routes import definitions as defs_router
from .api.routes import device_profiles as device_profiles_router
from .api.routes import health as health_router
from .api.routes import migration as migration_router
from .api.routes import sanitize as sanitize_router
from .api.routes import schedules as schedules_router
from .api.routes import ui as ui_router
```

**NEW:**
```python
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
```

### 3b. Register it at root (no prefix) so `/docs` is unchanged

Add the registration next to the `ui_router` line. Order vs. the `/api/v1` routers does
not matter (no path collision: `/docs` is unique, `docs_url=None` keeps FastAPI from
claiming it). Placing it right before `ui_router` keeps the two root-mounted UI-ish
routers together.

**OLD (line 302):**
```python
    app.include_router(ui_router.router)  # UI routes at root (/, /jobs, …)
```

**NEW:**
```python
    app.include_router(docs_router.router)  # custom Swagger UI at /docs (no prefix)
    app.include_router(ui_router.router)  # UI routes at root (/, /jobs, …)
```

> `docs_url=None` on `main.py:232` is UNCHANGED — must stay `None` or FastAPI re-adds its
> own `/docs` and collides with ours. No other line in `main.py` changes.

---

## 4. Test plan

### 4a. Existing coverage — ALREADY GREEN, route-location-agnostic

`tests/integration/test_swagger_docs_page.py` (24 test methods across 5 classes) is the
primary safety net. **Every test hits `client.get("/docs")`** and asserts on response body
substrings — none of them import from `netcanon.api.routes.ui` or reference the module at
all. So they pass unchanged after the split as long as `/docs` resolves to the identical
body. They assert, among others:
- `status_code == 200`, boot script + `netcanon.theme.v1`, all `--*` tokens,
  `[data-theme="dark"]`,
- every nav `data-testid`/`href` pair (`nav-api-docs` → `/docs` with `class="active"`),
  spacer ordering, theme-toggle + `function toggleTheme(`,
- Swagger dark overrides, `!important` count ≥ 20, try-it-out inputs,
- `id="swagger-ui"`, `swagger-ui-bundle.js`, `/api/v1/openapi.json`.

The `client` fixture: `tests/integration/conftest.py::client` wraps `test_app`
(root `tests/conftest.py`, built via `create_app(test_settings)`) in a `TestClient`
context manager.

**Run after applying the edits (must stay green, zero changes to the test file):**
```
py -m pytest tests/integration/test_swagger_docs_page.py -q
```

### 4b. New import-smoke (add to the suite, or run ad-hoc to confirm the split imports)

```python
def test_docs_module_imports_and_exposes_router():
    """docs.py imports cleanly and exposes an include_in_schema=False router
    carrying exactly the /docs GET route."""
    from fastapi import APIRouter
    from netcanon.api.routes import docs as docs_router

    assert isinstance(docs_router.router, APIRouter)
    paths = {r.path for r in docs_router.router.routes}
    assert paths == {"/docs"}
    # The constants moved off ui.py and onto docs.py.
    assert hasattr(docs_router, "_DOCS_SWAGGER_DARK_CSS")

    # ...and are GONE from ui.py (no accidental duplicate definition).
    from netcanon.api.routes import ui as ui_router
    assert not hasattr(ui_router, "_DOCS_SWAGGER_DARK_CSS")
    assert not hasattr(ui_router, "swagger_ui")
```

### 4c. New route-exists check — `/docs` resolves AND all 8/9 UI pages still resolve

```python
import pytest

@pytest.mark.parametrize("path", [
    "/", "/jobs", "/schedules", "/configs", "/devices",
    "/definitions", "/migrate", "/sanitize",   # the UI page handlers (stay in ui.py)
    "/docs",                                    # the extracted Swagger page (now docs.py)
])
def test_root_pages_resolve(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
```

(The diff view `/configs/{left}/vs/{right}` needs stored fixtures to exercise meaningfully;
it is unchanged by this split, so it's out of scope for the smoke parametrize. The existing
`tests/integration/` diff-page tests, if any, cover it.)

### 4d. Regression sanity — nothing else moved

```
py -m pytest tests/integration -q
```
Confirms the UI page handlers (which still live in `ui.py` and still use the shared
`_templates`/`_format_interval`) are unaffected.

---

## 5. Risk assessment

- **Behavior-preserving:** YES. The handler body + all six constants are byte-identical
  copies; only their module home changes. `/docs` URL, `include_in_schema=False`, and
  `docs_url=None` are all preserved, so the route, its OpenAPI-exclusion, and its rendered
  HTML are unchanged.
- **Shared-helper trap (the named risk):** checked and clear. `swagger_ui()` does NOT use
  `_templates`, `_format_interval`, `_TEMPLATES_DIR`, `heapq`, `defaultdict`, or `Request`
  — so none of the shared template state or page-handler imports get dragged into `docs.py`
  by accident. The only import that crosses is `get_swagger_ui_html` (moves) and
  `HTMLResponse` (legitimately duplicated — used by both files).
- **Module-level state moved by accident:** none. The `_templates` singleton +
  `_templates.env.globals["format_interval"]` registration stay in `ui.py`. `docs.py` has
  no module-level state beyond its own `router` + the string constants.
- **Import-order / circular-import:** none. `docs.py` imports only from `fastapi`; `main.py`
  imports `docs_router` exactly like its siblings. No cross-import between `ui.py` and
  `docs.py`.
- **`HTMLResponse` still needed in `ui.py`:** YES — every page handler declares
  `response_class=HTMLResponse`. Do NOT remove it from `ui.py` (only `get_swagger_ui_html`
  is removed there). This is the single easiest mistake to make on this diff.
- **Stale `build/lib/netcanon/...` copy:** there is a parallel `build/lib/...` tree. It is a
  packaging artifact and is NOT imported at runtime (runtime uses the `netcanon/` package).
  Leave it untouched.
- **Pre-existing dead `logger` in `ui.py`:** `logging`/`logger` were already unused before
  this change (grep shows only the `getLogger` definition line). I deliberately did NOT
  touch them — that's an orthogonal cleanup, not part of the `/docs` extraction, and
  removing it would widen the diff beyond "behavior-preserving move". Flag for a separate
  lint pass if desired.

---

## 6. Self-assessment & ambiguity

- **Confidence: HIGH.** The `/docs` concern is a single contiguous, self-contained block
  with exactly one external import to relocate (`get_swagger_ui_html`) and one shared
  import to keep in both places (`HTMLResponse`). No shared template state crosses the cut.
  A dedicated 24-method integration test already pins the `/docs` contract and is fully
  agnostic to which module serves the route, giving a strong behavior-preserving guarantee.
- **Exact cut line:** lines **447-884** of `ui.py` (section banner through
  `return HTMLResponse(content=html)`). Unambiguous — the section banner above and the
  unrelated `/health` NOTE comment below bracket it cleanly.
- **Ambiguity 1 — module docstring (edit 2b):** the `ui.py` docstring asserts the Swagger
  wrapper "is also here." Post-move that's stale. I provided a corrected docstring but
  marked it OPTIONAL/SKIPPABLE since it's comment-only and the brief emphasizes a minimal
  behavior-preserving cut. Orchestrator's call.
- **Ambiguity 2 — "8 page handlers":** the brief says 8; I count 9 `@router.get` HTML
  routes (the diff view `/configs/{left}/vs/{right}` is arguably the 9th, or folds into
  "configs"). Immaterial to the split — all of them stay in `ui.py` either way.
- **Ambiguity 3 — registration order:** I placed `docs_router` immediately before
  `ui_router`. Order is behavior-neutral here (no path collision; `docs_url=None`), but
  grouping the two root-mounted routers reads best.
- **Blocker: none.**
