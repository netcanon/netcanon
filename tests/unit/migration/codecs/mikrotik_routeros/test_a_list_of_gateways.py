"""A RouterOS route with a list of gateways is a route for each gateway.

``gateway=192.0.2.21,192.0.2.22`` is ECMP on RouterOS.  Up to 0.7.7 it
was one route whose next hop was the list as written: onto another
vendor a next hop that no target reads, in a job that said
``completed``.  The tree holds ECMP as several routes to one
destination at one distance -- how every target writes it, and how
RouterOS 7 prints it ("Multiple equally preferred routes are grouped
together automatically and are used for ECMP", MikroTik, How Packets
Are Routed:
https://help.mikrotik.com/docs/pages/viewpage.action?pageId=30146592)
-- so the parser makes a route a gateway, and between two RouterOS 6
configs, where a list is the form of ECMP, the renderer writes them as
one list again.

Every output is read as TEXT, for a line that holds two of the list's
addresses: a reader of a target's output could read a list as two
next hops, and pass the defect it is meant to find.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.codecs.mikrotik_routeros import parse as ros_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

_V7 = "# 2026-01-01 00:00:00 by RouterOS 7.18.2\n"
_V6 = "# jan/01/2026 00:00:00 by RouterOS 6.49.10\n"
_GATEWAYS = ("192.0.2.21", "192.0.2.22", "192.0.2.23")
_LIST = "add dst-address=10.220.0.0/16 gateway=192.0.2.21,192.0.2.22,192.0.2.23 distance=5"
_ADDRESS = re.compile(r"(?<![\d.])192\.0\.2\.2[123](?!\d)")


def _text(head: str, routes: list[str]) -> str:
    return (
        head
        + "/ip address\n"
        + "add address=192.0.2.1/24 interface=ether1\n"
        + "/ip route\n"
        + "".join(line + "\n" for line in routes)
    )


def _routes(text: str) -> list[tuple[str, str, str, int | None]]:
    tree = get_codec("mikrotik_routeros").parse(text)
    return [(r.destination, r.gateway, r.interface, r.metric) for r in tree.static_routes]


def _route_lines(text: str) -> list[str]:
    """The ``add`` lines of routes (a ``comment=`` is written first)."""
    return [line for line in text.splitlines() if line.startswith("add ") and " dst-address=" in f" {line[4:]}"]


def _lines_with_two(text: str) -> list[str]:
    """The lines of an output that hold two of the list's gateways."""
    return [line for line in text.splitlines() if len(set(_ADDRESS.findall(line))) >= 2]


def _ros_to_ros(text: str) -> str:
    ros = get_codec("mikrotik_routeros")
    return ros.render(ros.parse(text))


class TestTheTree:
    def test_a_list_is_a_route_a_gateway(self) -> None:
        assert _routes(_text(_V7, [_LIST])) == [
            ("10.220.0.0/16", gateway, "", 5) for gateway in _GATEWAYS
        ]

    def test_so_it_is_from_routeros_6(self) -> None:
        assert _routes(_text(_V6, [_LIST])) == _routes(_text(_V7, [_LIST]))

    def test_a_gateway_pinned_to_an_interface_is_one_gateway_of_the_list(self) -> None:
        routes = _routes(_text(_V7, [
            "add dst-address=10.221.0.0/16 gateway=192.0.2.21%ether1,192.0.2.22",
        ]))
        assert [(gateway, interface) for _, gateway, interface, _ in routes] == [
            ("192.0.2.21", "ether1"), ("192.0.2.22", ""),
        ]


class TestOntoRouterOS:
    def test_routeros_7_writes_a_route_a_line(self) -> None:
        assert _route_lines(_ros_to_ros(_text(_V7, [_LIST]))) == [
            f"add dst-address=10.220.0.0/16 gateway={gateway} distance=5"
            for gateway in _GATEWAYS
        ]

    def test_routeros_6_writes_the_list_again(self) -> None:
        assert _route_lines(_ros_to_ros(_text(_V6, [_LIST]))) == [_LIST]

    def test_routeros_6_joins_only_one_destination_distance_and_comment(self) -> None:
        text = _text(_V6, [
            "add dst-address=10.222.0.0/16 gateway=192.0.2.21",
            "add dst-address=10.223.0.0/16 gateway=192.0.2.22",
            "add dst-address=10.222.0.0/16 gateway=192.0.2.22 distance=7",
            'add dst-address=10.222.0.0/16 gateway=192.0.2.23 comment="backup"',
            "add dst-address=10.222.0.0/16 gateway=192.0.2.23",
        ])
        assert _route_lines(_ros_to_ros(text)) == [
            "add dst-address=10.222.0.0/16 gateway=192.0.2.21,192.0.2.23",
            "add dst-address=10.223.0.0/16 gateway=192.0.2.22",
            "add dst-address=10.222.0.0/16 gateway=192.0.2.22 distance=7",
            'add comment="backup" dst-address=10.222.0.0/16 gateway=192.0.2.23',
        ]

    def test_routeros_6_joins_no_route_of_a_vrf_and_no_gateway_with_a_comma(self) -> None:
        """Neither comes from a RouterOS parse -- a route of another
        table is left out, and a list is split -- so the tree is made
        by hand: a route of a VRF is written under its review line, and
        a gateway that holds a ``,`` would be read back as more
        gateways."""
        ros = get_codec("mikrotik_routeros")
        tree = ros.parse(_text(_V6, [
            "add dst-address=10.224.0.0/16 gateway=192.0.2.21",
            "add dst-address=10.224.0.0/16 gateway=192.0.2.22",
            "add dst-address=10.224.0.0/16 gateway=192.0.2.23",
        ]))
        tree.static_routes[1].vrf = "blue"
        tree.static_routes[2].gateway = "192.0.2.23,192.0.2.24"
        lines = _route_lines(ros.render(tree))
        assert "add dst-address=10.224.0.0/16 gateway=192.0.2.21" in lines
        assert not any("192.0.2.22" in line for line in lines)
        assert not any("192.0.2.21," in line for line in lines)

    def test_another_vendors_routes_are_written_apart(self) -> None:
        text = (
            "hostname R\n"
            "ip route 10.225.0.0 255.255.0.0 192.0.2.21\n"
            "ip route 10.225.0.0 255.255.0.0 192.0.2.22\n"
        )
        job = run_plan_with_checked_names(
            get_codec("cisco_iosxe_cli"), get_codec("mikrotik_routeros"), text,
            port_rename_map={},
        )
        assert _route_lines(job.rendered) == [
            "add dst-address=10.225.0.0/16 gateway=192.0.2.21",
            "add dst-address=10.225.0.0/16 gateway=192.0.2.22",
        ]


class TestOntoEveryTarget:
    @pytest.mark.parametrize("target", list_public_codecs())
    @pytest.mark.parametrize("head", [_V7, _V6], ids=["routeros_7", "routeros_6"])
    def test_each_gateway_is_written_and_no_line_holds_two(self, target: str, head: str) -> None:
        job = run_plan_with_checked_names(
            get_codec("mikrotik_routeros"), get_codec(target), _text(head, [_LIST]),
            port_rename_map={},
        )
        assert job.rendered is not None, job.error
        written = set(_ADDRESS.findall(job.rendered))
        if "/routing/static-route" in {p.path for p in job.validation.unsupported_paths}:
            # The target writes no static route, and its matrix says so.
            assert written == set(), target
            return
        assert written == set(_GATEWAYS), (target, sorted(written))
        if target == "mikrotik_routeros" and head == _V6:
            assert _lines_with_two(job.rendered) == [_LIST]
        else:
            assert _lines_with_two(job.rendered) == [], target

    def test_the_check_finds_a_list_kept_as_one_route(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With the parser keeping the list as one gateway, as it did up
        to 0.7.7, the check finds the line on a target that writes the
        next hop as the tree holds it."""
        monkeypatch.setattr(ros_parse, "_gateways", lambda raw: [raw] if raw else [""])
        job = run_plan_with_checked_names(
            get_codec("mikrotik_routeros"), get_codec("cisco_iosxe_cli"), _text(_V7, [_LIST]),
            port_rename_map={},
        )
        assert _lines_with_two(job.rendered) != []

    def test_the_reader_of_text(self) -> None:
        assert _lines_with_two("ip route 10.0.0.0/8 192.0.2.21,192.0.2.22") != []
        assert _lines_with_two("ip route 10.0.0.0/8 192.0.2.21\nip route 10.0.0.0/8 192.0.2.22") == []
        assert _lines_with_two("192.0.2.210 192.0.2.21") == []
