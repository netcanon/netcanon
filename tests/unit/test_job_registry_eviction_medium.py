"""BackupJobRegistry must not evict a non-terminal job (2026-07-06 MEDIUM #25).

``__setitem__`` evicted the LRU entry unconditionally.  If that entry was a
still-running/pending job, a later poll promoted its stale ``pending`` disk
snapshot into the cache, and the worker's terminal save (disk-only, never
re-inserted) was masked forever.  The fix evicts the LRU-most TERMINAL job
instead, allowing a temporary cap overshoot when every resident job is live.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from netcanon.models.backup import BackupJob, JobStatus
from netcanon.storage.job_registry import BackupJobRegistry
from netcanon.storage.job_store import FileJobStore

pytestmark = pytest.mark.unit


def _job(status: JobStatus) -> BackupJob:
    return BackupJob(
        id=str(uuid.uuid4()), status=status, created_at=datetime.now(UTC),
        total_devices=1,
    )


@pytest.fixture
def registry(tmp_path: Path):
    def _build(cap: int) -> BackupJobRegistry:
        store = FileJobStore(tmp_path / f"jobs{cap}")
        return BackupJobRegistry(store, max_memory_jobs=cap, warm_cache=False)
    return _build


class TestNonTerminalEvictionProtection:
    def test_running_job_not_evicted_over_cap(self, registry):
        reg = registry(1)
        a, b = _job(JobStatus.running), _job(JobStatus.running)
        reg[a.id] = a
        reg[b.id] = b  # over cap, but both non-terminal -> overshoot, no evict
        assert a.id in list(reg)  # pre-fix: popitem evicts a
        assert b.id in list(reg)

    def test_running_job_protected_terminal_evicted_instead(self, registry):
        reg = registry(1)
        running, done = _job(JobStatus.running), _job(JobStatus.completed)
        reg[running.id] = running
        reg[done.id] = done  # over cap -> the TERMINAL one is evicted
        assert running.id in list(reg)   # protected (pre-fix: evicted)
        assert done.id not in list(reg)  # pre-fix: running evicted, done kept

    def test_terminal_jobs_still_evict_lru(self, registry):
        # Regression guard: normal LRU still applies to terminal jobs.
        reg = registry(2)
        a, b, c = (_job(JobStatus.completed) for _ in range(3))
        reg[a.id] = a
        reg[b.id] = b
        reg[c.id] = c
        assert a.id not in list(reg)  # oldest terminal evicted
        assert b.id in list(reg) and c.id in list(reg)

    def test_stale_pending_disk_load_not_promoted_then_heals(self, registry):
        # (HEAD-review F1) The runner flips a job terminal IN MEMORY before its
        # terminal DISK save.  If an eviction lands in that window and a poll
        # disk-loads the stale ``pending`` snapshot, PROMOTING it would pin it
        # non-terminal forever (eviction-protected, #25) and answer the wrong
        # status until restart.  __getitem__ must NOT cache a non-terminal disk
        # load -> the next poll re-reads disk and HEALS once the terminal save
        # lands.  (Also covers the swallowed terminal-save OSError sibling.)
        reg = registry(2)
        store = reg._store
        a = _job(JobStatus.pending)
        reg[a.id] = a
        store.save(a)  # creation snapshot on disk: pending
        filler = _job(JobStatus.completed)
        reg[filler.id] = filler  # cache at cap: {a(pending), filler(done)}
        a.status = JobStatus.completed  # in-memory terminal flip, NOT saved yet
        overflow = _job(JobStatus.completed)
        reg[overflow.id] = overflow  # over cap -> evicts A (LRU-most terminal)
        assert a.id not in list(reg)  # A evicted in the window

        # Poll while disk still says pending: returns pending but must NOT cache
        # it (pre-fix: promoted -> pinned pending forever).
        assert reg[a.id].status is JobStatus.pending
        assert a.id not in list(reg), "stale pending must not be promoted (F1)"

        # Terminal save lands -> the next poll re-reads disk and heals.
        store.save(a)
        assert reg[a.id].status is JobStatus.completed
