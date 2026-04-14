"""
Integration tests for ``/api/v1/backups/`` endpoints.

Key property of TestClient + BackgroundTasks:
FastAPI's ``TestClient`` executes background tasks **synchronously** before
returning the HTTP response.  This means the backup job is always in
``completed`` state by the time the ``POST /api/v1/backups`` response arrives —
no polling or sleep required in tests.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _device_payload(
    type_key: str = "Cisco",
    host: str = "192.168.1.1",
    username: str = "admin",
    password: str = "testpass",
) -> dict:
    return {
        "type_key": type_key,
        "host": host,
        "credentials": {"username": username, "password": password},
    }


def _post_backup(client, devices: list[dict] | None = None) -> dict:
    if devices is None:
        devices = [_device_payload()]
    resp = client.post("/api/v1/backups", json={"devices": devices})
    return resp


def _post_and_get(client, devices: list[dict] | None = None) -> dict:
    """POST a backup job and return the final job state via GET.

    Background tasks run synchronously in TestClient but AFTER the POST
    response body is serialized.  The POST response always shows
    ``status: pending``; a subsequent GET reflects the completed state.
    """
    post_resp = _post_backup(client, devices)
    assert post_resp.status_code == 202
    job_id = post_resp.json()["id"]
    return client.get(f"/api/v1/backups/{job_id}").json()


# ---------------------------------------------------------------------------
# POST /api/v1/backups
# ---------------------------------------------------------------------------


class TestCreateBackup:
    def test_returns_202(self, client):
        resp = _post_backup(client)
        assert resp.status_code == 202

    def test_response_has_job_id(self, client):
        resp = _post_backup(client)
        assert "id" in resp.json()

    def test_post_returns_pending(self, client):
        """POST response is serialised before background tasks run → always pending."""
        resp = _post_backup(client)
        assert resp.json()["status"] == "pending"

    def test_job_completed_after_get(self, client):
        """Background task runs synchronously; GET reflects completed state."""
        job = _post_and_get(client)
        assert job["status"] == "completed"

    def test_total_devices_matches_request(self, client):
        job = _post_and_get(
            client,
            devices=[_device_payload(host="1.1.1.1"), _device_payload(host="2.2.2.2")],
        )
        assert job["total_devices"] == 2

    def test_results_populated(self, client):
        job = _post_and_get(client)
        assert len(job["results"]) == 1

    def test_result_status_success(self, client):
        job = _post_and_get(client)
        assert job["results"][0]["status"] == "success"

    def test_result_has_config_record(self, client):
        job = _post_and_get(client)
        result = job["results"][0]
        assert result["config_record"] is not None
        assert "filename" in result["config_record"]

    def test_result_host_matches_request(self, client):
        job = _post_and_get(client, devices=[_device_payload(host="10.0.0.1")])
        assert job["results"][0]["host"] == "10.0.0.1"

    def test_unknown_type_key_returns_422(self, client):
        resp = _post_backup(client, devices=[_device_payload(type_key="Unknown")])
        assert resp.status_code == 422

    def test_422_detail_mentions_unknown_key(self, client):
        resp = _post_backup(client, devices=[_device_payload(type_key="NOPE")])
        assert "NOPE" in resp.json()["detail"]

    def test_empty_devices_returns_422(self, client):
        resp = client.post("/api/v1/backups", json={"devices": []})
        assert resp.status_code == 422

    def test_multiple_devices_all_backed_up(self, client):
        job = _post_and_get(
            client,
            devices=[
                _device_payload(host="1.1.1.1"),
                _device_payload(host="2.2.2.2"),
                _device_payload(host="3.3.3.3"),
            ],
        )
        assert job["total_devices"] == 3
        assert len(job["results"]) == 3
        assert all(r["status"] == "success" for r in job["results"])

    def test_opnsense_type_key(self, client):
        resp = _post_backup(client, devices=[_device_payload(type_key="OPNsense")])
        assert resp.status_code == 202
        job = _post_and_get(client, devices=[_device_payload(type_key="OPNsense")])
        assert job["status"] == "completed"

    def test_backup_creates_config_file(self, client):
        """After a successful backup, the config appears in GET /api/v1/configs/."""
        _post_and_get(client)
        configs = client.get("/api/v1/configs/").json()
        assert len(configs) >= 1

    def test_completed_at_set_after_completion(self, client):
        job = _post_and_get(client)
        assert job["completed_at"] is not None

    def test_port_field_respected(self, client):
        """Non-default port in request is accepted (FakeCollector ignores it)."""
        device = _device_payload()
        device["port"] = 2222
        resp = _post_backup(client, devices=[device])
        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# GET /api/v1/backups/
# ---------------------------------------------------------------------------


class TestListJobs:
    def test_empty_registry_returns_200(self, client):
        resp = client.get("/api/v1/backups/")
        assert resp.status_code == 200

    def test_empty_registry_returns_empty_list(self, client):
        resp = client.get("/api/v1/backups/")
        assert resp.json() == []

    def test_after_backup_job_listed(self, client):
        _post_backup(client)
        resp = client.get("/api/v1/backups/")
        assert len(resp.json()) == 1

    def test_multiple_jobs_all_listed(self, client):
        _post_backup(client)
        _post_backup(client)
        resp = client.get("/api/v1/backups/")
        assert len(resp.json()) == 2

    def test_list_sorted_newest_first(self, client):
        _post_backup(client)
        _post_backup(client)
        resp = client.get("/api/v1/backups/")
        items = resp.json()
        ts = [item["created_at"] for item in items]
        assert ts == sorted(ts, reverse=True)


# ---------------------------------------------------------------------------
# GET /api/v1/backups/{job_id}
# ---------------------------------------------------------------------------


class TestGetJob:
    def test_get_existing_job_returns_200(self, client):
        job_id = _post_backup(client).json()["id"]
        resp = client.get(f"/api/v1/backups/{job_id}")
        assert resp.status_code == 200

    def test_get_job_returns_correct_id(self, client):
        job_id = _post_backup(client).json()["id"]
        resp = client.get(f"/api/v1/backups/{job_id}")
        assert resp.json()["id"] == job_id

    def test_get_job_status_completed(self, client):
        job_id = _post_backup(client).json()["id"]
        resp = client.get(f"/api/v1/backups/{job_id}")
        assert resp.json()["status"] == "completed"

    def test_get_nonexistent_job_returns_404(self, client):
        resp = client.get("/api/v1/backups/nonexistent-id")
        assert resp.status_code == 404

    def test_404_detail_mentions_job_id(self, client):
        resp = client.get("/api/v1/backups/missing-id-123")
        assert "missing-id-123" in resp.json()["detail"]

    def test_job_has_results(self, client):
        job_id = _post_backup(client).json()["id"]
        resp = client.get(f"/api/v1/backups/{job_id}")
        assert len(resp.json()["results"]) == 1
