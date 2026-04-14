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
