"""
Phase 4b regression: juniper_junos parse() must mirror per-iface
switchport state into VLAN-centric tagged_ports / untagged_ports.

Junos's ``family ethernet-switching`` subcommands populate
CanonicalInterface.switchport_mode / .access_vlan /
.trunk_allowed_vlans correctly; the missing piece was the
``project_switchport_to_vlan`` call at the end of parse_intent().
Without it, VLAN-centric renderers (Aruba, OPNsense) consuming a
Junos source dropped all VLAN membership.

Trunk-all (``vlan members all`` -> trunk_allowed_vlans=range(1,4095))
is intentionally NOT projected — the helper detects that sentinel
and skips synthesis to avoid spamming 4094 phantom VLAN records.
"""

from __future__ import annotations

import pytest

from netconfig.migration.codecs.juniper_junos.parse import parse_intent

pytestmark = pytest.mark.unit


def test_parse_projects_trunk_allowed_to_vlan_tagged_ports() -> None:
    """Trunk members must land in vlans[].tagged_ports after parse."""
    cfg = (
        "set system host-name sw1\n"
        "set vlans USERS vlan-id 10\n"
        "set vlans LAB vlan-id 20\n"
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching "
        "interface-mode trunk\n"
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching "
        "vlan members USERS\n"
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching "
        "vlan members LAB\n"
    )
    intent = parse_intent(cfg)
    by_id = {v.id: v for v in intent.vlans}
    assert "ge-0/0/2" in by_id[10].tagged_ports
    assert "ge-0/0/2" in by_id[20].tagged_ports


def test_parse_projects_access_vlan_to_vlan_untagged_ports() -> None:
    """Access ports must land in vlans[].untagged_ports after parse."""
    cfg = (
        "set system host-name sw1\n"
        "set vlans USERS vlan-id 10\n"
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching "
        "interface-mode access\n"
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching "
        "vlan members USERS\n"
    )
    intent = parse_intent(cfg)
    by_id = {v.id: v for v in intent.vlans}
    assert "ge-0/0/1" in by_id[10].untagged_ports
    assert "ge-0/0/1" not in by_id[10].tagged_ports


def test_parse_skips_projection_for_trunk_all_sentinel() -> None:
    """``vlan members all`` expands to trunk_allowed_vlans=range(1,4095)
    in the parser; project_switchport_to_vlan must NOT synthesise 4094
    phantom VLANs from that sentinel form, otherwise round-trip
    stability breaks (the rendered ``set vlans VLAN-N vlan-id N`` lines
    leak generated names back through reparse).  See the trunk-all
    guard in netconfig/migration/canonical/transforms.py."""
    cfg = (
        "set system host-name sw1\n"
        "set vlans V100 vlan-id 100\n"
        "set interfaces ae0 unit 0 family ethernet-switching "
        "interface-mode trunk\n"
        "set interfaces ae0 unit 0 family ethernet-switching "
        "vlan members all\n"
    )
    intent = parse_intent(cfg)
    # Only the explicitly declared V100 (id=100) must remain.  No
    # synthesised VLAN records for the 1-4094 range.
    assert len(intent.vlans) == 1
    assert intent.vlans[0].id == 100
    assert intent.vlans[0].name == "V100"
