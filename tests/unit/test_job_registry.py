"""
Unit tests for ``netcanon.storage.job_registry.BackupJobRegistry``.

The registry caps in-memory ``BackupJob`` objects at
``max_memory_jobs`` (default 1000) and falls through to disk via
:class:`FileJobStore` when an evicted job is requested by ID.  Disk
is the source of truth — every job is persisted there regardless of
the cache state.

Tests cover four invariants:

1. **Bounded memory** — inserting > cap evicts LRU; the cache never
   grows beyond ``max_memory_jobs``.
2. **Lazy disk-load** — get-by-id of an evicted job lazy-loads from
   disk + promotes back into cache.
3. **LRU ordering** — accessed jobs move to MRU; old-but-recently-
   read jobs survive eviction in favour of older-untouched ones.
4. **Warm cache** — constructor preloads the most-recent N jobs
   from disk so the API is fast on the common case post-restart.

Plus tests for the dict-like API surface (``__contains__`` /
``__len__`` / ``__iter__`` / ``values()`` / ``get()``) and the
registry-specific ``total_disk_count`` / ``max_memory_jobs``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from netcanon.models.backup import BackupJob, JobStatus
from netcanon.storage.job_registry import (
    DEFAULT_MAX_MEMORY_JOBS,
    BackupJobRegistry,
)
from netcanon.storage.job_store import FileJobStore

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    *,
    job_id: str | None = None,
    created_at: datetime | None = None,
    status: JobStatus = JobStatus.completed,
) -> BackupJob:
    """Build a minimal ``BackupJob`` suitable for registry tests."""
    return BackupJob(
        id=job_id or str(uuid.uuid4()),
        status=status,
        created_at=created_at or datetime.now(timezone.utc),
        total_devices=1,
    )


@pytest.fixture
def store(tmp_path: Path) -> FileJobStore:
    """Empty FileJobStore in an isolated tmp directory."""
    return FileJobStore(tmp_path / "jobs")


@pytest.fixture
def registry(store: FileJobStore) -> BackupJobRegistry:
    """Empty registry with a small cap for predictable eviction tests."""
    return BackupJobRegistry(store, max_memory_jobs=3, warm_cache=False)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_max_is_1000(self, store: FileJobStore):
        reg = BackupJobRegistry(store, warm_cache=False)
        assert reg.max_memory_jobs == DEFAULT_MAX_MEMORY_JOBS

    def test_custom_max(self, store: FileJobStore):
        reg = BackupJobRegistry(store, max_memory_jobs=50, warm_cache=False)
        assert reg.max_memory_jobs == 50

    def test_zero_max_allowed(self, store: FileJobStore):
        """max_memory_jobs=0 disables caching entirely — every read
        falls through to disk.  Allowed for operators who want zero
        memory overhead at the cost of disk IO per request."""
        reg = BackupJobRegistry(store, max_memory_jobs=0, warm_cache=False)
        assert reg.max_memory_jobs == 0
        assert len(reg) == 0

    def test_negative_max_rejected(self, store: FileJobStore):
        with pytest.raises(ValueError, match=">= 0"):
            BackupJobRegistry(store, max_memory_jobs=-1, warm_cache=False)


# ---------------------------------------------------------------------------
# Bounded memory (LRU eviction)
# ---------------------------------------------------------------------------


class TestBoundedMemory:
    def test_inserts_within_cap_dont_evict(
        self, registry: BackupJobRegistry,
    ):
        for _ in range(3):
            j = _make_job()
            registry[j.id] = j
        assert len(registry) == 3

    def test_insert_over_cap_evicts_lru(
        self, registry: BackupJobRegistry, store: FileJobStore,
    ):
        """Insert 4 jobs into a cap-3 registry → oldest evicts from
        memory.  Disk is unaffected (eviction is memory-only)."""
        jobs = [_make_job() for _ in range(4)]
        for j in jobs:
            # Persist to disk too so the lazy-load works for the test
            store.save(j)
            registry[j.id] = j
        assert len(registry) == 3
        # The first-inserted job is gone from cache.
        assert jobs[0].id not in list(registry.keys())
        # Cache contains the 3 most-recent.
        assert set(registry.keys()) == {j.id for j in jobs[1:]}

    def test_zero_cap_never_caches(self, store: FileJobStore):
        reg = BackupJobRegistry(store, max_memory_jobs=0, warm_cache=False)
        j = _make_job()
        store.save(j)
        reg[j.id] = j
        assert len(reg) == 0
        # But lazy-load on get-by-id still works.
        assert reg[j.id].id == j.id

    def test_update_existing_does_not_grow_cache(
        self, registry: BackupJobRegistry,
    ):
        j = _make_job(status=JobStatus.pending)
        registry[j.id] = j
        assert len(registry) == 1
        # Update the same ID with a new status.
        j2 = _make_job(job_id=j.id, status=JobStatus.completed)
        registry[j.id] = j2
        assert len(registry) == 1
        assert registry[j.id].status is JobStatus.completed


# ---------------------------------------------------------------------------
# LRU ordering — accessed jobs move to MRU
# ---------------------------------------------------------------------------


class TestLRUOrdering:
    def test_get_moves_to_mru(
        self, registry: BackupJobRegistry, store: FileJobStore,
    ):
        """Insert 3 jobs (cap=3), read the oldest, then insert a 4th.
        The middle job should evict, NOT the recently-read oldest."""
        jobs = [_make_job() for _ in range(3)]
        for j in jobs:
            store.save(j)
            registry[j.id] = j
        # Read the oldest — it moves to MRU.
        _ = registry[jobs[0].id]
        # Insert a new job → cache is over cap by 1.
        j_new = _make_job()
        store.save(j_new)
        registry[j_new.id] = j_new
        # Middle job is evicted; oldest (just-read) survives.
        keys = list(registry.keys())
        assert jobs[0].id in keys  # survived
        assert jobs[1].id not in keys  # evicted
        assert jobs[2].id in keys
        assert j_new.id in keys

    def test_setitem_existing_moves_to_mru(
        self, registry: BackupJobRegistry,
    ):
        """Updating an existing job's entry should refresh its LRU
        position — re-setting a key counts as 'recent activity'."""
        jobs = [_make_job() for _ in range(3)]
        for j in jobs:
            registry[j.id] = j
        # Re-set the oldest.
        registry[jobs[0].id] = jobs[0]
        # The oldest is now MRU (end of OrderedDict).
        keys = list(registry.keys())
        assert keys[-1] == jobs[0].id


# ---------------------------------------------------------------------------
# Lazy disk-load on memory miss
# ---------------------------------------------------------------------------


class TestLazyDiskLoad:
    def test_getitem_loads_from_disk_on_miss(
        self, registry: BackupJobRegistry, store: FileJobStore,
    ):
        """Job on disk but evicted from memory — get-by-id should
        transparently lazy-load + return the job."""
        # Persist a job WITHOUT inserting it into the cache.
        evicted = _make_job()
        store.save(evicted)
        # Registry has zero memory entries; the disk read fires.
        result = registry[evicted.id]
        assert result.id == evicted.id

    def test_getitem_promotes_loaded_job_to_cache(
        self, registry: BackupJobRegistry, store: FileJobStore,
    ):
        """After a disk lazy-load, the job should be in memory so
        subsequent reads are fast."""
        evicted = _make_job()
        store.save(evicted)
        _ = registry[evicted.id]
        # Now in cache.
        assert evicted.id in list(registry.keys())

    def test_getitem_missing_raises_keyerror(
        self, registry: BackupJobRegistry,
    ):
        with pytest.raises(KeyError):
            _ = registry["nonexistent-job-id"]

    def test_get_returns_default_on_miss(
        self, registry: BackupJobRegistry,
    ):
        assert registry.get("nonexistent-job-id") is None
        assert registry.get("nonexistent-job-id", "fallback") == "fallback"

    def test_contains_checks_disk(
        self, registry: BackupJobRegistry, store: FileJobStore,
    ):
        """``job_id in registry`` should return True for jobs on disk
        but not in memory.  This is what the get-by-id route handler
        relies on for its 404 / found check."""
        on_disk_only = _make_job()
        store.save(on_disk_only)
        assert on_disk_only.id in registry
        assert on_disk_only.id not in list(registry.keys())  # not cached

    def test_contains_rejects_non_string(
        self, registry: BackupJobRegistry,
    ):
        """Defensive: ``42 in registry`` returns False rather than
        crashing on a non-string key."""
        assert 42 not in registry
        assert None not in registry


# ---------------------------------------------------------------------------
# Warm cache (constructor preloads from disk)
# ---------------------------------------------------------------------------


class TestWarmCache:
    def test_warm_loads_recent_jobs_within_cap(
        self, store: FileJobStore,
    ):
        """Seed 5 jobs on disk, instantiate registry with cap=3,
        warm_cache=True → cache contains 3 most-recent."""
        base = datetime(2026, 5, 1, tzinfo=timezone.utc)
        jobs = [
            _make_job(created_at=base + timedelta(hours=i))
            for i in range(5)
        ]
        for j in jobs:
            store.save(j)
        reg = BackupJobRegistry(store, max_memory_jobs=3, warm_cache=True)
        # Three most-recent are jobs[2], jobs[3], jobs[4].
        assert len(reg) == 3
        assert set(reg.keys()) == {jobs[2].id, jobs[3].id, jobs[4].id}

    def test_warm_disabled_starts_empty(self, store: FileJobStore):
        for _ in range(3):
            store.save(_make_job())
        reg = BackupJobRegistry(store, max_memory_jobs=10, warm_cache=False)
        assert len(reg) == 0
        # But jobs still queryable via lazy-load.
        assert reg.total_disk_count() == 3

    def test_warm_with_zero_cap_loads_nothing(
        self, store: FileJobStore,
    ):
        for _ in range(3):
            store.save(_make_job())
        reg = BackupJobRegistry(store, max_memory_jobs=0, warm_cache=True)
        assert len(reg) == 0


# ---------------------------------------------------------------------------
# Dict-like surface
# ---------------------------------------------------------------------------


class TestDictSurface:
    def test_iter_yields_memory_resident_ids(
        self, registry: BackupJobRegistry,
    ):
        jobs = [_make_job() for _ in range(2)]
        for j in jobs:
            registry[j.id] = j
        ids = list(iter(registry))
        assert set(ids) == {j.id for j in jobs}

    def test_values_returns_memory_resident_only(
        self, registry: BackupJobRegistry, store: FileJobStore,
    ):
        """``values()`` is what the list endpoint uses — confirm it
        returns ONLY memory-resident jobs (not disk-only ones).
        Old jobs on disk but evicted from memory don't appear in
        the recent-jobs list, which is the intended UX."""
        # One job in memory; one on disk only.
        memory_job = _make_job()
        registry[memory_job.id] = memory_job
        disk_only = _make_job()
        store.save(disk_only)
        values = list(registry.values())
        assert len(values) == 1
        assert values[0].id == memory_job.id

    def test_len_reflects_memory_only(
        self, registry: BackupJobRegistry, store: FileJobStore,
    ):
        store.save(_make_job())  # disk only
        registry[_make_job().id] = _make_job()  # memory
        assert len(registry) == 1


# ---------------------------------------------------------------------------
# Registry-specific surface
# ---------------------------------------------------------------------------


class TestRegistrySpecific:
    def test_total_disk_count(
        self, registry: BackupJobRegistry, store: FileJobStore,
    ):
        """Operator-meaningful 'total jobs ever recorded' — counts
        every JSON file in the jobs/ directory."""
        for _ in range(5):
            store.save(_make_job())
        assert registry.total_disk_count() == 5
        # Inserting into the registry doesn't double-count if the
        # registry already persisted (it doesn't — that's the route
        # handler's job via job_store.save).  Insertions go to
        # cache only here.
        registry[_make_job().id] = _make_job()
        assert registry.total_disk_count() == 5

    def test_max_memory_jobs_property(
        self, store: FileJobStore,
    ):
        reg = BackupJobRegistry(store, max_memory_jobs=42, warm_cache=False)
        assert reg.max_memory_jobs == 42


# ---------------------------------------------------------------------------
# Pathological / boundary cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_cap_of_one(self, store: FileJobStore):
        """Smallest non-zero cap — every insert evicts the previous."""
        reg = BackupJobRegistry(store, max_memory_jobs=1, warm_cache=False)
        j1 = _make_job()
        j2 = _make_job()
        reg[j1.id] = j1
        reg[j2.id] = j2
        assert list(reg.keys()) == [j2.id]
        assert len(reg) == 1

    def test_lazy_load_with_corrupt_disk_file(
        self, registry: BackupJobRegistry, store: FileJobStore,
    ):
        """If the disk file exists but is corrupt, lazy-load returns
        None (via load_one's exception swallow), which surfaces as
        KeyError to the registry caller — same UX as a truly missing
        job.  Operators see the corruption logged."""
        job_id = "corrupt-id"
        path = store._dir / f"{job_id}.json"
        path.write_text("not valid JSON")
        with pytest.raises(KeyError):
            _ = registry[job_id]
