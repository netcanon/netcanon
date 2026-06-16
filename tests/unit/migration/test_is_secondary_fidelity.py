"""R-13 / CC-02 — cross-vendor fidelity of classic ``ip address X secondary``.

Before R-13, the `cisco_iosxe_cli` `ip address` handler dropped the
`secondary` keyword (round-tripping it only *positionally*) and the
`arista_eos` plain `ip address` parse branch dropped the trailer
outright ("first address wins").  So a classic secondary address lost
its `is_secondary` designation on `cisco_iosxe_cli → arista_eos` and on
`arista_eos → arista_eos`.

The fix (additive): cisco parse now captures `is_secondary` (its render
stays positional, so cisco self-round-trips are byte-stable); arista
parse sets the flag from the trailer; arista's plain `ip address` render
branch emits ` secondary` when the flag is set.  This module guards all
three.  (The VARP `ip address virtual … secondary` path already worked
and is covered by `test_arista_eos.py::TestVARPAnycast`.)
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
)
from netcanon.migration.codecs.arista_eos import AristaEOSCodec
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec

pytestmark = pytest.mark.unit


class TestPlainSecondaryAddressFidelity:
    """Arista plain (non-VARP) ``ip address X/Y secondary`` round-trips."""

    def test_arista_plain_parse_sets_is_secondary(self):
        raw = (
            "hostname sw1\n"
            "interface Vlan20\n"
            "   ip address 10.0.20.1/24\n"
            "   ip address 10.0.99.1/24 secondary\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan20")
        assert len(iface.ipv4_addresses) == 2
        assert iface.ipv4_addresses[0].ip == "10.0.20.1"
        assert iface.ipv4_addresses[0].is_secondary is False
        assert iface.ipv4_addresses[1].ip == "10.0.99.1"
        assert iface.ipv4_addresses[1].is_secondary is True
        # Plain addresses must NOT be mistaken for VARP.
        assert iface.ipv4_addresses[1].virtual_gateway_address == ""

    def test_arista_plain_render_emits_secondary(self):
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(
                    name="Vlan20",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.0.20.1", prefix_length=24),
                        CanonicalIPv4Address(
                            ip="10.0.99.1", prefix_length=24, is_secondary=True,
                        ),
                    ],
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "   ip address 10.0.20.1/24" in out
        assert "   ip address 10.0.99.1/24 secondary" in out
        # The primary must NOT carry the trailer.
        assert "   ip address 10.0.20.1/24 secondary" not in out

    def test_arista_plain_self_round_trip_preserves_secondary(self):
        raw = (
            "hostname sw1\n"
            "interface Vlan20\n"
            "   ip address 10.0.20.1/24\n"
            "   ip address 10.0.99.1/24 secondary\n"
            "!\n"
        )
        codec = AristaEOSCodec()
        tree1 = codec.parse(raw)
        tree2 = codec.parse(codec.render(tree1))
        i1 = next(i for i in tree1.interfaces if i.name == "Vlan20")
        i2 = next(i for i in tree2.interfaces if i.name == "Vlan20")
        assert len(i1.ipv4_addresses) == len(i2.ipv4_addresses) == 2
        for a, b in zip(i1.ipv4_addresses, i2.ipv4_addresses):
            assert a.ip == b.ip
            assert a.prefix_length == b.prefix_length
            assert a.is_secondary == b.is_secondary
        assert i2.ipv4_addresses[1].is_secondary is True

    def test_cisco_cli_to_arista_preserves_secondary(self):
        """The R-13 cross-vendor target: cisco_iosxe_cli dotted-mask
        ``secondary`` → arista CIDR ``secondary``."""
        cisco_raw = (
            "hostname r1\n"
            "interface Vlan20\n"
            " ip address 10.0.20.1 255.255.255.0\n"
            " ip address 10.0.99.1 255.255.255.0 secondary\n"
            "!\n"
        )
        intent = CiscoIOSXECLICodec().parse(cisco_raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan20")
        assert iface.ipv4_addresses[0].is_secondary is False
        assert iface.ipv4_addresses[1].is_secondary is True
        out = AristaEOSCodec().render(intent)
        assert "   ip address 10.0.20.1/24" in out
        assert "   ip address 10.0.99.1/24 secondary" in out
        assert "   ip address 10.0.20.1/24 secondary" not in out


class TestCiscoCLISecondaryAddress:
    """cisco_iosxe_cli now CAPTURES ``is_secondary`` on parse while its
    render stays POSITIONAL, so self-round-trips remain byte-stable."""

    _RAW = (
        "hostname r1\n"
        "interface Vlan20\n"
        " ip address 10.0.20.1 255.255.255.0\n"
        " ip address 10.0.99.1 255.255.255.0 secondary\n"
        "!\n"
    )

    def test_parse_sets_is_secondary_from_trailer(self):
        intent = CiscoIOSXECLICodec().parse(self._RAW)
        iface = next(i for i in intent.interfaces if i.name == "Vlan20")
        assert iface.ipv4_addresses[0].is_secondary is False
        assert iface.ipv4_addresses[1].is_secondary is True

    def test_self_round_trip_positional_secondary_unchanged(self):
        codec = CiscoIOSXECLICodec()
        out = codec.render(codec.parse(self._RAW))
        assert " ip address 10.0.20.1 255.255.255.0" in out
        assert " ip address 10.0.99.1 255.255.255.0 secondary" in out
        # Primary must not gain a spurious trailer.
        assert " ip address 10.0.20.1 255.255.255.0 secondary" not in out
        # Idempotent: a second pass is identical.
        assert codec.render(codec.parse(out)) == out
