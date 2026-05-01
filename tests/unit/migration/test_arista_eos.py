"""
Unit tests for the Arista EOS codec.

Covers parse + render + round-trip + port-name identity + probe on
synthetic grammar snippets.  Real-capture parse is exercised separately
by ``test_real_captures.py`` against
``tests/fixtures/real/arista_eos/``.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalLocalUser,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from netconfig.migration.codecs.arista_eos import AristaEOSCodec
from netconfig.migration.codecs.arista_eos.port_names import (
    classify_port_name,
    format_port_identity,
)
from netconfig.migration.codecs.base import ParseError, RenderError

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Parse — top-level scalars
# ---------------------------------------------------------------------------


class TestParseScalars:
    def test_hostname(self):
        intent = AristaEOSCodec().parse("hostname sw-edge-01\n")
        assert intent.hostname == "sw-edge-01"

    def test_dns_servers(self):
        raw = (
            "hostname sw1\n"
            "ip name-server vrf default 10.0.0.1\n"
            "ip name-server vrf default 10.0.0.2\n"
            "dns domain example.com\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert intent.dns_servers == ["10.0.0.1", "10.0.0.2"]
        assert intent.domain == "example.com"

    def test_ntp_servers(self):
        raw = (
            "hostname sw1\n"
            "ntp server 10.0.0.1\n"
            "ntp server 10.0.0.2\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert intent.ntp_servers == ["10.0.0.1", "10.0.0.2"]

    def test_static_route(self):
        raw = (
            "hostname sw1\n"
            "ip route 0.0.0.0/0 10.0.0.1\n"
            "ip route 192.168.1.0/24 10.0.0.2\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert len(intent.static_routes) == 2
        assert intent.static_routes[0].destination == "0.0.0.0/0"
        assert intent.static_routes[0].gateway == "10.0.0.1"

    def test_interface_form_next_hop_ignored(self):
        """``ip route 10.0.0.0/8 Null0`` — interface-form next hops
        aren't IPs; parser drops them rather than store 'Null0' as a
        gateway."""
        raw = (
            "hostname sw1\n"
            "ip route 10.0.0.0/8 Null0\n"
            "ip route 0.0.0.0/0 10.0.0.1\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert len(intent.static_routes) == 1
        assert intent.static_routes[0].gateway == "10.0.0.1"


# ---------------------------------------------------------------------------
# Parse — SNMP
# ---------------------------------------------------------------------------


class TestParseSnmp:
    def test_snmp_community_ro(self):
        raw = (
            "hostname sw1\n"
            "snmp-server community public ro\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert intent.snmp is not None
        assert intent.snmp.community == "public"

    def test_snmp_community_first_match_wins(self):
        """EOS permits multiple community lines.  First one wins."""
        raw = (
            "hostname sw1\n"
            "snmp-server community primary ro\n"
            "snmp-server community secondary rw\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert intent.snmp.community == "primary"

    def test_snmp_location_contact(self):
        raw = (
            "hostname sw1\n"
            'snmp-server location DC1-rack-4\n'
            "snmp-server contact netops@example.com\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert intent.snmp.location == "DC1-rack-4"
        assert intent.snmp.contact == "netops@example.com"

    def test_snmp_trap_hosts(self):
        raw = (
            "hostname sw1\n"
            "snmp-server community public ro\n"
            "snmp-server host 10.0.0.50\n"
            "snmp-server host 10.0.0.51\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert intent.snmp.trap_hosts == ["10.0.0.50", "10.0.0.51"]


# ---------------------------------------------------------------------------
# Parse — local users
# ---------------------------------------------------------------------------


class TestParseUsers:
    def test_username_with_role_nopassword(self):
        raw = (
            "hostname sw1\n"
            "username admin privilege 15 role network-admin nopassword\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert len(intent.local_users) == 1
        u = intent.local_users[0]
        assert u.name == "admin"
        assert u.privilege_level == 15
        assert u.role == "network-admin"
        assert u.hashed_password == ""

    def test_username_with_sha512_hash(self):
        raw = (
            "hostname sw1\n"
            "username backup privilege 15 secret sha512 $6$abcdef$ghijkl\n"
        )
        intent = AristaEOSCodec().parse(raw)
        u = intent.local_users[0]
        assert u.name == "backup"
        # Vendor-tagged: ``arista:sha512:$6$...`` — interior colon is
        # the canonical delimiter.
        assert u.hashed_password == "arista:sha512:$6$abcdef$ghijkl"

    def test_username_default_privilege_is_1(self):
        raw = (
            "hostname sw1\n"
            "username lowpriv secret 5 $1$foo$bar\n"
        )
        intent = AristaEOSCodec().parse(raw)
        u = intent.local_users[0]
        assert u.privilege_level == 1
        assert u.hashed_password == "arista:5:$1$foo$bar"

    def test_multiple_users_no_line_bleed(self):
        """Critical regression: ``\\s`` in the username regex was
        consuming ``\\nusername`` from the next line, causing the
        following user to disappear from finditer.  Fixed by using
        ``[^\\S\\n]`` (non-newline whitespace) inside the pwmode
        alternation.  This test locks the fix in."""
        raw = (
            "hostname sw1\n"
            "username a privilege 15 secret sha512 $6$aaa$aaaaaaaaaa\n"
            "username b privilege 15 secret sha512 $6$bbb$bbbbbbbbbb\n"
            "username c privilege 15 secret sha512 $6$ccc$cccccccccc\n"
            "username d privilege 15 nopassword\n"
        )
        intent = AristaEOSCodec().parse(raw)
        names = [u.name for u in intent.local_users]
        assert names == ["a", "b", "c", "d"], (
            f"expected 4 users in order; got {names} — the regex is "
            "bleeding across newlines again"
        )


# ---------------------------------------------------------------------------
# Parse — interfaces + VLANs
# ---------------------------------------------------------------------------


class TestParseInterfaces:
    def test_interface_ethernet_l3(self):
        raw = (
            "hostname sw1\n"
            "interface Ethernet1\n"
            "   description uplink\n"
            "   no switchport\n"
            "   ip address 10.0.0.1/31\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert len(intent.interfaces) == 1
        iface = intent.interfaces[0]
        assert iface.name == "Ethernet1"
        assert iface.description == "uplink"
        assert len(iface.ipv4_addresses) == 1
        assert iface.ipv4_addresses[0].ip == "10.0.0.1"
        assert iface.ipv4_addresses[0].prefix_length == 31

    def test_interface_loopback(self):
        raw = (
            "hostname sw1\n"
            "interface Loopback0\n"
            "   ip address 172.16.0.1/32\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = intent.interfaces[0]
        assert iface.name == "Loopback0"
        assert iface.interface_type == "ianaift:softwareLoopback"

    def test_interface_shutdown(self):
        raw = (
            "hostname sw1\n"
            "interface Ethernet5\n"
            "   shutdown\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = intent.interfaces[0]
        assert iface.enabled is False

    def test_interface_quoted_description(self):
        raw = (
            "hostname sw1\n"
            "interface Ethernet1\n"
            '   description "switch2 uplink port"\n'
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = intent.interfaces[0]
        assert iface.description == "switch2 uplink port"

    def test_vlan_stanza_with_name(self):
        raw = (
            "hostname sw1\n"
            "vlan 10\n"
            "   name USERS\n"
            "!\n"
            "vlan 20\n"
            "   name VOICE\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert len(intent.vlans) == 2
        assert intent.vlans[0].id == 10
        assert intent.vlans[0].name == "USERS"
        assert intent.vlans[1].id == 20
        assert intent.vlans[1].name == "VOICE"

    def test_switchport_access(self):
        raw = (
            "hostname sw1\n"
            "interface Ethernet1\n"
            "   switchport access vlan 10\n"
            "   switchport mode access\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = intent.interfaces[0]
        assert iface.access_vlan == 10
        assert iface.switchport_mode == "access"

    def test_switchport_trunk_allowed(self):
        raw = (
            "hostname sw1\n"
            "interface Ethernet1\n"
            "   switchport mode trunk\n"
            "   switchport trunk allowed vlan 10,20,30-32\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = intent.interfaces[0]
        assert iface.switchport_mode == "trunk"
        assert iface.trunk_allowed_vlans == [10, 20, 30, 31, 32]

    def test_channel_group_creates_lag(self):
        raw = (
            "hostname sw1\n"
            "interface Ethernet1\n"
            "   channel-group 1 mode active\n"
            "!\n"
            "interface Ethernet2\n"
            "   channel-group 1 mode active\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert len(intent.lags) == 1
        lag = intent.lags[0]
        assert lag.name == "Port-Channel1"
        assert sorted(lag.members) == ["Ethernet1", "Ethernet2"]
        # Reverse-linking fires.
        for iface in intent.interfaces:
            assert iface.lag_member_of == "Port-Channel1"


# ---------------------------------------------------------------------------
# Parse — input validation
# ---------------------------------------------------------------------------


class TestParseValidation:
    def test_empty_input_raises(self):
        with pytest.raises(ParseError, match="empty"):
            AristaEOSCodec().parse("")

    def test_xml_input_rejected(self):
        with pytest.raises(ParseError, match="XML"):
            AristaEOSCodec().parse("<config/>")

    def test_json_input_rejected(self):
        with pytest.raises(ParseError, match="JSON"):
            AristaEOSCodec().parse('{"a": 1}')


# ---------------------------------------------------------------------------
# Render + round-trip
# ---------------------------------------------------------------------------


class TestRender:
    def test_render_minimal(self):
        intent = CanonicalIntent(hostname="sw1")
        out = AristaEOSCodec().render(intent)
        assert "hostname sw1" in out
        assert out.rstrip().endswith("end")

    def test_render_rejects_non_canonical(self):
        with pytest.raises(RenderError):
            AristaEOSCodec().render({"not": "canonical"})

    def test_render_interface_l3_emits_no_switchport(self):
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(
                    name="Ethernet1",
                    description="uplink",
                    ipv4_addresses=[
                        CanonicalIPv4Address(
                            ip="10.0.0.1", prefix_length=31,
                        ),
                    ],
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "interface Ethernet1" in out
        assert "no switchport" in out
        assert "ip address 10.0.0.1/31" in out

    def test_render_user_with_hash_roundtrips(self):
        intent = CanonicalIntent(
            hostname="sw1",
            local_users=[
                CanonicalLocalUser(
                    name="admin",
                    privilege_level=15,
                    role="network-admin",
                    hashed_password="arista:sha512:$6$abc$def",
                ),
            ],
        )
        codec = AristaEOSCodec()
        out = codec.render(intent)
        assert "username admin privilege 15 role network-admin secret sha512 $6$abc$def" in out
        # Round-trip: re-parse preserves the hash.
        tree2 = codec.parse(out)
        assert tree2.local_users[0].hashed_password == (
            "arista:sha512:$6$abc$def"
        )

    def test_render_lag_member_emits_channel_group(self):
        """Regression guard for the LAG round-trip bug surfaced by the
        batfish DC1-LEAF2A EVPN fixture (GAP 3).

        Before the fix: render emitted ``interface Port-Channel3``
        stubs but did NOT emit ``channel-group 3 mode active`` on the
        member Ethernet interfaces.  The canonical tree carried both
        ``tree.lags[].members`` AND each member's ``lag_member_of``;
        the render loop only consumed the lag list, leaving the member
        side silent.  Re-parse then produced zero LAGs because Arista
        LAGs are synthesised from ``channel-group`` lines on members.
        """
        raw = (
            "! device: sw1 (DCS-7050SX-64, EOS-4.23.0F)\n"
            "hostname sw1\n"
            "!\n"
            "interface Ethernet3\n"
            "   channel-group 3 mode active\n"
            "!\n"
            "interface Ethernet4\n"
            "   channel-group 3 mode active\n"
            "!\n"
            "interface Port-Channel3\n"
            "!\n"
            "end\n"
        )
        codec = AristaEOSCodec()
        first = codec.parse(raw)
        assert len(first.lags) == 1
        assert first.lags[0].name == "Port-Channel3"
        assert set(first.lags[0].members) == {"Ethernet3", "Ethernet4"}
        # Render must emit channel-group on the member side so re-parse
        # reconstructs the same LAG.
        rendered = codec.render(first)
        assert "channel-group 3 mode active" in rendered
        # Round-trip stability.
        second = codec.parse(rendered)
        assert len(second.lags) == 1
        assert second.lags[0].name == "Port-Channel3"
        assert set(second.lags[0].members) == {"Ethernet3", "Ethernet4"}

    def test_render_lag_member_mode_normalised(self):
        """Canonical LAG modes map to EOS CLI tokens:
        ``static`` → ``on``, ``passive`` → ``passive``,
        everything else (including ``active``) → ``active``.
        """
        from netconfig.migration.canonical.intent import CanonicalLAG
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(
                    name="Ethernet1",
                    lag_member_of="Port-Channel1",
                ),
            ],
            lags=[
                CanonicalLAG(
                    name="Port-Channel1",
                    members=["Ethernet1"],
                    mode="static",
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "channel-group 1 mode on" in out


class TestVxlanSourceInterfaceUdpPort:
    """GAP-EVPN-2: ``vxlan source-interface`` + ``vxlan udp-port`` are
    switch-level globals that apply to every CanonicalVxlan record."""

    def test_parse_default_source_interface_and_udp_port(self):
        raw = (
            "vlan 100\n"
            "   name Tenant_100\n"
            "!\n"
            "interface Vxlan1\n"
            "   vxlan source-interface Loopback0\n"
            "   vxlan udp-port 4789\n"
            "   vxlan vlan 100 vni 100\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert len(intent.vxlan_vnis) == 1
        rec = intent.vxlan_vnis[0]
        assert rec.vlan_id == 100
        assert rec.vni == 100
        assert rec.source_interface == "Loopback0"
        assert rec.udp_port == 4789

    def test_parse_non_default_source_interface_back_patches_records(self):
        # Source-interface declared AFTER VNI mapping (rare but legal).
        # Tests the back-patch path: the record was emitted before
        # the source-interface line was scanned.
        raw = (
            "vlan 110\n"
            "   name V110\n"
            "!\n"
            "interface Vxlan1\n"
            "   vxlan vlan 110 vni 10110\n"
            "   vxlan source-interface Loopback1\n"
            "   vxlan udp-port 8472\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert len(intent.vxlan_vnis) == 1
        rec = intent.vxlan_vnis[0]
        assert rec.source_interface == "Loopback1"
        assert rec.udp_port == 8472

    def test_parse_multi_vni_inherits_switch_level_settings(self):
        raw = (
            "interface Vxlan1\n"
            "   vxlan source-interface Loopback99\n"
            "   vxlan udp-port 4789\n"
            "   vxlan vlan 10 vni 1010\n"
            "   vxlan vlan 20 vni 1020\n"
            "   vxlan vlan 30 vni 1030\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert len(intent.vxlan_vnis) == 3
        for rec in intent.vxlan_vnis:
            assert rec.source_interface == "Loopback99"
            assert rec.udp_port == 4789

    def test_render_uses_recorded_values(self):
        from netconfig.migration.canonical.intent import CanonicalVxlan
        intent = CanonicalIntent(
            vlans=[CanonicalVlan(id=100, name="V100")],
            vxlan_vnis=[CanonicalVxlan(
                vlan_id=100, vni=10100,
                source_interface="Loopback99",
                udp_port=8472,
            )],
        )
        out = AristaEOSCodec().render(intent)
        assert "interface Vxlan1" in out
        assert "vxlan source-interface Loopback99" in out
        assert "vxlan udp-port 8472" in out
        assert "vxlan vlan 100 vni 10100" in out

    def test_render_falls_back_to_defaults_when_unset(self):
        from netconfig.migration.canonical.intent import CanonicalVxlan
        intent = CanonicalIntent(
            vlans=[CanonicalVlan(id=100, name="V100")],
            vxlan_vnis=[CanonicalVxlan(vlan_id=100, vni=10100)],
        )
        out = AristaEOSCodec().render(intent)
        assert "vxlan source-interface Loopback0" in out
        assert "vxlan udp-port 4789" in out

    def test_round_trip_preserves_vxlan_globals(self):
        raw = (
            "interface Vxlan1\n"
            "   vxlan source-interface Loopback1\n"
            "   vxlan udp-port 4789\n"
            "   vxlan vlan 110 vni 10110\n"
            "   vxlan vlan 120 vni 10120\n"
            "!\n"
        )
        codec = AristaEOSCodec()
        first = codec.parse(raw)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        assert len(second.vxlan_vnis) == 2
        for rec in second.vxlan_vnis:
            assert rec.source_interface == "Loopback1"
            assert rec.udp_port == 4789


class TestRoundTrip:
    """Full parse → render → parse idempotency on realistic snippets."""

    def test_round_trip_full_snippet(self):
        raw = (
            "! Command: show running-config\n"
            "! device: sw1 (DCS-7050SX-64, EOS-4.27.0F)\n"
            "!\n"
            "hostname sw1\n"
            "ip name-server vrf default 10.0.0.1\n"
            "ntp server 10.0.0.1\n"
            "snmp-server community public ro\n"
            "username admin privilege 15 role network-admin nopassword\n"
            "!\n"
            "vlan 10\n"
            "   name USERS\n"
            "!\n"
            "vlan 20\n"
            "   name VOICE\n"
            "!\n"
            "interface Ethernet1\n"
            "   description uplink\n"
            "   no switchport\n"
            "   ip address 10.0.0.1/31\n"
            "!\n"
            "interface Loopback0\n"
            "   ip address 172.16.0.1/32\n"
            "!\n"
            "ip route 0.0.0.0/0 10.0.0.2\n"
            "!\n"
            "end\n"
        )
        codec = AristaEOSCodec()
        tree1 = codec.parse(raw)
        out = codec.render(tree1)
        tree2 = codec.parse(out)
        assert tree1.hostname == tree2.hostname
        assert [i.name for i in tree1.interfaces] == [
            i.name for i in tree2.interfaces
        ]
        assert [v.id for v in tree1.vlans] == [v.id for v in tree2.vlans]
        assert len(tree1.local_users) == len(tree2.local_users)
        assert len(tree1.static_routes) == len(tree2.static_routes)
        assert (
            tree1.snmp.community if tree1.snmp else ""
        ) == (
            tree2.snmp.community if tree2.snmp else ""
        )


# ---------------------------------------------------------------------------
# port_names identity bridge
# ---------------------------------------------------------------------------


class TestPortNames:
    def test_classify_ethernet_flat(self):
        ident = classify_port_name("Ethernet1")
        assert ident.kind == "physical"
        assert ident.port == 1

    def test_classify_ethernet_breakout(self):
        ident = classify_port_name("Ethernet50/3")
        assert ident.kind == "breakout"
        assert ident.port == 50
        assert ident.breakout_lane == 3
        assert ident.breakout_parent == "Ethernet50"

    def test_classify_management(self):
        ident = classify_port_name("Management1")
        assert ident.kind == "mgmt"
        assert ident.port == 1

    def test_classify_loopback(self):
        ident = classify_port_name("Loopback0")
        assert ident.kind == "loopback"
        assert ident.index == 0

    def test_classify_port_channel_caps(self):
        """Arista uses capital 'C' in Port-Channel.  Classifier must
        be case-insensitive on input but producers emit canonical
        caps."""
        ident = classify_port_name("Port-Channel5")
        assert ident.kind == "lag"
        assert ident.index == 5
        ident = classify_port_name("port-channel5")
        assert ident.kind == "lag"

    def test_classify_vlan_svi(self):
        ident = classify_port_name("Vlan100")
        assert ident.kind == "svi"
        assert ident.index == 100

    def test_classify_unknown_returns_unknown_kind(self):
        ident = classify_port_name("SomethingWeird42")
        assert ident.kind == "unknown"

    def test_format_physical_roundtrip(self):
        ident = classify_port_name("Ethernet7")
        assert format_port_identity(ident) == "Ethernet7"

    def test_format_breakout_roundtrip(self):
        ident = classify_port_name("Ethernet50/2")
        assert format_port_identity(ident) == "Ethernet50/2"

    def test_format_lag_emits_capital_c(self):
        """Canonical rendering uses ``Port-Channel`` (capital C),
        distinct from Cisco's ``Port-channel`` convention."""
        ident = classify_port_name("port-channel3")
        assert format_port_identity(ident) == "Port-Channel3"

    def test_format_cross_vendor_physical(self):
        """Cisco ``GigabitEthernet1/0/24`` parsed by Cisco codec
        then rendered on Arista — stack + module get dropped,
        port becomes the flat ``Ethernet24``.  Documented
        behaviour (operator may have to disambiguate via the
        rename modal)."""
        from netconfig.migration.codecs.cisco_iosxe_cli.port_names import (
            classify_port_name as cisco_classify,
        )
        cisco_ident = cisco_classify("GigabitEthernet1/0/24")
        arista_name = format_port_identity(cisco_ident)
        assert arista_name == "Ethernet24"


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


class TestProbe:
    def test_eos_banner_strong_signal(self):
        raw = (
            "! Command: show running-config\n"
            "! device: sw1 (DCS-7050SX-64, EOS-4.27.0F)\n"
            "!\n"
            "hostname sw1\n"
        )
        result = AristaEOSCodec.probe(raw)
        assert result is not None
        score, reason = result
        assert score >= 95
        assert "EOS" in reason

    def test_grammar_markers_moderate_signal(self):
        raw = (
            "daemon TerminAttr\n"
            "   no shutdown\n"
            "!\n"
            "interface Ethernet1\n"
            "interface Port-Channel1\n"
            "management api http-commands\n"
        )
        result = AristaEOSCodec.probe(raw)
        assert result is not None
        score, _ = result
        assert score >= 90  # 3+ markers

    def test_no_signal_returns_none(self):
        raw = "hostname router1\ninterface GigabitEthernet0/0\n"
        # Cisco-ish grammar — Arista probe shouldn't claim it.
        result = AristaEOSCodec.probe(raw)
        # Could return None or a low partial-match — either is fine
        # as long as it's not a strong signal.
        if result is not None:
            score, _ = result
            assert score < 90

    def test_xml_input_returns_none(self):
        assert AristaEOSCodec.probe("<config/>") is None

    def test_json_input_returns_none(self):
        assert AristaEOSCodec.probe("{\"a\": 1}") is None
