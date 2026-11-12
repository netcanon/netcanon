"""A Junos IPv6 static route is a route of ``rib inet6.0``, both ways.

Juniper's examples put an IPv6 static route under ``rib inet6.0``: "set
routing-options rib inet6.0 static route ::/0 next-hop ..." (Example:
Configuring IPv6 Static Routes,
https://www.juniper.net/documentation/en_US/junos12.3/topics/example/policy-ipv6-static-routes.html),
and "In a routing instance, the routing table name must include the
routing instance name" (rib (Routing Options),
https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/ref/statement/rib-edit-routing-options.html):
``<instance>.inet6.0``.  Up to 0.7.7 the parser read no ``rib`` line, so
such a route was lost on every target, Junos included, with nothing
said; and the renderer wrote an IPv6 route under ``routing-options
static``, as an IPv4 route is.

Read here: each form the parser reads, block form among them; a route
of another table, left out and counted; a Junos IPv6 route onto every
public codec, the output read with the target's own parser; and the
Junos output read as text by the table each route is in -- a reader of
this module's own, not the parser.
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
    "set system host-name r1",
    "set interfaces ge-0/0/0 unit 0 family inet address 192.0.2.1/24",
    "set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8:1::1/64",
    "set interfaces ge-0/0/1 unit 0 family inet address 198.51.100.1/24",
    "set interfaces ge-0/0/1 unit 0 family inet6 address 2001:db8:2::1/64",
    "set routing-instances blue instance-type vrf",
    "set routing-instances blue interface ge-0/0/1.0",
]

#: Routes of the main tables, the global ones and those of ``blue``.
_ROUTES = [
    "set routing-options static route 10.10.0.0/16 next-hop 192.0.2.254",
    "set routing-options rib inet.0 static route 10.11.0.0/16 next-hop 192.0.2.253",
    "set routing-options rib inet6.0 static route 2001:db8:10::/48 next-hop 2001:db8:1::fe",
    "set routing-options rib inet6.0 static route ::/0 next-hop 2001:db8:1::fd",
    "set routing-instances blue routing-options static route 10.20.0.0/16 next-hop 198.51.100.254",
    "set routing-instances blue routing-options rib blue.inet6.0 static route 2001:db8:20::/48 "
    "next-hop 2001:db8:2::fe",
]

_READ = [
    ("10.10.0.0/16", "192.0.2.254", ""),
    ("10.11.0.0/16", "192.0.2.253", ""),
    ("2001:db8:10::/48", "2001:db8:1::fe", ""),
    ("::/0", "2001:db8:1::fd", ""),
    ("10.20.0.0/16", "198.51.100.254", "blue"),
    ("2001:db8:20::/48", "2001:db8:2::fe", "blue"),
]

#: Routes of tables that are not the main ones: LSP next hops,
#: multicast RPF, a table of another instance, and ``inet6.0`` named in
#: an instance, which is not the instance's own.
_OTHER_TABLES = [
    "set routing-options rib inet.3 static route 192.0.2.77/32 next-hop 192.0.2.254",
    "set routing-options rib inet6.3 static route 2001:db8:77::/48 next-hop 2001:db8:1::fe",
    "set routing-options rib inet.2 static route 10.77.0.0/16 next-hop 192.0.2.254",
    "set routing-options rib blue.inet6.0 static route 2001:db8:78::/48 next-hop 2001:db8:1::fe",
    "set routing-instances blue routing-options rib inet6.0 static route 2001:db8:79::/48 "
    "next-hop 2001:db8:2::fe",
    "set routing-instances blue routing-options rib blue.inet.3 static route 10.79.0.0/16 "
    "next-hop 198.51.100.254",
    # A second line of a route already counted counts no more.
    "set routing-options rib inet.3 static route 192.0.2.77/32 preference 7",
]


def _text(lines: list[str]) -> str:
    return "\n".join([*_HEAD, *lines, ""])


def _routes(text: str) -> list[tuple[str, str, str]]:
    tree = get_codec("juniper_junos").parse(text)
    return [(r.destination, r.gateway, r.vrf) for r in tree.static_routes]


@functools.cache
def _job(source: str, target: str, text: str) -> MigrationJob:
    return run_plan_with_checked_names(get_codec(source), get_codec(target), text, {})


class TestTheParser:
    def test_each_main_table_is_read(self) -> None:
        assert _routes(_text(_ROUTES)) == _READ

    def test_a_route_alone_makes_no_routing_instance(self) -> None:
        """As a route of ``static`` does not: an instance named by its
        route alone states nothing else."""
        text = "\n".join([
            "set system host-name r1",
            "set routing-instances red routing-options rib red.inet6.0 static route "
            "2001:db8:30::/48 next-hop 2001:db8:3::fe",
            "",
        ])
        tree = get_codec("juniper_junos").parse(text)
        assert [(r.destination, r.vrf) for r in tree.static_routes] == [("2001:db8:30::/48", "red")]
        assert not tree.routing_instances

    def test_the_block_form_is_read(self) -> None:
        text = (
            "system {\n"
            "    host-name r1;\n"
            "}\n"
            "routing-options {\n"
            "    rib inet6.0 {\n"
            "        static {\n"
            "            route ::/0 next-hop 2001:db8:1::fd;\n"
            "        }\n"
            "    }\n"
            "}\n"
            "routing-instances {\n"
            "    blue {\n"
            "        instance-type vrf;\n"
            "        routing-options {\n"
            "            rib blue.inet6.0 {\n"
            "                static {\n"
            "                    route 2001:db8:20::/48 next-hop 2001:db8:2::fe;\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        assert _routes(text) == [
            ("::/0", "2001:db8:1::fd", ""),
            ("2001:db8:20::/48", "2001:db8:2::fe", "blue"),
        ]

    def test_a_route_of_another_table_is_left_out_and_counted(self) -> None:
        tree = get_codec("juniper_junos").parse(_text(_OTHER_TABLES))
        assert not tree.static_routes
        rows = [row for row in tree.dropped_tier3_sections if row.startswith("routing-options rib")]
        assert len(rows) == 1
        assert rows[0].startswith("routing-options rib: 6 static route(s) of a routing table other")
        assert not is_left_out_row(rows[0])
        # The row names neither a table nor a destination.
        assert not any(word in rows[0] for word in ("inet.3", "inet6.3", "blue", "2001:db8", "10.77"))

    def test_a_form_the_tree_has_no_form_for_is_counted_as_under_static(self) -> None:
        tree = get_codec("juniper_junos").parse(_text([
            "set routing-options rib inet6.0 static route 2001:db8:60::/48 discard",
            "set routing-options rib inet6.0 static route ::/0 next-hop 2001:db8:1::fc",
            "set routing-options rib inet6.0 static route ::/0 preference 0",
        ]))
        assert not tree.static_routes
        rows = [row for row in tree.dropped_tier3_sections if row.startswith("routing-options static")]
        assert [row.split(" route(s)", 1)[0].split(" at a", 1)[0] for row in rows] == [
            "routing-options static: 1 discard, reject or receive",
            "routing-options static: 1 next hop(s)",
        ]


def _by_table(rendered: str) -> list[tuple[str, str]]:
    """(table, destination) of each static route of a Junos output, the
    table being the one its line names (``inet.0`` for ``static``,
    ``<instance>.inet.0`` for ``static`` in an instance)."""
    found = []
    for line in rendered.splitlines():
        words = line.split()
        if "static" not in words or "route" not in words:
            continue
        before = words[:words.index("static")]
        dest = words[words.index("route") + 1]
        instance = before[2] if before[1:2] == ["routing-instances"] else ""
        if "rib" in before:
            table = before[before.index("rib") + 1].strip('"')
        else:
            table = f"{instance}.inet.0" if instance else "inet.0"
        found.append((table, dest))
    return found


def _misplaced(rendered: str) -> list[tuple[str, str]]:
    """The routes written into a table of the other family."""
    return [
        (table, dest) for table, dest in _by_table(rendered)
        if table.endswith("inet6.0") != (":" in dest)
    ]


class TestTheRenderer:
    def test_each_route_is_in_the_table_of_its_family(self) -> None:
        rendered = _job("juniper_junos", "juniper_junos", _text(_ROUTES)).rendered or ""
        assert sorted(_by_table(rendered)) == sorted([
            ("inet.0", "10.10.0.0/16"),
            ("inet.0", "10.11.0.0/16"),
            ("inet6.0", "2001:db8:10::/48"),
            ("inet6.0", "::/0"),
            ("blue.inet.0", "10.20.0.0/16"),
            ("blue.inet6.0", "2001:db8:20::/48"),
        ])

    def test_a_junos_config_round_trips(self) -> None:
        text = _text(_ROUTES)
        rendered = _job("juniper_junos", "juniper_junos", text).rendered or ""
        assert sorted(_routes(rendered)) == sorted(_READ)

    def test_another_vendors_ipv6_route_is_written_under_rib_inet6_0(self) -> None:
        text = (
            "hostname r1\n!\n"
            "vrf definition blue\n address-family ipv6\n exit-address-family\n!\n"
            "interface GigabitEthernet1\n ipv6 address 2001:db8:1::1/64\n!\n"
            "ip route 10.10.0.0 255.255.0.0 192.0.2.254\n"
            "ipv6 route 2001:db8:10::/48 2001:db8:1::fe\n"
            "ipv6 route vrf blue 2001:db8:20::/48 2001:db8:2::fe\n"
            "!\nend\n"
        )
        rendered = _job("cisco_iosxe_cli", "juniper_junos", text).rendered or ""
        assert sorted(_by_table(rendered)) == [
            ("blue.inet6.0", "2001:db8:20::/48"),
            ("inet.0", "10.10.0.0/16"),
            ("inet6.0", "2001:db8:10::/48"),
        ]


#: The targets whose output holds no static route at all (each job
#: says so: it is not ``completed``).
_NO_ROUTE_AT_ALL = {"cisco_iosxe", "opnsense"}

_GLOBAL_V6 = [
    "set routing-options rib inet6.0 static route 2001:db8:10::/48 next-hop 2001:db8:1::fe",
    "set routing-options rib inet6.0 static route ::/0 next-hop 2001:db8:1::fd",
]


class TestOntoEveryTarget:
    @pytest.mark.parametrize("target", PUBLIC)
    def test_the_route_reaches_the_output(self, target: str) -> None:
        job = _job("juniper_junos", target, _text(_GLOBAL_V6))
        back = {r.destination for r in get_codec(target).parse(job.rendered or "").static_routes}
        if target in _NO_ROUTE_AT_ALL:
            assert job.status != MigrationJobStatus.completed
            assert not back
        else:
            assert {"2001:db8:10::/48", "::/0"} <= back, target

    @pytest.mark.parametrize("target", PUBLIC)
    def test_a_route_of_another_table_reaches_no_output_and_is_said(self, target: str) -> None:
        job = _job("juniper_junos", target, _text(_OTHER_TABLES))
        back = {r.destination for r in get_codec(target).parse(job.rendered or "").static_routes}
        assert not back, target
        assert [row for row in job.dropped_tier3_sections if row.startswith("routing-options rib")], target


class TestTheChecksCanFail:
    """Each check is handed an output with the defect it is for."""

    _AS_IT_WAS = (
        "set routing-options static route 10.10.0.0/16 next-hop 192.0.2.254\n"
        "set routing-options static route ::/0 next-hop 2001:db8:1::fd\n"
        "set routing-instances blue routing-options static route 2001:db8:20::/48 "
        "next-hop 2001:db8:2::fe\n"
    )

    def test_the_table_reader_sees_an_ipv6_route_in_inet_0(self) -> None:
        assert _misplaced(self._AS_IT_WAS) == [
            ("inet.0", "::/0"),
            ("blue.inet.0", "2001:db8:20::/48"),
        ]

    def test_the_table_reader_sees_an_ipv4_route_in_inet6_0(self) -> None:
        assert _misplaced(
            "set routing-options rib inet6.0 static route 10.10.0.0/16 next-hop 192.0.2.254\n"
        ) == [("inet6.0", "10.10.0.0/16")]
