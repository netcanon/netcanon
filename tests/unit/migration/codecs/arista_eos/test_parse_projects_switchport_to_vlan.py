"""
Phase 4b regression: arista_eos parse() must mirror per-iface
switchport state into VLAN-centric tagged_ports / untagged_ports.

Two Phase 4b agents converged on the same root cause: the parse
pipeline populated CanonicalInterface.switchport_mode /
.access_vlan / .trunk_allowed_vlans correctly, but never invoked
``project_switchport_to_vlan``, so VLAN-centric renderers (Aruba,
OPNsense) emitting from an arista_eos source dropped all VLAN
membership.  The fix is a single call at the end of parse_intent().

These tests pin the projection so a future refactor can't silently
delete the call.
"""

from __future__ import annotations

import pytest

from netconfig.migration.codecs.arista_eos.parse import parse_intent

pytestmark = pytest.mark.unit


def test_parse_projects_trunk_allowed_to_vlan_tagged_ports() -> None:
    """``switchport mode trunk`` + ``trunk allowed vlan 10,20`` must
    appear as ``Ethernet2`` in both vlans[10].tagged_ports and
    vlans[20].tagged_ports after parse."""
    cfg = (
        "hostname sw1\n"
        "vlan 10\n"
        "   name USERS\n"
        "vlan 20\n"
        "   name LAB\n"
        "interface Ethernet2\n"
        "   switchport mode trunk\n"
        "   switchport trunk allowed vlan 10,20\n"
    )
    intent = parse_intent(cfg)
    by_id = {v.id: v for v in intent.vlans}
    assert "Ethernet2" in by_id[10].tagged_ports
    assert "Ethernet2" in by_id[20].tagged_ports


def test_parse_projects_access_vlan_to_vlan_untagged_ports() -> None:
    """``switchport mode access`` + ``access vlan 10`` must appear as
    ``Ethernet1`` in vlans[10].untagged_ports after parse."""
    cfg = (
        "hostname sw1\n"
        "vlan 10\n"
        "   name USERS\n"
        "interface Ethernet1\n"
        "   switchport mode access\n"
        "   switchport access vlan 10\n"
    )
    intent = parse_intent(cfg)
    by_id = {v.id: v for v in intent.vlans}
    assert "Ethernet1" in by_id[10].untagged_ports
    assert "Ethernet1" not in by_id[10].tagged_ports


def test_parse_synthesizes_vlan_for_trunk_allowed_undeclared() -> None:
    """Trunk-allowed VIDs that have no top-level ``vlan N`` stanza
    still get a synthesised CanonicalVlan record so VLAN-centric
    renderers don't drop the membership.  Bug 3 from translator-plans."""
    cfg = (
        "hostname sw1\n"
        "interface Ethernet3\n"
        "   switchport mode trunk\n"
        "   switchport trunk allowed vlan 99\n"
    )
    intent = parse_intent(cfg)
    by_id = {v.id: v for v in intent.vlans}
    assert 99 in by_id, "trunk-allowed VID 99 must be synthesised"
    assert "Ethernet3" in by_id[99].tagged_ports
