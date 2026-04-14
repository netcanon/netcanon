"""
Integration tests for ``GET /api/v1/definitions/`` and
``GET /api/v1/definitions/{type_key}``.

The test app is loaded with two test definitions (Cisco + OPNsense) from
``tests/conftest.py``'s ``sample_definitions_dir`` fixture.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestListDefinitions:
    def test_returns_200(self, client):
        resp = client.get("/api/v1/definitions/")
        assert resp.status_code == 200

    def test_returns_list(self, client):
        resp = client.get("/api/v1/definitions/")
        assert isinstance(resp.json(), list)

    def test_returns_both_test_definitions(self, client):
        resp = client.get("/api/v1/definitions/")
        keys = {d["type_key"] for d in resp.json()}
        assert keys == {"Cisco", "OPNsense"}

    def test_sorted_by_type_key(self, client):
        resp = client.get("/api/v1/definitions/")
        keys = [d["type_key"] for d in resp.json()]
        assert keys == sorted(keys)

    def test_definition_has_expected_fields(self, client):
        resp = client.get("/api/v1/definitions/")
        cisco = next(d for d in resp.json() if d["type_key"] == "Cisco")
        assert cisco["vendor"] == "Cisco"
        assert cisco["os"] == "IOS-XE"
        assert cisco["file_extension"] == "cfg"
        assert "collector" in cisco
        assert cisco["collector"]["strategy"] == "netmiko"
        assert cisco["collector"]["netmiko_device_type"] == "cisco_xe"

    def test_source_file_not_in_response(self, client):
        """source_file is excluded from serialisation (Field(..., exclude=True))."""
        resp = client.get("/api/v1/definitions/")
        for d in resp.json():
            assert "source_file" not in d

    def test_opnsense_paramiko_shell(self, client):
        resp = client.get("/api/v1/definitions/")
        opn = next(d for d in resp.json() if d["type_key"] == "OPNsense")
        assert opn["collector"]["strategy"] == "paramiko_shell"

    def test_cisco_connection_flags(self, client):
        resp = client.get("/api/v1/definitions/")
        cisco = next(d for d in resp.json() if d["type_key"] == "Cisco")
        assert cisco["connection"]["needs_enable"] is True
        assert cisco["connection"]["handle_paging"] is True


class TestGetDefinition:
    def test_known_key_returns_200(self, client):
        resp = client.get("/api/v1/definitions/Cisco")
        assert resp.status_code == 200

    def test_known_key_returns_correct_definition(self, client):
        resp = client.get("/api/v1/definitions/Cisco")
        data = resp.json()
        assert data["type_key"] == "Cisco"
        assert data["vendor"] == "Cisco"

    def test_opnsense_key(self, client):
        resp = client.get("/api/v1/definitions/OPNsense")
        assert resp.status_code == 200
        assert resp.json()["type_key"] == "OPNsense"

    def test_unknown_key_returns_404(self, client):
        resp = client.get("/api/v1/definitions/NonExistent")
        assert resp.status_code == 404

    def test_404_detail_mentions_key(self, client):
        resp = client.get("/api/v1/definitions/Banana")
        assert "Banana" in resp.json()["detail"]

    def test_case_sensitive_key(self, client):
        """Type keys are case-sensitive — 'cisco' should not match 'Cisco'."""
        resp = client.get("/api/v1/definitions/cisco")
        assert resp.status_code == 404


class TestReloadDefinitions:
    def test_reload_returns_200(self, client):
        resp = client.post("/api/v1/definitions/reload")
        assert resp.status_code == 200

    def test_reload_returns_loaded_count(self, client):
        resp = client.post("/api/v1/definitions/reload")
        assert resp.json()["loaded"] == 2  # Cisco + OPNsense

    def test_reload_returns_type_keys(self, client):
        resp = client.post("/api/v1/definitions/reload")
        assert set(resp.json()["type_keys"]) == {"Cisco", "OPNsense"}

    def test_definitions_accessible_after_reload(self, client):
        """Reload must not corrupt the registry — GET still returns both defs."""
        client.post("/api/v1/definitions/reload")
        resp = client.get("/api/v1/definitions/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_reload_is_idempotent(self, client):
        """Calling reload twice leaves the registry identical."""
        client.post("/api/v1/definitions/reload")
        first  = client.get("/api/v1/definitions/").json()
        client.post("/api/v1/definitions/reload")
        second = client.get("/api/v1/definitions/").json()
        assert [d["type_key"] for d in first] == [d["type_key"] for d in second]
