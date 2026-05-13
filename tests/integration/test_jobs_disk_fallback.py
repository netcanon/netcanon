"""
Integration tests for R8 backup-job registry: bounded memory + disk
lazy-load.

Pre-R8 ``app.state.jobs`` was an unbounded ``dict[str, BackupJob]``
that grew indefinitely as jobs ran.  R8 replaces it with
:class:`netcanon.storage.job_registry.BackupJobRegistry`, an LRU-
bounded cache backed by ``FileJobStore``.  These tests assert the
end-to-end contract from the operator-facing API:

* ``POST /api/v1/backups/`` over the cap → oldest jobs evict from
  memory (don't appear in ``GET /api/v1/backups/``).
* ``GET /api/v1/backups/{id}`` for an evicted-but-on-disk job still
  returns 200 with the full record (lazy-loads transparently).
* ``GET /api/v1/backups/{id}`` for a truly-missing job returns 404.

The route handlers themselves are unchanged from pre-R8 — they
operate on a dict-like surface.  These tests confirm the registry
swap didn't break any of the contracts they relied on.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from netcanon.models.backup import BackupJob, JobStatus

pytestmark = pytest.mark.integration


def _make_job(
    *,
    job_id: str | None = None,
    created_at: datetime | None = None,
) -> BackupJob:
    return BackupJob(
        id=job_id or str(uuid.uuid4()),
        status=JobStatus.completed,
        created_at=created_at or datetime.now(timezone.utc),
        total_devices=1,
    )


class TestBoundedMemory:
    def test_list_endpoint_returns_memory_resident_only(self, client):
        """Seed more jobs on disk than the cache holds, then verify the
        list endpoint returns only memory-resident.  Uses the actual
        registry on app.state (which warmed from the empty dir at
        startup) — we directly insert via the registry's __setitem__
        + the underlying disk store to control state."""
        registry = client.app.state.jobs
        store = client.app.state.job_store
        # Force a small cap for this test by replacing the registry
        # with one capped at 3.
        from netcanon.storage.job_registry import BackupJobRegistry
        client.app.state.jobs = BackupJobRegistry(
            store, max_memory_jobs=3, warm_cache=False,
        )
        # Insert 5 jobs (cap is 3 → 2 oldest evict from memory).
        base = datetime(2026, 5, 1, tzinfo=timezone.utc)
        jobs = [
            _make_job(created_at=base + timedelta(hours=i))
            for i in range(5)
        ]
        for j in jobs:
            store.save(j)
            client.app.state.jobs[j.id] = j
        # List endpoint returns memory-resident jobs only.
        resp = client.get("/api/v1/backups/")
        assert resp.status_code == 200
        listed_ids = [j["id"] for j in resp.json()]
        # The 3 most-recent inserts survived; the 2 oldest are evicted.
        assert set(listed_ids) == {j.id for j in jobs[-3:]}
        # Restore the registry so other tests aren't affected.
        client.app.state.jobs = registry


class TestDiskFallback:
    def test_get_by_id_lazy_loads_evicted_job(self, client):
        """A job that was evicted from memory but still exists on
        disk should be retrievable via ``GET /api/v1/backups/{id}``.
        This is the core promise of the R8 design — operators don't
        lose access to historical jobs just because they're old."""
        registry = client.app.state.jobs
        store = client.app.state.job_store
        from netcanon.storage.job_registry import BackupJobRegistry
        client.app.state.jobs = BackupJobRegistry(
            store, max_memory_jobs=2, warm_cache=False,
        )
        # Persist a job to disk + cache.
        evicted = _make_job()
        store.save(evicted)
        client.app.state.jobs[evicted.id] = evicted
        # Insert 2 more jobs → evicted should fall out of cache.
        for _ in range(2):
            j = _make_job()
            store.save(j)
            client.app.state.jobs[j.id] = j
        # Confirm the targeted job is no longer in memory.
        assert evicted.id not in list(client.app.state.jobs.keys())
        # But GET /api/v1/backups/{id} still returns it (disk fallback).
        resp = client.get("/api/v1/backups/{}".format(evicted.id))
        assert resp.status_code == 200
        assert resp.json()["id"] == evicted.id
        client.app.state.jobs = registry

    def test_get_by_id_404_for_truly_missing_job(self, client):
        """A job ID that doesn't exist in memory OR on disk should
        still return 404 — disk fallback doesn't make the API too
        permissive."""
        resp = client.get("/api/v1/backups/{}".format(uuid.uuid4()))
        assert resp.status_code == 404


class TestRegistryWiredCorrectly:
    """Sanity check that ``app.state.jobs`` is the registry instance,
    not the pre-R8 plain dict.  Catches accidental regressions where
    a startup hook overwrites it."""

    def test_app_state_jobs_is_registry(self, client):
        from netcanon.storage.job_registry import BackupJobRegistry
        assert isinstance(client.app.state.jobs, BackupJobRegistry)

    def test_registry_uses_settings_cap(self, client):
        """The registry's cap should reflect the Settings value
        (default 1000) — not a hardcoded literal."""
        assert client.app.state.jobs.max_memory_jobs == 1000
