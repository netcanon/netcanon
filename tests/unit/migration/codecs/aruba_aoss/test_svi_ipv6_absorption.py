"""aruba_aoss SVI-mounted IPv6 — 2026-07-06 Fable review #10.

AOS-S packs the SVI L3 inside the ``vlan N`` stanza. IPv4 was absorbed
onto a synthesised ``Vlan<N>`` CanonicalInterface, but ``ipv6 address``
lines were skipped outright — a SILENT, UNDECLARED drop on both the
aoss round-trip and any cross-vendor render (the matrix declared the
ipv6 path supported, so validate reported zero findings). These tests
pin the parse + absorption-render round-trip.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv6Address,
    CanonicalVlan,
)
from netcanon.migration.codecs.aruba_aoss import ArubaAOSSCodec

pytestmark = pytest.mark.unit


class TestSviIpv6Parse:
    def test_vlan_context_ipv6_lands_on_svi_interface(self):
        cfg = (
            "vlan 10\n"
            '   name "V10"\n'
            "   ip address 10.0.10.1/24\n"
            "   ipv6 address 2001:db8:10::1/64\n"
            "   exit\n"
        )
        intent = ArubaAOSSCodec().parse(cfg)
        svi = next(i for i in intent.interfaces if i.name == "Vlan10")
        # Pre-fix: ipv6_addresses == [] (line silently skipped).
        assert [a.ip for a in svi.ipv6_addresses] == ["2001:db8:10::1"]
        assert svi.ipv6_addresses[0].prefix_length == 64

    def test_link_local_scope_preserved(self):
        cfg = (
            "vlan 20\n"
            "   ipv6 address fe80::1/64 link-local\n"
            "   exit\n"
        )
        intent = ArubaAOSSCodec().parse(cfg)
        svi = next(i for i in intent.interfaces if i.name == "Vlan20")
        assert svi.ipv6_addresses[0].scope == "link-local"


class TestSviIpv6Render:
    def test_cross_vendor_svi_ipv6_emitted_in_vlan_stanza(self):
        # A cross-vendor source (Vlan10 interface carrying ipv6) must
        # render the ipv6 address inside the vlan stanza — was dropped.
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(id=10, name="V10")],
            interfaces=[
                CanonicalInterface(
                    name="Vlan10",
                    interface_type="ianaift:l3ipvlan",
                    ipv6_addresses=[
                        CanonicalIPv6Address(ip="2001:db8:10::1", prefix_length=64)
                    ],
                ),
            ],
        )
        out = ArubaAOSSCodec().render(tree)
        assert "ipv6 address 2001:db8:10::1/64" in out
        # SVI iface absorbed into the vlan stanza → no stray
        # `interface Vlan10` block.
        assert "interface Vlan10" not in out

    def test_aoss_round_trip_preserves_svi_ipv6(self):
        c = ArubaAOSSCodec()
        cfg = (
            "vlan 30\n"
            '   name "V30"\n'
            "   ip address 10.0.30.1/24\n"
            "   ipv6 address 2001:db8:30::1/64\n"
            "   exit\n"
        )
        reparsed = c.parse(c.render(c.parse(cfg)))
        svi = next(i for i in reparsed.interfaces if i.name == "Vlan30")
        assert [a.ip for a in svi.ipv6_addresses] == ["2001:db8:30::1"]
