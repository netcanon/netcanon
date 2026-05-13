"""
Unit tests for the ``CiscoIOSXECLICodec`` — R4 first CLI codec.

This is the codec that makes the translator work against real backup
data.  It parses ``show running-config`` text — the format the existing
Netmiko collectors already capture — into the same tree shape as the
NETCONF ``CiscoIOSXECodec``.

Direction: ``parse_only`` — render() raises RenderError.
Certainty: ``experimental`` — tested against synthetic samples here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.base import ParseError, RenderError
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.cisco_iosxe import CiscoIOSXECodec
from netcanon.migration.codecs._mock import MockCodec
from netcanon.models.migration import DeviceClass, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan

pytestmark = pytest.mark.unit


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "iosxe"


_MINIMAL_CLI = """\
!
interface GigabitEthernet0/0/0
 description test link
 ip address 10.0.0.1 255.255.255.0
 no shutdown
!
end
"""


# ---------------------------------------------------------------------------
# R3 field declarations
# ---------------------------------------------------------------------------


class TestR3Fields:
    def test_direction_is_bidirectional(self):
        # The codec was originally parse_only; render path was added
        # so an Aruba/Junos/etc. source can target Cisco IOS-XE CLI
        # text instead of NETCONF XML.  See render() for scope.
        assert CiscoIOSXECLICodec.direction == "bidirectional"

    def test_certainty_is_certified(self):
        # Certified on a two-domain corpus:
        #   * Router grammar: 3 BSD-3 real captures from
        #     nickrusso42518/racc (CSR1000v + Cat8000V on IOS-XE 16.9,
        #     17.3, 17.9 LTS — BGP/OSPF/EIGRP/IPsec/NAT/telemetry).
        #   * Switch grammar: 1 user-contributed real capture from a
        #     physical Cisco Catalyst 9300-24UX on IOS-XE 17.12
        #     (switchport trunk/access, 3 EtherChannels w/ LACP, 6
        #     VLANs, SVIs, Mgmt-vrf, CPP policy-maps, 28 privilege-
        #     delegation entries, 47 interfaces across Gi/TenG/
        #     FortyG/TwentyFiveG/AppG port families) — plus 1 CML
        #     virtual IOL (ioll2-xe) on 17.12 for spanning-tree cost
        #     grammar.
        # 11 fixtures total; all parse cleanly and produce populated
        # canonical trees.  parse_only direction means round-trip is
        # N/A.  See tests/fixtures/real/RESULTS.md.
        assert CiscoIOSXECLICodec.certainty == "certified"

    def test_canonical_model(self):
        assert CiscoIOSXECLICodec.canonical_model == "openconfig-lite"

    def test_input_format(self):
        assert CiscoIOSXECLICodec.input_format == "cli-ios"

    def test_vendor_id_matches_netconf_codec(self):
        """CLI and NETCONF codecs share the same vendor."""
        cli = CiscoIOSXECLICodec().capabilities.vendor_id
        net = CiscoIOSXECodec().capabilities.vendor_id
        assert cli == net == "cisco_iosxe"

    def test_device_classes_match_netconf_codec(self):
        cli = CiscoIOSXECLICodec().capabilities.device_classes
        net = CiscoIOSXECodec().capabilities.device_classes
        assert set(cli) == set(net)


# ---------------------------------------------------------------------------
# Parse — basic
# ---------------------------------------------------------------------------


class TestParseCLI:
    def test_minimal_cli(self):
        tree = CiscoIOSXECLICodec().parse(_MINIMAL_CLI)
        ifaces = tree.interfaces
        assert len(ifaces) == 1
        assert ifaces[0].name == "GigabitEthernet0/0/0"
        assert ifaces[0].description == "test link"
        assert ifaces[0].enabled is True

    def test_ip_address_parsed(self):
        tree = CiscoIOSXECLICodec().parse(_MINIMAL_CLI)
        addrs = tree.interfaces[0].ipv4_addresses
        assert addrs[0].ip == "10.0.0.1"
        assert addrs[0].prefix_length == 24

    def test_fixture_parses_four_interfaces(self):
        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        tree = CiscoIOSXECLICodec().parse(raw)
        ifaces = tree.interfaces
        assert len(ifaces) == 4
        names = [i.name for i in ifaces]
        assert names == [
            "GigabitEthernet0/0/0",
            "GigabitEthernet0/0/1",
            "Loopback0",
            "GigabitEthernet0/0/2",
        ]

    def test_shutdown_interface_has_enabled_false(self):
        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        tree = CiscoIOSXECLICodec().parse(raw)
        # GigabitEthernet0/0/2 has "shutdown"
        gi2 = tree.interfaces[3]
        assert gi2.name == "GigabitEthernet0/0/2"
        assert gi2.enabled is False

    def test_loopback_has_host_mask(self):
        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        tree = CiscoIOSXECLICodec().parse(raw)
        lo = tree.interfaces[2]
        assert lo.ipv4_addresses[0].prefix_length == 32

    def test_interface_type_inferred(self):
        tree = CiscoIOSXECLICodec().parse(_MINIMAL_CLI)
        assert tree.interfaces[0].interface_type == "ianaift:ethernetCsmacd"

    def test_loopback_type_inferred(self):
        raw = "interface Loopback99\n!\nend\n"
        tree = CiscoIOSXECLICodec().parse(raw)
        assert tree.interfaces[0].interface_type == "ianaift:softwareLoopback"


# ---------------------------------------------------------------------------
# SVI → VLAN synthesis (fix for Bug 1: silently-dropped SVI IPs)
# ---------------------------------------------------------------------------


class TestSVIVlanSynthesis:
    """`interface Vlan<N>` stanzas must produce both a
    :class:`CanonicalInterface` AND a :class:`CanonicalVlan` so VLAN-
    centric downstream codecs (Aruba AOS-S, OPNsense) don't silently
    drop the SVI's IP address.

    Regression fixture exercised: a real Cisco 9300 user config that
    rendered to Aruba with NO ``vlan`` stanzas when the bug was open.
    """

    def test_svi_with_ip_synthesises_vlan(self):
        raw = (
            "interface Vlan11\n"
            " ip address 192.168.11.252 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        assert len(tree.vlans) == 1
        vlan = tree.vlans[0]
        assert vlan.id == 11
        assert len(vlan.ipv4_addresses) == 1
        assert vlan.ipv4_addresses[0].ip == "192.168.11.252"
        assert vlan.ipv4_addresses[0].prefix_length == 24

    def test_svi_also_appears_as_interface(self):
        """The SVI interface record must also survive — it carries
        L3 interface metadata (MTU, description) the bare VLAN record
        doesn't model."""
        raw = (
            "interface Vlan11\n"
            " description Corp users\n"
            " ip address 192.168.11.252 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        names = [i.name for i in tree.interfaces]
        assert "Vlan11" in names

    def test_svi_no_ip_still_produces_vlan_record(self):
        """`interface Vlan1 / no ip address` asserts the VLAN exists
        even without L3 data.  The VLAN record must be preserved."""
        raw = (
            "interface Vlan1\n"
            " no ip address\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        ids = [v.id for v in tree.vlans]
        assert 1 in ids
        # No IPs attached.
        vlan = next(v for v in tree.vlans if v.id == 1)
        assert vlan.ipv4_addresses == []

    def test_svi_merges_with_top_level_vlan_stanza(self):
        """If both `vlan 11 / name Users` AND `interface Vlan11 /
        ip address ...` exist, the resulting VLAN record MUST keep
        the explicit name (it's the authoritative L2 tag) and gain
        the SVI's IP."""
        raw = (
            "vlan 11\n"
            " name Users\n"
            "!\n"
            "interface Vlan11\n"
            " ip address 192.168.11.252 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        vlan11 = next(v for v in tree.vlans if v.id == 11)
        assert vlan11.name == "Users"
        assert len(vlan11.ipv4_addresses) == 1
        assert vlan11.ipv4_addresses[0].ip == "192.168.11.252"

    def test_multiple_svis_all_synthesised(self):
        """User's reported regression: `interface Vlan1` + `interface
        Vlan11` both present.  Both must produce VLAN records."""
        raw = (
            "interface Vlan1\n"
            " no ip address\n"
            "!\n"
            "interface Vlan11\n"
            " ip address 192.168.11.252 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        ids = sorted(v.id for v in tree.vlans)
        assert ids == [1, 11]

    def test_svi_description_fills_name_when_no_stanza(self):
        """When no top-level `vlan N / name X` exists, the SVI's
        description is a reasonable fallback for the VLAN's name."""
        raw = (
            "interface Vlan11\n"
            " description Corporate users\n"
            " ip address 192.168.11.252 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        vlan = next(v for v in tree.vlans if v.id == 11)
        assert vlan.name == "Corporate users"

    def test_non_svi_interface_does_not_create_vlan(self):
        """Only interfaces whose name matches `Vlan<digits>` exactly
        should trigger synthesis.  GigabitEthernet0/0 must NOT create
        a phantom VLAN."""
        raw = (
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        assert tree.vlans == []

    def test_svi_ip_reaches_aruba_render(self):
        """End-to-end regression: the exact case from the user's
        real config."""
        from netcanon.migration.codecs.aruba_aoss import ArubaAOSSCodec
        raw = (
            'hostname "Switch"\n'
            "!\n"
            "interface Vlan1\n"
            " no ip address\n"
            "!\n"
            "interface Vlan11\n"
            " ip address 192.168.11.252 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        rendered = ArubaAOSSCodec().render(tree)
        assert "vlan 11" in rendered
        assert "ip address 192.168.11.252/24" in rendered


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------


class TestParseCLIErrors:
    def test_empty_input_raises(self):
        with pytest.raises(ParseError, match="empty input"):
            CiscoIOSXECLICodec().parse("")

    def test_xml_input_rejected(self):
        with pytest.raises(ParseError, match="looks like XML"):
            CiscoIOSXECLICodec().parse('<?xml version="1.0"?><data/>')

    def test_json_input_rejected(self):
        # Phase-3-R4.2: error message is now per-shape ("JSON" specifically,
        # not the older conjoined "XML or JSON" — the shared shape helper
        # distinguishes them).
        with pytest.raises(ParseError, match="looks like JSON"):
            CiscoIOSXECLICodec().parse('{"key": "value"}')

    def test_xml_with_leading_shell_echo_rejected(self):
        """Round-4.2 regression guard: the shared shape helper sees
        past leading shell-command-echo / banner framing lines that
        real captures often have prefixed.  Pre-R4.2 the inline
        ``stripped.startswith('<')`` check missed these and the parser
        silently returned an empty CanonicalIntent."""
        prefixed_xml = (
            "cat /conf/config.xml\r\r\r\n"
            '<?xml version="1.0"?>\r\r\n'
            "<opnsense><theme>opnsense</theme></opnsense>"
        )
        with pytest.raises(ParseError, match="looks like XML"):
            CiscoIOSXECLICodec().parse(prefixed_xml)

    def test_non_contiguous_mask_rejected(self):
        raw = "interface Gi0/0\n ip address 1.1.1.1 255.0.255.0\n!\n"
        with pytest.raises(ParseError, match="non-contiguous"):
            CiscoIOSXECLICodec().parse(raw)


# ---------------------------------------------------------------------------
# Render — emits IOS-XE running-config text
# ---------------------------------------------------------------------------


class TestRender:
    """The CLI render path emits IOS-XE-shape ``show running-config``
    text from any :class:`CanonicalIntent`.  Spot-check the major
    surfaces; full per-vendor cross-translation coverage lives in
    the cross-mesh smoke tier."""

    def test_render_rejects_non_canonical_input(self):
        with pytest.raises(RenderError, match="must be a CanonicalIntent"):
            CiscoIOSXECLICodec().render({})

    def test_render_emits_ios_banner_pair(self):
        intent = CiscoIOSXECLICodec().parse(
            "hostname sw1\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n!\n"
        )
        out = CiscoIOSXECLICodec().render(intent)
        # Both banners present so the round-tripped output detects
        # back to cisco_iosxe_cli with high confidence.
        assert "Building configuration..." in out
        assert "service timestamps" in out

    def test_render_emits_hostname_and_interface(self):
        intent = CiscoIOSXECLICodec().parse(
            "hostname r1\n"
            "interface GigabitEthernet0/0/0\n"
            " description uplink\n"
            " ip address 10.0.0.1 255.255.255.0\n"
            "!\n"
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "hostname r1" in out
        assert "interface GigabitEthernet0/0/0" in out
        assert " description uplink" in out
        assert " ip address 10.0.0.1 255.255.255.0" in out

    def test_render_emits_static_route_dotted_decimal(self):
        intent = CiscoIOSXECLICodec().parse(
            "ip route 192.168.0.0 255.255.255.0 10.0.0.1\n"
        )
        out = CiscoIOSXECLICodec().render(intent)
        # Render must use dotted-decimal masks (Cisco-native form),
        # NOT CIDR — even though the canonical tree stores prefix
        # length internally.
        assert "ip route 192.168.0.0 255.255.255.0 10.0.0.1" in out

    def test_render_emits_default_route_correctly(self):
        intent = CiscoIOSXECLICodec().parse(
            "ip default-gateway 10.0.0.1\n"
        )
        out = CiscoIOSXECLICodec().render(intent)
        # 0.0.0.0/0 → ``ip route 0.0.0.0 0.0.0.0 <gw>`` on render
        # (Cisco's classic default-route form; not the L2-switch
        # ``ip default-gateway`` form because the latter only works
        # on switches with no routing).
        assert "ip route 0.0.0.0 0.0.0.0 10.0.0.1" in out

    def test_render_emits_vlan_database_and_svi(self):
        intent = CiscoIOSXECLICodec().parse(
            "vlan 10\n name USERS\n!\n"
            "interface Vlan10\n ip address 10.0.10.1 255.255.255.0\n!\n"
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "vlan 10" in out
        assert " name USERS" in out
        assert "interface Vlan10" in out
        assert " ip address 10.0.10.1 255.255.255.0" in out

    def test_render_emits_snmp_community_block(self):
        intent = CiscoIOSXECLICodec().parse(
            "snmp-server community public RO\n"
            "snmp-server location HQ\n"
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "snmp-server community public RO" in out
        assert "snmp-server location HQ" in out

    def test_render_emits_snmpv3_user_with_priv_aes(self):
        intent = CiscoIOSXECLICodec().parse(
            "snmp-server user netadmin grp v3 "
            "auth sha SHApass priv aes 128 AESpass\n"
        )
        out = CiscoIOSXECLICodec().render(intent)
        # Cisco's wire form is the two-token ``aes 128`` not the
        # canonical-internal one-token ``aes128``.
        assert "snmp-server user netadmin grp v3 " in out
        assert "auth sha SHApass" in out
        assert "priv aes 128 AESpass" in out

    def test_render_emits_lag_member_channel_group(self):
        intent = CiscoIOSXECLICodec().parse(
            "interface Port-channel10\n description LAG\n!\n"
            "interface GigabitEthernet0/1\n channel-group 10 mode active\n!\n"
        )
        out = CiscoIOSXECLICodec().render(intent)
        assert "interface Port-channel10" in out
        assert "channel-group 10 mode active" in out

    def test_render_round_trip_stable_on_simple_config(self):
        """Parse → render → re-parse → equal.  The minimal
        round-trip invariant for a bidirectional codec.  Real-capture
        round-trip lives in test_real_captures.py."""
        raw = (
            "hostname r1\n!\n"
            "vlan 10\n name USERS\n!\n"
            "interface GigabitEthernet0/0\n"
            " description uplink\n"
            " ip address 10.0.0.1 255.255.255.0\n"
            "!\n"
            "ip route 0.0.0.0 0.0.0.0 10.0.0.254\n"
            "snmp-server community public RO\n"
        )
        codec = CiscoIOSXECLICodec()
        first = codec.parse(raw)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        # Field-by-field equality on the surfaces this test exercises.
        assert first.hostname == second.hostname
        assert [(v.id, v.name) for v in first.vlans] == \
               [(v.id, v.name) for v in second.vlans]
        assert [(i.name, i.description, [(a.ip, a.prefix_length)
                for a in i.ipv4_addresses])
                for i in first.interfaces] == \
               [(i.name, i.description, [(a.ip, a.prefix_length)
                for a in i.ipv4_addresses])
                for i in second.interfaces]
        assert [(r.destination, r.gateway) for r in first.static_routes] == \
               [(r.destination, r.gateway) for r in second.static_routes]
        assert (first.snmp.community if first.snmp else "") == \
               (second.snmp.community if second.snmp else "")


class TestRenderSynthesisesInterfacesFromVlanMembership:
    """Regression for the Aruba 2930M user-paste bug.

    When the source codec emits VLAN-centric port membership
    (Aruba AOS-S ``vlan N / untagged 1/1-1/47`` form, OPNsense
    ``<vlans>``-only) and there are NO explicit
    :class:`CanonicalInterface` entries in the parsed tree, the
    Cisco render path must synthesise interface stanzas from the
    VLAN membership lists.  Without synthesis Cisco render emitted
    only the VLAN-database lines + an SNMP block — the operator
    saw 0 interfaces despite the source carrying 52 ports.

    This is implemented via
    :func:`canonical.transforms.project_vlan_to_switchport` with
    ``synthesise_missing=True`` (default) called from the top of
    Cisco render.  Idempotent + safe on same-vendor round-trips
    where interfaces are already populated.
    """

    def test_synthesises_access_ports_from_vlan_untagged_list(self):
        from netcanon.migration.canonical.intent import (
            CanonicalIntent, CanonicalVlan,
        )
        intent = CanonicalIntent(hostname="sw")
        intent.vlans.append(CanonicalVlan(
            id=10, name="USERS",
            untagged_ports=["1/1", "1/2", "1/3"],
        ))
        out = CiscoIOSXECLICodec().render(intent)
        # Three ``interface ...`` stanzas should appear.
        assert out.count("\ninterface ") >= 3
        # Each port emits a switchport access vlan 10 line.
        assert out.count("switchport access vlan 10") == 3

    def test_synthesises_trunk_ports_from_vlan_tagged_list(self):
        from netcanon.migration.canonical.intent import (
            CanonicalIntent, CanonicalVlan,
        )
        intent = CanonicalIntent(hostname="sw")
        intent.vlans.append(CanonicalVlan(
            id=10, name="USERS",
            untagged_ports=["1/47"],
        ))
        intent.vlans.append(CanonicalVlan(
            id=20, name="VOICE",
            tagged_ports=["1/47"],
        ))
        out = CiscoIOSXECLICodec().render(intent)
        # Port 1/47 is in BOTH lists — should render as trunk with
        # native vlan 10 + allowed list including 20.
        assert "switchport mode trunk" in out
        assert "switchport trunk native vlan 10" in out
        assert "switchport trunk allowed vlan" in out and "20" in out

    def test_synthesis_idempotent_with_existing_interfaces(self):
        """Same-vendor round-trips already have CanonicalInterface
        entries; calling synthesis on them is a no-op (doesn't
        duplicate stanzas)."""
        raw = (
            "hostname r1\n!\n"
            "vlan 10\n name USERS\n!\n"
            "interface GigabitEthernet0/0\n"
            " switchport mode access\n"
            " switchport access vlan 10\n"
            "!\n"
        )
        codec = CiscoIOSXECLICodec()
        first = codec.parse(raw)
        rendered_a = codec.render(first)
        rendered_b = codec.render(first)
        # Render is deterministic + idempotent under repeated calls.
        assert rendered_a == rendered_b
        # Exactly one interface stanza, not duplicated.
        assert rendered_a.count("\ninterface GigabitEthernet0/0\n") == 1


class TestRenderPortIdentitySubslotLetter:
    """Regression for the Aruba 1/A1 → Cisco GigabitEthernet1/0/1
    collision.

    Aruba AOS-S encodes uplink-module ports as ``1/A1``, ``1/A2``,
    etc. (letter subslot).  Cisco IOS-XE encodes the equivalent as
    ``<switch>/<module>/<port>`` with module=1+ for line-card /
    uplink-module ports.  Letter A→module=1, B→module=2, etc.
    Letter slots are also typically 10G+ → prefix promotes to
    ``TenGigabitEthernet`` when no explicit speed hint is set.

    Without the subslot_letter handling, ``1/A1`` collapsed to
    ``GigabitEthernet1/0/1`` — same as Aruba's chassis port ``1/1``.
    The rename mesh then flagged 8 collisions across the chassis
    vs uplink ports of a 2930M+JL083A stack.
    """

    def test_aruba_letter_slot_maps_to_cisco_module_1(self):
        from netcanon.migration.codecs.aruba_aoss.port_names import (
            classify_port_name as a_classify,
        )
        from netcanon.migration.codecs.cisco_iosxe_cli.port_names import (
            format_port_identity as c_format,
        )
        # 1/A1, 1/A2, 1/A3, 1/A4 should each get a UNIQUE Cisco
        # name distinct from chassis 1/1, 1/2, 1/3, 1/4.
        chassis_names = {c_format(a_classify(f"1/{n}")) for n in (1, 2, 3, 4)}
        letter_names = {
            c_format(a_classify(f"1/A{n}")) for n in (1, 2, 3, 4)
        }
        assert chassis_names.isdisjoint(letter_names), (
            f"Aruba letter-slot ports collide with chassis ports: "
            f"chassis={chassis_names!r} letter={letter_names!r}"
        )
        # All 8 names are distinct (no within-set collisions either).
        assert len(chassis_names | letter_names) == 8

    def test_letter_a_promotes_to_tengigabitethernet(self):
        """Letter slots are typically SFP+ uplinks; prefix should
        bump to TenGigabitEthernet when no explicit speed hint is
        set on the canonical PortIdentity."""
        from netcanon.migration.codecs.aruba_aoss.port_names import (
            classify_port_name as a_classify,
        )
        from netcanon.migration.codecs.cisco_iosxe_cli.port_names import (
            format_port_identity as c_format,
        )
        out = c_format(a_classify("1/A1"))
        assert out == "TenGigabitEthernet1/1/1", (
            f"expected TenGigabitEthernet1/1/1, got {out!r}"
        )

    def test_letter_b_maps_to_module_2(self):
        """Module-bay B (e.g. on modular 5400 chassis) should map to
        Cisco module=2."""
        from netcanon.migration.canonical.port_names import PortIdentity
        from netcanon.migration.codecs.cisco_iosxe_cli.port_names import (
            format_port_identity as c_format,
        )
        ident = PortIdentity(
            kind="physical", stack=1, port=24, subslot_letter="B",
        )
        out = c_format(ident)
        assert "/2/24" in out, (
            f"module bay B should map to Cisco module=2; got {out!r}"
        )


# ---------------------------------------------------------------------------
# Tree shape compatibility with the NETCONF codec
# ---------------------------------------------------------------------------


class TestTreeShapeCompatibility:
    """The CLI codec's tree must be identical in shape to the NETCONF
    codec's tree — that's what makes them interchangeable as sources."""

    def test_cli_tree_validates_against_netconf_caps(self):
        """Parse CLI → validate against the NETCONF codec's capability
        matrix.  The interface-subtree xpaths land in ``supported``;
        the system / vlans / snmp xpaths land in ``unsupported`` (the
        NETCONF codec's render is a Phase 0.5 stub — see Wave 10γ-2).
        The validation severity is ``block`` because the NETCONF
        target honestly declares those un-rendered surfaces as
        unsupported, but the interfaces still classify cleanly."""
        from netcanon.services.migration_validate import validate_against

        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        cli_codec = CiscoIOSXECLICodec()
        net_codec = CiscoIOSXECodec()
        tree = cli_codec.parse(raw)
        report = validate_against(tree, net_codec, source=cli_codec)
        # Interface-subtree paths classify cleanly; non-interface
        # surfaces (hostname, vlans, snmp, static-routes) classify as
        # unsupported per the honest matrix.
        assert len(report.supported_paths) >= 4
        # The walker emits /interfaces/interface/name + per-interface
        # config xpaths — all supported.
        assert any(
            "/interfaces/interface" in p for p in report.supported_paths
        )


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


class TestPipelineWithCLICodec:
    def test_cli_to_netconf_plan_succeeds(self):
        """CLI (source) → NETCONF (target): the translate pipeline
        runs to a terminal state because both codecs share the
        canonical tree shape.  The fixture carries hostname / VLANs /
        SNMP / etc. that the NETCONF render drops (Phase 0.5 stub),
        so the matrix's honest unsupported declarations (Wave 10γ-2)
        flip the validation severity to ``block`` and the job to
        ``partial``.  The interface subtree is still emitted in the
        rendered XML."""
        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        cli = CiscoIOSXECLICodec()
        net = CiscoIOSXECodec()
        job = run_plan(cli, net, raw)
        assert job.status is MigrationJobStatus.partial
        assert job.validation is not None
        assert job.validation.severity == "block"
        assert job.rendered is not None
        # Rendered output is OpenConfig XML (from the NETCONF renderer).
        assert "<interfaces" in job.rendered
        assert "GigabitEthernet0/0/0" in job.rendered

    def test_cli_as_target_succeeds_with_cli_render(self):
        """The CLI codec is now bidirectional; using it as a TARGET
        produces IOS-XE running-config text instead of NETCONF XML.
        Was previously expected to fail with ``parse-only`` error;
        now expected to complete with CLI output.

        Uses ``cisco_iosxe_cli`` for both source and target so the
        canonical tree is genuinely a CanonicalIntent (the mock
        codec returns a plain dict that the CLI render correctly
        rejects).  Aruba → Cisco IOS-XE CLI is the real-world
        cross-vendor case this codec was promoted to enable."""
        raw = "hostname r1\n!\ninterface GigabitEthernet0/0\n ip address 10.0.0.1 255.255.255.0\n!\n"
        cli = CiscoIOSXECLICodec()
        job = run_plan(cli, cli, raw)
        assert job.status is MigrationJobStatus.completed
        assert job.rendered is not None
        assert "Building configuration..." in job.rendered
        assert "hostname r1" in job.rendered
        assert "interface GigabitEthernet0/0" in job.rendered


# ---------------------------------------------------------------------------
# Bug 4 — ip default-gateway
# ---------------------------------------------------------------------------


class TestDefaultGatewayParse:
    """Cisco L2 switches use ``ip default-gateway X`` instead of
    ``ip route 0.0.0.0 0.0.0.0 X``.  Ensure the parser picks it up and
    maps it to a CanonicalStaticRoute(0.0.0.0/0, X)."""

    def test_default_gateway_parsed_as_default_route(self):
        raw = "hostname sw1\nip default-gateway 192.168.11.1\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        assert len(intent.static_routes) == 1
        r = intent.static_routes[0]
        assert r.destination == "0.0.0.0/0"
        assert r.gateway == "192.168.11.1"
        assert r.interface == ""

    def test_default_gateway_and_explicit_ip_route_coexist(self):
        raw = (
            "ip default-gateway 192.168.11.1\n"
            "ip route 10.20.0.0 255.255.0.0 10.0.0.1\n"
        )
        intent = CiscoIOSXECLICodec().parse(raw)
        dests = {r.destination: r for r in intent.static_routes}
        assert dests["0.0.0.0/0"].gateway == "192.168.11.1"
        assert dests["10.20.0.0/16"].gateway == "10.0.0.1"

    def test_default_gateway_survives_aruba_round_trip(self):
        """Cisco parse -> Aruba render should re-emit the native
        ``ip default-gateway`` form (Aruba's renderer collapses
        0.0.0.0/0 routes back to that syntax)."""
        from netcanon.migration.codecs.aruba_aoss import ArubaAOSSCodec
        raw = "hostname sw1\nip default-gateway 192.168.11.1\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        aruba_out = ArubaAOSSCodec().render(intent)
        assert "ip default-gateway 192.168.11.1" in aruba_out

    def test_default_gateway_case_insensitive(self):
        raw = "IP DEFAULT-GATEWAY 10.0.0.254\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        assert intent.static_routes[0].gateway == "10.0.0.254"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_cli_codec_in_registry(self):
        from netcanon.migration.codecs.registry import list_codecs
        import netcanon.migration  # side-effect
        assert "cisco_iosxe_cli" in list_codecs()

    def test_two_codecs_for_same_vendor(self):
        """cisco_iosxe and cisco_iosxe_cli both registered — first
        multi-codec-per-vendor case."""
        from netcanon.migration.codecs.registry import list_codecs
        codecs = list_codecs()
        assert "cisco_iosxe" in codecs
        assert "cisco_iosxe_cli" in codecs
