"""
Unit tests for the Arista EOS codec.

Covers parse + render + round-trip + port-name identity + probe on
synthetic grammar snippets.  Real-capture parse is exercised separately
by ``test_real_captures.py`` against
``tests/fixtures/real/arista_eos/``.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalLocalUser,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVRRPGroup,
)
from netcanon.migration.codecs.arista_eos import AristaEOSCodec
from netcanon.migration.codecs.arista_eos.port_names import (
    classify_port_name,
    format_port_identity,
)
from netcanon.migration.codecs.base import ParseError, RenderError

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
        from netcanon.migration.canonical.intent import CanonicalLAG
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
        from netcanon.migration.canonical.intent import CanonicalVxlan
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
        from netcanon.migration.canonical.intent import CanonicalVxlan
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


class TestBgpVlanMacVrf:
    """GAP-EVPN-1: ``router bgp <asn> / vlan <N> / rd ... /
    route-target both ...`` is the per-VLAN EVPN MAC-VRF binding form.
    Populates a CanonicalRoutingInstance keyed by the matching
    CanonicalVlan.name with ``instance_type="mac-vrf"``."""

    def test_parse_bgp_vlan_mac_vrf_minimal(self):
        raw = (
            "vlan 100\n"
            "   name Tenant_100\n"
            "!\n"
            "router bgp 65033\n"
            "   router-id 10.0.255.33\n"
            "   !\n"
            "   vlan 100\n"
            "      rd 10.0.255.33:100\n"
            "      route-target both 65000:100\n"
            "      redistribute learned\n"
            "   !\n"
        )
        intent = AristaEOSCodec().parse(raw)
        ri = next(
            (r for r in intent.routing_instances if r.name == "Tenant_100"),
            None,
        )
        assert ri is not None, (
            f"Expected MAC-VRF for VLAN 100 with name Tenant_100; "
            f"got {[r.name for r in intent.routing_instances]}"
        )
        assert ri.instance_type == "mac-vrf"
        assert ri.route_distinguisher == "10.0.255.33:100"
        assert ri.rt_imports == ["65000:100"]
        assert ri.rt_exports == ["65000:100"]

    def test_parse_bgp_vlan_unnamed_vlan_uses_synthetic_name(self):
        # CanonicalVlan with no name → routing-instance keyed
        # ``VLAN<N>`` synthetic-form so render can reverse-resolve.
        raw = (
            "vlan 200\n"
            "!\n"
            "router bgp 65000\n"
            "   !\n"
            "   vlan 200\n"
            "      rd 1.1.1.1:200\n"
            "      route-target both 65000:200\n"
            "   !\n"
        )
        intent = AristaEOSCodec().parse(raw)
        ri = next(
            (r for r in intent.routing_instances if r.name == "VLAN200"),
            None,
        )
        assert ri is not None
        assert ri.instance_type == "mac-vrf"
        assert ri.route_distinguisher == "1.1.1.1:200"

    def test_parse_bgp_vlan_does_not_match_inside_vlan_aware_bundle(self):
        # Per-VLAN EVPN form must NOT spawn spurious MAC-VRF entries
        # from nested ``vlan <N>`` lines under
        # ``vlan-aware-bundle <NAME> / vlan <N|range>`` (a deeper indent
        # form that is NOT a top-level router-bgp sub-stanza).
        raw = (
            "vlan 110\n"
            "   name V110\n"
            "!\n"
            "vlan 111\n"
            "   name V111\n"
            "!\n"
            "router bgp 65000\n"
            "   !\n"
            "   vlan-aware-bundle MyBundle\n"
            "      rd 1.1.1.1:111\n"
            "      route-target both 65000:111\n"
            "      vlan 110\n"
            "      vlan 111\n"
            "   !\n"
        )
        intent = AristaEOSCodec().parse(raw)
        # The vlan-aware-bundle form is parse-and-ignore today, but
        # the inner ``vlan 110`` / ``vlan 111`` lines must NOT
        # surface as MAC-VRF entries.
        names = [r.name for r in intent.routing_instances]
        assert "V110" not in names
        assert "V111" not in names
        assert "VLAN110" not in names
        assert "VLAN111" not in names

    def test_parse_bgp_vlan_separate_import_export(self):
        raw = (
            "vlan 100\n"
            "   name Tenant_100\n"
            "!\n"
            "router bgp 65000\n"
            "   !\n"
            "   vlan 100\n"
            "      rd 1.1.1.1:100\n"
            "      route-target import evpn 65000:100\n"
            "      route-target export evpn 65000:200\n"
            "   !\n"
        )
        intent = AristaEOSCodec().parse(raw)
        ri = next(r for r in intent.routing_instances if r.name == "Tenant_100")
        assert ri.rt_imports == ["65000:100"]
        assert ri.rt_exports == ["65000:200"]

    def test_render_emits_bgp_vlan_block_for_mac_vrf(self):
        intent = CanonicalIntent(
            vlans=[CanonicalVlan(id=100, name="Tenant_100")],
            routing_instances=[
                __import__(
                    "netcanon.migration.canonical.intent",
                    fromlist=["CanonicalRoutingInstance"],
                ).CanonicalRoutingInstance(
                    name="Tenant_100",
                    instance_type="mac-vrf",
                    route_distinguisher="10.0.255.33:100",
                    rt_imports=["65000:100"],
                    rt_exports=["65000:100"],
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "router bgp 65000" in out
        assert "   vlan 100" in out
        assert "      rd 10.0.255.33:100" in out
        assert "      route-target both 65000:100" in out
        assert "      redistribute learned" in out
        # MAC-VRF is NOT an L3 VRF — must NOT emit ``vrf instance``.
        assert "vrf instance Tenant_100" not in out

    def test_render_skips_mac_vrf_when_no_matching_vlan(self):
        # Defensive: a MAC-VRF whose name doesn't match any vlan and
        # doesn't fit the synthetic VLAN<N> form gets skipped (no
        # garbage line emitted).
        from netcanon.migration.canonical.intent import (
            CanonicalRoutingInstance,
        )
        intent = CanonicalIntent(
            vlans=[],  # no vlan to reverse-look-up against
            routing_instances=[CanonicalRoutingInstance(
                name="Orphaned_Tenant",
                instance_type="mac-vrf",
                route_distinguisher="1.1.1.1:200",
                rt_imports=["65000:200"],
                rt_exports=["65000:200"],
            )],
        )
        out = AristaEOSCodec().render(intent)
        # Block should NOT be emitted (no resolvable vid).
        assert "vlan Orphaned_Tenant" not in out
        # And it must NOT appear as a vrf instance (not L3) — except
        # as a comment-stripped phrase nowhere.
        assert "vrf instance Orphaned_Tenant" not in out

    def test_round_trip_bgp_vlan_mac_vrf(self):
        raw = (
            "vlan 100\n"
            "   name Tenant_100\n"
            "!\n"
            "router bgp 65033\n"
            "   !\n"
            "   vlan 100\n"
            "      rd 10.0.255.33:100\n"
            "      route-target both 65000:100\n"
            "      redistribute learned\n"
            "   !\n"
        )
        codec = AristaEOSCodec()
        first = codec.parse(raw)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        ri_first = next(
            r for r in first.routing_instances if r.name == "Tenant_100"
        )
        ri_second = next(
            r for r in second.routing_instances if r.name == "Tenant_100"
        )
        assert ri_first.instance_type == ri_second.instance_type == "mac-vrf"
        assert ri_first.route_distinguisher == ri_second.route_distinguisher
        assert ri_first.rt_imports == ri_second.rt_imports
        assert ri_first.rt_exports == ri_second.rt_exports

    def test_multi_vlan_mac_vrf(self):
        raw = (
            "vlan 100\n"
            "   name V100\n"
            "!\n"
            "vlan 200\n"
            "   name V200\n"
            "!\n"
            "router bgp 65000\n"
            "   !\n"
            "   vlan 100\n"
            "      rd 1.1.1.1:100\n"
            "      route-target both 65000:100\n"
            "   !\n"
            "   vlan 200\n"
            "      rd 1.1.1.1:200\n"
            "      route-target both 65000:200\n"
            "   !\n"
        )
        intent = AristaEOSCodec().parse(raw)
        names = {r.name: r for r in intent.routing_instances}
        assert "V100" in names and "V200" in names
        assert names["V100"].instance_type == "mac-vrf"
        assert names["V200"].instance_type == "mac-vrf"
        assert names["V100"].route_distinguisher == "1.1.1.1:100"
        assert names["V200"].route_distinguisher == "1.1.1.1:200"

    def test_parse_l3_vrf_and_mac_vrf_coexist(self):
        # Mixed: ``vrf instance L3VRF`` + ``router bgp / vrf L3VRF``
        # block alongside ``router bgp / vlan 100`` MAC-VRF block.
        raw = (
            "vlan 100\n"
            "   name V100\n"
            "!\n"
            "vrf instance L3VRF\n"
            "!\n"
            "router bgp 65000\n"
            "   !\n"
            "   vrf L3VRF\n"
            "      rd 1.1.1.1:1\n"
            "      route-target both 65000:1\n"
            "   !\n"
            "   vlan 100\n"
            "      rd 1.1.1.1:100\n"
            "      route-target both 65000:100\n"
            "   !\n"
        )
        intent = AristaEOSCodec().parse(raw)
        l3 = next(r for r in intent.routing_instances if r.name == "L3VRF")
        mac = next(r for r in intent.routing_instances if r.name == "V100")
        assert l3.instance_type == "vrf"
        assert mac.instance_type == "mac-vrf"


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
        from netcanon.migration.codecs.cisco_iosxe_cli.port_names import (
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


# ---------------------------------------------------------------------------
# Cross-vendor hash gate (issue #1 in user_smoke_findings.md)
# ---------------------------------------------------------------------------


class TestCrossVendorHashGate:
    """Wave 2 hash-policy gate.  Foreign-source hashes that Arista's
    ``secret`` command cannot consume must NEVER reach the wire as
    payload — render falls back to a ``! password manager ...
    review:`` comment so the operator gets an explicit reset signal
    and the rendered config commits clean.

    Mirrors the existing FortiGate / Junos / OPNsense gates from
    Wave 2 (commit ``b2036aa`` is the cleanest model).
    """

    def test_arista_bcrypt_hash_emits_review_comment(self):
        """OPNsense-source bcrypt (``$2y$..``) cannot be consumed
        by EOS — render must elide the payload AND attach a review
        comment naming the algorithm.  Before Wave 2 this leaked as
        ``secret 5 bcrypt:$2y$..`` (CRITICAL security disclosure +
        wrong type tag)."""
        intent = CanonicalIntent(
            hostname="sw1",
            local_users=[
                CanonicalLocalUser(
                    name="root",
                    privilege_level=15,
                    role="user",
                    hashed_password="bcrypt:$2y$11$fakeBcryptHashForRootSyntheticOnly",
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        # Payload must NOT appear anywhere in the output.
        assert "$2y$" not in out, (
            "bcrypt payload leaked through the hash gate:\n" + out
        )
        assert "fakeBcryptHashForRoot" not in out
        # The bare prefix line is fine (no secret tag).
        assert "secret 5 bcrypt" not in out
        # Review comment must be present, in Arista (``!``) syntax.
        assert "! password manager" in out
        assert 'user-name "root"' in out
        assert "bcrypt" in out
        # Wave-4 follow-up (finding #16): the orphan ``username X
        # role Y`` declaration line is now dropped entirely.
        # Leaving it with no ``secret`` clause created a
        # passwordless account on commit, defeating the gate.  The
        # comment alone signals operator intent.  See the dedicated
        # regression guard in ``TestHashGateFullDrop`` below.
        assert "username root" not in out

    def test_arista_native_sha512_passes_through(self):
        """Native vendor-tagged ``arista:sha512:$6$..`` rounds
        trip via ``secret sha512 $6$..`` (existing behaviour — the
        gate must not regress this)."""
        intent = CanonicalIntent(
            hostname="sw1",
            local_users=[
                CanonicalLocalUser(
                    name="ops",
                    privilege_level=15,
                    role="network-admin",
                    hashed_password="arista:sha512:$6$abc$defghijkl",
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert (
            "username ops privilege 15 role network-admin "
            "secret sha512 $6$abc$defghijkl"
        ) in out
        assert "review:" not in out

    def test_arista_md5crypt_passes_through(self):
        """Native vendor-tagged ``arista:5:$1$..`` (md5crypt) emits
        ``secret 5 $1$..`` — the legitimate md5crypt path that the
        old ``secret 5 <anything>`` fallback was masquerading as."""
        intent = CanonicalIntent(
            hostname="sw1",
            local_users=[
                CanonicalLocalUser(
                    name="legacy",
                    privilege_level=1,
                    hashed_password="arista:5:$1$foo$barbazquux",
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "username legacy secret 5 $1$foo$barbazquux" in out
        assert "review:" not in out

    def test_arista_plaintext_emits_secret_zero(self):
        """A canonical plaintext password (no ``alg:`` separator)
        emits ``secret 0 <password>``, which is EOS's plaintext
        form (the device hashes on commit)."""
        intent = CanonicalIntent(
            hostname="sw1",
            local_users=[
                CanonicalLocalUser(
                    name="seeded",
                    privilege_level=1,
                    hashed_password="hunter2",
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "username seeded secret 0 hunter2" in out


# ---------------------------------------------------------------------------
# Empty-stub elision (issue #8 in user_smoke_findings.md)
# ---------------------------------------------------------------------------


class TestEmptyInterfaceStubElision:
    """Tiered policy mirroring Junos commit ``0fdf7e9``: skip empty
    interface stubs unless the iface (a) carries renderable content,
    (b) matches an Arista physical-port shape, or (c) is referenced
    elsewhere (VRF binding, vlan member list)."""

    def test_arista_foreign_port_stub_elided(self):
        """OPNsense ``igc0`` arriving via a cross-vendor render
        with no body must NOT appear in the Arista output — the
        EOS commit-time validator would reject ``interface igc0``
        as an unknown interface."""
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(name="igc0"),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "interface igc0" not in out

    def test_arista_native_port_with_no_body_kept(self):
        """An empty ``Ethernet0`` stub (operator-style placeholder)
        IS preserved — same-vendor round-trip stability requires
        the bare line so reparse restores the iface canonical."""
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(name="Ethernet1"),
                CanonicalInterface(name="Loopback0"),
                CanonicalInterface(name="Management1"),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "interface Ethernet1" in out
        assert "interface Loopback0" in out
        assert "interface Management1" in out

    def test_arista_vrf_referenced_foreign_port_kept(self):
        """A foreign-named iface bound to a VRF MUST keep its bare
        line so the EOS commit-time validator can resolve the
        VRF-binding line in the routed-block — even though the
        port name is non-native, the canonical tree wires the VRF
        membership through it."""
        from netcanon.migration.canonical.intent import (
            CanonicalRoutingInstance,
        )
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(
                    name="igc0",
                    vrf="WAN",
                ),
            ],
            routing_instances=[
                CanonicalRoutingInstance(
                    name="WAN",
                    instance_type="vrf",
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "interface igc0" in out
        assert "vrf WAN" in out

    def test_arista_vlan_member_foreign_port_kept(self):
        """A foreign-named iface that appears in a VLAN's
        tagged_ports list IS referenced from elsewhere — the
        L2 graph would break if we elided it."""
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(name="igc0"),
            ],
            vlans=[
                CanonicalVlan(
                    id=10,
                    name="USERS",
                    tagged_ports=["igc0"],
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "interface igc0" in out

    def test_arista_foreign_port_with_body_kept(self):
        """A foreign-named iface that DOES carry renderable
        content (description, IP, MTU, ...) is preserved — the
        elision rule only kicks in for fully empty stubs."""
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(
                    name="igc0",
                    description="WAN uplink",
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "interface igc0" in out
        assert "description WAN uplink" in out

    def test_arista_native_breakout_port_kept(self):
        """``Ethernet50/3`` (QSFP breakout child) is also a
        native shape — keep the bare line on round-trip."""
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(name="Ethernet50/3"),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "interface Ethernet50/3" in out


# ---------------------------------------------------------------------------
# Domain emit (issue #12 in user_smoke_findings.md)
# ---------------------------------------------------------------------------


class TestDomainEmit:
    """Canonical-side ``tree.domain`` must surface as Arista's
    ``dns domain <X>`` line so cross-vendor renders carrying a
    domain (e.g. OPNsense ``<domain>example.test</domain>``) don't
    silently drop it."""

    def test_arista_domain_emits_dns_domain_line(self):
        intent = CanonicalIntent(
            hostname="sw1",
            domain="example.test",
        )
        out = AristaEOSCodec().render(intent)
        assert "dns domain example.test" in out

    def test_arista_no_domain_emits_no_line(self):
        """Defensive: empty / unset domain should NOT emit a
        bare ``dns domain`` line."""
        intent = CanonicalIntent(hostname="sw1")
        out = AristaEOSCodec().render(intent)
        assert "dns domain" not in out


# ---------------------------------------------------------------------------
# Hash-gate full drop (issue #16 in user_smoke_findings.md)
# ---------------------------------------------------------------------------


class TestHashGateFullDrop:
    """Wave-4 fix: when an unmigratable hash hits the gate, the
    entire ``username X role Y`` declaration is dropped — only the
    review comment survives.  Mirrors the cisco_iosxe_cli pattern.
    Leaving the prefix line alone (no ``secret``) created a
    passwordless account at commit time, defeating the gate."""

    def test_arista_unmigratable_hash_drops_username_declaration_entirely(self):
        intent = CanonicalIntent(
            hostname="sw1",
            local_users=[
                CanonicalLocalUser(
                    name="root",
                    privilege_level=15,
                    role="user",
                    hashed_password="bcrypt:$2y$11$fakeBcryptHashSynthetic",
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        # The review comment is present (and uses the new
        # target_label="Arista EOS" wording from commit 0074bda).
        assert "! password manager" in out
        assert 'user-name "root"' in out
        assert "cannot be re-used on Arista EOS" in out
        # The orphan declaration line MUST NOT appear anywhere.
        assert "username root role" not in out
        assert "username root privilege" not in out
        # Defence in depth: no bare ``username root`` form either.
        for line in out.splitlines():
            assert not line.startswith("username root"), (
                f"orphan username line leaked through the gate: {line!r}"
            )

    def test_arista_migratable_hash_still_emits_username_declaration(self):
        """Regression guard: a migratable hash (sha512) MUST still
        emit the full ``username ... secret sha512 ...`` line."""
        intent = CanonicalIntent(
            hostname="sw1",
            local_users=[
                CanonicalLocalUser(
                    name="ops",
                    privilege_level=15,
                    role="network-admin",
                    hashed_password="arista:sha512:$6$abc$defghijkl",
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert (
            "username ops privilege 15 role network-admin "
            "secret sha512 $6$abc$defghijkl"
        ) in out
        assert "review:" not in out

    def test_arista_plaintext_password_still_emits_username_declaration(self):
        """Regression guard: a plaintext password is migratable —
        emits ``secret 0 ...`` not a review comment."""
        intent = CanonicalIntent(
            hostname="sw1",
            local_users=[
                CanonicalLocalUser(
                    name="seeded",
                    privilege_level=1,
                    hashed_password="hunter2",
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "username seeded secret 0 hunter2" in out
        assert "review:" not in out


# ---------------------------------------------------------------------------
# VLAN name sanitising (issue #17 in user_smoke_findings.md)
# ---------------------------------------------------------------------------


class TestVlanNameSanitise:
    """Arista's ``name`` clause is whitespace-tokenised — a space
    in the name causes the EOS tokenizer to treat the trailing word
    as an unrecognized argument and rejects the line at commit
    time.  The vendor docs (EOS User Manual / Virtual LANs) state
    spaces are not permitted; AVD's style guide uses underscores
    as the separator.  Render replaces every whitespace run with a
    single underscore so cross-vendor names like OPNsense's
    ``USER VLAN`` survive as ``USER_VLAN``."""

    def test_arista_vlan_name_with_space_is_underscored(self):
        intent = CanonicalIntent(
            hostname="sw1",
            vlans=[CanonicalVlan(id=10, name="USER VLAN")],
        )
        out = AristaEOSCodec().render(intent)
        assert "   name USER_VLAN" in out
        # The unsanitised raw form must NOT appear.
        assert "name USER VLAN" not in out

    def test_arista_vlan_name_single_token_unchanged(self):
        """Same-vendor round-trip stability: a single-token name
        like ``USERS`` (from a real Arista capture) emits unchanged.
        """
        intent = CanonicalIntent(
            hostname="sw1",
            vlans=[CanonicalVlan(id=10, name="USERS")],
        )
        out = AristaEOSCodec().render(intent)
        assert "   name USERS" in out

    def test_arista_vlan_name_with_special_chars_handled(self):
        """Names with hyphens / digits / underscores but no
        whitespace pass through verbatim — the sanitiser is
        whitespace-only, deliberately conservative."""
        intent = CanonicalIntent(
            hostname="sw1",
            vlans=[CanonicalVlan(id=20, name="MY-VLAN_01")],
        )
        out = AristaEOSCodec().render(intent)
        assert "   name MY-VLAN_01" in out

    def test_arista_vlan_name_multiple_spaces_collapsed(self):
        """Multiple consecutive spaces collapse to a single
        underscore (``re.sub(r"\\s+", "_", ...)``)."""
        intent = CanonicalIntent(
            hostname="sw1",
            vlans=[CanonicalVlan(id=30, name="THREE  WORD  NAME")],
        )
        out = AristaEOSCodec().render(intent)
        assert "   name THREE_WORD_NAME" in out

    def test_arista_vlan_name_leading_trailing_whitespace_stripped(self):
        """Defensive: leading/trailing whitespace from sloppy
        parsing of foreign sources gets stripped before the
        underscore replace, so we never emit ``name _USERS_``."""
        intent = CanonicalIntent(
            hostname="sw1",
            vlans=[CanonicalVlan(id=40, name="  USERS  ")],
        )
        out = AristaEOSCodec().render(intent)
        assert "   name USERS" in out
        assert "name _" not in out


# ---------------------------------------------------------------------------
# VRRP groups (v0.2.0 Wave B wire-up)
# ---------------------------------------------------------------------------


class TestVRRPGroups:
    """Classic VRRP grammar on Arista EOS — multi-line per-group form.

    The codec supports the modern ``vrrp <gid> ipv4 <ip>`` form and
    the legacy ``vrrp <gid> ip <ip>`` form.  Multiple sub-commands
    on the same interface converge onto one
    :class:`CanonicalVRRPGroup` keyed by ``group_id``.
    """

    def test_vrrp_ipv4_basic_group(self):
        """``vrrp 10 ipv4 192.168.1.254`` produces a single
        :class:`CanonicalVRRPGroup` on the SVI."""
        raw = (
            "hostname sw1\n"
            "interface Vlan10\n"
            "   ip address 192.168.1.1/24\n"
            "   vrrp 10 ipv4 192.168.1.254\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan10")
        assert len(iface.vrrp_groups) == 1
        g = iface.vrrp_groups[0]
        assert g.group_id == 10
        assert g.mode == "vrrp"
        assert g.virtual_ips == ["192.168.1.254"]
        # Defaults preserved.
        assert g.priority == 100
        assert g.preempt is True

    def test_vrrp_legacy_ip_form(self):
        """Older EOS / Cisco-derived grammar: ``vrrp 10 ip X``.
        Same canonical landing as the modern ``ipv4`` form."""
        raw = (
            "hostname sw1\n"
            "interface Vlan20\n"
            "   ip address 10.0.0.1/24\n"
            "   vrrp 10 ip 10.0.0.254\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan20")
        assert len(iface.vrrp_groups) == 1
        assert iface.vrrp_groups[0].virtual_ips == ["10.0.0.254"]

    def test_vrrp_priority_preempt_track(self):
        """Multi-line VRRP grammar: priority, no-preempt, track,
        timers, description all converge onto the same group."""
        raw = (
            "hostname sw1\n"
            "interface Vlan30\n"
            "   ip address 10.0.30.1/24\n"
            "   vrrp 10 ipv4 10.0.30.254\n"
            "   vrrp 10 priority 110\n"
            "   no vrrp 10 preempt\n"
            "   vrrp 10 track Ethernet1\n"
            "   vrrp 10 description primary HA pair\n"
            "   vrrp 10 timers advertise 3\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan30")
        assert len(iface.vrrp_groups) == 1
        g = iface.vrrp_groups[0]
        assert g.priority == 110
        assert g.preempt is False
        assert g.track_interfaces == ["Ethernet1"]
        assert g.description == "primary HA pair"
        assert g.advertisement_interval == 3

    def test_vrrp_multiple_groups_per_interface(self):
        """Two groups on the same SVI converge onto two distinct
        :class:`CanonicalVRRPGroup` records keyed by gid."""
        raw = (
            "hostname sw1\n"
            "interface Vlan40\n"
            "   ip address 10.0.40.1/24\n"
            "   vrrp 10 ipv4 10.0.40.254\n"
            "   vrrp 10 priority 110\n"
            "   vrrp 20 ipv4 10.0.40.253\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan40")
        assert len(iface.vrrp_groups) == 2
        gids = sorted(g.group_id for g in iface.vrrp_groups)
        assert gids == [10, 20]
        g10 = next(g for g in iface.vrrp_groups if g.group_id == 10)
        assert g10.priority == 110

    def test_vrrp_ipv6_group(self):
        """``vrrp 10 ipv6 fe80::1`` populates the ``virtual_ipv6s``
        list (dual-stack v4+v6 designs use this)."""
        raw = (
            "hostname sw1\n"
            "interface Vlan50\n"
            "   ipv6 address 2001:db8::1/64\n"
            "   vrrp 10 ipv6 2001:db8::ff\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan50")
        assert len(iface.vrrp_groups) == 1
        assert iface.vrrp_groups[0].virtual_ipv6s == ["2001:db8::ff"]

    def test_vrrp_authentication_md5(self):
        """``vrrp 10 authentication md5 key-string <key>`` lands as
        canonical ``md5:<key>``."""
        raw = (
            "hostname sw1\n"
            "interface Vlan60\n"
            "   ip address 10.0.60.1/24\n"
            "   vrrp 10 ipv4 10.0.60.254\n"
            "   vrrp 10 authentication md5 key-string secret123\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan60")
        g = iface.vrrp_groups[0]
        assert g.authentication == "md5:secret123"

    def test_vrrp_authentication_text(self):
        """``vrrp 10 authentication text <key>`` lands as canonical
        ``plain:<key>``."""
        raw = (
            "hostname sw1\n"
            "interface Vlan61\n"
            "   ip address 10.0.61.1/24\n"
            "   vrrp 10 ipv4 10.0.61.254\n"
            "   vrrp 10 authentication text mypass\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan61")
        g = iface.vrrp_groups[0]
        assert g.authentication == "plain:mypass"

    def test_vrrp_render_emits_modern_grammar(self):
        """Render emits the modern ``vrrp <gid> ipv4 <ip>`` form, not
        the legacy ``vrrp <gid> ip <ip>``."""
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(
                    name="Vlan10",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="192.168.1.1", prefix_length=24),
                    ],
                    vrrp_groups=[
                        CanonicalVRRPGroup(
                            group_id=10,
                            virtual_ips=["192.168.1.254"],
                            priority=110,
                            preempt=False,
                        ),
                    ],
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "   vrrp 10 ipv4 192.168.1.254" in out
        assert "   vrrp 10 priority 110" in out
        assert "   no vrrp 10 preempt" in out

    def test_vrrp_default_priority_not_emitted(self):
        """Priority defaults to 100 — render must NOT emit a redundant
        ``vrrp <gid> priority 100`` line for the default value."""
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(
                    name="Vlan10",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.0.10.1", prefix_length=24),
                    ],
                    vrrp_groups=[
                        CanonicalVRRPGroup(
                            group_id=10,
                            virtual_ips=["10.0.10.254"],
                            priority=100,
                        ),
                    ],
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "vrrp 10 priority" not in out
        # And preempt at default should not emit either (EOS default
        # is preempt-enabled).
        assert "no vrrp 10 preempt" not in out

    def test_vrrp_round_trip(self):
        """parse → render → parse stability on a multi-attribute VRRP
        group."""
        raw = (
            "hostname sw1\n"
            "interface Vlan10\n"
            "   ip address 10.0.10.1/24\n"
            "   vrrp 10 ipv4 10.0.10.254\n"
            "   vrrp 10 priority 110\n"
            "   no vrrp 10 preempt\n"
            "   vrrp 10 description primary\n"
            "!\n"
        )
        codec = AristaEOSCodec()
        tree1 = codec.parse(raw)
        rendered = codec.render(tree1)
        tree2 = codec.parse(rendered)
        iface1 = next(i for i in tree1.interfaces if i.name == "Vlan10")
        iface2 = next(i for i in tree2.interfaces if i.name == "Vlan10")
        assert len(iface1.vrrp_groups) == len(iface2.vrrp_groups) == 1
        g1, g2 = iface1.vrrp_groups[0], iface2.vrrp_groups[0]
        assert g1.group_id == g2.group_id
        assert g1.virtual_ips == g2.virtual_ips
        assert g1.priority == g2.priority
        assert g1.preempt == g2.preempt
        assert g1.description == g2.description

    def test_vrrp_carp_mode_emits_review_comment(self):
        """Cross-vendor source carrying ``mode="carp"`` (OPNsense) has
        no EOS equivalent — render emits a review comment so the
        operator sees the loss rather than silently dropping the
        intent."""
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(
                    name="Vlan10",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.0.10.1", prefix_length=24),
                    ],
                    vrrp_groups=[
                        CanonicalVRRPGroup(
                            group_id=10, mode="carp",
                            virtual_ips=["10.0.10.254"],
                        ),
                    ],
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "review:" in out
        assert "carp" in out
        # The payload virtual IP MUST NOT have leaked to the wire as a
        # plain ``vrrp 10 ipv4 ...`` line — protocol mismatch would
        # silently turn a BSD CARP group into IETF VRRP.
        assert "vrrp 10 ipv4 10.0.10.254" not in out

    def test_vrrp_groups_capability_supported(self):
        """Wave B matrix flip: vrrp-groups path declared supported."""
        caps = AristaEOSCodec().capabilities
        supported = set(caps.supported)
        assert "/interfaces/interface/vrrp-groups/group" in supported
        unsupported = {u.path for u in caps.unsupported}
        assert "/interfaces/interface/vrrp-groups/group" not in unsupported


# ---------------------------------------------------------------------------
# VARP anycast-gateway (v0.2.0 Wave C wire-up)
# ---------------------------------------------------------------------------


class TestVARPAnycast:
    """Arista VARP (Virtual ARP) grammar.

    Two surfaces: per-SVI ``ip address virtual X/Y [secondary]`` and
    the system-wide ``ip virtual-router mac-address <MAC>``.  VARP
    has NO per-leaf primary — the wire IP IS the virtual one — so
    canonical records carry ``ip=""`` with
    ``virtual_gateway_address="<X>"``.  See
    ``docs/v0.2.0-planning/02-anycast-gateway/02-per-vendor-grammar.md``
    § "Arista EOS (VARP)" for the design rationale.
    """

    def test_varp_basic_ipv4(self):
        """``ip address virtual X/Y`` populates ``virtual_gateway_address``
        with ``ip=""`` (no per-leaf primary on EOS VARP)."""
        raw = (
            "hostname sw1\n"
            "interface Vlan110\n"
            "   ip address virtual 10.1.10.1/24\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan110")
        assert len(iface.ipv4_addresses) == 1
        a = iface.ipv4_addresses[0]
        assert a.ip == ""
        assert a.virtual_gateway_address == "10.1.10.1"
        assert a.prefix_length == 24
        assert a.is_secondary is False

    def test_varp_secondary_trailer(self):
        """``ip address virtual X/Y secondary`` lands as
        ``is_secondary=True``.  This is the test for the EOS
        ``secondary`` trailer preservation — previously the
        non-VARP ``ip address`` handler silently dropped the
        trailer."""
        raw = (
            "hostname sw1\n"
            "interface Vlan110\n"
            "   ip address virtual 10.1.10.1/24\n"
            "   ip address virtual 10.1.100.1/24 secondary\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan110")
        assert len(iface.ipv4_addresses) == 2
        assert iface.ipv4_addresses[0].is_secondary is False
        assert iface.ipv4_addresses[0].virtual_gateway_address == "10.1.10.1"
        assert iface.ipv4_addresses[1].is_secondary is True
        assert iface.ipv4_addresses[1].virtual_gateway_address == "10.1.100.1"

    def test_varp_multiple_addresses_same_svi(self):
        """Multiple VARP addresses on the same SVI (per-tenant default
        gateways) all land on the same canonical interface."""
        raw = (
            "hostname sw1\n"
            "interface Vlan110\n"
            "   ip address virtual 10.1.10.1/24\n"
            "   ip address virtual 10.1.20.1/24 secondary\n"
            "   ip address virtual 10.1.30.1/24 secondary\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan110")
        vips = [a.virtual_gateway_address for a in iface.ipv4_addresses]
        assert vips == ["10.1.10.1", "10.1.20.1", "10.1.30.1"]
        sec_flags = [a.is_secondary for a in iface.ipv4_addresses]
        assert sec_flags == [False, True, True]

    def test_varp_source_nat_is_ignored(self):
        """``ip address virtual source-nat vrf V address Z`` is a
        DISTINCT feature (VARP source-NAT for VRF-leaked traffic),
        NOT anycast-gateway.  Parser must NOT route it to the
        ipv4_addresses VARP path."""
        raw = (
            "hostname sw1\n"
            "interface Vlan110\n"
            "   ip address virtual source-nat vrf Tenant_A address 10.255.1.4\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan110")
        # source-nat line is parse-and-ignored — no VARP address
        # leaks into ipv4_addresses with a 10.255.x.x VIP.
        assert all(
            a.virtual_gateway_address != "10.255.1.4"
            for a in iface.ipv4_addresses
        )

    def test_varp_global_mac_parsed(self):
        """``ip virtual-router mac-address 00:1c:73:00:dc:01`` lands
        on ``intent.anycast_gateway_mac``."""
        raw = (
            "hostname sw1\n"
            "ip virtual-router mac-address 00:1c:73:00:dc:01\n"
        )
        intent = AristaEOSCodec().parse(raw)
        assert intent.anycast_gateway_mac == "00:1c:73:00:dc:01"

    def test_varp_global_mac_rendered(self):
        """Render emits the top-level ``ip virtual-router mac-address``
        line when ``intent.anycast_gateway_mac`` is set."""
        intent = CanonicalIntent(
            hostname="sw1",
            anycast_gateway_mac="00:1c:73:00:dc:01",
        )
        out = AristaEOSCodec().render(intent)
        assert "ip virtual-router mac-address 00:1c:73:00:dc:01" in out

    def test_varp_render_with_secondary_trailer(self):
        """Render emits the ``secondary`` trailer for any VARP record
        flagged ``is_secondary=True``."""
        intent = CanonicalIntent(
            hostname="sw1",
            interfaces=[
                CanonicalInterface(
                    name="Vlan110",
                    ipv4_addresses=[
                        CanonicalIPv4Address(
                            ip="", prefix_length=24,
                            virtual_gateway_address="10.1.10.1",
                        ),
                        CanonicalIPv4Address(
                            ip="", prefix_length=24,
                            virtual_gateway_address="10.1.100.1",
                            is_secondary=True,
                        ),
                    ],
                ),
            ],
        )
        out = AristaEOSCodec().render(intent)
        assert "   ip address virtual 10.1.10.1/24" in out
        assert "   ip address virtual 10.1.100.1/24 secondary" in out
        # The primary must NOT carry the secondary trailer.
        assert "   ip address virtual 10.1.10.1/24 secondary" not in out

    def test_varp_round_trip(self):
        """parse → render → parse stability across the full VARP
        surface: multiple SVIs, secondary trailers, system-wide MAC."""
        raw = (
            "hostname sw1\n"
            "interface Vlan110\n"
            "   description Tenant_A\n"
            "   ip address virtual 10.1.10.1/24\n"
            "   ip address virtual 10.1.100.1/24 secondary\n"
            "!\n"
            "interface Vlan111\n"
            "   description Tenant_B\n"
            "   ip address virtual 10.1.11.1/24\n"
            "!\n"
            "ip virtual-router mac-address 00:dc:00:00:00:01\n"
        )
        codec = AristaEOSCodec()
        tree1 = codec.parse(raw)
        rendered = codec.render(tree1)
        tree2 = codec.parse(rendered)
        assert tree1.anycast_gateway_mac == tree2.anycast_gateway_mac
        # Compare canonical address records on every Vlan SVI.
        names = ["Vlan110", "Vlan111"]
        for name in names:
            i1 = next(i for i in tree1.interfaces if i.name == name)
            i2 = next(i for i in tree2.interfaces if i.name == name)
            assert len(i1.ipv4_addresses) == len(i2.ipv4_addresses)
            for a, b in zip(i1.ipv4_addresses, i2.ipv4_addresses):
                assert a.virtual_gateway_address == b.virtual_gateway_address
                assert a.is_secondary == b.is_secondary
                assert a.prefix_length == b.prefix_length

    def test_varp_ipv6_basic(self):
        """``ipv6 address virtual X/Y`` (EOS 4.30+) populates
        IPv6Address.virtual_gateway_address."""
        raw = (
            "hostname sw1\n"
            "interface Vlan110\n"
            "   ipv6 address virtual fd20:1::1/64\n"
            "!\n"
        )
        intent = AristaEOSCodec().parse(raw)
        iface = next(i for i in intent.interfaces if i.name == "Vlan110")
        assert len(iface.ipv6_addresses) == 1
        a = iface.ipv6_addresses[0]
        assert a.ip == ""
        assert a.virtual_gateway_address == "fd20:1::1"
        assert a.prefix_length == 64
        assert a.scope == "global"

    def test_varp_capability_paths_supported(self):
        """Wave C matrix flip: the four VARP-adjacent paths are
        declared supported (or lossy for the per-IP MAC override
        slot that EOS doesn't have)."""
        caps = AristaEOSCodec().capabilities
        supported = set(caps.supported)
        assert (
            "/interfaces/interface/ipv4/address/virtual-gateway-address"
            in supported
        )
        assert (
            "/interfaces/interface/ipv6/address/virtual-gateway-address"
            in supported
        )
        assert "/anycast-gateway-mac" in supported
        # Per-IP MAC overrides are lossy (EOS only has system-wide).
        lossy = {l.path for l in caps.lossy}
        assert (
            "/interfaces/interface/ipv4/address/virtual-gateway-mac"
            in lossy
        )

    def test_varp_real_fixture_round_trip(self):
        """End-to-end real-capture round-trip on the Batfish EOS
        EVPN fixture.  Confirms the VARP grammar landing matches the
        real-world wire form (multi-VRF, multi-SVI, system MAC)."""
        import pathlib
        fixture = pathlib.Path(
            "tests/fixtures/real/arista_eos/"
            "batfish_eos_evpn_vlan_based_leaf.txt"
        )
        raw = fixture.read_text(encoding="utf-8")
        codec = AristaEOSCodec()
        tree1 = codec.parse(raw)
        rendered = codec.render(tree1)
        tree2 = codec.parse(rendered)
        # System MAC survives.
        assert tree1.anycast_gateway_mac == "00:dc:00:00:00:01"
        assert tree1.anycast_gateway_mac == tree2.anycast_gateway_mac
        # Both fixtures had a single ``secondary`` VARP on Vlan110.
        v110_1 = next(i for i in tree1.interfaces if i.name == "Vlan110")
        v110_2 = next(i for i in tree2.interfaces if i.name == "Vlan110")
        sec_1 = [a for a in v110_1.ipv4_addresses if a.is_secondary]
        sec_2 = [a for a in v110_2.ipv4_addresses if a.is_secondary]
        assert len(sec_1) == 1
        assert len(sec_2) == 1
        assert sec_1[0].virtual_gateway_address == sec_2[0].virtual_gateway_address

    def test_varp_with_classic_vrrp_coexist(self):
        """VARP (anycast) and classic VRRP can co-exist on different
        SVIs in the same config — they share the
        :class:`CanonicalInterface` model but populate different
        fields (VARP on ipv4_addresses, VRRP on vrrp_groups)."""
        raw = (
            "hostname sw1\n"
            "interface Vlan10\n"
            "   ip address 10.0.10.1/24\n"
            "   vrrp 10 ipv4 10.0.10.254\n"
            "!\n"
            "interface Vlan20\n"
            "   ip address virtual 10.0.20.1/24\n"
            "!\n"
            "ip virtual-router mac-address 00:1c:73:00:dc:01\n"
        )
        intent = AristaEOSCodec().parse(raw)
        v10 = next(i for i in intent.interfaces if i.name == "Vlan10")
        v20 = next(i for i in intent.interfaces if i.name == "Vlan20")
        # Vlan10 has classic VRRP, no VARP.
        assert len(v10.vrrp_groups) == 1
        assert v10.vrrp_groups[0].virtual_ips == ["10.0.10.254"]
        assert all(not a.virtual_gateway_address for a in v10.ipv4_addresses)
        # Vlan20 has VARP, no classic VRRP.
        assert v20.vrrp_groups == []
        assert any(
            a.virtual_gateway_address == "10.0.20.1"
            for a in v20.ipv4_addresses
        )
        # System MAC.
        assert intent.anycast_gateway_mac == "00:1c:73:00:dc:01"
