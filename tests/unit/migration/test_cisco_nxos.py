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
    CanonicalVlan,
    CanonicalVRRPGroup,
    CanonicalVxlan,
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

    def test_rancid_cisco_nx_header_detected(self, codec):
        """RANCID collection header is a definitive NX-OS declaration — a
        marker-light snippet (no !Command banner, no structural markers)
        must still be claimed rather than lose the alphabetical tie-break
        to cisco_iosxe_cli (dogfood detection label-noise sweep)."""
        raw = (
            "!RANCID-CONTENT-TYPE: cisco-nx\n"
            "!\n"
            "hostname nxos_ntp\n"
        )
        result = codec.probe(raw)
        assert result is not None
        score, reason = result
        assert score >= 95
        assert "cisco-nx" in reason

    def test_nxapi_is_nxos_marker(self, codec):
        """``nxapi http port`` (NX-API mgmt plane) is NX-OS-exclusive and
        lands in the 500-byte probe window even when the `feature` lines
        sit deeper in the config (dogfood detection sweep — leaf2 case)."""
        raw = (
            "hostname leaf2\n"
            "nxapi http port 80\n"
            "interface Ethernet1/1\n"
            "  ip address 10.0.0.1/32\n"
        )
        result = codec.probe(raw)
        assert result is not None
        assert result[0] >= 70

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
        # Default-VRF routes carry no vrf; the TENANT-A per-VRF route
        # (Phase 3) carries its VRF name.
        assert by_dest["0.0.0.0/0"].vrf == ""
        assert by_dest["10.100.0.0/16"].vrf == ""
        assert by_dest["10.50.0.0/16"].vrf == "TENANT-A"

    def test_per_vrf_static_route_harvested_no_phantom_instance(self, codec):
        """Phase 3: a per-VRF ``ip route`` nested in ``vrf context`` is
        harvested onto ``CanonicalStaticRoute.vrf`` — and must NOT
        materialise a phantom routing-instance (the ``vrf context``
        header already created exactly one).  See the per-VRF harvest
        memory."""
        raw = (
            "!Command: show running-config\n"
            "hostname R1\n"
            "vrf context TENANT\n"
            "  ip route 10.9.9.0/24 10.9.9.1\n"
            "ip route 0.0.0.0/0 192.0.2.254\n"
        )
        intent = codec.parse(raw)
        by_dest = {r.destination: r for r in intent.static_routes}
        # The per-VRF route carries its VRF; the default route stays global.
        assert by_dest["10.9.9.0/24"].vrf == "TENANT"
        assert by_dest["10.9.9.0/24"].gateway == "10.9.9.1"
        assert by_dest["0.0.0.0/0"].vrf == ""
        # Exactly one instance — no phantom duplicate from the route harvest.
        assert [r.name for r in intent.routing_instances] == ["TENANT"]

    def test_render_ipv6_static_route_uses_ipv6_keyword(self, codec):
        # NX-OS keys the AF off the keyword: an IPv6 destination must render
        # ``ipv6 route`` (``ip route <v6>`` is invalid CLI).  Covers both the
        # default-VRF and per-VRF (vrf context) render paths.
        intent = CanonicalIntent(hostname="R1", static_routes=[
            CanonicalStaticRoute(destination="10.0.0.0/8", gateway="192.0.2.1"),
            CanonicalStaticRoute(destination="2001:db8:1::/48", gateway="2001:db8::1"),
            CanonicalStaticRoute(
                destination="2001:db8:a::/48", gateway="2001:db8::9", vrf="TENANT",
            ),
        ])
        out = codec.render(intent)
        assert "ip route 10.0.0.0/8 192.0.2.1" in out
        assert "ipv6 route 2001:db8:1::/48 2001:db8::1" in out
        assert "ipv6 route 2001:db8:a::/48 2001:db8::9" in out  # inside vrf context
        assert "ip route 2001" not in out  # v6 never on the bare ``ip route``

    def test_parse_ipv6_static_route_default_and_per_vrf(self, codec):
        # Capstone: NX-OS now parses ``ipv6 route`` back (top-level default
        # VRF + nested inside ``vrf context``), so v6 routes round-trip.
        raw = (
            "!Command: show running-config\n"
            "hostname R1\n"
            "vrf context TENANT\n"
            "  ipv6 route 2001:db8:a::/48 2001:db8::9\n"
            "ipv6 route 2001:db8:1::/48 2001:db8::1\n"
        )
        by_dest = {r.destination: r for r in codec.parse(raw).static_routes}
        assert by_dest["2001:db8:1::/48"].gateway == "2001:db8::1"
        assert by_dest["2001:db8:1::/48"].vrf == ""
        assert by_dest["2001:db8:a::/48"].gateway == "2001:db8::9"
        assert by_dest["2001:db8:a::/48"].vrf == "TENANT"

    def test_ipv6_static_route_round_trip(self, codec):
        intent = CanonicalIntent(hostname="R1", static_routes=[
            CanonicalStaticRoute(destination="2001:db8:1::/48", gateway="2001:db8::1"),
            CanonicalStaticRoute(
                destination="2001:db8:a::/48", gateway="2001:db8::9", vrf="TENANT",
            ),
        ])
        reparsed = codec.parse(codec.render(intent))
        got = sorted((r.destination, r.gateway, r.vrf)
                     for r in reparsed.static_routes if ":" in r.destination)
        assert got == [
            ("2001:db8:1::/48", "2001:db8::1", ""),
            ("2001:db8:a::/48", "2001:db8::9", "TENANT"),
        ]


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

    def test_render_emits_full_phase2_surface(self, codec):
        """A cross-vendor tree renders the full Phase-2 surface (L2
        switchport / LAG / SNMP / HSRP) — every FHRP group normalises to
        an `hsrp` block — without crashing or leaking unknown stanzas."""
        tree = CanonicalIntent(hostname="X", source_vendor="arista_eos")
        tree.interfaces = [
            CanonicalInterface(
                name="Ethernet1",
                switchport_mode="access",
                access_vlan=10,
            ),
            CanonicalInterface(
                name="Ethernet2",
                ipv4_addresses=[
                    CanonicalIPv4Address(ip="1.1.1.1", prefix_length=24),
                ],
                vrrp_groups=[
                    CanonicalVRRPGroup(
                        group_id=5, mode="vrrp", virtual_ips=["1.1.1.254"],
                        priority=120, preempt=True,
                    ),
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
        assert "switchport access vlan 10" in out          # 2a
        assert "no switchport" in out                      # 2a routed
        assert "channel-group 1 mode active" in out        # 2a LAG
        assert "snmp-server community public" in out       # 2b
        # 2c: the source VRRP group normalises to an NX-OS HSRP block.
        assert "hsrp 5" in out
        assert "    ip 1.1.1.254" in out
        assert "feature hsrp" in out
        assert "vrf context MGMT" in out
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
            "/interfaces/interface/config/vrf",
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing-instances/instance/name",
            "/routing-instances/instance/description",
            "/routing/static-route",
        ]:
            assert path in sup, path

    def test_deferred_paths_declared_unsupported(self, codec):
        """Surfaces still deferred (Tier-3) must classify ``unsupported``
        so the migrate-page banner + cross-mesh report flag them.
        (Phase-2a L2, Phase-3 VRF RD/RT + per-VRF static, Phase-4
        VXLAN-EVPN + L3VNI, and IPv4 DAG anycast have all graduated — see
        the ``test_*_matrix_graduated`` companions.)"""
        caps = codec.capabilities
        for path in [
            "/interfaces/interface/ipv6/address/virtual-gateway-address",  # v6 anycast deferred
            "/routing-protocols/bgp",                       # Tier-3
            "/routing-protocols/ospf",                      # Tier-3
            "/access-list/extended",                        # Tier-3
            "/qos",                                         # Tier-3
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
        assert codec.certainty == "certified"   # 6-config batfish corpus
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


class TestRoutedSubifDot1q:
    """GAP 7 wiring: routed sub-interface ``encapsulation dot1q N`` <->
    CanonicalInterface.dot1q_vlan (NOT access_vlan)."""

    _RAW = (
        "!Command: show running-config\n"
        "hostname r1\n"
        "interface Ethernet1/1.100\n"
        "  no switchport\n"
        "  encapsulation dot1q 100\n"
        "  ip address 10.0.0.1/30\n"
    )

    def test_parse(self, codec):
        sub = next(
            i for i in codec.parse(self._RAW).interfaces
            if i.name == "Ethernet1/1.100"
        )
        assert sub.dot1q_vlan == 100
        assert sub.access_vlan is None  # NOT the L2 access field
        assert sub.switchport_mode is None

    def test_round_trip(self, codec):
        out = codec.render(codec.parse(self._RAW))
        assert "  encapsulation dot1q 100" in out
        assert "switchport access vlan" not in out.lower()
        sub = next(
            i for i in codec.parse(out).interfaces
            if i.name == "Ethernet1/1.100"
        )
        assert sub.dot1q_vlan == 100


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


# ---------------------------------------------------------------------------
# Phase 2b regression — SNMPv3 ``priv <key>`` (default-DES, no explicit
# cipher).  The dogfood mesh (napalm NX-OS captures) caught the sanitizer
# leaking the priv key here: the parse regex assumed ``priv <cipher> <key>``
# (two tokens), so the bare ``priv <key> localizedkey`` form swallowed the
# real key as the "cipher" (un-sanitized ``priv_protocol``) and the
# ``localizedkey`` keyword as the "key".
# ---------------------------------------------------------------------------


_SNMP_V3_PRIV_NOCIPHER_CONFIG = """\
!Command: show running-config
hostname AAA
snmp-server user pyclass network-admin auth md5 0xd1e3bf70 priv 0xd1e3bf70 localizedkey
snmp-server user admin auth md5 0x9e902c38 priv 0x9e902c38 localizedkey engineID 128:0:0:9:3:0:12:41
"""


class TestSNMPv3PrivNoCipherKeyLeak:
    @pytest.fixture
    def tree(self, codec):
        return codec.parse(_SNMP_V3_PRIV_NOCIPHER_CONFIG)

    def test_priv_key_lands_in_passphrase_not_protocol(self, tree):
        """The bare ``priv <key>`` form has NO cipher, so the key must land
        in ``priv_passphrase`` (sanitized) with an empty ``priv_protocol`` —
        NOT the reverse, which leaked the key through the un-sanitized
        protocol field."""
        pyclass = next(u for u in tree.snmp.v3_users if u.name == "pyclass")
        assert pyclass.priv_protocol == ""        # default DES, no cipher token
        assert pyclass.priv_passphrase == "0xd1e3bf70"
        assert pyclass.auth_passphrase == "0xd1e3bf70"

    def test_default_des_priv_round_trips_faithfully(self, codec, tree):
        rendered = codec.render(tree)
        assert (
            "snmp-server user pyclass network-admin auth md5 "
            "0xd1e3bf70 priv 0xd1e3bf70 localizedkey" in rendered
        )
        # priv survives a parse->render->parse cycle (was dropped when render
        # gated the priv segment on the now-empty priv_protocol).
        assert codec.parse(rendered).snmp.model_dump() == tree.snmp.model_dump()

    def test_sanitizer_does_not_leak_priv_key(self, codec, tree):
        """Security regression: the original priv/auth key MUST NOT survive
        verbatim into the sanitized output (dogfood mesh residual-secret
        sweep finding)."""
        from netcanon.tools.sanitize import sanitize_intent

        sanitized, _subs = sanitize_intent(tree)
        out = codec.render(sanitized)
        for secret in ("0xd1e3bf70", "0x9e902c38"):
            assert secret not in out, f"sanitizer leaked SNMPv3 key {secret!r}"
        # the redaction placeholders ARE present (priv actually rendered).
        assert "priv REDACTED-PRIV-1 localizedkey" in out


# ---------------------------------------------------------------------------
# Phase 2c — HSRP (CanonicalVRRPGroup mode="hsrp")
# ---------------------------------------------------------------------------


_HSRP_CONFIG = """\
!Command: show running-config
hostname FHRP
feature interface-vlan
feature hsrp
vlan 1,10,20
interface Vlan10
  no shutdown
  ip address 10.10.10.2/24
  hsrp version 2
  hsrp 10
    ip 10.10.10.1
    priority 110
    preempt
    authentication md5 key-string 0xKEY01
interface Vlan20
  no shutdown
  ip address 10.20.20.2/24
  hsrp 20
    ip 10.20.20.1
"""


class TestPhase2cHSRP:
    @pytest.fixture
    def tree(self, codec):
        return codec.parse(_HSRP_CONFIG)

    def test_hsrp_group_parsed(self, tree):
        v10 = next(i for i in tree.interfaces if i.name == "Vlan10")
        assert len(v10.vrrp_groups) == 1
        g = v10.vrrp_groups[0]
        assert g.group_id == 10
        assert g.mode == "hsrp"
        assert g.virtual_ips == ["10.10.10.1"]
        assert g.priority == 110
        assert g.preempt is True
        assert g.authentication == "md5:0xKEY01"

    def test_hsrp_defaults(self, tree):
        # Vlan20's `hsrp 20` has no priority/preempt → NX-OS defaults
        # (priority 100, preempt disabled).
        v20 = next(i for i in tree.interfaces if i.name == "Vlan20")
        g = v20.vrrp_groups[0]
        assert g.group_id == 20
        assert g.priority == 100
        assert g.preempt is False

    def test_render_round_trips(self, codec, tree):
        rendered = codec.render(tree)
        assert "  hsrp 10" in rendered
        assert "    ip 10.10.10.1" in rendered
        assert "    priority 110" in rendered
        assert "    preempt" in rendered
        assert "    authentication md5 key-string 0xKEY01" in rendered
        assert "feature hsrp" in rendered

        def groups(t):
            return {
                i.name: [
                    (g.group_id, tuple(g.virtual_ips), g.priority,
                     g.preempt, g.authentication)
                    for g in i.vrrp_groups
                ]
                for i in t.interfaces if i.vrrp_groups
            }
        assert groups(tree) == groups(codec.parse(rendered))

    def test_hsrpv2_group_above_255_parses_and_round_trips(self, codec):
        """NX-OS HSRPv2 groups run 0-4095; a group > 255 (`hsrp 301`) must
        parse + represent, not raise a ValidationError.  Was rejected by
        the old `group_id` le=255 constraint (the class that produced the
        #229 sanitize 500); the ceiling is now 4095."""
        raw = (
            "!Command: show running-config\n"
            "hostname FHRP\n"
            "feature hsrp\n"
            "interface Vlan30\n"
            "  no shutdown\n"
            "  ip address 10.30.30.2/24\n"
            "  hsrp 301\n"
            "    ip 10.30.30.1\n"
        )
        tree = codec.parse(raw)
        g = next(i for i in tree.interfaces if i.name == "Vlan30").vrrp_groups[0]
        assert g.group_id == 301
        assert g.mode == "hsrp"
        rendered = codec.render(tree)
        assert "  hsrp 301" in rendered
        reparsed = next(
            i for i in codec.parse(rendered).interfaces if i.name == "Vlan30"
        )
        assert reparsed.vrrp_groups[0].group_id == 301

    def test_hsrp_union_edge_values_parse_and_round_trip(self, codec):
        """HSRP legitimately uses group 0 (HSRPv1 default) and priority 0-255
        (255 = highest); the VRRP-centric bounds (group_id ge=1, priority
        1-254) rejected all three, which the CodecBase boundary turns into a
        ParseError.  The `group_id` ge=0 / `priority` 0-255 union widening
        lets them parse + round-trip instead of being dropped."""
        raw = (
            "!Command: show running-config\n"
            "hostname FHRP\n"
            "feature hsrp\n"
            "interface Vlan40\n"
            "  no shutdown\n"
            "  ip address 10.40.40.2/24\n"
            "  hsrp 0\n"          # HSRPv1 group 0
            "    priority 255\n"  # HSRP max priority
            "    ip 10.40.40.1\n"
            "interface Vlan41\n"
            "  no shutdown\n"
            "  ip address 10.40.41.2/24\n"
            "  hsrp 5\n"
            "    priority 0\n"    # HSRP min priority
            "    ip 10.40.41.1\n"
        )
        tree = codec.parse(raw)  # must NOT raise
        g40 = next(i for i in tree.interfaces if i.name == "Vlan40").vrrp_groups[0]
        assert (g40.group_id, g40.priority) == (0, 255)
        g41 = next(i for i in tree.interfaces if i.name == "Vlan41").vrrp_groups[0]
        assert (g41.group_id, g41.priority) == (5, 0)
        # Round-trip: the edge values survive render + reparse.
        reparsed = codec.parse(codec.render(tree))
        r40 = next(i for i in reparsed.interfaces if i.name == "Vlan40").vrrp_groups[0]
        r41 = next(i for i in reparsed.interfaces if i.name == "Vlan41").vrrp_groups[0]
        assert (r40.group_id, r40.priority) == (0, 255)
        assert (r41.group_id, r41.priority) == (5, 0)

    def test_vrrp_groups_declared_lossy(self, codec):
        # FHRP normalises to HSRP on NX-OS render → the mode discriminator
        # is lossy cross-vendor.
        assert codec.capabilities.classify(
            "/interfaces/interface/vrrp-groups/group"
        ) == "lossy"


# ---------------------------------------------------------------------------
# Phase 3 — VRF RD / route-target + per-VRF static routes
# ---------------------------------------------------------------------------


_VRF_RDRT_CONFIG = """\
!Command: show running-config
hostname VRF3
vrf context management
  description oob
vrf context TENANT-A
  description tenant a
  rd 65001:100
  address-family ipv4 unicast
    route-target import 65001:100
    route-target export 65001:200
  ip route 10.50.0.0/16 172.16.0.2
  ip route 10.60.0.0/16 172.16.0.2 250
vrf context TENANT-EVPN
  rd auto
  address-family ipv4 unicast
    route-target both 65001:300 evpn
ip route 0.0.0.0/0 192.0.2.254
"""


# A tenant VRF the way real NX-OS EVPN-VXLAN leaves write it: the same RT
# value repeats across the ipv4-unicast / ipv6-unicast address-families
# AND the ``... evpn`` scope, with an asymmetric import-only route-leak
# mixed in.  Mirrors the akarneliuk multivendor-network-labs leaf
# (c-1-l1) that surfaced the rt_imports round-trip drift.
_VRF_DUAL_AF_RT_CONFIG = """\
!Command: show running-config
hostname VRFDUP
vrf context TENANT-DUAL
  vni 901001
  rd auto
  address-family ipv4 unicast
    route-target both auto
    route-target both auto evpn
    route-target import 65000:901002
  address-family ipv6 unicast
    route-target both auto
    route-target both auto evpn
"""


class TestPhase3VRF:
    @pytest.fixture
    def tree(self, codec):
        return codec.parse(_VRF_RDRT_CONFIG)

    def test_rd_and_split_rts(self, tree):
        a = next(r for r in tree.routing_instances if r.name == "TENANT-A")
        assert a.route_distinguisher == "65001:100"
        assert a.rt_imports == ["65001:100"]
        assert a.rt_exports == ["65001:200"]

    def test_rd_auto_sentinel(self, tree):
        evpn = next(
            r for r in tree.routing_instances if r.name == "TENANT-EVPN"
        )
        assert evpn.route_distinguisher == "auto"

    def test_route_target_both_evpn_suffix_stripped(self, tree):
        """``route-target both 65001:300 evpn`` → RT preserved on both
        import + export; the ``evpn`` AF discriminator is dropped (lossy)."""
        evpn = next(
            r for r in tree.routing_instances if r.name == "TENANT-EVPN"
        )
        assert evpn.rt_imports == ["65001:300"]
        assert evpn.rt_exports == ["65001:300"]

    def test_per_vrf_static_routes_harvested(self, tree):
        a_routes = sorted(
            (r for r in tree.static_routes if r.vrf == "TENANT-A"),
            key=lambda r: r.destination,
        )
        assert [(r.destination, r.gateway, r.metric) for r in a_routes] == [
            ("10.50.0.0/16", "172.16.0.2", 0),
            ("10.60.0.0/16", "172.16.0.2", 250),
        ]

    def test_default_vrf_route_stays_global(self, tree):
        default = [r for r in tree.static_routes if not r.vrf]
        assert [r.destination for r in default] == ["0.0.0.0/0"]

    def test_no_phantom_instance(self, tree):
        # Exactly the three declared vrf contexts — the per-VRF ``ip
        # route`` harvest must not conjure a duplicate / phantom instance.
        assert sorted(r.name for r in tree.routing_instances) == [
            "TENANT-A", "TENANT-EVPN", "management",
        ]

    def test_render_round_trips(self, codec, tree):
        rendered = codec.render(tree)
        # RD + per-VRF routes nest inside the vrf context block.
        assert "vrf context TENANT-A" in rendered
        assert "  rd 65001:100" in rendered
        assert "  address-family ipv4 unicast" in rendered
        assert "    route-target import 65001:100" in rendered
        assert "    route-target export 65001:200" in rendered
        assert "  ip route 10.50.0.0/16 172.16.0.2" in rendered
        assert "  ip route 10.60.0.0/16 172.16.0.2 250" in rendered
        # rd auto sentinel re-emits verbatim.
        assert "  rd auto" in rendered

        def vrf_view(t):
            return {
                r.name: (
                    r.route_distinguisher,
                    tuple(r.rt_imports),
                    tuple(r.rt_exports),
                )
                for r in t.routing_instances
            }

        def route_view(t):
            return sorted(
                (r.destination, r.gateway, r.interface, r.metric, r.vrf)
                for r in t.static_routes
            )

        second = codec.parse(rendered)
        assert vrf_view(tree) == vrf_view(second)
        assert route_view(tree) == route_view(second)

    def test_route_target_both_compact_render(self, codec):
        """An RT in both import + export renders the compact ``both`` form
        and round-trips back to import == export."""
        tree = CanonicalIntent(
            hostname="X",
            routing_instances=[
                CanonicalRoutingInstance(
                    name="T", route_distinguisher="65001:1",
                    rt_imports=["65001:1"], rt_exports=["65001:1"],
                ),
            ],
        )
        out = codec.render(tree)
        assert "    route-target both 65001:1" in out
        t2 = next(
            r for r in codec.parse(out).routing_instances if r.name == "T"
        )
        assert t2.rt_imports == ["65001:1"]
        assert t2.rt_exports == ["65001:1"]

    def test_dual_af_route_targets_deduped(self, codec):
        """The same RT value repeated across ipv4-unicast / ipv6-unicast /
        ``evpn`` scopes collapses to a single canonical entry (the flat
        per-direction list carries no AF / evpn dimension, so the repeats
        are artefacts).  First-seen order is preserved, so the asymmetric
        import-only route-leak follows the single ``auto``."""
        t = next(
            r for r in codec.parse(_VRF_DUAL_AF_RT_CONFIG).routing_instances
            if r.name == "TENANT-DUAL"
        )
        assert t.rt_imports == ["auto", "65000:901002"]
        assert t.rt_exports == ["auto"]

    def test_dual_af_asymmetric_rt_round_trips_stable(self, codec):
        """Regression (akarneliuk EVPN-VXLAN leaf): an asymmetric
        import-only RT interleaved among ``both`` lines must not drift
        ``rt_imports`` order on a parse->render->parse round-trip.  Before
        the parse-side dedup the renderer emitted the import-only RT after
        the (duplicated) ``both`` RTs, so the re-parse saw a different
        order and the round-trip was unstable."""
        first = codec.parse(_VRF_DUAL_AF_RT_CONFIG)
        second = codec.parse(codec.render(first))
        a = next(r for r in first.routing_instances if r.name == "TENANT-DUAL")
        b = next(r for r in second.routing_instances if r.name == "TENANT-DUAL")
        assert a.rt_imports == b.rt_imports == ["auto", "65000:901002"]
        assert a.rt_exports == b.rt_exports == ["auto"]

    def test_dual_af_render_is_idiomatic_not_duplicated(self, codec):
        """The deduped RTs render as one compact ``both auto`` plus the
        import-only leak — not the four duplicate ``both auto`` lines the
        pre-dedup flatten produced."""
        out = codec.render(codec.parse(_VRF_DUAL_AF_RT_CONFIG))
        block = out.split("vrf context TENANT-DUAL", 1)[1]
        assert block.count("route-target both auto") == 1
        assert "    route-target import 65000:901002" in block

    def test_defensive_vrf_context_for_orphan_per_vrf_route(self, codec):
        """A per-VRF static route whose VRF has NO routing-instance record
        (e.g. a cisco_iosxe_cli source where ``ip route vrf X`` never
        declared a ``vrf definition X``) still renders a ``vrf context``
        wrapper so the route is valid NX-OS and re-parses with vrf set."""
        tree = CanonicalIntent(
            hostname="X", source_vendor="cisco_iosxe",
            static_routes=[
                CanonicalStaticRoute(
                    destination="10.7.0.0/16", gateway="10.7.0.1", vrf="ORPHAN",
                ),
            ],
        )
        out = codec.render(tree)
        assert "vrf context ORPHAN" in out
        assert "  ip route 10.7.0.0/16 10.7.0.1" in out
        reparsed = codec.parse(out)
        r = next(
            r for r in reparsed.static_routes if r.destination == "10.7.0.0/16"
        )
        assert r.vrf == "ORPHAN"

    def test_phase3_matrix_graduated(self, codec):
        caps = codec.capabilities
        # rt-exports + per-VRF static-route are cleanly supported.
        assert caps.classify(
            "/routing-instances/instance/rt-exports"
        ) == "supported"
        assert caps.classify("/routing/static-route/vrf") == "supported"
        # rd + rt-imports are supported-but-lossy (auto sentinel / evpn).
        assert caps.classify(
            "/routing-instances/instance/route-distinguisher"
        ) == "lossy"
        assert caps.classify(
            "/routing-instances/instance/rt-imports"
        ) == "lossy"


# ---------------------------------------------------------------------------
# Phase 4 — VXLAN-EVPN (vn-segment + nve1 VTEP + L3VNI) + vtep PortKind
# ---------------------------------------------------------------------------


_VXLAN_CONFIG = """\
!Command: show running-config
hostname EVPN1
feature interface-vlan
feature nv overlay
feature vn-segment-vlan-based
vlan 1,10,20
vlan 10
  name WEB
  vn-segment 10010
vlan 20
  name APP
  vn-segment 10020
vrf context TENANT-A
  vni 50001
  rd auto
  address-family ipv4 unicast
    route-target both auto evpn
interface Vlan10
  no shutdown
  ip address 10.10.10.1/24
interface loopback0
  ip address 10.255.0.1/32
interface nve1
  no shutdown
  host-reachability protocol bgp
  source-interface loopback0
  member vni 10010
  member vni 10020
  member vni 50001 associate-vrf
"""


# Exercises BOTH real NX-OS multicast grammars in one capture: the inline
# ``member vni N mcast-group X`` (vni 10010) and the own-sub-line form
# where ``mcast-group`` lands on the next indented line (vni 10020), plus
# an ``associate-vrf`` L3VNI member (50001) that must NOT acquire an
# mcast-group or become an L2 record.
_VXLAN_MCAST_CONFIG = """\
!Command: show running-config
hostname MCAST1
feature nv overlay
feature vn-segment-vlan-based
vlan 10
  name WEB
  vn-segment 10010
vlan 20
  name APP
  vn-segment 10020
vrf context TENANT-A
  vni 50001
interface loopback0
  ip address 10.255.0.1/32
interface nve1
  no shutdown
  host-reachability protocol bgp
  source-interface loopback0
  member vni 10010 mcast-group 239.1.1.10
  member vni 10020
    mcast-group 239.1.1.20
  member vni 50001 associate-vrf
"""


class TestPhase4VXLAN:
    @pytest.fixture
    def tree(self, codec):
        return codec.parse(_VXLAN_CONFIG)

    def test_vlan_vni_bindings(self, tree):
        vnis = sorted((v.vlan_id, v.vni) for v in tree.vxlan_vnis)
        assert vnis == [(10, 10010), (20, 10020)]

    def test_source_interface_broadcast(self, tree):
        # The nve1 source-interface stamps onto every L2 VNI record.
        assert all(v.source_interface == "loopback0" for v in tree.vxlan_vnis)

    def test_l3_vni_on_vrf(self, tree):
        a = next(r for r in tree.routing_instances if r.name == "TENANT-A")
        assert a.l3_vni == 50001

    def test_l3_vni_not_an_l2_record(self, tree):
        # The L3VNI (50001) is a VRF property, NOT an L2 VLAN↔VNI record.
        assert 50001 not in {v.vni for v in tree.vxlan_vnis}

    def test_nve1_not_materialised_as_interface(self, tree):
        # nve1 is a VXLAN config container, not a routed/switched port.
        assert "nve1" not in {i.name for i in tree.interfaces}

    def test_render_emits_vxlan(self, codec, tree):
        out = codec.render(tree)
        assert "  vn-segment 10010" in out
        assert "  vn-segment 10020" in out
        assert "interface nve1" in out
        assert "  source-interface loopback0" in out
        assert "  member vni 10010" in out
        assert "  member vni 50001 associate-vrf" in out
        assert "  vni 50001" in out                    # vrf-context L3VNI
        assert "feature nv overlay" in out
        assert "feature vn-segment-vlan-based" in out

    def test_round_trips(self, codec, tree):
        rendered = codec.render(tree)
        second = codec.parse(rendered)

        def vx(t):
            return sorted(
                (v.vlan_id, v.vni, v.source_interface) for v in t.vxlan_vnis
            )

        assert vx(tree) == vx(second)
        l3a = next(
            r for r in tree.routing_instances if r.name == "TENANT-A"
        ).l3_vni
        l3b = next(
            r for r in second.routing_instances if r.name == "TENANT-A"
        ).l3_vni
        assert l3a == l3b == 50001

    def test_vtep_portkind_classify_and_format(self, codec):
        ident = codec.classify_port_name("nve1")
        assert ident.kind == "vtep"
        assert codec.format_port_identity(ident) == "nve1"

    def test_mcast_group_render(self, codec):
        tree = CanonicalIntent(
            hostname="X",
            vlans=[CanonicalVlan(id=30, name="MC")],
            vxlan_vnis=[
                CanonicalVxlan(
                    vlan_id=30, vni=10030, mcast_group="239.1.1.30",
                    source_interface="loopback0",
                ),
            ],
        )
        out = codec.render(tree)
        assert "  member vni 10030" in out
        assert "    mcast-group 239.1.1.30" in out

    def test_mcast_group_parse_inline(self, codec):
        # Regression (gap-hunt): the inline ``member vni N mcast-group X``
        # form was never harvested — a matrix-`supported` surface lost
        # 100% of its data on parse.
        tree = codec.parse(_VXLAN_MCAST_CONFIG)
        v = next(v for v in tree.vxlan_vnis if v.vni == 10010)
        assert v.mcast_group == "239.1.1.10"

    def test_mcast_group_parse_own_subline(self, codec):
        # The own-sub-line form (``mcast-group`` on the next indented
        # line) must harvest to the preceding ``member vni`` too.
        tree = codec.parse(_VXLAN_MCAST_CONFIG)
        v = next(v for v in tree.vxlan_vnis if v.vni == 10020)
        assert v.mcast_group == "239.1.1.20"

    def test_associate_vrf_member_carries_no_mcast(self, codec):
        # The L3VNI ``member vni 50001 associate-vrf`` must not become an
        # L2 vxlan record nor steal an mcast-group from a sibling.
        tree = codec.parse(_VXLAN_MCAST_CONFIG)
        assert 50001 not in {v.vni for v in tree.vxlan_vnis}

    def test_mcast_group_round_trips(self, codec):
        tree = codec.parse(_VXLAN_MCAST_CONFIG)
        second = codec.parse(codec.render(tree))

        def mc(t):
            return sorted((v.vni, v.mcast_group) for v in t.vxlan_vnis)

        assert mc(tree) == [(10010, "239.1.1.10"), (10020, "239.1.1.20")]
        assert mc(second) == mc(tree)

    # ── static head-end replication (flood-list) — gap-hunt follow-up ──
    # `/vxlan-vnis/flood-list` was matrix-`supported` but parse never read
    # the `ingress-replication protocol static / peer-ip` lines (the
    # deferred sibling of the mcast-group fix), so a real static-IR VTEP
    # lost 100% of its flood-list on parse.
    _FLOOD_CONFIG = """\
!Command: show running-config
hostname LEAF-IR
feature nv overlay
feature vn-segment-vlan-based
vlan 10
  vn-segment 10010
vlan 20
  vn-segment 10020
interface nve1
  no shutdown
  source-interface loopback0
  member vni 10010
    ingress-replication protocol static
      peer-ip 192.0.2.11
      peer-ip 192.0.2.12
  member vni 10020 mcast-group 239.1.1.20
"""

    def test_flood_list_parse(self, codec):
        tree = codec.parse(self._FLOOD_CONFIG)
        v = next(v for v in tree.vxlan_vnis if v.vni == 10010)
        assert v.flood_list == ["192.0.2.11", "192.0.2.12"]
        assert v.mcast_group == ""

    def test_flood_list_and_mcast_are_mutually_exclusive(self, codec):
        # A multicast VNI carries no flood-list; a static-IR VNI carries no
        # mcast-group — the render emits one or the other, never both.
        tree = codec.parse(self._FLOOD_CONFIG)
        mc = next(v for v in tree.vxlan_vnis if v.vni == 10020)
        assert mc.mcast_group == "239.1.1.20"
        assert mc.flood_list == []

    def test_flood_list_render(self, codec):
        out = codec.render(codec.parse(self._FLOOD_CONFIG))
        assert "  member vni 10010" in out
        assert "    ingress-replication protocol static" in out
        assert "      peer-ip 192.0.2.11" in out
        assert "      peer-ip 192.0.2.12" in out

    def test_flood_list_round_trips(self, codec):
        tree = codec.parse(self._FLOOD_CONFIG)
        second = codec.parse(codec.render(tree))

        def fl(t):
            return sorted((v.vni, tuple(v.flood_list)) for v in t.vxlan_vnis)

        assert fl(tree) == [(10010, ("192.0.2.11", "192.0.2.12")), (10020, ())]
        assert fl(second) == fl(tree)

    def test_phase4_matrix_graduated(self, codec):
        caps = codec.capabilities
        for path in [
            "/vxlan-vnis/source-interface",
            "/vxlan-vnis/udp-port",
            "/vxlan-vnis/mcast-group",
            "/vxlan-vnis/flood-list",
            "/routing-instances/instance/l3-vni",
        ]:
            assert caps.classify(path) == "supported", path
        # vxlan-vni is supported-but-lossy (nve sub-flags dropped);
        # evpn-type5 is lossy (modelled via the l3_vni VRF binding).
        assert caps.classify("/vxlan-vnis/vni") == "lossy"
        assert caps.classify("/evpn-type5-routes/route") == "lossy"
        # IPv4 DAG anycast graduated; only the IPv6 companion is deferred.
        assert caps.classify("/anycast-gateway-mac") == "supported"
        # Demoted supported -> lossy (Bucket-C stage 3): DAG round-trips only
        # vga == primary-IP; a separate cross-vendor VARP VIP has no NX-OS
        # equivalent and drops on render.
        assert caps.classify(
            "/interfaces/interface/ipv4/address/virtual-gateway-address"
        ) == "lossy"
        assert caps.classify(
            "/interfaces/interface/ipv6/address/virtual-gateway-address"
        ) == "unsupported"


class TestAnycastGateway:
    """Distributed Anycast Gateway (DAG) — per-SVI ``fabric forwarding
    mode anycast-gateway`` mirrors the primary IP into
    ``virtual_gateway_address``; the chassis-wide ``fabric forwarding
    anycast-gateway-mac`` round-trips dotted-triplet ↔ canonical
    colon-hex.  Mirrors the IOS-XE SD-Access shape."""

    def test_global_mac_harvested_colon_hex(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        assert intent.anycast_gateway_mac == "00:01:c7:3a:00:00"

    def test_svi_mirrors_primary_ip(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        svi = next(i for i in intent.interfaces if i.name == "Vlan20")
        addr = svi.ipv4_addresses[0]
        assert addr.virtual_gateway_address == addr.ip == "10.20.20.1"

    def test_non_anycast_svi_has_no_vga(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        svi = next(i for i in intent.interfaces if i.name == "Vlan10")
        assert all(a.virtual_gateway_address == "" for a in svi.ipv4_addresses)

    def test_render_emits_dotted_triplet_and_mode(self, codec, kitchen_sink):
        out = codec.render(codec.parse(kitchen_sink))
        assert "fabric forwarding anycast-gateway-mac 0001.c73a.0000" in out
        assert "  fabric forwarding mode anycast-gateway" in out

    def test_round_trip(self, codec, kitchen_sink):
        first = codec.parse(kitchen_sink)
        second = codec.parse(codec.render(first))
        assert second.anycast_gateway_mac == first.anycast_gateway_mac
        s1 = next(i for i in first.interfaces if i.name == "Vlan20")
        s2 = next(i for i in second.interfaces if i.name == "Vlan20")
        assert (
            [(a.ip, a.virtual_gateway_address) for a in s1.ipv4_addresses]
            == [(a.ip, a.virtual_gateway_address) for a in s2.ipv4_addresses]
        )
