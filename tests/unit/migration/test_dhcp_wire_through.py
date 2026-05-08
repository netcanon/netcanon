"""
Unit tests for :class:`CanonicalDHCPPool` wire-through across codecs.

Vendor coverage:
    * cisco_iosxe_cli  - parse only (`ip dhcp pool` stanza)
    * opnsense          - parse + render (`<dhcpd>/<zone>` blocks)
    * fortigate_cli     - parse + render (`config system dhcp server`)
    * mikrotik_routeros - parse + render (`/ip dhcp-server network` +
                          `/ip pool` section-pair, deferred merge)
    * aruba_aoss        - render-only (emits a comment block; AOS-S
                          doesn't implement DHCP server)
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
)
from netcanon.migration.codecs.aruba_aoss import ArubaAOSSCodec
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.fortigate_cli import FortiGateCLICodec
from netcanon.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netcanon.migration.codecs.opnsense import OPNsenseCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Cisco IOS-XE CLI
# ---------------------------------------------------------------------------


class TestCiscoDHCPParse:
    def test_basic_pool_network_gateway_dns(self):
        raw = """\
ip dhcp pool DATA
 network 192.168.10.0 255.255.255.0
 default-router 192.168.10.1
 dns-server 192.168.10.4 8.8.8.8
 domain-name example.com
 lease 7
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        assert len(intent.dhcp_servers) == 1
        p = intent.dhcp_servers[0]
        assert p.network == "192.168.10.0/24"
        assert p.gateway == "192.168.10.1"
        assert p.dns_servers == ["192.168.10.4", "8.8.8.8"]
        assert p.domain_name == "example.com"
        assert p.lease_time == 7 * 86400

    def test_multiple_pools(self):
        raw = """\
ip dhcp pool A
 network 10.0.0.0 255.255.255.0
 default-router 10.0.0.1
!
ip dhcp pool B
 network 10.0.1.0 255.255.255.0
 default-router 10.0.1.1
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        assert len(intent.dhcp_servers) == 2
        assert intent.dhcp_servers[0].network == "10.0.0.0/24"
        assert intent.dhcp_servers[1].network == "10.0.1.0/24"

    def test_lease_infinite(self):
        raw = """\
ip dhcp pool A
 network 10.0.0.0 255.255.255.0
 lease infinite
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        # Infinite lease = max uint32 per DHCP convention.
        assert intent.dhcp_servers[0].lease_time == 0xFFFFFFFF

    def test_lease_days_hours_minutes(self):
        raw = """\
ip dhcp pool A
 network 10.0.0.0 255.255.255.0
 lease 2 6 30
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        expected = 2 * 86400 + 6 * 3600 + 30 * 60
        assert intent.dhcp_servers[0].lease_time == expected


# ---------------------------------------------------------------------------
# OPNsense
# ---------------------------------------------------------------------------


class TestOPNsenseDHCPParseRender:
    def test_parse_lan_zone(self):
        raw = """\
<opnsense>
<dhcpd>
<lan>
<enable/>
<range><from>192.168.1.100</from><to>192.168.1.199</to></range>
<gateway>192.168.1.1</gateway>
<dnsserver>1.1.1.1,8.8.8.8</dnsserver>
<domain>example.com</domain>
<defaultleasetime>7200</defaultleasetime>
</lan>
</dhcpd>
</opnsense>
"""
        intent = OPNsenseCodec().parse(raw)
        assert len(intent.dhcp_servers) == 1
        p = intent.dhcp_servers[0]
        assert p.interface == "lan"
        assert p.start_ip == "192.168.1.100"
        assert p.end_ip == "192.168.1.199"
        assert p.gateway == "192.168.1.1"
        assert p.dns_servers == ["1.1.1.1", "8.8.8.8"]
        assert p.domain_name == "example.com"
        assert p.lease_time == 7200

    def test_empty_zone_skipped(self):
        """Upstream config.xml.sample has empty <wan>/<lan> zones used
        as scaffolding; don't create bogus empty pool records."""
        raw = """\
<opnsense>
<dhcpd>
<lan></lan>
<wan></wan>
</dhcpd>
</opnsense>
"""
        intent = OPNsenseCodec().parse(raw)
        assert intent.dhcp_servers == []

    def test_render_emits_dhcpd_element(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            dhcp_servers=[CanonicalDHCPPool(
                interface="lan",
                start_ip="10.0.0.100",
                end_ip="10.0.0.199",
                gateway="10.0.0.1",
                dns_servers=["1.1.1.1"],
                domain_name="corp.local",
                lease_time=3600,
            )],
        )
        out = OPNsenseCodec().render(intent)
        assert "<dhcpd>" in out
        assert "<lan>" in out
        assert "<from>10.0.0.100</from>" in out
        assert "<to>10.0.0.199</to>" in out
        assert "<gateway>10.0.0.1</gateway>" in out
        assert "<defaultleasetime>3600</defaultleasetime>" in out

    def test_round_trip(self):
        raw = """\
<opnsense>
<dhcpd>
<lan>
<range><from>10.0.0.100</from><to>10.0.0.199</to></range>
<gateway>10.0.0.1</gateway>
<defaultleasetime>3600</defaultleasetime>
</lan>
</dhcpd>
</opnsense>
"""
        c = OPNsenseCodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.dhcp_servers[0].gateway == second.dhcp_servers[0].gateway
        assert first.dhcp_servers[0].start_ip == second.dhcp_servers[0].start_ip
        assert first.dhcp_servers[0].end_ip == second.dhcp_servers[0].end_ip


# ---------------------------------------------------------------------------
# FortiGate
# ---------------------------------------------------------------------------


class TestFortiGateDHCPParseRender:
    def test_parse_pool_with_nested_ip_range(self):
        raw = """\
config system dhcp server
    edit 1
        set lease-time 604800
        set default-gateway 192.168.10.1
        set netmask 255.255.255.0
        set interface "port1"
        set dns-server1 192.168.10.4
        set dns-server2 8.8.8.8
        set domain "example.com"
        config ip-range
            edit 1
                set start-ip 192.168.10.100
                set end-ip 192.168.10.199
            next
        end
    next
end
"""
        intent = FortiGateCLICodec().parse(raw)
        p = intent.dhcp_servers[0]
        assert p.interface == "port1"
        assert p.gateway == "192.168.10.1"
        assert p.network == "192.168.10.0/24"
        assert p.dns_servers == ["192.168.10.4", "8.8.8.8"]
        assert p.domain_name == "example.com"
        assert p.start_ip == "192.168.10.100"
        assert p.end_ip == "192.168.10.199"
        assert p.lease_time == 604800

    def test_render_emits_nested_ip_range(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            dhcp_servers=[CanonicalDHCPPool(
                interface="port1",
                network="10.0.0.0/24",
                start_ip="10.0.0.100",
                end_ip="10.0.0.199",
                gateway="10.0.0.1",
                dns_servers=["1.1.1.1"],
                domain_name="corp.local",
                lease_time=3600,
            )],
        )
        out = FortiGateCLICodec().render(intent)
        assert "config system dhcp server" in out
        assert "set lease-time 3600" in out
        assert "set default-gateway 10.0.0.1" in out
        assert "set netmask 255.255.255.0" in out
        assert 'set interface "port1"' in out
        assert "set dns-server1 1.1.1.1" in out
        assert 'set domain "corp.local"' in out
        assert "config ip-range" in out
        assert "set start-ip 10.0.0.100" in out
        assert "set end-ip 10.0.0.199" in out

    def test_round_trip(self):
        raw = """\
config system dhcp server
    edit 1
        set lease-time 3600
        set default-gateway 10.0.0.1
        set netmask 255.255.255.0
        set interface "port1"
        config ip-range
            edit 1
                set start-ip 10.0.0.100
                set end-ip 10.0.0.199
            next
        end
    next
end
"""
        c = FortiGateCLICodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.dhcp_servers[0].gateway == second.dhcp_servers[0].gateway
        assert first.dhcp_servers[0].start_ip == second.dhcp_servers[0].start_ip
        assert first.dhcp_servers[0].end_ip == second.dhcp_servers[0].end_ip


# ---------------------------------------------------------------------------
# MikroTik
# ---------------------------------------------------------------------------


class TestMikroTikDHCPParseRender:
    def test_pool_and_network_merge_regardless_of_file_order(self):
        """/ip pool listed BEFORE /ip dhcp-server network — tests that
        the deferred-merge logic handles either section order.
        Without deferral, this input split one logical pool into two
        canonical records."""
        raw = """\
/ip pool
add name=dhcp_pool1 ranges=192.168.1.100-192.168.1.199

/ip dhcp-server network
add address=192.168.1.0/24 gateway=192.168.1.1 dns-server=1.1.1.1 domain=corp.local
"""
        intent = MikroTikRouterOSCodec().parse(raw)
        assert len(intent.dhcp_servers) == 1
        p = intent.dhcp_servers[0]
        assert p.network == "192.168.1.0/24"
        assert p.start_ip == "192.168.1.100"
        assert p.end_ip == "192.168.1.199"
        assert p.gateway == "192.168.1.1"

    def test_network_first_then_pool_also_merges(self):
        raw = """\
/ip dhcp-server network
add address=10.0.0.0/24 gateway=10.0.0.1

/ip pool
add name=dhcp_pool1 ranges=10.0.0.100-10.0.0.199
"""
        intent = MikroTikRouterOSCodec().parse(raw)
        assert len(intent.dhcp_servers) == 1
        assert intent.dhcp_servers[0].start_ip == "10.0.0.100"

    def test_render_emits_both_sections(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            dhcp_servers=[CanonicalDHCPPool(
                network="10.0.0.0/24",
                start_ip="10.0.0.100",
                end_ip="10.0.0.199",
                gateway="10.0.0.1",
                dns_servers=["1.1.1.1"],
                domain_name="corp.local",
            )],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "/ip pool" in out
        assert "ranges=10.0.0.100-10.0.0.199" in out
        assert "/ip dhcp-server network" in out
        assert "address=10.0.0.0/24" in out
        assert "gateway=10.0.0.1" in out

    def test_round_trip(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            dhcp_servers=[CanonicalDHCPPool(
                network="10.0.0.0/24",
                start_ip="10.0.0.100",
                end_ip="10.0.0.199",
                gateway="10.0.0.1",
            )],
        )
        c = MikroTikRouterOSCodec()
        re_parsed = c.parse(c.render(intent))
        assert re_parsed.dhcp_servers[0].network == "10.0.0.0/24"
        assert re_parsed.dhcp_servers[0].start_ip == "10.0.0.100"
        assert re_parsed.dhcp_servers[0].gateway == "10.0.0.1"


# ---------------------------------------------------------------------------
# Aruba AOS-S — DHCP server not supported; emits a comment block
# ---------------------------------------------------------------------------


class TestArubaDHCPRender:
    def test_dhcp_pool_emits_comment_not_silently_dropped(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            dhcp_servers=[CanonicalDHCPPool(
                network="10.0.0.0/24",
                gateway="10.0.0.1",
                start_ip="10.0.0.100",
                end_ip="10.0.0.199",
            )],
        )
        out = ArubaAOSSCodec().render(intent)
        # Human reviewer needs to see this can't translate.
        assert "; DHCP pools" in out
        assert "AOS-S" in out
        # Key facts preserved in the comment for the reviewer.
        assert "10.0.0.0/24" in out
        assert "10.0.0.1" in out

    def test_no_dhcp_pools_no_comment(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            dhcp_servers=[],
        )
        out = ArubaAOSSCodec().render(intent)
        assert "DHCP pools" not in out


# ---------------------------------------------------------------------------
# Cross-codec: Cisco -> OPNsense DHCP flow
# ---------------------------------------------------------------------------


class TestCiscoToOPNsenseDHCP:
    def test_dhcp_pool_survives_cross_vendor(self):
        raw = """\
ip dhcp pool USERS
 network 10.0.0.0 255.255.255.0
 default-router 10.0.0.1
 dns-server 10.0.0.4
 domain-name corp.local
 lease 1
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        out = OPNsenseCodec().render(intent)
        # OPNsense zone tag synthesised from empty interface field.
        assert "<dhcpd>" in out
        assert "<gateway>10.0.0.1</gateway>" in out
        assert "<domain>corp.local</domain>" in out
