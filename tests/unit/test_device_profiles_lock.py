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

import pytest

from netcanon.api.routes import device_profiles as routes_mod
from netcanon.models.device_profile import DeviceProfile
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
