"""An AOS-CX route of ``nullroute`` or ``reject`` is left out and said, never a route out an interface.

HPE documents two words where a route's next hop goes that are no next
hop: ``nullroute`` ("packets are silently discarded and no ICMP error
notification is sent to the sender") and ``reject`` (the packets are
discarded "and an ICMP error notification is sent to the sender"), as in
``ip route 1.2.3.4/32 nullroute vrf myvrf`` (AOS-CX IP Routing Guide,
``ip route`` / ``ipv6 route``,
https://arubanetworking.hpe.com/techdocs/AOS-CX/10.17/HTML/ip_route_6300-6400-8100-83xx-93xx-100xx/Content/Chp_StatRoute/StatRoute_cmds/ipv-rou.htm).
The tree has no form for a route that discards.  Up to 0.7.7 the parser
read the word as the route's interface, and the route was written onto
IOS-XE and EOS as a route out an interface called ``nullroute``, in a job
that said ``completed``; so was a keyword of the rest of the line where
the next hop goes (``ip route 10.8.0.0/16 distance 5``), and a route line
neither pattern reads was dropped with nothing said.

Read here: each form, left out, with one row a kind that names no
destination, VRF or line; the routes beside them read as before; and
every public codec's output read as TEXT, by a reader of this module's
own, for the destinations left out and for the two words.
"""

from __future__ import annotations

import functools
import re

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

_HEAD = [
    "hostname sw1",
    "vrf blue",
    "interface 1/1/1",
    "    no shutdown",
    "    ip address 192.0.2.2/24",
    "    ipv6 address 2001:db8:1::2/64",
]

#: Routes that discard, each with what the line says beside the word.
_DISCARD = [
    "ip route 10.4.0.0/16 nullroute",
    "ip route 10.5.0.0/16 reject",
    "ip route 10.6.0.0/16 nullroute distance 9",
    "ip route 10.7.0.0/16 reject vrf blue",
    "ipv6 route 2001:db8:4::/48 nullroute",
    "ipv6 route 2001:db8:5::/48 reject distance 3",
    # A second line of a route already counted counts no more.
    "ip route 10.4.0.0/16 nullroute",
]
#: A keyword where the next hop goes: the line states none.
_NO_NEXT_HOP = [
    "ip route 10.8.0.0/16 distance 5",
    "ipv6 route 2001:db8:8::/48 tag 7",
]
#: Lines that begin as a route does and that neither pattern reads.
_UNREAD = [
    "ip route 10.9.0.0 255.255.0.0 192.0.2.1",
]
#: Routes the tree holds, beside them.
_HELD = [
    "ip route 10.11.0.0/16 192.0.2.1",
    "ip route 10.12.0.0/16 192.0.2.1 distance 4 vrf blue",
    "ipv6 route 2001:db8:11::/48 2001:db8:1::1",
]

#: What each left-out line is about, as the output would spell it.
_LEFT_OUT = [
    "10.4.0.0", "10.5.0.0", "10.6.0.0", "10.7.0.0", "2001:db8:4::", "2001:db8:5::",
    "10.8.0.0", "2001:db8:8::", "10.9.0.0",
]


def _text(lines: list[str]) -> str:
    return "\n".join([*_HEAD, *lines, ""])


_ALL = _text([*_DISCARD, *_NO_NEXT_HOP, *_UNREAD, *_HELD])


def _rows(text: str) -> list[str]:
    return [r for r in get_codec("aruba_aoscx").parse(text).dropped_tier3_sections if r.startswith("ip route:")]


@functools.cache
def _job(target: str, text: str) -> MigrationJob:
    return run_plan_with_checked_names(get_codec("aruba_aoscx"), get_codec(target), text, {})


def _left_out_in(output: str) -> list[str]:
    """What of the left-out routes an output spells: a destination, or
    one of the two words as a word of a line.  Read from the text, not
    by any parser."""
    found = [d for d in _LEFT_OUT if d in output]
    found += sorted(set(re.findall(r"\b(nullroute|reject)\b", output, re.IGNORECASE)))
    return found


class TestTheParser:
    def test_the_routes_beside_them_are_read(self) -> None:
        tree = get_codec("aruba_aoscx").parse(_ALL)
        assert [(r.destination, r.gateway, r.interface, r.metric, r.vrf) for r in tree.static_routes] == [
            ("10.11.0.0/16", "192.0.2.1", "", 0, ""),
            ("10.12.0.0/16", "192.0.2.1", "", 4, "blue"),
            ("2001:db8:11::/48", "2001:db8:1::1", "", 0, ""),
        ]

    def test_no_route_is_made_of_a_word(self) -> None:
        tree = get_codec("aruba_aoscx").parse(_ALL)
        assert sorted(r.destination for r in tree.static_routes) == [
            "10.11.0.0/16", "10.12.0.0/16", "2001:db8:11::/48",
        ]
        assert not [r for r in tree.static_routes if r.interface]

    def test_one_row_a_kind_counts_them(self) -> None:
        assert _rows(_ALL) == [
            "ip route: 6 route(s) that discard (nullroute, reject): the tree has no form for a route "
            "that discards; not translated",
            "ip route: 2 route(s) that state no next hop (a keyword where the next hop goes); "
            "not translated",
            "ip route: 1 route line(s) not read; not translated",
        ]

    def test_a_row_names_no_destination_vrf_or_line(self) -> None:
        for row in _rows(_ALL):
            assert not [d for d in [*_LEFT_OUT, "blue", "10.", "2001:"] if d in row], row

    def test_each_row_is_a_section_not_a_statement_left_out(self) -> None:
        """Each route is in force on the switch."""
        rows = _rows(_ALL)
        assert rows
        assert not [r for r in rows if is_left_out_row(r)]

    def test_a_route_map_is_no_route(self) -> None:
        assert _rows(_text(["ip route-map x", *_HELD])) == []

    @pytest.mark.parametrize("line", [*_DISCARD[:6], *_NO_NEXT_HOP, *_UNREAD])
    def test_each_line_alone_is_left_out(self, line: str) -> None:
        tree = get_codec("aruba_aoscx").parse(_text([line]))
        assert not tree.static_routes
        assert len(_rows(_text([line]))) == 1


class TestOntoEveryTarget:
    @pytest.mark.parametrize("target", PUBLIC)
    def test_no_output_spells_a_route_left_out(self, target: str) -> None:
        job = _job(target, _ALL)
        assert _left_out_in(job.rendered or "") == [], target

    @pytest.mark.parametrize("target", PUBLIC)
    def test_the_rows_reach_the_job(self, target: str) -> None:
        rows = [r for r in _job(target, _ALL).dropped_tier3_sections if r.startswith("ip route:")]
        assert rows == _rows(_ALL), target


class TestTheChecksCanFail:
    """The reader is handed the outputs the parser made up to 0.7.7."""

    def test_the_reader_sees_a_route_out_nullroute(self) -> None:
        assert _left_out_in("ip route 10.4.0.0 255.255.0.0 nullroute\n") == ["10.4.0.0", "nullroute"]

    def test_the_reader_sees_a_route_out_reject_on_eos(self) -> None:
        assert _left_out_in("ipv6 route 2001:db8:5::/48 reject 3\n") == ["2001:db8:5::", "reject"]

    def test_the_reader_sees_a_route_out_distance(self) -> None:
        assert _left_out_in("ip route 10.8.0.0/16 distance 5\n") == ["10.8.0.0"]
