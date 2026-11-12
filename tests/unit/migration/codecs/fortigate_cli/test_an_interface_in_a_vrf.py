"""A FortiOS interface in a VRF other than 0 is not written into the
global table of the output: what it routes is left out and said.

"VRFs are always enabled and, by default, all routing is done in VRF
0"; ``set vrf <id>`` on an interface puts it in another, "all routes
relating to that interface are isolated to that VRF specific routing
table", and "interfaces in one VRF cannot reach interfaces in a
different VRF" (Fortinet, FortiOS 7.0.1 Administration Guide,
"Implementing VRF",
https://docs.fortinet.com/document/fortigate/7.0.1/administration-guide/752950).
A static route is put in a VRF by the interface its ``set device``
names (Fortinet KB, "Configure static routes and black hole routes to
different VRFs",
https://community.fortinet.com/t5/FortiGate/Technical-Tip-Configure-static-routes-and-black-hole-routes-to/ta-p/230872).

The parser read no ``set vrf`` of an interface, and the output puts
nothing in a VRF, so up to 0.7.7 such an interface was written with
its addresses, its VRRP groups, the DHCP pool on it and the routes
out it into the one table of the output, connected to every other
interface, in jobs that said ``completed``.

The output is read against an output of the same config written
without those forms -- the interface with no address, no VRRP group
and no pool, and no route out it -- on every public codec: the two
are the same text.  That reading asks nothing of the parser it
checks.
"""

from __future__ import annotations

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.codecs.fortigate_cli import parse as fgt_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

#: A port in the global table, and a port, a VLAN interface on it and a
#: DHCP client in VRFs other than 0, each with what it routes.
_INTERFACES = [
    "config system interface",
    '    edit "port1"',
    "        set ip 192.0.2.1 255.255.255.0",
    "        set type physical",
    "    next",
    '    edit "port3"',
    '        set alias "red side"',
    "        set ip 198.51.100.1 255.255.255.0",
    "        set type physical",
    "        set vrf 5",
    "        config secondaryip",
    "            edit 1",
    "                set ip 198.51.101.1 255.255.255.0",
    "            next",
    "        end",
    "        config ipv6",
    "            set ip6-address 2001:db8:5::1/64",
    "        end",
    "        config vrrp",
    "            edit 7",
    "                set vrip 198.51.100.254",
    "            next",
    "        end",
    "    next",
    '    edit "VL_50"',
    "        set ip 203.0.113.1 255.255.255.0",
    '        set interface "port1"',
    "        set vlanid 50",
    "        set vrf 7",
    "    next",
    '    edit "port4"',
    "        set mode dhcp",
    "        set type physical",
    "        set vrf 9",
    "    next",
    "end",
]

#: The same interfaces as a config with none of the forms writes them.
_INTERFACES_PLAIN = [
    "config system interface",
    '    edit "port1"',
    "        set ip 192.0.2.1 255.255.255.0",
    "        set type physical",
    "    next",
    '    edit "port3"',
    '        set alias "red side"',
    "        set type physical",
    "    next",
    '    edit "VL_50"',
    '        set interface "port1"',
    "        set vlanid 50",
    "    next",
    '    edit "port4"',
    "        set type physical",
    "    next",
    "end",
]

_POOL = [
    "config system dhcp server",
    "    edit 1",
    "        set default-gateway 198.51.100.1",
    "        set netmask 255.255.255.0",
    '        set interface "port3"',
    "        config ip-range",
    "            edit 1",
    "                set start-ip 198.51.100.10",
    "                set end-ip 198.51.100.20",
    "            next",
    "        end",
    "    next",
    "end",
]

_ROUTES = [
    "config router static",
    "    edit 1",
    "        set dst 10.5.0.0 255.255.0.0",
    "        set gateway 198.51.100.9",
    '        set device "port3"',
    "    next",
    "    edit 2",
    "        set dst 10.7.0.0 255.255.0.0",
    "        set gateway 203.0.113.9",
    '        set device "VL_50"',
    "    next",
    "    edit 3",
    "        set gateway 192.0.2.9",
    '        set device "port1"',
    "    next",
    "end",
    "config router static6",
    "    edit 1",
    "        set dst 2001:db8:7::/48",
    "        set gateway 2001:db8:5::9",
    '        set device "port3"',
    "    next",
    "end",
]

_ROUTES_PLAIN = [
    "config router static",
    "    edit 3",
    "        set gateway 192.0.2.9",
    '        set device "port1"',
    "    next",
    "end",
]


def _text(*parts: list[str]) -> str:
    return "\n".join([*(line for part in parts for line in part), ""])


_WITH_THE_FORMS = _text(_INTERFACES, _POOL, _ROUTES)
_WITHOUT_THEM = _text(_INTERFACES_PLAIN, _ROUTES_PLAIN)


def _rendered(text: str, target: str) -> str:
    job = run_plan_with_checked_names(
        get_codec("fortigate_cli"), get_codec(target), text, {},
    )
    return job.rendered or ""


def _tree(text: str):
    return get_codec("fortigate_cli").parse(text)


class TestTheOutput:
    @pytest.mark.parametrize("target", list_public_codecs())
    def test_is_the_output_of_the_config_without_the_forms(self, target: str) -> None:
        assert _rendered(_WITH_THE_FORMS, target) == _rendered(_WITHOUT_THEM, target)

    def test_the_reading_can_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A parser that reads no interface's VRF writes the interface
        with its addresses, and the two outputs differ."""
        monkeypatch.setattr(fgt_parse, "_in_a_vrf", lambda blocks: set())
        assert _rendered(_WITH_THE_FORMS, "cisco_iosxe_cli") != _rendered(
            _WITHOUT_THEM, "cisco_iosxe_cli",
        )

    def test_the_reading_reads_the_interfaces(self) -> None:
        """The compared outputs hold the interfaces and the route that
        stays: a comparison of two empty outputs would pass whatever
        the parser did."""
        out = _rendered(_WITHOUT_THEM, "cisco_iosxe_cli")
        assert "description red side" in out
        assert "ip address 192.0.2.1 255.255.255.0" in out
        assert "encapsulation dot1Q 50" in out
        assert "ip route 0.0.0.0 0.0.0.0" in out


class TestTheTree:
    def test_the_interface_is_kept_without_what_it_routes(self) -> None:
        by_name = {iface.name: iface for iface in _tree(_WITH_THE_FORMS).interfaces}
        port3 = by_name["port3"]
        assert port3.description == "red side"
        assert port3.ipv4_addresses == []
        assert port3.ipv6_addresses == []
        assert port3.vrrp_groups == []
        assert by_name["VL_50"].dot1q_vlan == 50
        assert by_name["VL_50"].ipv4_addresses == []
        assert by_name["port4"].dhcp_client is False
        assert [a.ip for a in by_name["port1"].ipv4_addresses] == ["192.0.2.1"]

    def test_no_pool_and_no_route_out_it(self) -> None:
        tree = _tree(_WITH_THE_FORMS)
        assert tree.dhcp_servers == []
        assert [(r.destination, r.interface) for r in tree.static_routes] == [
            ("0.0.0.0/0", "port1"),
        ]

    def test_a_route_block_before_the_interface_is_left_out_too(self) -> None:
        tree = _tree(_text(_ROUTES, _INTERFACES))
        assert [r.interface for r in tree.static_routes] == ["port1"]

    def test_vrf_0_is_the_global_table(self) -> None:
        text = _text([
            "config system interface",
            '    edit "port3"',
            "        set ip 198.51.100.1 255.255.255.0",
            "        set vrf 0",
            "    next",
            "end",
        ], _POOL, _ROUTES[:6], ["end"])
        tree = _tree(text)
        assert [a.ip for a in tree.interfaces[0].ipv4_addresses] == ["198.51.100.1"]
        assert [p.interface for p in tree.dhcp_servers] == ["port3"]
        assert [r.interface for r in tree.static_routes] == ["port3"]
        assert tree.dropped_tier3_sections == []


class TestTheRows:
    def test_a_row_for_each_thing_left_out(self) -> None:
        rows = _tree(_WITH_THE_FORMS).dropped_tier3_sections
        assert not [row for row in rows if is_left_out_row(row)]
        assert [row.split(":", 1)[0] for row in rows] == [
            "router static", "router static6",
            "config system dhcp server edit 1",
            "config system interface edit port3, VL_50, port4",
        ]
        assert rows[0].startswith("router static: 2 route(s) of a VRF other than 0")
        assert rows[1].startswith("router static6: 1 route(s) of a VRF other than 0")
        assert "a pool on an interface in a VRF other than 0" in rows[2]
        assert "its addresses, DHCP client and VRRP groups are not translated" in rows[3]

    def test_no_row_where_no_interface_is_in_a_vrf(self) -> None:
        assert _tree(_WITHOUT_THEM).dropped_tier3_sections == []

    def test_a_row_names_no_value(self) -> None:
        """A row names the interfaces and pools; it quotes no address,
        no VRF id and no description of them."""
        rows = _tree(_WITH_THE_FORMS).dropped_tier3_sections
        for value in ("198.51", "203.0.113", "2001:db8", "10.5", "red side", "vrf 5"):
            assert not [row for row in rows if value in row], value

    def test_the_row_is_bounded(self) -> None:
        many = ["config system interface"]
        for n in range(60):
            many += [f'    edit "port{n + 10}"', f"        set ip 10.9.{n}.1 255.255.255.0",
                     "        set vrf 3", "    next"]
        rows = _tree(_text([*many, "end"])).dropped_tier3_sections
        assert len(rows) == 1
        assert "port69" not in rows[0]
        assert "more" in rows[0]

    def test_every_job_says_them(self) -> None:
        job = run_plan_with_checked_names(
            get_codec("fortigate_cli"), get_codec("juniper_junos"), _WITH_THE_FORMS, {},
        )
        assert len([row for row in job.dropped_tier3_sections if "VRF other than 0" in row]) == 4
