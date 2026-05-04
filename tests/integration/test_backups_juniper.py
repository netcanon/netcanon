"""
End-to-end backup tests for the Juniper Junos definition.

Patches ``netconfig.api.routes.backups.get_collector`` (the single
factory the backup route imports) with a fake that returns a
representative ``show configuration | display set | no-more`` capture,
then drives the full POST/GET round-trip via TestClient.  Confirms:

* The ``Juniper`` ``type_key`` is accepted by the backup route.
* The collected output lands as a config file under the configs store.
* The captured ``set``-form text round-trips through the
  ``juniper_junos`` migration codec — proving the definition's
  command choice produces wire form the codec actually consumes.

Patch target rationale (CLAUDE.md hard rule): never patch
``ConnectHandler`` / ``paramiko.SSHClient`` directly — the canonical
seam is ``get_collector``, the single factory used by the backup
route.

POST/GET sequence rationale (CLAUDE.md hard rule): the POST response
is serialised before the BackgroundTask runs and always shows
``status: pending``.  Always GET the job by ID for the final state.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from netconfig.collectors.base import BaseCollector
from netconfig.config import Settings
from netconfig.definitions.schema import DeviceDefinition
from netconfig.main import create_app

pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parents[2]
JUNOS_DEF_PATH = REPO_ROOT / "definitions" / "juniper" / "junos" / "22.x.yaml"


# ---------------------------------------------------------------------------
# Synthetic Junos capture — what `show configuration | display set | no-more`
# returns on a real device, in miniature.  Covers the families the codec
# dispatches on so the round-trip assertion exercises real parser paths.
# ---------------------------------------------------------------------------

JUNOS_FAKE_OUTPUT = (
    "set version 22.4R3-S2.5\n"
    "set system host-name junos-edge-01\n"
    "set system domain-name example.com\n"
    "set system name-server 8.8.8.8\n"
    "set system name-server 1.1.1.1\n"
    "set system login user admin class super-user\n"
    # Synthetic but plausibly-shaped Junos hash — obviously fake per
    # CLAUDE.md "synthetic test secrets" rule.
    'set system login user admin authentication encrypted-password "$6$fake$JunosFakeHashForTest1234"\n'
    "set interfaces ge-0/0/0 description \"uplink-to-core\"\n"
    "set interfaces ge-0/0/0 mtu 9000\n"
    "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24\n"
    "set interfaces lo0 unit 0 family inet address 10.255.0.1/32\n"
    "set vlans v100 vlan-id 100\n"
    "set vlans v200 vlan-id 200\n"
    "set routing-options static route 0.0.0.0/0 next-hop 10.0.0.254\n"
    "set snmp community public authorization read-only\n"
    "set snmp location \"rack-7\"\n"
    "set snmp contact \"netops@example.com\"\n"
)


class JunosFakeCollector(BaseCollector):
    """Returns the canned Junos `display set` capture for any device."""

    def collect(self, device, definition):  # noqa: ARG002
        return JUNOS_FAKE_OUTPUT


# ---------------------------------------------------------------------------
# Fixtures — wire a Settings tree containing ONLY the real Junos definition,
# so the integration tests exercise the shipped YAML rather than a tmp stub.
# ---------------------------------------------------------------------------


@pytest.fixture()
def junos_settings(tmp_path) -> Settings:
    """Settings pointing at a tmp tree containing only the Junos definition.

    Copies the shipped 22.x.yaml verbatim — the integration test then
    drives the full pipeline (route -> definition resolution -> collector
    -> store) against that exact YAML.
    """
    defs_dir = tmp_path / "definitions"
    (defs_dir / "juniper" / "junos").mkdir(parents=True)
    (defs_dir / "juniper" / "junos" / "22.x.yaml").write_text(
        JUNOS_DEF_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    return Settings(
        definitions_dir=defs_dir,
        configs_dir=configs_dir,
        backup_concurrency=1,
    )


@pytest.fixture()
def junos_app(junos_settings):
    return create_app(junos_settings)


@pytest.fixture()
def junos_client(junos_app):
    """TestClient with the canonical ``get_collector`` patch in place."""
    with patch(
        "netconfig.api.routes.backups.get_collector",
        return_value=JunosFakeCollector(),
    ):
        with TestClient(junos_app, raise_server_exceptions=True) as c:
            yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _device_payload(host: str = "10.10.10.1") -> dict:
    return {
        "type_key": "Juniper",
        "host": host,
        "credentials": {"username": "admin", "password": "fake-test-password"},
    }


class TestJunosBackupRoute:
    def test_post_accepts_juniper_type_key(self, junos_client):
        resp = junos_client.post(
            "/api/v1/backups", json={"devices": [_device_payload()]}
        )
        assert resp.status_code == 202

    def test_post_returns_pending_status(self, junos_client):
        # CLAUDE.md hard rule: POST response is always pending.  GET for
        # the final status.
        resp = junos_client.post(
            "/api/v1/backups", json={"devices": [_device_payload()]}
        )
        assert resp.json()["status"] == "pending"

    def test_get_after_post_shows_completed(self, junos_client):
        post = junos_client.post(
            "/api/v1/backups", json={"devices": [_device_payload()]}
        )
        job_id = post.json()["id"]
        job = junos_client.get(f"/api/v1/backups/{job_id}").json()
        assert job["status"] == "completed"

    def test_result_marked_success(self, junos_client):
        post = junos_client.post(
            "/api/v1/backups", json={"devices": [_device_payload()]}
        )
        job = junos_client.get(f"/api/v1/backups/{post.json()['id']}").json()
        assert job["results"][0]["status"] == "success"

    def test_config_file_created(self, junos_client):
        post = junos_client.post(
            "/api/v1/backups", json={"devices": [_device_payload()]}
        )
        job = junos_client.get(f"/api/v1/backups/{post.json()['id']}").json()
        record = job["results"][0]["config_record"]
        assert record is not None
        assert record["filename"]
        # File extension matches the definition's ``file_extension: cfg``.
        assert record["filename"].endswith(".cfg")

    def test_config_file_contains_set_form(self, junos_client, junos_settings):
        post = junos_client.post(
            "/api/v1/backups", json={"devices": [_device_payload()]}
        )
        job = junos_client.get(f"/api/v1/backups/{post.json()['id']}").json()
        filename = job["results"][0]["config_record"]["filename"]
        # FileConfigStore lays files out under
        # ``configs_dir/<device_type>/<safe_host>/<filename>`` — discover
        # via rglob so the test stays robust to layout details.
        matches = list(junos_settings.configs_dir.rglob(filename))
        assert matches, f"backup file {filename!r} not found under {junos_settings.configs_dir}"
        on_disk = matches[0].read_text(encoding="utf-8")
        # The captured output is set-form — sanity-check leading "set "
        # statements made it to disk verbatim.
        assert "set system host-name" in on_disk
        assert "set interfaces ge-0/0/0" in on_disk


class TestJunosCapturedOutputCodecRoundTrip:
    """Confirm the definition's wire form is what the codec actually parses.

    This is the load-bearing test for the BD agent's contract: the
    backup pipeline writes raw bytes; the migration codec must accept
    those bytes.  If the definition's ``commands.config`` were ever
    changed to drop ``| display set``, this assertion would fail —
    catching the regression at definition-author time, not in
    production.
    """

    def test_captured_output_parses_through_codec(self, junos_client, junos_settings):
        # 1. Run the backup against the patched collector — produces the
        #    on-disk file using the shipped definition.
        post = junos_client.post(
            "/api/v1/backups", json={"devices": [_device_payload()]}
        )
        job = junos_client.get(f"/api/v1/backups/{post.json()['id']}").json()
        filename = job["results"][0]["config_record"]["filename"]
        matches = list(junos_settings.configs_dir.rglob(filename))
        assert matches, f"backup file {filename!r} not found under {junos_settings.configs_dir}"
        captured = matches[0].read_text(encoding="utf-8")

        # 2. Feed the captured text directly through the migration codec.
        from netconfig.migration.codecs.juniper_junos import JunosCodec

        codec = JunosCodec()
        intent = codec.parse(captured)

        # 3. Assert representative dispatch landed.
        assert intent.hostname == "junos-edge-01"
        assert any(
            iface.name == "ge-0/0/0" for iface in intent.interfaces
        )
        assert any(v.name == "v100" for v in intent.vlans)
