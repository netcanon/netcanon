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
<interfaces><lan><if>em0</if></lan></interfaces>
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
        # The device the zone `lan` is assigned to.  This line read
        # "lan" while the parser put the zone's NAME in a field that
        # holds a port name, and the text had no <interfaces>: a pool
        # whose zone has no device is left out of the tree now
        # (test_a_zone_with_no_device_is_left_out, below).
        assert p.interface == "em0"
        assert p.start_ip == "192.168.1.100"
        assert p.end_ip == "192.168.1.199"
        assert p.gateway == "192.168.1.1"
        assert p.dns_servers == ["1.1.1.1", "8.8.8.8"]
        assert p.domain_name == "example.com"
        assert p.lease_time == 7200

    def test_a_zone_with_no_device_is_left_out(self):
        """A pool keyed by a zone <interfaces> does not have has no
        interface to be on: it is not in the tree, and the tree says
        which zone."""
        raw = """\
<opnsense>
<dhcpd>
<lan>
<enable/>
<range><from>192.168.1.100</from><to>192.168.1.199</to></range>
</lan>
</dhcpd>
</opnsense>
"""
        intent = OPNsenseCodec().parse(raw)
        assert intent.dhcp_servers == []
        assert intent.dropped_tier3_sections == [
            "<dhcpd><lan>: no <lan> in <interfaces>, so its DHCP pool has no interface",
        ]

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
<interfaces><lan><if>em0</if></lan></interfaces>
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
        assert first.dhcp_servers[0].interface == second.dhcp_servers[0].interface == "em0"
        assert first.dhcp_servers[0].gateway == second.dhcp_servers[0].gateway
        assert first.dhcp_servers[0].start_ip == second.dhcp_servers[0].start_ip
        assert first.dhcp_servers[0].end_ip == second.dhcp_servers[0].end_ip


class TestAnOPNsensePoolServesItsZonesSubnet:
    """A zone states no network of its own: its DHCP server hands out
    addresses of the subnet its interface is on.  The pool carries
    that subnet, so a target that writes a pool's network writes it.
    Before, the pool had none, and an IOS-XE pool with no `network`
    line hands out nothing."""

    _RAW = """\
<opnsense>
<interfaces>
<wan><if>em0</if><ipaddr>dhcp</ipaddr></wan>
<lan><if>em1</if><enable/><ipaddr>192.168.1.1</ipaddr><subnet>24</subnet></lan>
<opt1><if>em2</if><enable/><ipaddr>10.20.30.1</ipaddr><subnet>26</subnet></opt1>
</interfaces>
<dhcpd>
<lan>
<enable/>
<range><from>192.168.1.100</from><to>192.168.1.199</to></range>
<gateway>192.168.1.1</gateway>
</lan>
<opt1>
<enable/>
<range><from>10.20.30.10</from><to>10.20.30.20</to></range>
</opt1>
<wan>
<enable/>
<domain>wan.example</domain>
</wan>
</dhcpd>
</opnsense>
"""

    def _pools(self, intent):
        return {pool.interface: pool for pool in intent.dhcp_servers}

    def test_each_pool_has_the_subnet_of_its_zones_address(self):
        pools = self._pools(OPNsenseCodec().parse(self._RAW))
        assert pools["em1"].network == "192.168.1.0/24"
        assert pools["em2"].network == "10.20.30.0/26"

    def test_a_zone_with_no_static_address_gives_no_network(self):
        pools = self._pools(OPNsenseCodec().parse(self._RAW))
        assert pools["em0"].network == ""

    def test_the_network_survives_a_round_trip(self):
        codec = OPNsenseCodec()
        first = codec.parse(self._RAW)
        second = codec.parse(codec.render(first))
        assert [(p.interface, p.network) for p in first.dhcp_servers] == [
            (p.interface, p.network) for p in second.dhcp_servers
        ]

    def test_an_ios_xe_output_serves_the_range(self):
        from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
        from netcanon.services.migration_pipeline import run_plan

        target = CiscoIOSXECLICodec()
        result = run_plan(OPNsenseCodec(), target, self._RAW, force=True)
        out = result.rendered or ""
        assert " network 192.168.1.0 255.255.255.0" in out
        assert " network 10.20.30.0 255.255.255.192" in out
        assert "has no network" not in out
        back = {
            pool.network: (pool.start_ip, pool.end_ip)
            for pool in target.parse(out).dhcp_servers
        }
        assert back["192.168.1.0/24"] == ("192.168.1.100", "192.168.1.199")
        assert back["10.20.30.0/26"] == ("10.20.30.10", "10.20.30.20")

    def test_a_junos_output_states_the_network(self):
        from netcanon.migration.codecs.juniper_junos import JunosCodec
        from netcanon.services.migration_pipeline import run_plan

        result = run_plan(OPNsenseCodec(), JunosCodec(), self._RAW, force=True)
        lines = (result.rendered or "").splitlines()
        assert any(line.endswith(" network 192.168.1.0/24") for line in lines)
        assert any(line.endswith(" network 10.20.30.0/26") for line in lines)


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
