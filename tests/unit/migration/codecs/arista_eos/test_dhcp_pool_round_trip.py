"""
Cluster E.1-A: arista_eos DHCP-server parse + render round-trip tests.

Reference: Arista EOS User Manual — "DHCP and DHCP Relay"
(https://www.arista.com/en/um-eos/eos-dhcp-and-dhcp-relay).

EOS DHCP-pool grammar (post-7.x):

    ip dhcp pool <name>
       network <ip> <netmask>          ! dotted-mask form
       network <ip>/<prefix>           ! CIDR form (also accepted)
       range <start_ip> <end_ip>       ! allocatable window
       default-router <ip>             ! Cisco-derived spelling on EOS
       dns-server <ip> [<ip> ...]
       lease <days> [<hours>] [<minutes>]
       lease infinite
       domain-name <name>
    !

Lease conversion: canonical seconds <-> EOS d/h/m triple.  ``lease 0 12 0``
is twelve hours (43_200 s); ``lease 7`` is seven days (604_800 s); ``lease
infinite`` is the DHCP max-uint32 sentinel ``0xFFFFFFFF``.

Tests target: parse, render, native round-trip, cross-vendor round-trip
(via cisco_iosxe_cli source — the closest grammar twin).
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
)
from netconfig.migration.codecs.arista_eos import AristaEOSCodec
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Native parse tests — every CanonicalDHCPPool field exercised once.
# ---------------------------------------------------------------------------


class TestAristaDHCPParse:
    def test_basic_pool_dotted_mask_form(self):
        raw = (
            "hostname sw1\n"
            "ip dhcp pool USERS\n"
            "   network 192.168.10.0 255.255.255.0\n"
            "   range 192.168.10.100 192.168.10.200\n"
            "   default-router 192.168.10.1\n"
            "   dns-server 192.168.10.4 8.8.8.8\n"
            "   domain-name example.net\n"
            "   lease 0 12 0\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert len(intent.dhcp_servers) == 1
        p = intent.dhcp_servers[0]
        assert p.interface == "USERS"
        assert p.network == "192.168.10.0/24"
        assert p.start_ip == "192.168.10.100"
        assert p.end_ip == "192.168.10.200"
        assert p.gateway == "192.168.10.1"
        assert p.dns_servers == ["192.168.10.4", "8.8.8.8"]
        assert p.domain_name == "example.net"
        assert p.lease_time == 12 * 3600   # 43_200 s

    def test_basic_pool_cidr_form(self):
        """EOS accepts ``network <ip>/<prefix>`` as well as the dotted-mask
        form — see the Arista DHCP doc snippet for VOICE pool."""
        raw = (
            "hostname sw1\n"
            "ip dhcp pool VOICE\n"
            "   network 10.10.20.0/24\n"
            "   range 10.10.20.50 10.10.20.150\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        p = intent.dhcp_servers[0]
        assert p.network == "10.10.20.0/24"
        assert p.start_ip == "10.10.20.50"
        assert p.end_ip == "10.10.20.150"

    def test_lease_days_only(self):
        raw = (
            "ip dhcp pool A\n"
            "   network 10.0.0.0 255.255.255.0\n"
            "   lease 7\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert intent.dhcp_servers[0].lease_time == 7 * 86400

    def test_lease_days_hours_minutes(self):
        raw = (
            "ip dhcp pool A\n"
            "   network 10.0.0.0 255.255.255.0\n"
            "   lease 2 6 30\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        expected = 2 * 86400 + 6 * 3600 + 30 * 60
        assert intent.dhcp_servers[0].lease_time == expected

    def test_lease_infinite(self):
        raw = (
            "ip dhcp pool A\n"
            "   network 10.0.0.0 255.255.255.0\n"
            "   lease infinite\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert intent.dhcp_servers[0].lease_time == 0xFFFFFFFF

    def test_multiple_pools(self):
        raw = (
            "ip dhcp pool A\n"
            "   network 10.0.0.0 255.255.255.0\n"
            "   default-router 10.0.0.1\n"
            "!\n"
            "ip dhcp pool B\n"
            "   network 10.0.1.0 255.255.255.0\n"
            "   default-router 10.0.1.1\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert len(intent.dhcp_servers) == 2
        assert intent.dhcp_servers[0].interface == "A"
        assert intent.dhcp_servers[1].interface == "B"
        assert intent.dhcp_servers[0].network == "10.0.0.0/24"
        assert intent.dhcp_servers[1].network == "10.0.1.0/24"


# ---------------------------------------------------------------------------
# Native render tests — every emit branch validated.
# ---------------------------------------------------------------------------


class TestAristaDHCPRender:
    def test_render_emits_named_pool_stanza(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            dhcp_servers=[CanonicalDHCPPool(
                interface="USERS",
                network="192.168.10.0/24",
                start_ip="192.168.10.100",
                end_ip="192.168.10.200",
                gateway="192.168.10.1",
                dns_servers=["192.168.10.4", "8.8.8.8"],
                domain_name="example.net",
                lease_time=12 * 3600,
            )],
        )
        out = AristaEOSCodec().render(intent)
        assert "ip dhcp pool USERS" in out
        # Dotted-mask form (consistent with the cisco_iosxe_cli emit
        # convention so EOS targets accept the syntax verbatim).
        assert "   network 192.168.10.0 255.255.255.0" in out
        assert "   range 192.168.10.100 192.168.10.200" in out
        assert "   default-router 192.168.10.1" in out
        assert "   dns-server 192.168.10.4 8.8.8.8" in out
        assert "   domain-name example.net" in out
        # 12 hours -> "lease 0 12 0".
        assert "   lease 0 12 0" in out

    def test_render_pool_name_falls_back_when_interface_empty(self):
        """An interface-less pool (Cisco-style network-only) must still
        emit a syntactically valid named-pool stanza."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            dhcp_servers=[CanonicalDHCPPool(
                network="10.0.0.0/24",
                gateway="10.0.0.1",
            )],
        )
        out = AristaEOSCodec().render(intent)
        assert "ip dhcp pool " in out
        assert "   network 10.0.0.0 255.255.255.0" in out
        assert "   default-router 10.0.0.1" in out


# ---------------------------------------------------------------------------
# Native round-trip — parse(render(parse(x))) == parse(x) on dhcp_servers.
# ---------------------------------------------------------------------------


class TestAristaDHCPRoundTrip:
    def test_native_round_trip_preserves_all_fields(self):
        raw = (
            "ip dhcp pool USERS\n"
            "   network 192.168.10.0 255.255.255.0\n"
            "   range 192.168.10.100 192.168.10.200\n"
            "   default-router 192.168.10.1\n"
            "   dns-server 1.1.1.1 8.8.8.8\n"
            "   domain-name corp.local\n"
            "   lease 1\n"
            "!\n"
        )
        c = AristaEOSCodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        a = first.dhcp_servers[0]
        b = second.dhcp_servers[0]
        assert a.interface == b.interface == "USERS"
        assert a.network == b.network == "192.168.10.0/24"
        assert a.start_ip == b.start_ip == "192.168.10.100"
        assert a.end_ip == b.end_ip == "192.168.10.200"
        assert a.gateway == b.gateway == "192.168.10.1"
        assert a.dns_servers == b.dns_servers == ["1.1.1.1", "8.8.8.8"]
        assert a.domain_name == b.domain_name == "corp.local"
        assert a.lease_time == b.lease_time == 86400


# ---------------------------------------------------------------------------
# Cross-vendor round-trip — Cisco IOS-XE source -> Arista render -> Arista
# parse.  Both grammars use ``ip dhcp pool`` but Cisco lacks the explicit
# ``range`` line; verify the closer-twin migration preserves the
# CanonicalDHCPPool surface.
# ---------------------------------------------------------------------------


class TestCiscoToAristaDHCP:
    def test_cisco_pool_renders_to_arista_and_re_parses(self):
        cisco_raw = (
            "ip dhcp pool USERS\n"
            " network 10.0.0.0 255.255.255.0\n"
            " default-router 10.0.0.1\n"
            " dns-server 10.0.0.4\n"
            " domain-name corp.local\n"
            " lease 1\n"
            "!\n"
        )
        intent = CiscoIOSXECLICodec().parse(cisco_raw)
        eos_text = AristaEOSCodec().render(intent)
        # Render emits an EOS-shaped pool stanza.
        assert "ip dhcp pool" in eos_text
        assert "   network 10.0.0.0 255.255.255.0" in eos_text
        assert "   default-router 10.0.0.1" in eos_text

        # Round-trip back through arista parse.
        re_parsed = AristaEOSCodec().parse(eos_text)
        assert len(re_parsed.dhcp_servers) == 1
        p = re_parsed.dhcp_servers[0]
        assert p.network == "10.0.0.0/24"
        assert p.gateway == "10.0.0.1"
        assert p.dns_servers == ["10.0.0.4"]
        assert p.domain_name == "corp.local"
        assert p.lease_time == 86400


# ---------------------------------------------------------------------------
# Capability-matrix wire-up — once parse + render exist, the matrix must
# advertise /dhcp_servers as supported (not unsupported).
# ---------------------------------------------------------------------------


class TestAristaDHCPCapability:
    def test_dhcp_servers_advertised_supported(self):
        caps = AristaEOSCodec().capabilities
        # The path may be advertised under any of the conventional canonical
        # YANG-ish prefixes used elsewhere in the matrix; assert presence.
        assert any("dhcp" in p for p in caps.supported), (
            "AristaEOSCodec must advertise DHCP-pool support after Cluster "
            "E.1-A: parse + render landed."
        )
        assert not any(
            "dhcp" in u.path for u in caps.unsupported
        ), "DHCP path should no longer appear in `unsupported`."
