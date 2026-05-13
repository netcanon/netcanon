"""
Integration tests for ``GET /sanitize``.

Phase-3 Round-6 deliverable.  The page-level tests pin the page's
testid surface + nav-link + Swagger-nav additions.  Submit-flow tests
are out of scope here — the existing ``test_sanitize_api.py`` covers
the underlying API; the page just renders + posts FormData.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


# Every testid the sanitize.html template renders synchronously (i.e.
# without waiting for an XHR / form submit).  Counter testids are
# rendered dynamically per category so they're not in this list — the
# audit-row + counter tests live with the API tests.
SYNC_TESTIDS = [
    "sanitize-form",
    "sanitize-source-select",
    "sanitize-input-mode",
    "sanitize-input-mode-raw",
    "sanitize-input-mode-filename",
    "sanitize-raw-wrap",
    "sanitize-raw-input",
    "sanitize-filename-wrap",
    "sanitize-filename-select",
    "sanitize-dry-run-checkbox",
    "sanitize-submit-btn",
    "sanitize-result",
    "sanitize-status-summary",
    "sanitize-stats",
    "sanitize-output-section",
    "sanitize-output",
    "sanitize-copy-btn",
    "sanitize-download-btn",
    "sanitize-audit-section",
    "sanitize-audit-count",
    "sanitize-audit-table",
]


class TestSanitizePageRoute:
    """``GET /sanitize`` returns 200 + the expected page surface."""

    def test_returns_200(self, client):
        resp = client.get("/sanitize")
        assert resp.status_code == 200

    def test_returns_html(self, client):
        resp = client.get("/sanitize")
        ctype = resp.headers.get("content-type", "")
        assert ctype.startswith("text/html")
        assert "<title>Sanitize" in resp.text

    def test_renders_all_required_testids(self, client):
        """Every testid the sanitize.html template renders synchronously
        must be present in the response body.  Catches regressions
        where a template edit accidentally drops a testid + dynamic
        callers (Playwright tests / future automation) silently break."""
        resp = client.get("/sanitize")
        missing = [
            tid for tid in SYNC_TESTIDS
            if 'data-testid="{}"'.format(tid) not in resp.text
        ]
        assert not missing, (
            "missing testids on /sanitize: " + ", ".join(missing)
        )

    def test_includes_source_vendor_select_with_required(self, client):
        """The source-vendor select is required by the API
        (``netcanon.api.routes.sanitize:43``).  The form element must
        carry ``required`` so the browser blocks submit on empty
        selection.  Adapter options are populated client-side via
        ``GET /api/v1/migration/adapters`` — not asserted here."""
        resp = client.get("/sanitize")
        # The select has ``required`` attribute.
        assert (
            'id="san-source"' in resp.text
            and "required" in resp.text.split('id="san-source"')[1].split(">")[0]
        )


class TestSanitizeNavLink:
    """Nav surface — sanitize-tab appears on every page + activates
    when the operator is on /sanitize."""

    def test_nav_link_present_on_dashboard(self, client):
        resp = client.get("/")
        assert 'data-testid="nav-sanitize"' in resp.text
        assert 'href="/sanitize"' in resp.text

    def test_nav_link_active_on_sanitize(self, client):
        resp = client.get("/sanitize")
        # The nav-sanitize anchor carries ``class="active"`` on the
        # sanitize page itself.
        nav_chunk = resp.text.split('data-testid="nav-sanitize"')[1].split(">")[0]
        assert "active" in nav_chunk
        assert 'aria-current="page"' in nav_chunk

    def test_nav_link_not_active_on_other_pages(self, client):
        resp = client.get("/")
        nav_chunk = resp.text.split('data-testid="nav-sanitize"')[1].split(">")[0]
        assert "active" not in nav_chunk

    def test_swagger_nav_includes_sanitize(self, client):
        """The Swagger UI page wraps its own nav (separate from base.html).
        Sanitize must be added there too or the operator on /docs
        loses the link."""
        resp = client.get("/docs")
        assert 'href="/sanitize"' in resp.text
        assert ">Sanitize</a>" in resp.text


class TestStoredConfigDropdown:
    """The stored-config picker is server-rendered from
    ``state.storage.list_configs()`` — confirm it picks up real
    records and shows the filename + device_type label."""

    def test_stored_configs_listed_when_storage_has_records(self, client):
        """Seed two ConfigRecords directly into the file-store + assert
        both filenames appear as ``<option>`` entries in the
        san-filename select.  Bypasses the backup pipeline (no SSH
        mock plumbing needed for a UI test)."""
        from datetime import datetime, timezone

        storage = client.app.state.storage
        storage.save(
            device_type="Cisco",
            host="10.0.0.1",
            timestamp=datetime.now(timezone.utc),
            extension="cfg",
            content="hostname r1\n!",
        )
        storage.save(
            device_type="OPNsense",
            host="10.0.0.2",
            timestamp=datetime.now(timezone.utc),
            extension="xml",
            content="<?xml version='1.0'?>\n<opnsense/>",
        )
        resp = client.get("/sanitize")
        san_chunk = resp.text.split('id="san-filename"')[1].split("</select>")[0]
        # Both seeded device_type labels appear; placeholder + 2 records
        # = at least 3 <option> tags.
        assert "Cisco" in san_chunk
        assert "OPNsense" in san_chunk
        opt_count = san_chunk.count("<option")
        assert opt_count >= 3, (
            "expected placeholder + 2 stored-config options; got " + str(opt_count)
        )

    def test_empty_storage_still_renders_placeholder(self, client):
        """When storage has no records, the select still renders with
        just the placeholder option — never errors out."""
        resp = client.get("/sanitize")
        assert 'id="san-filename"' in resp.text
        # Placeholder always present.
        assert "— pick one —" in resp.text
