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
