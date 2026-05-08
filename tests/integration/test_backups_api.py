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
# Terminal-state logic: completed / partial / failed
# ---------------------------------------------------------------------------


class _SelectiveFailCollector:
    """Collector that raises for hosts in ``fail_hosts`` and succeeds otherwise."""

    def __init__(self, fail_hosts: set[str]) -> None:
        self._fail_hosts = fail_hosts

    def collect(self, device, definition):  # noqa: ARG002
        if device.host in self._fail_hosts:
            raise RuntimeError(f"Simulated failure for {device.host}")
        return "! config for " + device.host


class TestJobTerminalStatus:
    """Verify the three-way terminal status: completed / partial / failed."""

    def _run(self, test_app, fail_hosts: set[str], hosts: list[str]) -> dict:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        collector = _SelectiveFailCollector(fail_hosts)
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(test_app, raise_server_exceptions=True) as c:
                resp = c.post(
                    "/api/v1/backups",
                    json={"devices": [_device_payload(host=h) for h in hosts]},
                )
                assert resp.status_code == 202
                return c.get(f"/api/v1/backups/{resp.json()['id']}").json()

    def test_all_success_marks_job_completed(self, test_app):
        job = self._run(test_app, fail_hosts=set(), hosts=["1.1.1.1", "2.2.2.2"])
        assert job["status"] == "completed"

    def test_all_failure_marks_job_failed(self, test_app):
        job = self._run(
            test_app, fail_hosts={"1.1.1.1", "2.2.2.2"}, hosts=["1.1.1.1", "2.2.2.2"]
        )
        assert job["status"] == "failed"
        assert all(r["status"] == "failed" for r in job["results"])

    def test_mixed_results_mark_job_partial(self, test_app):
        job = self._run(
            test_app, fail_hosts={"2.2.2.2"}, hosts=["1.1.1.1", "2.2.2.2", "3.3.3.3"]
        )
        assert job["status"] == "partial"
        statuses = [r["status"] for r in job["results"]]
        assert statuses.count("success") == 2
        assert statuses.count("failed") == 1

    def test_single_device_failure_is_failed_not_partial(self, test_app):
        job = self._run(test_app, fail_hosts={"1.1.1.1"}, hosts=["1.1.1.1"])
        assert job["status"] == "failed"


# ---------------------------------------------------------------------------
# Per-device status lifecycle: queued -> running -> success/failed
# ---------------------------------------------------------------------------


class _ObservingCollector:
    """Collector that snapshots the full job-results list on each call.

    Snapshots are taken at the *start* of ``collect()`` (i.e. while the
    collector is the current device's ``running`` state, and every other
    device is still ``queued``) so we can assert the lifecycle from a
    single completed run without threading or timing.

    The app reference is lazy-resolved — ``app.state.jobs`` doesn't exist
    until the FastAPI lifespan runs, which happens inside the TestClient
    context manager, so we can't capture the dict at construction time.
    """

    def __init__(self, app, fail_hosts: set[str] | None = None) -> None:
        self._app = app
        self._fail = fail_hosts or set()
        self.snapshots: list[list[dict]] = []

    def collect(self, device, definition):  # noqa: ARG002
        # capture the only in-progress job's results verbatim
        running_job = next(iter(self._app.state.jobs.values()))
        self.snapshots.append(
            [{"host": r.host, "status": r.status} for r in running_job.results]
        )
        if device.host in self._fail:
            raise RuntimeError("simulated")
        return "! config"


class TestDeviceStatusLifecycle:
    """queued -> running -> success|failed, per-device, in order."""

    def test_first_device_is_running_others_queued_mid_flight(self, test_app):
        """While device N is being collected, N is 'running' and N+1..end are 'queued'."""
        from unittest.mock import patch
        from fastapi.testclient import TestClient

        collector = _ObservingCollector(test_app)
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(test_app, raise_server_exceptions=True) as c:
                resp = c.post(
                    "/api/v1/backups",
                    json={
                        "devices": [
                            _device_payload(host="1.1.1.1"),
                            _device_payload(host="2.2.2.2"),
                            _device_payload(host="3.3.3.3"),
                        ]
                    },
                )
                assert resp.status_code == 202

        # 3 devices → 3 snapshots, one taken at the start of each collect.
        assert len(collector.snapshots) == 3
        # Snapshot 0: device 1 running, 2 & 3 queued
        snap0 = collector.snapshots[0]
        assert [r["host"] for r in snap0] == ["1.1.1.1", "2.2.2.2", "3.3.3.3"]
        assert snap0[0]["status"] == "running"
        assert snap0[1]["status"] == "queued"
        assert snap0[2]["status"] == "queued"
        # Snapshot 1: device 1 success (already completed), 2 running, 3 queued
        snap1 = collector.snapshots[1]
        assert snap1[0]["status"] == "success"
        assert snap1[1]["status"] == "running"
        assert snap1[2]["status"] == "queued"
        # Snapshot 2: device 1 & 2 success, 3 running
        snap2 = collector.snapshots[2]
        assert snap2[0]["status"] == "success"
        assert snap2[1]["status"] == "success"
        assert snap2[2]["status"] == "running"

    def test_results_preserve_device_order(self, test_app, client):
        """results[i].host must match request.devices[i].host for all i."""
        hosts = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
        resp = _post_backup(client, devices=[_device_payload(host=h) for h in hosts])
        job = client.get(f"/api/v1/backups/{resp.json()['id']}").json()
        assert [r["host"] for r in job["results"]] == hosts

    def test_final_result_count_matches_total_devices(self, client):
        job = _post_and_get(
            client,
            devices=[_device_payload(host=f"10.0.0.{i}") for i in range(1, 6)],
        )
        assert len(job["results"]) == job["total_devices"] == 5
        # After completion, no result is still queued/running.
        assert all(r["status"] in ("success", "failed") for r in job["results"])


# ---------------------------------------------------------------------------
# Bounded per-job parallelism (ThreadPoolExecutor, cap of 10)
# ---------------------------------------------------------------------------


class _BarrierCollector:
    """Block in ``collect()`` until *parties* workers all reach the barrier.

    If execution were serial, only the first worker would ever arrive at
    ``barrier.wait()``; the others would never start.  The barrier's
    timeout therefore doubles as a proof that *parties* devices were being
    processed concurrently.
    """

    def __init__(self, parties: int) -> None:
        import threading
        self._barrier = threading.Barrier(parties, timeout=5)
        self.max_observed_concurrent: int = 0
        self._active = 0
        self._lock = threading.Lock()

    def collect(self, device, definition):  # noqa: ARG002
        with self._lock:
            self._active += 1
            if self._active > self.max_observed_concurrent:
                self.max_observed_concurrent = self._active
        try:
            self._barrier.wait()
        finally:
            with self._lock:
                self._active -= 1
        return "! config for " + device.host


def _build_parallel_app(test_settings, concurrency: int):
    """Return a fresh FastAPI app with ``backup_concurrency=concurrency``."""
    from netcanon.main import create_app

    parallel = test_settings.model_copy(update={"backup_concurrency": concurrency})
    return create_app(parallel)


class TestBackupConcurrency:
    """Exercise the ThreadPoolExecutor path + 10-at-a-time batching."""

    def test_three_devices_run_concurrently_when_concurrency_3(self, test_settings):
        """Barrier(3) only opens if 3 workers arrive simultaneously."""
        from unittest.mock import patch
        from fastapi.testclient import TestClient

        app = _build_parallel_app(test_settings, concurrency=3)
        collector = _BarrierCollector(parties=3)

        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(app, raise_server_exceptions=True) as c:
                resp = c.post(
                    "/api/v1/backups",
                    json={"devices": [
                        _device_payload(host="1.1.1.1"),
                        _device_payload(host="2.2.2.2"),
                        _device_payload(host="3.3.3.3"),
                    ]},
                )
                assert resp.status_code == 202
                job = c.get(f"/api/v1/backups/{resp.json()['id']}").json()

        # All devices succeeded (barrier opened, no timeout).
        assert job["status"] == "completed"
        # Peak concurrency must equal the configured limit.
        assert collector.max_observed_concurrent == 3

    def test_concurrency_clamped_to_hard_max_of_10(self, test_settings):
        """Even if Settings allowed higher, 10 is the ceiling."""
        from netcanon.config import MAX_BACKUP_CONCURRENCY
        assert MAX_BACKUP_CONCURRENCY == 10
        # Pydantic rejects out-of-range values at Settings construction.
        import pytest
        from netcanon.config import Settings
        with pytest.raises(Exception):  # ValidationError
            Settings(
                definitions_dir=test_settings.definitions_dir,
                configs_dir=test_settings.configs_dir,
                backup_concurrency=MAX_BACKUP_CONCURRENCY + 1,
            )

    def test_batching_caps_concurrency_and_processes_all_devices(
        self, test_settings
    ):
        """With 12 devices and concurrency=5, peak concurrency must be 5 (not 12)
        AND every device must still be processed successfully."""
        import threading
        import time
        from unittest.mock import patch
        from fastapi.testclient import TestClient

        app = _build_parallel_app(test_settings, concurrency=5)

        class _CountingCollector:
            """Tracks peak concurrency without deadlocking on batch boundaries.

            Each call briefly sleeps so workers have real overlap — without
            this the collector would complete instantly and peak concurrency
            would depend on scheduler timing rather than the pool size.
            """
            def __init__(self) -> None:
                self.lock = threading.Lock()
                self.active = 0
                self.peak = 0

            def collect(self, device, definition):  # noqa: ARG002
                with self.lock:
                    self.active += 1
                    if self.active > self.peak:
                        self.peak = self.active
                try:
                    time.sleep(0.05)  # keep workers overlapping
                finally:
                    with self.lock:
                        self.active -= 1
                return "! config"

        collector = _CountingCollector()
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(app, raise_server_exceptions=True) as c:
                resp = c.post(
                    "/api/v1/backups",
                    json={"devices": [
                        _device_payload(host=f"10.0.0.{i}") for i in range(1, 13)
                    ]},
                )
                assert resp.status_code == 202
                job = c.get(f"/api/v1/backups/{resp.json()['id']}").json()

        assert job["status"] == "completed"
        assert len(job["results"]) == 12
        assert all(r["status"] == "success" for r in job["results"])
        # Hard cap: concurrency must never have exceeded the configured limit.
        assert collector.peak <= 5
        # Evidence of actual parallelism: >1 device was in flight at once.
        assert collector.peak >= 2

    def test_single_device_job_uses_serial_fast_path(self, test_settings):
        """Single-device jobs skip the pool entirely (no thread overhead)."""
        from unittest.mock import patch
        from fastapi.testclient import TestClient

        # Sentinel collector: records the name of the thread that called it.
        import threading
        thread_names: list[str] = []

        class ThreadNameCollector:
            def collect(self, device, definition):  # noqa: ARG002
                thread_names.append(threading.current_thread().name)
                return "! config"

        app = _build_parallel_app(test_settings, concurrency=10)
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=ThreadNameCollector(),
        ):
            with TestClient(app, raise_server_exceptions=True) as c:
                c.post(
                    "/api/v1/backups",
                    json={"devices": [_device_payload(host="1.1.1.1")]},
                )

        assert len(thread_names) == 1
        # Serial path runs in the caller's thread, not a "backup-…" worker.
        assert not thread_names[0].startswith("backup-")


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
