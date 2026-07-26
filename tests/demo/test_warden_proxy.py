"""Proxy behaviour: header rewriting, the route allowlist, and idle accounting.

Three separable concerns, all pure enough to test without a daemon:

* **Header rewriting** — netcanon stamps ``X-Frame-Options: DENY`` and CSP
  ``frame-ancestors 'none'`` on every response. Unless the warden strips and
  rewrites those, the demo iframe renders blank. This is the one piece of the
  chain whose failure mode is a *silently* broken demo.
* **The route allowlist** — feature-surface reduction (module 04). Default-deny:
  the backup dashboard, devices, configs and `/docs` must be unreachable through
  the warden even though the instance still serves them.
* **Idle accounting** — which requests count as "work" decides whether an active
  visitor is reclaimed at 600 s, so the set is asserted explicitly.

Live-stack counterpart: that the *instance* really returns those headers, and
that a blocked route 404s end-to-end through Caddy — `deploy/VERIFY.md` proof 9
and module 08's allowlist rows.
"""

from __future__ import annotations

import json

import httpx
import pytest

from demo.warden import app as warden_app
from demo.warden import constants as C

pytestmark = pytest.mark.unit


# ── Response-header rewriting (claim 2 / VERIFY.md proof 9) ──────────────────
def headers_to_dict(pairs: list[tuple[str, str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, value in pairs:
        out.setdefault(key.lower(), []).append(value)
    return out


def test_x_frame_options_is_stripped():
    fixed = warden_app._fix_response_headers(
        httpx.Headers([("x-frame-options", "DENY"), ("content-type", "text/html")])
    )
    result = headers_to_dict(fixed)
    assert "x-frame-options" not in result, "the iframe would render blank"
    assert result["content-type"] == ["text/html"]


def test_csp_frame_ancestors_none_is_rewritten_to_self():
    original = "default-src 'self'; frame-ancestors 'none'; object-src 'none'"
    fixed = warden_app._fix_response_headers(
        httpx.Headers([("content-security-policy", original)])
    )
    csp = headers_to_dict(fixed)["content-security-policy"][0]

    assert "frame-ancestors 'self'" in csp
    assert "frame-ancestors 'none'" not in csp
    # every other directive must survive untouched
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp


def test_csp_rewrite_is_case_insensitive():
    fixed = warden_app._fix_response_headers(
        httpx.Headers([("Content-Security-Policy", "FRAME-ANCESTORS 'NONE'")])
    )
    csp = headers_to_dict(fixed)["content-security-policy"][0]
    assert "frame-ancestors 'self'" in csp.lower()


def test_hop_by_hop_headers_are_dropped():
    fixed = warden_app._fix_response_headers(
        httpx.Headers([
            ("connection", "keep-alive"),
            ("transfer-encoding", "chunked"),
            ("keep-alive", "timeout=5"),
            ("content-type", "application/json"),
        ])
    )
    result = headers_to_dict(fixed)
    for banned in ("connection", "transfer-encoding", "keep-alive"):
        assert banned not in result
    assert result["content-type"] == ["application/json"]


def test_duplicate_headers_are_preserved():
    """A dict() collapse here would silently drop one of the instance's cookies
    (or one CSP header), so multi-value headers must survive the rewrite."""
    fixed = warden_app._fix_response_headers(
        httpx.Headers([("set-cookie", "a=1"), ("set-cookie", "b=2")])
    )
    assert sorted(headers_to_dict(fixed)["set-cookie"]) == ["a=1", "b=2"]


def test_a_response_without_csp_or_xfo_passes_through():
    fixed = warden_app._fix_response_headers(
        httpx.Headers([("content-type", "text/plain"), ("etag", '"abc"')])
    )
    result = headers_to_dict(fixed)
    assert result["content-type"] == ["text/plain"]
    assert result["etag"] == ['"abc"']


# ── Route allowlist (module 04 feature-surface reduction) ────────────────────
@pytest.mark.parametrize("path", sorted(C.ALLOW_GET_EXACT))
def test_allowlisted_gets_are_permitted(path):
    assert C.route_allowed("GET", path) is True


@pytest.mark.parametrize("path", sorted(C.ALLOW_POST_EXACT))
def test_allowlisted_posts_are_permitted(path):
    assert C.route_allowed("POST", path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/",  # the backup DASHBOARD, not migrate — must never be reachable
        "/api/v1/backups",
        "/api/v1/devices",
        "/api/v1/configs",
        "/api/v1/schedules",
        "/api/v1/definitions",
        "/docs",
        "/jobs",
        "/schedules",
        "/devices",
        "/configs",
        "/definitions",
        "/openapi.json",
    ],
)
def test_blocked_surfaces_are_denied_for_both_methods(path):
    assert C.route_allowed("GET", path) is False
    assert C.route_allowed("POST", path) is False


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE"])
def test_only_get_and_post_are_ever_allowed(method):
    assert C.route_allowed(method, "/migrate") is False
    assert C.route_allowed(method, "/api/v1/migration/plan") is False


def test_capability_prefixes_are_allowed_but_not_open_ended():
    assert C.route_allowed("GET", "/api/v1/migration/adapters/cisco_iosxe_cli/capabilities")
    assert C.route_allowed("GET", "/api/v1/migration/target-profiles/juniper/ex4300")
    # a sibling path that merely starts similarly must not slip through
    assert C.route_allowed("GET", "/api/v1/migration/adapters-secret") is False


def test_render_is_deliberately_not_allowlisted():
    """POST /api/v1/migration/render is excluded on purpose (module 04)."""
    assert C.route_allowed("POST", "/api/v1/migration/render") is False


def test_get_prefix_rules_do_not_leak_to_post():
    assert C.route_allowed("POST", "/api/v1/migration/adapters/x/capabilities") is False


# ── Refusals have to explain themselves ─────────────────────────────────────
# netcanon's own nav links Dashboard, Devices, Configs, Definitions, Jobs,
# Schedules and API Docs. None are allowlisted, so all seven answered with a
# bare `Response(status_code=404)` — a blank white page inside the iframe, which
# reads as "this product is broken" rather than "this part isn't in the demo".
BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


async def test_a_blocked_nav_route_explains_itself_to_a_browser(warden, make_request):
    await warden.fill_pool()
    token = json.loads((await warden.mint()).body)["token"]

    response = await warden.app.iframe_route(
        token, "devices", make_request(method="GET", accept=BROWSER_ACCEPT)
    )
    assert response.status_code == 404, "still a 404 — the route genuinely is not here"
    body = response.body.decode()
    assert "isn't in the demo" in body
    assert 'href="migrate"' in body, "relative, so it resolves under /i/{token}/ AND /"


async def test_a_blocked_api_call_still_gets_an_empty_404(warden, make_request):
    """netcanon's own fetch/XHR must keep getting nothing to parse."""
    await warden.fill_pool()
    token = json.loads((await warden.mint()).body)["token"]

    response = await warden.app.iframe_route(
        token, "api/v1/backups", make_request(method="GET", accept="application/json")
    )
    assert response.status_code == 404
    assert response.body == b""


async def test_a_dead_token_says_session_ended_not_route_missing(warden, make_request):
    """Only the warden can tell the two refusals apart; it should say which."""
    response = await warden.app.iframe_route(
        "not-a-real-token", "migrate", make_request(method="GET", accept=BROWSER_ACCEPT)
    )
    assert response.status_code == 404
    assert "session has ended" in response.body.decode()


def test_the_refusal_pages_are_self_contained():
    """Claim 10 promises no third-party requests from the demo. A 404 body that
    pulled a webfont or a CDN script would quietly make that false."""
    from demo.warden import pages

    for html in (pages.NOT_IN_DEMO, pages.SESSION_GONE):
        assert "http://" not in html and "https://" not in html
        assert "<script" not in html.lower()


# ── Routing 404s (dead token / blocked path) ────────────────────────────────
async def test_iframe_route_404s_on_an_unknown_token(warden, make_request):
    response = await warden.app.iframe_route(
        "not-a-real-token", "migrate", make_request(method="GET")
    )
    assert response.status_code == 404


async def test_iframe_route_404s_on_the_bare_instance_root(warden, make_request):
    """`/i/{t}/` maps to the instance's backup dashboard — the allowlist must
    cover the `{path}` component exactly as it does absolute paths."""
    await warden.fill_pool()
    token = json.loads((await warden.mint()).body)["token"]

    response = await warden.app.iframe_route(token, "", make_request(method="GET"))
    assert response.status_code == 404


async def test_iframe_route_404s_on_a_blocked_api_path(warden, make_request):
    await warden.fill_pool()
    token = json.loads((await warden.mint()).body)["token"]

    response = await warden.app.iframe_route(
        token, "api/v1/backups", make_request(method="GET")
    )
    assert response.status_code == 404


async def test_iframe_route_404s_after_the_deadline_passes(warden, make_request):
    """Belt to the reaper's braces: an expired session must not be proxied even
    if the reaper has not ticked yet."""
    await warden.fill_pool()
    token = json.loads((await warden.mint()).body)["token"]
    warden.clock.advance(C.HARD_TTL + 1)  # no tick: session still in the map

    assert token in warden.active
    response = await warden.app.iframe_route(token, "migrate", make_request(method="GET"))
    assert response.status_code == 404


async def test_cookie_route_404s_without_a_routing_cookie(warden, make_request):
    response = await warden.app.cookie_route("migrate", make_request(method="GET"))
    assert response.status_code == 404


async def test_cookie_route_404s_on_a_dead_cookie(warden, make_request):
    """VERIFY.md proof 5: after session A is destroyed, A's cookie 404s."""
    await warden.fill_pool()
    token = json.loads((await warden.mint()).body)["token"]
    await warden.app._destroy(token, "end")

    response = await warden.app.cookie_route(
        "migrate", make_request(method="GET", cookie=token)
    )
    assert response.status_code == 404


# ── Idle accounting ─────────────────────────────────────────────────────────
async def test_allowlisted_post_refreshes_activity(warden):
    await warden.fill_pool()
    token = json.loads((await warden.mint()).body)["token"]
    session = warden.active[token]
    warden.clock.advance(120)

    warden.app._refresh_activity(session, "POST", "/api/v1/migration/plan")

    assert session.last_activity == warden.clock.monotonic()
    assert session.last_heartbeat == warden.clock.monotonic()


async def test_a_get_refreshes_the_heartbeat_but_not_activity(warden):
    """Browsing must not hold a session open — only real translation work does."""
    await warden.fill_pool()
    token = json.loads((await warden.mint()).body)["token"]
    session = warden.active[token]
    original_activity = session.last_activity
    warden.clock.advance(120)

    warden.app._refresh_activity(session, "GET", "/migrate")

    assert session.last_heartbeat == warden.clock.monotonic()
    assert session.last_activity == original_activity


async def test_render_post_does_not_refresh_activity(warden):
    await warden.fill_pool()
    token = json.loads((await warden.mint()).body)["token"]
    session = warden.active[token]
    original_activity = session.last_activity
    warden.clock.advance(120)

    warden.app._refresh_activity(session, "POST", "/api/v1/migration/render")

    assert session.last_activity == original_activity


def test_idle_resetting_set_matches_the_post_allowlist():
    """If a new translate route is added, it must be a deliberate decision
    whether it counts as activity — this pins the two sets together."""
    assert C.IDLE_RESETTING == C.ALLOW_POST_EXACT


# ── Client-IP extraction (the per-IP cap depends on it) ──────────────────────
def test_client_ip_uses_the_first_forwarded_hop(make_request):
    """Behind Caddy, request.client.host is Caddy — using it would collapse the
    per-IP cap into a single global cap of 2 for the whole internet."""
    request = make_request()
    request.headers = {"x-forwarded-for": "203.0.113.9, 10.0.0.1, 172.16.0.1"}
    assert warden_app._client_ip(request) == "203.0.113.9"


def test_client_ip_falls_back_when_no_forwarded_header(make_request):
    request = make_request()
    request.headers = {}
    assert warden_app._client_ip(request) == "?"
