"""A FortiGate VLAN interface is written on the interface its config says.

``edit "VL_100" ... set interface "LAG_INTERNAL" ... set vlanid 100``
names the interface the VLAN rides on.  The parser did not keep it, and
the renderer chose a parent for every VLAN itself, with a scorer that
does not look at the VLAN: a FortiGate config translated to FortiGate
came back with both VLANs of the 70G capture on its loopback
``LO_BGP``, and the five of the 100E capture on ``dmz`` instead of the
aggregate ``lacp trunk``.  From another vendor the same held: each VLAN
of the RouterOS CRS310 capture, which rides on ``bridge``, was written
on the port ``Access Point``.

The parser keeps the parent (``CanonicalInterface.vlan_parent``), and
the renderer writes it where the output has that interface; where it
does not, a parent is chosen as before and a ``review`` line says which
the source named.  A VLAN with no parent of its own is unchanged.

The expectations are typed from the captures' text by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.codecs.fortigate_cli import FortiGateCLICodec
from netcanon.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netcanon.services.migration_pipeline import run_plan, run_plan_with_overrides

pytestmark = pytest.mark.unit

REAL = Path(__file__).resolve().parents[4] / "fixtures" / "real"

#: Capture -> VLAN interface -> the interface its ``set interface`` says.
STATED = {
    "kevinguenay_fgt_70g_branch.conf": {
        "VL_100": "LAG_INTERNAL",
        "VL_101": "LAG_INTERNAL",
    },
    "user_contrib_fg100e_fos7213.conf": {
        "user-vlan": "lacp trunk",
        "cluster-vlan": "lacp trunk",
        "server-vlan": "lacp trunk",
        "int-mgmt-vlan": "lacp trunk",
        "iot-vlan": "lacp trunk",
    },
}

#: RouterOS capture -> VLAN interface -> its ``interface=``.
FROM_ROUTEROS = {
    "user_contrib_crs310_ros7.rsc": {
        "clustervlan100": "bridge",
        "iotvlan150": "bridge",
        "mgmtvlan11": "bridge",
        "servervlan20": "bridge",
        "uservlan10": "bridge",
    },
    "routeros_diff_verbose_export.rsc": {"gn-mgmt": "ether3"},
}


def _fortigate(capture: str) -> str:
    return (REAL / "fortigate" / capture).read_text(encoding="utf-8")


def _routeros(capture: str) -> str:
    return (REAL / "mikrotik" / capture).read_text(encoding="utf-8")


def _edits(output: str) -> dict[str, list[str]]:
    """Each ``edit`` of ``config system interface`` in *output* -> the
    lines of its body, read as text (nested ``config`` blocks left in)."""
    found: dict[str, list[str]] = {}
    inside = False
    current: list[str] | None = None
    for line in output.splitlines():
        if line == "config system interface":
            inside = True
        elif inside and line == "end":
            inside = False
        elif inside:
            m = re.fullmatch(r'    edit "([^"]*)"', line)
            if m:
                current = found.setdefault(m.group(1), [])
            elif line == "    next":
                current = None
            elif current is not None:
                current.append(line.strip())
    return found


def _vlan_parents(output: str) -> dict[str, str | None]:
    """VLAN interface (an edit with a ``set vlanid``) -> the interface
    its ``set interface`` line names, or ``None`` with no such line."""
    parents: dict[str, str | None] = {}
    for name, body in _edits(output).items():
        if any(line.startswith("set vlanid ") for line in body):
            parents[name] = next(
                (
                    line[len('set interface "'):-1]
                    for line in body if line.startswith('set interface "')
                ),
                None,
            )
    return parents


def _routeros_vlan_parents(output: str) -> dict[str, str]:
    """VLAN interface -> the ``interface=`` of its line in the
    ``/interface vlan`` section of *output*, a quoted value unquoted."""
    found: dict[str, str] = {}
    section = ""
    for line in output.splitlines():
        if line.startswith("/"):
            section = line.strip()
        elif section == "/interface vlan" and line.startswith("add "):
            words = {
                key: value.strip('"')
                for key, value in re.findall(r'(\S+?)=("[^"]*"|\S+)', line)
            }
            found[words["name"]] = words["interface"]
    return found


def _routeros_defined(output: str) -> set[str]:
    """Every name an ``add`` line of *output* gives an interface."""
    return {
        value.strip('"')
        for value in re.findall(r'^add .*?\bname=("[^"]*"|\S+)', output, re.M)
    }


@pytest.mark.parametrize("capture", sorted(STATED))
def test_the_parser_keeps_the_parent_the_config_states(capture: str) -> None:
    tree = FortiGateCLICodec().parse(_fortigate(capture))
    assert {
        iface.name: iface.vlan_parent
        for iface in tree.interfaces if iface.vlan_parent
    } == STATED[capture]


@pytest.mark.parametrize("capture", sorted(STATED))
def test_a_round_trip_writes_each_vlan_on_its_own_parent(capture: str) -> None:
    codec = FortiGateCLICodec()
    job = run_plan(codec, codec, _fortigate(capture))
    assert _vlan_parents(job.rendered) == STATED[capture]
    assert "review: rides on" not in job.rendered


@pytest.mark.parametrize("capture", sorted(STATED))
def test_onto_routeros_each_vlan_rides_on_a_bond_the_output_has(
    capture: str,
) -> None:
    job = run_plan(
        FortiGateCLICodec(), MikroTikRouterOSCodec(), _fortigate(capture),
    )
    parents = _routeros_vlan_parents(job.rendered)
    assert parents == STATED[capture]
    assert set(parents.values()) <= _routeros_defined(job.rendered)


@pytest.mark.parametrize("capture", sorted(FROM_ROUTEROS))
def test_from_routeros_each_vlan_rides_on_its_parent(capture: str) -> None:
    job = run_plan(
        MikroTikRouterOSCodec(), FortiGateCLICodec(), _routeros(capture),
    )
    parents = _vlan_parents(job.rendered)
    assert parents == FROM_ROUTEROS[capture]
    assert set(parents.values()) <= set(_edits(job.rendered))


def test_an_entry_for_the_parent_moves_its_vlans_with_it() -> None:
    codec = FortiGateCLICodec()
    job = run_plan_with_overrides(
        codec, codec, _fortigate("kevinguenay_fgt_70g_branch.conf"),
        port_rename_map={"LAG_INTERNAL": "LAG_LAN"},
    )
    assert _vlan_parents(job.rendered) == {
        "VL_100": "LAG_LAN", "VL_101": "LAG_LAN",
    }
    assert "LAG_LAN" in _edits(job.rendered)


def test_a_parent_the_output_does_not_have_is_said() -> None:
    """The VLAN names a port the config defines nothing under: the
    output has no such interface, so a parent is chosen, and a line in
    the VLAN's own block says which one the source named."""
    codec = FortiGateCLICodec()
    tree = codec.parse("\n".join([
        "config system interface",
        '    edit "port1"',
        "        set ip 192.168.1.1 255.255.255.0",
        "    next",
        '    edit "v10"',
        "        set vlanid 10",
        '        set interface "port9"',
        "    next",
        "end",
        "",
    ]))
    output = codec.render(tree)
    body = _edits(output)["v10"]
    assert (
        '# review: rides on "port9" in the source, which is not in this '
        "output; the parent below was chosen"
    ) in body
    assert _vlan_parents(output) == {"v10": "port1"}


def test_a_vlan_with_no_parent_of_its_own_is_as_before() -> None:
    """``set type vlan`` with no ``set interface``: nothing is stated, so
    the parent is chosen as it always was, and nothing is said."""
    codec = FortiGateCLICodec()
    tree = codec.parse("\n".join([
        "config system interface",
        '    edit "port1"',
        "        set ip 192.168.1.1 255.255.255.0",
        "    next",
        '    edit "v10"',
        "        set type vlan",
        "        set vlanid 10",
        "    next",
        "end",
        "",
    ]))
    assert tree.interfaces[-1].vlan_parent is None
    output = codec.render(tree)
    assert _vlan_parents(output) == {"v10": "port1"}
    assert "review: rides on" not in output
