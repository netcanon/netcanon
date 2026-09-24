"""Unit tests for ``netcanon.migration._tier3_detection``.

Pin the per-vendor detector behaviour against synthetic fixtures so the
"detected in source but not translated" banner has stable inputs.
False positives are preferred to false negatives — every test here
asserts on EXACT label content for the synthetic stanzas the parser
genuinely drops.
"""

from __future__ import annotations

import pytest

from netcanon.migration._tier3_detection import (
    detect_tier3_sections_dellos10,
    detect_tier3_sections_fortios,
    detect_tier3_sections_iosxe_cli,
    detect_tier3_sections_iosxe_xml,
    detect_tier3_sections_junos,
    detect_tier3_sections_opnsense,
    detect_tier3_sections_routeros,
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
