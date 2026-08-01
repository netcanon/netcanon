"""Explanatory bodies for requests the warden refuses.

The route allowlist (``constants.ALLOW_*``) is deliberately tiny: the demo ships
the translator and nothing else. But netcanon's own nav still links Dashboard,
Devices, Configs, Definitions, Jobs, Schedules and API Docs, and every one of
them was answering with a bare ``Response(status_code=404)`` — a blank white
page inside the iframe, which reads as "this product is broken" rather than
"this part isn't in the demo".

Only the warden can tell the two refusals apart: a lapsed session and a route
that was never exposed are different things and deserve different copy. That is
why this lives here rather than in a Caddy error handler.

Kept out of ``app.py`` because that file is held to an audited 500-line budget
(whitepaper claim: the TCB is small enough to read end to end). Static markup is
not TCB logic; the one function here is four lines and does no I/O.
"""

from __future__ import annotations

from fastapi import Request, Response
from fastapi.responses import HTMLResponse

# Inline everything: the demo page claims no third-party requests, and a 404
# body that pulled a webfont would quietly make that false.
_SHELL = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — netcanon demo</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    margin: 0; min-height: 100vh; display: grid; place-items: center;
    font: 15px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: Canvas; color: CanvasText; padding: 2rem;
  }}
  main {{ max-width: 34rem; text-align: left; }}
  h1 {{ font-size: 1.35rem; margin: 0 0 .75rem; letter-spacing: -.01em; }}
  p {{ margin: 0 0 .9rem; opacity: .85; }}
  code {{
    font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    background: color-mix(in srgb, CanvasText 8%, Canvas); padding: .15em .4em; border-radius: 4px;
  }}
  pre {{
    background: color-mix(in srgb, CanvasText 8%, Canvas); padding: .7rem .9rem;
    border-radius: 6px; overflow-x: auto; margin: 0 0 .9rem;
  }}
  pre code {{ background: none; padding: 0; }}
  a {{ color: inherit; }}
  .muted {{ opacity: .6; font-size: .9em; }}
</style>
<main>{body}</main>
"""

_NOT_IN_DEMO_BODY = """
<h1>That part isn't in the demo</h1>
<p>The public demo exposes the translator only — <strong>Migrate</strong> and
<strong>Sanitize</strong>. Devices, Configs, Definitions, Jobs and Schedules all
need persistent storage and real device credentials, so the demo refuses them at
the proxy instead of showing you a hollow version of the page.</p>
<p>Nothing broke and nothing was stored. This route simply isn't routed.</p>
<p><a href="migrate">← Back to Migrate</a></p>
<p class="muted">Want the whole application? It's the same image, one command,
no sign-up:</p>
<pre><code>docker run --rm -p 8000:8000 -e NETCANON_ALLOW_INSECURE_BIND=1 ghcr.io/netcanon/netcanon</code></pre>
<p class="muted">amd64/x86-64 image; the flag acknowledges a local unauthenticated bind.</p>
"""

_SESSION_GONE_BODY = """
<h1>This demo session has ended</h1>
<p>Instances self-destruct on a hard timer, and everything they held goes with
them — that's the point of the demo, not a fault.</p>
<p><a href="/" target="_top">Start a fresh instance →</a></p>
<pre><code>docker run --rm -p 8000:8000 -e NETCANON_ALLOW_INSECURE_BIND=1 ghcr.io/netcanon/netcanon</code></pre>
<p class="muted">amd64/x86-64 image; the flag acknowledges a local unauthenticated bind.</p>
"""

NOT_IN_DEMO = _SHELL.format(title="Not in the demo", body=_NOT_IN_DEMO_BODY)
SESSION_GONE = _SHELL.format(title="Session ended", body=_SESSION_GONE_BODY)


def refuse(request: Request, html: str) -> Response:
    """404 with an explanation for a browser navigation, bare 404 for anything else.

    The status stays 404 either way — the route genuinely does not exist here, and
    dressing a refusal up as a 200 would lie to caches and crawlers. Only the body
    changes, and only when the client actually asked for HTML: netcanon's own
    fetch/XHR calls must keep getting an empty 404 rather than a page to parse.
    """
    if "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(html, status_code=404)
    return Response(status_code=404)
