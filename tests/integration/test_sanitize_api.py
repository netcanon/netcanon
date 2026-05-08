"""Integration tests for ``POST /api/v1/sanitize``.

Verifies the HTTP endpoint behaves identically to the CLI invocation
(both call into the same shared library at :mod:`netcanon.tools.sanitize`).

The endpoint is the recommended invocation for Docker / running-server
operators — ``curl -F`` against a deployed instance avoids any
``docker exec`` gymnastics.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from netcanon.main import create_app

pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parents[2]
ARUBA_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "real" / "aruba_aoss"
    / "hpe_community_2920_wb1608_dhcp_snooping.cfg"
)


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestSanitizeEndpoint:
    def test_default_returns_sanitized_text(self, client):
        with open(ARUBA_FIXTURE, "rb") as f:
            response = client.post(
                "/api/v1/sanitize",
                data={"source_vendor": "aruba_aoss"},
                files={"config": ("test.cfg", f, "text/plain")},
            )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        body = response.text
        assert body  # non-empty rendered output
        # Original hostname should not survive
        assert "SW-1OG-01" not in body

    def test_dry_run_returns_json_audit(self, client):
        with open(ARUBA_FIXTURE, "rb") as f:
            response = client.post(
                "/api/v1/sanitize",
                data={"source_vendor": "aruba_aoss", "dry_run": "true"},
                files={"config": ("test.cfg", f, "text/plain")},
            )
        assert response.status_code == 200
        body = response.json()
        assert "substitutions" in body
        assert "total" in body
        assert body["total"] >= 1
        # Each substitution has the expected shape
        for sub in body["substitutions"]:
            assert {"category", "field", "original", "redacted"} <= set(sub.keys())

    def test_substitution_count_header_set(self, client):
        with open(ARUBA_FIXTURE, "rb") as f:
            response = client.post(
                "/api/v1/sanitize",
                data={"source_vendor": "aruba_aoss"},
                files={"config": ("test.cfg", f, "text/plain")},
            )
        assert response.status_code == 200
        assert "X-Netcanon-Substitution-Count" in response.headers
        count = int(response.headers["X-Netcanon-Substitution-Count"])
        assert count >= 1


class TestSanitizeEndpointErrors:
    def test_unknown_source_vendor_returns_400(self, client):
        response = client.post(
            "/api/v1/sanitize",
            data={"source_vendor": "no_such_vendor"},
            files={"config": ("test.cfg", b"hostname x\n", "text/plain")},
        )
        assert response.status_code == 400
        assert "Unknown source_vendor" in response.json()["detail"]

    def test_missing_source_vendor_returns_422(self, client):
        # FastAPI's required-form validation kicks in
        response = client.post(
            "/api/v1/sanitize",
            files={"config": ("test.cfg", b"hostname x\n", "text/plain")},
        )
        assert response.status_code == 422

    def test_missing_config_file_returns_422(self, client):
        response = client.post(
            "/api/v1/sanitize",
            data={"source_vendor": "aruba_aoss"},
        )
        assert response.status_code == 422


class TestSanitizeEndpointConsistency:
    """The HTTP endpoint must produce the same result as direct
    library invocation — both flow through ``sanitize_text``."""

    def test_dry_run_audit_matches_library(self, client):
        from netcanon.tools.sanitize import sanitize_text

        raw = ARUBA_FIXTURE.read_text(encoding="utf-8")
        lib_result = sanitize_text(raw, "aruba_aoss", dry_run=True)

        with open(ARUBA_FIXTURE, "rb") as f:
            response = client.post(
                "/api/v1/sanitize",
                data={"source_vendor": "aruba_aoss", "dry_run": "true"},
                files={"config": ("test.cfg", f, "text/plain")},
            )
        api_result = response.json()

        assert api_result["total"] == len(lib_result.substitutions)
