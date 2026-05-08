"""
Integration tests for the X-Request-ID correlation middleware.

Phase 9 of the logging-audit plan.  The middleware wraps every HTTP
request, generates (or honours) a short correlation id, stores it in
a :class:`contextvars.ContextVar`, and echoes it on the response.
Every log record emitted *during* the request picks up the same id
via the ``RequestIdFilter`` installed by ``configure_logging``.

These tests validate the API-observable contract:

1. Every response carries an ``X-Request-ID`` header.
2. IDs are unique per request.
3. A client-supplied inbound ``X-Request-ID`` (printable, reasonable
   length) is honoured verbatim so upstream proxies + trace systems
   can stitch their own correlation.
4. Garbage inbound ids (too short, too long, non-printable) are
   rejected and replaced with a generated id — defensive against
   header injection or truncation by buggy proxies.
5. Request-scoped log records pick up the correct id.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


class TestResponseHeaderPresence:
    def test_every_response_has_x_request_id(self, client: TestClient):
        resp = client.get("/api/v1/migration/adapters")
        assert resp.status_code == 200
        assert "x-request-id" in {k.lower() for k in resp.headers}

    def test_id_is_nonempty(self, client: TestClient):
        resp = client.get("/api/v1/migration/adapters")
        assert resp.headers["X-Request-ID"]

    def test_distinct_requests_get_distinct_ids(
        self, client: TestClient,
    ):
        ids = {
            client.get("/api/v1/migration/adapters").headers["X-Request-ID"]
            for _ in range(5)
        }
        assert len(ids) == 5, f"expected 5 distinct ids, got {ids}"


class TestInboundHeaderPassthrough:
    def test_inbound_id_is_echoed(self, client: TestClient):
        inbound = "trace-abc-12345"
        resp = client.get(
            "/api/v1/migration/adapters",
            headers={"X-Request-ID": inbound},
        )
        assert resp.headers["X-Request-ID"] == inbound

    def test_inbound_uuid_hex_is_echoed(self, client: TestClient):
        """Full 32-char UUID hex — at the upper length bound."""
        inbound = "a" * 32
        resp = client.get(
            "/api/v1/migration/adapters",
            headers={"X-Request-ID": inbound},
        )
        assert resp.headers["X-Request-ID"] == inbound

    def test_too_short_inbound_id_is_replaced(self, client: TestClient):
        """7 chars — below the 8-char minimum.  Middleware falls back
        to a generated id."""
        inbound = "tooshor"
        resp = client.get(
            "/api/v1/migration/adapters",
            headers={"X-Request-ID": inbound},
        )
        assert resp.headers["X-Request-ID"] != inbound

    def test_too_long_inbound_id_is_replaced(self, client: TestClient):
        """37 chars — above the 36-char max (standard UUID length)."""
        inbound = "x" * 37
        resp = client.get(
            "/api/v1/migration/adapters",
            headers={"X-Request-ID": inbound},
        )
        assert resp.headers["X-Request-ID"] != inbound

    def test_inbound_with_space_is_replaced(self, client: TestClient):
        """Non-alphanumeric / non-dash / non-underscore chars
        rejected.  Prevents header injection of newlines or
        formatting-destroying characters."""
        inbound = "bad id with spaces"
        resp = client.get(
            "/api/v1/migration/adapters",
            headers={"X-Request-ID": inbound},
        )
        assert resp.headers["X-Request-ID"] != inbound

    def test_inbound_with_control_char_is_replaced(
        self, client: TestClient,
    ):
        inbound = "abc\ndef-injected"
        resp = client.get(
            "/api/v1/migration/adapters",
            headers={"X-Request-ID": inbound},
        )
        assert resp.headers["X-Request-ID"] != inbound


class TestLogRecordCorrelation:
    """End-to-end proof that the correlation id flows from the
    middleware through the contextvar into log records emitted by
    route handlers mid-request."""

    def test_log_record_carries_inbound_request_id(
        self, client: TestClient, caplog,
    ):
        """Caplog sees the log record.  The record's ``request_id``
        attribute (set by the filter) should match the inbound id."""
        from netcanon.logging_config import RequestIdFilter
        # Caplog's handler doesn't have RequestIdFilter by default
        # (pytest owns it).  Install the filter on caplog's handler
        # so the attribute injection happens on captured records.
        caplog.handler.addFilter(RequestIdFilter())
        inbound = "itest-0001"
        with caplog.at_level(
            "INFO", logger="netcanon.api.routes.migration",
        ):
            client.get(
                "/api/v1/migration/adapters",
                headers={"X-Request-ID": inbound},
            )
        # The /adapters route logs nothing — switch to /plan which
        # does emit an INFO line with the job id.  Use a minimal
        # body that reaches the logger.info() call.
        with caplog.at_level(
            "INFO", logger="netcanon.api.routes.migration",
        ):
            resp = client.post(
                "/api/v1/migration/plan",
                headers={"X-Request-ID": inbound},
                json={
                    "source": "mock",
                    "target": "mock",
                    "raw_text": "{}",
                },
            )
        assert resp.status_code == 200
        assert resp.headers["X-Request-ID"] == inbound
        # Find the route's own INFO log.
        plan_records = [
            r for r in caplog.records
            if r.name == "netcanon.api.routes.migration"
            and r.levelname == "INFO"
        ]
        assert plan_records, (
            "expected an INFO record from the migration route; "
            "got: " + ", ".join(
                f"{r.name}/{r.levelname}" for r in caplog.records
            )
        )
        # At least one of those records should carry the inbound id.
        correlated = [
            r for r in plan_records
            if getattr(r, "request_id", None) == inbound
        ]
        assert correlated, (
            f"no INFO record carried request_id={inbound!r}; "
            "contextvar did not thread through the middleware"
        )

    def test_generated_id_is_8_chars_hex(self, client: TestClient):
        """Default generated id is a UUID4 hex prefix (8 chars,
        lowercase hex).  Short enough to fit the log column
        without breaking alignment."""
        resp = client.get("/api/v1/migration/adapters")
        req_id = resp.headers["X-Request-ID"]
        assert len(req_id) == 8
        assert all(c in "0123456789abcdef" for c in req_id)
