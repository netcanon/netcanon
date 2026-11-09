"""A RouterOS DHCP pool is served by its ``/ip dhcp-server``.

The renderer wrote a pool's ``/ip pool`` and its network's options and
no ``/ip dhcp-server``: RouterOS's server names the interface it runs on
("mandatory") and the pool it takes addresses from, and with neither the
pool serves nobody; its lease time was not written either.  And the
parser made a pool of every ``/ip dhcp-server network`` entry and of
every ``/ip pool``, whether or not a server used it -- a pool can be
PPP's, a hotspot's or IPsec's -- and read no server's interface or
lease.  See the docstrings of ``mikrotik_routeros/dhcp_pools.py`` and of
``_DHCPServers`` in ``mikrotik_routeros/parse.py``.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.canonical.intent import CanonicalDHCPPool, CanonicalIntent
from netcanon.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netcanon.migration.codecs.mikrotik_routeros.dhcp_pools import as_time
from netcanon.migration.codecs.mikrotik_routeros.parse import seconds_of

pytestmark = pytest.mark.unit

_HEADER = "# 2026-01-01 00:00:00 by RouterOS 7.14"
_POOL = "/ip pool\nadd name=lan ranges=192.0.2.10-192.0.2.200"
_NETWORK = "/ip dhcp-server network\nadd address=192.0.2.0/24 gateway=192.0.2.1 dns-server=192.0.2.1"


def _parsed(*servers: str, header: str = _HEADER, pool: str = _POOL) -> CanonicalIntent:
    """A config of *servers* (``add`` lines of ``/ip dhcp-server``),
    the pool ``lan`` and the network that holds it."""
    lines = [header, pool, "/ip dhcp-server", *servers, _NETWORK]
    return MikroTikRouterOSCodec().parse("\n".join(line for line in lines if line) + "\n")


def _rows(tree: CanonicalIntent) -> list[str]:
    return [row for row in tree.dropped_tier3_sections if "dhcp" in row or "pool" in row]


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------


class TestTheParserReadsTheServer:

    def test_a_server_is_a_pool_on_its_interface_with_its_lease(self) -> None:
        tree = _parsed("add address-pool=lan disabled=no interface=bridge1 lease-time=1d name=dhcp1")
        assert [
            (p.interface, p.network, p.start_ip, p.end_ip, p.gateway, p.dns_servers, p.lease_time)
            for p in tree.dhcp_servers
        ] == [("bridge1", "192.0.2.0/24", "192.0.2.10", "192.0.2.200", "192.0.2.1", ["192.0.2.1"], 86400)]
        assert _rows(tree) == []

    def test_relay_0000_is_a_server_of_its_own_clients(self) -> None:
        # "0.0.0.0 (default) - Only requests from directly connected clients".
        tree = _parsed("add address-pool=lan interface=ether2 name=dhcp1 relay=0.0.0.0")
        assert [p.interface for p in tree.dhcp_servers] == ["ether2"]

    def test_a_quoted_interface_is_read_whole(self) -> None:
        tree = _parsed('add address-pool=lan interface="my port" name=dhcp1')
        assert [p.interface for p in tree.dhcp_servers] == ["my port"]

    @pytest.mark.parametrize(
        ("server", "said"),
        [
            ("add interface=ether2 name=s1", "address-pool=static-only"),
            ("add address-pool=static-only interface=ether2 name=s1", "address-pool=static-only"),
            ("add address-pool=lan interface=ether2 name=s1 relay=10.0.0.1", "relay= a server of the requests"),
            ("add address-pool=elsewhere interface=ether2 name=s1", "address-pool= names no /ip pool"),
        ],
    )
    def test_a_server_that_serves_no_pool_of_its_own_is_said(self, server: str, said: str) -> None:
        tree = _parsed(server)
        assert tree.dhcp_servers == []
        rows = _rows(tree)
        assert rows[0].startswith(f"/ip dhcp-server s1: {said}"), rows
        # The pool and the network it would have served are said too.
        assert [row.split(":")[0] for row in rows[1:]] == ["/ip pool lan", "/ip dhcp-server network 192.0.2.0/24"]

    def test_a_pool_with_no_range_it_reads_is_said(self) -> None:
        tree = _parsed("add address-pool=lan interface=ether2 name=s1", pool="/ip pool\nadd name=lan ranges=192.0.2.9")
        assert tree.dhcp_servers == []
        assert [row.split(":")[0] for row in _rows(tree)] == [
            "/ip dhcp-server s1", "/ip pool lan", "/ip dhcp-server network 192.0.2.0/24",
        ]
        assert "names an /ip pool that states no range this parser reads" in _rows(tree)[0]

    @pytest.mark.parametrize("disabled", ["yes", "true"])
    def test_a_disabled_server_is_left_out_and_said(self, disabled: str) -> None:
        tree = _parsed(f"add address-pool=lan disabled={disabled} interface=ether2 name=s1")
        assert tree.dhcp_servers == []
        left_out = [row for row in tree.dropped_tier3_sections if is_left_out_row(row)]
        assert left_out == [
            "disabled: ip dhcp-server s1 (the source's DHCP server is not enabled, "
            "so it serves nothing; not translated)",
        ]

    def test_next_pool_is_said(self) -> None:
        tree = _parsed(
            "add address-pool=lan interface=ether2 name=s1",
            pool="/ip pool\nadd name=lan next-pool=more ranges=192.0.2.10-192.0.2.20\n"
                 "add name=more ranges=192.0.2.30-192.0.2.40",
        )
        assert [(p.start_ip, p.end_ip) for p in tree.dhcp_servers] == [("192.0.2.10", "192.0.2.20")]
        assert [row.split(":")[0] for row in _rows(tree)] == ["/ip pool lan", "/ip pool more"]
        assert "next-pool=" in _rows(tree)[0]

    def test_a_server_whose_range_no_network_holds_is_said(self) -> None:
        tree = _parsed(
            "add address-pool=lan interface=ether2 name=s1",
            pool="/ip pool\nadd name=lan ranges=198.51.100.10-198.51.100.20",
        )
        assert [(p.interface, p.network, p.start_ip) for p in tree.dhcp_servers] == [
            ("ether2", "", "198.51.100.10"),
        ]
        assert [row.split(":")[0] for row in _rows(tree)] == [
            "/ip dhcp-server s1", "/ip dhcp-server network 192.0.2.0/24",
        ]

    def test_two_servers_of_one_pool_are_two_pools(self) -> None:
        tree = _parsed(
            "add address-pool=lan interface=ether2 name=s1",
            "add address-pool=lan interface=ether3 name=s2",
        )
        assert [(p.interface, p.start_ip) for p in tree.dhcp_servers] == [
            ("ether2", "192.0.2.10"), ("ether3", "192.0.2.10"),
        ]

    def test_a_row_names_a_few_and_counts_the_rest(self) -> None:
        tree = _parsed(*(f"add interface=ether{n} name=s{n}" for n in range(10)))
        assert _rows(tree)[0].startswith("/ip dhcp-server s0, s1, s2 and 7 more: address-pool=static-only")

    def test_a_long_name_is_cut_in_its_row(self) -> None:
        name = "n" * 500
        tree = _parsed(f"add interface=ether2 name={name}")
        row = _rows(tree)[0]
        assert row.startswith("/ip dhcp-server " + "n" * 39 + "…: ")
        assert len(row) < 200


class TestTheLeaseTime:

    @pytest.mark.parametrize(
        ("text", "seconds"),
        [
            ("30m", 1800), ("1d", 86400), ("1d12h", 129600), ("1w", 604800), ("90s", 90),
            ("1w2d3h4m5s", ((9 * 24 + 3) * 60 + 4) * 60 + 5),
            # As RouterOS prints a time.
            ("3d00:00:00", 3 * 86400), ("00:10:00", 600), ("1w2d03:04:05", ((9 * 24 + 3) * 60 + 4) * 60 + 5),
        ],
    )
    def test_each_form_is_read(self, text: str, seconds: int) -> None:
        assert seconds_of(text) == seconds
        tree = _parsed(f"add address-pool=lan interface=ether2 lease-time={text} name=s1")
        assert [p.lease_time for p in tree.dhcp_servers] == [seconds]
        assert _rows(tree) == []

    @pytest.mark.parametrize("text", ["", "forever", "10x", "1d 2h", "3:0:00", "1h1d", "12345678s"])
    def test_a_form_it_does_not_read_is_the_default_and_said(self, text: str) -> None:
        assert seconds_of(text) is None
        tree = _parsed(f'add address-pool=lan interface=ether2 lease-time="{text}" name=s1')
        assert [p.lease_time for p in tree.dhcp_servers] == [1800]
        assert [row for row in _rows(tree) if "lease-time=" in row] == [
            "/ip dhcp-server s1: lease-time= a time in a form this parser does not read; "
            "read as 30m, RouterOS's default",
        ]

    @pytest.mark.parametrize(
        ("header", "said"),
        [(_HEADER, False), ("# jan/02/1970 00:00:00 by RouterOS 6.49.10", True), ("", True)],
    )
    def test_no_lease_time_is_30m_and_said_where_the_release_is_not_7(self, header: str, said: bool) -> None:
        # RouterOS 7's manual: "Default: 30m"; another release's default
        # is not established.
        tree = _parsed("add address-pool=lan interface=ether2 name=s1", header=header)
        assert [p.lease_time for p in tree.dhcp_servers] == [1800]
        rows = [row for row in _rows(tree) if "no lease-time" in row]
        assert bool(rows) is said

    @pytest.mark.parametrize(
        ("seconds", "text"),
        [
            (86400, "1d"), (604800, "7d"), (43200, "12h"), (1800, "30m"), (129600, "1d12h"),
            (90, "1m30s"), (3661, "1h1m1s"), (59, "59s"), (0, "0s"),
        ],
    )
    def test_the_writer_writes_each_unit_it_holds(self, seconds: int, text: str) -> None:
        assert as_time(seconds) == text

    @pytest.mark.parametrize("seconds", [1, 59, 60, 61, 3599, 3600, 7200, 86399, 86400, 90000, 10**7, 0xFFFFFFFE])
    def test_what_the_writer_writes_the_parser_reads(self, seconds: int) -> None:
        assert seconds_of(as_time(seconds)) == seconds


# ---------------------------------------------------------------------------
# The renderer
# ---------------------------------------------------------------------------


def _tree(*pools: CanonicalDHCPPool) -> CanonicalIntent:
    return CanonicalIntent(source_vendor="test", source_format="test", hostname="r1", dhcp_servers=list(pools))


def _pool(interface: str = "ether2", lease_time: int = 86400, **fields: str) -> CanonicalDHCPPool:
    values: dict[str, str] = {
        "network": "192.0.2.0/24", "start_ip": "192.0.2.10", "end_ip": "192.0.2.200", "gateway": "192.0.2.1",
    }
    values.update(fields)
    return CanonicalDHCPPool(interface=interface, lease_time=lease_time, **values)


def _section(text: str, header: str) -> list[str]:
    """The lines of the section *header* opens, the header left out, up
    to the blank line after it or the end of the text."""
    lines = [*text.splitlines(), ""]
    start = lines.index(header) + 1
    return lines[start:lines.index("", start)]


#: A key and its value, as RouterOS writes one: a word, or a string in
#: quotes whose escapes are a backslash and one character.
_KEY_VALUE = re.compile(r'([a-z][a-z-]*)=("(?:\\.|[^"\\])*"|[^ "]*)')


def _key_values(line: str) -> dict[str, str]:
    return {key: value.strip('"') for key, value in _KEY_VALUE.findall(line)}


def _served(text: str) -> list[tuple[str, str, str]]:
    """What the output's servers serve, read from its text by a reader
    of this test's own: each ``/ip dhcp-server`` ``add`` line's
    interface, the ``ranges`` of the ``/ip pool`` it names, and its
    lease time."""
    if "/ip dhcp-server" not in text.splitlines():
        return []
    ranges = {
        values.get("name", ""): values.get("ranges", "")
        for values in map(_key_values, _section(text, "/ip pool")) if values
    }
    return [
        (values.get("interface", ""), ranges.get(values.get("address-pool", ""), ""), values.get("lease-time", ""))
        for line in _section(text, "/ip dhcp-server") if line.startswith("add")
        for values in [_key_values(line)]
    ]


class TestTheRendererWritesTheServer:

    def test_each_pool_is_a_server_on_its_interface(self) -> None:
        text = MikroTikRouterOSCodec().render(_tree(
            _pool(), _pool("vlan100", 3600, network="198.51.100.0/24", start_ip="198.51.100.5",
                           end_ip="198.51.100.9", gateway="198.51.100.1"),
        ))
        assert _section(text, "/ip dhcp-server") == [
            "add address-pool=dhcp_pool1 disabled=no interface=ether2 lease-time=1d name=dhcp1",
            "add address-pool=dhcp_pool2 disabled=no interface=vlan100 lease-time=1h name=dhcp2",
        ]
        assert _served(text) == [
            ("ether2", "192.0.2.10-192.0.2.200", "1d"), ("vlan100", "198.51.100.5-198.51.100.9", "1h"),
        ]

    def test_a_pool_with_no_interface_is_a_review_line_and_no_server(self) -> None:
        codec = MikroTikRouterOSCodec()
        tree = _tree(_pool(""), _pool("ether3"))
        text = codec.render(tree)
        lines = _section(text, "/ip dhcp-server")
        assert lines[0].startswith("# review: the DHCP pool dhcp_pool1 (192.0.2.0/24) names no interface")
        assert lines[1:] == ["add address-pool=dhcp_pool2 disabled=no interface=ether3 lease-time=1d name=dhcp2"]
        warnings = [w for w in codec.render_warnings(tree) if "names no interface" in w]
        assert len(warnings) == 1 and "192.0.2.0/24" in warnings[0]
        # It reads back as no pool: a pool no server takes serves nothing.
        assert [p.interface for p in codec.parse(text).dhcp_servers] == ["ether3"]

    def test_a_lease_that_does_not_end_is_written_with_none_and_said(self) -> None:
        codec = MikroTikRouterOSCodec()
        tree = _tree(_pool(lease_time=0xFFFFFFFF))
        lines = _section(codec.render(tree), "/ip dhcp-server")
        assert lines[0].startswith("# review: the lease of the DHCP pool of ether2 does not end in the source")
        assert lines[1:] == ["add address-pool=dhcp_pool1 disabled=no interface=ether2 name=dhcp1"]
        assert [w for w in codec.render_warnings(tree) if "does not end" in w]

    def test_a_pool_that_is_not_written_has_no_server(self) -> None:
        # The first states no range and no network, so it has no /ip pool.
        text = MikroTikRouterOSCodec().render(_tree(
            _pool("ether2", network="", start_ip="", end_ip=""), _pool("ether3"),
        ))
        assert _section(text, "/ip dhcp-server") == [
            "add address-pool=dhcp_pool2 disabled=no interface=ether3 lease-time=1d name=dhcp2",
        ]
        # Nor a line of its options: what is not written is said once.
        assert not [line for line in _section(text, "/ip dhcp-server network") if line.startswith("#")]

    def test_options_with_no_network_are_a_review_line(self) -> None:
        # A pool of an OPNsense zone with no static address states its
        # gateway and DNS servers and no network: RouterOS gives them
        # from an /ip dhcp-server network, which needs one.
        codec = MikroTikRouterOSCodec()
        tree = _tree(_pool("igb2", network="", dns_servers=["192.0.2.53"]), _pool("ether3"))
        text = codec.render(tree)
        lines = _section(text, "/ip dhcp-server network")
        assert lines[0].startswith("# review: the DHCP pool of igb2 states no network")
        assert lines[1:] == ["add address=192.0.2.0/24 gateway=192.0.2.1"]
        assert len([w for w in codec.render_warnings(tree) if "states no network" in w]) == 1
        # The pool itself is served, on its interface.
        assert [line.split(" interface=")[1].split()[0] for line in _section(text, "/ip dhcp-server")] == [
            "igb2", "ether3",
        ]

    def test_no_pool_is_no_section(self) -> None:
        assert "/ip dhcp-server" not in MikroTikRouterOSCodec().render(_tree()).splitlines()


class TestTheOutputReadsBack:

    def test_through_the_text_and_through_the_parser(self) -> None:
        codec = MikroTikRouterOSCodec()
        tree = _tree(
            _pool("my port", 7200),
            _pool("vlan100", 1800, network="198.51.100.0/24", start_ip="198.51.100.5",
                  end_ip="198.51.100.9", gateway="198.51.100.1"),
        )
        text = codec.render(tree)
        assert _served(text) == [
            ("my port", "192.0.2.10-192.0.2.200", "2h"), ("vlan100", "198.51.100.5-198.51.100.9", "30m"),
        ]
        back = codec.parse(text)
        assert [
            (p.interface, p.network, p.start_ip, p.end_ip, p.gateway, p.lease_time) for p in back.dhcp_servers
        ] == [
            ("my port", "192.0.2.0/24", "192.0.2.10", "192.0.2.200", "192.0.2.1", 7200),
            ("vlan100", "198.51.100.0/24", "198.51.100.5", "198.51.100.9", "198.51.100.1", 1800),
        ]
        assert _rows(back) == []

    def test_the_reader_sees_a_server_left_out(self) -> None:
        """Handed the output as the renderer wrote it before (no server
        line), the reader of the text finds no server, and the parser
        finds no pool."""
        codec = MikroTikRouterOSCodec()
        text = codec.render(_tree(_pool()))
        lines = text.splitlines()
        start = lines.index("/ip dhcp-server")
        without = "\n".join(lines[:start] + lines[lines.index("", start) + 1:]) + "\n"
        assert _served(without) == []
        assert codec.parse(without).dhcp_servers == []

    def test_the_reader_sees_a_server_with_no_interface(self) -> None:
        text = MikroTikRouterOSCodec().render(_tree(_pool())).replace(" interface=ether2", "")
        assert _served(text) == [("", "192.0.2.10-192.0.2.200", "1d")]
