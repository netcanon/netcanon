"""
Unit tests for the dedicated backup-*job* executor (2026-07-06 review
MEDIUM #27).

The r7 ceiling (``tests/unit/test_backup_global_concurrency.py``) bounds how
many *devices* collect at once.  This module covers the orthogonal, newer
ceiling: how many whole *jobs* run at once.  Both backup entry points used to
dispatch the minutes-long :func:`run_backup_job` onto a *shared* pool — the
manual path onto anyio's ~40-token default worker pool (starving every sync
route), the scheduled path onto asyncio's default executor (shared with
``/sanitize`` + the egress filter).  A dedicated module-level
``ThreadPoolExecutor`` now runs jobs off those shared pools and caps
concurrent jobs at :data:`~netcanon.config.MAX_CONCURRENT_BACKUP_JOBS`.

The cap test pins the "<= cap" direction deterministically: with a cap of N
and N+1 submissions, exactly N stubs enter the pool and the (N+1)th cannot
start until one frees — an uncapped executor would start all N+1 and fail the
assertion.
"""

from __future__ import annotations

import threading

import pytest

from netcanon.services import backup_runner

pytestmark = pytest.mark.unit


@pytest.fixture
def small_job_cap(monkeypatch):
    """Shrink the concurrent-jobs cap and rebuild the executor around it.

    ``reset_job_executor`` on both edges keeps the small pool from leaking
    into (or being shadowed by) other tests in the same process.
    """
    cap = 2
    monkeypatch.setattr(backup_runner, "MAX_CONCURRENT_BACKUP_JOBS", cap)
    backup_runner.reset_job_executor()
    yield cap
    backup_runner.reset_job_executor()


# ---------------------------------------------------------------------------
# Executor singleton + thread naming + reset
# ---------------------------------------------------------------------------


def test_job_executor_is_a_built_once_singleton():
    backup_runner.reset_job_executor()
    ex = backup_runner._job_executor()
    try:
        assert backup_runner._job_executor() is ex  # built once
        assert ex._thread_name_prefix == "backup-job"
    finally:
        backup_runner.reset_job_executor()


def test_reset_job_executor_rebuilds_at_current_cap(monkeypatch):
    """After a reset the executor rebuilds from the current cap value."""
    monkeypatch.setattr(backup_runner, "MAX_CONCURRENT_BACKUP_JOBS", 4)
    backup_runner.reset_job_executor()
    ex = backup_runner._job_executor()
    try:
        assert ex._max_workers == 4
        assert backup_runner._job_executor() is ex  # same instance on re-call
    finally:
        backup_runner.reset_job_executor()


def test_jobs_run_on_the_dedicated_backup_job_threads():
    """Work submitted to the executor runs on a ``backup-job``-named thread —
    i.e. off anyio's / asyncio's shared default pools."""
    backup_runner.reset_job_executor()
    seen: dict[str, str] = {}

    def stub() -> None:
        seen["thread"] = threading.current_thread().name

    try:
        backup_runner._job_executor().submit(stub).result(timeout=10)
        assert seen["thread"].startswith("backup-job")
    finally:
        backup_runner.reset_job_executor()


# ---------------------------------------------------------------------------
# The cap bounds concurrent JOBS (the actual #27 fix)
# ---------------------------------------------------------------------------


def test_executor_caps_concurrent_jobs_below_submission_count(small_job_cap):
    """Submit cap+1 blocking stubs → exactly ``cap`` run at once; the extra
    one waits in the FIFO queue until a slot frees.  An uncapped executor
    would start all cap+1 and this assertion would fail."""
    cap = small_job_cap
    entered = threading.Semaphore(0)   # released once per stub that STARTS
    release = threading.Event()        # test opens this to let stubs finish
    lock = threading.Lock()
    state = {"inflight": 0, "peak": 0}

    def blocking_stub() -> None:
        with lock:
            state["inflight"] += 1
            state["peak"] = max(state["peak"], state["inflight"])
        entered.release()
        # Bounded wait so a logic bug can never hang the suite forever.
        release.wait(timeout=15)
        with lock:
            state["inflight"] -= 1

    ex = backup_runner._job_executor()
    futures = [ex.submit(blocking_stub) for _ in range(cap + 1)]
    try:
        # Wait until `cap` stubs have actually started.
        for _ in range(cap):
            assert entered.acquire(timeout=10), "a stub never started"
        # The (cap+1)th must NOT have started — the pool is full.  A short
        # bounded probe: if it HAD started, this acquire would succeed.
        assert not entered.acquire(timeout=0.3), (
            "more than the cap started concurrently — the executor is not "
            "bounding concurrent jobs"
        )
        with lock:
            assert state["peak"] == cap
    finally:
        release.set()
        for f in futures:
            f.result(timeout=15)

    # After everything drains the extra job ran too, but the peak never
    # exceeded the cap.
    assert state["peak"] == cap
    assert state["inflight"] == 0


# ---------------------------------------------------------------------------
# submit_backup_job dispatches run_backup_job onto the dedicated executor
# ---------------------------------------------------------------------------


def test_submit_backup_job_runs_run_backup_job_on_the_dedicated_pool(monkeypatch):
    """``submit_backup_job(*args)`` runs ``run_backup_job(*args)`` on a
    ``backup-job`` thread — the single manual-path dispatch seam."""
    backup_runner.reset_job_executor()
    captured: dict[str, object] = {}

    def fake_run_backup_job(*args, **kwargs) -> str:
        captured["args"] = args
        captured["kwargs"] = kwargs
        captured["thread"] = threading.current_thread().name
        return "done"

    monkeypatch.setattr(backup_runner, "run_backup_job", fake_run_backup_job)
    try:
        fut = backup_runner.submit_backup_job(
            "job-sentinel", "request-sentinel", 42
        )
        assert fut.result(timeout=10) == "done"
        assert captured["args"] == ("job-sentinel", "request-sentinel", 42)
        assert captured["thread"].startswith("backup-job")
    finally:
        backup_runner.reset_job_executor()


# ---------------------------------------------------------------------------
# Config resolution: default / env override / floor / garbage fallback
# ---------------------------------------------------------------------------


def test_default_concurrent_jobs_cap_is_eight():
    from netcanon import config

    assert config.MAX_CONCURRENT_BACKUP_JOBS == 8


def test_env_override_sets_cap(monkeypatch):
    from netcanon import config

    monkeypatch.setenv("NETCANON_MAX_CONCURRENT_BACKUP_JOBS", "16")
    assert config._resolve_max_concurrent_backup_jobs() == 16


def test_env_override_floors_at_one(monkeypatch):
    from netcanon import config

    monkeypatch.setenv("NETCANON_MAX_CONCURRENT_BACKUP_JOBS", "0")
    assert config._resolve_max_concurrent_backup_jobs() == 1


def test_env_override_garbage_falls_back_to_default(monkeypatch):
    from netcanon import config

    monkeypatch.setenv("NETCANON_MAX_CONCURRENT_BACKUP_JOBS", "not-a-number")
    with pytest.warns(UserWarning):
        assert config._resolve_max_concurrent_backup_jobs() == 8
