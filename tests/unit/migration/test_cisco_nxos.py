"""
Unit tests for the Cisco NX-OS codec — Phase 1 surface.

Phase 1 scope (see ``docs/v0.2.0-planning/03-nxos-codec/``): hostname,
basic-L3 interfaces (description / enabled / mtu / IPv4 CIDR / IPv6 CIDR /
``vrf member`` / mgmt-kind), VLANs (comma+range id-list + names + SVI
synthesis), ``vrf context`` (name + description), and default-VRF static
routes.  Switchport / LAG / SNMP / local-users / per-VRF static / VRF
RD-RT / VXLAN-EVPN are declared ``unsupported`` and explicitly NOT
parsed — guarded below so a future phase landing one of them updates
this test deliberately.

The generic ``test_synthetic_kitchen_sink_round_trips`` harness already
exercises ``tests/fixtures/synthetic/cisco_nxos/kitchen_sink.cfg`` for
the three uniform drift-guards; the round-trip test here is a focused
companion that also asserts specific parsed values survive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalLAG,
    CanonicalRoutingInstance,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVRRPGroup,
)
from netcanon.migration.codecs.cisco_nxos import CiscoNXOSCodec

pytestmark = pytest.mark.unit


_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "synthetic" / "cisco_nxos" / "kitchen_sink.cfg"
)


@pytest.fixture
def codec() -> CiscoNXOSCodec:
    return CiscoNXOSCodec()


@pytest.fixture
def kitchen_sink() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


class TestProbe:
    def test_sample_input_detected_high(self, codec):
        score = codec.probe(codec.sample_input)
        assert score is not None
        assert score[0] >= 95, score

    def test_banner_plus_structure_is_98(self, codec):
        raw = (
            "!Command: show running-config\n"
            "version 9.3(11) Bios:version\n"
            "feature interface-vlan\n"
            "interface Ethernet1/1\n"
            "  ip address 10.0.0.1/24\n"
        )
        assert codec.probe(raw) == (
            98, "NX-OS !Command banner + structural markers",
        )

    def test_iosxe_classic_banner_rejected(self, codec):
        """IOS-XE classic banners are a hard NOT-NX-OS signal even if a
        stray ``!Command:`` line appears later in a multi-capture paste."""
        raw = (
            "Building configuration...\n"
            "Current configuration : 1234 bytes\n"
            "!Command: show running-config\n"
            "hostname Router\n"
        )
        assert codec.probe(raw) is None

    def test_no_banner_no_nxos_markers_returns_none(self, codec):
        """A CIDR-addressed config WITHOUT NX-OS-specific markers must
        not be claimed (don't steal Arista / Aruba captures)."""
        raw = (
            "hostname GenericBox\n"
            "interface Ethernet1\n"
            "  ip address 10.0.0.1/24\n"
        )
        assert codec.probe(raw) is None

    def test_rejects_xml(self, codec):
        assert codec.probe('<?xml version="1.0"?><config/>') is None


# ---------------------------------------------------------------------------
# Parse — Phase 1 surfaces
# ---------------------------------------------------------------------------


class TestParse:
    def test_hostname_and_version(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        assert intent.hostname == "nxos-kitchensink"
        assert intent.source_version == "9.3(11)"
        assert intent.source_vendor == "cisco_nxos"
        assert intent.source_format == "cli-nxos"

    def test_interfaces_basic_l3(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        by_name = {i.name: i for i in intent.interfaces}
        eth1 = by_name["Ethernet1/1"]
        assert eth1.description == "routed uplink to spine"
        assert eth1.enabled is True
        assert eth1.mtu == 9216
        assert eth1.switchport_mode is None          # `no switchport` → routed
        assert [(a.ip, a.prefix_length) for a in eth1.ipv4_addresses] == [
            ("192.0.2.1", 31),
        ]

    def test_ipv6_cidr_global_scope(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        eth2 = next(i for i in intent.interfaces if i.name == "Ethernet1/2")
        assert eth2.vrf == "TENANT-A"
        assert [(a.ip, a.prefix_length, a.scope) for a in eth2.ipv6_addresses] == [
            ("2001:db8:a::1", 64, "global"),
        ]

    def test_shutdown_disables_interface(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        eth7 = next(i for i in intent.interfaces if i.name == "Ethernet1/7")
        assert eth7.enabled is False

    def test_mgmt0_classifies_by_name_no_kind_override(self, codec, kitchen_sink):
        """mgmt0 is classified as kind=mgmt by NAME, so the kind OVERRIDE
        field stays empty (the override is only for context-derived
        roles).  Mirrors cisco_iosxe_cli."""
        intent = codec.parse(kitchen_sink)
        mgmt = next(i for i in intent.interfaces if i.name == "mgmt0")
        assert mgmt.kind == ""
        assert mgmt.vrf == "management"
        assert codec.classify_port_name("mgmt0").kind == "mgmt"

    def test_physical_port_in_management_vrf_promoted_to_mgmt(self, codec):
        """A physically-named port bound to the management VRF is the
        OOBM port — kind is promoted to ``mgmt`` (name alone classifies
        physical)."""
        raw = (
            "!Command: show running-config\n"
            "hostname R1\n"
            "vrf context management\n"
            "interface Ethernet1/48\n"
            "  vrf member management\n"
            "  ip address 192.0.2.9/24\n"
        )
        intent = codec.parse(raw)
        eth = next(i for i in intent.interfaces if i.name == "Ethernet1/48")
        assert eth.kind == "mgmt"

    def test_vlans_comma_range_and_names(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        by_id = {v.id: v for v in intent.vlans}
        assert set(by_id) == {1, 10, 20, 30}
        assert by_id[10].name == "PROD"
        assert by_id[30].name == "MGMT-VLAN"

    def test_vlan_id_range_expands(self, codec):
        intent = codec.parse(
            "!Command: show running-config\n"
            "hostname R1\n"
            "vlan 10-13\n"
        )
        assert {v.id for v in intent.vlans} == {10, 11, 12, 13}

    def test_svi_synthesises_vlan_with_ip(self, codec, kitchen_sink):
        """SVI Vlan10 has a top-level ``vlan 10`` stanza; the SVI's IP is
        merged into that VLAN record."""
        intent = codec.parse(kitchen_sink)
        vlan10 = next(v for v in intent.vlans if v.id == 10)
        assert ("10.10.10.1", 24) in [
            (a.ip, a.prefix_length) for a in vlan10.ipv4_addresses
        ]

    def test_vrf_context_name_and_description(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        by_name = {r.name: r for r in intent.routing_instances}
        assert set(by_name) == {"management", "TENANT-A"}
        assert by_name["TENANT-A"].description == "tenant a routing instance"

    def test_default_vrf_static_routes_with_metric(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        by_dest = {r.destination: r for r in intent.static_routes}
        assert by_dest["0.0.0.0/0"].gateway == "192.0.2.254"
        assert by_dest["0.0.0.0/0"].metric == 0
        assert by_dest["10.100.0.0/16"].metric == 200
        # All Phase-1 routes are default-VRF.
        assert all(r.vrf == "" for r in intent.static_routes)

    def test_per_vrf_static_route_not_parsed_in_phase1(self, codec):
        """Per-VRF static routes (indented inside ``vrf context``) are
        Phase 3 — Phase 1 must NOT harvest them, and must NOT
        auto-materialise a phantom routing-instance from a ``vrf member``
        reference (see the per-VRF harvest memory)."""
        raw = (
            "!Command: show running-config\n"
            "hostname R1\n"
            "vrf context TENANT\n"
            "  ip route 10.9.9.0/24 10.9.9.1\n"
            "ip route 0.0.0.0/0 192.0.2.254\n"
        )
        intent = codec.parse(raw)
        # Only the top-level (default-VRF) route is harvested.
        assert [r.destination for r in intent.static_routes] == ["0.0.0.0/0"]
        # The explicit ``vrf context TENANT`` materialises exactly one
        # instance — no phantom duplicates.
        assert [r.name for r in intent.routing_instances] == ["TENANT"]


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def _canonical(intent: CanonicalIntent) -> dict:
    """Strip metadata + sort cosmetic-order list fields — mirrors the
    generic synthetic round-trip harness's ``_compare``."""
    d = intent.model_dump()
    for k in ("source_vendor", "source_format", "source_version"):
        d.pop(k, None)
    for key, id_key in [
        ("interfaces", "name"),
        ("vlans", "id"),
        ("static_routes", "destination"),
    ]:
        d[key] = sorted(d[key], key=lambda x: x.get(id_key, ""))
    return d


class TestRoundTrip:
    def test_kitchen_sink_round_trips(self, codec, kitchen_sink):
        first = codec.parse(kitchen_sink)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        assert _canonical(first) == _canonical(second)

    def test_render_reparses_as_nxos(self, codec, kitchen_sink):
        rendered = codec.render(codec.parse(kitchen_sink))
        probe = codec.probe(rendered)
        assert probe is not None and probe[0] >= 90

    def test_render_emits_l2_snmp_skips_hsrp(self, codec):
        """A cross-vendor tree renders the Phase-2a L2 surface (switchport
        / LAG) + the Phase-2b SNMP surface, but still omits the Phase-2c
        surface (VRRP/HSRP groups) — no crash, no deferred-surface leak."""
        tree = CanonicalIntent(hostname="X", source_vendor="arista_eos")
        tree.interfaces = [
            CanonicalInterface(
                name="Ethernet1",
                switchport_mode="access",
                access_vlan=10,
                vrrp_groups=[
                    CanonicalVRRPGroup(group_id=5, virtual_ips=["1.1.1.254"]),
                ],
            ),
            CanonicalInterface(
                name="Ethernet2",
                ipv4_addresses=[
                    CanonicalIPv4Address(ip="1.1.1.1", prefix_length=24),
                ],
            ),
            CanonicalInterface(name="Ethernet3", lag_member_of="port-channel1"),
        ]
        tree.lags = [
            CanonicalLAG(name="port-channel1", members=["Ethernet3"], mode="active"),
        ]
        tree.snmp = CanonicalSNMP(community="public")
        tree.routing_instances = [
            CanonicalRoutingInstance(name="MGMT", route_distinguisher="65000:1"),
        ]
        out = codec.render(tree)
        # Phase-2a L2 + Phase-2b SNMP surfaces ARE rendered.
        assert "switchport access vlan 10" in out
        assert "no switchport" in out                 # Ethernet2 routed
        assert "channel-group 1 mode active" in out
        assert "vrf context MGMT" in out
        assert "snmp-server community public" in out  # Phase 2b
        # Phase-2c surface (HSRP / VRRP groups) must NOT appear yet.
        assert "vrrp" not in out and "hsrp" not in out
        # And it must re-parse without error.
        assert codec.parse(out).hostname == "X"


# ---------------------------------------------------------------------------
# Capability matrix honesty
# ---------------------------------------------------------------------------


class TestCapabilityMatrix:
    def test_phase1_supported_paths(self, codec):
        sup = set(codec.capabilities.supported)
        for path in [
            "/system/hostname",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/config/mtu",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv6/address/ip",
            "/interfaces/interface/vrf",
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing-instances/instance/name",
            "/routing-instances/instance/description",
            "/routing/static-route",
        ]:
            assert path in sup, path

    def test_deferred_paths_declared_unsupported(self, codec):
        """Surfaces deferred to Phase 2b/2c/3/4 must classify
        ``unsupported`` so the migrate-page banner + cross-mesh report
        flag them.  (The Phase-2a L2 surface has graduated — see
        ``test_l2_paths_graduated_to_supported``.)"""
        caps = codec.capabilities
        for path in [
            "/routing-instances/instance/route-distinguisher",  # Phase 3
            "/routing-instances/instance/rt-imports",       # Phase 3
            "/routing/static-route/vrf",                    # Phase 3
            "/routing-instances/instance/l3-vni",           # Phase 4
            "/vxlan-vnis/vni",                              # Phase 4
            "/anycast-gateway",                             # Phase 4
            "/routing-protocols/bgp",                       # Tier-3
            "/access-list/extended",                        # Tier-3
        ]:
            assert caps.classify(path) == "unsupported", path

    def test_config_type_is_lossy(self, codec):
        assert codec.capabilities.classify(
            "/interfaces/interface/config/type"
        ) == "lossy"

    def test_no_overlap_supported_unsupported(self, codec):
        caps = codec.capabilities
        sup = set(caps.supported)
        unsup = {u.path for u in caps.unsupported}
        assert not (sup & unsup)

    def test_walker_yields_only_declared_paths(self, codec, kitchen_sink):
        """Every xpath ``iter_xpaths`` emits for a fully-populated Phase-1
        tree must classify ``supported`` or ``lossy`` — never
        ``unsupported`` (that would mean the codec emits a surface it
        claims it can't)."""
        intent = codec.parse(kitchen_sink)
        caps = codec.capabilities
        for xp in set(codec.iter_xpaths(intent)):
            assert caps.classify(xp) in ("supported", "lossy"), xp

    def test_metadata(self, codec):
        assert codec.name == "cisco_nxos"
        assert codec.input_format == "cli-nxos"
        assert codec.direction == "bidirectional"
        assert codec.certainty == "experimental"
        assert codec.capabilities.vendor_id == "cisco_nxos"

    def test_l2_paths_graduated_to_supported(self, codec):
        """Phase 2a graduates the L2 switchport + LAG surface from
        ``unsupported`` to ``supported``."""
        caps = codec.capabilities
        for path in [
            "/interfaces/interface/switchport-mode",
            "/interfaces/interface/access-vlan",
            "/interfaces/interface/trunk-allowed-vlans",
            "/interfaces/interface/trunk-native-vlan",
            "/interfaces/interface/lag-member-of",
            "/vlans/vlan/tagged-ports",
            "/vlans/vlan/untagged-ports",
            "/lags/lag/name",
            "/lags/lag/members",
            "/lags/lag/mode",
        ]:
            assert caps.classify(path) == "supported", path


# ---------------------------------------------------------------------------
# Phase 2a — L2 switchport (default-flip) + LAG
# ---------------------------------------------------------------------------


_L2_CONFIG = """\
!Command: show running-config
hostname L2
feature interface-vlan
feature lacp
vlan 1,10,20
interface port-channel1
  switchport mode trunk
  switchport trunk allowed vlan 10,20
interface Ethernet1/1
  no switchport
  ip address 192.0.2.1/31
interface Ethernet1/2
  switchport access vlan 10
interface Ethernet1/3
  switchport mode trunk
  switchport trunk native vlan 1
  switchport trunk allowed vlan 10,20
interface Ethernet1/5
  channel-group 1 mode active
interface Ethernet1/6
  channel-group 1 mode active
"""


class TestPhase2L2:
    @pytest.fixture
    def tree(self, codec):
        return codec.parse(_L2_CONFIG)

    def test_routed_port_mode_none_with_ip(self, tree):
        """`no switchport` + IP → routed (switchport_mode None)."""
        eth1 = next(i for i in tree.interfaces if i.name == "Ethernet1/1")
        assert eth1.switchport_mode is None
        assert [a.ip for a in eth1.ipv4_addresses] == ["192.0.2.1"]

    def test_access_port(self, tree):
        eth2 = next(i for i in tree.interfaces if i.name == "Ethernet1/2")
        assert eth2.switchport_mode == "access"
        assert eth2.access_vlan == 10

    def test_trunk_port(self, tree):
        eth3 = next(i for i in tree.interfaces if i.name == "Ethernet1/3")
        assert eth3.switchport_mode == "trunk"
        assert eth3.trunk_native_vlan == 1
        assert sorted(eth3.trunk_allowed_vlans) == [10, 20]

    def test_lag_membership_and_mode(self, tree):
        lags = {lag.name: lag for lag in tree.lags}
        assert "port-channel1" in lags
        assert sorted(lags["port-channel1"].members) == [
            "Ethernet1/5", "Ethernet1/6",
        ]
        assert lags["port-channel1"].mode == "active"
        members = {i.name: i.lag_member_of for i in tree.interfaces}
        assert members["Ethernet1/5"] == "port-channel1"

    def test_channel_group_on_mode_maps_to_static(self, codec):
        intent = codec.parse(
            "!Command: show running-config\nhostname X\n"
            "interface Ethernet1/9\n  channel-group 7 mode on\n"
        )
        lag = next(lag for lag in intent.lags if lag.name == "port-channel7")
        assert lag.mode == "static"

    def test_switchport_and_lag_render_kind_aware(self, codec, tree):
        out = codec.render(tree)
        assert "  switchport access vlan 10" in out
        assert "  switchport mode trunk" in out
        assert "  switchport trunk allowed vlan 10,20" in out
        assert "  no switchport" in out                 # routed Ethernet1/1
        assert "  channel-group 1 mode active" in out
        assert "feature lacp" in out

    def test_svi_is_not_switchport_capable(self, codec):
        """An SVI is inherently L3 — render must NOT emit a `no
        switchport` line for it (only physical / LAG ports take one)."""
        intent = codec.parse(
            "!Command: show running-config\nhostname X\nfeature interface-vlan\n"
            "interface Vlan10\n  no shutdown\n  ip address 10.0.0.1/24\n"
        )
        out = codec.render(intent)
        # The Vlan10 stanza carries no switchport line.
        svi_block = out.split("interface Vlan10", 1)[1].split("interface ", 1)[0]
        assert "switchport" not in svi_block

    def test_lag_round_trips(self, codec, tree):
        second = codec.parse(codec.render(tree))
        lags1 = {lag.name: (sorted(lag.members), lag.mode) for lag in tree.lags}
        lags2 = {lag.name: (sorted(lag.members), lag.mode) for lag in second.lags}
        assert lags1 == lags2


# ---------------------------------------------------------------------------
# Phase 2b — SNMP (v2c + v3 USM) + local users
# ---------------------------------------------------------------------------


_SNMP_USERS_CONFIG = """\
!Command: show running-config
hostname AAA
username admin password 5 $5$Ab$adminhash role network-admin
username noc password 5 $5$Nc$nochash role custom-readonly
snmp-server community public-ro
snmp-server location DC1-RackB
snmp-server contact netops@example.net
snmp-server host 192.0.2.50
snmp-server user admin network-admin auth md5 0x1a2b3c4d priv aes-128 0xff00ee11 localizedkey
snmp-server user mon network-operator auth sha 0xdeadbeef localizedkey engineID 128:0:0:9:3:1:2:3
"""


class TestPhase2bSNMPUsers:
    @pytest.fixture
    def tree(self, codec):
        return codec.parse(_SNMP_USERS_CONFIG)

    def test_local_users(self, tree):
        users = {u.name: u for u in tree.local_users}
        assert users["admin"].role == "network-admin"
        assert users["admin"].privilege_level == 15
        assert users["admin"].hashed_password == "5 $5$Ab$adminhash"
        # Non-admin / custom role → privilege 1 (lossy), role preserved verbatim.
        assert users["noc"].role == "custom-readonly"
        assert users["noc"].privilege_level == 1

    def test_snmp_v2c(self, tree):
        assert tree.snmp.community == "public-ro"
        assert tree.snmp.location == "DC1-RackB"
        assert tree.snmp.contact == "netops@example.net"
        assert tree.snmp.trap_hosts == ["192.0.2.50"]

    def test_snmp_v3_authpriv_user(self, tree):
        admin = next(u for u in tree.snmp.v3_users if u.name == "admin")
        assert admin.group == "network-admin"
        assert admin.auth_protocol == "md5"
        assert admin.auth_passphrase == "0x1a2b3c4d"
        assert admin.priv_protocol == "aes128"         # normalised from aes-128
        assert admin.priv_passphrase == "0xff00ee11"

    def test_snmp_v3_authnopriv_user_with_engine_id(self, tree):
        mon = next(u for u in tree.snmp.v3_users if u.name == "mon")
        assert mon.auth_protocol == "sha"
        assert mon.priv_protocol == ""                  # auth-no-priv
        assert mon.engine_id == "128:0:0:9:3:1:2:3"

    def test_render_round_trips(self, codec, tree):
        rendered = codec.render(tree)
        assert (
            "username admin password 5 $5$Ab$adminhash role network-admin"
            in rendered
        )
        assert (
            "snmp-server user admin network-admin auth md5 0x1a2b3c4d "
            "priv aes-128 0xff00ee11 localizedkey" in rendered
        )
        second = codec.parse(rendered)
        u1 = {
            u.name: (u.role, u.privilege_level, u.hashed_password)
            for u in tree.local_users
        }
        u2 = {
            u.name: (u.role, u.privilege_level, u.hashed_password)
            for u in second.local_users
        }
        assert u1 == u2
        assert tree.snmp.model_dump() == second.snmp.model_dump()

    def test_snmp_users_matrix_graduated(self, codec):
        caps = codec.capabilities
        for path in [
            "/snmp/community", "/snmp/location", "/snmp/contact",
            "/snmp/trap-host", "/snmp/v3-user",
            "/local-users/user/name", "/local-users/user/role",
            "/local-users/user/hashed-password",
        ]:
            assert caps.classify(path) == "supported", path
        for path in [
            "/local-users/user/privilege-level",
            "/snmp/v3-user/auth-passphrase",
            "/snmp/v3-user/engine-id",
        ]:
            assert caps.classify(path) == "lossy", path
