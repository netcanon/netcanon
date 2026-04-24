"""
Integration tests for UI routes (``/jobs``, ``/schedules``) and job
persistence behaviour.

Covers:
- HTTP 200 and text/html content-type for both UI pages.
- Correct ``data-testid`` sentinel elements in empty and populated states.
- JSON job files written to disk after a backup completes.
- Jobs survive a simulated server restart (second ``create_app`` reads same dirs).
- Manual backup jobs carry ``schedule_id=None`` / ``schedule_name=None``.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from netconfig.main import create_app
from tests.conftest import CISCO_FAKE_OUTPUT, FakeCollector

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_CISCO_DEVICE = {
    "type_key": "Cisco",
    "host": "192.168.1.1",
    "credentials": {"username": "admin", "password": "pw"},
}

_BACKUP_PAYLOAD = {"devices": [_CISCO_DEVICE]}

_SCHEDULE_PAYLOAD = {
    "name": "Test Schedule",
    "interval_minutes": 60,
    "target_type_keys": ["Cisco"],
}


def _post_backup(client: TestClient) -> dict:
    """POST a backup and return the parsed JSON response body."""
    resp = client.post("/api/v1/backups", json=_BACKUP_PAYLOAD)
    assert resp.status_code == 202
    return resp.json()


def _post_and_get_job(client: TestClient) -> dict:
    """POST a backup then GET the completed job state."""
    job_id = _post_backup(client)["id"]
    resp = client.get(f"/api/v1/backups/{job_id}")
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# TestJobsUIRoute
# ---------------------------------------------------------------------------


class TestJobsUIRoute:
    def test_get_returns_200(self, client: TestClient) -> None:
        resp = client.get("/jobs")
        assert resp.status_code == 200

    def test_response_content_type_is_html(self, client: TestClient) -> None:
        resp = client.get("/jobs")
        assert "text/html" in resp.headers["content-type"]

    def test_empty_state_contains_no_jobs_msg(self, client: TestClient) -> None:
        resp = client.get("/jobs")
        assert 'data-testid="no-jobs-msg"' in resp.text

    def test_after_backup_contains_job_card(self, client: TestClient) -> None:
        _post_backup(client)
        resp = client.get("/jobs")
        assert 'data-testid="job-card"' in resp.text

    def test_after_backup_no_jobs_msg_absent(self, client: TestClient) -> None:
        _post_backup(client)
        resp = client.get("/jobs")
        assert 'data-testid="no-jobs-msg"' not in resp.text


# ---------------------------------------------------------------------------
# TestSchedulesUIRoute
# ---------------------------------------------------------------------------


class TestSchedulesUIRoute:
    def test_get_returns_200(self, client: TestClient) -> None:
        resp = client.get("/schedules")
        assert resp.status_code == 200

    def test_response_content_type_is_html(self, client: TestClient) -> None:
        resp = client.get("/schedules")
        assert "text/html" in resp.headers["content-type"]

    def test_empty_state_contains_no_schedules_msg(self, client: TestClient) -> None:
        resp = client.get("/schedules")
        assert 'data-testid="no-schedules-msg"' in resp.text

    def test_schedule_form_always_present(self, client: TestClient) -> None:
        resp = client.get("/schedules")
        assert 'data-testid="schedule-form"' in resp.text

    def test_after_create_schedule_contains_schedule_row(
        self, client: TestClient
    ) -> None:
        resp = client.post("/api/v1/schedules/", json=_SCHEDULE_PAYLOAD)
        assert resp.status_code == 201
        page = client.get("/schedules")
        assert 'data-testid="schedule-row"' in page.text


# ---------------------------------------------------------------------------
# TestJobPersistence
# ---------------------------------------------------------------------------


class TestJobPersistence:
    def test_job_file_written_to_disk(self, test_settings) -> None:
        """After a completed backup the job JSON file exists on disk."""
        fake = FakeCollector(output=CISCO_FAKE_OUTPUT)
        with patch(
            "netconfig.api.routes.backups.get_collector", return_value=fake
        ):
            app = create_app(test_settings)
            with TestClient(app, raise_server_exceptions=True) as c:
                job = _post_and_get_job(c)
                job_id = job["id"]

        jobs_dir = test_settings.configs_dir.parent / "jobs"
        job_file = jobs_dir / f"{job_id}.json"
        assert job_file.exists(), f"Expected job file at {job_file}"

    def test_job_survives_restart(self, test_settings) -> None:
        """Jobs loaded on startup survive a simulated server restart."""
        fake = FakeCollector(output=CISCO_FAKE_OUTPUT)
        with patch(
            "netconfig.api.routes.backups.get_collector", return_value=fake
        ):
            app1 = create_app(test_settings)
            with TestClient(app1, raise_server_exceptions=True) as c1:
                job_id = _post_backup(c1)["id"]
            # c1 is closed here; app1 lifespan torn down

            # Simulate restart: fresh app pointing at the same directories
            app2 = create_app(test_settings)
            with TestClient(app2, raise_server_exceptions=True) as c2:
                resp = c2.get(f"/api/v1/backups/{job_id}")
                assert resp.status_code == 200
                assert resp.json()["id"] == job_id

    def test_persisted_job_has_no_schedule_id(self, test_settings) -> None:
        """A manually triggered job has ``schedule_id=None`` after reload."""
        fake = FakeCollector(output=CISCO_FAKE_OUTPUT)
        with patch(
            "netconfig.api.routes.backups.get_collector", return_value=fake
        ):
            app1 = create_app(test_settings)
            with TestClient(app1, raise_server_exceptions=True) as c1:
                job_id = _post_backup(c1)["id"]

            app2 = create_app(test_settings)
            with TestClient(app2, raise_server_exceptions=True) as c2:
                job = c2.get(f"/api/v1/backups/{job_id}").json()
                assert job["schedule_id"] is None

    def test_persisted_job_has_no_schedule_name(self, test_settings) -> None:
        """A manually triggered job has ``schedule_name=None`` after reload."""
        fake = FakeCollector(output=CISCO_FAKE_OUTPUT)
        with patch(
            "netconfig.api.routes.backups.get_collector", return_value=fake
        ):
            app1 = create_app(test_settings)
            with TestClient(app1, raise_server_exceptions=True) as c1:
                job_id = _post_backup(c1)["id"]

            app2 = create_app(test_settings)
            with TestClient(app2, raise_server_exceptions=True) as c2:
                job = c2.get(f"/api/v1/backups/{job_id}").json()
                assert job["schedule_name"] is None


# ---------------------------------------------------------------------------
# TestJobScheduleFields
# ---------------------------------------------------------------------------


class TestJobScheduleFields:
    def test_manual_backup_schedule_id_is_none(self, client: TestClient) -> None:
        """POST /api/v1/backups sets schedule_id=None on the completed job."""
        job = _post_and_get_job(client)
        assert job["schedule_id"] is None

    def test_manual_backup_schedule_name_is_none(self, client: TestClient) -> None:
        """POST /api/v1/backups sets schedule_name=None on the completed job."""
        job = _post_and_get_job(client)
        assert job["schedule_name"] is None


# ---------------------------------------------------------------------------
# TestThemeToggleRendered — server-side sanity that the dark-mode
# toggle button + boot script render on every page.  Cheaper than
# Playwright; catches template regressions before e2e runs.
# ---------------------------------------------------------------------------


class TestThemeToggleRendered:
    """Dark-mode wiring is in base.html, so EVERY page that extends
    it should carry:

    * ``<html data-theme="light">`` default on the root element
      (boot script overrides on the client before CSS paints).
    * Inline boot script reading ``localStorage`` + prefers-color-
      scheme.
    * The ``nav-theme-toggle`` button with sun + moon glyphs.
    * The theme-toggle partial inclusion.

    Sample the dashboard + jobs + configs pages — if one extends
    base.html differently, this catches it.
    """

    _PAGES = ["/", "/jobs", "/schedules", "/configs", "/definitions"]

    def test_html_has_data_theme_attribute(self, client: TestClient) -> None:
        for path in self._PAGES:
            resp = client.get(path)
            assert resp.status_code == 200, path
            assert 'data-theme="light"' in resp.text, (
                f"{path} missing default data-theme on <html>"
            )

    def test_boot_script_present(self, client: TestClient) -> None:
        """FOUC-prevention: the boot script MUST be inline in <head>
        (not an external <script src>) so it runs synchronously
        before CSS parses."""
        resp = client.get("/")
        assert "netconfig.theme.v1" in resp.text
        assert "prefers-color-scheme" in resp.text
        # Boot script references documentElement (not body/DOM) —
        # required so the attribute is set before the body renders.
        assert "document.documentElement.setAttribute" in resp.text

    def test_nav_theme_toggle_button_present(
        self, client: TestClient,
    ) -> None:
        for path in self._PAGES:
            resp = client.get(path)
            assert 'data-testid="nav-theme-toggle"' in resp.text, (
                f"{path} missing nav-theme-toggle"
            )

    def test_sun_and_moon_glyphs_both_present(
        self, client: TestClient,
    ) -> None:
        """The glyph swap happens via CSS, not DOM mutation — both
        spans are in the markup, one hidden by the data-theme
        selector rules."""
        resp = client.get("/")
        # Sun (U+2600) + moon (U+263D) — HTML entities, mixed case
        # tolerated (the template uses lowercase hex).
        assert "&#x263D;" in resp.text or "&#x263d;" in resp.text
        assert "&#x2600;" in resp.text

    def test_toggle_partial_included(self, client: TestClient) -> None:
        """``_partials/theme-toggle.js`` inclusion means
        ``toggleTheme`` + aria-label updater both reach the page."""
        resp = client.get("/")
        assert "function toggleTheme()" in resp.text
        assert "_updateThemeToggleAriaLabel" in resp.text

    def test_css_variables_declared(self, client: TestClient) -> None:
        """Dark-mode CSS tokens must be present (regression guard
        against someone accidentally removing the :root or
        [data-theme=\"dark\"] block)."""
        resp = client.get("/")
        assert "--page-bg:" in resp.text
        assert '[data-theme="dark"]' in resp.text
        # Spot-check a few tokens; no need to enumerate all.
        assert "--surface:" in resp.text
        assert "--text-primary:" in resp.text
        assert "--nav-bg:" in resp.text
