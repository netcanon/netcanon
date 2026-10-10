"""What a parser finds among the records its earlier lines made -- and that finding it by key changed nothing.

A handler that runs once per line used to look through everything the
earlier lines had made, which cost the square of the lines
(``tests/unit/test_untrusted_text_cost.py`` pins the cost).  Each such
handler now finds its record by key, or does its pass over the tree
once.  The cost is one half of that change; this module is the other:
the ANSWERS each rewritten handler has to keep giving, on configs
written to reach the cases where a lookup by key could differ from a
scan -- two records of one key, a record made out of order, a list
that was added to by something else, a value that is stated twice.
"""

from __future__ import annotations

import random

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.canonical.transforms import _PortList, project_switchport_to_vlan
from netcanon.migration.codecs._helpers import GrowingIndex
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit

EOS = get_codec("arista_eos")
AOSS = get_codec("aruba_aoss")
FORTI = get_codec("fortigate_cli")
JUNOS = get_codec("juniper_junos")
OPN = get_codec("opnsense")
ROS = get_codec("mikrotik_routeros")

_AOSS_TOP = '; J9729A Configuration Editor; Created on release #WB.16.08.0001\nhostname "sw"\n'


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------


class TestGrowingIndex:
    def test_the_first_record_of_a_key_as_a_scan_returned(self) -> None:
        records = [("a", 1), ("b", 2), ("a", 3)]
        index = GrowingIndex(lambda: records, lambda record: record[0])
        assert index.get("a") == ("a", 1) and index.get("b") == ("b", 2) and index.get("c") is None

    def test_or_the_last_as_a_dict_built_from_the_list_held(self) -> None:
        records = [("a", 1), ("b", 2), ("a", 3)]
        index = GrowingIndex(lambda: records, lambda record: record[0], last=True)
        assert index.get("a") == {key: (key, value) for key, value in records}["a"] == ("a", 3)

    def test_a_record_appended_by_anyone_is_found(self) -> None:
        records: list[tuple[str, int]] = []
        index = GrowingIndex(lambda: records, lambda record: record[0])
        assert index.get("a") is None and "a" not in index
        records.append(("a", 1))
        assert index.get("a") == ("a", 1) and "a" in index
        records.append(("a", 2))
        assert index.get("a") == ("a", 1)

    def test_a_list_that_was_replaced_is_read_from_the_start(self) -> None:
        holder = {"records": [("a", 1)]}
        index = GrowingIndex(lambda: holder["records"], lambda record: record[0])
        assert index.get("a") == ("a", 1)
        holder["records"] = [("a", 9), ("b", 2)]
        assert index.get("a") == ("a", 9) and index.get("b") == ("b", 2)

    def test_a_list_that_became_shorter_is_read_from_the_start(self) -> None:
        records = [("a", 1), ("b", 2)]
        index = GrowingIndex(lambda: records, lambda record: record[0])
        assert index.get("b") == ("b", 2)
        del records[:]
        assert index.get("b") is None and "a" not in index

    def test_each_record_is_read_once(self) -> None:
        """The point of it: ten thousand lookups over a list of ten
        thousand ask each record for its key once."""
        asked = []
        records = list(range(10_000))
        index = GrowingIndex(lambda: records, lambda record: asked.append(record) or record)
        assert all(index.get(n) == n for n in range(10_000))
        assert len(asked) == 10_000


# ---------------------------------------------------------------------------
# The port list of the switchport projection
# ---------------------------------------------------------------------------


class TestPortList:
    NAMES = ["Gi1", "Gi01", "Gi2", "1/1", "A1", "a1", "x"]

    def test_it_does_what_the_list_did_on_random_runs(self) -> None:
        """``add`` is ``if name not in lst: lst.append(name)`` and
        ``remove_first`` is ``if name in lst: lst.remove(name)``, in
        any order, on a list that may start with duplicates."""
        rng = random.Random(7)
        for _ in range(3000):
            start = [rng.choice(self.NAMES) for _ in range(rng.randint(0, 6))]
            plain, kept = list(start), list(start)
            reader = _PortList(kept)
            for _ in range(rng.randint(0, 14)):
                name = rng.choice(self.NAMES)
                if rng.random() < 0.6:
                    if name not in plain:
                        plain.append(name)
                    reader.add(name)
                else:
                    if name in plain:
                        plain.remove(name)
                    reader.remove_first(name)
            reader.settle()
            assert kept == plain

    def test_the_list_is_changed_in_place(self) -> None:
        kept = ["a", "b"]
        reader = _PortList(kept)
        reader.remove_first("a")
        reader.add("c")
        reader.settle()
        assert kept == ["b", "c"]

    def test_names_that_sort_alike_keep_the_order_they_were_added_in(self) -> None:
        """``Gi1`` and ``Gi01`` have one sort key, and the sort that
        follows the projection is stable: which comes first is the
        order the projection left them in."""
        tree = CanonicalIntent.model_validate({
            "interfaces": [
                {"name": "Gi01", "switchport_mode": "access", "access_vlan": 10},
                {"name": "Gi1", "switchport_mode": "access", "access_vlan": 10},
            ],
        })
        project_switchport_to_vlan(tree)
        assert tree.vlans[0].untagged_ports == ["Gi01", "Gi1"]

    def test_a_native_vlan_is_untagged_and_not_tagged(self) -> None:
        tree = CanonicalIntent.model_validate({
            "interfaces": [
                {"name": "Gi1", "switchport_mode": "trunk", "trunk_allowed_vlans": [10, 20], "trunk_native_vlan": 10},
                {"name": "Gi2", "switchport_mode": "trunk", "trunk_allowed_vlans": [10, 20]},
            ],
            "vlans": [{"id": 10, "tagged_ports": ["Gi1", "Gi1"]}],
        })
        project_switchport_to_vlan(tree)
        by_id = {vlan.id: vlan for vlan in tree.vlans}
        # One of the two entries the list began with is taken out, as
        # ``list.remove`` took one.
        assert by_id[10].tagged_ports == ["Gi1", "Gi2"] and by_id[10].untagged_ports == ["Gi1"]
        assert by_id[20].tagged_ports == ["Gi1", "Gi2"]


# ---------------------------------------------------------------------------
# Arista
# ---------------------------------------------------------------------------


def _eos(*lines: str) -> CanonicalIntent:
    return EOS.parse("\n".join(("hostname sw", "!", *lines, "!")) + "\n")


class TestAristaVxlan:
    def test_a_source_interface_stated_after_the_mappings_reaches_them(self) -> None:
        tree = _eos(
            "interface Vxlan1", "   vxlan vlan 10 vni 10010", "   vxlan source-interface Loopback1",
            "   vxlan vlan 20 vni 10020",
        )
        assert [(vx.vlan_id, vx.source_interface) for vx in tree.vxlan_vnis] == [(10, "Loopback1"), (20, "Loopback1")]

    def test_the_first_source_interface_a_record_gets_is_the_one_it_keeps(self) -> None:
        tree = _eos(
            "interface Vxlan1", "   vxlan vlan 10 vni 10010", "   vxlan source-interface Loopback1",
            "   vxlan source-interface Loopback2", "   vxlan vlan 20 vni 10020",
        )
        assert [vx.source_interface for vx in tree.vxlan_vnis] == ["Loopback1", "Loopback2"]

    def test_a_port_moves_the_records_still_on_the_default_and_no_other(self) -> None:
        tree = _eos(
            "interface Vxlan1", "   vxlan vlan 10 vni 10010", "   vxlan udp-port 8472",
            "   vxlan vlan 20 vni 10020", "   vxlan udp-port 4789", "   vxlan vlan 30 vni 10030",
            "   vxlan udp-port 4790",
        )
        assert [(vx.vlan_id, vx.udp_port) for vx in tree.vxlan_vnis] == [(10, 8472), (20, 8472), (30, 4790)]

    def test_the_default_port_stated_changes_nothing(self) -> None:
        tree = _eos(
            "interface Vxlan1", "   vxlan vlan 10 vni 10010", "   vxlan udp-port 4789", "   vxlan udp-port 4789",
        )
        assert [vx.udp_port for vx in tree.vxlan_vnis] == [4789]

    def test_a_record_made_under_the_default_port_stated_is_still_moved_by_a_later_one(self) -> None:
        mapping, default, other = "   vxlan vlan 10 vni 10010", "   vxlan udp-port 4789", "   vxlan udp-port 8472"
        for lines in ((default, mapping, other), (mapping, default, other)):
            assert [vx.udp_port for vx in _eos("interface Vxlan1", *lines).vxlan_vnis] == [8472]
        # And by the FIRST port stated after it that is not the default,
        # not by whichever is stated last.
        last = "   vxlan udp-port 4790"
        assert [vx.udp_port for vx in _eos("interface Vxlan1", mapping, default, other, last).vxlan_vnis] == [8472]

    def test_a_second_vxlan_stanza_goes_on_with_what_the_first_stated(self) -> None:
        tree = _eos(
            "interface Vxlan1", "   vxlan vlan 10 vni 10010", "!",
            "interface Vxlan1", "   vxlan source-interface Loopback9", "   vxlan udp-port 8472",
            "   vxlan vlan 20 vni 10020",
        )
        assert [(vx.vlan_id, vx.source_interface, vx.udp_port) for vx in tree.vxlan_vnis] == [
            (10, "Loopback9", 8472), (20, "Loopback9", 8472),
        ]

    def test_a_vrfs_vni_is_set_on_the_one_instance_of_that_name(self) -> None:
        tree = _eos(
            "vrf instance A", "!", "interface Vxlan1", "   vxlan vrf A vni 50001", "   vxlan vrf B vni 50002",
            "   vxlan vrf A vni 50003",
        )
        assert [(ri.name, ri.l3_vni) for ri in tree.routing_instances] == [("A", 50003), ("B", 50002)]


class TestAristaRouterBgp:
    def test_a_vrf_stated_twice_is_one_instance(self) -> None:
        tree = _eos(
            "router bgp 65001", "   vrf A", "      rd 65001:1", "   vrf B", "      rd 65001:2", "   vrf A",
            "      route-target import evpn 65001:9",
        )
        assert [(ri.name, ri.route_distinguisher, ri.rt_imports) for ri in tree.routing_instances] == [
            ("A", "65001:1", ["65001:9"]), ("B", "65001:2", []),
        ]

    def test_a_vlan_binding_takes_the_vlans_name_and_is_found_again(self) -> None:
        tree = _eos(
            "vlan 10", "   name USERS", "!", "router bgp 65001", "   vlan 10", "      rd 65001:10",
            "   vlan 20", "      rd 65001:20", "   vlan 10", "      route-target both 65001:10",
        )
        assert [(ri.name, ri.instance_type, ri.route_distinguisher) for ri in tree.routing_instances] == [
            ("USERS", "mac-vrf", "65001:10"), ("VLAN20", "mac-vrf", "65001:20"),
        ]
        assert tree.routing_instances[0].rt_imports == ["65001:10"]


# ---------------------------------------------------------------------------
# FortiGate
# ---------------------------------------------------------------------------


def _forti_block(*edits: tuple[str, str]) -> str:
    lines = ["config system interface"]
    for name, members in edits:
        lines += [f'    edit "{name}"', '        set vdom "root"']
        if members:
            lines += ["        set type aggregate", "        set member " + " ".join(f'"{m}"' for m in members.split())]
        lines.append("    next")
    return "\n".join([*lines, "end"]) + "\n"


class TestFortiGateLagMembers:
    @staticmethod
    def _links(text: str) -> list[tuple[str, str | None]]:
        return [(iface.name, iface.lag_member_of) for iface in FORTI.parse(text).interfaces]

    def test_a_member_defined_after_its_aggregate_is_linked(self) -> None:
        assert self._links(_forti_block(("agg1", "port1 port2"), ("port1", ""), ("port2", ""))) == [
            ("agg1", None), ("port1", "agg1"), ("port2", "agg1"),
        ]

    def test_a_member_defined_in_another_block_is_linked(self) -> None:
        text = _forti_block(("port1", "")) + _forti_block(("agg1", "port1 port2")) + _forti_block(("port2", ""))
        assert self._links(text) == [("port1", "agg1"), ("agg1", None), ("port2", "agg1")]

    def test_of_two_aggregates_that_name_a_port_the_first_has_it(self) -> None:
        text = _forti_block(("agg1", "port1"), ("agg2", "port1")) + _forti_block(("port1", ""))
        assert self._links(text) == [("agg1", None), ("agg2", None), ("port1", "agg1")]

    def test_a_port_an_edit_already_linked_is_left_with_that_aggregate(self) -> None:
        """``agg2`` is edited after ``port1`` and links it there and
        then; ``agg1`` names it too, from an earlier block, and comes
        first in the config -- but the port is already linked."""
        text = _forti_block(("agg1", "port1")) + _forti_block(("port1", ""), ("agg2", "port1"))
        assert self._links(text)[1] == ("port1", "agg2")

    def test_every_record_of_a_name_is_linked(self) -> None:
        text = _forti_block(("port1", "")) + _forti_block(("port1", "")) + _forti_block(("agg1", "port1"))
        assert self._links(text) == [("port1", "agg1"), ("port1", "agg1"), ("agg1", None)]


# ---------------------------------------------------------------------------
# Junos
# ---------------------------------------------------------------------------


def _junos(*lines: str) -> CanonicalIntent:
    return JUNOS.parse("\n".join(("set system host-name r1", *lines)) + "\n")


class TestJunosRecordsFoundByKey:
    def test_a_route_stated_twice_is_one_route(self) -> None:
        tree = _junos(
            "set routing-options static route 10.0.0.0/8 next-hop 192.0.2.1",
            "set routing-options static route 10.0.0.0/8 next-hop 192.0.2.2",
            "set routing-options static route 10.0.0.0/8 next-hop 192.0.2.1",
        )
        assert [(r.destination, r.gateway, r.vrf) for r in tree.static_routes] == [
            ("10.0.0.0/8", "192.0.2.1", ""), ("10.0.0.0/8", "192.0.2.2", ""),
        ]

    def test_the_same_route_in_a_vrf_is_another_route(self) -> None:
        tree = _junos(
            "set routing-options static route 10.0.0.0/8 next-hop 192.0.2.1",
            "set routing-instances RED routing-options static route 10.0.0.0/8 next-hop 192.0.2.1",
            "set routing-instances RED routing-options static route 10.0.0.0/8 next-hop 192.0.2.1",
            "set routing-instances BLUE routing-options static route 10.0.0.0/8 next-hop 192.0.2.1",
        )
        assert [r.vrf for r in tree.static_routes] == ["", "RED", "BLUE"]

    def test_a_route_from_a_group_and_the_same_one_at_the_top_is_one(self) -> None:
        tree = _junos(
            "set groups G routing-options static route 10.0.0.0/8 next-hop 192.0.2.1",
            "set apply-groups G",
            "set routing-options static route 10.0.0.0/8 next-hop 192.0.2.1",
        )
        assert len(tree.static_routes) == 1

    def test_a_users_lines_are_one_user_however_they_are_interleaved(self) -> None:
        tree = _junos(
            "set system login user ops class operator",
            "set system login user noc class read-only",
            'set system login user ops authentication encrypted-password "$6$fake$hash"',
            "set system login user ops class super-user",
        )
        assert [(user.name, user.role) for user in tree.local_users] == [("ops", "super-user"), ("noc", "read-only")]
        assert tree.local_users[0].hashed_password and not tree.local_users[1].hashed_password

    def test_a_routing_instances_lines_are_one_instance(self) -> None:
        tree = _junos(
            "set routing-instances RED instance-type vrf",
            "set routing-instances BLUE instance-type virtual-router",
            "set routing-instances RED route-distinguisher 65000:1",
        )
        assert [(ri.name, ri.instance_type, ri.route_distinguisher) for ri in tree.routing_instances] == [
            ("RED", "vrf", "65000:1"), ("BLUE", "virtual-router", ""),
        ]

    def test_a_vni_stated_twice_is_one_and_another_vni_of_the_vlan_is_a_second(self) -> None:
        tree = _junos(
            "set vlans USERS vlan-id 10", "set vlans USERS vxlan vni 10010", "set vlans USERS vxlan vni 10010",
            "set vlans USERS vxlan vni 10011",
        )
        assert [(vx.vlan_id, vx.vni) for vx in tree.vxlan_vnis] == [(10, 10010), (10, 10011)]
        tree = _junos(
            "set vlans USERS vlan-id 10", "set vlans USERS vxlan vni 10011", "set vlans USERS vxlan vni 10010",
            "set vlans USERS vxlan vni 10011",
        )
        assert [(vx.vlan_id, vx.vni) for vx in tree.vxlan_vnis] == [(10, 10011), (10, 10010)]

    def test_a_group_applied_twice_is_applied_once_and_in_its_place(self) -> None:
        """Groups are applied last-declared first, so the first
        declared wins a scalar; naming one again does not move it."""
        tree = _junos(
            "set groups A system host-name from-a", "set groups B system host-name from-b",
            "set apply-groups A", "set apply-groups B", "set apply-groups A",
        )
        assert tree.hostname == "r1"
        only_groups = JUNOS.parse(
            "set groups A system host-name from-a\nset groups B system host-name from-b\n"
            "set apply-groups A\nset apply-groups B\nset apply-groups A\n"
        )
        assert only_groups.hostname == "from-a"


# ---------------------------------------------------------------------------
# AOS-S
# ---------------------------------------------------------------------------


def _aoss(*lines: str) -> CanonicalIntent:
    return AOSS.parse(_AOSS_TOP + "\n".join(lines) + "\n")


class TestAossRecordsFoundByKey:
    def test_a_port_untagged_in_a_later_vlan_leaves_the_earlier_one(self) -> None:
        tree = _aoss(
            "vlan 1", "   untagged 1-8", "   exit", "vlan 10", "   untagged 3-4", "   exit",
            "vlan 20", "   untagged 4,7", "   exit",
        )
        assert {vlan.id: vlan.untagged_ports for vlan in tree.vlans} == {
            1: ["1", "2", "5", "6", "8"], 10: ["3"], 20: ["4", "7"],
        }

    def test_a_second_stanza_of_one_vlan_takes_the_ports_from_the_first(self) -> None:
        tree = _aoss("vlan 10", "   untagged 1-4", "   exit", "vlan 10", "   untagged 2-3", "   exit")
        assert [(vlan.id, vlan.untagged_ports) for vlan in tree.vlans] == [(10, ["1", "4"]), (10, ["2", "3"])]

    def test_a_tagged_port_is_not_moved(self) -> None:
        tree = _aoss("vlan 1", "   tagged 1-2", "   exit", "vlan 10", "   untagged 1", "   tagged 2", "   exit")
        assert tree.vlans[0].tagged_ports == ["1", "2"]

    def test_a_global_radius_key_goes_to_the_hosts_without_one_at_that_line(self) -> None:
        tree = _aoss(
            "radius-server host 192.0.2.1",
            'radius-server host 192.0.2.2 key "own"',
            'radius-server key "first"',
            "radius-server host 192.0.2.3",
            'radius-server key "second"',
            "radius-server host 192.0.2.4",
        )
        assert [(s.host, s.key) for s in tree.radius_servers] == [
            ("192.0.2.1", "first"), ("192.0.2.2", "own"), ("192.0.2.3", "second"), ("192.0.2.4", ""),
        ]

    def test_an_empty_global_key_gives_nothing_and_takes_nothing(self) -> None:
        tree = _aoss(
            "radius-server host 192.0.2.1", 'radius-server key ""', "radius-server host 192.0.2.2",
            'radius-server key "late"',
        )
        assert [s.key for s in tree.radius_servers] == ["late", "late"]

    def test_a_host_stated_twice_is_one_server_and_keeps_its_first_key(self) -> None:
        tree = _aoss(
            'radius-server host 192.0.2.1 key "one"', "radius-server host 192.0.2.2",
            'radius-server host 192.0.2.1 key "two" auth-port 1645',
        )
        assert [(s.host, s.key, s.auth_port) for s in tree.radius_servers] == [
            ("192.0.2.1", "one", 1645), ("192.0.2.2", "", 1812),
        ]

    def test_a_group_line_before_or_after_its_user_is_that_user(self) -> None:
        tree = _aoss(
            'snmpv3 group "operatorauth" user "late" sec-model ver3',
            'snmpv3 user "early" auth sha "fakeauthpass"',
            'snmpv3 user "late" auth md5 "fakeauthpass"',
            'snmpv3 group "managerpriv" user "early" sec-model ver3',
        )
        assert [(u.name, u.group, u.auth_protocol) for u in tree.snmp.v3_users] == [
            ("late", "operatorauth", "md5"), ("early", "managerpriv", "sha"),
        ]

    def test_a_trunk_line_links_the_members_that_have_a_stanza_above_it(self) -> None:
        tree = _aoss(
            "interface 1", '   name "a"', "   exit", "trunk 1-2 trk1 lacp", "interface 2", '   name "b"', "   exit",
        )
        linked = [(i.name, i.lag_member_of) for i in tree.interfaces if i.name in {"1", "2"}]
        assert linked == [("1", "trk1"), ("2", "trk1")]


    def test_of_two_stanzas_of_one_name_a_trunk_line_links_the_later(self) -> None:
        """What the dict a trunk line used to build from every
        interface answered with: the last record of a name.  The pass
        after the loop does the same, so the earlier one stays as it
        was."""
        tree = _aoss(
            "interface 1", '   name "a"', "   exit", "interface 1", '   name "b"', "   exit", "trunk 1 trk1 lacp",
        )
        assert [(i.description, i.lag_member_of) for i in tree.interfaces if i.name == "1"] == [
            ("a", None), ("b", "trk1"),
        ]


# ---------------------------------------------------------------------------
# OPNsense
# ---------------------------------------------------------------------------


class TestOpnsenseLaggMembers:
    def test_every_interface_of_a_members_name_is_linked_to_the_first_lagg(self) -> None:
        text = (
            '<?xml version="1.0"?>\n<opnsense>\n<system><hostname>fw</hostname><domain>example.test</domain></system>\n'
            "<interfaces><wan><if>igb0</if></wan><lan><if>igb1</if></lan><opt1><if>igb0</if></opt1></interfaces>\n"
            "<laggs>"
            "<lagg><laggif>lagg0</laggif><members>igb0,igb9</members><proto>lacp</proto></lagg>"
            "<lagg><laggif>lagg1</laggif><members>igb0,igb1</members><proto>lacp</proto></lagg>"
            "</laggs>\n</opnsense>\n"
        )
        tree = OPN.parse(text)
        assert [(i.name, i.lag_member_of) for i in tree.interfaces] == [
            ("igb0", "lagg0"), ("igb1", "lagg1"), ("igb0", "lagg0"),
        ]
        assert [(lag.name, lag.members) for lag in tree.lags] == [
            ("lagg0", ["igb0", "igb9"]), ("lagg1", ["igb0", "igb1"]),
        ]


# ---------------------------------------------------------------------------
# RouterOS
# ---------------------------------------------------------------------------


def _ros(networks: list[str], ranges: list[str], pools_first: bool = False) -> CanonicalIntent:
    nets = ["/ip dhcp-server network", *(f"add address={network} gateway=192.0.2.1" for network in networks)]
    pools = ["/ip pool", *(f"add name=p{n} ranges={value}" for n, value in enumerate(ranges))]
    body = [*pools, *nets] if pools_first else [*nets, *pools]
    return ROS.parse("\n".join(("# 2026-01-01 00:00:00 by RouterOS 7.14", *body)) + "\n")


class TestRouterOsPools:
    @staticmethod
    def _pools(tree: CanonicalIntent) -> list[tuple[str, str, str]]:
        return [(pool.network, pool.start_ip, pool.end_ip) for pool in tree.dhcp_servers]

    def test_a_range_goes_to_the_network_that_holds_its_start(self) -> None:
        tree = _ros(["10.0.0.0/24", "10.0.1.0/24"], ["10.0.1.10-10.0.1.20", "10.0.0.5-10.0.0.9"])
        assert self._pools(tree) == [
            ("10.0.0.0/24", "10.0.0.5", "10.0.0.9"), ("10.0.1.0/24", "10.0.1.10", "10.0.1.20"),
        ]

    def test_of_two_networks_that_hold_it_the_first_in_the_config_has_it(self) -> None:
        wide_first = _ros(["10.0.0.0/16", "10.0.1.0/24"], ["10.0.1.10-10.0.1.20"])
        assert self._pools(wide_first) == [("10.0.0.0/16", "10.0.1.10", "10.0.1.20"), ("10.0.1.0/24", "", "")]
        narrow_first = _ros(["10.0.1.0/24", "10.0.0.0/16"], ["10.0.1.10-10.0.1.20"])
        assert self._pools(narrow_first) == [("10.0.1.0/24", "10.0.1.10", "10.0.1.20"), ("10.0.0.0/16", "", "")]

    def test_of_two_statements_of_one_network_the_first_has_it(self) -> None:
        tree = _ros(["10.0.0.0/24", "10.0.0.0/24"], ["10.0.0.5-10.0.0.9"])
        assert self._pools(tree) == [("10.0.0.0/24", "10.0.0.5", "10.0.0.9"), ("10.0.0.0/24", "", "")]

    def test_a_later_range_for_a_network_replaces_the_earlier(self) -> None:
        tree = _ros(["10.0.0.0/24"], ["10.0.0.5-10.0.0.9", "10.0.0.50-10.0.0.90"])
        assert self._pools(tree) == [("10.0.0.0/24", "10.0.0.50", "10.0.0.90")]

    def test_a_range_no_network_holds_is_a_pool_of_its_own(self) -> None:
        tree = _ros(["10.0.0.0/24"], ["198.51.100.7-198.51.100.9", "198.51.100.7-198.51.100.8"])
        assert self._pools(tree) == [
            ("10.0.0.0/24", "", ""), ("", "198.51.100.7", "198.51.100.9"), ("", "198.51.100.7", "198.51.100.8"),
        ]

    def test_a_default_network_holds_everything(self) -> None:
        tree = _ros(["10.0.0.0/24", "0.0.0.0/0"], ["198.51.100.7-198.51.100.9", "10.0.0.5-10.0.0.9"])
        assert self._pools(tree) == [
            ("10.0.0.0/24", "10.0.0.5", "10.0.0.9"), ("0.0.0.0/0", "198.51.100.7", "198.51.100.9"),
        ]

    def test_a_network_that_is_no_ipv4_network_holds_nothing(self) -> None:
        tree = _ros(["2001:db8::/64", "not-a-network"], ["10.0.0.5-10.0.0.9"])
        assert self._pools(tree)[-1] == ("", "10.0.0.5", "10.0.0.9")

    def test_the_sections_may_come_in_either_order(self) -> None:
        tree = _ros(["10.0.0.0/24"], ["10.0.0.5-10.0.0.9"], pools_first=True)
        assert self._pools(tree) == [("10.0.0.0/24", "10.0.0.5", "10.0.0.9")]
