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

    def test_get_omits_legacy_inline_device_credentials(self, client):
        """SEC-1 (2026-07-03 review): a legacy inline-device schedule must
        not echo the device password / enable_password over the read API.

        Inline devices can't be created via ``POST`` (``ScheduleCreate``
        accepts only target lists), so inject one straight into the registry
        the route reads — the same shape a pre-profile schedule loads from
        disk — and assert the serialised response is credential-free.
        """
        from netcanon.models.schedule import BackupSchedule, ScheduleDevice

        sched = BackupSchedule(
            name="legacy inline",
            interval_minutes=60,
            devices=[
                ScheduleDevice(
                    type_key="Cisco", host="10.0.0.1", port=22,
                    username="admin", password="PLAINTEXT-PW-XYZ",
                    enable_password="ENABLE-PW-XYZ",
                )
            ],
        )
        client.app.state.schedules[sched.id] = sched

        resp = client.get("/api/v1/schedules/")
        assert resp.status_code == 200
        # Neither secret may appear anywhere in the serialised response.
        assert "PLAINTEXT-PW-XYZ" not in resp.text
        assert "ENABLE-PW-XYZ" not in resp.text
        item = next(s for s in resp.json() if s["id"] == sched.id)
        assert item["devices"][0]["username"] == "admin"  # non-secret survives
        assert "password" not in item["devices"][0]
        assert "enable_password" not in item["devices"][0]


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


# ---------------------------------------------------------------------------
# CONC-2: delete-during-run must not resurrect the schedule
# ---------------------------------------------------------------------------


class TestScheduleDeleteResurrection:
    """A schedule deleted DURING its run must not be resurrected by the run's
    post-completion ``save`` (2026-07-03 review, CONC-2).

    ``_run_scheduled_backup_inner`` captures the schedule, awaits a
    minutes-long ``run_backup_job``, then persists ``last_run_at`` /
    ``next_run_at``.  If the operator deletes the schedule in that window, the
    (formerly unconditional) save rewrote the deleted JSON and resurrected it
    on the next startup reload.  The fix re-checks membership under
    ``SCHEDULE_REGISTRY_LOCK`` before saving.

    The run is driven directly (not via APScheduler) with ``run_backup_job``
    monkeypatched, so the delete lands deterministically mid-run.
    """

    @staticmethod
    def _cisco_profile(app):
        from netcanon.models.device_profile import DeviceProfile

        profile = DeviceProfile(
            name="sw", type_key="Cisco", host="10.0.0.1", port=22,
            username="admin", password="pw",
        )
        # A resolvable target so the coroutine reaches run_backup_job + the
        # post-run save (an empty target set short-circuits before both).
        app.state.device_profiles[profile.id] = profile
        return profile

    async def test_delete_during_run_is_not_resurrected(
        self, client, monkeypatch,
    ):
        from pathlib import Path

        from netcanon.api.routes.schedules import _run_scheduled_backup_inner
        from netcanon.services import backup_runner

        app = client.app
        self._cisco_profile(app)
        sid = _create_schedule(client)["id"]
        store_dir = Path(app.state.schedule_store._dir)
        assert (store_dir / f"{sid}.json").exists()

        # The awaited backup simulates the operator deleting the schedule
        # mid-run (registry + disk), exactly as the delete route does.
        def _delete_mid_run(*args, **kwargs):
            app.state.schedules.pop(sid, None)
            app.state.schedule_store.delete(sid)

        monkeypatch.setattr(backup_runner, "run_backup_job", _delete_mid_run)
        await _run_scheduled_backup_inner(sid, app)

        assert sid not in app.state.schedules
        assert not (store_dir / f"{sid}.json").exists(), (
            "deleted schedule was resurrected on disk by the post-run save"
        )

    async def test_normal_run_still_persists(self, client, monkeypatch):
        """Negative control: when NOT deleted, the post-run save still runs."""
        from pathlib import Path

        from netcanon.api.routes.schedules import _run_scheduled_backup_inner
        from netcanon.services import backup_runner

        app = client.app
        self._cisco_profile(app)
        sid = _create_schedule(client)["id"]

        monkeypatch.setattr(
            backup_runner, "run_backup_job", lambda *a, **k: None,
        )
        await _run_scheduled_backup_inner(sid, app)

        assert sid in app.state.schedules
        assert app.state.schedules[sid].last_run_at is not None
        assert (Path(app.state.schedule_store._dir) / f"{sid}.json").exists()


class TestScheduledJobCreationPersist:
    """(#26) A scheduled job must be persisted to disk at creation, mirroring
    backups.py's CONC-5 save — else an LRU-evicted scheduled job (or every run
    under max_memory_jobs=0) 404s while genuinely running."""

    @staticmethod
    def _cisco_profile(app):
        from netcanon.models.device_profile import DeviceProfile

        profile = DeviceProfile(
            name="sw", type_key="Cisco", host="10.0.0.1", port=22,
            username="admin", password="pw",
        )
        app.state.device_profiles[profile.id] = profile
        return profile

    async def test_scheduled_job_persisted_at_creation(
        self, client, monkeypatch,
    ):
        from netcanon.api.routes.schedules import _run_scheduled_backup_inner
        from netcanon.services import backup_runner

        app = client.app
        self._cisco_profile(app)
        sid = _create_schedule(client)["id"]

        captured: list = []

        def _capture(job, *a, **k):
            # Capture the job WITHOUT saving — the creation-time persist is then
            # the only disk write, isolating the #26 fix from the terminal save.
            captured.append(job)

        monkeypatch.setattr(backup_runner, "run_backup_job", _capture)
        await _run_scheduled_backup_inner(sid, app)

        assert captured, "runner never dispatched (no resolvable target?)"
        job = captured[0]
        # #26: on disk from the creation-time persist even though the stubbed
        # runner wrote nothing.  Pre-fix the scheduled path never saved -> None.
        assert app.state.job_store.load_one(job.id) is not None

    async def test_scheduled_backup_passes_app_settings(
        self, client, monkeypatch,
    ):
        """(HEAD-review F5) the scheduled path must pass ``app.state.settings``
        as the final positional arg (``run_in_executor`` takes no kwargs) so the
        job's collectors use the app data dir / TOFU ``known_hosts`` store rather
        than a worker-resolved ``Settings()`` from env — the sibling of the
        manual POST call site that was also left ``None``."""
        from netcanon.api.routes.schedules import _run_scheduled_backup_inner
        from netcanon.services import backup_runner

        app = client.app
        self._cisco_profile(app)
        sid = _create_schedule(client)["id"]

        captured: list = []

        def _capture(job, *a, **k):
            captured.append(a)

        monkeypatch.setattr(backup_runner, "run_backup_job", _capture)
        await _run_scheduled_backup_inner(sid, app)

        assert captured, "runner never dispatched (no resolvable target?)"
        # ``settings`` is the last positional arg after ``job``.
        assert captured[0][-1] is app.state.settings
