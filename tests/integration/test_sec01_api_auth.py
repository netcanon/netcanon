"""SEC-01 integration: the API-key gate is actually wired onto /api/v1.

The unit tests prove ``require_api_key`` works in isolation; this proves
the dependency is mounted on the real router set (a forgotten
``dependencies=`` on any include_router would slip past the unit test).
``/health`` and the browser UI stay open; only ``/api/v1`` is gated.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_api_v1_open_when_no_key(client):
    # Default fixture has no api_key → /api/v1 is unauthenticated.
    assert client.get("/api/v1/definitions").status_code == 200


def test_api_v1_gated_when_api_key_set(client):
    client.app.state.settings.api_key = "s3cret"

    # Unauthenticated request to a real /api/v1 route → 401.
    unauth = client.get("/api/v1/definitions")
    assert unauth.status_code == 401
    assert unauth.headers.get("www-authenticate") == "Bearer"

    # Correct bearer token → not blocked by auth.
    ok = client.get(
        "/api/v1/definitions", headers={"Authorization": "Bearer s3cret"}
    )
    assert ok.status_code == 200

    # Wrong token → 401.
    assert (
        client.get(
            "/api/v1/definitions", headers={"Authorization": "Bearer nope"}
        ).status_code
        == 401
    )

    # /health is a conventional probe path and stays open even with a key.
    assert client.get("/health").status_code == 200
