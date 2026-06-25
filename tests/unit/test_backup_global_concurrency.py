"""
Unit tests for the process-wide backup-collection ceiling (blind-audit
3ec11f3 r7).

The per-job ``ThreadPoolExecutor`` in :func:`run_backup_job` caps a *single*
job at ``backup_concurrency`` (<= ``MAX_BACKUP_CONCURRENCY``).  Before r7
nothing capped the *number of jobs* in flight, so N concurrent jobs (several
schedules firing together, or a schedule firing during a manual run) could
open N×cap SSH/NETCONF sessions at once.  A module-level ``BoundedSemaphore``
in :mod:`netcanon.services.backup_runner` now bounds the SUM of in-flight
collections across every job; workers that can't get a permit block (back-
pressure), they never fail.

These tests pin both directions of the invariant deterministically:

* a ``Barrier`` sized to the ceiling forces exactly ``ceiling`` collections
  to be simultaneously in flight before any proceeds (the ">= ceiling"
  direction, no flaky sleeps), and
* the semaphore guarantees the observed peak never exceeds the ceiling (the
  "<= ceiling" direction).

Per AGENTS.md the collection layer is mocked at the documented seam
(``netcanon.api.routes.backups.get_collector``) — never ``paramiko`` /
``ConnectHandler``.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from netcanon.collectors.base import BaseCollector
from netcanon.config import MAX_BACKUP_CONCURRENCY, Settings
from netcanon.models.backup import BackupJob, ConfigRecord
from netcanon.models.device import BackupRequest, DeviceCredentials, DeviceTarget
from netcanon.services import backup_runner

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _PeakCollector(BaseCollector):
    """Collector that records the peak number of concurrent ``collect`` calls.

    Each call increments a shared in-flight counter (tracking the peak), waits
    on a ``Barrier`` so a full group of ``ceiling`` calls must be present
    simultaneously, then decrements.  Never touches the network.
    """

    def __init__(self, lock: threading.Lock, gate: threading.Barrier, state: dict):
        self._lock = lock
        self._gate = gate
        self._state = state  # {"inflight": int, "peak": int}

    def collect(self, device, definition) -> str:
        with self._lock:
            self._state["inflight"] += 1
            self._state["peak"] = max(self._state["peak"], self._state["inflight"])
        try:
            # Block until a full group of `ceiling` collections is here
            # together — deterministic overlap without sleeps.
            self._gate.wait()
        finally:
            with self._lock:
                self._state["inflight"] -= 1
        return "synthetic-config"


class _StubStorage:
    """Storage double: returns a valid ``ConfigRecord`` without writing disk."""

    def save(self, *, device_type, host, timestamp, extension, content,
             device_profile_id=None) -> ConfigRecord:
        return ConfigRecord(
            device_type=device_type,
            host=host,
            timestamp=timestamp,
            filename=f"{host}.{extension}",
            file_extension=extension,
            size_bytes=len(content),
            device_profile_id=device_profile_id,
        )


# A minimal definition stub: no probe command (so the probe branch is skipped
# without a definition_loader) and a file extension for ConfigRecord.
_STUB_DEF = SimpleNamespace(probe=SimpleNamespace(command=""), file_extension="txt")


def _job() -> BackupJob:
    return BackupJob(id="job", created_at=datetime.now(UTC))


def _request(n: int, prefix: str = "10.0.0") -> BackupRequest:
    return BackupRequest(
        devices=[
            DeviceTarget(
                type_key="X",
                host=f"{prefix}.{i}",
                credentials=DeviceCredentials(username="u", password="p"),
            )
            for i in range(n)
        ]
    )


@pytest.fixture
def small_global_ceiling(monkeypatch):
    """Shrink the process-wide ceiling and rebuild the limiter around it.

    ``reset_global_limiter`` on both edges keeps the small semaphore from
    leaking into (or being shadowed by) other tests in the same process.
    """
    ceiling = 2
    monkeypatch.setattr(backup_runner, "MAX_GLOBAL_BACKUP_CONCURRENCY", ceiling)
    backup_runner.reset_global_limiter()
    yield ceiling
    backup_runner.reset_global_limiter()


# ---------------------------------------------------------------------------
# The ceiling caps concurrency BELOW the per-job pool size (single job)
# ---------------------------------------------------------------------------


def test_global_ceiling_caps_collections_within_a_single_job(small_global_ceiling):
    """One job with 6 devices and a per-job pool of 6 workers, but a global
    ceiling of 2 → at most 2 collections ever run at once."""
    ceiling = small_global_ceiling
    n_devices = 6  # multiple of ceiling so every Barrier group is full
    assert n_devices % ceiling == 0

    state = {"inflight": 0, "peak": 0}
    lock = threading.Lock()
    gate = threading.Barrier(ceiling, timeout=15)
    collector = _PeakCollector(lock, gate, state)

    with patch(
        "netcanon.api.routes.backups.get_collector", return_value=collector
    ):
        backup_runner.run_backup_job(
            _job(), _request(n_devices), {"X": _STUB_DEF},
            storage=_StubStorage(), settings=Settings(),
        )

    # Hard invariant (semaphore): never more than the ceiling at once.
    # Reached-the-ceiling (Barrier): exactly the ceiling, not serialized to 1.
    assert state["peak"] == ceiling
    assert state["inflight"] == 0  # all permits released


# ---------------------------------------------------------------------------
# The ceiling caps concurrency ACROSS concurrent jobs (the actual r7 fix)
# ---------------------------------------------------------------------------


def test_global_ceiling_caps_collections_across_concurrent_jobs(small_global_ceiling):
    """3 jobs running at once, each with its own per-job pool, share ONE
    global ceiling of 2 → the SUM of in-flight collections never exceeds 2,
    which only the process-wide limiter (not the per-job pools) can enforce."""
    ceiling = small_global_ceiling
    n_jobs = 3
    per_job = 4
    total = n_jobs * per_job  # 12, a multiple of the ceiling (2)
    assert total % ceiling == 0

    state = {"inflight": 0, "peak": 0}
    lock = threading.Lock()
    gate = threading.Barrier(ceiling, timeout=15)
    collector = _PeakCollector(lock, gate, state)

    def run_one(batch: int) -> None:
        backup_runner.run_backup_job(
            _job(), _request(per_job, prefix=f"10.0.{batch}"),
            {"X": _STUB_DEF}, storage=_StubStorage(), settings=Settings(),
        )

    with patch(
        "netcanon.api.routes.backups.get_collector", return_value=collector
    ), ThreadPoolExecutor(max_workers=n_jobs) as pool:
        futures = [pool.submit(run_one, b) for b in range(n_jobs)]
        for f in futures:
            f.result()  # surface any unexpected exception

    assert state["peak"] == ceiling, (
        f"peak in-flight {state['peak']} != ceiling {ceiling}: the global "
        "limiter is not bounding the sum across concurrent jobs"
    )
    assert state["inflight"] == 0


# ---------------------------------------------------------------------------
# Defaults + env resolution + reset hook
# ---------------------------------------------------------------------------


def test_default_global_ceiling_equals_per_job_cap():
    """Default global ceiling == per-job cap, so a single job's behaviour is
    unchanged — it can still fill every worker slot; only the multi-job
    blow-up is newly bounded."""
    from netcanon import config

    assert config.MAX_GLOBAL_BACKUP_CONCURRENCY == MAX_BACKUP_CONCURRENCY


def test_env_override_sets_ceiling(monkeypatch):
    from netcanon import config

    monkeypatch.setenv("NETCANON_MAX_GLOBAL_BACKUP_CONCURRENCY", "25")
    assert config._resolve_global_backup_ceiling() == 25


def test_env_override_floors_at_one(monkeypatch):
    from netcanon import config

    monkeypatch.setenv("NETCANON_MAX_GLOBAL_BACKUP_CONCURRENCY", "0")
    assert config._resolve_global_backup_ceiling() == 1


def test_env_override_garbage_falls_back_to_default(monkeypatch):
    from netcanon import config

    monkeypatch.setenv("NETCANON_MAX_GLOBAL_BACKUP_CONCURRENCY", "not-a-number")
    with pytest.warns(UserWarning):
        assert config._resolve_global_backup_ceiling() == MAX_BACKUP_CONCURRENCY


def test_reset_global_limiter_rebuilds_at_current_size(monkeypatch):
    """After a reset the limiter rebuilds from the current ceiling value."""
    monkeypatch.setattr(backup_runner, "MAX_GLOBAL_BACKUP_CONCURRENCY", 4)
    backup_runner.reset_global_limiter()
    limiter = backup_runner._global_collection_limiter()
    # BoundedSemaphore exposes its initial value as _initial_value (CPython).
    assert limiter._initial_value == 4
    # Same instance returned on a second call (built once).
    assert backup_runner._global_collection_limiter() is limiter
    backup_runner.reset_global_limiter()
