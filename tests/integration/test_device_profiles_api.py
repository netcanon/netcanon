"""
Integration tests for the device-profile API with a focus on the
layered-definitions pin fields added in P1C1 (and surfaced in the UI
by P1C2).  ``os_version`` / ``model`` / ``detected_facts`` must
round-trip through POST / GET / PUT without loss.

Layer-A fine-grained store tests live at
``tests/unit/test_device_profile_store.py``; this file verifies the
HTTP contract end-to-end through the FastAPI router + pydantic
request/response models.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _create_body(**overrides) -> dict:
    body = {
        "name": "Test Cisco",
        "type_key": "Cisco",
        "host": "10.0.0.1",
        "username": "admin",
        "password": "hunter2",
    }
    body.update(overrides)
    return body


class TestCreateWithPins:
    """``POST /api/v1/devices`` accepts + persists the new pin fields."""

    def test_create_with_os_version_pin(self, client):
        resp = client.post(
            "/api/v1/devices/", json=_create_body(os_version="17.12"),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["os_version"] == "17.12"
        assert body["model"] is None
        assert body["detected_facts"] is None

    def test_create_with_both_pins(self, client):
        resp = client.post(
            "/api/v1/devices/",
            json=_create_body(os_version="17.12", model="C9300-48P"),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["os_version"] == "17.12"
        assert body["model"] == "C9300-48P"

    def test_create_without_pins_defaults_to_none(self, client):
        """Backwards-compat: creating a profile without pins leaves
        them null.  Every pre-P1C1 client continues to work."""
        resp = client.post("/api/v1/devices/", json=_create_body())
        assert resp.status_code == 201
        body = resp.json()
        assert body["os_version"] is None
        assert body["model"] is None


class TestUpdatePins:
    """``PUT /api/v1/devices/{id}`` updates pin fields.

    UI contract: omitted fields = "keep existing" (handler filters
    ``None`` values before model_copy).  So the UI sends pins only
    when they have values; blanks are interpreted as "unchanged"."""

    def test_update_adds_os_version_pin(self, client):
        created = client.post(
            "/api/v1/devices/", json=_create_body()
        ).json()
        profile_id = created["id"]
        # Later: operator discovers their firmware version and pins it.
        resp = client.put(
            f"/api/v1/devices/{profile_id}",
            json={"os_version": "17.12"},
        )
        assert resp.status_code == 200
        assert resp.json()["os_version"] == "17.12"

    def test_update_changes_model_pin(self, client):
        created = client.post(
            "/api/v1/devices/",
            json=_create_body(model="C9300-24U"),
        ).json()
        profile_id = created["id"]
        resp = client.put(
            f"/api/v1/devices/{profile_id}",
            json={"model": "C9300-48U"},
        )
        assert resp.status_code == 200
        assert resp.json()["model"] == "C9300-48U"

    def test_update_without_pin_fields_preserves_pins(self, client):
        """Regression: editing the host / notes of a profile with
        pins set must NOT accidentally clear the pins.  This locks
        in the "blank = keep" UI pattern's round-trip behaviour."""
        created = client.post(
            "/api/v1/devices/",
            json=_create_body(os_version="17.12", model="C9300-48P"),
        ).json()
        profile_id = created["id"]
        resp = client.put(
            f"/api/v1/devices/{profile_id}",
            json={"notes": "updated notes"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Pins preserved.
        assert body["os_version"] == "17.12"
        assert body["model"] == "C9300-48P"
        assert body["notes"] == "updated notes"


class TestGetReturnsAllFields:
    """``GET /api/v1/devices/{id}`` surfaces pins + detected_facts in
    the response so the UI form can pre-fill them."""

    def test_get_includes_pin_fields(self, client):
        created = client.post(
            "/api/v1/devices/",
            json=_create_body(os_version="17.12", model="C9300-48P"),
        ).json()
        profile_id = created["id"]
        resp = client.get(f"/api/v1/devices/{profile_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["os_version"] == "17.12"
        assert body["model"] == "C9300-48P"
        # detected_facts starts null (probe hasn't run yet in P1C2).
        assert body["detected_facts"] is None


class TestCredentialsNeverSerialised:
    """Credentials are write-only over the API (2026-06 review finding #1).

    ``password`` / ``enable_password`` are accepted in create / update
    request bodies but must never appear in *any* response — the
    ``DeviceProfilePublic`` response model strips them so the decrypted
    value never crosses the API boundary."""

    _CRED_KEYS = ("password", "enable_password")

    def test_create_response_omits_credentials(self, client):
        body = client.post(
            "/api/v1/devices/",
            json=_create_body(enable_password="enable-secret"),
        ).json()
        for key in self._CRED_KEYS:
            assert key not in body, f"POST response leaked {key!r}"
        # Non-secret fields are still present.
        assert body["username"] == "admin"
        assert body["host"] == "10.0.0.1"

    def test_get_response_omits_credentials(self, client):
        profile_id = client.post(
            "/api/v1/devices/", json=_create_body(enable_password="enable-secret")
        ).json()["id"]
        body = client.get(f"/api/v1/devices/{profile_id}").json()
        for key in self._CRED_KEYS:
            assert key not in body, f"GET response leaked {key!r}"

    def test_list_response_omits_credentials(self, client):
        client.post("/api/v1/devices/", json=_create_body(host="10.0.0.1"))
        client.post("/api/v1/devices/", json=_create_body(host="10.0.0.2"))
        items = client.get("/api/v1/devices/").json()
        assert len(items) >= 2
        for item in items:
            for key in self._CRED_KEYS:
                assert key not in item, f"LIST response leaked {key!r}"

    def test_update_response_omits_credentials(self, client):
        profile_id = client.post(
            "/api/v1/devices/", json=_create_body()
        ).json()["id"]
        # Change the password via PUT; the response must still not echo it.
        body = client.put(
            f"/api/v1/devices/{profile_id}",
            json={"password": "rotated-secret", "notes": "rotated"},
        ).json()
        for key in self._CRED_KEYS:
            assert key not in body, f"PUT response leaked {key!r}"
        assert body["notes"] == "rotated"


def _raise_oserror(*_args, **_kwargs):
    raise OSError("disk full")


class TestPersistFailureRollback:
    """Create/update roll the in-memory registry back when the sole-persistence
    disk save fails, so the registry can't drift ahead of disk (review #47b)."""

    def test_create_rolls_back_on_save_oserror(self, client, monkeypatch):
        monkeypatch.setattr(
            client.app.state.device_profile_store, "save", _raise_oserror
        )
        resp = client.post("/api/v1/devices/", json=_create_body())
        assert resp.status_code == 500
        # No phantom profile left behind in the in-memory registry.
        assert client.app.state.device_profiles == {}

    def test_update_rolls_back_to_pre_update_on_save_oserror(
        self, client, monkeypatch
    ):
        pid = client.post(
            "/api/v1/devices/", json=_create_body(os_version="17.12")
        ).json()["id"]
        monkeypatch.setattr(
            client.app.state.device_profile_store, "save", _raise_oserror
        )
        resp = client.put(f"/api/v1/devices/{pid}", json={"os_version": "18.1"})
        assert resp.status_code == 500
        # The in-memory profile keeps its pre-update value (not the 18.1 that
        # failed to persist).
        assert client.app.state.device_profiles[pid].os_version == "17.12"
