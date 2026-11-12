"""A Junos static route the tree has no form for is left out and said.

The parser read a static route of one form, ``<dest> next-hop <gw>``,
and passed over every other line of a route.  Three forms are a route
in force that the tree cannot hold (Juniper, "static (Routing
Options)"):

* ``next-table <table>`` -- "Name of the next routing table to the
  destination": the next hop is looked up in another table, and a
  canonical route has one VRF;
* ``discard`` and ``reject`` -- "Do not forward packets addressed to
  this destination", ``reject`` with an ICMP unreachable -- and
  ``receive``, which sends the packets to the Routing Engine: a route
  that forwards to no next hop.

Each was missing from every output, in a job that said nothing of it.
Each is left out, as before, and one section row a kind counts them,
in the global table and in a routing instance alike, in both forms the
device prints.  (A ``qualified-next-hop`` was left out here too, as a
next hop with a preference of its own; it is read now, with the
route's preference, and the next hops a preference leaves out have
rows of their own: ``test_a_routes_preference.py``.)
"""

from __future__ import annotations

import functools

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.codecs._helpers import next_hop_elsewhere_rows
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

_HEAD = (
    "set system host-name r1\n"
    "set interfaces ge-0/0/0 unit 0 family inet address 192.0.2.2/24\n"
    "set interfaces ge-0/0/1 unit 0 family inet address 198.51.100.2/24\n"
    "set routing-instances RED instance-type virtual-router\n"
    "set routing-instances RED interface ge-0/0/1.0\n"
)

_TABLE_ROW = next_hop_elsewhere_rows("routing-options static", 1, "next-table <table>")[0]


def _no_next_hop_row(count: int) -> str:
    return (
        f"routing-options static: {count} discard, reject or receive "
        "route(s): the tree has no form for a route that forwards to no "
        "next hop; not translated"
    )


def _preference_row(count: int) -> str:
    return (
        f"routing-options static: {count} next hop(s) at a preference "
        "the tree does not hold (preference 0, or 255 and above): the "
        "tree holds a distance of 1 to 254; not translated"
    )


def _read(*lines: str):
    """(vrf, destination, gateway) of each route the parser keeps, and
    its rows."""
    tree = get_codec("juniper_junos").parse(_HEAD + "".join(f"{line}\n" for line in lines))
    routes = sorted((r.vrf, r.destination, r.gateway) for r in tree.static_routes)
    return routes, tree.dropped_tier3_sections


_GLOBAL = "set routing-options static route 10.9.0.0/16"
_IN_RED = "set routing-instances RED routing-options static route 10.9.0.0/16"

#: (line, its row), each in the global table and in RED.
_NOT_HELD = [
    (f"{where} {form}", row)
    for where in (_GLOBAL, _IN_RED)
    for form, row in (
        ("next-table RED.inet.0", _TABLE_ROW),
        ("next-table inet.0", _TABLE_ROW),
        ("discard", _no_next_hop_row(1)),
        ("reject", _no_next_hop_row(1)),
        ("receive", _no_next_hop_row(1)),
    )
]


class TestTheParse:
    @pytest.mark.parametrize(("line", "row"), _NOT_HELD)
    def test_it_is_left_out_and_counted(self, line: str, row: str) -> None:
        routes, rows = _read(line)
        assert routes == []
        assert rows == [row]

    def test_a_next_hop_is_read_beside_them(self) -> None:
        routes, rows = _read(
            f"{_GLOBAL} next-hop 192.0.2.1",
            f"{_IN_RED} next-hop 198.51.100.1",
            "set routing-options static route 10.8.0.0/16 discard",
        )
        assert routes == [
            ("", "10.9.0.0/16", "192.0.2.1"), ("RED", "10.9.0.0/16", "198.51.100.1"),
        ]
        assert rows == [_no_next_hop_row(1)]

    def test_each_route_is_counted_once(self) -> None:
        """A route of each kind is counted once by VRF and destination:
        a route of RED and one of the global table with the same
        destination are two."""
        _, rows = _read(
            "set routing-options static route 10.1.0.0/16 discard",
            "set routing-options static route 10.1.0.0/16 discard",
            "set routing-options static route 10.2.0.0/16 reject",
            "set routing-options static route 10.3.0.0/16 receive",
            "set routing-options static route 10.1.0.0/16 next-table RED.inet.0",
            "set routing-instances RED routing-options static route 0.0.0.0/0 next-table inet.0",
        )
        assert rows == [
            next_hop_elsewhere_rows("routing-options static", 2, "next-table <table>")[0],
            _no_next_hop_row(3),
        ]

    def test_the_block_form_says_the_same(self) -> None:
        text = (
            "system {\n    host-name r1;\n}\n"
            "routing-options {\n    static {\n"
            "        route 10.1.0.0/16 discard;\n"
            "        route 10.2.0.0/16 next-table RED.inet.0;\n"
            "        route 10.3.0.0/16 {\n"
            "            next-hop 192.0.2.1;\n"
            "            qualified-next-hop 192.0.2.9 {\n"
            "                preference 7;\n"
            "            }\n"
            "        }\n"
            "    }\n}\n"
        )
        tree = get_codec("juniper_junos").parse(text)
        # The qualified next hop is read at its own preference, and the
        # route's own next hop at Junos's default for a static route.
        assert [(r.destination, r.gateway, r.metric) for r in tree.static_routes] == [
            ("10.3.0.0/16", "192.0.2.1", 5), ("10.3.0.0/16", "192.0.2.9", 7),
        ]
        assert tree.dropped_tier3_sections == [_TABLE_ROW, _no_next_hop_row(1)]

    def test_a_deactivated_one_is_not_counted_twice(self) -> None:
        """A route the device holds and does not run is left out by its
        own row, and is no route of a kind counted here."""
        _, rows = _read(
            "set routing-options static route 10.1.0.0/16 discard",
            "deactivate routing-options static route 10.1.0.0/16",
        )
        assert len(rows) == 1
        assert is_left_out_row(rows[0])

    def test_the_rows_are_sections(self) -> None:
        """Each route is in force on the device: its row is not one of
        a statement left out."""
        for row in (_TABLE_ROW, _no_next_hop_row(2), _preference_row(2)):
            assert not is_left_out_row(row)


@functools.cache
def _job(target: str) -> MigrationJob:
    text = _HEAD + "".join(f"{line}\n" for line in (
        "set routing-options static route 0.0.0.0/0 next-hop 192.0.2.1",
        "set routing-options static route 203.0.113.0/24 next-table RED.inet.0",
        "set routing-options static route 203.0.113.64/26 discard",
        "set routing-options static route 203.0.113.128/26 next-hop 192.0.2.9",
        "set routing-options static route 203.0.113.128/26 preference 0",
        "set routing-instances RED routing-options static route 203.0.113.192/26 reject",
    ))
    job = run_plan_with_checked_names(
        get_codec("juniper_junos"), get_codec(target), text, port_rename_map={},
    )
    assert job.rendered, f"juniper_junos -> {target}: {job.error}"
    return job


class TestTheOutput:
    @pytest.mark.parametrize("target", PUBLIC)
    def test_no_output_has_them_and_the_job_says_so(self, target: str) -> None:
        job = _job(target)
        assert "203.0.113." not in job.rendered, target
        assert job.dropped_tier3_sections[-3:] == [
            _TABLE_ROW, _no_next_hop_row(2), _preference_row(1),
        ], target

    def test_the_route_with_a_next_hop_is_written(self) -> None:
        assert "0.0.0.0/0 next-hop 192.0.2.1" in _job("juniper_junos").rendered
