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
                    "netconfig.migration.canonical.intent",
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
        from netconfig.migration.canonical.intent import (
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
        # And the username line itself still emits (just without
        # the ``secret ...`` suffix) so role/privilege survive.
        assert "username root" in out
        assert "role user" in out

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
        from netconfig.migration.canonical.intent import (
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
