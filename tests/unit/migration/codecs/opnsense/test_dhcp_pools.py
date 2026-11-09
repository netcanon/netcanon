"""An OPNsense DHCP zone is written with the addresses its pool hands out.

The renderer wrote a pool that states no range as an enabled zone with
no ``<range>``, and said nothing: such a pool hands out its network's
addresses, OPNsense writes a ``range`` line for every zone it serves
(enabled, its interface holding an IPv4 address) whether it states one
or not, and its GUI saves no zone without one.  See the docstring of
``opnsense/dhcp_pools.py``.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
)
from netcanon.migration.codecs.opnsense import OPNsenseCodec

pytestmark = pytest.mark.unit


def _tree(*addresses: str, **pool: str) -> CanonicalIntent:
    """One interface with *addresses* (each a /24) and one pool of
    192.0.2.0/24 on it, with the fields *pool* states."""
    iface = CanonicalInterface(
        name="igb1",
        ipv4_addresses=[
            CanonicalIPv4Address(ip=address, prefix_length=24) for address in addresses
        ],
    )
    fields = {"interface": "igb1", "network": "192.0.2.0/24", "gateway": "192.0.2.1"}
    fields.update(pool)
    return CanonicalIntent(
        source_vendor="test", source_format="test", hostname="r1",
        interfaces=[iface], dhcp_servers=[CanonicalDHCPPool(**fields)],
    )


def _dhcpd(text: str) -> ET.Element:
    """The ``<dhcpd>`` element of *text*, its comments kept."""
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(text, parser=parser)
    found = root.find("dhcpd")
    assert found is not None
    return found


def _comments(element: ET.Element) -> list[str]:
    return [child.text.strip() for child in element.iter() if child.tag is ET.Comment]


def _range(zone: ET.Element) -> tuple[str, str]:
    return zone.findtext("range/from", ""), zone.findtext("range/to", "")


class TestAPoolWithNoWholeRange:

    def test_no_range_is_its_networks_hosts_less_the_interfaces_own(self) -> None:
        tree = _tree("192.0.2.1")
        codec = OPNsenseCodec()
        dhcpd = _dhcpd(codec.render(tree))
        (zone,) = [child for child in dhcpd if child.tag is not ET.Comment]
        assert _range(zone) == ("192.0.2.2", "192.0.2.254")
        (said,) = _comments(zone)
        assert said.startswith("review: the source states no range for this pool")
        assert "other runs" not in said
        warnings = [w for w in codec.render_warnings(tree) if "DHCP" in w]
        assert len(warnings) == 1
        assert "igb1" in warnings[0] and "192.0.2.2-192.0.2.254" in warnings[0]

    def test_an_own_address_inside_leaves_the_largest_run(self) -> None:
        dhcpd = _dhcpd(OPNsenseCodec().render(_tree("192.0.2.1", "192.0.2.100")))
        (zone,) = [child for child in dhcpd if child.tag is not ET.Comment]
        assert _range(zone) == ("192.0.2.101", "192.0.2.254")
        (said,) = _comments(zone)
        assert "the other runs of it are not handed out" in said

    def test_one_end_is_kept_and_the_other_is_the_networks(self) -> None:
        dhcpd = _dhcpd(OPNsenseCodec().render(_tree("192.0.2.1", end_ip="192.0.2.150")))
        (zone,) = [child for child in dhcpd if child.tag is not ET.Comment]
        assert _range(zone) == ("192.0.2.2", "192.0.2.150")
        assert "one end of its range" in _comments(zone)[0]

    @pytest.mark.parametrize(
        ("pool", "why"),
        [
            ({"network": ""}, "it states no range and no network"),
            ({"start_ip": "198.51.100.5"}, "its range is not in its network"),
        ],
    )
    def test_a_pool_that_can_be_given_no_range_is_no_zone(
        self, pool: dict[str, str], why: str,
    ) -> None:
        tree = _tree("192.0.2.1", **pool)
        codec = OPNsenseCodec()
        text = codec.render(tree)
        dhcpd = _dhcpd(text)
        assert [child for child in dhcpd if child.tag is not ET.Comment] == []
        (said,) = _comments(dhcpd)
        assert said.startswith("review: a DHCP pool of the source (igb1) is not written")
        assert why in said
        assert [w for w in codec.render_warnings(tree) if why in w]
        assert codec.parse(text).dhcp_servers == []

    def test_a_zone_opnsense_does_not_serve_is_as_it_was(self) -> None:
        """The plugin skips a zone whose interface has no IPv4 address
        (a DHCP client's zone), so such a pool is no ``range`` line of
        any server, and is written as it stands."""
        tree = _tree(network="", domain_name="wan.example")
        codec = OPNsenseCodec()
        dhcpd = _dhcpd(codec.render(tree))
        (zone,) = list(dhcpd)
        assert zone.find("enable") is not None
        assert zone.find("range") is None
        assert zone.findtext("domain") == "wan.example"
        assert not [w for w in codec.render_warnings(tree) if "DHCP" in w]

    def test_a_pool_that_states_its_range_is_as_it_was(self) -> None:
        tree = _tree("192.0.2.1", start_ip="192.0.2.100", end_ip="192.0.2.200")
        codec = OPNsenseCodec()
        dhcpd = _dhcpd(codec.render(tree))
        (zone,) = list(dhcpd)
        assert _range(zone) == ("192.0.2.100", "192.0.2.200")
        assert _comments(dhcpd) == []
        assert not [w for w in codec.render_warnings(tree) if "DHCP" in w]

    def test_the_output_reads_back_to_the_range_written(self) -> None:
        codec = OPNsenseCodec()
        back = codec.parse(codec.render(_tree("192.0.2.1")))
        assert [(p.start_ip, p.end_ip) for p in back.dhcp_servers] == [
            ("192.0.2.2", "192.0.2.254"),
        ]
