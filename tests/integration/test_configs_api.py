"""
Integration tests for ``/api/v1/configs/`` endpoints.

Tests cover the full config lifecycle:
list (empty) → backup creates a file → list (populated) → get content → delete.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from netconfig.storage.file_store import FileConfigStore

pytestmark = pytest.mark.integration


def _seed_config(client, host: str = "192.168.1.1") -> str:
    """Run a backup job and return the saved filename.

    Background tasks run synchronously in TestClient but AFTER the POST
    response body is serialised (so POST always returns ``status: pending``).
    We GET the job immediately after to read the completed state.
    """
    post_resp = client.post(
        "/api/v1/backups",
        json={
            "devices": [
                {
                    "type_key": "Cisco",
                    "host": host,
                    "credentials": {
                        "username": "admin",
                        "password": "testpass",
                    },
                }
            ]
        },
    )
    assert post_resp.status_code == 202
    job_id = post_resp.json()["id"]
    job = client.get(f"/api/v1/backups/{job_id}").json()
    assert job["status"] == "completed", f"Expected completed, got {job['status']}"
    result = job["results"][0]
    assert result["status"] == "success"
    return result["config_record"]["filename"]


class TestListConfigs:
    def test_empty_store_returns_200(self, client):
        resp = client.get("/api/v1/configs/")
        assert resp.status_code == 200

    def test_empty_store_returns_empty_list(self, client):
        resp = client.get("/api/v1/configs/")
        assert resp.json() == []

    def test_after_backup_config_appears(self, client):
        _seed_config(client)
        resp = client.get("/api/v1/configs/")
        assert len(resp.json()) == 1

    def test_config_metadata_fields(self, client):
        _seed_config(client)
        resp = client.get("/api/v1/configs/")
        cfg = resp.json()[0]
        assert cfg["device_type"] == "Cisco"
        assert cfg["host"] == "192.168.1.1"
        assert "filename" in cfg
        assert "size_bytes" in cfg
        assert "timestamp" in cfg

    def test_multiple_backups_all_listed(self, client):
        _seed_config(client, "1.1.1.1")
        _seed_config(client, "2.2.2.2")
        resp = client.get("/api/v1/configs/")
        assert len(resp.json()) == 2

    def test_list_sorted_newest_first(self, client):
        _seed_config(client, "1.1.1.1")
        _seed_config(client, "2.2.2.2")
        resp = client.get("/api/v1/configs/")
        items = resp.json()
        ts = [item["timestamp"] for item in items]
        assert ts == sorted(ts, reverse=True)


class TestGetConfig:
    def test_get_existing_config_returns_200(self, client):
        filename = _seed_config(client)
        resp = client.get(f"/api/v1/configs/{filename}")
        assert resp.status_code == 200

    def test_get_existing_config_returns_text(self, client):
        filename = _seed_config(client)
        resp = client.get(f"/api/v1/configs/{filename}")
        # FakeCollector returns CISCO_FAKE_OUTPUT
        assert "hostname" in resp.text or "version" in resp.text

    def test_get_nonexistent_config_returns_404(self, client):
        resp = client.get("/api/v1/configs/nonexistent.cfg")
        assert resp.status_code == 404

    def test_get_404_detail_mentions_filename(self, client):
        resp = client.get("/api/v1/configs/ghost.cfg")
        assert "ghost.cfg" in resp.json()["detail"]


class TestDeleteConfig:
    def test_delete_returns_204(self, client):
        filename = _seed_config(client)
        resp = client.delete(f"/api/v1/configs/{filename}")
        assert resp.status_code == 204

    def test_delete_removes_from_list(self, client):
        filename = _seed_config(client)
        client.delete(f"/api/v1/configs/{filename}")
        resp = client.get("/api/v1/configs/")
        assert resp.json() == []

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/v1/configs/ghost.cfg")
        assert resp.status_code == 404

    def test_delete_then_get_returns_404(self, client):
        filename = _seed_config(client)
        client.delete(f"/api/v1/configs/{filename}")
        resp = client.get(f"/api/v1/configs/{filename}")
        assert resp.status_code == 404

    def test_delete_only_removes_target(self, client):
        fn1 = _seed_config(client, "1.1.1.1")
        _seed_config(client, "2.2.2.2")
        client.delete(f"/api/v1/configs/{fn1}")
        remaining = client.get("/api/v1/configs/").json()
        assert len(remaining) == 1
        assert remaining[0]["host"] == "2.2.2.2"
