"""Integration tests for ``GET /health`` — the readiness probe.

The endpoint is what Docker ``HEALTHCHECK`` directives + container
orchestrators (Kubernetes liveness / readiness probes, load-balancer
health configurations) call against the running server.  These tests
pin its contract:

1. Returns 200 on a vanilla GET.
2. Returns the static-shape JSON `{"status": "ok", "version": "..."}`.
3. Sets `application/json` Content-Type.
4. Doesn't require auth / query args / body.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from netcanon.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    return TestClient(create_app())


class TestHealthEndpoint:
    def test_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_response_shape(self, client):
        response = client.get("/health")
        body = response.json()
        assert body["status"] == "ok"
        assert "version" in body

    def test_returns_json_content_type(self, client):
        response = client.get("/health")
        assert response.headers["content-type"].startswith("application/json")

    def test_no_query_args_required(self, client):
        # Health probes shouldn't need any auth, query params, or body.
        # Standard probes do GET / no body / no auth.
        response = client.get("/health")
        assert response.status_code == 200

    def test_version_is_a_string(self, client):
        # Whether installed or editable, the version field must be a str
        # (importlib.metadata.version() returns str; we fall back to
        # "unknown" for non-installed source trees).
        response = client.get("/health")
        body = response.json()
        assert isinstance(body["version"], str)
        assert body["version"]  # non-empty
