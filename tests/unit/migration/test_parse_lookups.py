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

The same goes for a list of ONE record that a line adds to after
looking for its value there (the addresses of one interface, the
members of one LAG): the look is now ``Uniques``, and what each such
list comes to is pinned below, as it was when the handler read the
list -- and for three scans over another list that were given an
index of their own.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalLAG,
    CanonicalSNMPv3User,
    CanonicalVlan,
)
from netcanon.migration.canonical.transforms import _PortList, project_switchport_to_vlan
from netcanon.migration.codecs._helpers import GrowingIndex, Uniques, address_key
from netcanon.migration.codecs.cisco_nxos import render as nxos_render
from netcanon.migration.codecs.opnsense import render as opnsense_render
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.codecs.vyos import render as vyos_render
from netcanon.services import migration_pipeline
from netcanon.services.migration_pipeline import run_plan_with_overrides

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
# The list that is added to unless it has the value
# ---------------------------------------------------------------------------


class TestUniques:
    #: Among them 1, 1.0 and True, which are one value to a list.
    VALUES = ["a", "b", "A", "", ("10.0.0.1", 24), ("10.0.0.1", 25), 1, 1.0, True, 2, None]

    def test_it_does_what_looking_first_did(self) -> None:
        """``add`` is ``if value not in lst: lst.append(value)``, on
        several lists at once, with entries appended by someone else
        and a list cut short between two questions."""
        rng = random.Random(11)
        for _ in range(2000):
            once = Uniques()
            plain: list[list[object]] = [[], [], []]
            kept: list[list[object]] = [[], [], []]
            for _ in range(rng.randint(0, 30)):
                which, value, roll = rng.randrange(3), rng.choice(self.VALUES), rng.random()
                if roll < 0.15:
                    plain[which].append(value)
                    kept[which].append(value)
                    continue
                if roll < 0.25:
                    cut = rng.randrange(len(plain[which]) + 1)
                    del plain[which][cut:]
                    del kept[which][cut:]
                is_new = value not in plain[which]
                if is_new:
                    plain[which].append(value)
                assert once.add(kept[which], value) is is_new
            assert kept == plain
            assert [[type(value) for value in values] for values in kept] == [
                [type(value) for value in values] for values in plain
            ]

    def test_a_value_is_appended_once_in_order(self) -> None:
        once, kept = Uniques(), []
        assert [once.add(kept, value) for value in ("b", "a", "b", "c", "a")] == [True, True, False, True, False]
        assert kept == ["b", "a", "c"]

    def test_an_entry_anyone_appended_is_known(self) -> None:
        once, kept = Uniques(), ["a"]
        assert not once.add(kept, "a")
        kept.append("b")
        assert not once.add(kept, "b") and once.add(kept, "c") and kept == ["a", "b", "c"]

    def test_a_list_that_is_gone_is_not_taken_for_the_next(self) -> None:
        """A parser drops a record in the middle of a config, and the
        next list made may stand where the last one stood.  The
        helper holds each list it has read, so the two are never
        one list to it."""
        for _ in range(100):
            once = Uniques()
            first = ["a"]
            once.add(first, "b")
            del first
            other = ["x", "y"]
            assert once.add(other, "a") and other == ["x", "y", "a"]

    def test_a_shorter_list_is_read_again(self) -> None:
        once, kept = Uniques(), []
        once.add(kept, "a")
        once.add(kept, "b")
        del kept[:]
        assert once.add(kept, "b") and kept == ["b"]

    def test_a_list_given_anew_is_another_list(self) -> None:
        once, record = Uniques(), {"members": ["a"]}
        assert not once.add(record["members"], "a")
        record["members"] = []
        assert once.add(record["members"], "a") and record["members"] == ["a"]

    def test_two_lists_are_kept_apart(self) -> None:
        once, first, second = Uniques(), [], []
        assert once.add(first, "a") and once.add(second, "a") and not once.add(first, "a")
        assert (first, second) == (["a"], ["a"])

    def test_each_entry_is_read_once(self) -> None:
        """The point of it: five thousand values given to one list ask
        for five thousand keys, and for one more for each entry that
        someone else appended."""
        asked: list[object] = []

        def key(value: object) -> object:
            asked.append(value)
            return value

        once, kept = Uniques(), []
        for value in range(5000):
            once.add(kept, value, key)
        assert len(asked) == 5000 and kept == list(range(5000))
        kept.extend(["x", "y"])
        once.add(kept, "x", key)
        assert len(asked) == 5003

    def test_records_are_found_by_key(self) -> None:
        once, kept = Uniques(), []
        first = CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24)
        again = CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24)
        other = CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24, is_secondary=True)
        assert once.add(kept, first, address_key) and not once.add(kept, again, address_key)
        assert once.add(kept, other, address_key) and kept == [first, other] and kept[0] is first

    def test_a_coarse_key_costs_no_answer(self) -> None:
        once, kept = Uniques(), []
        addresses = [
            CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24),
            CanonicalIPv4Address(ip="10.0.0.1", prefix_length=25),
            CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24),
        ]
        assert [once.add(kept, address, lambda _address: "one key") for address in addresses] == [True, True, False]

    def test_addresses_that_differ_are_two(self) -> None:
        """Whatever the record holds, now or later: a field the key
        leaves out is still compared."""
        plain = {"ip": "10.0.0.1", "prefix_length": 24}
        different = {
            "ip": "10.0.0.2", "prefix_length": 25, "is_secondary": True,
            "virtual_gateway_address": "10.0.0.254", "virtual_gateway_mac": "00:00:5e:00:01:01",
        }
        assert set(different) == set(CanonicalIPv4Address.model_fields), "a field this test has no value for"
        for field, value in different.items():
            once, kept = Uniques(), []
            base, changed = CanonicalIPv4Address(**plain), CanonicalIPv4Address(**{**plain, field: value})
            assert base != changed
            assert once.add(kept, base, address_key) and once.add(kept, changed, address_key), field
            assert not once.add(kept, CanonicalIPv4Address(**{**plain, field: value}), address_key), field
            assert address_key(changed) == address_key(CanonicalIPv4Address(**{**plain, field: value}))


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


    def test_two_stanzas_of_one_interface_are_one_record_for_a_trunk_line(self) -> None:
        """Two ``interface`` stanzas of one name are one record -- the
        second goes on with the first, as the device reads them -- so
        a trunk line has one record to link, and the later ``name``
        is its description."""
        tree = _aoss(
            "interface 1", '   name "a"', "   exit", "interface 1", '   name "b"', "   exit", "trunk 1 trk1 lacp",
        )
        assert [(i.description, i.lag_member_of) for i in tree.interfaces if i.name == "1"] == [
            ("b", "trk1"),
        ]

    def test_of_two_records_of_one_name_a_trunk_line_links_the_later(self) -> None:
        """What the dict a trunk line used to build from every
        interface answered with: the last record of a name.  The pass
        after the loop does the same, so the earlier one stays as it
        was.  Two records of one name are still made by a VLAN stanza
        met twice: each makes a ``Vlan<N>`` interface."""
        tree = _aoss(
            "vlan 10", "   ip address 192.0.2.1 255.255.255.0", "   exit",
            "vlan 10", "   ip address 198.51.100.1 255.255.255.0", "   exit",
            "trunk Vlan10 trk1 lacp",
        )
        assert [
            (i.ipv4_addresses[0].ip, i.lag_member_of) for i in tree.interfaces if i.name == "Vlan10"
        ] == [("192.0.2.1", None), ("198.51.100.1", "trk1")]


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
        # ``igb9``, which no zone assigns, is given a record of its own.
        assert [(i.name, i.lag_member_of) for i in tree.interfaces] == [
            ("igb0", "lagg0"), ("igb1", "lagg1"), ("igb0", "lagg0"), ("igb9", "lagg0"),
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


# ---------------------------------------------------------------------------
# Lists of one record
# ---------------------------------------------------------------------------


def _parsed(codec: str, *lines: str) -> CanonicalIntent:
    return get_codec(codec).parse("\n".join(lines) + "\n")


def _named(records: Any, name: object, by: str = "name") -> Any:
    return next(record for record in records if getattr(record, by) == name)


def _written(addresses: Any) -> list[str]:
    """``ip/length``, with an ``s`` on a secondary."""
    return [
        f"{address.ip}/{address.prefix_length}" + ("s" if getattr(address, "is_secondary", False) else "")
        for address in addresses
    ]


_UNIT = "set interfaces ge-0/0/0 unit 0 family"
_IRB = "set interfaces irb unit 100 family"
_VRRP = "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/8 vrrp-group 1"
_POOL = "set access address-assignment pool P family inet"
_OLD_POOL = "set system services dhcp pool 10.0.0.0/8"
_VRF = "set routing-instances V"
_USM = "set snmp v3 usm local-engine user"
_HOST = "set system host-name r1"
_NETCONF = (
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<rpc-reply xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" message-id="101">', "<data>",
    '<interfaces xmlns="http://openconfig.net/yang/interfaces">',
)


def _netconf_svi(*addresses: str) -> str:
    return (
        "<interface><name>Vlan10</name><config><name>Vlan10</name><enabled>true</enabled></config>"
        '<subinterfaces><subinterface><index>0</index><ipv4 xmlns="http://openconfig.net/yang/interfaces/ip">'
        "<addresses>" + "".join(
            f"<address><ip>{address}</ip><config><ip>{address}</ip>"
            "<prefix-length>24</prefix-length></config></address>"
            for address in addresses
        ) + "</addresses></ipv4></subinterface></subinterfaces></interface>"
    )


def _both_lists(instance: Any) -> list[list[str]]:
    return [instance.rt_imports, instance.rt_exports]


def _members(tree: CanonicalIntent) -> list[list[object]]:
    return [[lag.name, lag.members] for lag in tree.lags]


#: A text for each list of one record that a line adds to after
#: looking for its value there, with a value stated twice and the
#: values out of order -- and what the list came to before the look
#: was taken out of the handler: each value once, where it first came.
ONE_RECORD: dict[str, tuple[Callable[[], object], object]] = {
    "juniper_junos: a unit's addresses": (
        lambda: _written(_named(_parsed(
            "juniper_junos", _HOST, f"{_UNIT} inet address 10.0.0.2/24", f"{_UNIT} inet address 10.0.0.1/24",
            f"{_UNIT} inet address 10.0.0.2/24", f"{_UNIT} inet address 10.0.0.2/25",
            f"{_UNIT} inet address 10.0.0.1/24",
        ).interfaces, "ge-0/0/0").ipv4_addresses),
        ["10.0.0.2/24", "10.0.0.1/24", "10.0.0.2/25"],
    ),
    "juniper_junos: a unit's IPv6 addresses": (
        lambda: _written(_named(_parsed(
            "juniper_junos", _HOST, f"{_UNIT} inet6 address 2001:db8::2/64", f"{_UNIT} inet6 address 2001:db8::1/64",
            f"{_UNIT} inet6 address 2001:db8::2/64",
        ).interfaces, "ge-0/0/0").ipv6_addresses),
        ["2001:db8::2/64", "2001:db8::1/64"],
    ),
    "juniper_junos: an IRB unit's addresses": (
        lambda: _written(_named(_parsed(
            "juniper_junos", _HOST, f"{_IRB} inet address 10.0.0.2/24", f"{_IRB} inet address 10.0.0.1/24",
            f"{_IRB} inet address 10.0.0.2/24",
        ).interfaces, "irb.100").ipv4_addresses),
        ["10.0.0.2/24", "10.0.0.1/24"],
    ),
    "juniper_junos: an IRB unit's addresses, folded onto its VLAN": (
        lambda: _written(_named(_parsed(
            "juniper_junos", _HOST, "set vlans V100 vlan-id 100", "set vlans V100 l3-interface irb.100",
            f"{_IRB} inet address 10.0.0.2/24", f"{_IRB} inet address 10.0.0.1/24",
            f"{_IRB} inet address 10.0.0.2/24",
        ).vlans, 100, "id").ipv4_addresses),
        ["10.0.0.2/24", "10.0.0.1/24"],
    ),
    "juniper_junos: an IRB unit's IPv6 addresses": (
        lambda: _written(_named(_parsed(
            "juniper_junos", _HOST, f"{_IRB} inet6 address 2001:db8::2/64", f"{_IRB} inet6 address 2001:db8::1/64",
            f"{_IRB} inet6 address 2001:db8::2/64",
        ).interfaces, "irb.100").ipv6_addresses),
        ["2001:db8::2/64", "2001:db8::1/64"],
    ),
    "juniper_junos: a LAG's members": (
        lambda: _named(_parsed(
            "juniper_junos", _HOST, "set interfaces ge-0/0/7 ether-options 802.3ad ae0",
            "set interfaces ge-0/0/3 ether-options 802.3ad ae0", "set interfaces ge-0/0/7 ether-options 802.3ad ae0",
            "set interfaces ge-0/0/5 ether-options 802.3ad ae1",
        ).lags, "ae0").members,
        ["ge-0/0/7", "ge-0/0/3"],
    ),
    "juniper_junos: an interface-range's members and addresses": (
        lambda: [[port.name, _written(port.ipv4_addresses)] for port in _parsed(
            "juniper_junos", _HOST, "set interfaces interface-range R member ge-0/0/2",
            "set interfaces interface-range R member ge-0/0/1", "set interfaces interface-range R member ge-0/0/2",
            "set interfaces interface-range R unit 0 family inet address 10.0.0.2/24",
            "set interfaces interface-range R unit 0 family inet address 10.0.0.1/24",
            "set interfaces interface-range R unit 0 family inet address 10.0.0.2/24",
        ).interfaces],
        [["ge-0/0/1", ["10.0.0.2/24", "10.0.0.1/24"]], ["ge-0/0/2", ["10.0.0.2/24", "10.0.0.1/24"]]],
    ),
    "juniper_junos: a pool's name servers": (
        lambda: _parsed(
            "juniper_junos", _HOST, f"{_POOL} network 10.0.0.0/8", f"{_POOL} dhcp-attributes name-server 10.0.0.2",
            f"{_POOL} dhcp-attributes name-server 10.0.0.1", f"{_POOL} dhcp-attributes name-server 10.0.0.2",
        ).dhcp_servers[0].dns_servers,
        ["10.0.0.2", "10.0.0.1"],
    ),
    "juniper_junos: a pool's name servers, old grammar": (
        lambda: _parsed(
            "juniper_junos", _HOST, f"{_OLD_POOL} name-server 10.0.0.2", f"{_OLD_POOL} name-server 10.0.0.1",
            f"{_OLD_POOL} name-server 10.0.0.2",
        ).dhcp_servers[0].dns_servers,
        ["10.0.0.2", "10.0.0.1"],
    ),
    "juniper_junos: a VRF's route targets": (
        lambda: _both_lists(_named(_parsed(
            "juniper_junos", _HOST, f"{_VRF} instance-type vrf", f"{_VRF} vrf-target import target:65000:2",
            f"{_VRF} vrf-target target:65000:1", f"{_VRF} vrf-target export target:65000:3",
            f"{_VRF} vrf-target import target:65000:1", f"{_VRF} vrf-target target:65000:2",
            f"{_VRF} vrf-target export target:65000:3",
        ).routing_instances, "V")),
        [["65000:2", "65000:1"], ["65000:1", "65000:3", "65000:2"]],
    ),
    "juniper_junos: a VRRP group's addresses and tracked interfaces": (
        lambda: (lambda group: [group.virtual_ips, group.virtual_ipv6s, group.track_interfaces])(_named(_parsed(
            "juniper_junos", _HOST, f"{_VRRP} virtual-address 10.0.0.9", f"{_VRRP} virtual-address 10.0.0.8",
            f"{_VRRP} virtual-address 10.0.0.9", f"{_VRRP} track interface ge-0/0/2",
            f"{_VRRP} track interface ge-0/0/1", f"{_VRRP} track interface ge-0/0/2",
            f"{_VRRP} virtual-inet6-address 2001:db8::9", f"{_VRRP} virtual-inet6-address 2001:db8::9",
        ).interfaces, "ge-0/0/0").vrrp_groups[0]),
        [["10.0.0.9", "10.0.0.8"], ["2001:db8::9"], ["ge-0/0/2", "ge-0/0/1"]],
    ),
    "juniper_junos: SNMPv3 users, their lines in any order": (
        lambda: [[user.name, user.auth_protocol, user.priv_protocol, user.group] for user in _parsed(
            "juniper_junos", _HOST, f"{_USM} u2 authentication-sha authentication-password fakepass2",
            f"{_USM} u1 authentication-md5 authentication-password fakepass1",
            f"{_USM} u2 privacy-aes128 privacy-password fakepriv2",
            "set snmp v3 vacm security-to-group security-model usm security-name u1 group G1",
            "set snmp v3 vacm security-to-group security-model usm security-name u3 group G3",
            f"{_USM} u2 authentication-sha authentication-password fakepass2",
        ).snmp.v3_users],
        [["u2", "sha", "aes128", ""], ["u1", "md5", "", "G1"], ["u3", "", "", "G3"]],
    ),
    "arista_eos: a VRF's route targets": (
        lambda: _both_lists(_named(_parsed(
            "arista_eos", "hostname sw", "!", "vrf instance V", "   route-target import 65000:2",
            "   route-target both 65000:1", "   route-target export 65000:3", "   route-target import 65000:1",
            "   route-target import 65000:2", "   route-target export 65000:3", "!",
        ).routing_instances, "V")),
        [["65000:2", "65000:1"], ["65000:1", "65000:3"]],
    ),
    "arista_eos: a VRF's route targets under router bgp": (
        lambda: _both_lists(_named(_parsed(
            "arista_eos", "hostname sw", "!", "router bgp 65001", "   vrf V", "      rd 65001:1",
            "      route-target import evpn 65000:2", "      route-target both 65000:1",
            "      route-target export evpn 65000:3", "      route-target import 65000:1",
            "      route-target import evpn 65000:2", "      route-target export 65000:3", "!",
        ).routing_instances, "V")),
        [["65000:2", "65000:1"], ["65000:1", "65000:3"]],
    ),
    "arista_eos: a VRRP group's tracked interfaces": (
        lambda: _named(_parsed(
            "arista_eos", "hostname sw", "!", "interface Ethernet1", "   no switchport", "   ip address 10.0.0.1/8",
            "   vrrp 1 track Ethernet7", "   vrrp 1 track Ethernet3", "   vrrp 1 track Ethernet7",
            "   vrrp 2 track Ethernet7", "!",
        ).interfaces, "Ethernet1").vrrp_groups[0].track_interfaces,
        ["Ethernet7", "Ethernet3"],
    ),
    "aruba_aoscx: a LAG's members": (
        lambda: _members(_parsed(
            "aruba_aoscx", "hostname sw", "interface lag 1", "    no shutdown", "interface 1/1/7", "    lag 1",
            "interface 1/1/3", "    lag 1", "interface 1/1/7", "    lag 1", "interface 1/1/5", "    lag 2",
        )),
        [["lag 1", ["1/1/7", "1/1/3"]], ["lag 2", ["1/1/5"]]],
    ),
    "cisco_iosxe_cli: a LAG's members": (
        lambda: _members(_parsed(
            "cisco_iosxe_cli", "hostname sw", "!", "interface GigabitEthernet1/0/7", " channel-group 1 mode active",
            "!", "interface GigabitEthernet1/0/3", " channel-group 1 mode active", "!",
            "interface GigabitEthernet1/0/7", " channel-group 1 mode on", "!", "interface GigabitEthernet1/0/5",
            " channel-group 2 mode active", "!",
        )),
        [["Port-channel1", ["GigabitEthernet1/0/7", "GigabitEthernet1/0/3"]],
         ["Port-channel2", ["GigabitEthernet1/0/5"]]],
    ),
    "cisco_iosxr: a LAG's members": (
        lambda: _members(_parsed(
            "cisco_iosxr", "hostname r1", "!", "interface GigabitEthernet0/0/0/7", " bundle id 1 mode active", "!",
            "interface GigabitEthernet0/0/0/3", " bundle id 1 mode active", "!", "interface GigabitEthernet0/0/0/7",
            " bundle id 1 mode active", "!", "interface GigabitEthernet0/0/0/5", " bundle id 2 mode active", "!",
        )),
        [["Bundle-Ether1", ["GigabitEthernet0/0/0/7", "GigabitEthernet0/0/0/3"]],
         ["Bundle-Ether2", ["GigabitEthernet0/0/0/5"]]],
    ),
    "cisco_nxos: a LAG's members": (
        lambda: _members(_parsed(
            "cisco_nxos", "hostname sw", "feature lacp", "interface Ethernet1/7", "  channel-group 1 mode active",
            "interface Ethernet1/3", "  channel-group 1 mode active", "interface Ethernet1/7",
            "  channel-group 1 mode active", "interface Ethernet1/5", "  channel-group 2 mode active",
        )),
        [["port-channel1", ["Ethernet1/7", "Ethernet1/3"]], ["port-channel2", ["Ethernet1/5"]]],
    ),
    "dell_os10: a LAG's members": (
        lambda: _members(_parsed(
            "dell_os10", "! Version 10.5.4.0", "hostname sw", "!", "interface ethernet1/1/7",
            " channel-group 1 mode active", "!", "interface ethernet1/1/3", " channel-group 1 mode active", "!",
            "interface ethernet1/1/7", " channel-group 1 mode active", "!", "interface ethernet1/1/5",
            " channel-group 2 mode active", "!",
        )),
        [["port-channel1", ["ethernet1/1/7", "ethernet1/1/3"]], ["port-channel2", ["ethernet1/1/5"]]],
    ),
    "aruba_aoscx: an SVI's addresses on its VLAN": (
        lambda: _written(_named(_parsed(
            "aruba_aoscx", "hostname sw", "vlan 10", "    name users", "interface vlan 10",
            "    ip address 10.0.0.2/24", "    ip address 10.0.0.1/24 secondary",
            "    ip address 10.0.0.2/24 secondary", "    ip address 10.0.0.1/24 secondary",
        ).vlans, 10, "id").ipv4_addresses),
        ["10.0.0.2/24", "10.0.0.1/24s", "10.0.0.2/24s"],
    ),
    "cisco_iosxe_cli: an SVI's addresses on its VLAN": (
        lambda: _written(_named(_parsed(
            "cisco_iosxe_cli", "hostname sw", "!", "vlan 10", " name users", "!", "interface Vlan10",
            " ip address 10.0.0.2 255.255.255.0", " ip address 10.0.0.1 255.255.255.0 secondary",
            " ip address 10.0.0.2 255.255.255.0 secondary", " ip address 10.0.0.1 255.255.255.0 secondary", "!",
        ).vlans, 10, "id").ipv4_addresses),
        ["10.0.0.2/24", "10.0.0.1/24s", "10.0.0.2/24s"],
    ),
    "cisco_nxos: an SVI's addresses on its VLAN": (
        lambda: _written(_named(_parsed(
            "cisco_nxos", "hostname sw", "feature interface-vlan", "vlan 10", "  name users", "interface Vlan10",
            "  ip address 10.0.0.2/24", "  ip address 10.0.0.1/24 secondary", "  ip address 10.0.0.2/24 secondary",
            "  ip address 10.0.0.1/24 secondary",
        ).vlans, 10, "id").ipv4_addresses),
        ["10.0.0.2/24", "10.0.0.1/24s", "10.0.0.2/24s"],
    ),
    "dell_os10: a second SVI stanza's addresses on the VLAN": (
        lambda: _written(_named(_parsed(
            "dell_os10", "! Version 10.5.4.0", "hostname sw", "!", "interface vlan10", " ip address 10.0.0.2/24",
            "!", "interface vlan10", " ip address 10.0.0.1/24 secondary", " ip address 10.0.0.2/24",
            " ip address 10.0.0.1/24 secondary", " ip address 10.0.0.2/24 secondary", "!",
        ).vlans, 10, "id").ipv4_addresses),
        ["10.0.0.2/24", "10.0.0.1/24s", "10.0.0.2/24s"],
    ),
    "cisco_iosxe: a second SVI element's addresses on the VLAN": (
        lambda: _written(_named(_parsed(
            "cisco_iosxe", *_NETCONF, _netconf_svi("10.0.0.2"),
            _netconf_svi("10.0.0.1", "10.0.0.2", "10.0.0.1", "10.0.0.3"), "</interfaces>", "</data>", "</rpc-reply>",
        ).vlans, 10, "id").ipv4_addresses),
        ["10.0.0.2/24", "10.0.0.1/24", "10.0.0.3/24"],
    ),
    "vyos: a bond's members": (
        lambda: _members(_parsed(
            "vyos", _HOST, "set interfaces bonding bond0 mode 802.3ad",
            "set interfaces bonding bond0 member interface eth7", "set interfaces bonding bond0 member interface eth3",
            "set interfaces bonding bond0 member interface eth7", "set interfaces bonding bond1 member interface eth5",
        )),
        [["bond0", ["eth7", "eth3"]], ["bond1", ["eth5"]]],
    ),
    "vyos: NTP servers, under both paths": (
        lambda: _parsed(
            "vyos", _HOST, "set service ntp server 10.0.0.2", "set service ntp server 10.0.0.1",
            "set service ntp server 10.0.0.2", "set system ntp server 10.0.0.3", "set system ntp server 10.0.0.1",
        ).ntp_servers,
        ["10.0.0.3", "10.0.0.1", "10.0.0.2"],
    ),
    "vyos: a VXLAN's remotes": (
        lambda: _parsed(
            "vyos", _HOST, "set interfaces vxlan vxlan10 vni 10010", "set interfaces vxlan vxlan10 remote 10.0.0.2",
            "set interfaces vxlan vxlan10 remote 10.0.0.1", "set interfaces vxlan vxlan10 remote 10.0.0.2",
        ).vxlan_vnis[0].flood_list,
        ["10.0.0.2", "10.0.0.1"],
    ),
    "mikrotik_routeros: NTP servers from both sections": (
        lambda: _parsed(
            "mikrotik_routeros", "# 2026-01-01 00:00:00 by RouterOS 7.14", "/system ntp client",
            "set enabled=yes servers=10.0.0.2,pool.ntp.org,10.0.0.2", "/system ntp client servers",
            "add address=10.0.0.1", "add address=pool.ntp.org", "add address=0.0.0.0", "add address=10.0.0.3",
            "add address=10.0.0.1",
        ).ntp_servers,
        ["10.0.0.2", "pool.ntp.org", "10.0.0.1", "10.0.0.3"],
    ),
    "mikrotik_routeros: NTP servers, the keys of RouterOS 6": (
        lambda: _parsed(
            "mikrotik_routeros", "# 2026-01-01 00:00:00 by RouterOS 7.14", "/system ntp client",
            "set enabled=yes primary-ntp=10.0.0.2 secondary-ntp=10.0.0.2 "
            "server-dns-names=b.example,a.example,b.example",
        ).ntp_servers,
        ["10.0.0.2", "b.example", "a.example"],
    ),
    "aruba_aoss: a VLAN's ports, stated and taken back": (
        lambda: (lambda vlan: [vlan.untagged_ports, vlan.tagged_ports])(_named(_aoss(
            "vlan 10", "   untagged 1-3", "   untagged 2,5", "   no untagged 2", "   untagged 2", "   no untagged 9",
            "   tagged 7,8,7", "   tagged Trk1", "   no tagged 8", "   tagged 8,6", "   exit",
        ).vlans, 10, "id")),
        [["1", "2", "3", "5"], ["6", "7", "8", "trk1"]],
    ),
    "aruba_aoss: a VLAN's ports, every one of them taken back": (
        lambda: (lambda vlan: [vlan.untagged_ports, vlan.tagged_ports])(_named(_aoss(
            "vlan 10", "   untagged 1-3", "   no untagged 1-3", "   tagged 4", "   no tagged 4,5", "   untagged 3",
            "   exit",
        ).vlans, 10, "id")),
        [["3"], []],
    ),
}


class TestListsOfOneRecord:
    @pytest.mark.parametrize("title", sorted(ONE_RECORD))
    def test_a_value_stated_twice_is_there_once(self, title: str) -> None:
        made, before = ONE_RECORD[title]
        assert made() == before

    def test_an_aoss_stanza_gives_the_same_list(self) -> None:
        """Before the passes that drop a repeat and sort: the ports
        of every line in the order they were stated (a line names a
        port once), less what a ``no`` line found above it.  A port
        stated again after such a line is there."""
        from netcanon.migration.codecs.aruba_aoss.parse import _parse_vlan_stanza

        lines = [
            "   untagged 3,1", "   untagged 2,3", "   no untagged 1,7", "   untagged 1", "   no untagged 2",
            "   untagged 2,2", "   untagged 2", "   tagged 9", "   tagged 8,9", "   no tagged 9", "   tagged 9",
            "   exit",
        ]
        vlan, _groups, _v6, after = _parse_vlan_stanza(lines, 0, 10)
        assert (vlan.untagged_ports, vlan.tagged_ports, after) == (["3", "3", "1", "2", "2"], ["8", "9"], len(lines))

    def test_and_does_so_on_random_stanzas(self) -> None:
        """Against the list written again for every ``no`` line, as
        the reader used to do it."""
        from netcanon.migration.codecs.aruba_aoss.parse import _parse_vlan_stanza

        rng = random.Random(21)
        for _ in range(500):
            lines, untagged, tagged = [], [], []
            for _ in range(rng.randrange(0, 12)):
                ports = [str(rng.randrange(1, 7)) for _ in range(rng.randrange(1, 4))]
                word, kept = rng.choice((("untagged", untagged), ("tagged", tagged)))
                if rng.random() < 0.35:
                    lines.append(f"   no {word} {','.join(ports)}")
                    kept[:] = [port for port in kept if port not in ports]
                else:
                    lines.append(f"   {word} {','.join(ports)}")
                    kept.extend(dict.fromkeys(ports))
            vlan, _groups, _v6, _after = _parse_vlan_stanza([*lines, "   exit"], 0, 10)
            assert (vlan.untagged_ports, vlan.tagged_ports) == (untagged, tagged), lines


# ---------------------------------------------------------------------------
# Scans over another list, each given an index that is built once
# ---------------------------------------------------------------------------


def _parent_by_walking(vlan: Any, intent: CanonicalIntent, default: str) -> str:
    """The OPNsense renderer's search for a VLAN's parent, walked:
    every interface for every LAG, and again for every member, then
    the plain interfaces -- once for a trunk that names the VLAN, and
    once more for a trunk of every VLAN."""
    members = {member for lag in intent.lags for member in lag.members}
    for of_every_vlan in (False, True):
        def carries(iface: Any, wide: bool = of_every_vlan) -> bool:
            every = set(range(1, 4095)) <= set(iface.trunk_allowed_vlans)
            return every is wide and vlan.id in iface.trunk_allowed_vlans

        for lag in intent.lags:
            for iface in intent.interfaces:
                if iface.name == lag.name and carries(iface):
                    return lag.name
            for member in lag.members:
                for iface in intent.interfaces:
                    if iface.name == member and carries(iface):
                        return lag.name
        for iface in intent.interfaces:
            if iface.name.lower().startswith("vlan") or iface.name in members:
                continue
            if carries(iface):
                return iface.name
    return default


class TestAnIndexBuiltOnce:
    def test_opnsense_parent_is_the_one_reached(self) -> None:
        names = ["lagg0", "lagg1", "Po2", "igb0", "igb1", "igb2", "Vlan10", "vlan20", "ix0"]
        lists = ([], [10], [10, 20], [20, 30, 40], list(range(1, 4095)), [5, 10, 5])
        rng = random.Random(3)
        for _ in range(400):
            tree = CanonicalIntent(
                interfaces=[
                    CanonicalInterface(name=rng.choice(names), trunk_allowed_vlans=list(rng.choice(lists)))
                    for _ in range(rng.randrange(0, 9))
                ],
                lags=[
                    CanonicalLAG(name=rng.choice(names[:4]), members=rng.sample(names, rng.randrange(0, 4)))
                    for _ in range(rng.randrange(0, 4))
                ],
                vlans=[CanonicalVlan(id=vid) for vid in rng.sample([5, 10, 20, 30, 40, 50], rng.randrange(1, 6))],
            )
            carriers = opnsense_render._vlan_carriers(tree)
            for vlan in tree.vlans:
                assert opnsense_render._vlan_parent_for(vlan, carriers, "lan") == _parent_by_walking(vlan, tree, "lan")

    def test_what_a_dropped_port_took_from_a_lag(self) -> None:
        """A LAG's ports are those it lists and those that say they
        are its members."""
        names = ["1", "2", "3", "4", "5", "6"]
        rng = random.Random(5)
        for _ in range(400):
            tree = CanonicalIntent(
                interfaces=[
                    CanonicalInterface(name=name, lag_member_of=rng.choice([None, None, "trk1", "trk2", "trk9", ""]))
                    for name in rng.sample(names, rng.randrange(0, 7))
                ],
                lags=[
                    CanonicalLAG(name=name, members=rng.sample([*names, ""], rng.randrange(0, 4)))
                    for name in rng.sample(["trk1", "trk2", "trk3"], rng.randrange(0, 4))
                ],
            )
            drops = rng.sample(names, rng.randrange(0, 5))
            emptied, shrunk = [], []
            for lag in tree.lags:
                ports = {member for member in lag.members if member} | {
                    port.name for port in tree.interfaces if lag.name and port.lag_member_of == lag.name
                }
                lost = ports & set(drops)
                if ports and lost == ports:
                    emptied.append(lag.name)
                elif lost:
                    shrunk.append(lag.name)
            _dropped, taken = migration_pipeline._taken_with_dropped_ports(tree, drops)
            assert (taken["emptied_lags"], taken["shrunk_lags"]) == (emptied, shrunk)

    def test_vyos_carries_or_names_each_user(self) -> None:
        users = [
            CanonicalSNMPv3User(name="u3", auth_protocol="sha", auth_passphrase="fakepass3"),
            CanonicalSNMPv3User(name="u1", auth_protocol="sha"),
            CanonicalSNMPv3User(name="u2", auth_protocol="md5", auth_passphrase="fakepass2"),
            CanonicalSNMPv3User(name="u3", auth_protocol="sha", auth_passphrase="fakepass3"),
            CanonicalSNMPv3User(name="u0"),
        ]

        def said(lines: list[str]) -> list[str]:
            """``review u1`` for a user that is named in a comment, ``user u2`` for one that is carried."""
            out = []
            for line in lines:
                words = line.split()
                if words[:3] == ["/*", "snmpv3", "user"]:
                    out.append("review " + words[3].strip('"'))
                elif words[0] == "user":
                    out.append("user " + words[1])
            return out

        assert said(vyos_render._render_snmp_v3(users, "vyos")) == ["review u1", "user u2", "user u3", "user u3"]
        assert said(vyos_render._render_snmp_v3(users, "cisco_iosxe")) == [
            "review u1", "review u2", "review u3", "review u3",
        ]

    def test_nxos_route_targets_of_both_lists(self) -> None:
        rng = random.Random(9)
        for _ in range(300):
            imports = [rng.choice("abcdef") for _ in range(rng.randrange(0, 7))]
            exports = [rng.choice("abcdef") for _ in range(rng.randrange(0, 7))]
            assert nxos_render._render_route_targets(imports, exports) == [
                *(f"    route-target both {rt}" for rt in imports if rt in exports),
                *(f"    route-target import {rt}" for rt in imports if rt not in exports),
                *(f"    route-target export {rt}" for rt in exports if rt not in imports),
            ]

    def test_a_shared_name_names_its_own_two(self) -> None:
        """AOS-S ``1/1`` and module port ``1/A1`` are one name on
        Junos; so are ``1/2`` and ``1/A2``."""
        text = _AOSS_TOP + "".join(
            f'interface {name}\n   name "p"\n   exit\n' for name in ("1/2", "1/A1", "1/1", "1/A2", "1/3")
        )
        job = run_plan_with_overrides(AOSS, JUNOS, text, port_rename_map={})
        shared = [warning.split(";")[0] for warning in job.warnings if "multiple source ports map to" in warning]
        assert shared == [
            "port_rename: multiple source ports map to 'ge-1/0/1' (sources: 1/1, 1/A1)",
            "port_rename: multiple source ports map to 'ge-1/0/2' (sources: 1/2, 1/A2)",
        ]
