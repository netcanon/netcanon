"""
Integration tests for backups against the shipped Arista EOS 4.32
device definition.

Drops the real ``definitions/arista/eos/4.32.yaml`` into a tmp
``definitions/`` tree (alongside the test Cisco + OPNsense YAML the
root conftest already writes) and exercises POST /api/v1/backups +
GET /api/v1/backups/{id} via the same ``get_collector`` patch
pattern other backup integration tests use.

Real SSH never runs — the collector factory is replaced with a
``FakeCollector`` returning a canned EOS running-config snippet so
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

from netcanon.config import Settings
from netcanon.main import create_app
from tests.conftest import FakeCollector

pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parents[2]
ARISTA_DEF_SRC = REPO_ROOT / "definitions" / "arista" / "eos" / "4.32.yaml"


# Synthetic Arista EOS running-config — small but recognisable shape:
# hostname / vlan / interface / username with an obviously fake hash.
# Per CLAUDE.md hard rule on test fixtures, the secret looks plausible
# but is not a real captured hash.
ARISTA_FAKE_OUTPUT = """\
! Command: show running-config
! device: TestSwitchA (DCS-7050SX-64-F, EOS-4.32.0F)
!
hostname TestSwitchA
!
spanning-tree mode mstp
!
no aaa root
!
username admin privilege 15 secret sha512 $6$fakehash$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
!
vlan 100
   name Tenant_100
!
interface Ethernet1
   description uplink-to-spine
   switchport access vlan 100
!
interface Management1
   ip address 10.0.0.2/24
!
end
"""


# ---------------------------------------------------------------------------
# Fixtures local to this module
# ---------------------------------------------------------------------------


@pytest.fixture()
def arista_settings(sample_definitions_dir, tmp_path) -> Settings:
    """``Settings`` whose definitions dir contains the real Arista YAML
    on top of the test Cisco + OPNsense YAML."""
    arista_dir = sample_definitions_dir / "arista" / "eos"
    arista_dir.mkdir(parents=True)
    shutil.copy(ARISTA_DEF_SRC, arista_dir / "4.32.yaml")

    configs_dir = tmp_path / "configs"
    configs_dir.mkdir(exist_ok=True)
    return Settings(
        definitions_dir=sample_definitions_dir,
        configs_dir=configs_dir,
        backup_concurrency=1,
    )


@pytest.fixture()
def arista_app(arista_settings):
    """FastAPI app loaded with the real Arista definition + test Cisco/OPNsense."""
    return create_app(arista_settings)


@pytest.fixture()
def arista_client(arista_app):
    """``TestClient`` with the SSH layer mocked by a FakeCollector that
    returns the canned EOS config."""
    fake = FakeCollector(output=ARISTA_FAKE_OUTPUT)
    with patch(
        "netcanon.api.routes.backups.get_collector",
        return_value=fake,
    ):
        with TestClient(arista_app, raise_server_exceptions=True) as c:
            yield c


def _arista_device(host: str = "192.168.60.10") -> dict:
    return {
        "type_key": "Arista",
        "host": host,
        "credentials": {
            "username": "admin",
            "password": "fake-password",
        },
    }


def _post_and_get(client, devices: list[dict] | None = None) -> dict:
    if devices is None:
        devices = [_arista_device()]
    resp = client.post("/api/v1/backups", json={"devices": devices})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]
    return client.get(f"/api/v1/backups/{job_id}").json()


# ---------------------------------------------------------------------------
# Definition discoverability
# ---------------------------------------------------------------------------


class TestAristaDefinitionDiscoverable:
    def test_listed_in_definitions(self, arista_client):
        resp = arista_client.get("/api/v1/definitions/")
        assert resp.status_code == 200
        keys = {d["type_key"] for d in resp.json()}
        assert "Arista" in keys

    def test_get_by_key(self, arista_client):
        resp = arista_client.get("/api/v1/definitions/Arista")
        assert resp.status_code == 200
        data = resp.json()
        assert data["vendor"].lower() == "arista"
        assert data["collector"]["netmiko_device_type"] == "arista_eos"


# ---------------------------------------------------------------------------
# POST + GET happy path
# ---------------------------------------------------------------------------


class TestAristaBackupHappyPath:
    def test_post_returns_202(self, arista_client):
        resp = arista_client.post(
            "/api/v1/backups", json={"devices": [_arista_device()]}
        )
        assert resp.status_code == 202

    def test_post_response_is_pending(self, arista_client):
        # Hard rule: POST always shows pending — final state is via GET.
        resp = arista_client.post(
            "/api/v1/backups", json={"devices": [_arista_device()]}
        )
        assert resp.json()["status"] == "pending"

    def test_job_completes_after_get(self, arista_client):
        job = _post_and_get(arista_client)
        assert job["status"] == "completed"

    def test_result_status_success(self, arista_client):
        job = _post_and_get(arista_client)
        assert job["results"][0]["status"] == "success"

    def test_result_host_matches_request(
        self, arista_client
    ):
        job = _post_and_get(
            arista_client, devices=[_arista_device(host="10.40.50.60")]
        )
        assert job["results"][0]["host"] == "10.40.50.60"

    def test_result_has_config_record(self, arista_client):
        job = _post_and_get(arista_client)
        record = job["results"][0]["config_record"]
        assert record is not None
        assert "filename" in record


# ---------------------------------------------------------------------------
# File landing — the captured config lands in configs/ with .cfg ext
# ---------------------------------------------------------------------------


class TestAristaBackupFileLanding:
    def test_config_file_listed_via_api(self, arista_client):
        _post_and_get(arista_client)
        resp = arista_client.get("/api/v1/configs/")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_config_filename_uses_cfg_extension(self, arista_client):
        _post_and_get(arista_client)
        configs = arista_client.get("/api/v1/configs/").json()
        # We don't pin host-specific naming here — just the extension,
        # which is governed by the definition's file_extension field.
        assert any(c["filename"].endswith(".cfg") for c in configs)

    def test_config_contents_round_trip(self, arista_client):
        """The fake collector's output is what gets persisted; readback
        proves the pipeline didn't mangle CR/LF or strip the body."""
        _post_and_get(arista_client)
        configs = arista_client.get("/api/v1/configs/").json()
        assert configs, "expected at least one config file after backup"
        filename = configs[0]["filename"]
        body = arista_client.get(f"/api/v1/configs/{filename}").text
        # Marker lines from ARISTA_FAKE_OUTPUT must appear verbatim.
        assert "hostname TestSwitchA" in body
        assert "interface Ethernet1" in body
        assert "vlan 100" in body


# ---------------------------------------------------------------------------
# Failure path — collector raises, job marked failed
# ---------------------------------------------------------------------------


class _RaisingCollector:
    def collect(self, device, definition):  # noqa: ARG002
        raise RuntimeError("simulated EOS SSH timeout")


class TestAristaBackupFailureSurface:
    def test_collector_failure_marks_result_failed(self, arista_app):
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=_RaisingCollector(),
        ):
            with TestClient(arista_app, raise_server_exceptions=True) as c:
                resp = c.post(
                    "/api/v1/backups", json={"devices": [_arista_device()]}
                )
                assert resp.status_code == 202
                job = c.get(f"/api/v1/backups/{resp.json()['id']}").json()

        # Single device, single failure → job-level status is "failed".
        assert job["status"] == "failed"
        assert job["results"][0]["status"] == "failed"
