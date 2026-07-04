"""SEC-9: Content-Security-Policy header contract.

The security-headers middleware sets a strict same-origin CSP on every
response, plus a scoped variant on ``/docs`` that additionally permits the
Swagger UI CDN (jsDelivr) + the FastAPI favicon host — because the custom
docs page wraps ``get_swagger_ui_html()``, which loads its bundle from
that CDN.  Verified live in the browser during the fix (zero violations
across every UI page; ``/docs`` renders the full Swagger UI); these tests
pin the contract so a future edit can't silently drop the header or
loosen the default policy.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from netcanon.main import _CSP_DEFAULT, _CSP_DOCS

pytestmark = pytest.mark.integration


class TestContentSecurityPolicy:
    def test_ui_page_gets_strict_default_csp(self, test_app):
        """A UI page carries the strict default CSP + the sibling
        hardening headers."""
        with TestClient(test_app) as c:
            r = c.get("/")
        assert r.status_code == 200
        assert r.headers["content-security-policy"] == _CSP_DEFAULT
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"

    def test_json_api_also_carries_csp(self, test_app):
        """The header is set on every response, JSON included."""
        with TestClient(test_app) as c:
            r = c.get("/health")
        assert r.headers["content-security-policy"] == _CSP_DEFAULT

    def test_docs_gets_cdn_permitting_variant(self, test_app):
        """/docs gets the variant that allows the Swagger UI CDN — the
        strict default would blank the page.  The CDN allowance is the
        *only* difference between the two policies, so a distinct docs
        policy is exactly the guarantee that /docs can load Swagger."""
        with TestClient(test_app) as c:
            r = c.get("/docs")
        assert r.status_code == 200
        assert r.headers["content-security-policy"] == _CSP_DOCS
        assert _CSP_DOCS != _CSP_DEFAULT

    def test_default_policy_is_same_origin_only(self):
        """Guard the strict contract: the default policy allows no
        off-origin host and keeps the real hardening directives.  A
        regression that pastes a CDN into the default (rather than the
        /docs variant) fails here."""
        assert "cdn.jsdelivr.net" not in _CSP_DEFAULT
        assert "http://" not in _CSP_DEFAULT
        assert "https://" not in _CSP_DEFAULT
        for directive in (
            "default-src 'self'",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ):
            assert directive in _CSP_DEFAULT
