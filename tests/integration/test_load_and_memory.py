"""
Phase-3 Round-9 load + memory smoke tests.

R9 is the "runtime checks" round.  R7.1 / R7.2 covered the browser
visual side; this module covers the backend side: the full backup
pipeline under sustained synthetic load, with the R8 registry cap in
place.  These tests don't require Docker or browsers — they use
``TestClient`` + ``FakeCollector`` (the same mock-collection pattern
the rest of the integration suite uses) and stdlib ``tracemalloc``
for memory verification.

Pinned scenarios:

* **Sustained job load**: submit > cap backup requests through the
  real API surface; verify the registry's LRU eviction holds + every
  job survives on disk + job-completion semantics aren't broken by
  the eviction.
* **Concurrent backups**: many parallel POSTs hitting
  ``/api/v1/backups`` simultaneously to surface any race conditions
  in the registry's ``__setitem__`` or in the background-task
  pipeline.  Marker class for what the operator-reported "10 devices
  × 100KB × concurrent backups" load looks like in practice.
* **Memory bound under load**: stdlib ``tracemalloc`` snapshot
  before/after a synthetic-load burst; the peak BackupJob-attributable
  allocation must stay bounded by the registry cap × per-job size
  estimate.

These are deliberately "smoke" tests — they pin the property + catch
gross regressions but don't try to be perfect benchmarks.  Real load
testing belongs in a separate tools/ script not run as part of the
test suite.
"""

from __future__ import annotations

import gc
import threading
import tracemalloc
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from netcanon.models.backup import BackupJob
from netcanon.storage.job_registry import BackupJobRegistry
from tests.conftest import FakeCollector

pytestmark = pytest.mark.integration


# A ~100KB synthetic config — Cisco-shaped so the file_store accepts
# it.  Padding is a repeated banner so it's plausibly real-looking
# rather than just lorem-ipsum.  Each padding line is ~79 bytes
# encoded (em-dash → 3 bytes in UTF-8), so 1260 reps ≈ 100KB.
_BIG_CONFIG = (
    "!\nversion 17.9\nhostname Router\n!\n"
    + ("! synthetic padding line - Netcanon load test\n" * 2150)
    + "\n!\nend\n"
)
assert 95_000 < len(_BIG_CONFIG) < 110_000, (
    "expected ~100KB synthetic config, got {} bytes".format(len(_BIG_CONFIG))
)


def _device_payload(host: str = "192.168.1.1") -> dict:
    return {
        "type_key": "Cisco",
        "host": host,
        "credentials": {"username": "admin", "password": "fake"},
    }


def _swap_registry(app, max_memory_jobs: int) -> BackupJobRegistry:
    """Replace ``app.state.jobs`` with a small-cap registry for
    eviction tests.  Returns the original so the test can restore it
    in teardown (avoids leaking state across tests).

    MUST be called AFTER the ``TestClient`` context-manager has fired
    the app lifespan — otherwise ``app.state.jobs`` doesn't exist
    yet.  Tests guard this by structuring as::

        with TestClient(test_app) as c:
            original = _swap_registry(test_app, max_memory_jobs=10)
            try:
                ... test body ...
            finally:
                test_app.state.jobs = original
    """
    original = app.state.jobs
    app.state.jobs = BackupJobRegistry(
        app.state.job_store,
        max_memory_jobs=max_memory_jobs,
        warm_cache=False,
    )
    return original


# ---------------------------------------------------------------------------
# Sustained-load: cap holds across the real API pipeline
# ---------------------------------------------------------------------------


class TestSustainedLoad:
    """Submit > cap backup requests through ``POST /api/v1/backups``
    and verify the registry's LRU eviction holds end-to-end (not just
    via direct registry inserts, which the R8 unit tests covered)."""

    def test_50_sequential_backups_with_cap_10(self, test_app):
        """50 backups against a cap-10 registry → memory holds at 10,
        disk holds 50, every job remains queryable by ID."""
        collector = FakeCollector(output=_BIG_CONFIG)
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(test_app) as c:
                original_registry = _swap_registry(test_app, max_memory_jobs=10)
                try:
                    job_ids = []
                    for i in range(50):
                        resp = c.post(
                            "/api/v1/backups",
                            json={"devices": [_device_payload(host=f"10.0.0.{i}")]},
                        )
                        assert resp.status_code == 202, resp.text
                        job_ids.append(resp.json()["id"])
                    # Registry memory bounded by the cap.
                    assert len(test_app.state.jobs) == 10
                    # All 50 persist to disk.
                    disk_ids = test_app.state.job_store.list_job_ids()
                    assert len(disk_ids) == 50
                    assert set(disk_ids) == set(job_ids)
                    # Every job is queryable by ID (transparent disk
                    # fallback for evicted ones).
                    for jid in job_ids:
                        resp = c.get(f"/api/v1/backups/{jid}")
                        assert resp.status_code == 200, jid
                        assert resp.json()["status"] == "completed"
                finally:
                    test_app.state.jobs = original_registry

    def test_job_completion_survives_eviction(self, test_app):
        """Submit a job, evict it from memory by flooding new jobs,
        then re-read it — the saved completion state must persist
        (the FileJobStore.save call in _run_backup_job is what makes
        this true; the test pins that contract)."""
        collector = FakeCollector(output=_BIG_CONFIG)
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(test_app) as c:
                original_registry = _swap_registry(test_app, max_memory_jobs=3)
                try:
                    # First job — should complete, get persisted, then
                    # be evicted by subsequent submissions.
                    first = c.post(
                        "/api/v1/backups",
                        json={"devices": [_device_payload(host="10.0.0.0")]},
                    ).json()
                    # Flood enough jobs to push the first one out.
                    for i in range(5):
                        c.post(
                            "/api/v1/backups",
                            json={"devices": [_device_payload(host=f"10.0.0.{i + 1}")]},
                        )
                    # First job is no longer in memory.
                    assert first["id"] not in list(test_app.state.jobs.keys())
                    # But its persisted state is intact + reachable.
                    resp = c.get(f"/api/v1/backups/{first['id']}")
                    assert resp.status_code == 200
                    payload = resp.json()
                    assert payload["id"] == first["id"]
                    assert payload["status"] == "completed"
                    assert len(payload["results"]) == 1
                    assert payload["results"][0]["status"] == "success"
                finally:
                    test_app.state.jobs = original_registry


# ---------------------------------------------------------------------------
# Concurrency: parallel POSTs against the registry
# ---------------------------------------------------------------------------


class TestConcurrentBackups:
    """Fire many parallel ``POST /api/v1/backups`` requests against
    a shared TestClient — surfaces races in the registry's
    ``__setitem__`` (OrderedDict mutations under contention) and in
    the BackgroundTask pipeline.

    Python's GIL means the OrderedDict ops themselves are atomic at
    the CPython bytecode level, so we don't expect data races; but
    the test pins the property so any future refactor that introduces
    real concurrency (e.g. switching to an async registry) doesn't
    silently regress."""

    def test_20_concurrent_pots_all_succeed(self, test_app):
        """20 parallel backup POSTs (each with a single device) →
        every request returns 202 + completes + ends up in the
        registry/disk."""
        collector = FakeCollector(output=_BIG_CONFIG)
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(test_app) as c:
                original_registry = _swap_registry(test_app, max_memory_jobs=100)
                try:
                    def submit(idx: int) -> tuple[int, str]:
                        resp = c.post(
                            "/api/v1/backups",
                            json={"devices": [_device_payload(host=f"10.0.{idx}.1")]},
                        )
                        return resp.status_code, resp.json().get("id", "")

                    with ThreadPoolExecutor(max_workers=10) as pool:
                        futures = [pool.submit(submit, i) for i in range(20)]
                        results = [f.result() for f in as_completed(futures)]
                    # Every request succeeded.
                    assert all(code == 202 for code, _ in results)
                    # Every job ID is unique.
                    ids = {jid for _, jid in results if jid}
                    assert len(ids) == 20
                    # And every job persisted.
                    disk_ids = set(test_app.state.job_store.list_job_ids())
                    assert ids.issubset(disk_ids)
                finally:
                    test_app.state.jobs = original_registry

    def test_multi_device_backup_under_concurrency(self, test_app):
        """The "10 devices × 100KB × concurrent backups" scenario from
        the pre-launch checklist.  10 devices in a single job exercises
        the per-job ThreadPoolExecutor (backup_concurrency, default 10);
        running 3 such jobs concurrently exercises both layers."""
        collector = FakeCollector(output=_BIG_CONFIG)
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(test_app) as c:
                original_registry = _swap_registry(test_app, max_memory_jobs=100)
                try:
                    # 3 concurrent jobs, each with 10 devices.
                    def submit_burst(batch: int) -> dict:
                        devices = [
                            _device_payload(host=f"172.16.{batch}.{i}")
                            for i in range(10)
                        ]
                        resp = c.post(
                            "/api/v1/backups",
                            json={"devices": devices},
                        )
                        return resp.json()

                    with ThreadPoolExecutor(max_workers=3) as pool:
                        jobs = list(pool.map(submit_burst, range(3)))
                    # All 3 jobs accepted.
                    assert len(jobs) == 3
                    # GET each job → all completed with 10 results each.
                    for j in jobs:
                        resp = c.get(f"/api/v1/backups/{j['id']}")
                        payload = resp.json()
                        assert payload["status"] == "completed", payload
                        assert len(payload["results"]) == 10
                        assert all(
                            r["status"] == "success" for r in payload["results"]
                        )
                finally:
                    test_app.state.jobs = original_registry


# ---------------------------------------------------------------------------
# Memory bound (tracemalloc)
# ---------------------------------------------------------------------------


class TestMemoryBound:
    """Verify the in-memory ``BackupJob`` instance count stays bounded
    under load.  Uses ``gc.get_objects()`` to directly count instances
    of the model class — more reliable than RSS-based measurement on
    Windows test runners where Python's allocator caches inflate the
    apparent memory footprint."""

    def _count_backup_jobs(self) -> int:
        """Count live BackupJob instances by walking gc.get_objects().

        ``gc.collect()`` first to make the count deterministic — pending
        cycles from previous tests can otherwise inflate the result."""
        gc.collect()
        return sum(1 for obj in gc.get_objects() if isinstance(obj, BackupJob))

    def test_backupjob_instance_count_stays_bounded(self, test_app):
        """Submit 30 jobs against a cap-5 registry; the live
        ``BackupJob`` instance count delta during the load burst
        should track the cap (not 30 like pre-R8).

        Counts the DELTA from a baseline taken at the start of the
        burst rather than the absolute count — other tests in the
        suite create BackupJob instances that linger via Pydantic's
        weak-ref / cycle structures even after ``gc.collect()``, so
        an absolute-count assertion is brittle.  The delta-based
        check is the actual property we care about: load doesn't
        cause unbounded growth."""
        collector = FakeCollector(output=_BIG_CONFIG)
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=collector,
        ):
            with TestClient(test_app) as c:
                original_registry = _swap_registry(test_app, max_memory_jobs=5)
                try:
                    baseline = self._count_backup_jobs()
                    for i in range(30):
                        resp = c.post(
                            "/api/v1/backups",
                            json={"devices": [_device_payload(host=f"10.1.0.{i}")]},
                        )
                        assert resp.status_code == 202
                    after_load = self._count_backup_jobs()
                    delta = after_load - baseline
                    # Generous ceiling: cap (5) plus reasonable slack
                    # for in-flight response objects, recent disk-load
                    # cache entries, and TestClient internals holding
                    # short-lived references.  Pre-R8 the delta would
                    # have been ~30 (one per submitted job).  Post-R8
                    # the registry caps growth.
                    assert delta <= 20, (
                        "BackupJob instance delta {} exceeds 20-instance "
                        "ceiling — load is causing unbounded growth (cap=5 "
                        "+ slack expected)".format(delta)
                    )
                    # Registry's own count is exact regardless of test
                    # pollution.
                    assert len(test_app.state.jobs) == 5
                finally:
                    test_app.state.jobs = original_registry

    def test_tracemalloc_peak_under_load(self, test_app):
        """End-to-end memory: tracemalloc snapshot before vs after
        a 20-job burst.  Asserts peak Python-managed memory delta
        stays under a generous ceiling (5 MB).  Best-effort — flaky
        in CI envs where allocator state varies; primary guard is
        the gc.get_objects test above."""
        collector = FakeCollector(output=_BIG_CONFIG)
        tracemalloc.start()
        try:
            with patch(
                "netcanon.api.routes.backups.get_collector",
                return_value=collector,
            ):
                with TestClient(test_app) as c:
                    original_registry = _swap_registry(test_app, max_memory_jobs=10)
                    try:
                        snap_before = tracemalloc.take_snapshot()
                        for i in range(20):
                            c.post(
                                "/api/v1/backups",
                                json={"devices": [_device_payload(host=f"10.2.0.{i}")]},
                            )
                        gc.collect()
                        snap_after = tracemalloc.take_snapshot()
                    finally:
                        test_app.state.jobs = original_registry
            stats = snap_after.compare_to(snap_before, "filename")
            total_delta = sum(s.size_diff for s in stats)
            # 20 jobs × 100KB ≈ 2 MB worst case for serialisation
            # buffers.  Cap holds at 10 in memory so the live
            # BackupJob instances are ~50 KB total.  Use 5 MB as
            # a generous ceiling that flags > 10× regressions.
            assert total_delta < 5_000_000, (
                "tracemalloc delta {} bytes exceeds 5 MB ceiling "
                "— suggests an allocation regression".format(total_delta)
            )
        finally:
            tracemalloc.stop()
