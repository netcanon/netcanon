"""
Integration tests for ``/api/v1/schedules/`` endpoints.

The ``client`` fixture (from ``tests/integration/conftest.py``) wraps
``TestClient`` in a context manager so the full app lifespan runs, which
means APScheduler is started and stopped around each test.  This lets us
verify APScheduler job registration and removal alongside the HTTP
behaviour.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _schedule_payload(
    name: str = "Test schedule",
    interval_minutes: int = 1440,
    target_type_keys: list[str] | None = None,
) -> dict:
    if target_type_keys is None:
        target_type_keys = ["Cisco"]
    return {
        "name": name,
        "interval_minutes": interval_minutes,
        "target_type_keys": target_type_keys,
    }


def _post_schedule(client, payload: dict | None = None):
    if payload is None:
        payload = _schedule_payload()
    return client.post("/api/v1/schedules/", json=payload)


def _create_schedule(client, payload: dict | None = None) -> dict:
    """POST a schedule and return the response body (asserts 201)."""
    resp = _post_schedule(client, payload)
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# GET /api/v1/schedules/
# ---------------------------------------------------------------------------


class TestListSchedules:
    def test_returns_200(self, client):
        resp = client.get("/api/v1/schedules/")
        assert resp.status_code == 200

    def test_empty_list_when_no_schedules_exist(self, client):
        resp = client.get("/api/v1/schedules/")
        assert resp.json() == []

    def test_returns_one_schedule_after_creation(self, client):
        _create_schedule(client)
        resp = client.get("/api/v1/schedules/")
        assert len(resp.json()) == 1

    def test_returns_multiple_schedules_after_multiple_creations(self, client):
        _create_schedule(client, _schedule_payload(name="Alpha"))
        _create_schedule(client, _schedule_payload(name="Beta"))
        _create_schedule(client, _schedule_payload(name="Gamma"))
        resp = client.get("/api/v1/schedules/")
        assert len(resp.json()) == 3

    def test_results_sorted_newest_first(self, client):
        _create_schedule(client, _schedule_payload(name="First"))
        _create_schedule(client, _schedule_payload(name="Second"))
        resp = client.get("/api/v1/schedules/")
        items = resp.json()
        timestamps = [item["created_at"] for item in items]
        assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# POST /api/v1/schedules/
# ---------------------------------------------------------------------------


class TestCreateSchedule:
    def test_returns_201(self, client):
        resp = _post_schedule(client)
        assert resp.status_code == 201

    def test_response_contains_id_field(self, client):
        body = _create_schedule(client)
        assert "id" in body

    def test_response_name_matches_request(self, client):
        body = _create_schedule(client, _schedule_payload(name="My Schedule"))
        assert body["name"] == "My Schedule"

    def test_response_interval_minutes_matches_request(self, client):
        body = _create_schedule(client, _schedule_payload(interval_minutes=60))
        assert body["interval_minutes"] == 60

    def test_enabled_is_true_in_response(self, client):
        body = _create_schedule(client)
        assert body["enabled"] is True

    def test_next_run_at_is_populated(self, client):
        """APScheduler sets next_run_time immediately on job registration."""
        body = _create_schedule(client)
        assert body["next_run_at"] is not None

    def test_created_at_is_populated(self, client):
        body = _create_schedule(client)
        assert body["created_at"] is not None

    def test_apscheduler_job_registered_after_creation(self, client):
        """The APScheduler job should exist immediately after creation."""
        body = _create_schedule(client)
        schedule_id = body["id"]
        job = client.app.state.scheduler.get_job(schedule_id)
        assert job is not None

    def test_invalid_interval_minutes_zero_returns_422(self, client):
        resp = _post_schedule(client, _schedule_payload(interval_minutes=0))
        assert resp.status_code == 422

    def test_missing_name_returns_422(self, client):
        payload = _schedule_payload()
        del payload["name"]
        resp = _post_schedule(client, payload)
        assert resp.status_code == 422

    def test_no_targets_returns_422(self, client):
        resp = _post_schedule(
            client,
            {"name": "Test", "interval_minutes": 1440, "target_type_keys": [], "target_device_ids": []},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/v1/schedules/{id}
# ---------------------------------------------------------------------------


class TestDeleteSchedule:
    def test_delete_returns_204(self, client):
        schedule_id = _create_schedule(client)["id"]
        resp = client.delete(f"/api/v1/schedules/{schedule_id}")
        assert resp.status_code == 204

    def test_deleted_schedule_absent_from_list(self, client):
        schedule_id = _create_schedule(client)["id"]
        client.delete(f"/api/v1/schedules/{schedule_id}")
        items = client.get("/api/v1/schedules/").json()
        ids = [item["id"] for item in items]
        assert schedule_id not in ids

    def test_delete_nonexistent_id_returns_404(self, client):
        resp = client.delete("/api/v1/schedules/nonexistent-id")
        assert resp.status_code == 404

    def test_404_detail_mentions_schedule_id(self, client):
        resp = client.delete("/api/v1/schedules/missing-id-abc")
        assert "missing-id-abc" in resp.json()["detail"]

    def test_apscheduler_job_removed_after_deletion(self, client):
        """After deletion the APScheduler job should no longer exist."""
        schedule_id = _create_schedule(client)["id"]
        client.delete(f"/api/v1/schedules/{schedule_id}")
        job = client.app.state.scheduler.get_job(schedule_id)
        assert job is None


# ---------------------------------------------------------------------------
# POST /api/v1/schedules/{id}/toggle
# ---------------------------------------------------------------------------


class TestToggleSchedule:
    def test_toggle_enabled_schedule_returns_200(self, client):
        schedule_id = _create_schedule(client)["id"]
        resp = client.post(f"/api/v1/schedules/{schedule_id}/toggle")
        assert resp.status_code == 200

    def test_toggle_enabled_schedule_sets_enabled_false(self, client):
        schedule_id = _create_schedule(client)["id"]
        body = client.post(f"/api/v1/schedules/{schedule_id}/toggle").json()
        assert body["enabled"] is False

    def test_next_run_at_is_none_after_disabling(self, client):
        schedule_id = _create_schedule(client)["id"]
        body = client.post(f"/api/v1/schedules/{schedule_id}/toggle").json()
        assert body["next_run_at"] is None

    def test_toggle_disabled_schedule_re_enables_it(self, client):
        schedule_id = _create_schedule(client)["id"]
        # First toggle: disable
        client.post(f"/api/v1/schedules/{schedule_id}/toggle")
        # Second toggle: re-enable
        body = client.post(f"/api/v1/schedules/{schedule_id}/toggle").json()
        assert body["enabled"] is True

    def test_next_run_at_set_after_re_enabling(self, client):
        schedule_id = _create_schedule(client)["id"]
        # First toggle: disable
        client.post(f"/api/v1/schedules/{schedule_id}/toggle")
        # Second toggle: re-enable
        body = client.post(f"/api/v1/schedules/{schedule_id}/toggle").json()
        assert body["next_run_at"] is not None

    def test_toggle_nonexistent_id_returns_404(self, client):
        resp = client.post("/api/v1/schedules/nonexistent-id/toggle")
        assert resp.status_code == 404
