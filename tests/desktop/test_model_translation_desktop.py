"""
Desktop smoke test — the embedded server does model-to-model port
mapping exactly as the web platform does.

Device-model families are data and the mapping is server logic, so the
desktop platform needs no code of its own.  What it does need is for
the embedded ``ServerThread`` to load the families at startup, serve
them, compile an inventory and run a plan with both devices declared.
This proves all four, so a change that wires the feature into the web
app only (a lifespan step the desktop build skips, say) fails on the
desktop tier and not only on the web tier.

Complements ``tests/integration/test_migration_models_api.py``
(TestClient).
"""

from __future__ import annotations

import json
import logging
import shutil
import socket
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from netcanon.config import Settings
from netcanon.definitions import LIBRARY_DIR
from netcanon.main import create_app
from netcanon_desktop.server import ServerThread
from tests.conftest import FakeCollector

pytestmark = pytest.mark.desktop

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPTURE_2930F = (
    REPO_ROOT / "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg"
).read_text(encoding="utf-8")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _settings(tmp_path: Path) -> Settings:
    # The whole shipped library, as the MSI lays it out next to the
    # executable: device definitions, target profiles and model
    # families under one definitions directory.
    defs = tmp_path / "definitions"
    shutil.copytree(LIBRARY_DIR, defs)
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    return Settings(
        definitions_dir=defs, configs_dir=configs_dir, backup_concurrency=1,
    )


def _get(port: int, path: str) -> object:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        assert resp.status == 200, path
        return json.loads(resp.read().decode("utf-8"))


def _post(port: int, path: str, body: dict) -> object:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as resp:
        assert resp.status == 200, path
        return json.loads(resp.read().decode("utf-8"))


def _post_raw(port: int, path: str, body: bytes) -> tuple[int, object]:
    """POST bytes as they are; return the status and the decoded body,
    whatever the status."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


_EOS_ONE_ROUTED_PORT = """hostname sw
!
interface Ethernet1
   no switchport
   ip address 192.0.2.1/24
!
end
"""


class TestModelTranslationServedByEmbeddedServer:
    def test_families_inventory_and_a_declared_plan(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="netcanon.migration.device_models")
        app = create_app(_settings(tmp_path))
        port = _free_port()
        target = {
            "mode": "stacked",
            "members": [{"model": "JL322A", "modules": {"A": "JL083A"}}],
        }
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=FakeCollector(output="! noop\n"),
        ):
            server = ServerThread(app, port=port, log_level="critical")
            server.start()
            try:
                server.wait_ready(timeout=10.0)
                families = _get(port, "/api/v1/migration/model-families")
                inventory = _post(port, "/api/v1/migration/inventory", {
                    "codec": "aruba_aoss", "deployment": target,
                })
                job = _post(port, "/api/v1/migration/plan", {
                    "source": "aruba_aoss",
                    "target": "aruba_aoss",
                    "raw_text": CAPTURE_2930F,
                    "source_deployment": {
                        "mode": "standalone", "members": [{"model": "JL260A"}],
                    },
                    "target_deployment": target,
                })
            finally:
                server.stop()
                server.join(timeout=5.0)

        # The shipped families are loaded.  The definitions directory
        # here IS a copy of the library, as on an installed desktop:
        # the copy must be recognised as the same families, not
        # refused as a conflicting second set -- which would show as
        # one warning per family at every start.
        keys = [f"{f['vendor']}/{f['family']}" for f in families]
        assert "aruba_aoss/2930F" in keys and "aruba_aoss/2930M" in keys
        loader_warnings = [
            record.getMessage() for record in caplog.records
            if record.name == "netcanon.migration.device_models"
        ]
        assert not loader_warnings, loader_warnings

        # An inventory is compiled on the server, by the naming rule.
        names = [p["name"] for p in inventory["ports"]]
        assert names[0] == "1/1" and names[-1] == "1/A4"

        # A plan with both devices declared pairs ports by position.
        assert job["status"] == "completed"
        assert job["port_renames"]["49"] == "1/A1"
        assert len(job["port_mapping_plan"]["pairings"]) == 52
        assert "untagged 1/48,1/A1,1/A2,1/A3,1/A4" in job["rendered"]

    def test_a_stack_on_both_sides(self, tmp_path: Path) -> None:
        """Two members declared for the source AND for the target,
        through the embedded server: the members pair in the order
        listed, and a member whose number changes is said."""
        app = create_app(_settings(tmp_path))
        port = _free_port()
        # Not a capture: no committed capture names a port of a second
        # member.  The names are the ones the family's VSF mode gives.
        fabric = (
            "; hpStack_WC Configuration Editor; Created on release #WC.16.07.0002\n"
            'hostname "fabric"\n'
            "trunk 1/49,3/49 trk1 lacp\n"
            'interface 3/1\n   name "desk-b"\n   exit\n'
            'vlan 10\n   name "users"\n   untagged 1/1-1/10,3/1-3/4\n'
            "   tagged Trk1,3/50\n   exit\n"
        )
        body = {
            "source": "aruba_aoss", "target": "aruba_aoss", "raw_text": fabric,
            "source_deployment": {
                "mode": "vsf",
                "members": [{"model": "JL260A", "id": 1}, {"model": "JL260A", "id": 3}],
            },
            "target_deployment": {
                "mode": "stacked",
                "members": [
                    {"model": "JL322A", "id": 1, "modules": {"A": "JL083A"}},
                    {"model": "JL322A", "id": 2, "modules": {"A": "JL083A"}},
                ],
            },
        }
        short = {
            **body,
            "target_deployment": {
                "mode": "stacked",
                "members": [{"model": "JL322A", "id": 1, "modules": {"A": "JL083A"}}],
            },
        }
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=FakeCollector(output="! noop\n"),
        ):
            server = ServerThread(app, port=port, log_level="critical")
            server.start()
            try:
                server.wait_ready(timeout=10.0)
                job = _post(port, "/api/v1/migration/plan", body)
                partial = _post(port, "/api/v1/migration/plan", short)
            finally:
                server.stop()
                server.join(timeout=5.0)

        assert job["status"] == "completed"
        assert {k: v for k, v in job["port_renames"].items() if "/" in k} == {
            "1/49": "1/A1", "3/1": "2/1", "3/2": "2/2", "3/3": "2/3", "3/4": "2/4",
            "3/49": "2/A1", "3/50": "2/A2",
        }
        lines = [line.strip() for line in job["rendered"].splitlines()]
        assert "trunk 1/A1,2/A1 trk1 lacp" in lines
        assert lines[lines.index("interface 2/1") + 1] == 'name "desk-b"'
        assert not [line for line in lines if "3/" in line]
        plan = job["port_mapping_plan"]
        assert [m["member_id"] for m in plan["source"]["members"]] == [1, 3]
        assert [m["member_id"] for m in plan["target"]["members"]] == [1, 2]
        (line,) = [w for w in job["warnings"] if w.startswith("port mapping:")]
        assert line.endswith("source member 3 with target member 2")

        # One member short on the target: the second member's ports are
        # dropped and the job is not a success.
        assert partial["status"] == "partial"
        assert sorted(partial["port_drops"]) == ["3/1", "3/2", "3/3", "3/4", "3/49", "3/50"]
        assert {p["reason"] for p in partial["port_mapping_plan"]["unplaced"] if p["used"]} == {
            "no-member",
        }
        assert "trunk 1/A1 trk1 lacp" in partial["rendered"]

    def test_the_finished_run_is_checked_and_a_bad_body_is_a_422(
        self, tmp_path: Path,
    ) -> None:
        """Two things the server does after the pairing, through the
        embedded server: an override typed in another case is read
        as the port it names -- here a port the pairing already gave
        away, so the job is ``partial`` and says which target
        received two ports -- and a body that cannot be echoed as
        UTF-8 is refused with a 422, not a 500."""
        app = create_app(_settings(tmp_path))
        port = _free_port()
        declared = {
            "source": "aruba_aoss",
            "target": "aruba_aoss",
            "raw_text": CAPTURE_2930F,
            "source_deployment": {
                "mode": "standalone", "members": [{"model": "JL260A"}],
            },
            "target_deployment": {
                "mode": "stacked",
                "members": [{"model": "JL322A", "modules": {"A": "JL083A"}}],
            },
            "port_rename_map": {"52": " 1/a1"},
        }
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=FakeCollector(output="! noop\n"),
        ):
            server = ServerThread(app, port=port, log_level="critical")
            server.start()
            try:
                server.wait_ready(timeout=10.0)
                job = _post(port, "/api/v1/migration/plan", declared)
                status, refused = _post_raw(
                    port, "/api/v1/migration/plan",
                    b'{"source":"aruba_aoss","target":"aruba_aoss","raw_text":"x",'
                    b'"source_deployment":{"members":[{"model":"JL\\ud800"}]}}',
                )
            finally:
                server.stop()
                server.join(timeout=5.0)

        plan = job["port_mapping_plan"]
        assert job["port_renames"]["52"] == "1/A1"
        assert plan["fused"] == {"1/A1": ["49", "52"]}
        assert plan["overridden"] == ["52"] and plan["off_target"] == []
        assert job["status"] == "partial"
        assert "received more than one source port" in job["error"]

        assert status == 422
        assert refused["detail"][0]["type"] == "string_unicode"

    def test_a_ports_hardware_stays_or_moves_and_a_bad_map_name_is_a_422(
        self, tmp_path: Path,
    ) -> None:
        """Server behaviour a client of the embedded server sees, on
        RouterOS, where a port has a factory name beside its own:
        without devices an entry NAMES the port (the output finds it
        by the factory name it always had); with both devices declared
        the hardware moves, a port the operator named keeps that name,
        and the plan says where its hardware is.  And a name in a
        rename map that cannot be written back is a 422."""
        app = create_app(_settings(tmp_path))
        port = _free_port()
        routeros = (
            "/interface ethernet\n"
            'set [ find default-name=ether1 ] comment="wan"\n'
            'set [ find default-name=ether2 ] name=core-a comment="core A"\n'
            "/ip address\n"
            "add address=192.0.2.2/30 interface=ether1\n"
            "add address=10.0.0.1/24 interface=core-a\n"
        )
        base = {
            "source": "mikrotik_routeros", "target": "mikrotik_routeros", "raw_text": routeros,
        }
        with patch(
            "netcanon.api.routes.backups.get_collector",
            return_value=FakeCollector(output="! noop\n"),
        ):
            server = ServerThread(app, port=port, log_level="critical")
            server.start()
            try:
                server.wait_ready(timeout=10.0)
                named = _post(port, "/api/v1/migration/plan", {
                    **base, "port_rename_map": {"ether1": "WAN"},
                })
                moved = _post(port, "/api/v1/migration/plan", {
                    **base,
                    "source_profile": "mikrotik_routeros/CRS310-8G+2S+",
                    "target_profile": "mikrotik_routeros/CCR2004-1G-12S+2XS",
                })
                # From another vendor too: a named port is found by the
                # hardware it was paired with, not by its name.
                foreign = _post(port, "/api/v1/migration/plan", {
                    "source": "arista_eos", "target": "mikrotik_routeros",
                    "raw_text": (
                        "hostname sw\n!\ninterface Ethernet1\n   no switchport\n"
                        "   ip address 192.0.2.1/24\n!\nend\n"
                    ),
                    "source_profile": "arista_eos/DCS-7050SX-64",
                    "target_profile": "mikrotik_routeros/CCR2004-1G-12S+2XS",
                    "port_rename_map": {"Ethernet1": "WAN"},
                })
                # ...and a name RouterOS writes no line for is reported,
                # not said to be on the hardware.
                unbound = _post(port, "/api/v1/migration/plan", {
                    "source": "arista_eos", "target": "mikrotik_routeros",
                    "raw_text": _EOS_ONE_ROUTED_PORT,
                    "source_profile": "arista_eos/DCS-7050SX-64",
                    "target_profile": "mikrotik_routeros/CCR2004-1G-12S+2XS",
                    "port_rename_map": {"Ethernet1": "bridge-uplink"},
                })
                status, refused = _post_raw(
                    port, "/api/v1/migration/plan",
                    b'{"source":"aruba_aoss","target":"aruba_aoss","raw_text":"x",'
                    b'"port_rename_map":{"1":"\\ud800"}}',
                )
            finally:
                server.stop()
                server.join(timeout=5.0)

        assert 'set [ find default-name=ether1 ] name=WAN comment="wan"' in named["rendered"]
        assert named["port_mapping_plan"] is None

        plan = moved["port_mapping_plan"]
        assert 'set [ find default-name=sfp-sfpplus1 ] comment="wan"' in moved["rendered"]
        assert 'set [ find default-name=sfp-sfpplus2 ] name=core-a' in moved["rendered"]
        assert plan["labelled_ports"] == {"core-a": "ether2"}
        assert plan["target_hardware"] == {"core-a": "sfp-sfpplus2"}
        assert moved["status"] == "completed"

        assert "set [ find default-name=sfp-sfpplus1 ] name=WAN" in foreign["rendered"]
        assert foreign["port_mapping_plan"]["target_hardware"] == {"Ethernet1": "sfp-sfpplus1"}

        assert "default-name=sfp-sfpplus1" not in unbound["rendered"]
        assert unbound["port_mapping_plan"]["unbound_ports"] == {"Ethernet1": "sfp-sfpplus1"}
        assert unbound["status"] == "partial"

        assert status == 422
        assert refused["detail"][0]["loc"] == ["body", "port_rename_map"]
