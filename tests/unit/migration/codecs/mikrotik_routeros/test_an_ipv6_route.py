"""An IPv6 route of a RouterOS config is in ``/ipv6 route``, both ways.

"To add or remove routes /ip(ipv6) route menus should be used", ``/ip
route`` listing the IPv4 routes and ``/ipv6 route`` the IPv6 ones
(MikroTik, IP Routing:
https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing).  Up
to 0.7.7 the parser read no ``/ipv6 route`` section, so every IPv6 route
of a RouterOS config was lost on every target, RouterOS included, in
jobs that said ``completed`` and nothing more; and the renderer wrote
every route, the IPv6 ones included, as an ``add`` of ``/ip route``.

Read here: a RouterOS ``/ipv6 route`` onto every public codec, the
output read with the target's own parser; the forms ``/ipv6 route``
shares with ``/ip route`` (a route of another table, a disabled route, a
route that discards), left out and said alike; and an IPv6 route of
another vendor onto RouterOS, the output read as text by the section
each ``add`` is in -- a reader of this module's own, not the parser.
"""

from __future__ import annotations

import functools

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

_HEAD = [
    "# 2026-01-01 00:00:00 by RouterOS 7.18.2",
    "/interface ethernet",
    "set [ find default-name=ether1 ] name=ether1",
    "/ip address",
    "add address=192.0.2.1/24 interface=ether1",
    "/ipv6 address",
    "add address=2001:db8:1::1/64 interface=ether1",
    "/ip route",
    "add dst-address=10.10.0.0/16 gateway=192.0.2.254",
    "/ipv6 route",
]

#: Routes of ``/ipv6 route`` the tree holds.
_KEPT = [
    "add dst-address=2001:db8:10::/48 gateway=2001:db8:1::fe",
    'add comment="uplink" distance=5 dst-address=::/0 gateway=fe80::1%ether1',
]

#: Routes of ``/ipv6 route`` no output has: of another table, held
#: disabled, discarding.
_LEFT_OUT = [
    "add dst-address=2001:db8:40::/48 gateway=2001:db8:1::fc routing-table=blue",
    "add disabled=yes dst-address=2001:db8:30::/48 gateway=2001:db8:1::fd",
    "add blackhole dst-address=2001:db8:50::/48",
]


def _text(routes: list[str]) -> str:
    return "\n".join([*_HEAD, *routes, ""])


@functools.cache
def _job(source: str, target: str, text: str) -> MigrationJob:
    return run_plan_with_checked_names(get_codec(source), get_codec(target), text, {})


def _read_back(target: str, rendered: str) -> set[str]:
    """The destinations of the routes the target's parser reads."""
    return {r.destination for r in get_codec(target).parse(rendered).static_routes}


class TestTheParser:
    def test_an_ipv6_route_is_read(self) -> None:
        routes = get_codec("mikrotik_routeros").parse(_text(_KEPT)).static_routes
        assert [
            (r.destination, r.gateway, r.interface, r.metric, r.description) for r in routes
        ] == [
            ("10.10.0.0/16", "192.0.2.254", "", 0, ""),
            ("2001:db8:10::/48", "2001:db8:1::fe", "", 0, ""),
            ("::/0", "fe80::1", "ether1", 5, "uplink"),
        ]

    def test_what_is_left_out_is_said_as_in_ip_route(self) -> None:
        tree = get_codec("mikrotik_routeros").parse(_text(_LEFT_OUT))
        assert [r.destination for r in tree.static_routes] == ["10.10.0.0/16"]
        rows = [row for row in tree.dropped_tier3_sections if "route" in row]
        assert [row for row in rows if is_left_out_row(row)] == [
            "disabled: ipv6 route 2001:db8:30::/48 (a route the source holds disabled, "
            "so it installs nothing; not translated)",
        ]
        others = [row for row in rows if not is_left_out_row(row)]
        assert [row.split(":", 1)[0] for row in others] == ["/ipv6 route", "/ipv6 route"]
        assert "1 route(s) in a routing table other than main" in others[0]
        assert "1 blackhole, unreachable or prohibit" in others[1]

    def test_each_section_counts_its_own(self) -> None:
        text = "\n".join([
            "# 2026-01-01 00:00:00 by RouterOS 7.18.2",
            "/ip route",
            "add dst-address=10.20.0.0/16 gateway=192.0.2.9 routing-table=blue",
            "add dst-address=10.21.0.0/16 gateway=192.0.2.9 routing-table=blue",
            "/ipv6 route",
            "add dst-address=2001:db8:40::/48 gateway=2001:db8:1::fc routing-table=blue",
            "",
        ])
        rows = get_codec("mikrotik_routeros").parse(text).dropped_tier3_sections
        assert [row.split(" route(s)", 1)[0] for row in rows] == ["/ip route: 2", "/ipv6 route: 1"]


#: The targets whose output holds no static route at all (each job
#: says so: it is not ``completed``).
_NO_ROUTE_AT_ALL = {"cisco_iosxe", "opnsense"}


class TestOntoEveryTarget:
    @pytest.mark.parametrize("target", PUBLIC)
    def test_the_route_reaches_the_output(self, target: str) -> None:
        job = _job("mikrotik_routeros", target, _text(_KEPT))
        back = _read_back(target, job.rendered or "")
        if target in _NO_ROUTE_AT_ALL:
            assert job.status != MigrationJobStatus.completed
            assert not back
        else:
            assert {"2001:db8:10::/48", "::/0"} <= back, target

    @pytest.mark.parametrize("target", PUBLIC)
    def test_a_route_left_out_reaches_no_output_and_is_said(self, target: str) -> None:
        job = _job("mikrotik_routeros", target, _text(_LEFT_OUT))
        assert not _read_back(target, job.rendered or "") & {
            "2001:db8:30::/48", "2001:db8:40::/48", "2001:db8:50::/48",
        }
        rows = [row for row in job.dropped_tier3_sections if "ipv6 route" in row]
        assert len(rows) == 3, target


_IOSXE = """hostname r1
!
interface GigabitEthernet1
 ip address 192.0.2.1 255.255.255.0
 ipv6 address 2001:db8:1::1/64
!
ip route 10.10.0.0 255.255.0.0 192.0.2.254
ipv6 route 2001:db8:10::/48 2001:db8:1::fe
ip route 10.30.0.0 255.255.0.0 192.0.2.253
ipv6 route ::/0 2001:db8:1::fd
!
end
"""


def _adds_by_section(rendered: str) -> list[tuple[str, str]]:
    """(section, destination) of each ``add`` with a ``dst-address=``,
    the section being the last line that begins with ``/``."""
    section, adds = "", []
    for line in rendered.splitlines():
        if line.startswith("/"):
            section = line.strip()
        elif line.startswith("add ") and " dst-address=" in f" {line[4:]}":
            value = f" {line[4:]}".split(" dst-address=", 1)[1].split()[0].strip('"')
            adds.append((section, value))
    return adds


def _misplaced(rendered: str) -> list[tuple[str, str]]:
    """The routes written in the section of the other family."""
    return [
        (section, dest) for section, dest in _adds_by_section(rendered)
        if section != ("/ipv6 route" if ":" in dest else "/ip route")
    ]


class TestOntoRouterOS:
    def test_each_route_is_in_the_section_of_its_family(self) -> None:
        rendered = _job("cisco_iosxe_cli", "mikrotik_routeros", _IOSXE).rendered or ""
        assert sorted(_adds_by_section(rendered)) == [
            ("/ip route", "10.10.0.0/16"),
            ("/ip route", "10.30.0.0/16"),
            ("/ipv6 route", "2001:db8:10::/48"),
            ("/ipv6 route", "::/0"),
        ]

    def test_and_is_read_back(self) -> None:
        rendered = _job("cisco_iosxe_cli", "mikrotik_routeros", _IOSXE).rendered or ""
        assert _read_back("mikrotik_routeros", rendered) == {
            "10.10.0.0/16", "10.30.0.0/16", "2001:db8:10::/48", "::/0",
        }

    def test_a_routeros_config_round_trips(self) -> None:
        text = _text(_KEPT)
        rendered = _job("mikrotik_routeros", "mikrotik_routeros", text).rendered or ""
        assert not _misplaced(rendered)
        assert _read_back("mikrotik_routeros", rendered) == _read_back("mikrotik_routeros", text)


class TestTheChecksCanFail:
    """Each check is handed an output with the defect it is for."""

    _AS_IT_WAS = (
        "/ip route\n"
        "add dst-address=10.10.0.0/16 gateway=192.0.2.254\n"
        "add dst-address=2001:db8:10::/48 gateway=2001:db8:1::fe\n"
    )

    def test_the_section_reader_sees_an_ipv6_route_in_ip_route(self) -> None:
        assert _misplaced(self._AS_IT_WAS) == [("/ip route", "2001:db8:10::/48")]

    def test_the_section_reader_reads_a_quoted_destination(self) -> None:
        assert _adds_by_section('/ipv6 route\nadd comment="a b" dst-address="::/0"\n') == [
            ("/ipv6 route", "::/0"),
        ]
