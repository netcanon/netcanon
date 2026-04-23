"""
Tests for the file-based DeviceProfile store, with a focus on the new
optional fields added for layered-definitions support: ``os_version``,
``model``, and ``detected_facts``.

These round-trip tests would have caught a forgotten field in
:meth:`FileDeviceProfileStore.save` or
:meth:`FileDeviceProfileStore.load_all` — missing fields silently
default to ``None`` on read, which is exactly the silent-drop failure
mode this suite exists to prevent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netconfig.models.device_profile import DeviceProfile
from netconfig.storage.device_profile_store import FileDeviceProfileStore

pytestmark = pytest.mark.unit


def _base_profile(**overrides) -> DeviceProfile:
    """Minimal valid DeviceProfile; callers apply field overrides."""
    kwargs = {
        "name": "Test Switch",
        "type_key": "Cisco",
        "host": "10.0.0.1",
        "port": 22,
        "username": "admin",
        "password": "hunter2",
    }
    kwargs.update(overrides)
    return DeviceProfile(**kwargs)


class TestBackwardsCompatibility:
    """A profile saved WITHOUT the new fields (legacy shape) must
    still load cleanly.  This is the critical back-compat guarantee
    — existing encrypted JSON files on disk predate the schema
    extension and must keep working."""

    def test_profile_with_no_pinned_fields_roundtrips(self, tmp_path: Path):
        store = FileDeviceProfileStore(tmp_path)
        p = _base_profile()
        store.save(p)

        loaded = store.load_all()
        restored = loaded[p.id]
        assert restored.os_version is None
        assert restored.model is None
        assert restored.detected_facts is None


class TestPinnedFieldsPersist:
    """The new optional fields must round-trip through encrypt-to-disk
    and decrypt-back-to-memory without loss."""

    def test_os_version_pin_persists(self, tmp_path: Path):
        store = FileDeviceProfileStore(tmp_path)
        p = _base_profile(os_version="17.12")
        store.save(p)
        restored = store.load_all()[p.id]
        assert restored.os_version == "17.12"

    def test_model_pin_persists(self, tmp_path: Path):
        store = FileDeviceProfileStore(tmp_path)
        p = _base_profile(model="C9300-48P")
        store.save(p)
        restored = store.load_all()[p.id]
        assert restored.model == "C9300-48P"

    def test_both_pins_persist_together(self, tmp_path: Path):
        store = FileDeviceProfileStore(tmp_path)
        p = _base_profile(os_version="17.12", model="C9300-48P")
        store.save(p)
        restored = store.load_all()[p.id]
        assert restored.os_version == "17.12"
        assert restored.model == "C9300-48P"


class TestDetectedFactsPersist:
    """``detected_facts`` is populated server-side by the probe phase
    (future work); for now it's round-trip-safe through the store so
    a later commit can start writing to it without schema churn."""

    def test_detected_facts_dict_persists(self, tmp_path: Path):
        store = FileDeviceProfileStore(tmp_path)
        p = _base_profile(detected_facts={
            "detected_os_version": "17.12.04",
            "detected_model": "C9300-48P",
            "firmware_build": "cat9k_iosxe.17.12.04a.SPA.bin",
            "probe_timestamp": "2026-04-22T10:15:30Z",
            "probe_codec_version": "0.1",
        })
        store.save(p)
        restored = store.load_all()[p.id]
        assert restored.detected_facts is not None
        assert restored.detected_facts["detected_os_version"] == "17.12.04"
        assert restored.detected_facts["detected_model"] == "C9300-48P"
        assert len(restored.detected_facts) == 5

    def test_detected_facts_none_roundtrips(self, tmp_path: Path):
        """Default value must survive the JSON round-trip as None
        rather than being promoted to an empty dict (which would
        masquerade as "probed and found nothing" — different
        semantics from "never probed")."""
        store = FileDeviceProfileStore(tmp_path)
        p = _base_profile()
        store.save(p)
        restored = store.load_all()[p.id]
        assert restored.detected_facts is None


class TestCredentialsStillEncrypted:
    """Regression guard: the new fields must not accidentally disturb
    the existing credential-encryption flow.  The two password fields
    should still be encrypted-on-disk and decrypted-on-load.  Absent
    this check, a refactor that shuffled field order in ``save`` could
    silently leak plaintext to disk."""

    def test_password_is_encrypted_on_disk(self, tmp_path: Path):
        store = FileDeviceProfileStore(tmp_path)
        p = _base_profile(
            password="my-super-secret-password",
            os_version="17.12",
        )
        store.save(p)
        raw_disk = (tmp_path / f"{p.id}.json").read_text(encoding="utf-8")
        assert "my-super-secret-password" not in raw_disk
        # Decryption on load still works.
        restored = store.load_all()[p.id]
        assert restored.password == "my-super-secret-password"
        assert restored.os_version == "17.12"
