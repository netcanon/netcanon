"""An IRB unit that states an MTU keeps it.

The Junos parser folds an IRB unit that a VLAN names (``set vlans v100
l3-interface irb.100``) onto that VLAN: the unit's address goes on the
VLAN record and the unit's own record is taken out.  A unit that holds
something a VLAN record cannot -- a description, a VRF, an IPv6
address -- is left as it is.  A VLAN record holds no MTU either, and an
MTU was not on that list: a unit with ``family inet mtu 9000`` was
folded and its MTU lost, on every target, Junos to Junos included, in
a job that reported nothing.

The tree is read here, and the Junos output is read twice: for the
line, as text, and by the parser.  The fold without an MTU is held as
it was.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan

_BASE = (
    "set system host-name sw1\n"
    "set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk\n"
    "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members v100\n"
    "set interfaces irb unit 100 family inet address 192.0.2.1/24\n"
    "{mtu}"
    "set vlans v100 vlan-id 100\n"
    "set vlans v100 l3-interface irb.100\n"
)


def _junos():
    return get_codec("juniper_junos")


def _units_mtu(tree, name: str) -> int | None:
    found = [i for i in tree.interfaces if i.name == name]
    assert len(found) == 1, [i.name for i in tree.interfaces]
    return found[0].mtu


@pytest.mark.parametrize("family", ["inet", "inet6"])
def test_an_irb_unit_with_an_mtu_is_not_folded(family: str) -> None:
    text = _BASE.format(mtu=f"set interfaces irb unit 100 family {family} mtu 9000\n")
    tree = _junos().parse(text)
    assert _units_mtu(tree, "irb.100") == 9000
    unit = next(i for i in tree.interfaces if i.name == "irb.100")
    assert [(a.ip, a.prefix_length) for a in unit.ipv4_addresses] == [("192.0.2.1", 24)]
    vlan = next(v for v in tree.vlans if v.id == 100)
    assert vlan.ipv4_addresses == []


def test_an_irb_units_mtu_comes_back_from_junos_to_junos() -> None:
    text = _BASE.format(mtu="set interfaces irb unit 100 family inet mtu 9000\n")
    out = run_plan(_junos(), _junos(), text).rendered
    assert re.search(r"^set interfaces irb unit 100 family inet mtu 9000$", out, re.M), out
    assert _units_mtu(_junos().parse(out), "irb.100") == 9000


def test_an_irb_unit_without_an_mtu_is_folded_as_before() -> None:
    tree = _junos().parse(_BASE.format(mtu=""))
    assert not [i for i in tree.interfaces if i.name.startswith("irb")]
    vlan = next(v for v in tree.vlans if v.id == 100)
    assert [(a.ip, a.prefix_length) for a in vlan.ipv4_addresses] == [("192.0.2.1", 24)]


def test_the_check_fails_where_the_mtu_is_lost() -> None:
    """The output of the fold as it was, the unit's MTU line taken out."""
    text = _BASE.format(mtu="set interfaces irb unit 100 family inet mtu 9000\n")
    out = run_plan(_junos(), _junos(), text).rendered
    lost = "\n".join(line for line in out.splitlines() if " mtu 9000" not in line)
    with pytest.raises(AssertionError):
        assert _units_mtu(_junos().parse(lost), "irb.100") == 9000
