"""A RouterOS VLAN interface is written on the interface its config says.

``/interface vlan add interface=bridge name=mgmtvlan11 vlan-id=11``
names the interface the VLAN rides on.  The parser did not keep it,
and the renderer chose a parent for every VLAN itself: one port that
had an address or a trunk, or else a ``bridge1`` it made up.  A
RouterOS config translated to RouterOS came back with each VLAN of the
committed CRS310 capture on a ``bridge1`` the config does not have
(its bridge is ``bridge``), and the routeros-diff capture's ``gn-mgmt``
moved off ``ether3`` onto it -- in jobs that said ``completed``.

The parser keeps the parent (``CanonicalInterface.vlan_parent``), the
port-name sweep renames it with the interface it names and clears it,
with a warning, where that interface is dropped, and the renderer
chooses a parent only for a VLAN that has none of its own.

The expectations are typed from the captures' text by hand.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import CanonicalVlan
from netcanon.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netcanon.services.migration_pipeline import run_plan, run_plan_with_overrides

pytestmark = pytest.mark.unit

REAL = Path(__file__).resolve().parents[4] / "fixtures" / "real" / "mikrotik"

#: Capture -> VLAN interface -> the interface its line says it rides on.
STATED = {
    "user_contrib_crs310_ros7.rsc": {
        "clustervlan100": "bridge",
        "iotvlan150": "bridge",
        "mgmtvlan11": "bridge",
        "servervlan20": "bridge",
        "uservlan10": "bridge",
    },
    "routeros_diff_verbose_export.rsc": {"gn-mgmt": "ether3"},
}


def _text(capture: str) -> str:
    return (REAL / capture).read_text(encoding="utf-8")


def _vlan_lines(output: str) -> dict[str, str]:
    """VLAN interface name -> the ``interface=`` of its line, read from
    the ``/interface vlan`` section of *output* as text."""
    found: dict[str, str] = {}
    section = ""
    for line in output.splitlines():
        if line.startswith("/"):
            section = line.strip()
        elif section == "/interface vlan" and line.startswith("add "):
            words = dict(
                word.split("=", 1) for word in line.split()[1:] if "=" in word
            )
            found[words["name"]] = words["interface"]
    return found


@pytest.mark.parametrize("capture", sorted(STATED))
def test_the_parser_keeps_the_parent_the_config_states(capture: str) -> None:
    tree = MikroTikRouterOSCodec().parse(_text(capture))
    assert {
        iface.name: iface.vlan_parent
        for iface in tree.interfaces if iface.vlan_parent
    } == STATED[capture]


@pytest.mark.parametrize("capture", sorted(STATED))
def test_a_round_trip_writes_each_vlan_on_its_own_parent(capture: str) -> None:
    codec = MikroTikRouterOSCodec()
    job = run_plan(codec, codec, _text(capture))
    assert job.status == "completed"
    assert _vlan_lines(job.rendered) == STATED[capture]
    assert "bridge1" not in job.rendered


def test_an_entry_for_the_parent_moves_its_vlans_with_it() -> None:
    codec = MikroTikRouterOSCodec()
    job = run_plan_with_overrides(
        codec, codec, _text("user_contrib_crs310_ros7.rsc"),
        port_rename_map={"bridge": "br-lan"},
    )
    assert _vlan_lines(job.rendered) == dict.fromkeys(
        STATED["user_contrib_crs310_ros7.rsc"], "br-lan",
    )


def test_a_parent_that_is_dropped_is_said() -> None:
    """The VLAN stays, the port it rode on does not: the renderer has
    to choose another parent, and the job says so."""
    codec = MikroTikRouterOSCodec()
    job = run_plan_with_overrides(
        codec, codec, _text("routeros_diff_verbose_export.rsc"),
        port_rename_map={"ether3": None},
    )
    assert _vlan_lines(job.rendered)["gn-mgmt"] != "ether3"
    assert any(
        "'gn-mgmt' rides on 'ether3', which is not in the output" in warning
        for warning in job.warnings
    )


def test_a_vlan_with_no_parent_of_its_own_still_gets_one() -> None:
    """One VLAN interface states its parent; VLAN 30 has no interface at
    all.  The first is written on its own parent, and a parent is still
    chosen for the second -- here the ``bridge1`` the renderer makes,
    the config having no bridge and no port that could anchor it."""
    codec = MikroTikRouterOSCodec()
    tree = codec.parse("\n".join([
        "/interface vlan",
        "add interface=ether2 name=v20 vlan-id=20",
    ]))
    tree.vlans.append(CanonicalVlan(id=30, name="vlan30"))
    output = codec.render(tree)
    assert _vlan_lines(output) == {"v20": "ether2", "vlan30": "bridge1"}
    assert "add name=bridge1" in output
