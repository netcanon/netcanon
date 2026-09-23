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

from netcanon.migration.codecs.arista_eos.parse import parse_intent

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


def test_parse_phantom_vlan_guard_drops_wide_trunk_allowed_range() -> None:
    """Phase 4b Wave 7c-C: a WIDE trunk-allowed range must not inflate
    ``intent.vlans``.  Without the guard a cross-vendor pass from a
    source that already pruned phantoms (Cisco IOS-XE) silently
    re-inflated the canonical VLAN table on Arista round-trip parse,
    surfacing as ``vlans`` count drift in the Phase 4 mesh.

    The per-port ``trunk_allowed_vlans`` attribute is still carried
    on the interface — the L2 attribute round-trips through canonical
    unchanged; only the synthesised top-level VLAN entries are pruned.
    """
    cfg = (
        "hostname sw1\n"
        "interface Ethernet3\n"
        "   switchport mode trunk\n"
        "   switchport trunk allowed vlan 1-4094\n"
    )
    intent = parse_intent(cfg)
    assert intent.vlans == [], (
        "an allow-everything range must synthesise no VLAN records"
    )
    iface = next(i for i in intent.interfaces if i.name == "Ethernet3")
    assert iface.trunk_allowed_vlans == list(range(1, 4095))


def test_parse_keeps_a_specific_trunk_allowed_vid() -> None:
    """A single-VID trunk-allowed list is as explicit as an access VLAN.

    ``switchport trunk allowed vlan 99`` names exactly one VLAN the
    operator put on that link.  This used to assert ``99 not in by_id``
    — pruning it meant a target rendered `switchport trunk allowed vlan
    99` with no `vlan 99` stanza to back it, so the VLAN did not forward.
    Breadth, not the mere absence of a stanza, is what makes a VID a
    phantom; the wide case is pinned above.
    """
    cfg = (
        "hostname sw1\n"
        "interface Ethernet3\n"
        "   switchport mode trunk\n"
        "   switchport trunk allowed vlan 99\n"
    )
    intent = parse_intent(cfg)
    by_id = {v.id: v for v in intent.vlans}
    assert 99 in by_id
    assert "Ethernet3" in by_id[99].tagged_ports
    iface = next(i for i in intent.interfaces if i.name == "Ethernet3")
    assert iface.trunk_allowed_vlans == [99]


def test_parse_phantom_guard_keeps_explicit_vlan_membership() -> None:
    """Phase 4b Wave 7c-C: phantom-VLAN guard must NOT strip
    membership from legitimate (explicitly-declared) VLAN records.

    VID 30 has no ``vlan 30`` stanza but is one of three VIDs the
    operator enumerated on the trunk, so it is kept alongside the two
    declared ones (it used to be dropped).
    """
    cfg = (
        "hostname sw1\n"
        "vlan 10\n"
        "   name V10\n"
        "vlan 20\n"
        "   name V20\n"
        "interface Ethernet1\n"
        "   switchport mode trunk\n"
        "   switchport trunk allowed vlan 10,20,30\n"
    )
    intent = parse_intent(cfg)
    by_id = {v.id: v for v in intent.vlans}
    assert sorted(by_id) == [10, 20, 30]
    assert by_id[10].name == "V10", "declared names must survive the prune"
    assert by_id[20].name == "V20"
    assert "Ethernet1" in by_id[10].tagged_ports
    assert "Ethernet1" in by_id[20].tagged_ports
    assert "Ethernet1" in by_id[30].tagged_ports
    iface = next(i for i in intent.interfaces if i.name == "Ethernet1")
    assert iface.trunk_allowed_vlans == [10, 20, 30]


def test_parse_recognises_switchport_trunk_native_vlan() -> None:
    """Phase 4b Wave 7c-C: ``switchport trunk native vlan <N>`` must
    set ``CanonicalInterface.trunk_native_vlan`` so cross-vendor
    round-trips don't silently re-tag native-vlan ports.  Without
    parse symmetry, ``project_switchport_to_vlan`` projects the
    interface as TAGGED on the native VID rather than UNTAGGED."""
    cfg = (
        "hostname sw1\n"
        "vlan 10\n"
        "   name USERS\n"
        "interface Ethernet5\n"
        "   switchport mode trunk\n"
        "   switchport trunk native vlan 10\n"
        "   switchport trunk allowed vlan 10,20,30\n"
    )
    intent = parse_intent(cfg)
    iface = next(i for i in intent.interfaces if i.name == "Ethernet5")
    assert iface.trunk_native_vlan == 10
    assert iface.switchport_mode == "trunk"
    by_id = {v.id: v for v in intent.vlans}
    assert "Ethernet5" in by_id[10].untagged_ports
    assert "Ethernet5" not in by_id[10].tagged_ports
