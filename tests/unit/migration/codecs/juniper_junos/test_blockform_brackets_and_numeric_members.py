"""Junos parse regressions from the 2026-07-06 Fable review.

#7 — block-form (``show configuration``) bracket value-lists
    (``name-server [ a b ];``, ``members [ v1 v2 ]``) must be expanded
    into one set-line per value, not ingested with the literal ``[``.

#8 — numeric ``vlan members <vid>`` / ``<vid-range>`` must resolve
    directly (not only via the name→id map), else membership is
    silently dropped (port → VLAN 1 on access; bare trunk = all-4094).

The committed junos fixtures are all set-form files, so the cross-mesh
never exercised the block-form path — these tests close that gap.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.juniper_junos.parse import parse_intent

pytestmark = pytest.mark.unit


class TestBlockFormBracketLists:
    def test_name_server_bracket_list_expanded(self) -> None:
        cfg = "system {\n    name-server [ 8.8.8.8 1.1.1.1 ];\n}\n"
        intent = parse_intent(cfg)
        # Pre-fix: dns_servers == ['['] (both servers lost, literal bracket).
        assert intent.dns_servers == ["8.8.8.8", "1.1.1.1"]

    def test_trunk_members_bracket_list_expanded(self) -> None:
        cfg = (
            "vlans {\n"
            "    v10 { vlan-id 10; }\n"
            "    v20 { vlan-id 20; }\n"
            "}\n"
            "interfaces {\n"
            "    ge-0/0/0 {\n"
            "        unit 0 {\n"
            "            family ethernet-switching {\n"
            "                interface-mode trunk;\n"
            "                vlan { members [ v10 v20 ]; }\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        intent = parse_intent(cfg)
        ge0 = next(i for i in intent.interfaces if i.name.startswith("ge-0/0/0"))
        # Pre-fix: trunk_allowed_vlans == [] → IOS target renders bare
        # `switchport mode trunk` = ALL vlans allowed.
        assert sorted(ge0.trunk_allowed_vlans) == [10, 20]


class TestNumericVlanMembers:
    def test_numeric_access_member_resolves(self) -> None:
        cfg = (
            "set vlans v100 vlan-id 100\n"
            "set interfaces ge-0/0/1 unit 0 family ethernet-switching "
            "interface-mode access\n"
            "set interfaces ge-0/0/1 unit 0 family ethernet-switching "
            "vlan members 100\n"
        )
        intent = parse_intent(cfg)
        ge1 = next(i for i in intent.interfaces if i.name.startswith("ge-0/0/1"))
        # Pre-fix: access_vlan is None (numeric never resolved) → VLAN 1.
        assert ge1.access_vlan == 100

    def test_numeric_range_trunk_members_expand(self) -> None:
        cfg = (
            "set interfaces ge-0/0/2 unit 0 family ethernet-switching "
            "interface-mode trunk\n"
            "set interfaces ge-0/0/2 unit 0 family ethernet-switching "
            "vlan members 100-110\n"
        )
        intent = parse_intent(cfg)
        ge2 = next(i for i in intent.interfaces if i.name.startswith("ge-0/0/2"))
        # Pre-fix: [] → bare trunk = 4094 VLANs instead of 11.
        assert ge2.trunk_allowed_vlans == list(range(100, 111))

    def test_out_of_range_numeric_member_ignored(self) -> None:
        # 9999 is out of the 1-4094 VID range — must NOT be added (and
        # must not crash); guards the resolver's bounds check.
        cfg = (
            "set interfaces ge-0/0/3 unit 0 family ethernet-switching "
            "interface-mode trunk\n"
            "set interfaces ge-0/0/3 unit 0 family ethernet-switching "
            "vlan members 9999\n"
        )
        intent = parse_intent(cfg)
        ge3 = next(i for i in intent.interfaces if i.name.startswith("ge-0/0/3"))
        assert ge3.trunk_allowed_vlans == []
