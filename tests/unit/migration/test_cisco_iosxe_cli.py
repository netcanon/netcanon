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


class TestLocalUserPasswordRoundTrip:
    """Regression for the ``password 0 X`` round-trip bug.

    The IOS-XE encoding-type prefix on a ``username … {secret|password}
    <N> X`` line drives how the device interprets ``X``:

      * ``0`` — plaintext (device hashes on commit)
      * ``5`` — md5crypt
      * ``7`` — Cisco's reversible XOR (legacy)
      * ``8`` — PBKDF2-SHA256
      * ``9`` — scrypt

    The canonical model stores types 5/7/8/9 as ``"<digit> <hash>"``
    so the render side can reconstruct the original wire form.  Type
    ``0`` (plaintext) has no canonical tag — the parser strips the
    ``0 `` prefix so the value sits in the same slot as a bare
    plaintext literal, and the render emits ``secret 0 X`` whenever
    plaintext needs to cross the wire.

    Without the parse-side strip, the canonical value carried a
    leading ``0 `` that the render path re-prefixed under a fresh
    ``secret 0 ``, producing ``secret 0 0 X``.  Re-parsing then
    captured the second ``0`` as a hash-type marker, breaking
    parse↔render symmetry on the very next iteration.
    """

    def _round_trip(self, line: str) -> tuple[str, str]:
        """Parse ``line``, render, re-parse, return both hash values."""
        codec = CiscoIOSXECLICodec()
        first = codec.parse(line + "\n")
        rendered = codec.render(first)
        second = codec.parse(rendered)
        return (
            first.local_users[0].hashed_password,
            second.local_users[0].hashed_password,
        )

    def test_password_zero_plaintext_strips_prefix_on_parse(self):
        codec = CiscoIOSXECLICodec()
        intent = codec.parse(
            "username cisco privilege 15 password 0 cisco\n"
        )
        # Type-0 prefix is plaintext-marker — canonical form drops it
        # so the value matches a bare plaintext literal exactly.
        assert intent.local_users[0].hashed_password == "cisco"

    def test_password_zero_round_trips_through_secret_zero(self):
        first, second = self._round_trip(
            "username cisco privilege 15 password 0 cisco"
        )
        # Idempotent: parse → render → re-parse gives the same value.
        assert first == "cisco"
        assert second == "cisco"

    def test_password_zero_render_emits_secret_zero_form(self):
        """The render path normalises ``password`` to ``secret`` (the
        IOS-XE-preferred keyword) and re-emits the explicit ``0``
        encoding-type marker — never a doubled ``0 0 X``."""
        codec = CiscoIOSXECLICodec()
        intent = codec.parse(
            "username cisco privilege 15 password 0 cisco\n"
        )
        rendered = codec.render(intent)
        username_lines = [
            line for line in rendered.splitlines()
            if line.startswith("username cisco")
        ]
        assert username_lines == [
            "username cisco privilege 15 secret 0 cisco",
        ]

    def test_secret_zero_round_trips_through_secret_zero(self):
        """Explicit ``secret 0 X`` is the documented plaintext form —
        must round-trip identically to ``password 0 X``."""
        first, second = self._round_trip(
            "username admin privilege 15 secret 0 hunter2"
        )
        assert first == "hunter2"
        assert second == "hunter2"

    def test_password_seven_reversible_preserves_prefix(self):
        """Type-7 (reversible XOR) is a real hash — canonical form
        preserves the ``7 `` prefix so render can reconstruct it."""
        first, second = self._round_trip(
            "username legacy privilege 15 password 7 091C08"
        )
        assert first == "7 091C08"
        assert second == "7 091C08"

    def test_secret_five_md5crypt_preserves_prefix(self):
        """Type-5 (md5crypt) — canonical form preserves ``5 $1$…``."""
        first, second = self._round_trip(
            "username admin privilege 15 "
            "secret 5 $1$abcd$xyzhashpayloadexample123"
        )
        assert first == "5 $1$abcd$xyzhashpayloadexample123"
        assert second == "5 $1$abcd$xyzhashpayloadexample123"

    def test_secret_nine_scrypt_preserves_prefix(self):
        """Type-9 (scrypt) — canonical form preserves ``9 $9$…``."""
        first, second = self._round_trip(
            "username admin privilege 15 "
            "secret 9 $9$fakeSalt$fakeHashExampleValue1"
        )
        assert first == "9 $9$fakeSalt$fakeHashExampleValue1"
        assert second == "9 $9$fakeSalt$fakeHashExampleValue1"

    def test_secret_with_no_type_marker_round_trips_as_plaintext(self):
        """``secret X`` with no leading digit is plaintext too — the
        device hashes on commit.  Render normalises to ``secret 0 X``
        (the explicit plaintext form)."""
        first, second = self._round_trip(
            "username admin privilege 15 secret hunter2"
        )
        assert first == "hunter2"
        assert second == "hunter2"


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


# ---------------------------------------------------------------------------
# Wave B — classic VRRP grammar (single-line per-attribute form)
# ---------------------------------------------------------------------------


class TestVRRPGroups:
    """IOS-XE classic VRRP grammar (``vrrp <VRID> <sub-cmd>``).

    The classic single-line per-attribute form is the broadly-supported
    surface across every IOS-XE release from 15.x onward, and is the
    form real captures emit (see ``tests/fixtures/real/cisco_iosxe/
    batfish_iosxe_basic_vrrp.txt``).  Modern 17.12+ address-family
    form is declared lossy on the capability matrix — covered by the
    final test below.
    """

    def _basic_vrrp_config(self, extra_lines: str = "") -> str:
        """Helper: minimal interface stanza with a VRRP group and
        optional extra sub-commands."""
        return (
            "interface GigabitEthernet0/2\n"
            " ip address 192.168.1.1 255.255.255.0\n"
            " vrrp 12 ip 192.168.1.254\n"
            + extra_lines
            + "!\n"
        )

    def test_basic_vrrp_ip_parses(self):
        """`vrrp N ip X` populates virtual_ips with one entry."""
        tree = CiscoIOSXECLICodec().parse(self._basic_vrrp_config())
        iface = tree.interfaces[0]
        assert len(iface.vrrp_groups) == 1
        g = iface.vrrp_groups[0]
        assert g.group_id == 12
        assert g.mode == "vrrp"
        assert g.virtual_ips == ["192.168.1.254"]

    def test_basic_vrrp_round_trips(self):
        """Parse → render → re-parse keeps the canonical VRRP group
        identical."""
        codec = CiscoIOSXECLICodec()
        first = codec.parse(self._basic_vrrp_config())
        rendered = codec.render(first)
        second = codec.parse(rendered)
        assert (
            first.interfaces[0].vrrp_groups
            == second.interfaces[0].vrrp_groups
        )

    def test_basic_vrrp_render_emits_classic_form(self):
        """Render emits the classic ``vrrp N ip X`` form (operator-
        recognised; broad IOS-XE compatibility)."""
        codec = CiscoIOSXECLICodec()
        tree = codec.parse(self._basic_vrrp_config())
        rendered = codec.render(tree)
        assert " vrrp 12 ip 192.168.1.254" in rendered

    def test_multiple_groups_per_interface(self):
        """IOS-XE accepts arbitrary VRIDs on the same port; the
        canonical model preserves all of them."""
        raw = (
            "interface GigabitEthernet0/2\n"
            " ip address 192.168.1.1 255.255.255.0\n"
            " vrrp 10 ip 192.168.1.10\n"
            " vrrp 20 ip 192.168.1.20\n"
            " vrrp 30 ip 192.168.1.30\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        groups = tree.interfaces[0].vrrp_groups
        assert len(groups) == 3
        assert [g.group_id for g in groups] == [10, 20, 30]
        assert [g.virtual_ips[0] for g in groups] == [
            "192.168.1.10", "192.168.1.20", "192.168.1.30",
        ]

    def test_priority_parses_and_renders(self):
        """`vrrp N priority P` populates the priority field; render
        round-trips."""
        codec = CiscoIOSXECLICodec()
        tree = codec.parse(self._basic_vrrp_config(
            " vrrp 12 priority 110\n",
        ))
        assert tree.interfaces[0].vrrp_groups[0].priority == 110
        rendered = codec.render(tree)
        assert " vrrp 12 priority 110" in rendered

    def test_preempt_default_round_trips(self):
        """`vrrp N preempt` sets preempt=True; render emits the
        explicit line (IOS-XE default but operator-visible)."""
        codec = CiscoIOSXECLICodec()
        tree = codec.parse(self._basic_vrrp_config(
            " vrrp 12 preempt\n",
        ))
        assert tree.interfaces[0].vrrp_groups[0].preempt is True
        rendered = codec.render(tree)
        assert " vrrp 12 preempt" in rendered

    def test_no_preempt_parses_false(self):
        """`no vrrp N preempt` flips preempt off; render emits the
        ``no vrrp N preempt`` form."""
        codec = CiscoIOSXECLICodec()
        tree = codec.parse(self._basic_vrrp_config(
            " no vrrp 12 preempt\n",
        ))
        assert tree.interfaces[0].vrrp_groups[0].preempt is False
        rendered = codec.render(tree)
        assert " no vrrp 12 preempt" in rendered

    def test_description_parses_and_renders(self):
        """`vrrp N description X` populates the description field."""
        codec = CiscoIOSXECLICodec()
        tree = codec.parse(self._basic_vrrp_config(
            " vrrp 12 description Edge VRRP\n",
        ))
        assert (
            tree.interfaces[0].vrrp_groups[0].description == "Edge VRRP"
        )
        rendered = codec.render(tree)
        assert " vrrp 12 description Edge VRRP" in rendered

    def test_timers_advertise_parses(self):
        """`vrrp N timers advertise N` populates advertisement_interval."""
        codec = CiscoIOSXECLICodec()
        tree = codec.parse(self._basic_vrrp_config(
            " vrrp 12 timers advertise 3\n",
        ))
        assert (
            tree.interfaces[0].vrrp_groups[0].advertisement_interval == 3
        )
        rendered = codec.render(tree)
        assert " vrrp 12 timers advertise 3" in rendered

    def test_authentication_text_maps_to_plain_scheme(self):
        """`vrrp N authentication text X` stores as ``plain:X``."""
        codec = CiscoIOSXECLICodec()
        tree = codec.parse(self._basic_vrrp_config(
            " vrrp 12 authentication text secret-pass\n",
        ))
        assert (
            tree.interfaces[0].vrrp_groups[0].authentication
            == "plain:secret-pass"
        )
        rendered = codec.render(tree)
        # Round-trip back to the wire form.
        assert " vrrp 12 authentication text secret-pass" in rendered

    def test_authentication_md5_maps_to_md5_scheme(self):
        """`vrrp N authentication md5 key-string X` stores as
        ``md5:X``."""
        codec = CiscoIOSXECLICodec()
        tree = codec.parse(self._basic_vrrp_config(
            " vrrp 12 authentication md5 key-string SECRET\n",
        ))
        assert (
            tree.interfaces[0].vrrp_groups[0].authentication
            == "md5:SECRET"
        )
        rendered = codec.render(tree)
        assert (
            " vrrp 12 authentication md5 key-string SECRET" in rendered
        )

    def test_track_object_parses(self):
        """`vrrp N track <obj> decrement <D>` appends to
        track_interfaces.  Decrement is lossy — only the object name
        survives."""
        codec = CiscoIOSXECLICodec()
        tree = codec.parse(self._basic_vrrp_config(
            " vrrp 12 track 100 decrement 20\n",
        ))
        assert (
            tree.interfaces[0].vrrp_groups[0].track_interfaces == ["100"]
        )
        rendered = codec.render(tree)
        assert " vrrp 12 track 100" in rendered

    def test_full_grammar_round_trip_stability(self):
        """Full grammar kitchen-sink: parse → render → re-parse → re-
        render produces canonically-identical output the SECOND time
        through.  Canonical stability is what cross-vendor migration
        relies on."""
        raw = (
            "interface GigabitEthernet0/2\n"
            " ip address 192.168.1.1 255.255.255.0\n"
            " vrrp 12 ip 192.168.1.254\n"
            " vrrp 12 priority 110\n"
            " vrrp 12 preempt\n"
            " vrrp 12 description Edge VRRP\n"
            " vrrp 12 timers advertise 3\n"
            " vrrp 12 authentication text secret-pass\n"
            " vrrp 12 track 100 decrement 20\n"
            "!\n"
        )
        codec = CiscoIOSXECLICodec()
        first = codec.parse(raw)
        rendered_a = codec.render(first)
        second = codec.parse(rendered_a)
        rendered_b = codec.render(second)
        # Canonical equivalence
        assert (
            first.interfaces[0].vrrp_groups
            == second.interfaces[0].vrrp_groups
        )
        # And the second rendering exactly matches the first — wire-
        # level stability.
        assert rendered_a == rendered_b

    def test_real_capture_batfish_vrrp_fixture(self):
        """Confirms the cleanly-shipping VRRP fixture
        (``batfish_iosxe_basic_vrrp.txt``) parses + round-trips with
        the wired-up VRRP grammar.  The fixture also exercises the
        ``password 0 cisco`` round-trip that landed in commit
        ``b85c39c`` — both surfaces must coexist."""
        raw = (
            Path(__file__).resolve().parents[2]
            / "fixtures" / "real" / "cisco_iosxe"
            / "batfish_iosxe_basic_vrrp.txt"
        ).read_text()
        codec = CiscoIOSXECLICodec()
        tree = codec.parse(raw)
        # Find the Gi0/2 stanza — it carries vrrp 12 ip + priority 110.
        gi2 = next(
            i for i in tree.interfaces if i.name == "GigabitEthernet0/2"
        )
        assert len(gi2.vrrp_groups) == 1
        g = gi2.vrrp_groups[0]
        assert g.group_id == 12
        assert g.virtual_ips == ["192.168.1.254"]
        assert g.priority == 110
        # The cleartext-password fix from b85c39c also lives in this
        # fixture — sanity check that both surfaces survive.
        assert tree.local_users[0].name == "cisco"
        assert tree.local_users[0].hashed_password == "cisco"
        # Round-trip stability across both surfaces.
        rendered = codec.render(tree)
        reparsed = codec.parse(rendered)
        gi2_round = next(
            i for i in reparsed.interfaces if i.name == "GigabitEthernet0/2"
        )
        assert gi2_round.vrrp_groups == gi2.vrrp_groups

    def test_modern_address_family_form_declared_lossy(self):
        """IOS-XE 17.12+ ``vrrp N address-family ipv4`` modern form is
        declared lossy on the capability matrix — every sibling codec
        must recognise the surface exists even though the parser
        intentionally does not deep-populate the nested attributes."""
        codec = CiscoIOSXECLICodec()
        lossy_paths = {l.path for l in codec.capabilities.lossy}
        assert (
            "/interfaces/interface/vrrp-groups/group/address-family"
            in lossy_paths
        ), (
            "Capability matrix must declare the modern address-family "
            "form as lossy — see codec.py LossyPath."
        )
        # Surface acknowledgement: the AF discriminator creates an
        # empty group shell when no classic sub-commands appear.  The
        # group ID surfaces even though the nested attributes are
        # lossy.
        raw = (
            "interface GigabitEthernet0/2\n"
            " ip address 192.168.1.1 255.255.255.0\n"
            " vrrp 12 address-family ipv4\n"
            "  address 192.168.1.254 primary\n"
            "  priority 110\n"
            " exit-address-family\n"
            "!\n"
        )
        tree = codec.parse(raw)
        groups = tree.interfaces[0].vrrp_groups
        # The group ID is captured (lossiness is visible) but the
        # nested address-family attributes (address / priority) are
        # NOT populated — declared lossy by the matrix.
        assert len(groups) == 1
        assert groups[0].group_id == 12


# ---------------------------------------------------------------------------
# Wave C — SD-Access anycast-gateway
# ---------------------------------------------------------------------------


class TestAnycastGateway:
    """IOS-XE SD-Access anycast-gateway (Catalyst 9000 fabric mode).

    Two surfaces:
      * Top-level ``fabric forwarding anycast-gateway-mac <MAC>``
        declares the chassis-wide anycast MAC (one per device).
      * Per-SVI ``fabric forwarding mode anycast-gateway`` marks the
        SVI's primary IP as the anycast gateway.  Canonical mapping
        mirrors the NX-OS / IOS-XE SD-Access shape: the primary IP IS
        the virtual IP (``virtual_gateway_address == ip``).
    """

    def test_top_level_anycast_mac_parses(self):
        """``fabric forwarding anycast-gateway-mac AABB.CCDD.EEFF``
        populates ``intent.anycast_gateway_mac`` in canonical colon-
        hex form."""
        raw = (
            "fabric forwarding anycast-gateway-mac 0001.c73a.0000\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        assert tree.anycast_gateway_mac == "00:01:c7:3a:00:00"

    def test_top_level_anycast_mac_renders_dotted_triplet(self):
        """Canonical colon-hex round-trips back to Cisco dotted-triplet
        on render."""
        from netcanon.migration.canonical.intent import CanonicalIntent
        intent = CanonicalIntent(
            hostname="fabric-edge",
            anycast_gateway_mac="00:01:c7:3a:00:00",
        )
        rendered = CiscoIOSXECLICodec().render(intent)
        assert (
            "fabric forwarding anycast-gateway-mac 0001.c73a.0000"
            in rendered
        )

    def test_top_level_anycast_mac_round_trips(self):
        """Parse → render → re-parse keeps the canonical MAC value
        intact across the dotted-triplet ↔ colon-hex conversion."""
        codec = CiscoIOSXECLICodec()
        first = codec.parse(
            "fabric forwarding anycast-gateway-mac 0001.c73a.0000\n!\n"
        )
        rendered = codec.render(first)
        second = codec.parse(rendered)
        assert first.anycast_gateway_mac == second.anycast_gateway_mac

    def test_per_svi_mode_mirrors_primary_ip(self):
        """``fabric forwarding mode anycast-gateway`` inside an SVI
        sets ``virtual_gateway_address = ip`` on every IPv4 address
        (NX-OS / IOS-XE SD-Access mirror semantic)."""
        raw = (
            "interface Vlan100\n"
            " ip address 10.1.100.1 255.255.255.0\n"
            " fabric forwarding mode anycast-gateway\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        svi = next(i for i in tree.interfaces if i.name == "Vlan100")
        assert len(svi.ipv4_addresses) == 1
        addr = svi.ipv4_addresses[0]
        # Mirror — primary IP IS the virtual.
        assert addr.ip == "10.1.100.1"
        assert addr.virtual_gateway_address == "10.1.100.1"

    def test_anycast_mode_after_ip_address(self):
        """Order doesn't matter — IOS-XE accepts ``fabric forwarding
        mode anycast-gateway`` either before or after ``ip address``.
        Parser must apply the flag at stanza-close time, not at line-
        time."""
        raw = (
            "interface Vlan100\n"
            " fabric forwarding mode anycast-gateway\n"
            " ip address 10.1.100.1 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        svi = next(i for i in tree.interfaces if i.name == "Vlan100")
        # Mirror semantic still applies regardless of declaration order.
        assert svi.ipv4_addresses[0].virtual_gateway_address == "10.1.100.1"

    def test_svi_without_anycast_marker_has_empty_virtual_gateway(self):
        """Discriminator gate: a plain SVI (no ``fabric forwarding mode
        anycast-gateway`` line) parses with ``virtual_gateway_address``
        empty.  Same IP, same SVI — only the marker changes the
        canonical state."""
        raw = (
            "interface Vlan100\n"
            " ip address 10.1.100.1 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        svi = next(i for i in tree.interfaces if i.name == "Vlan100")
        assert svi.ipv4_addresses[0].virtual_gateway_address == ""

    def test_anycast_mode_renders_marker(self):
        """Per-SVI ``virtual_gateway_address == ip`` triggers the
        ``fabric forwarding mode anycast-gateway`` line on render."""
        codec = CiscoIOSXECLICodec()
        tree = codec.parse(
            "interface Vlan100\n"
            " ip address 10.1.100.1 255.255.255.0\n"
            " fabric forwarding mode anycast-gateway\n"
            "!\n"
        )
        rendered = codec.render(tree)
        assert " fabric forwarding mode anycast-gateway" in rendered

    def test_anycast_full_round_trip(self):
        """Full SD-Access fabric edge config — top-level MAC + per-SVI
        marker — round-trips through parse → render → re-parse with
        canonical state preserved."""
        raw = (
            "hostname fabric-edge\n"
            "!\n"
            "fabric forwarding anycast-gateway-mac 0001.c73a.0000\n"
            "!\n"
            "interface Vlan100\n"
            " ip address 10.1.100.1 255.255.255.0\n"
            " fabric forwarding mode anycast-gateway\n"
            "!\n"
            "interface Vlan200\n"
            " ip address 10.1.200.1 255.255.255.0\n"
            " fabric forwarding mode anycast-gateway\n"
            "!\n"
        )
        codec = CiscoIOSXECLICodec()
        first = codec.parse(raw)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        # Top-level MAC.
        assert (
            first.anycast_gateway_mac == second.anycast_gateway_mac
            == "00:01:c7:3a:00:00"
        )
        # Both SVIs round-trip with mirror semantics intact.
        for vid, vip in [(100, "10.1.100.1"), (200, "10.1.200.1")]:
            svi_a = next(
                i for i in first.interfaces if i.name == f"Vlan{vid}"
            )
            svi_b = next(
                i for i in second.interfaces if i.name == f"Vlan{vid}"
            )
            assert (
                svi_a.ipv4_addresses[0].virtual_gateway_address
                == svi_b.ipv4_addresses[0].virtual_gateway_address
                == vip
            )

    def test_mac_accepts_colon_hex_input(self):
        """The MAC normaliser accepts the canonical colon-hex form
        directly (operator paste from a non-Cisco target)."""
        tree = CiscoIOSXECLICodec().parse(
            "fabric forwarding anycast-gateway-mac 00:01:c7:3a:00:00\n!\n"
        )
        assert tree.anycast_gateway_mac == "00:01:c7:3a:00:00"

    def test_anycast_mode_emits_only_once_per_interface(self):
        """Multiple IPv4 addresses on the same SVI (rare in SD-Access,
        but possible) emit the ``fabric forwarding mode anycast-
        gateway`` line ONCE — it's a per-interface marker, not per-
        address."""
        from netcanon.migration.canonical.intent import (
            CanonicalIntent, CanonicalInterface, CanonicalIPv4Address,
        )
        intent = CanonicalIntent(hostname="sw")
        intent.interfaces.append(CanonicalInterface(
            name="Vlan100",
            interface_type="ianaift:l3ipvlan",
            ipv4_addresses=[
                CanonicalIPv4Address(
                    ip="10.1.100.1", prefix_length=24,
                    virtual_gateway_address="10.1.100.1",
                ),
                CanonicalIPv4Address(
                    ip="10.1.101.1", prefix_length=24,
                    virtual_gateway_address="10.1.101.1",
                ),
            ],
        ))
        rendered = CiscoIOSXECLICodec().render(intent)
        # Marker appears once even though two addresses carry the flag.
        assert rendered.count(
            " fabric forwarding mode anycast-gateway"
        ) == 1

    def test_anycast_capability_matrix_lists_supported_paths(self):
        """Capability matrix declares the three new SD-Access paths
        supported (Wave C) — keeping the IPv6 form unsupported as
        documented."""
        codec = CiscoIOSXECLICodec()
        caps = codec.capabilities
        supported = set(caps.supported)
        unsupported = {u.path for u in caps.unsupported}
        # Wave B + C wire-up.
        assert "/interfaces/interface/vrrp-groups/group" in supported
        assert (
            "/interfaces/interface/ipv4/address/virtual-gateway-address"
            in supported
        )
        assert "/anycast-gateway-mac" in supported
        # IPv6 anycast intentionally unsupported.
        assert (
            "/interfaces/interface/ipv6/address/virtual-gateway-address"
            in unsupported
        )
        # Per-VRF static-route also remains unsupported (separate work).
        assert "/routing/static-route/vrf" in unsupported

    def test_cross_vendor_virtual_ip_distinct_from_primary_emits_review(self):
        """When ``virtual_gateway_address`` differs from the primary
        IP (Junos / Arista VARP cross-vendor shape), IOS-XE SD-Access
        has no equivalent — the renderer must emit a ``! review:``
        comment rather than silently dropping the discrepancy."""
        from netcanon.migration.canonical.intent import (
            CanonicalIntent, CanonicalInterface, CanonicalIPv4Address,
        )
        intent = CanonicalIntent(hostname="sw")
        intent.interfaces.append(CanonicalInterface(
            name="Vlan100",
            interface_type="ianaift:l3ipvlan",
            ipv4_addresses=[
                CanonicalIPv4Address(
                    ip="10.1.100.1", prefix_length=24,
                    # Distinct virtual IP — Junos-shape, not SD-Access.
                    virtual_gateway_address="10.1.100.254",
                ),
            ],
        ))
        rendered = CiscoIOSXECLICodec().render(intent)
        assert "! review:" in rendered
        assert "virtual_gateway_address" in rendered
        # And the SD-Access marker MUST NOT be emitted for this shape.
        assert (
            " fabric forwarding mode anycast-gateway" not in rendered
        )
