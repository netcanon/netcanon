"""
Unit tests for the IPv6 dhcp_client_v6 + tunnel_type schema additions.

Both fields were added during the validation cleanup wave to close
gaps that were originally flagged as deferred:

* ``CanonicalInterface.dhcp_client_v6`` — IPv6 DHCPv6 / SLAAC mode
  string.  Empty = static / unset; one of
  ``"dhcp6"|"slaac"|"track6"|"6rd"|"6to4"``.  Replaces the OPNsense
  parser's previous parse-and-log-and-skip behaviour for
  ``<ipaddrv6>{dhcp6|slaac|track6|6rd|6to4}</ipaddrv6>`` (see
  ``tests/fixtures/real/user_smoke_findings.md`` IPv6 SLAAC flag).

* ``CanonicalInterface.tunnel_type`` — tunnel encapsulation
  discriminator.  Empty = unset (renderers fall back to GRE);
  one of ``"gre"|"eoip"|"ipip"|"ipsec"|"vxlan"``.  Replaces the
  MikroTik render's "always GRE" fallback so EoIP / IPIP cross-
  vendor migrations preserve the encap choice.

Coverage per codec (parse + render symmetry where the codec wires
both directions):

    * cisco_iosxe_cli   — ``ipv6 address dhcp/autoconfig``;
                          ``tunnel mode gre|ipip|ipsec|vxlan``.
    * arista_eos        — same as cisco_iosxe_cli.
    * juniper_junos     — ``family inet6 dhcpv6-client``;
                          tunnel_type from ``gr-`` / ``ip-`` /
                          ``st0`` name prefix.
    * mikrotik_routeros — ``/interface gre|eoip|ipip`` discriminator.
    * fortigate_cli     — ``set ip6-mode dhcp``.
    * opnsense          — ``<ipaddrv6>{dhcp6|slaac|track6|6rd|6to4}``.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalInterface,
    CanonicalIntent,
)
from netcanon.migration.codecs.arista_eos import AristaEOSCodec
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.fortigate_cli import FortiGateCLICodec
from netcanon.migration.codecs.juniper_junos import JunosCodec
from netcanon.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netcanon.migration.codecs.opnsense import OPNsenseCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_dhcp_client_v6_default_empty(self):
        iface = CanonicalInterface(name="Ethernet1")
        assert iface.dhcp_client_v6 == ""

    def test_dhcp_client_v6_accepts_documented_values(self):
        for value in ("dhcp6", "slaac", "track6", "6rd", "6to4"):
            iface = CanonicalInterface(name="x", dhcp_client_v6=value)
            assert iface.dhcp_client_v6 == value

    def test_tunnel_type_default_empty(self):
        iface = CanonicalInterface(name="Tunnel0")
        assert iface.tunnel_type == ""

    def test_tunnel_type_accepts_documented_values(self):
        for value in ("gre", "eoip", "ipip", "ipsec", "vxlan"):
            iface = CanonicalInterface(name="x", tunnel_type=value)
            assert iface.tunnel_type == value

    def test_round_trip_through_pydantic(self):
        # Field survives model_dump / model_validate with no data loss.
        iface = CanonicalInterface(
            name="Tunnel0",
            interface_type="ianaift:tunnel",
            dhcp_client_v6="dhcp6",
            tunnel_type="ipsec",
        )
        dumped = iface.model_dump()
        restored = CanonicalInterface.model_validate(dumped)
        assert restored.dhcp_client_v6 == "dhcp6"
        assert restored.tunnel_type == "ipsec"


# ---------------------------------------------------------------------------
# OPNsense — original flag from user_smoke_findings.md (IPv6 SLAAC)
# ---------------------------------------------------------------------------


class TestOpnsenseDhcpV6:
    @pytest.mark.parametrize("keyword", [
        "dhcp6", "slaac", "track6", "6rd", "6to4",
    ])
    def test_parse_populates_dhcp_client_v6(self, keyword):
        raw = f"""<?xml version="1.0"?>
<opnsense>
  <interfaces>
    <wan>
      <if>igc0</if>
      <ipaddrv6>{keyword}</ipaddrv6>
    </wan>
  </interfaces>
</opnsense>
"""
        intent = OPNsenseCodec().parse(raw)
        iface = intent.interfaces[0]
        assert iface.dhcp_client_v6 == keyword
        # Static IPv6 list stays empty — keyword is dynamic, not a literal.
        assert iface.ipv6_addresses == []

    def test_render_emits_keyword(self):
        intent = CanonicalIntent(
            source_vendor="opnsense",
            source_format="xml-opnsense",
            interfaces=[
                CanonicalInterface(name="wan", dhcp_client_v6="slaac"),
            ],
        )
        out = OPNsenseCodec().render(intent)
        assert "<ipaddrv6>slaac</ipaddrv6>" in out

    def test_round_trip_dhcp6(self):
        # parse(render(intent)) preserves dhcp_client_v6.
        intent = CanonicalIntent(
            source_vendor="opnsense",
            source_format="xml-opnsense",
            interfaces=[
                CanonicalInterface(name="wan", dhcp_client_v6="dhcp6"),
            ],
        )
        out = OPNsenseCodec().render(intent)
        re_parsed = OPNsenseCodec().parse(out)
        assert re_parsed.interfaces[0].dhcp_client_v6 == "dhcp6"


# ---------------------------------------------------------------------------
# Cisco IOS-XE CLI
# ---------------------------------------------------------------------------


class TestCiscoIosxeCliDhcpV6:
    def test_parse_dhcp(self):
        raw = (
            "interface GigabitEthernet0/0\n"
            " ipv6 address dhcp\n"
            "!\n"
        )
        intent = CiscoIOSXECLICodec().parse(raw)
        assert intent.interfaces[0].dhcp_client_v6 == "dhcp6"

    def test_parse_autoconfig(self):
        raw = (
            "interface GigabitEthernet0/0\n"
            " ipv6 address autoconfig\n"
            "!\n"
        )
        intent = CiscoIOSXECLICodec().parse(raw)
        assert intent.interfaces[0].dhcp_client_v6 == "slaac"

    def test_render_dhcp(self):
        intent = CanonicalIntent(
            source_vendor="cisco_iosxe_cli",
            interfaces=[
                CanonicalInterface(
                    name="GigabitEthernet0/0", dhcp_client_v6="dhcp6",
                ),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "ipv6 address dhcp" in out

    def test_render_autoconfig(self):
        intent = CanonicalIntent(
            source_vendor="cisco_iosxe_cli",
            interfaces=[
                CanonicalInterface(
                    name="GigabitEthernet0/0", dhcp_client_v6="slaac",
                ),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "ipv6 address autoconfig" in out


class TestCiscoIosxeCliTunnelType:
    @pytest.mark.parametrize("mode_in,canonical_out", [
        ("gre ip", "gre"),
        ("ipip", "ipip"),
        ("ipsec ipv4", "ipsec"),
        ("vxlan", "vxlan"),
        ("ipv6ip", "ipip"),  # ipv6-over-ipv4 collapses to ipip
    ])
    def test_parse(self, mode_in, canonical_out):
        raw = (
            "interface Tunnel0\n"
            f" tunnel mode {mode_in}\n"
            "!\n"
        )
        intent = CiscoIOSXECLICodec().parse(raw)
        assert intent.interfaces[0].tunnel_type == canonical_out

    def test_render(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="Tunnel0",
                    interface_type="ianaift:tunnel",
                    tunnel_type="ipip",
                ),
            ],
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "tunnel mode ipip" in out


# ---------------------------------------------------------------------------
# Arista EOS
# ---------------------------------------------------------------------------


class TestAristaEosDhcpV6:
    def test_parse_dhcp(self):
        raw = (
            "interface Ethernet1\n"
            "   ipv6 address dhcp\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert intent.interfaces[0].dhcp_client_v6 == "dhcp6"

    def test_parse_autoconfig(self):
        raw = (
            "interface Ethernet1\n"
            "   ipv6 address autoconfig\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert intent.interfaces[0].dhcp_client_v6 == "slaac"

    def test_render_dhcp(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="Ethernet1", dhcp_client_v6="dhcp6",
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "ipv6 address dhcp" in out


class TestAristaEosTunnelType:
    def test_parse_gre(self):
        raw = (
            "interface Tunnel0\n"
            "   tunnel mode gre\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert intent.interfaces[0].tunnel_type == "gre"

    def test_render_ipip(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="Tunnel0",
                    interface_type="ianaift:tunnel",
                    tunnel_type="ipip",
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "tunnel mode ipip" in out


# ---------------------------------------------------------------------------
# MikroTik RouterOS — tunnel_type discriminator (the headline use case)
# ---------------------------------------------------------------------------


class TestMikroTikTunnelType:
    @pytest.mark.parametrize("section,kind", [
        ("/interface gre", "gre"),
        ("/interface eoip", "eoip"),
        ("/interface ipip", "ipip"),
    ])
    def test_parse(self, section, kind):
        raw = (
            f"{section}\n"
            "add name=tun1 remote-address=10.0.0.1\n"
        )
        intent = MikroTikRouterOSCodec().parse(raw)
        assert len(intent.interfaces) == 1
        assert intent.interfaces[0].tunnel_type == kind
        assert intent.interfaces[0].interface_type == "ianaift:tunnel"

    @pytest.mark.parametrize("kind,expected_section", [
        ("gre", "/interface gre"),
        ("eoip", "/interface eoip"),
        ("ipip", "/interface ipip"),
    ])
    def test_render_picks_right_section(self, kind, expected_section):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="tun1",
                    interface_type="ianaift:tunnel",
                    tunnel_type=kind,
                ),
            ],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert expected_section in out
        # And the placeholder remote-address sentinel is preserved.
        assert "remote-address=0.0.0.0" in out

    def test_render_empty_falls_back_to_gre(self):
        # Empty tunnel_type → still emits under /interface gre (the
        # historical default).  This preserves backwards compat for
        # codecs that haven't been wired yet.
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="tun1",
                    interface_type="ianaift:tunnel",
                ),
            ],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "/interface gre" in out

    def test_round_trip_eoip(self):
        intent_in = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="tun1",
                    interface_type="ianaift:tunnel",
                    tunnel_type="eoip",
                ),
            ],
        )
        out = MikroTikRouterOSCodec().render(intent_in)
        intent_out = MikroTikRouterOSCodec().parse(out)
        assert intent_out.interfaces[0].tunnel_type == "eoip"


# ---------------------------------------------------------------------------
# Junos
# ---------------------------------------------------------------------------


class TestJunosDhcpV6:
    def test_parse_dhcpv6_client(self):
        raw = (
            "set interfaces ge-0/0/0 unit 0 family inet6 dhcpv6-client\n"
        )
        intent = JunosCodec().parse(raw)
        # Find the parent interface (unit 0 collapses).
        ifaces = [i for i in intent.interfaces if i.name == "ge-0/0/0"]
        assert ifaces
        assert ifaces[0].dhcp_client_v6 == "dhcp6"

    def test_render_emits_dhcpv6_client(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ge-0/0/0", dhcp_client_v6="dhcp6",
                ),
            ],
        )
        out = JunosCodec().render(intent)
        assert "family inet6 dhcpv6-client" in out


class TestJunosTunnelType:
    @pytest.mark.parametrize("name,expected", [
        ("gr-0/0/0", "gre"),
        ("ip-0/0/1", "ipip"),
        ("st0.0", "ipsec"),
        ("ge-0/0/0", ""),  # Non-tunnel name → empty.
    ])
    def test_infer_from_name(self, name, expected):
        # The parse pulls tunnel_type from name prefix automatically.
        raw = f"set interfaces {name} description test\n"
        intent = JunosCodec().parse(raw)
        ifaces = [i for i in intent.interfaces if i.name in (name, name.split(".")[0])]
        assert ifaces
        assert ifaces[0].tunnel_type == expected


# ---------------------------------------------------------------------------
# FortiGate
# ---------------------------------------------------------------------------


class TestFortiGateDhcpV6:
    def test_parse_ip6_mode_dhcp(self):
        raw = (
            "config system interface\n"
            '    edit "wan1"\n'
            "        set ip6-mode dhcp\n"
            "    next\n"
            "end\n"
        )
        intent = FortiGateCLICodec().parse(raw)
        ifaces = [i for i in intent.interfaces if i.name == "wan1"]
        assert ifaces
        assert ifaces[0].dhcp_client_v6 == "dhcp6"

    def test_render_emits_ip6_mode_dhcp(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="wan1", dhcp_client_v6="dhcp6",
                ),
            ],
        )
        out = FortiGateCLICodec().render(intent)
        assert "set ip6-mode dhcp" in out


# ---------------------------------------------------------------------------
# Cross-vendor — preservation across the canonical bridge
# ---------------------------------------------------------------------------


class TestCrossVendorPreservation:
    def test_opnsense_to_cisco_iosxe_cli_dhcp6(self):
        """OPNsense ``<ipaddrv6>dhcp6</ipaddrv6>`` → IOS-XE
        ``ipv6 address dhcp`` end-to-end."""
        opn_xml = """<?xml version="1.0"?>
<opnsense>
  <interfaces>
    <wan>
      <if>igc0</if>
      <ipaddrv6>dhcp6</ipaddrv6>
    </wan>
  </interfaces>
</opnsense>
"""
        intent = OPNsenseCodec().parse(opn_xml)
        out = CiscoIOSXECLICodec().render(intent)
        assert "ipv6 address dhcp" in out

    def test_opnsense_to_routeros_dhcp6_drops_with_lossy_marker(self):
        """OPNsense ``<ipaddrv6>dhcp6</ipaddrv6>`` is declared lossy
        on RouterOS render (``/ipv6 dhcp-client`` lives in a
        separate top-level section).  Field is preserved on the
        canonical intent — operators see the loss in the validation
        report rather than via silent drop."""
        opn_xml = """<?xml version="1.0"?>
<opnsense>
  <interfaces>
    <wan>
      <if>igc0</if>
      <ipaddrv6>dhcp6</ipaddrv6>
    </wan>
  </interfaces>
</opnsense>
"""
        intent = OPNsenseCodec().parse(opn_xml)
        # Canonical preservation: dhcp_client_v6 survived parse.
        assert intent.interfaces[0].dhcp_client_v6 == "dhcp6"
        # Render to RouterOS — the lossy marker means the field
        # doesn't surface in /interface ethernet stanzas; the
        # CapabilityMatrix's lossy declaration drives the
        # validation banner instead.
        out = MikroTikRouterOSCodec().render(intent)
        # Render must not raise.
        assert isinstance(out, str)
