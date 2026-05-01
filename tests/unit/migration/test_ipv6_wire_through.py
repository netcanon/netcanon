"""
Unit tests for per-interface IPv6 address wire-through (GAP-EVPN-3).

Schema: ``CanonicalIPv6Address`` (ip + prefix_length + scope) +
``CanonicalInterface.ipv6_addresses``.  Mirrors the existing
``CanonicalIPv4Address`` shape with the added scope discriminator
(``"global"`` / ``"link-local"``) since IPv6's link-local block is
keyword-tagged on Cisco / Arista (``ipv6 address X link-local``)
and prefix-inferred elsewhere (Junos / MikroTik / OPNsense / FortiGate).

Vendors covered (parse + render):
    * arista_eos          (``ipv6 address X/Y [link-local]``)
    * cisco_iosxe_cli     (same syntax as arista_eos)
    * cisco_iosxe          (NETCONF ``ipv6/addresses/address`` element)
    * aruba_aoss           (``ipv6 address X/Y [link-local]``)
    * juniper_junos        (``set interfaces N unit M family inet6
                            address X/Y``)
    * fortigate_cli        (``set ip6-address X/Y``; placeholder
                            ``::/0`` filtered)
    * mikrotik_routeros    (``/ipv6 address ; add address=X/Y
                            interface=Z``)
    * opnsense             (``<ipaddrv6>X</ipaddrv6><subnetv6>N</subnetv6>``;
                            ``dhcp6``/``track6`` placeholders filtered)

The cross-vendor flow at the bottom proves the canonical bridge
end-to-end on a representative source/target pair.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalInterface,
    CanonicalIntent,
    CanonicalIPv6Address,
)
from netconfig.migration.codecs.arista_eos import AristaEOSCodec
from netconfig.migration.codecs.aruba_aoss import ArubaAOSSCodec
from netconfig.migration.codecs.cisco_iosxe import CiscoIOSXECodec
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec
from netconfig.migration.codecs.juniper_junos import JunosCodec
from netconfig.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netconfig.migration.codecs.opnsense import OPNsenseCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_global_default(self):
        a = CanonicalIPv6Address(ip="2001:db8::1", prefix_length=64)
        assert a.scope == "global"

    def test_link_local_explicit(self):
        a = CanonicalIPv6Address(
            ip="fe80::1", prefix_length=64, scope="link-local",
        )
        assert a.scope == "link-local"

    def test_prefix_range(self):
        with pytest.raises(Exception):
            CanonicalIPv6Address(ip="2001:db8::1", prefix_length=129)


# ---------------------------------------------------------------------------
# Arista EOS
# ---------------------------------------------------------------------------


class TestAristaIPv6:
    def test_parse_global(self):
        raw = (
            "interface Ethernet1\n"
            "   ipv6 address 2001:db8::1/64\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        v6s = intent.interfaces[0].ipv6_addresses
        assert len(v6s) == 1
        assert v6s[0].ip == "2001:db8::1"
        assert v6s[0].prefix_length == 64
        assert v6s[0].scope == "global"

    def test_parse_link_local(self):
        raw = (
            "interface Ethernet1\n"
            "   ipv6 address fe80::1/64 link-local\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        v6 = intent.interfaces[0].ipv6_addresses[0]
        assert v6.scope == "link-local"
        assert v6.ip == "fe80::1"

    def test_render_global(self):
        intent = CanonicalIntent(interfaces=[CanonicalInterface(
            name="Ethernet1",
            ipv6_addresses=[
                CanonicalIPv6Address(ip="2001:db8::1", prefix_length=64),
            ],
        )])
        out = AristaEOSCodec().render(intent)
        assert "ipv6 address 2001:db8::1/64" in out
        assert "link-local" not in out

    def test_render_link_local(self):
        intent = CanonicalIntent(interfaces=[CanonicalInterface(
            name="Ethernet1",
            ipv6_addresses=[
                CanonicalIPv6Address(
                    ip="fe80::1", prefix_length=64, scope="link-local",
                ),
            ],
        )])
        out = AristaEOSCodec().render(intent)
        assert "ipv6 address fe80::1/64 link-local" in out

    def test_round_trip(self):
        c = AristaEOSCodec()
        raw = (
            "interface Ethernet1\n"
            "   no switchport\n"
            "   ipv6 address 2001:db8::1/64\n"
            "   ipv6 address fe80::1/64 link-local\n"
            "!\n"
        )
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.interfaces[0].ipv6_addresses == \
               second.interfaces[0].ipv6_addresses


# ---------------------------------------------------------------------------
# Cisco IOS-XE CLI (same grammar as Arista)
# ---------------------------------------------------------------------------


class TestCiscoIOSXECLIIPv6:
    def test_parse_global(self):
        raw = (
            "interface GigabitEthernet1\n"
            " ipv6 address 2001:db8::1/64\n"
            "!\n"
        )
        intent = CiscoIOSXECLICodec().parse(raw)
        v6 = intent.interfaces[0].ipv6_addresses[0]
        assert v6.ip == "2001:db8::1"
        assert v6.prefix_length == 64
        assert v6.scope == "global"

    def test_parse_link_local_keyword(self):
        raw = (
            "interface GigabitEthernet1\n"
            " ipv6 address fe80::1 link-local\n"
            "!\n"
        )
        intent = CiscoIOSXECLICodec().parse(raw)
        v6 = intent.interfaces[0].ipv6_addresses[0]
        assert v6.scope == "link-local"
        # IOS-XE accepts a bare link-local address with no /N — we
        # store the canonical /64 default.
        assert v6.prefix_length == 64

    def test_render_round_trip(self):
        c = CiscoIOSXECLICodec()
        raw = (
            "interface GigabitEthernet1\n"
            " ipv6 address 2001:db8::1/64\n"
            " ipv6 address fe80::1/64 link-local\n"
            "!\n"
        )
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.interfaces[0].ipv6_addresses == \
               second.interfaces[0].ipv6_addresses

    def test_real_capture_carrier_interface(self):
        """ntc_carrier_interfaces.txt has `ipv6 address FE80:A8::2DA::1689/126`
        (note the malformed double-colon — real-fixture noise).  The
        codec should silently skip it without crashing."""
        raw = (
            "interface GigabitEthernet1\n"
            " ipv6 address FE80:A8::2DA::1689/126\n"
            "!\n"
        )
        # Should not raise; address may or may not parse depending on
        # canonical validation, but the codec must not throw.
        intent = CiscoIOSXECLICodec().parse(raw)
        # Canonical pydantic model doesn't validate v6 syntax, so
        # the address gets through; the assertion is about robustness.
        assert intent.interfaces[0].name == "GigabitEthernet1"


# ---------------------------------------------------------------------------
# Cisco IOS-XE NETCONF (OpenConfig)
# ---------------------------------------------------------------------------


class TestCiscoNETCONFIPv6:
    def test_parse_render_round_trip(self):
        raw = (
            '<interfaces xmlns="http://openconfig.net/yang/interfaces">\n'
            "  <interface>\n"
            "    <name>Gi0/0/0</name>\n"
            "    <config><name>Gi0/0/0</name><enabled>true</enabled></config>\n"
            "    <subinterfaces>\n"
            "      <subinterface>\n"
            "        <index>0</index>\n"
            '        <ipv6 xmlns="http://openconfig.net/yang/interfaces/ip">\n'
            "          <addresses><address>\n"
            "            <ip>2001:db8::1</ip>\n"
            "            <config><ip>2001:db8::1</ip>"
            "<prefix-length>64</prefix-length></config>\n"
            "          </address></addresses>\n"
            "        </ipv6>\n"
            "      </subinterface>\n"
            "    </subinterfaces>\n"
            "  </interface>\n"
            "</interfaces>\n"
        )
        c = CiscoIOSXECodec()
        first = c.parse(raw)
        v6 = first.interfaces[0].ipv6_addresses[0]
        assert v6.ip == "2001:db8::1"
        assert v6.prefix_length == 64
        out = c.render(first)
        assert "<oc-ip:ipv6>" in out or "ipv6" in out.lower()
        assert "2001:db8::1" in out


# ---------------------------------------------------------------------------
# Aruba AOS-S
# ---------------------------------------------------------------------------


class TestArubaIPv6:
    def test_parse_global(self):
        raw = (
            "interface 1\n"
            "   routing\n"
            "   ipv6 address 2001:db8::1/64\n"
            "   exit\n"
        )
        intent = ArubaAOSSCodec().parse(raw)
        v6 = intent.interfaces[0].ipv6_addresses[0]
        assert v6.ip == "2001:db8::1"
        assert v6.prefix_length == 64

    def test_parse_link_local(self):
        raw = (
            "interface 1\n"
            "   routing\n"
            "   ipv6 address fe80::1/64 link-local\n"
            "   exit\n"
        )
        intent = ArubaAOSSCodec().parse(raw)
        v6 = intent.interfaces[0].ipv6_addresses[0]
        assert v6.scope == "link-local"

    def test_dhcp_full_filtered(self):
        """`ipv6 address dhcp full` is the stateless-DHCPv6 form
        which carries no static address; parse-and-ignore."""
        raw = (
            "interface 1\n"
            "   routing\n"
            "   ipv6 address dhcp full\n"
            "   exit\n"
        )
        intent = ArubaAOSSCodec().parse(raw)
        assert intent.interfaces[0].ipv6_addresses == []

    def test_render(self):
        intent = CanonicalIntent(interfaces=[CanonicalInterface(
            name="1",
            ipv6_addresses=[
                CanonicalIPv6Address(ip="2001:db8::1", prefix_length=64),
            ],
        )])
        out = ArubaAOSSCodec().render(intent)
        assert "ipv6 address 2001:db8::1/64" in out


# ---------------------------------------------------------------------------
# Juniper Junos
# ---------------------------------------------------------------------------


class TestJunosIPv6:
    def test_parse_global(self):
        raw = (
            "set interfaces em0 unit 0 family inet6 address 2001:db8::1/64\n"
        )
        intent = JunosCodec().parse(raw)
        v6 = intent.interfaces[0].ipv6_addresses[0]
        assert v6.ip == "2001:db8::1"
        assert v6.prefix_length == 64
        assert v6.scope == "global"

    def test_parse_link_local_inferred(self):
        """Junos doesn't keyword-tag link-local; we infer from
        the fe80::/10 prefix at materialisation time."""
        raw = "set interfaces em0 unit 0 family inet6 address fe80::1/64\n"
        intent = JunosCodec().parse(raw)
        assert intent.interfaces[0].ipv6_addresses[0].scope == "link-local"

    def test_parse_loopback_v6(self):
        """Real fixture pattern: lo0 carries a /128 v6 address."""
        raw = (
            "set interfaces lo0 unit 0 family inet6 address "
            "2001:db8:293:1::fd/128\n"
        )
        intent = JunosCodec().parse(raw)
        v6 = intent.interfaces[0].ipv6_addresses[0]
        assert v6.prefix_length == 128
        assert v6.scope == "global"

    def test_render(self):
        intent = CanonicalIntent(interfaces=[CanonicalInterface(
            name="em0",
            ipv6_addresses=[
                CanonicalIPv6Address(ip="2001:db8::1", prefix_length=64),
            ],
        )])
        out = JunosCodec().render(intent)
        assert (
            "set interfaces em0 unit 0 family inet6 address 2001:db8::1/64"
            in out
        )

    def test_round_trip(self):
        c = JunosCodec()
        raw = (
            "set interfaces em0 unit 0 family inet6 address 2001:db8::1/64\n"
            "set interfaces em0 unit 0 family inet6 address fe80::1/64\n"
        )
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.interfaces[0].ipv6_addresses == \
               second.interfaces[0].ipv6_addresses


# ---------------------------------------------------------------------------
# FortiGate CLI
# ---------------------------------------------------------------------------


class TestFortiGateIPv6:
    def test_parse(self):
        raw = (
            "config system interface\n"
            '    edit "port1"\n'
            "        set ip6-address 2001:db8::1/64\n"
            "    next\n"
            "end\n"
        )
        intent = FortiGateCLICodec().parse(raw)
        v6 = intent.interfaces[0].ipv6_addresses[0]
        assert v6.ip == "2001:db8::1"
        assert v6.prefix_length == 64

    def test_placeholder_filtered(self):
        """FortiOS writes `set ip6-address ::/0` on every interface
        as the no-IPv6-address default; canonical filters."""
        raw = (
            "config system interface\n"
            '    edit "port1"\n'
            "        set ip6-address ::/0\n"
            "    next\n"
            "end\n"
        )
        intent = FortiGateCLICodec().parse(raw)
        assert intent.interfaces[0].ipv6_addresses == []

    def test_render(self):
        intent = CanonicalIntent(interfaces=[CanonicalInterface(
            name="port1",
            ipv6_addresses=[
                CanonicalIPv6Address(ip="2001:db8::1", prefix_length=64),
            ],
        )])
        out = FortiGateCLICodec().render(intent)
        assert "set ip6-address 2001:db8::1/64" in out

    def test_round_trip(self):
        c = FortiGateCLICodec()
        raw = (
            "config system interface\n"
            '    edit "port1"\n'
            "        set ip6-address 2001:db8::1/64\n"
            "        set status up\n"
            "    next\n"
            "end\n"
        )
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.interfaces[0].ipv6_addresses == \
               second.interfaces[0].ipv6_addresses


# ---------------------------------------------------------------------------
# MikroTik RouterOS
# ---------------------------------------------------------------------------


class TestMikroTikIPv6:
    def test_parse(self):
        raw = (
            "/ipv6 address\n"
            "add address=2001:db8::1/64 interface=ether1\n"
        )
        intent = MikroTikRouterOSCodec().parse(raw)
        # Find the interface that carries the address.
        ether = next(i for i in intent.interfaces if i.name == "ether1")
        assert ether.ipv6_addresses[0].ip == "2001:db8::1"
        assert ether.ipv6_addresses[0].scope == "global"

    def test_link_local_inferred(self):
        raw = (
            "/ipv6 address\n"
            "add address=fe80::1/64 interface=ether1\n"
        )
        intent = MikroTikRouterOSCodec().parse(raw)
        ether = next(i for i in intent.interfaces if i.name == "ether1")
        assert ether.ipv6_addresses[0].scope == "link-local"

    def test_render(self):
        intent = CanonicalIntent(interfaces=[CanonicalInterface(
            name="ether1",
            interface_type="ianaift:ethernetCsmacd",
            default_name="ether1",
            ipv6_addresses=[
                CanonicalIPv6Address(ip="2001:db8::1", prefix_length=64),
            ],
        )])
        out = MikroTikRouterOSCodec().render(intent)
        assert "/ipv6 address" in out
        assert "add address=2001:db8::1/64 interface=ether1" in out


# ---------------------------------------------------------------------------
# OPNsense
# ---------------------------------------------------------------------------


class TestOPNsenseIPv6:
    def test_parse(self):
        raw = (
            '<?xml version="1.0"?>\n'
            "<opnsense>\n"
            "  <interfaces>\n"
            "    <wan>\n"
            "      <if>em0</if>\n"
            "      <enable>1</enable>\n"
            "      <ipaddrv6>2001:db8::1</ipaddrv6>\n"
            "      <subnetv6>64</subnetv6>\n"
            "    </wan>\n"
            "  </interfaces>\n"
            "</opnsense>\n"
        )
        intent = OPNsenseCodec().parse(raw)
        v6 = intent.interfaces[0].ipv6_addresses[0]
        assert v6.ip == "2001:db8::1"
        assert v6.prefix_length == 64

    def test_dhcp6_filtered(self):
        """Real OPNsense XMLs carry `<ipaddrv6>dhcp6</ipaddrv6>` and
        `<ipaddrv6>idassoc6</ipaddrv6>` as keyword markers — filtered
        from canonical because they don't represent static addresses."""
        raw = (
            '<?xml version="1.0"?>\n'
            "<opnsense>\n"
            "  <interfaces>\n"
            "    <wan>\n"
            "      <if>em0</if>\n"
            "      <enable>1</enable>\n"
            "      <ipaddrv6>dhcp6</ipaddrv6>\n"
            "    </wan>\n"
            "  </interfaces>\n"
            "</opnsense>\n"
        )
        intent = OPNsenseCodec().parse(raw)
        assert intent.interfaces[0].ipv6_addresses == []

    def test_round_trip(self):
        c = OPNsenseCodec()
        raw = (
            '<?xml version="1.0"?>\n'
            "<opnsense>\n"
            "  <interfaces>\n"
            "    <wan>\n"
            "      <if>em0</if>\n"
            "      <enable>1</enable>\n"
            "      <ipaddrv6>2001:db8::1</ipaddrv6>\n"
            "      <subnetv6>64</subnetv6>\n"
            "    </wan>\n"
            "  </interfaces>\n"
            "</opnsense>\n"
        )
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.interfaces[0].ipv6_addresses == \
               second.interfaces[0].ipv6_addresses


# ---------------------------------------------------------------------------
# Cross-vendor: end-to-end through the canonical bridge
# ---------------------------------------------------------------------------


class TestCrossVendorIPv6:
    """One representative source/target pair per direction-class proves
    the canonical bridge works end-to-end.  Cross-mesh smoke matrix
    coverage lives in test_cross_mesh_overrides."""

    def test_arista_to_junos(self):
        raw = (
            "interface Ethernet1\n"
            "   no switchport\n"
            "   ipv6 address 2001:db8::1/64\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        out = JunosCodec().render(intent)
        assert (
            "set interfaces Ethernet1 unit 0 family inet6 address "
            "2001:db8::1/64"
        ) in out

    def test_cisco_to_fortigate(self):
        raw = (
            "interface GigabitEthernet1\n"
            " ipv6 address 2001:db8::1/64\n"
            "!\n"
        )
        intent = CiscoIOSXECLICodec().parse(raw)
        out = FortiGateCLICodec().render(intent)
        assert "set ip6-address 2001:db8::1/64" in out

    def test_mikrotik_to_arista(self):
        raw = (
            "/ipv6 address\n"
            "add address=2001:db8::1/64 interface=ether1\n"
        )
        intent = MikroTikRouterOSCodec().parse(raw)
        out = AristaEOSCodec().render(intent)
        assert "ipv6 address 2001:db8::1/64" in out


# ---------------------------------------------------------------------------
# Karneliuk EOS 4.26 fixture: the regression that surfaced GAP-EVPN-3.
# ---------------------------------------------------------------------------


class TestKarneliukRegression:
    """The karneliuk_a_eos1_eos4260.txt fixture has
    `ipv6 address fc00:192:168:100::62/64` on Management1.  Before
    GAP-EVPN-3 this line was silently dropped on parse; now it
    survives the round-trip."""

    def test_management1_v6_preserved(self):
        from pathlib import Path
        fix = (
            Path("tests/fixtures/real/arista_eos") /
            "karneliuk_a_eos1_eos4260.txt"
        )
        raw = fix.read_text()
        intent = AristaEOSCodec().parse(raw)
        mgmt = next(
            i for i in intent.interfaces if i.name == "Management1"
        )
        assert any(
            a.ip == "fc00:192:168:100::62" and a.prefix_length == 64
            for a in mgmt.ipv6_addresses
        )
