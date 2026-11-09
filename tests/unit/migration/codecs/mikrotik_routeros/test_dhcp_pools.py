"""A RouterOS ``/ip pool`` is written with the addresses it hands out.

The renderer left out the ``/ip pool`` of a pool that states no range,
or one end of one, and said nothing: such a pool hands out its
network's addresses, and RouterOS takes no pool without its ``ranges``
(the manual: "mandatory").  And the parser kept the first run of a
``ranges=`` that states several, and read a piece in another form as
nothing, silently.  See the docstring of
``mikrotik_routeros/dhcp_pools.py``.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
)
from netcanon.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec

pytestmark = pytest.mark.unit


def _tree(*addresses: str, **pool: str) -> CanonicalIntent:
    """One interface with *addresses* (each a /24) and one pool of
    192.0.2.0/24 on it, with the fields *pool* states."""
    iface = CanonicalInterface(
        name="ether2",
        ipv4_addresses=[
            CanonicalIPv4Address(ip=address, prefix_length=24) for address in addresses
        ],
    )
    fields = {"interface": "ether2", "network": "192.0.2.0/24", "gateway": "192.0.2.1"}
    fields.update(pool)
    return CanonicalIntent(
        source_vendor="test", source_format="test", hostname="r1",
        interfaces=[iface], dhcp_servers=[CanonicalDHCPPool(**fields)],
    )


def _pool_lines(text: str) -> list[str]:
    """The lines of the ``/ip pool`` section, its header left out."""
    lines = text.splitlines()
    start = lines.index("/ip pool") + 1
    end = lines.index("", start)
    return lines[start:end]


class TestAPoolWithNoWholeRange:

    def test_no_range_is_its_networks_hosts_less_the_interfaces_own(self) -> None:
        tree = _tree("192.0.2.1")
        codec = MikroTikRouterOSCodec()
        lines = _pool_lines(codec.render(tree))
        assert lines[-1] == "add name=dhcp_pool1 ranges=192.0.2.2-192.0.2.254"
        assert lines[0].startswith("# review: the source states no range for the pool of ether2")
        warnings = [w for w in codec.render_warnings(tree) if "DHCP" in w]
        assert len(warnings) == 1
        assert "ether2" in warnings[0] and "192.0.2.1-192.0.2.254" in warnings[0]

    def test_an_own_address_inside_splits_the_ranges(self) -> None:
        tree = _tree("192.0.2.1", "192.0.2.100")
        lines = _pool_lines(MikroTikRouterOSCodec().render(tree))
        assert lines[-1] == (
            "add name=dhcp_pool1 ranges=192.0.2.2-192.0.2.99,192.0.2.101-192.0.2.254"
        )

    def test_one_end_is_kept_and_the_other_is_the_networks(self) -> None:
        tree = _tree("192.0.2.1", start_ip="192.0.2.50")
        lines = _pool_lines(MikroTikRouterOSCodec().render(tree))
        assert lines[-1] == "add name=dhcp_pool1 ranges=192.0.2.50-192.0.2.254"
        assert "one end of its range" in lines[0]

    @pytest.mark.parametrize(
        ("pool", "why"),
        [
            ({"network": ""}, "it states no range and no network"),
            ({"start_ip": "198.51.100.5"}, "its range is not in its network"),
        ],
    )
    def test_a_pool_that_can_be_given_no_range_is_a_review_line(
        self, pool: dict[str, str], why: str,
    ) -> None:
        tree = _tree("192.0.2.1", **pool)
        codec = MikroTikRouterOSCodec()
        lines = _pool_lines(codec.render(tree))
        assert len(lines) == 1
        assert lines[0].startswith("# review: a DHCP pool of the source")
        assert why in lines[0]
        assert [w for w in codec.render_warnings(tree) if why in w]

    def test_every_address_its_own_is_a_review_line(self) -> None:
        tree = _tree("192.0.2.1", "192.0.2.2", start_ip="192.0.2.1", network="192.0.2.0/30")
        lines = _pool_lines(MikroTikRouterOSCodec().render(tree))
        assert lines == [
            "# review: a DHCP pool of the source (ether2) is not written: every "
            "address of its range is this output's own, and RouterOS takes no "
            "/ip pool without its ranges",
        ]

    def test_a_pool_that_states_its_range_is_as_it_was(self) -> None:
        tree = _tree("192.0.2.1", start_ip="192.0.2.100", end_ip="192.0.2.200")
        codec = MikroTikRouterOSCodec()
        assert _pool_lines(codec.render(tree)) == [
            "add name=dhcp_pool1 ranges=192.0.2.100-192.0.2.200",
        ]
        assert not [w for w in codec.render_warnings(tree) if "DHCP" in w]

    def test_the_output_reads_back_to_a_run_of_the_network(self) -> None:
        codec = MikroTikRouterOSCodec()
        back = codec.parse(codec.render(_tree("192.0.2.1", "192.0.2.100")))
        assert [(p.network, p.start_ip, p.end_ip) for p in back.dhcp_servers] == [
            ("192.0.2.0/24", "192.0.2.101", "192.0.2.254"),
        ]


_NETWORK = "/ip dhcp-server network\nadd address=192.0.2.0/24 gateway=192.0.2.1\n"


class TestTheParserReadsEveryRange:

    def test_the_largest_run_is_kept_and_the_others_said(self) -> None:
        tree = MikroTikRouterOSCodec().parse(
            _NETWORK
            + "/ip pool\nadd name=lan ranges=192.0.2.10-192.0.2.20,192.0.2.100-192.0.2.200\n",
        )
        assert [(p.start_ip, p.end_ip) for p in tree.dhcp_servers] == [
            ("192.0.2.100", "192.0.2.200"),
        ]
        rows = [row for row in tree.dropped_tier3_sections if row.startswith("/ip pool")]
        assert rows == [
            "/ip pool lan: ranges= more than one range -- the tree holds one run "
            "of a pool, so the largest is kept and the others are not translated",
        ]

    def test_the_lower_of_two_as_large_is_kept(self) -> None:
        tree = MikroTikRouterOSCodec().parse(
            _NETWORK + "/ip pool\nadd name=lan ranges=192.0.2.50-192.0.2.59,192.0.2.10-192.0.2.19\n",
        )
        assert [(p.start_ip, p.end_ip) for p in tree.dhcp_servers] == [
            ("192.0.2.10", "192.0.2.19"),
        ]

    def test_a_piece_in_another_form_is_said(self) -> None:
        tree = MikroTikRouterOSCodec().parse(
            _NETWORK + "/ip pool\nadd name=lan ranges=192.0.2.10-192.0.2.20,192.0.2.30\n",
        )
        assert [(p.start_ip, p.end_ip) for p in tree.dhcp_servers] == [
            ("192.0.2.10", "192.0.2.20"),
        ]
        rows = [row for row in tree.dropped_tier3_sections if row.startswith("/ip pool")]
        assert rows == [
            "/ip pool lan: ranges= a range in a form this parser does not read "
            "(it reads <from>-<to>); not translated",
        ]

    def test_one_range_says_nothing(self) -> None:
        tree = MikroTikRouterOSCodec().parse(
            _NETWORK + "/ip pool\nadd name=lan ranges=192.0.2.10-192.0.2.20\n",
        )
        assert [(p.start_ip, p.end_ip) for p in tree.dhcp_servers] == [
            ("192.0.2.10", "192.0.2.20"),
        ]
        assert not [row for row in tree.dropped_tier3_sections if row.startswith("/ip pool")]
