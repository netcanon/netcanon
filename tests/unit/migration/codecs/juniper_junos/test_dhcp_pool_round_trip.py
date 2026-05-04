"""DHCP-server parse + render symmetry for the juniper_junos codec.

Cluster E.1-B addition.  Junos has two DHCP server grammars:

* ``set system services dhcp`` (legacy; deprecated on M / MX / SRX
  from the early-2010s, still works on EX 4.x trains).
* ``set system services dhcp-local-server`` + ``set access
  address-assignment pool`` (modern stack-based form, supported on
  every current LTS Junos 22.x train).

The codec emits the modern form; the parser accepts BOTH so old
captures still produce :class:`CanonicalDHCPPool` records.  Mapping:

* ``set access address-assignment pool <P> family inet network <N>``
  — :attr:`CanonicalDHCPPool.network`
* ``... family inet range <R> low|high <ip>`` —
  :attr:`CanonicalDHCPPool.start_ip` / :attr:`end_ip`
* ``... family inet dhcp-attributes router <ip>`` —
  :attr:`gateway`
* ``... family inet dhcp-attributes name-server <ip>`` —
  :attr:`dns_servers`
* ``... family inet dhcp-attributes maximum-lease-time <sec>`` —
  :attr:`lease_time`
* ``... family inet dhcp-attributes domain-name "<name>"`` —
  :attr:`domain_name`
* ``set system services dhcp-local-server group <G> interface
  <iface>`` — :attr:`interface` (matched to the pool by the same
  emit-time naming scheme on render).

Junos doc reference (modern form):
* "Configuring Address-Assignment Pools" (Junos OS Network Management)
  https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/topic-map/dhcp-address-assignment-pool.html
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
)
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.juniper_junos import JunosCodec
from netconfig.migration.codecs.juniper_junos.parse import parse_intent
from netconfig.migration.codecs.juniper_junos.render import render_intent

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Parse — modern form (`access address-assignment pool` + `dhcp-local-server`)
# ---------------------------------------------------------------------------


class TestJunosDHCPParseModernForm:
    def test_parse_basic_pool_network_range_gateway(self) -> None:
        raw = """\
set access address-assignment pool MY_POOL family inet network 192.168.10.0/24
set access address-assignment pool MY_POOL family inet range MY_RANGE low 192.168.10.100
set access address-assignment pool MY_POOL family inet range MY_RANGE high 192.168.10.200
set access address-assignment pool MY_POOL family inet dhcp-attributes router 192.168.10.1
set system services dhcp-local-server group MY_GROUP interface ge-0/0/1.0
"""
        intent = parse_intent(raw)
        assert len(intent.dhcp_servers) == 1
        p = intent.dhcp_servers[0]
        assert p.network == "192.168.10.0/24"
        assert p.start_ip == "192.168.10.100"
        assert p.end_ip == "192.168.10.200"
        assert p.gateway == "192.168.10.1"
        assert p.interface == "ge-0/0/1.0"

    def test_parse_lease_time_and_domain(self) -> None:
        raw = """\
set access address-assignment pool POOL_A family inet network 10.0.0.0/24
set access address-assignment pool POOL_A family inet dhcp-attributes maximum-lease-time 86400
set access address-assignment pool POOL_A family inet dhcp-attributes domain-name "example.com"
"""
        intent = parse_intent(raw)
        assert len(intent.dhcp_servers) == 1
        p = intent.dhcp_servers[0]
        assert p.lease_time == 86400
        assert p.domain_name == "example.com"

    def test_parse_multiple_dns_servers(self) -> None:
        raw = """\
set access address-assignment pool POOL_A family inet network 10.0.0.0/24
set access address-assignment pool POOL_A family inet dhcp-attributes name-server 8.8.8.8
set access address-assignment pool POOL_A family inet dhcp-attributes name-server 1.1.1.1
"""
        intent = parse_intent(raw)
        assert len(intent.dhcp_servers) == 1
        p = intent.dhcp_servers[0]
        assert p.dns_servers == ["8.8.8.8", "1.1.1.1"]

    def test_parse_multiple_pools(self) -> None:
        raw = """\
set access address-assignment pool A family inet network 10.0.0.0/24
set access address-assignment pool A family inet dhcp-attributes router 10.0.0.1
set access address-assignment pool B family inet network 10.0.1.0/24
set access address-assignment pool B family inet dhcp-attributes router 10.0.1.1
"""
        intent = parse_intent(raw)
        networks = sorted(p.network for p in intent.dhcp_servers)
        assert networks == ["10.0.0.0/24", "10.0.1.0/24"]

    def test_pool_without_dhcp_local_server_group_still_parses(self) -> None:
        """Pool body alone is enough — the group binding only adds
        the interface field; missing it should leave interface empty
        rather than dropping the whole pool."""
        raw = """\
set access address-assignment pool ORPHAN family inet network 10.0.0.0/24
set access address-assignment pool ORPHAN family inet dhcp-attributes router 10.0.0.1
"""
        intent = parse_intent(raw)
        assert len(intent.dhcp_servers) == 1
        assert intent.dhcp_servers[0].interface == ""


# ---------------------------------------------------------------------------
# Parse — legacy form (`system services dhcp`)
# ---------------------------------------------------------------------------


class TestJunosDHCPParseLegacyForm:
    def test_parse_legacy_pool_network_range_gateway(self) -> None:
        """Older EX 4.x train: ``system services dhcp`` grammar.  The
        parser accepts it for fixture compatibility — render always
        emits the modern form."""
        raw = """\
set system services dhcp pool 192.168.20.0/24 address-range low 192.168.20.100
set system services dhcp pool 192.168.20.0/24 address-range high 192.168.20.200
set system services dhcp pool 192.168.20.0/24 router 192.168.20.1
set system services dhcp pool 192.168.20.0/24 name-server 8.8.8.8
set system services dhcp pool 192.168.20.0/24 maximum-lease-time 7200
set system services dhcp pool 192.168.20.0/24 domain-name "legacy.example.net"
"""
        intent = parse_intent(raw)
        assert len(intent.dhcp_servers) == 1
        p = intent.dhcp_servers[0]
        assert p.network == "192.168.20.0/24"
        assert p.start_ip == "192.168.20.100"
        assert p.end_ip == "192.168.20.200"
        assert p.gateway == "192.168.20.1"
        assert p.dns_servers == ["8.8.8.8"]
        assert p.lease_time == 7200
        assert p.domain_name == "legacy.example.net"


# ---------------------------------------------------------------------------
# Render — emits modern form
# ---------------------------------------------------------------------------


class TestJunosDHCPRender:
    def test_render_emits_modern_address_assignment_pool(self) -> None:
        intent = CanonicalIntent(
            source_vendor="test",
            source_format="test",
            dhcp_servers=[CanonicalDHCPPool(
                interface="ge-0/0/1.0",
                network="192.168.10.0/24",
                start_ip="192.168.10.100",
                end_ip="192.168.10.200",
                gateway="192.168.10.1",
                dns_servers=["8.8.8.8", "1.1.1.1"],
                lease_time=86400,
                domain_name="example.com",
            )],
        )
        out = render_intent(intent)
        # Modern grammar: address-assignment pool body
        assert "set access address-assignment pool" in out
        assert "family inet network 192.168.10.0/24" in out
        assert "family inet range" in out
        assert "low 192.168.10.100" in out
        assert "high 192.168.10.200" in out
        assert "dhcp-attributes router 192.168.10.1" in out
        assert "dhcp-attributes name-server 8.8.8.8" in out
        assert "dhcp-attributes name-server 1.1.1.1" in out
        assert "dhcp-attributes maximum-lease-time 86400" in out
        assert 'dhcp-attributes domain-name "example.com"' in out
        # And the dhcp-local-server group binding
        assert "set system services dhcp-local-server group" in out
        assert "interface ge-0/0/1.0" in out

    def test_render_skips_dhcp_local_server_when_no_interface(self) -> None:
        """When the canonical pool has no interface, only the
        address-assignment pool block emits.  The dhcp-local-server
        group binding requires a known interface."""
        intent = CanonicalIntent(
            source_vendor="test",
            source_format="test",
            dhcp_servers=[CanonicalDHCPPool(
                network="10.0.0.0/24",
                gateway="10.0.0.1",
            )],
        )
        out = render_intent(intent)
        assert "set access address-assignment pool" in out
        assert "set system services dhcp-local-server" not in out

    def test_render_no_dhcp_servers_no_block(self) -> None:
        """No pools -> no DHCP-related output."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
        )
        out = render_intent(intent)
        assert "address-assignment" not in out
        assert "dhcp-local-server" not in out

    def test_render_uses_stable_pool_name_from_interface(self) -> None:
        """When a canonical interface is present, the synthesised pool
        + group names derive from it deterministically (so two renders
        produce byte-identical output).  Without an interface, fall
        back to ``pool0`` / ``pool1`` based on list position."""
        intent = CanonicalIntent(
            source_vendor="test",
            source_format="test",
            dhcp_servers=[
                CanonicalDHCPPool(
                    interface="ge-0/0/1.0",
                    network="10.0.0.0/24",
                    gateway="10.0.0.1",
                ),
                CanonicalDHCPPool(
                    network="10.0.1.0/24",
                    gateway="10.0.1.1",
                ),
            ],
        )
        out_a = render_intent(intent)
        out_b = render_intent(intent)
        assert out_a == out_b
        # Pool 1 derives a name from its interface; pool 2 falls back
        # to the enumerated form.
        assert "pool1" in out_a or "pool0" in out_a


# ---------------------------------------------------------------------------
# Round-trip — same-vendor parse(render(parse(raw))) preservation
# ---------------------------------------------------------------------------


class TestJunosDHCPRoundTrip:
    def test_round_trip_preserves_all_fields(self) -> None:
        original = CanonicalDHCPPool(
            interface="ge-0/0/1.0",
            network="192.168.10.0/24",
            start_ip="192.168.10.100",
            end_ip="192.168.10.200",
            gateway="192.168.10.1",
            dns_servers=["8.8.8.8", "1.1.1.1"],
            lease_time=86400,
            domain_name="example.com",
        )
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            dhcp_servers=[original],
        )
        rendered = render_intent(intent)
        re_parsed = parse_intent(rendered)
        assert len(re_parsed.dhcp_servers) == 1
        rt = re_parsed.dhcp_servers[0]
        assert rt.network == original.network
        assert rt.start_ip == original.start_ip
        assert rt.end_ip == original.end_ip
        assert rt.gateway == original.gateway
        assert rt.dns_servers == original.dns_servers
        assert rt.lease_time == original.lease_time
        assert rt.domain_name == original.domain_name
        assert rt.interface == original.interface

    def test_render_render_byte_identical(self) -> None:
        """render(parse(render(intent))) is byte-identical to
        render(intent) — second render has nothing left to change."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            dhcp_servers=[CanonicalDHCPPool(
                interface="ge-0/0/1.0",
                network="10.0.0.0/24",
                start_ip="10.0.0.100",
                end_ip="10.0.0.200",
                gateway="10.0.0.1",
                dns_servers=["1.1.1.1"],
                lease_time=3600,
                domain_name="corp.local",
            )],
        )
        first = render_intent(intent)
        second = render_intent(parse_intent(first))
        assert first == second


# ---------------------------------------------------------------------------
# Cross-vendor: cisco_iosxe_cli source -> juniper_junos render
# ---------------------------------------------------------------------------


class TestCiscoToJunosDHCP:
    def test_cisco_source_dhcp_pool_renders_into_junos(self) -> None:
        raw = """\
ip dhcp pool USERS
 network 10.0.0.0 255.255.255.0
 default-router 10.0.0.1
 dns-server 10.0.0.4 8.8.8.8
 domain-name corp.local
 lease 1
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        out = JunosCodec().render(intent)
        # Modern form, all key fields preserved
        assert "set access address-assignment pool" in out
        assert "family inet network 10.0.0.0/24" in out
        assert "dhcp-attributes router 10.0.0.1" in out
        assert "dhcp-attributes name-server 10.0.0.4" in out
        assert "dhcp-attributes name-server 8.8.8.8" in out
        assert 'dhcp-attributes domain-name "corp.local"' in out
        # Cisco "lease 1" = 1 day = 86400 seconds.
        assert "dhcp-attributes maximum-lease-time 86400" in out

    def test_cross_vendor_round_trip_preserves_pool(self) -> None:
        """cisco -> junos render -> junos parse: every CanonicalDHCPPool
        field that the cisco parser populated survives into the junos
        re-parsed canonical."""
        raw = """\
ip dhcp pool USERS
 network 10.0.0.0 255.255.255.0
 default-router 10.0.0.1
 dns-server 10.0.0.4
 domain-name corp.local
 lease 7
!
"""
        cisco_intent = CiscoIOSXECLICodec().parse(raw)
        junos_text = JunosCodec().render(cisco_intent)
        junos_intent = JunosCodec().parse(junos_text)
        assert len(junos_intent.dhcp_servers) == 1
        p = junos_intent.dhcp_servers[0]
        assert p.network == "10.0.0.0/24"
        assert p.gateway == "10.0.0.1"
        assert p.dns_servers == ["10.0.0.4"]
        assert p.domain_name == "corp.local"
        assert p.lease_time == 7 * 86400
