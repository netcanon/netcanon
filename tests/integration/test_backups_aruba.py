"""
Integration tests for backups against the shipped Aruba AOS-S 16.x
device definition.

Drops the real ``definitions/aruba/aos-s/16.x.yaml`` into a tmp
``definitions/`` tree (alongside the test Cisco + OPNsense YAML the
root conftest already writes) and exercises POST /api/v1/backups +
GET /api/v1/backups/{id} via the same ``get_collector`` patch
pattern other backup integration tests use.

Real SSH never runs — the collector factory is replaced with a
``FakeCollector`` returning a canned AOS-S running-config snippet so
the backup pipeline writes a real ``.cfg`` file under the temp
configs dir and can round-trip the file name + contents back to the
caller.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from netconfig.config import Settings
from netconfig.main import create_app
from tests.conftest import FakeCollector

pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parents[2]
ARUBA_DEF_SRC = REPO_ROOT / "definitions" / "aruba" / "aos-s" / "16.x.yaml"


# Synthetic AOS-S running-config — small but recognisable shape:
# vlan blocks, interface block, manager password line.  No real
# secrets — the password hash is obviously fake (per CLAUDE.md hard
# rule on test fixtures).
ARUBA_FAKE_OUTPUT = """\
; J9776A Configuration Editor; Created on release #WC.16.10.0023
; Ver #14:fa.ke.b1.t.s:00

hostname "TestSwitchA"

module 1 type j9776a

vlan 1
   name "DEFAULT_VLAN"
   untagged 1-24
   ip address 10.0.0.2 255.255.255.0
   exit

vlan 100
   name "Mgmt"
   tagged 1
   ip address 10.0.100.1 255.255.255.0
   exit

password manager user-name "admin" sha1 "0000000000000000000000000000000000000000"
"""


# ---------------------------------------------------------------------------
# Fixtures local to this module
# ---------------------------------------------------------------------------


@pytest.fixture()
def aruba_settings(sample_definitions_dir, tmp_path) -> Settings:
    """``Settings`` whose definitions dir contains the real Aruba YAML
    on top of the test Cisco + OPNsense YAML."""
    aruba_dir = sample_definitions_dir / "aruba" / "aos-s"
    aruba_dir.mkdir(parents=True)
    shutil.copy(ARUBA_DEF_SRC, aruba_dir / "16.x.yaml")

    configs_dir = tmp_path / "configs"
    configs_dir.mkdir(exist_ok=True)
    return Settings(
        definitions_dir=sample_definitions_dir,
        configs_dir=configs_dir,
        backup_concurrency=1,
    )


@pytest.fixture()
def aruba_app(aruba_settings):
    """FastAPI app loaded with the real Aruba definition + test Cisco/OPNsense."""
    return create_app(aruba_settings)


@pytest.fixture()
def aruba_client(aruba_app):
    """``TestClient`` with the SSH layer mocked by a FakeCollector that
    returns the canned AOS-S config."""
    fake = FakeCollector(output=ARUBA_FAKE_OUTPUT)
    with patch(
        "netconfig.api.routes.backups.get_collector",
        return_value=fake,
    ):
        with TestClient(aruba_app, raise_server_exceptions=True) as c:
            yield c


def _aruba_device(host: str = "192.168.50.10") -> dict:
    return {
        "type_key": "aruba_aoss_16.x",
        "host": host,
        "credentials": {
            "username": "admin",
            "password": "fake-password",
        },
    }


def _post_and_get(client, devices: list[dict] | None = None) -> dict:
    if devices is None:
        devices = [_aruba_device()]
    resp = client.post("/api/v1/backups", json={"devices": devices})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]
    return client.get(f"/api/v1/backups/{job_id}").json()


# ---------------------------------------------------------------------------
# Definition discoverability
# ---------------------------------------------------------------------------


class TestArubaDefinitionDiscoverable:
    def test_listed_in_definitions(self, aruba_client):
        resp = aruba_client.get("/api/v1/definitions/")
        assert resp.status_code == 200
        keys = {d["type_key"] for d in resp.json()}
        assert "aruba_aoss_16.x" in keys

    def test_get_by_key(self, aruba_client):
        resp = aruba_client.get("/api/v1/definitions/aruba_aoss_16.x")
        assert resp.status_code == 200
        data = resp.json()
        assert data["vendor"].lower() == "aruba"
        assert data["collector"]["netmiko_device_type"] == "aruba_osswitch"


# ---------------------------------------------------------------------------
# POST + GET happy path
# ---------------------------------------------------------------------------


class TestArubaBackupHappyPath:
    def test_post_returns_202(self, aruba_client):
        resp = aruba_client.post(
            "/api/v1/backups", json={"devices": [_aruba_device()]}
        )
        assert resp.status_code == 202

    def test_post_response_is_pending(self, aruba_client):
        # Hard rule: POST always shows pending — final state is via GET.
        resp = aruba_client.post(
            "/api/v1/backups", json={"devices": [_aruba_device()]}
        )
        assert resp.json()["status"] == "pending"

    def test_job_completes_after_get(self, aruba_client):
        job = _post_and_get(aruba_client)
        assert job["status"] == "completed"

    def test_result_status_success(self, aruba_client):
        job = _post_and_get(aruba_client)
        assert job["results"][0]["status"] == "success"

    def test_result_host_matches_request(self, aruba_client):
        job = _post_and_get(aruba_client, devices=[_aruba_device(host="10.20.30.40")])
        assert job["results"][0]["host"] == "10.20.30.40"

    def test_result_has_config_record(self, aruba_client):
        job = _post_and_get(aruba_client)
        record = job["results"][0]["config_record"]
        assert record is not None
        assert "filename" in record


# ---------------------------------------------------------------------------
# File landing — the captured config lands in configs/ with .cfg ext
# ---------------------------------------------------------------------------


class TestArubaBackupFileLanding:
    def test_config_file_listed_via_api(self, aruba_client):
        _post_and_get(aruba_client)
        resp = aruba_client.get("/api/v1/configs/")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_config_filename_uses_cfg_extension(self, aruba_client):
        _post_and_get(aruba_client)
        configs = aruba_client.get("/api/v1/configs/").json()
        # We don't pin host-specific naming here — just the extension,
        # which is governed by the definition's file_extension field.
        assert any(c["filename"].endswith(".cfg") for c in configs)

    def test_config_record_filename_starts_with_type_key(self, aruba_client):
        """The persisted filename embeds the type_key as its prefix; this
        proves the backup pipeline picked up the Aruba definition rather
        than silently falling back to a different family."""
        job = _post_and_get(aruba_client)
        record = job["results"][0]["config_record"]
        assert record["filename"].startswith("aruba_aoss_16.x_")


# ---------------------------------------------------------------------------
# Failure path — collector raises, job marked failed
# ---------------------------------------------------------------------------


class _RaisingCollector:
    def collect(self, device, definition):  # noqa: ARG002
        raise RuntimeError("simulated AOS-S SSH timeout")


class TestArubaBackupFailureSurface:
    def test_collector_failure_marks_result_failed(self, aruba_app):
        with patch(
            "netconfig.api.routes.backups.get_collector",
            return_value=_RaisingCollector(),
        ):
            with TestClient(aruba_app, raise_server_exceptions=True) as c:
                resp = c.post(
                    "/api/v1/backups", json={"devices": [_aruba_device()]}
                )
                assert resp.status_code == 202
                job = c.get(f"/api/v1/backups/{resp.json()['id']}").json()

        # Single device, single failure → job-level status is "failed".
        assert job["status"] == "failed"
        assert job["results"][0]["status"] == "failed"
