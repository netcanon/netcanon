"""Concurrency guard for the shared device-profile registry (review #10).

The backup worker thread mutates a profile's ``detected_facts`` and re-saves
it while route handlers (run in FastAPI's threadpool for sync ``def``
endpoints) create / update / delete the same dict + on-disk files.  A
``threading.Lock`` (``DEVICE_PROFILE_REGISTRY_LOCK``) serialises every
read-modify-write-persist + delete critical section so a delete-then-save
interleaving can't resurrect a just-deleted profile to disk.

These tests pin (a) that the lock is one shared object across the producer
and consumer modules and (b) that the locked persist/delete pattern keeps the
in-memory registry and the on-disk store in agreement under contention.
"""

from __future__ import annotations

import threading
import time
import types

import pytest
from fastapi import HTTPException

from netcanon.api.routes import device_profiles as routes_mod
from netcanon.models.device_profile import DeviceProfile, DeviceProfileCreate
from netcanon.services import backup_runner as runner_mod
from netcanon.storage.device_profile_store import (
    DEVICE_PROFILE_REGISTRY_LOCK,
    FileDeviceProfileStore,
)

pytestmark = pytest.mark.unit


def test_lock_is_a_lock() -> None:
    assert hasattr(DEVICE_PROFILE_REGISTRY_LOCK, "acquire")
    assert hasattr(DEVICE_PROFILE_REGISTRY_LOCK, "release")


def test_lock_is_shared_across_producer_and_consumer() -> None:
    """The backup worker and the route handlers must guard the same object —
    a per-module lock would not serialise anything."""
    assert runner_mod.DEVICE_PROFILE_REGISTRY_LOCK is DEVICE_PROFILE_REGISTRY_LOCK
    assert routes_mod.DEVICE_PROFILE_REGISTRY_LOCK is DEVICE_PROFILE_REGISTRY_LOCK


def _profile(pid: str) -> DeviceProfile:
    return DeviceProfile(
        id=pid,
        name="r1",
        type_key="Cisco",
        host="10.0.0.1",
        username="admin",
        password="hunter2",
    )


def test_locked_persist_and_delete_never_resurrect(tmp_path) -> None:
    """Race the worker's locked ``persist detected_facts`` against a route's
    locked ``delete`` many times; the on-disk store and the in-memory
    registry must always agree (no file left behind for a deleted id)."""
    store = FileDeviceProfileStore(tmp_path)
    registry: dict[str, DeviceProfile] = {}
    pid = "race-id"

    def persist() -> None:  # mirrors backup_runner's locked critical section
        with DEVICE_PROFILE_REGISTRY_LOCK:
            prof = registry.get(pid)
            if prof is not None:
                prof.detected_facts = {"detected_os_version": "17.12"}
                store.save(prof)

    def delete() -> None:  # mirrors the delete route's locked critical section
        with DEVICE_PROFILE_REGISTRY_LOCK:
            if registry.pop(pid, None) is not None:
                store.delete(pid)

    for _ in range(200):
        registry[pid] = _profile(pid)
        store.save(registry[pid])
        ta = threading.Thread(target=persist)
        tb = threading.Thread(target=delete)
        ta.start()
        tb.start()
        ta.join()
        tb.join()
        on_disk = pid in store.load_all()
        in_memory = pid in registry
        assert on_disk == in_memory, (
            "registry/disk disagreement (resurrection): "
            f"on_disk={on_disk} in_memory={in_memory}"
        )


def test_create_cap_check_is_inside_lock(tmp_path) -> None:
    """The 1000-profile cap must be evaluated under the registry lock (#44).

    Deterministic interleave: hold the lock, start a create (it must block on
    the lock *before* it evaluates the cap — that is the fix), then fill the
    last slot and release.  A create that checked the cap outside the lock
    already passed at 999 and inserts a 1001st profile; the fixed create
    re-reads 1000 under the lock and returns 409.
    """
    store = FileDeviceProfileStore(tmp_path)
    registry = {f"p{i}": _profile(f"p{i}") for i in range(999)}  # one slot left
    body = DeviceProfileCreate(
        name="new",
        type_key="Cisco",
        host="10.0.0.9",
        username="admin",
        password="hunter2",
    )
    outcome: dict[str, object] = {}
    # create_device_profile validates type_key against loaded definitions
    # (review #53); on a direct call the Depends() default isn't resolved, so
    # pass a stand-in — _require_known_type_key only tests key membership.
    defs = {"Cisco": None}

    def _create() -> None:
        try:
            routes_mod.create_device_profile(
                body,
                device_profiles=registry,
                device_profile_store=store,
                definitions=defs,
            )
            outcome["result"] = "created"
        except HTTPException as exc:
            outcome["result"] = exc.status_code

    with DEVICE_PROFILE_REGISTRY_LOCK:
        t = threading.Thread(target=_create)
        t.start()
        time.sleep(0.1)  # let the thread reach the lock (fixed) / the check (unfixed)
        registry["filler"] = _profile("filler")  # now exactly at the 1000 cap
    t.join()

    assert outcome["result"] == 409, (
        f"create at cap returned {outcome['result']!r}, not 409 — the cap check "
        "ran outside the lock, before the last slot filled"
    )
    assert len(registry) == 1000, f"cap breached: {len(registry)}"


def test_delete_snapshots_schedules_no_iteration_race(tmp_path) -> None:
    """delete_device_profile must snapshot ``app.state.schedules`` under
    ``SCHEDULE_REGISTRY_LOCK`` before iterating it (#43).

    Deterministic reproduction: a schedule whose ``target_device_ids`` mutates
    the backing dict when read.  Iterating the LIVE dict then raises
    ``RuntimeError: dictionary changed size during iteration``; iterating a
    snapshot list is immune.
    """
    store = FileDeviceProfileStore(tmp_path)
    schedules: dict[str, object] = {}

    class _MutatingSchedule:
        """Reading ``target_device_ids`` injects a new key into the backing
        dict — forcing a size change mid-iteration iff delete walks the live
        dict rather than a snapshot."""

        name = "evil"
        _n = 0

        def __init__(self, backing: dict) -> None:
            self._backing = backing

        @property
        def target_device_ids(self) -> list:
            type(self)._n += 1
            self._backing[f"injected{type(self)._n}"] = types.SimpleNamespace(
                name="x", target_device_ids=[]
            )
            return []

    schedules["a"] = _MutatingSchedule(schedules)
    for i in range(5):  # padding so the values-view iteration takes >1 step
        schedules[f"pad{i}"] = types.SimpleNamespace(
            name=f"pad{i}", target_device_ids=[]
        )

    state = types.SimpleNamespace(schedules=schedules)
    request = types.SimpleNamespace(app=types.SimpleNamespace(state=state))
    pid = "race-id"
    registry: dict[str, DeviceProfile] = {pid: _profile(pid)}
    store.save(registry[pid])

    # Unfixed: RuntimeError escapes here.  Fixed: clean delete off the snapshot.
    routes_mod.delete_device_profile(
        pid, request, device_profiles=registry, device_profile_store=store
    )
    assert pid not in registry
