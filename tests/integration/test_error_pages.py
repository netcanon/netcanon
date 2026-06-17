"""
Integration tests for the themed 404/500 error pages (UX review MF-5).

A mistyped URL or an uncaught server error must keep a *browser* user
inside the nav-wrapped themed shell (``error.html``) instead of dropping
them onto a raw JSON body — while the API surface and programmatic
clients keep their ``{"detail": ...}`` JSON contract untouched.

The browser-vs-JSON branch is driven by ``ui._wants_html``:
``Accept: text/html`` on a non-``/api/`` path → HTML page; everything
else (``*/*``, ``application/json``, or any ``/api/`` path) → JSON.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

_HTML = {"accept": "text/html"}


class TestNotFoundPage:
    """``404`` — unmatched routes."""

    def test_browser_404_renders_themed_html(self, client):
        resp = client.get("/this-page-does-not-exist", headers=_HTML)
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("text/html")
        body = resp.text
        # Extends base.html → the nav shell is present.
        assert 'data-testid="nav-home"' in body
        assert 'data-testid="error-page"' in body
        assert 'data-testid="error-home-link"' in body
        assert "404" in body
        # Never renders the raw JSON detail body to a browser.
        assert '{"detail"' not in body

    def test_api_style_404_keeps_json(self, client):
        # Default Accept (*/*) — programmatic clients keep the JSON contract.
        resp = client.get("/this-page-does-not-exist")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json() == {"detail": "Not Found"}

    def test_api_path_404_is_json_even_for_browser(self, client):
        # An /api/ path stays JSON even when the client accepts HTML —
        # the API namespace is a machine contract, not a browseable page.
        resp = client.get("/api/v1/this-endpoint-does-not-exist", headers=_HTML)
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")


class TestServerErrorPage:
    """``500`` — uncaught exceptions (never echo the exception detail)."""

    def test_browser_500_renders_themed_html(self, test_app):
        @test_app.get("/__boom_html__", include_in_schema=False)
        async def _boom():  # pragma: no cover - body never returns
            raise RuntimeError("kaboom-secret-detail")

        with TestClient(test_app, raise_server_exceptions=False) as c:
            resp = c.get("/__boom_html__", headers=_HTML)
        assert resp.status_code == 500
        assert resp.headers["content-type"].startswith("text/html")
        body = resp.text
        assert 'data-testid="error-page"' in body
        assert "500" in body
        # The exception type/message must not leak to the client.
        assert "kaboom-secret-detail" not in body
        assert "RuntimeError" not in body

    def test_api_style_500_keeps_json(self, test_app):
        @test_app.get("/__boom_json__", include_in_schema=False)
        async def _boom():  # pragma: no cover - body never returns
            raise RuntimeError("kaboom-secret-detail")

        with TestClient(test_app, raise_server_exceptions=False) as c:
            resp = c.get("/__boom_json__")  # default Accept: */*
        assert resp.status_code == 500
        assert resp.json() == {"detail": "Internal Server Error"}
        assert "kaboom-secret-detail" not in resp.text
