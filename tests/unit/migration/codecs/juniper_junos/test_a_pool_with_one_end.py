"""A Junos pool is written a whole range, or not written and said.

Juniper's reference of ``range`` names its ``low`` and its ``high`` and
does not say what a range with one of them is, and a pool hands out its
network's addresses only where it states no range.  The renderer wrote
a pool that states one end of its range as a ``range`` with that end
alone, and a pool with neither a range nor a network as its
``dhcp-attributes`` alone -- a pool that hands out nothing -- each with
nothing said (:mod:`netcanon.migration.codecs.juniper_junos.dhcp_pools`).

Every tree here is typed by hand; each output is read back with the
Junos parser.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalVlan,
)
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit

JUNOS = get_codec("juniper_junos")


def _tree(own: str = "192.0.2.1", **pool: str) -> CanonicalIntent:
    return CanonicalIntent(
        source_vendor="test", source_format="test", hostname="r1",
        interfaces=[CanonicalInterface(
            name="ge-0/0/1", ipv4_addresses=[CanonicalIPv4Address(ip=own, prefix_length=24)],
        )],
        dhcp_servers=[CanonicalDHCPPool(interface="ge-0/0/1", gateway="192.0.2.1", **pool)],
    )


def _review(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("# review:") and "DHCP pool" in line]


def _back(text: str) -> list[tuple[str, str, str]]:
    return [(p.network, p.start_ip, p.end_ip) for p in JUNOS.parse(text).dhcp_servers]


def _warnings(tree: CanonicalIntent) -> list[str]:
    return [w for w in JUNOS.render_warnings(tree) if "DHCP pool" in w]


class TestOneEnd:
    def test_the_low_end(self) -> None:
        tree = _tree(network="192.0.2.0/24", start_ip="192.0.2.50")
        out = JUNOS.render(tree)
        assert "range r1 low 192.0.2.50" in out
        assert "range r1 high 192.0.2.254" in out
        assert _review(out) == [
            "# review: the source states one end of the range of the DHCP pool of ge-0/0/1, "
            "and Junos's reference does not say what a range with one end is: written as "
            "192.0.2.50-192.0.2.254",
        ]
        assert _warnings(tree) == [
            "Junos DHCP pool ge-0/0/1: the source states one end of its range; it is written "
            "as 192.0.2.50-192.0.2.254; a review line in the output says so.",
        ]
        assert _back(out) == [("192.0.2.0/24", "192.0.2.50", "192.0.2.254")]

    def test_the_high_end_less_the_outputs_own_address(self) -> None:
        tree = _tree(network="192.0.2.0/24", end_ip="192.0.2.99")
        out = JUNOS.render(tree)
        assert _back(out) == [("192.0.2.0/24", "192.0.2.2", "192.0.2.99")]
        assert _review(out)[0].endswith(
            "written as 192.0.2.2-192.0.2.99, which is 192.0.2.1-192.0.2.99 less this output's own addresses",
        )
        assert len(_warnings(tree)) == 1

    def test_the_largest_run_where_an_own_address_splits_it(self) -> None:
        # The parser reads one range of a pool back, so the output has
        # one: the largest run that holds none of the output's own.
        tree = _tree(own="192.0.2.100", network="192.0.2.0/24", start_ip="192.0.2.50")
        out = JUNOS.render(tree)
        assert _back(out) == [("192.0.2.0/24", "192.0.2.101", "192.0.2.254")]
        assert "the largest run of 192.0.2.50-192.0.2.254" in _review(out)[0]
        assert len(_warnings(tree)) == 1

    def test_a_pool_of_a_vlan_address(self) -> None:
        # The VLAN interface the renderer makes of a VLAN's address is
        # an address of the output's own, as an interface's is.
        tree = CanonicalIntent(
            source_vendor="test", source_format="test", hostname="r1",
            vlans=[CanonicalVlan(id=10, name="users", ipv4_addresses=[
                CanonicalIPv4Address(ip="192.0.2.1", prefix_length=24)])],
            dhcp_servers=[CanonicalDHCPPool(interface="irb.10", network="192.0.2.0/24", end_ip="192.0.2.9")],
        )
        assert _back(JUNOS.render(tree)) == [("192.0.2.0/24", "192.0.2.2", "192.0.2.9")]


class TestNoAddressToWrite:
    @pytest.mark.parametrize(("pool", "reason"), [
        ({}, "it states no range and no network"),
        ({"start_ip": "192.0.2.50"}, "it states one end of its range and no network"),
        ({"network": "192.0.2.0/24", "start_ip": "198.51.100.5"}, "its range is not in its network"),
    ])
    def test_not_written_and_said(self, pool: dict[str, str], reason: str) -> None:
        tree = _tree(**pool)
        out = JUNOS.render(tree)
        assert "address-assignment" not in out
        assert "dhcp-local-server" not in out
        assert _review(out) == [
            f"# review: a DHCP pool of the source (ge-0/0/1) is not written: {reason}, "
            "so there is no address of it to write",
        ]
        assert _warnings(tree) == [
            f"Junos DHCP pool ge-0/0/1: it is not written: {reason}; a review line in the output says so.",
        ]
        assert _back(out) == []

    def test_every_address_is_the_outputs_own(self) -> None:
        tree = _tree(own="192.0.2.254", network="192.0.2.0/24", start_ip="192.0.2.254")
        out = JUNOS.render(tree)
        assert _back(out) == []
        assert "every address of its range is this output's own" in _review(out)[0]
        assert len(_warnings(tree)) == 1


class TestAsItStands:
    @pytest.mark.parametrize("pool", [
        {"network": "192.0.2.0/24"},
        {"network": "192.0.2.0/24", "start_ip": "192.0.2.10", "end_ip": "192.0.2.20"},
        # Both ends and no network: the range is the pool, as written.
        {"start_ip": "192.0.2.10", "end_ip": "192.0.2.20"},
    ])
    def test_nothing_is_said(self, pool: dict[str, str]) -> None:
        tree = _tree(**pool)
        out = JUNOS.render(tree)
        assert _review(out) == []
        assert _warnings(tree) == []
        assert _back(out) == [(pool.get("network", ""), pool.get("start_ip", ""), pool.get("end_ip", ""))]
        assert "dhcp-local-server group" in out


def test_each_review_line_is_a_warning() -> None:
    tree = CanonicalIntent(
        source_vendor="test", source_format="test", hostname="r1",
        interfaces=[CanonicalInterface(
            name="ge-0/0/1", ipv4_addresses=[CanonicalIPv4Address(ip="192.0.2.1", prefix_length=24)],
        )],
        dhcp_servers=[
            CanonicalDHCPPool(interface="ge-0/0/1", network="192.0.2.0/24", start_ip="192.0.2.50"),
            CanonicalDHCPPool(interface="ge-0/0/2"),
            CanonicalDHCPPool(interface="ge-0/0/3", network="198.51.100.0/24"),
        ],
    )
    assert len(_review(JUNOS.render(tree))) == len(_warnings(tree)) == 2
