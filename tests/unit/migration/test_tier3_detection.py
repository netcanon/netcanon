"""Unit tests for ``netcanon.migration._tier3_detection``.

Pin the per-vendor detector behaviour against synthetic fixtures so the
"detected in source but not translated" banner has stable inputs.
False positives are preferred to false negatives — every test here
asserts on EXACT label content for the synthetic stanzas the parser
genuinely drops.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration import _tier3_detection
from netcanon.migration._tier3_detection import (
    LEFT_OUT_ROWS_SHOWN,
    detect_tier3_sections_aoscx,
    detect_tier3_sections_aoss,
    detect_tier3_sections_dellos10,
    detect_tier3_sections_fortios,
    detect_tier3_sections_iosxe_cli,
    detect_tier3_sections_iosxe_xml,
    detect_tier3_sections_junos,
    detect_tier3_sections_opnsense,
    detect_tier3_sections_routeros,
    is_left_out_row,
    left_out_row,
    left_out_rows,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# IOS-XE / Arista CLI detector
# ---------------------------------------------------------------------------


class TestIOSXECLI:
    def test_empty_returns_empty(self) -> None:
        assert detect_tier3_sections_iosxe_cli("") == []

    def test_pure_supported_stanzas_return_empty(self) -> None:
        # hostname + interface + vlan + static route + snmp — all
        # things the parsers DO consume.
        raw = (
            "hostname r1\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n"
            "!\n"
            "vlan 10\n"
            " name USERS\n"
            "!\n"
            "snmp-server community public RO\n"
            "ip route 0.0.0.0 0.0.0.0 192.0.2.1\n"
        )
        assert detect_tier3_sections_iosxe_cli(raw) == []

    def test_extended_acl(self) -> None:
        raw = (
            "ip access-list extended OUTSIDE_IN\n"
            " permit tcp any any eq 22\n"
        )
        assert detect_tier3_sections_iosxe_cli(raw) == [
            "ip access-list extended OUTSIDE_IN",
        ]

    def test_full_tier3_kitchen_sink(self) -> None:
        raw = (
            "hostname r1\n"
            "ip access-list extended OUTSIDE_IN\n"
            " permit tcp any any eq 22\n"
            "ipv6 access-list V6_LOCK\n"
            "ip nat inside source list 10 interface Gi0/0 overload\n"
            "class-map match-all VOICE\n"
            "policy-map POLICE_VOICE\n"
            "route-map BGP-OUT permit 10\n"
            "crypto isakmp policy 10\n"
            "crypto ipsec transform-set TS esp-aes\n"
            "zone-pair security IN-OUT source IN destination OUT\n"
        )
        result = detect_tier3_sections_iosxe_cli(raw)
        assert "ip access-list extended OUTSIDE_IN" in result
        assert "ipv6 access-list V6_LOCK" in result
        assert any(s.startswith("ip nat inside source") for s in result)
        assert any(s.startswith("class-map") for s in result)
        assert any(s.startswith("policy-map") for s in result)
        assert "route-map BGP-OUT" in result
        assert any(s.startswith("crypto isakmp") for s in result)
        assert any(s.startswith("crypto ipsec") for s in result)
        assert any(s.startswith("zone-pair security") for s in result)

    def test_dedupe_first_occurrence_order(self) -> None:
        raw = (
            "ip access-list extended A\n"
            "ip access-list extended A\n"  # duplicate header
            "ip access-list extended B\n"
        )
        # ``A`` appears once even though source has two entries.
        assert detect_tier3_sections_iosxe_cli(raw) == [
            "ip access-list extended A",
            "ip access-list extended B",
        ]

    def test_numbered_acl(self) -> None:
        raw = "access-list 10 permit 10.0.0.0 0.0.0.255\n"
        result = detect_tier3_sections_iosxe_cli(raw)
        assert result == ["access-list 10 permit 10.0.0.0 0.0.0.255"]

    def test_interface_acl_binding_detected(self) -> None:
        # The indented per-interface ACL binding is a dropped security control;
        # it must surface so the "not translated" banner fires, even though the
        # column-0 anchors (test_extended_acl) only see the definition (audit
        # 81d9740 T0-4).
        raw = (
            "interface GigabitEthernet0/2\n"
            " ip address 203.0.113.1 255.255.255.0\n"
            " ip access-group BLOCK in\n"
            " ipv6 access-group V6OUT out\n"
            "!\n"
        )
        result = detect_tier3_sections_iosxe_cli(raw)
        assert "ip access-group BLOCK in" in result
        assert "ipv6 access-group V6OUT out" in result

    def test_interface_acl_binding_off_box_def_still_surfaces(self) -> None:
        # Worst case: ONLY the binding is in this config (the ACL definition
        # lives off-box), so the column-0 definition banner never fires — the
        # binding alone must still surface.
        raw = "interface Gi0/2\n ip access-group BLOCK in\n!\n"
        assert detect_tier3_sections_iosxe_cli(raw) == ["ip access-group BLOCK in"]

    def test_igmp_access_group_not_flagged(self) -> None:
        # `ip igmp access-group` is a multicast join-filter, not an ACL packet
        # filter — `ip` is not immediately followed by `access-group`, so the
        # binding pattern must NOT flag it (false-positive guard).
        raw = "interface Gi0/3\n ip igmp access-group MCAST-FILTER\n!\n"
        assert detect_tier3_sections_iosxe_cli(raw) == []


# ---------------------------------------------------------------------------
# FortiOS detector
# ---------------------------------------------------------------------------


class TestFortiOS:
    def test_empty_returns_empty(self) -> None:
        assert detect_tier3_sections_fortios("") == []

    def test_supported_blocks_return_empty(self) -> None:
        raw = (
            "config system global\n"
            '    set hostname "fw"\n'
            "end\n"
            "config system interface\n"
            '    edit "port1"\n'
            "    next\n"
            "end\n"
            "config system dns\n"
            "    set primary 1.1.1.1\n"
            "end\n"
        )
        assert detect_tier3_sections_fortios(raw) == []

    def test_firewall_policy(self) -> None:
        raw = (
            "config firewall policy\n"
            "    edit 1\n"
            "    next\n"
            "end\n"
        )
        assert detect_tier3_sections_fortios(raw) == ["config firewall policy"]

    def test_full_kitchen_sink(self) -> None:
        raw = (
            "config firewall policy\nend\n"
            "config firewall vip\nend\n"
            "config firewall address\nend\n"
            "config vpn ipsec phase1-interface\nend\n"
            "config vpn ssl settings\nend\n"
            "config webfilter profile\nend\n"
            "config antivirus profile\nend\n"
            "config ips sensor\nend\n"
            "config router policy\nend\n"
            "config router route-map\nend\n"
        )
        result = detect_tier3_sections_fortios(raw)
        # Spot-check a few — the test isn't trying to re-spec the full
        # pattern list, just to prove the major buckets are caught.
        assert "config firewall policy" in result
        assert "config firewall vip" in result
        assert "config vpn ipsec" in result
        assert "config webfilter" in result
        assert "config router policy" in result


# ---------------------------------------------------------------------------
# Junos set-form detector
# ---------------------------------------------------------------------------


class TestJunos:
    def test_empty_returns_empty(self) -> None:
        assert detect_tier3_sections_junos("") == []

    def test_supported_lines_return_empty(self) -> None:
        raw = (
            "set system host-name r1\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
            "set vlans USERS vlan-id 10\n"
            "set routing-options static route 0.0.0.0/0 next-hop 10.0.0.2\n"
            "set snmp community public authorization read-only\n"
        )
        assert detect_tier3_sections_junos(raw) == []

    def test_firewall_filter(self) -> None:
        raw = (
            "set firewall family inet filter LOOPBACK term ssh "
            "from protocol tcp\n"
        )
        assert detect_tier3_sections_junos(raw) == [
            "set firewall family inet filter LOOPBACK",
        ]

    def test_security_policies(self) -> None:
        raw = (
            "set security policies from-zone trust to-zone untrust "
            "policy ALLOW match\n"
            "set security nat source rule-set RS\n"
        )
        result = detect_tier3_sections_junos(raw)
        assert "set security policies" in result
        assert "set security nat" in result

    def test_policy_options(self) -> None:
        raw = (
            "set policy-options policy-statement BGP-IN term 1 then accept\n"
            "set policy-options prefix-list LANS 10.0.0.0/8\n"
        )
        result = detect_tier3_sections_junos(raw)
        assert "set policy-options policy-statement BGP-IN" in result
        assert "set policy-options prefix-list LANS" in result


# ---------------------------------------------------------------------------
# RouterOS detector
# ---------------------------------------------------------------------------


class TestRouterOS:
    def test_empty_returns_empty(self) -> None:
        assert detect_tier3_sections_routeros("") == []

    def test_supported_paths_return_empty(self) -> None:
        raw = (
            "/system identity set name=r1\n"
            "/ip address add address=10.0.0.1/24 interface=ether1\n"
            "/ip route add dst-address=0.0.0.0/0 gateway=10.0.0.2\n"
            "/snmp set enabled=yes\n"
            "/interface ethernet set [ find default-name=ether1 ]\n"
        )
        assert detect_tier3_sections_routeros(raw) == []

    def test_firewall_filter(self) -> None:
        raw = "/ip firewall filter add chain=input action=accept\n"
        assert detect_tier3_sections_routeros(raw) == ["/ip firewall filter"]

    def test_full_kitchen_sink(self) -> None:
        raw = (
            "/ip firewall filter add chain=input\n"
            "/ip firewall nat add chain=srcnat\n"
            "/ipv6 firewall filter add chain=input\n"
            "/queue tree add name=q1\n"
            "/ip ipsec policy add\n"
            "/routing bgp instance set default as=65001\n"
            "/routing ospf instance add name=default\n"
        )
        result = detect_tier3_sections_routeros(raw)
        assert "/ip firewall filter" in result
        assert "/ip firewall nat" in result
        assert "/ipv6 firewall filter" in result
        assert "/queue" in result
        assert "/ip ipsec" in result
        assert "/routing bgp" in result
        assert "/routing ospf" in result


# ---------------------------------------------------------------------------
# OPNsense XML detector
# ---------------------------------------------------------------------------


class TestOPNsense:
    def test_empty_returns_empty(self) -> None:
        assert detect_tier3_sections_opnsense("") == []

    def test_supported_blocks_return_empty(self) -> None:
        raw = (
            "<opnsense>"
            "  <system><hostname>fw</hostname></system>"
            "  <interfaces><wan><if>em0</if></wan></interfaces>"
            "  <vlans></vlans>"
            "  <staticroutes></staticroutes>"
            "</opnsense>"
        )
        assert detect_tier3_sections_opnsense(raw) == []

    def test_filter_and_nat(self) -> None:
        raw = (
            "<opnsense>"
            "  <filter><rule></rule></filter>"
            "  <nat><outbound></outbound></nat>"
            "  <ipsec></ipsec>"
            "</opnsense>"
        )
        result = detect_tier3_sections_opnsense(raw)
        assert "<filter>" in result
        assert "<nat>" in result
        assert "<ipsec>" in result

    def test_openvpn_and_wireguard(self) -> None:
        raw = "<opnsense><openvpn></openvpn><wireguard></wireguard></opnsense>"
        result = detect_tier3_sections_opnsense(raw)
        assert "<openvpn>" in result
        assert "<wireguard>" in result


# ---------------------------------------------------------------------------
# Cisco IOS-XE NETCONF / OpenConfig XML detector — currently a no-op.
# ---------------------------------------------------------------------------


class TestIOSXEXML:
    def test_noop_for_typical_netconf_input(self) -> None:
        raw = (
            '<rpc-reply><data>'
            '<interfaces xmlns="http://openconfig.net/yang/interfaces">'
            '<interface><name>Gi0/0</name></interface>'
            '</interfaces>'
            '</data></rpc-reply>'
        )
        assert detect_tier3_sections_iosxe_xml(raw) == []

    def test_noop_for_empty_string(self) -> None:
        assert detect_tier3_sections_iosxe_xml("") == []


# ---------------------------------------------------------------------------
# Cross-codec wiring — every codec's parse() populates the field.
# ---------------------------------------------------------------------------


class TestCodecWiring:
    """Pin that each shipped codec's ``parse()`` populates
    ``CanonicalIntent.dropped_tier3_sections`` from the per-vendor
    detector.  Synthetic input with one Tier-3 stanza per codec is
    enough — the helper tests above pin the detector content."""

    def test_arista_eos_populates_field(self) -> None:
        from netcanon.migration.codecs.arista_eos.codec import AristaEOSCodec

        raw = (
            "hostname r1\n"
            "ip access-list extended OUTSIDE_IN\n"
            " permit tcp any any\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert "ip access-list extended OUTSIDE_IN" in intent.dropped_tier3_sections

    def test_aruba_aoss_populates_field(self) -> None:
        from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec

        raw = (
            'hostname "sw"\n'
            "ip access-list extended LOCK\n"
            "vlan 1\n"
            "   exit\n"
        )
        intent = ArubaAOSSCodec().parse(raw)
        assert "ip access-list extended LOCK" in intent.dropped_tier3_sections

    def test_cisco_iosxe_cli_populates_field(self) -> None:
        from netcanon.migration.codecs.cisco_iosxe_cli.codec import (
            CiscoIOSXECLICodec,
        )

        raw = (
            "hostname r1\n"
            "ip access-list extended VTY_ACCESS\n"
            " permit tcp any any eq 22\n"
            "route-map RM permit 10\n"
        )
        intent = CiscoIOSXECLICodec().parse(raw)
        assert any(
            s.startswith("ip access-list extended VTY_ACCESS")
            for s in intent.dropped_tier3_sections
        )
        assert any(
            s.startswith("route-map RM")
            for s in intent.dropped_tier3_sections
        )

    def test_cisco_iosxe_cli_interface_acl_binding_surfaces(self) -> None:
        # The audit's worst case (81d9740 T0-4): the ONLY ACL signal is the
        # indented per-interface binding (the ACL definition lives off-box).
        # Before the detector fix this produced an empty dropped_tier3_sections
        # and a silent severity=ok migration; the binding must now surface so
        # the "not translated" banner fires.
        from netcanon.migration.codecs.cisco_iosxe_cli.codec import (
            CiscoIOSXECLICodec,
        )

        raw = (
            "hostname r1\n"
            "interface GigabitEthernet0/2\n"
            " ip address 203.0.113.1 255.255.255.0\n"
            " ip access-group BLOCK in\n"
            "!\n"
        )
        intent = CiscoIOSXECLICodec().parse(raw)
        assert "ip access-group BLOCK in" in intent.dropped_tier3_sections

    def test_cisco_iosxe_netconf_populates_field_as_empty(self) -> None:
        from netcanon.migration.codecs.cisco_iosxe.codec import (
            CiscoIOSXECodec,
        )

        raw = (
            '<interfaces xmlns="http://openconfig.net/yang/interfaces">\n'
            '  <interface><name>Gi0/0</name>'
            '<config><name>Gi0/0</name><enabled>true</enabled></config>'
            '</interface>\n'
            '</interfaces>\n'
        )
        intent = CiscoIOSXECodec().parse(raw)
        # NETCONF input doesn't carry firewall/QoS XML — detector is
        # a no-op.  Field is empty list, NOT None.
        assert intent.dropped_tier3_sections == []

    def test_fortigate_populates_field(self) -> None:
        from netcanon.migration.codecs.fortigate_cli.codec import (
            FortiGateCLICodec,
        )

        raw = (
            "config system global\n"
            '    set hostname "fw"\n'
            "end\n"
            "config firewall policy\n"
            "    edit 1\n"
            "    next\n"
            "end\n"
        )
        intent = FortiGateCLICodec().parse(raw)
        assert "config firewall policy" in intent.dropped_tier3_sections

    def test_juniper_junos_populates_field(self) -> None:
        from netcanon.migration.codecs.juniper_junos.codec import JunosCodec

        raw = (
            "set system host-name r1\n"
            "set firewall family inet filter LOCK term default then discard\n"
        )
        intent = JunosCodec().parse(raw)
        assert any(
            s.startswith("set firewall family inet filter LOCK")
            for s in intent.dropped_tier3_sections
        )

    def test_mikrotik_routeros_populates_field(self) -> None:
        from netcanon.migration.codecs.mikrotik_routeros.codec import (
            MikroTikRouterOSCodec,
        )

        raw = (
            "/system identity set name=r1\n"
            "/ip firewall filter add chain=input action=accept\n"
        )
        intent = MikroTikRouterOSCodec().parse(raw)
        assert "/ip firewall filter" in intent.dropped_tier3_sections

    def test_opnsense_populates_field(self) -> None:
        from netcanon.migration.codecs.opnsense.codec import OPNsenseCodec

        raw = (
            "<opnsense>"
            "<system><hostname>fw</hostname></system>"
            "<interfaces><wan><if>em0</if><enable/></wan></interfaces>"
            "<filter><rule></rule></filter>"
            "</opnsense>"
        )
        intent = OPNsenseCodec().parse(raw)
        assert "<filter>" in intent.dropped_tier3_sections

    def test_clean_input_returns_empty_list(self) -> None:
        """Sanity: a config with only Tier-1/2 content yields []."""
        from netcanon.migration.codecs.cisco_iosxe_cli.codec import (
            CiscoIOSXECLICodec,
        )

        raw = (
            "hostname r1\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n"
            "!\n"
            "ip route 0.0.0.0 0.0.0.0 10.0.0.2\n"
        )
        intent = CiscoIOSXECLICodec().parse(raw)
        assert intent.dropped_tier3_sections == []


# ---------------------------------------------------------------------------
# Dell OS10 detector — VLT
# ---------------------------------------------------------------------------


class TestDellOS10VLT:
    """`vlt-port-channel` is the half of VLT that silently changes meaning.

    `vlt-domain` is a column-0 stanza and was always detected.  The
    per-bundle marker that makes a LAG dual-homed ACROSS the peer pair is
    INDENTED inside an `interface port-channel` stanza, so the column-0
    anchoring every other Dell pattern uses missed it entirely.

    Consequence before 2026-09-24: a dual-homed bundle rendered as an
    ordinary single-chassis port-channel, with no marker in the output AND
    no line in the Tier-3 banner.  The operator was told VLT existed (via
    `vlt-domain`) but not which bundles had changed meaning — a semantic
    downgrade wearing a clean LAG translation.  Measured on the committed
    corpus: present in 6 of 9 captures, detected in 0.
    """

    _STANZA = (
        "vlt-domain 1\n"
        " backup destination 192.0.2.7\n"
        " discovery-interface ethernet1/1/13\n"
        "!\n"
        "interface port-channel102\n"
        " description dual-homed-to-host\n"
        " switchport mode trunk\n"
        " vlt-port-channel 102\n"
        "!\n"
    )

    def test_vlt_port_channel_is_detected(self) -> None:
        found = detect_tier3_sections_dellos10(self._STANZA)
        assert any("vlt-port-channel" in s for s in found), (
            f"dual-homed bundle marker not surfaced; got {found!r}"
        )

    def test_the_bundle_id_survives_into_the_label(self) -> None:
        """The id is the payload.

        "VLT existed somewhere" is not actionable; "port-channel 102 was
        dual-homed" is.  Unlike `interface breakout`, this pattern keeps
        its tail on purpose — pin that so a future tidy-up doesn't strip
        it for symmetry.
        """
        found = detect_tier3_sections_dellos10(self._STANZA)
        assert "vlt-port-channel 102" in found

    def test_indentation_is_the_whole_point(self) -> None:
        """Guard the guard.

        If this line ever appears at column 0 in a capture, the original
        `^vlt-domain`-style anchoring would have been sufficient and this
        pattern is no longer pinning what its docstring claims.
        """
        indented = " vlt-port-channel 7\n"
        assert detect_tier3_sections_dellos10(indented) == [
            "vlt-port-channel 7"
        ]

    def test_vlt_domain_still_detected(self) -> None:
        """The pre-existing half must not regress."""
        assert "vlt-domain 1" in detect_tier3_sections_dellos10(self._STANZA)

    def test_no_false_positive_on_a_plain_bundle(self) -> None:
        """A single-chassis port-channel is fully modelled and must NOT
        raise a Tier-3 line — a detector that fires everywhere is noise."""
        raw = (
            "interface port-channel10\n"
            " description plain-lag\n"
            " switchport mode trunk\n"
            "!\n"
        )
        found = detect_tier3_sections_dellos10(raw)
        assert not [s for s in found if "vlt" in s], found

    def test_committed_corpus_every_marker_is_surfaced(self) -> None:
        """The real regression guard, measured rather than asserted.

        Walks the committed Dell captures and requires that any capture
        carrying a `vlt-port-channel` line produces a matching banner
        label.  This is the assertion that would have failed before the
        fix, on 6 of 9 files.
        """
        from pathlib import Path

        corpus = (
            Path(__file__).resolve().parents[2]
            / "fixtures"
            / "real"
            / "dell_os10"
        )
        if not corpus.is_dir():  # pragma: no cover - corpus always present
            pytest.skip("dell_os10 corpus absent")

        checked = 0
        missed: list[str] = []
        for path in sorted(corpus.iterdir()):
            if not path.is_file() or path.suffix.lower() == ".md":
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            carries = any(
                line.strip().startswith("vlt-port-channel")
                for line in raw.splitlines()
            )
            if not carries:
                continue
            checked += 1
            found = detect_tier3_sections_dellos10(raw)
            if not any("vlt-port-channel" in s for s in found):
                missed.append(path.name)

        assert checked, (
            "no committed Dell capture carries a `vlt-port-channel` line — "
            "this guard would pass vacuously"
        )
        assert not missed, (
            "dual-homed bundles silently downgraded to single-chassis in: "
            f"{missed}"
        )


class TestAristaMLAG:
    """Arista's MLAG is the same defect as Dell's VLT, one vendor over.

    Neither half had a canonical surface OR a Tier-3 pattern, so both were
    dropped with no banner line at all — a silent loss, not a declared
    one.  Found 2026-09-24 while checking an over-claim in
    `docs/vendors/arista_eos.md`, which asserted the parser "round-trips
    the peer-link mapping"; measured, nothing MLAG-related reached the
    canonical tree or the rendered output.
    """

    _RAW = (
        "hostname leaf1\n"
        "!\n"
        "mlag configuration\n"
        "   domain-id MLAG1\n"
        "   peer-address 10.0.0.2\n"
        "   peer-link Port-Channel1000\n"
        "!\n"
        "interface Port-Channel10\n"
        "   description dual-homed\n"
        "   mlag 10\n"
        "!\n"
    )

    def test_peer_block_is_surfaced(self) -> None:
        assert "mlag configuration" in detect_tier3_sections_iosxe_cli(
            self._RAW
        )

    def test_per_bundle_marker_is_surfaced_with_its_id(self) -> None:
        """The indented half — the one that changes a bundle's meaning."""
        assert "mlag 10" in detect_tier3_sections_iosxe_cli(self._RAW)

    def test_plain_iosxe_is_unaffected(self) -> None:
        """This pattern set is SHARED with cisco_iosxe_cli.  IOS-XE has no
        `mlag` grammar, so the addition must be inert there."""
        raw = (
            "hostname r1\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n"
            "!\n"
        )
        found = detect_tier3_sections_iosxe_cli(raw)
        assert not [s for s in found if "mlag" in s.lower()], found

    def test_committed_arista_corpus_every_marker_is_surfaced(self) -> None:
        """Measured guard over the real captures.

        Two committed Arista captures carry MLAG; before the fix both
        produced zero MLAG banner lines.
        """
        from pathlib import Path

        corpus = (
            Path(__file__).resolve().parents[2]
            / "fixtures"
            / "real"
            / "arista_eos"
        )
        if not corpus.is_dir():  # pragma: no cover - corpus always present
            pytest.skip("arista_eos corpus absent")

        checked = 0
        missed: list[str] = []
        for path in sorted(corpus.iterdir()):
            if not path.is_file() or path.suffix.lower() == ".md":
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            if not any(
                line.strip().startswith("mlag") for line in raw.splitlines()
            ):
                continue
            checked += 1
            found = detect_tier3_sections_iosxe_cli(raw)
            if not any("mlag" in s.lower() for s in found):
                missed.append(path.name)

        assert checked, (
            "no committed Arista capture carries an `mlag` line — this "
            "guard would pass vacuously"
        )
        assert not missed, f"MLAG silently dropped, no banner, in: {missed}"


# ---------------------------------------------------------------------------
# Aruba AOS-CX detector -- VSF
# ---------------------------------------------------------------------------


class TestArubaAOSCXVSF:
    """A CX 6200's or 6300's stack lines are not translated, and were
    not listed: onto any target, AOS-CX included, the output had no
    ``vsf`` line and the job said ``completed`` with no row for them.
    Each line is a row now; the job's status is as it was, since a
    row is a section to apply by hand.

    The text is the shape of HPE's VSF guide for the 6200 and 6300
    (AOS-CX 10.18): a ``vsf member`` block with its ``type`` and
    ``link`` lines, and the two other lines it prints."""

    _STACK = (
        "hostname sw\n"
        "vsf member 1\n"
        "    type jl661a\n"
        "    link 1 1/1/49\n"
        "vsf member 2 \n"
        "    type jl662a\n"
        "    link 1 2/1/50\n"
        "vsf secondary-member 2\n"
        "vsf split-detect mgmt\n"
        "vlan 10\n"
        "interface 1/1/1\n"
        "    no shutdown\n"
        "    vlan access 10\n"
    )

    _ROWS = [
        "vsf member 1",
        "vsf member 2",
        "vsf secondary-member 2",
        "vsf split-detect mgmt",
    ]

    def test_each_vsf_line_is_a_row(self) -> None:
        """Exact: the indented ``type`` and ``link`` lines are under
        their member's row, and nothing else in the text is a row."""
        assert detect_tier3_sections_aoscx(self._STACK) == self._ROWS

    def test_crlf_text(self) -> None:
        text = self._STACK.replace("\n", "\r\n")
        assert detect_tier3_sections_aoscx(text) == self._ROWS

    @pytest.mark.parametrize(
        "text",
        [
            "interface 1/1/49\n    description vsf link\n",
            "no vsf member 3\n",
            "vsx\n    inter-switch-link lag 256\n",
        ],
        ids=["a word in a description", "a no form", "vsx"],
    )
    def test_what_is_not_a_vsf_line(self, text: str) -> None:
        assert detect_tier3_sections_aoscx(text) == []

    def test_the_codec_lists_them(self) -> None:
        from netcanon.migration.codecs.aruba_aoscx.codec import ArubaAOSCXCodec

        intent = ArubaAOSCXCodec().parse(self._STACK)
        assert intent.dropped_tier3_sections == self._ROWS

    def test_a_banners_line_is_text(self) -> None:
        from netcanon.migration.codecs.aruba_aoscx.codec import ArubaAOSCXCodec

        text = "banner motd !\nvsf member 9\n!\n" + self._STACK
        intent = ArubaAOSCXCodec().parse(text)
        assert intent.dropped_tier3_sections == self._ROWS

    @pytest.mark.parametrize(
        "target", ["aruba_aoscx", "cisco_iosxe_cli"],
    )
    def test_a_job_lists_them(self, target: str) -> None:
        """The output has no ``vsf`` line, onto AOS-CX itself as onto
        another vendor, and the job says which it left out.  The
        status is the validation report's: a section to apply by
        hand does not hold the job."""
        from netcanon.migration.codecs.registry import get_codec
        from netcanon.models.migration import MigrationJobStatus
        from netcanon.services.migration_pipeline import run_plan

        job = run_plan(get_codec("aruba_aoscx"), get_codec(target), self._STACK)
        assert job.status == MigrationJobStatus.completed, job.error
        assert job.dropped_tier3_sections == self._ROWS
        assert job.rendered is not None
        assert not [
            line for line in job.rendered.splitlines()
            if line.strip().startswith("vsf")
        ]


def _job(source: str, target: str, text: str):
    from netcanon.migration.codecs.registry import get_codec
    from netcanon.services.migration_pipeline import run_plan

    return run_plan(get_codec(source), get_codec(target), text)


def _only_in(with_lines, without_lines) -> list[str]:
    """The rows of the job *with_lines* has that the job *without_lines*
    has not, in order."""
    return [r for r in with_lines.dropped_tier3_sections if r not in without_lines.dropped_tier3_sections]


class TestCatalystStack:
    """A Catalyst stack's own lines were dropped with no row, as the
    AOS-CX ``vsf`` lines were: ``switch N provision`` (which a switch
    that is alone prints too), ``switch N priority``, StackPower and
    StackWise Virtual.  Each is a row now, kept whole; the job is
    otherwise as it was without them."""

    _HEAD = "hostname sw\n"
    _STACK_LINES = (
        "switch 1 provision c9300-24ux\n"
        "switch 2 provision c9300-48p\n"
        "switch 2 priority 14\n"
        "stack-power stack Powerstack-1\n"
        " mode redundant\n"
        "stack-power switch 1\n"
        " stack Powerstack-1\n"
        "!\n"
    )
    _BODY = (
        "vlan 10\n"
        "!\n"
        "interface GigabitEthernet1/0/1\n"
        " switchport access vlan 10\n"
        " switchport mode access\n"
        "!\n"
    )
    _ROWS = [
        "switch 1 provision c9300-24ux",
        "switch 2 provision c9300-48p",
        "switch 2 priority 14",
        "stack-power stack Powerstack-1",
        "stack-power switch 1",
    ]

    #: A StackWise Virtual pair: the block at the top, and a link and
    #: the dual-active detection under the interfaces that carry them.
    _PAIR = (
        "hostname core\n"
        "stackwise-virtual\n"
        " domain 1\n"
        "!\n"
        "vlan 10\n"
        "!\n"
        "interface FortyGigabitEthernet1/0/1\n"
        " stackwise-virtual link 1\n"
        "!\n"
        "interface FortyGigabitEthernet2/0/1\n"
        " stackwise-virtual link 1\n"
        "!\n"
        "interface FortyGigabitEthernet1/0/2\n"
        " stackwise-virtual dual-active-detection\n"
        "!\n"
        "interface FortyGigabitEthernet1/0/3\n"
        " switchport access vlan 10\n"
        " switchport mode access\n"
        "!\n"
    )
    _PAIR_ROWS = [
        "stackwise-virtual",
        "stackwise-virtual link 1",
        "stackwise-virtual dual-active-detection",
    ]

    def _pair_without(self) -> str:
        return "".join(
            line for line in self._PAIR.splitlines(keepends=True)
            if "stackwise-virtual" not in line and line != " domain 1\n"
        )

    def test_each_stack_line_is_a_row(self) -> None:
        text = self._HEAD + self._STACK_LINES + self._BODY
        assert detect_tier3_sections_iosxe_cli(text) == self._ROWS

    def test_each_line_of_a_pair_is_a_row(self) -> None:
        assert detect_tier3_sections_iosxe_cli(self._PAIR) == self._PAIR_ROWS

    def test_crlf_text(self) -> None:
        text = (self._HEAD + self._STACK_LINES + self._BODY).replace("\n", "\r\n")
        assert detect_tier3_sections_iosxe_cli(text) == self._ROWS

    @pytest.mark.parametrize(
        "text",
        [
            "interface GigabitEthernet1/0/1\n description switch 1 provision c9300-48p\n!\n",
            "interface GigabitEthernet1/0/1\n description stackwise-virtual link 1\n!\n",
            "interface GigabitEthernet1/0/1\n switchport mode trunk\n!\n",
            "switch provision\n",
            "spanning-tree mode rapid-pvst\n",
        ],
        ids=["a provision line in a description", "a link line in a description", "switchport",
             "no switch number", "another top line"],
    )
    def test_what_is_not_a_stack_line(self, text: str) -> None:
        assert detect_tier3_sections_iosxe_cli(text) == []

    def test_the_codec_lists_them_and_not_a_banners(self) -> None:
        from netcanon.migration.codecs.cisco_iosxe_cli.codec import CiscoIOSXECLICodec

        text = self._HEAD + "banner motd ^C\nswitch 3 provision c9300-48p\n^C\n" + self._STACK_LINES + self._BODY
        assert CiscoIOSXECLICodec().parse(text).dropped_tier3_sections == self._ROWS

    @pytest.mark.parametrize("target", ["cisco_iosxe_cli", "aruba_aoss"])
    def test_the_lines_change_nothing_but_the_rows(self, target: str) -> None:
        """The output is the same as without the lines, onto the
        Catalyst's own codec as onto another vendor's; so is the status;
        and the job says which lines it left out."""
        with_lines = _job("cisco_iosxe_cli", target, self._HEAD + self._STACK_LINES + self._BODY)
        without = _job("cisco_iosxe_cli", target, self._HEAD + self._BODY)
        assert with_lines.status == without.status, with_lines.error
        assert with_lines.rendered == without.rendered
        assert _only_in(with_lines, without) == self._ROWS

    @pytest.mark.parametrize("target", ["cisco_iosxe_cli", "arista_eos"])
    def test_a_pairs_lines_change_nothing_but_the_rows(self, target: str) -> None:
        with_lines = _job("cisco_iosxe_cli", target, self._PAIR)
        without = _job("cisco_iosxe_cli", target, self._pair_without())
        assert with_lines.status == without.status, with_lines.error
        assert with_lines.rendered == without.rendered
        assert _only_in(with_lines, without) == self._PAIR_ROWS

    def test_the_committed_captures(self) -> None:
        """Every ``switch N provision`` line of a committed IOS-XE capture
        is a row of its parse -- found by reading each line, not by the
        pattern under test."""
        from netcanon.migration.codecs.cisco_iosxe_cli.codec import CiscoIOSXECLICodec

        corpus = Path(__file__).resolve().parents[2] / "fixtures" / "real" / "cisco_iosxe"
        checked = 0
        for path in sorted(corpus.glob("*.txt")):
            raw = path.read_text(encoding="utf-8", errors="replace")
            lines = [
                line.strip() for line in raw.splitlines()
                if line[:1] not in (" ", "\t") and line.split()[:1] == ["switch"]
                and line.split()[2:3] == ["provision"]
            ]
            if not lines:
                continue
            checked += 1
            rows = CiscoIOSXECLICodec().parse(raw).dropped_tier3_sections
            assert [line for line in lines if line not in rows] == [], path.name
        assert checked, "no committed IOS-XE capture has a `switch N provision` line"


class TestArubaAOSSStack:
    """An AOS-S stack's stanza (``stacking``, a 2930M's; ``vsf``, a
    2930F's) and the ``oobm`` stanza were dropped with no row: the
    parser reads nothing of them.  Each is a row now, by its word: a
    member's lines in it carry the member's MAC address, which a row
    -- painted on a page and returned to every client -- does not
    show."""

    _HEAD = 'hostname "sw"\n'
    _STACK = (
        "stacking\n"
        '   member 1 type "JL323A" mac-address 000000-000001\n'
        "   member 1 priority 255\n"
        "   member 1 flexible-module A type JL083A\n"
        "   exit\n"
    )
    _OOBM = (
        "oobm\n"
        "   ip address dhcp-bootp\n"
        "   member 1\n"
        "      ip address dhcp-bootp\n"
        "      exit\n"
        "   exit\n"
    )
    _FABRIC = (
        "vsf\n"
        "   enable domain 1\n"
        "   member 1\n"
        '      type "JL259A" mac-address 000000-000002\n'
        "      priority 255\n"
        "      exit\n"
        "   exit\n"
    )
    _BODY = (
        "vlan 1\n"
        '   name "DEFAULT_VLAN"\n'
        "   untagged 1/1-1/4\n"
        "   exit\n"
    )

    @staticmethod
    def _flat(text: str) -> str:
        return "".join(line.lstrip(" ") for line in text.splitlines(keepends=True))

    def test_a_stack_and_its_oobm(self) -> None:
        text = self._HEAD + self._STACK + self._OOBM + self._BODY
        assert detect_tier3_sections_aoss(text) == ["stacking", "oobm"]

    def test_a_fabric(self) -> None:
        assert detect_tier3_sections_aoss(self._HEAD + self._FABRIC + self._BODY) == ["vsf"]

    def test_without_its_indentation(self) -> None:
        """The device takes a context by its commands, not by its
        indentation; a member's line at the margin is still no row."""
        text = self._flat(self._HEAD + self._STACK + self._OOBM + self._FABRIC + self._BODY)
        assert detect_tier3_sections_aoss(text) == ["stacking", "oobm", "vsf"]

    def test_crlf_text(self) -> None:
        text = (self._HEAD + self._STACK + self._OOBM + self._BODY).replace("\n", "\r\n")
        assert detect_tier3_sections_aoss(text) == ["stacking", "oobm"]

    def test_the_iosxe_sections_still_come_first(self) -> None:
        text = self._HEAD + "ip access-list extended LOCK\n" + self._OOBM + self._BODY
        assert detect_tier3_sections_aoss(text) == ["ip access-list extended LOCK", "oobm"]

    @pytest.mark.parametrize(
        "text",
        [
            'vlan 10\n   name "vsf"\n   exit\n',
            'snmp-server community "stacking"\n',
            'interface 1/1\n   name "oobm link"\n   exit\n',
            "stacking-port 1\n",
        ],
        ids=["a VLAN's name", "a community", "a port's name", "another word"],
    )
    def test_what_is_not_a_stack_stanza(self, text: str) -> None:
        assert detect_tier3_sections_aoss(text) == []

    def test_the_codec_lists_them_and_not_a_banners(self) -> None:
        from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec

        text = (
            self._HEAD + 'banner motd "Welcome\nvsf\noobm\n"\n'
            + self._STACK + self._OOBM + self._BODY
        )
        rows = ArubaAOSSCodec().parse(text).dropped_tier3_sections
        assert rows == ["stacking", "oobm"]

    @pytest.mark.parametrize("target", ["aruba_aoss", "aruba_aoscx", "cisco_iosxe_cli"])
    def test_the_stanzas_change_nothing_but_the_rows(self, target: str) -> None:
        with_lines = _job("aruba_aoss", target, self._HEAD + self._STACK + self._OOBM + self._BODY)
        without = _job("aruba_aoss", target, self._HEAD + self._BODY)
        assert with_lines.status == without.status, with_lines.error
        assert with_lines.rendered == without.rendered
        assert _only_in(with_lines, without) == ["stacking", "oobm"]

    def test_the_committed_captures(self) -> None:
        """Each stanza a committed AOS-S capture opens at the margin is a
        row of its parse, found by reading each line; and no row shows a
        member's line."""
        from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec

        corpus = Path(__file__).resolve().parents[2] / "fixtures" / "real" / "aruba_aoss"
        checked = 0
        for path in sorted(corpus.glob("*.cfg")):
            raw = path.read_text(encoding="utf-8", errors="replace")
            words = {
                line.split()[0].lower() for line in raw.splitlines()
                if line[:1] not in (" ", "\t", "") and line.split()[0].lower() in ("stacking", "vsf", "oobm")
            }
            if not words:
                continue
            checked += 1
            rows = ArubaAOSSCodec().parse(raw).dropped_tier3_sections
            assert sorted(words - set(rows)) == [], path.name
            assert not [row for row in rows if "mac-address" in row or "member" in row], path.name
        assert checked >= 2, "fewer committed AOS-S captures than expected open such a stanza"


# ---------------------------------------------------------------------------
# The rows for statements a parser read and left out
# ---------------------------------------------------------------------------


class TestRowsForStatementsLeftOut:
    """Each kind of statement a device holds and does not run has a
    row that begins with its own word.  Two readers tell such a row
    from a section by that word: ``is_left_out_row`` and the migrate
    page."""

    _KINDS = sorted(_tier3_detection._LEFT_OUT)

    def test_the_kinds(self) -> None:
        assert self._KINDS == ["delete", "inactive", "preconfigure", "untagged"]

    @pytest.mark.parametrize("kind", _KINDS)
    def test_a_row_of_each_kind_is_told_apart(self, kind: str) -> None:
        row = left_out_row(kind, ("interface", "TenGigE0/0/0/12"))
        assert row.startswith(f"{kind}: interface TenGigE0/0/0/12 (")
        assert row.endswith("; not translated)")
        assert is_left_out_row(row)

    def test_a_header_line_is_a_section(self) -> None:
        assert not is_left_out_row("interface preconfigure TenGigE0/0/0/12")
        assert not is_left_out_row("interface range GigabitEthernet1/0/2 - 3")

    def test_the_last_row_begins_as_asked(self) -> None:
        """Past the bound one row counts the rest.  It begins with the
        word of the kind the caller names, which for a config that has
        no deactivated statement is not ``inactive:``."""
        held = [("preconfigure", ("interface", f"TenGigE0/0/0/{n}")) for n in range(LEFT_OUT_ROWS_SHOWN + 3)]
        rows = left_out_rows(held, rest="preconfigure")
        assert len(rows) == LEFT_OUT_ROWS_SHOWN + 1
        assert rows[-1] == "preconfigure: ... (3 more statements left out; not listed)"
        assert left_out_rows(held)[-1] == "inactive: ... (3 more statements left out; not listed)"
        assert all(is_left_out_row(row) for row in rows)

    @pytest.mark.parametrize("kind", _KINDS)
    def test_the_page_knows_each_kinds_word(self, kind: str) -> None:
        """The page counts sections, and says of the other rows what
        they are: a kind it does not know is counted as a section to
        apply by hand."""
        page = (
            Path(__file__).resolve().parents[3] / "netcanon" / "templates" / "migrate.html"
        ).read_text(encoding="utf-8")
        prefix = _tier3_detection._LEFT_OUT[kind][0]
        assert f"label.indexOf('{prefix}') === 0" in page
        assert f"<code>{prefix.strip()}</code>" in page
