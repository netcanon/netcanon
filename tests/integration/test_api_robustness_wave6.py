"""HEAD-review Wave 6 PR-B — API robustness negative-controls (C1/C2/C3/C5/C7).

Each test reproduces a bug the fix converts to a clean 4xx (+ rollback):

* C1 — ``/sanitize`` 500'd on any non-Parse/RenderError codec crash; now 422.
* C2 — ``GET /backups/{id}`` 500'd on a corrupt on-disk job JSON; now 404.
* C3 — schedule/profile create/toggle/delete left memory ahead of (or behind)
  disk on an ``OSError``; now a clean 500 + rollback so a restart can't
  resurrect / lose the object.
* C5 — ``GET /backups/{malformed-uuid}`` is 422 (path pattern guard), declared.
* C7 — ``PUT /devices/{id}`` with an unknown field is 422, not a silent 200.

The ``client`` fixture runs with ``raise_server_exceptions=True``, so the
pre-fix code (which let a raw exception escape to an unhandled 500) would ERROR
here rather than return a status — these are genuine negative-controls.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _profile_body(**overrides) -> dict:
    body = {
        "name": "Robustness Cisco",
        "type_key": "Cisco",
        "host": "10.0.0.9",
        "username": "admin",
        "password": "hunter2",
    }
    body.update(overrides)
    return body


def _schedule_body(**overrides) -> dict:
    body = {
        "name": "Robustness Schedule",
        "interval_minutes": 1440,
        "target_type_keys": ["Cisco"],
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# C1 — /sanitize broad-except net
# ---------------------------------------------------------------------------


class TestSanitizeBroadExcept:
    def test_unexpected_codec_crash_is_422_not_500(self, client, monkeypatch):
        """A non-Parse/RenderError crash in the sanitize pipeline (the
        crash-on-input class — a raw ``IndexError`` on a malformed line) must
        become a clean 422, not an uncaught 500 (C1)."""

        def _boom(*_a, **_k):
            raise IndexError("simulated codec crash on a malformed line")

        monkeypatch.setattr(
            "netcanon.api.routes.sanitize.sanitize_text", _boom
        )
        resp = client.post(
            "/api/v1/sanitize",
            data={"source_vendor": "aruba_aoss"},
            files={"config": ("c.cfg", "hostname x\n", "text/plain")},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "unexpectedly" in detail.lower()
        assert "IndexError" in detail  # the exception type is surfaced


# ---------------------------------------------------------------------------
# C2 — corrupt on-disk job JSON
# ---------------------------------------------------------------------------


class TestCorruptJobFile:
    _BOGUS_ID = "11111111-2222-4333-8444-555555555555"

    def _write(self, client, content: str) -> None:
        jobs_dir = client.app.state.jobs._store._dir
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / f"{self._BOGUS_ID}.json").write_text(
            content, encoding="utf-8"
        )

    def test_truncated_json_is_404_not_500(self, client):
        self._write(client, "{not valid json")
        resp = client.get(f"/api/v1/backups/{self._BOGUS_ID}")
        assert resp.status_code == 404

    def test_zero_byte_file_is_404_not_500(self, client):
        self._write(client, "")
        resp = client.get(f"/api/v1/backups/{self._BOGUS_ID}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# C3 — persistence rollback on OSError
# ---------------------------------------------------------------------------


def _make_raiser():
    def _raise(*_a, **_k):
        raise OSError("simulated disk failure (disk-full / AV file lock)")

    return _raise


class TestSchedulePersistenceRollback:
    def test_create_rolls_back_on_save_oserror(self, client, monkeypatch):
        monkeypatch.setattr(
            client.app.state.schedule_store, "save", _make_raiser()
        )
        resp = client.post("/api/v1/schedules/", json=_schedule_body())
        assert resp.status_code == 500
        # The failed insert must NOT survive in memory (else it is listed,
        # never fires, and vanishes on restart).
        assert client.app.state.schedules == {}
        assert client.get("/api/v1/schedules/").json() == []

    def test_delete_rolls_back_on_delete_oserror(self, client, monkeypatch):
        created = client.post(
            "/api/v1/schedules/", json=_schedule_body()
        ).json()
        sid = created["id"]
        monkeypatch.setattr(
            client.app.state.schedule_store, "delete", _make_raiser()
        )
        resp = client.delete(f"/api/v1/schedules/{sid}")
        assert resp.status_code == 500
        # The schedule must survive in memory (else it resurrects on restart
        # from the JSON that was never removed).
        assert sid in client.app.state.schedules

    def test_toggle_rolls_back_flag_on_save_oserror(self, client, monkeypatch):
        created = client.post(
            "/api/v1/schedules/", json=_schedule_body()
        ).json()
        sid = created["id"]
        before = client.app.state.schedules[sid].enabled
        monkeypatch.setattr(
            client.app.state.schedule_store, "save", _make_raiser()
        )
        resp = client.post(f"/api/v1/schedules/{sid}/toggle")
        assert resp.status_code == 500
        # The enabled flag must be rolled back to its pre-toggle value.
        assert client.app.state.schedules[sid].enabled == before


class TestProfileDeleteRollback:
    def test_delete_rolls_back_on_delete_oserror(self, client, monkeypatch):
        created = client.post(
            "/api/v1/devices/", json=_profile_body()
        ).json()
        pid = created["id"]
        monkeypatch.setattr(
            client.app.state.device_profile_store, "delete", _make_raiser()
        )
        resp = client.delete(f"/api/v1/devices/{pid}")
        assert resp.status_code == 500
        # The profile must survive in memory (else it resurrects on restart).
        assert pid in client.app.state.device_profiles


# ---------------------------------------------------------------------------
# C5 / C7 — contract honesty
# ---------------------------------------------------------------------------


class TestContractHonesty:
    def test_get_backup_malformed_uuid_is_422(self, client):
        """C5: the SEC-3 UUID path pattern rejects a non-UUID id with 422
        before the handler runs — now declared in the route ``responses``."""
        resp = client.get("/api/v1/backups/not-a-uuid")
        assert resp.status_code == 422

    def test_update_profile_unknown_field_is_422(self, client):
        """C7: a typo'd field in a partial PUT must 422 (extra='forbid'), not
        silently no-op with 200 on a PATCH-semantics endpoint."""
        created = client.post(
            "/api/v1/devices/", json=_profile_body()
        ).json()
        pid = created["id"]
        resp = client.put(f"/api/v1/devices/{pid}", json={"nots": "typo"})
        assert resp.status_code == 422
