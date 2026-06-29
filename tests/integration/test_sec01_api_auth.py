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


def test_openapi_advertises_bearer_when_key_set(client):
    """audit 276eaeb #9: with NETCANON_API_KEY configured, the OpenAPI
    schema declares the ``BearerAuth`` security scheme and applies it to
    every /api/v1 operation, so /docs renders an Authorize button and a
    client can discover the requirement from the schema (require_api_key
    is a plain dependency, invisible to OpenAPI on its own)."""
    client.app.state.settings.api_key = "s3cret"
    schema = client.get("/api/v1/openapi.json").json()

    schemes = schema.get("components", {}).get("securitySchemes", {})
    assert schemes.get("BearerAuth", {}).get("type") == "http"
    assert schemes.get("BearerAuth", {}).get("scheme") == "bearer"

    api_paths = {
        p: item for p, item in schema["paths"].items() if p.startswith("/api/v1")
    }
    assert api_paths, "no /api/v1 paths in the schema"
    for path, item in api_paths.items():
        for op in item.values():
            if isinstance(op, dict):
                assert {"BearerAuth": []} in op.get("security", []), (
                    f"{path} operation does not require BearerAuth in the schema"
                )


def test_openapi_open_when_no_key(client):
    """No key → no security scheme: the schema is honest about the
    zero-config open posture (don't claim auth that isn't enforced)."""
    schema = client.get("/api/v1/openapi.json").json()
    schemes = schema.get("components", {}).get("securitySchemes", {})
    assert "BearerAuth" not in schemes
    for path, item in schema["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for op in item.values():
            if isinstance(op, dict):
                assert "security" not in op, (
                    f"{path} declares security but no key is configured"
                )


def test_ui_routes_are_not_key_gated_by_design(client):
    """DOCUMENTED DECISION (blind-audit 3ec11f3 T0-1), not an oversight: the
    API key gates ``/api/v1`` ONLY — the server-rendered HTML UI stays open
    even when a key is set.  Several UI pages read data server-side, *not*
    through the gated API: the diff view (``/configs/{a}/vs/{b}``) emits full
    config text and ``/configs`` / ``/devices`` list inventory, so the key
    does NOT protect them.  For any non-loopback exposure a reverse proxy that
    authenticates the whole surface is REQUIRED (a native in-app UI
    session/login is intentionally not implemented — it would duplicate the
    proxy).  See SECURITY.md "Known Limitations" (HTML UI not covered by the
    API key) + the README API-key note.

    This pins the behavior so docs and code agree: the audit's finding was
    that the README falsely claimed "the UI's data calls hit /api/v1" — the
    leak was real, but it is an accepted, proxy-mitigated posture, now named
    here and documented rather than silently shipped.
    """
    client.app.state.settings.api_key = "s3cret"
    # No bearer token supplied; UI routes must NOT 401 (they are not gated).
    for path in ("/", "/configs", "/devices"):
        assert client.get(path).status_code != 401, (
            f"{path} is now auth-gated — if intentional, update SECURITY.md "
            f"(HTML UI row) + README, which document the UI as NOT key-gated."
        )
