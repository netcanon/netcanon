"""
Unit tests for the Cisco IOS-XR codec — Phase 1-2 surface.

Phase 1 scope (see ``docs/v0.2.0-planning/04-iosxr-codec/``): hostname,
domain, interfaces (4-segment physical / Loopback / MgmtEth /
Bundle-Ether / sub-interfaces, with IPv4 dotted-mask + IPv6 CIDR +
description / admin-state / mtu), and default-VRF ``router static``
routes.  Shipped bidirectional (not the dossier's transient parse_only)
to satisfy the no-orphan-parse_only-cli invariant — same call NX-OS made.

Phase 2 adds: top-level ``vrf <name>`` stanzas + ``import|export
route-target`` blocks → routing-instances; the route-distinguisher
harvested from / rendered to ``router bgp <asn> / vrf <name> / rd``;
per-interface ``vrf <name>`` membership; ``Bundle-Ether`` LAGs (``bundle
id <N> mode <m>``); local users (``username`` block); per-VRF ``router
static`` routes; and sub-interface ``encapsulation dot1q`` → synthesised
VLAN records.  SNMP + the SP-routing / route-policy / MPLS / l2vpn
Tier-3 stanzas remain ``unsupported`` — guarded below so a future phase
landing one of them updates this test deliberately.

The generic ``test_synthetic_kitchen_sink_round_trips`` harness already
exercises ``tests/fixtures/synthetic/cisco_iosxr/kitchen_sink.cfg`` for
the uniform drift-guards; the round-trip test here is a focused
companion that also asserts specific parsed values survive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalStaticRoute,
)
from netcanon.migration.canonical.port_names import PortIdentity
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.cisco_iosxr import CiscoIOSXRCodec
from netcanon.migration.codecs.cisco_nxos import CiscoNXOSCodec

pytestmark = pytest.mark.unit


_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "synthetic" / "cisco_iosxr" / "kitchen_sink.cfg"
)


@pytest.fixture
def codec() -> CiscoIOSXRCodec:
    return CiscoIOSXRCodec()


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

    def test_banner_is_98(self, codec):
        raw = (
            "!! IOS XR Configuration 7.3.2\n"
            "hostname R1\n"
            "interface GigabitEthernet0/0/0/0\n"
            " ipv4 address 10.0.0.1 255.255.255.0\n"
        )
        assert codec.probe(raw) == (98, "IOS XR Configuration banner present")

    def test_rancid_cisco_xr_header_detected(self, codec):
        """RANCID collection header is a definitive XR declaration for
        marker-light captures lacking the banner + 4-segment ports."""
        raw = (
            "!RANCID-CONTENT-TYPE: cisco-xr\n"
            "!\n"
            "hostname pe1\n"
        )
        result = codec.probe(raw)
        assert result is not None
        score, reason = result
        assert score >= 95
        assert "cisco-xr" in reason

    def test_marker_fallback_without_banner(self, codec):
        """A 4-segment-port + ipv4-address + MgmtEth config without the
        banner still scores high on XR-specific markers."""
        raw = (
            "hostname R1\n"
            "interface GigabitEthernet0/0/0/0\n"
            " ipv4 address 10.0.0.1 255.255.255.0\n"
            "interface MgmtEth0/RP0/CPU0/0\n"
            " ipv4 address 192.168.0.1 255.255.255.0\n"
        )
        score = codec.probe(raw)
        assert score is not None and score[0] >= 90, score

    def test_rejects_plain_iosxe(self, codec):
        """A classic IOS-XE config (3-segment ports, `ip address`,
        no XR markers) must NOT be claimed."""
        raw = (
            "Building configuration...\n"
            "hostname R1\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n"
        )
        assert codec.probe(raw) is None

    def test_rejects_xml(self, codec):
        assert codec.probe('<?xml version="1.0"?><config/>') is None

    def test_outranks_iosxe_cli_and_nxos_for_xr_capture(self, codec):
        """For an XR capture, the XR probe must outrank the sibling Cisco
        CLI codecs so the auto-detector picks it."""
        raw = codec.sample_input
        xr = codec.probe(raw)
        assert xr is not None
        iosxe = CiscoIOSXECLICodec.probe(raw)
        nxos = CiscoNXOSCodec.probe(raw)
        assert iosxe is None or iosxe[0] < xr[0], iosxe
        assert nxos is None or nxos[0] < xr[0], nxos


# ---------------------------------------------------------------------------
# Parse — Phase 1 surfaces
# ---------------------------------------------------------------------------


class TestParse:
    def test_hostname_domain_version(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        assert intent.hostname == "xr-kitchensink"
        assert intent.domain == "lab.example.net"
        assert intent.source_version == "6.6.2"
        assert intent.source_vendor == "cisco_iosxr"
        assert intent.source_format == "cli-iosxr"

    @pytest.mark.parametrize("banner,expected", [
        ("!! IOS XR Configuration 6.3.1", "6.3.1"),          # older form
        ("!! IOS XR Configuration version = 6.2.1", "6.2.1"),  # newer form
        ("!! IOS XR Configuration version 7.3.2", "7.3.2"),  # keyword, no '='
    ])
    def test_source_version_banner_variants(self, codec, banner, expected):
        # Regression: the newer ``version = <rel>`` banner made the extractor
        # capture the literal word "version" instead of the release number.
        assert codec.parse(banner + "\nhostname r1\n").source_version == expected

    def test_loopback_ipv4_mask_to_prefix(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        lo = next(i for i in intent.interfaces if i.name == "Loopback0")
        assert lo.description == "router-id loopback"
        assert [(a.ip, a.prefix_length) for a in lo.ipv4_addresses] == [
            ("10.255.0.1", 32),
        ]

    def test_physical_4seg_ipv4_ipv6_mtu(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        gi = next(
            i for i in intent.interfaces
            if i.name == "GigabitEthernet0/0/0/0"
        )
        assert gi.description == "core uplink to P1"
        assert gi.mtu == 9192
        assert [(a.ip, a.prefix_length) for a in gi.ipv4_addresses] == [
            ("198.51.100.1", 30),
        ]
        assert [(a.ip, a.prefix_length, a.scope) for a in gi.ipv6_addresses] == [
            ("2001:db8:ff::1", 64, "global"),
        ]

    def test_shutdown_disables(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        te = next(i for i in intent.interfaces if i.name == "TenGigE0/0/0/2")
        assert te.enabled is False

    def test_bundle_and_mgmt_present(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        names = {i.name for i in intent.interfaces}
        assert "Bundle-Ether1" in names
        assert "MgmtEth0/RP0/CPU0/0" in names

    def test_static_routes_default_vrf(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        by_dest = {r.destination: r for r in intent.static_routes}
        # Gateway-only.
        assert by_dest["0.0.0.0/0"].gateway == "198.51.100.2"
        assert by_dest["0.0.0.0/0"].interface == ""
        # Interface + gateway.
        assert by_dest["10.50.0.0/16"].interface == "GigabitEthernet0/0/0/1"
        assert by_dest["10.50.0.0/16"].gateway == "203.0.113.2"
        # Interface-only (Null0 blackhole).
        assert by_dest["192.0.2.0/24"].interface == "Null0"
        assert by_dest["192.0.2.0/24"].gateway == ""
        # Default-VRF routes carry no vrf discriminator.
        assert by_dest["0.0.0.0/0"].vrf == ""
        assert by_dest["10.50.0.0/16"].vrf == ""
        # Phase 2 — per-VRF static (`router static / vrf CUSTOMER-A`).
        assert by_dest["10.99.0.0/16"].vrf == "CUSTOMER-A"
        assert by_dest["10.99.0.0/16"].gateway == "203.0.113.2"

    def test_parse_ipv6_static_routes_under_ipv6_af(self, codec):
        # Capstone: routes under ``address-family ipv6 unicast`` (default +
        # per-VRF) now parse — gateway, interface-only, and per-VRF forms.
        raw = (
            "!! IOS XR Configuration\n"
            "hostname r1\n"
            "router static\n"
            " address-family ipv6 unicast\n"
            "  2001:db8:1::/48 2001:db8::1\n"
            "  2001:db8:23::2/128 BVI500\n"
            " !\n"
            " vrf RED\n"
            "  address-family ipv6 unicast\n"
            "   2001:db8:a::/48 2001:db8::9\n"
            "  !\n"
            " !\n"
            "!\n"
        )
        by_dest = {r.destination: r for r in codec.parse(raw).static_routes}
        assert by_dest["2001:db8:1::/48"].gateway == "2001:db8::1"
        assert by_dest["2001:db8:1::/48"].vrf == ""
        # Interface-only v6 next-hop (BVI500) → interface, no gateway.
        assert by_dest["2001:db8:23::2/128"].interface == "BVI500"
        assert by_dest["2001:db8:23::2/128"].gateway == ""
        # Per-VRF v6 route tagged with its VRF.
        assert by_dest["2001:db8:a::/48"].vrf == "RED"
        assert by_dest["2001:db8:a::/48"].gateway == "2001:db8::9"

    def test_non_contiguous_mask_tolerated(self, codec):
        """A malformed mask drops the address rather than crashing the
        whole parse."""
        raw = (
            "!! IOS XR Configuration 6.6.2\n"
            "hostname R1\n"
            "interface GigabitEthernet0/0/0/0\n"
            " ipv4 address 10.0.0.1 255.0.255.0\n"
        )
        intent = codec.parse(raw)
        gi = next(
            i for i in intent.interfaces
            if i.name == "GigabitEthernet0/0/0/0"
        )
        assert gi.ipv4_addresses == []


# ---------------------------------------------------------------------------
# Parse — Phase 2 surfaces (VRF / RD / LAG / users / dot1q)
# ---------------------------------------------------------------------------


class TestParsePhase2:
    def test_vrf_stanzas_with_route_targets(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        by_name = {ri.name: ri for ri in intent.routing_instances}
        assert set(by_name) == {"CUSTOMER-A", "MGMT"}
        ca = by_name["CUSTOMER-A"]
        assert ca.description == "customer a l3vpn"
        assert ca.rt_imports == ["65001:100"]
        assert ca.rt_exports == ["65001:100"]

    def test_rd_harvested_from_router_bgp(self, codec, kitchen_sink):
        """The route-distinguisher lives under `router bgp / vrf / rd`,
        not the `vrf` stanza — harvest + merge by VRF name."""
        intent = codec.parse(kitchen_sink)
        by_name = {ri.name: ri for ri in intent.routing_instances}
        assert by_name["CUSTOMER-A"].route_distinguisher == "65001:100"
        assert by_name["MGMT"].route_distinguisher == "65001:999"

    def test_rd_empty_without_router_bgp(self, codec):
        """An XR config with a `vrf` stanza but no `router bgp` keeps
        route_distinguisher='' (the documented lossy gap)."""
        raw = (
            "!! IOS XR Configuration 7.3.2\n"
            "hostname R1\n"
            "vrf TENANT\n"
            " address-family ipv4 unicast\n"
            "  import route-target\n"
            "   65000:1\n"
            "  !\n"
            " !\n"
            "!\n"
        )
        intent = codec.parse(raw)
        ri = next(r for r in intent.routing_instances if r.name == "TENANT")
        assert ri.route_distinguisher == ""
        assert ri.rt_imports == ["65000:1"]

    def test_orphan_bgp_rd_creates_no_phantom_instance(self, codec):
        """A `router bgp / vrf X / rd` with no top-level `vrf X` stanza
        must NOT conjure a phantom routing-instance (per the per-VRF
        harvest memory)."""
        raw = (
            "!! IOS XR Configuration 7.3.2\n"
            "hostname R1\n"
            "router bgp 65001\n"
            " vrf GHOST\n"
            "  rd 65001:7\n"
            " !\n"
            "!\n"
        )
        intent = codec.parse(raw)
        assert intent.routing_instances == []

    def test_per_interface_vrf_membership(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        by_name = {i.name: i for i in intent.interfaces}
        assert by_name["GigabitEthernet0/0/0/1"].vrf == "CUSTOMER-A"
        assert by_name["MgmtEth0/RP0/CPU0/0"].vrf == "MGMT"
        # A global-VRF interface stays empty.
        assert by_name["GigabitEthernet0/0/0/0"].vrf == ""

    def test_bundle_ether_lag(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        lags = {lag.name: lag for lag in intent.lags}
        assert "Bundle-Ether1" in lags
        assert sorted(lags["Bundle-Ether1"].members) == [
            "GigabitEthernet0/0/0/3",
            "GigabitEthernet0/0/0/4",
        ]
        assert lags["Bundle-Ether1"].mode == "active"
        # Members carry the back-pointer.
        by_name = {i.name: i for i in intent.interfaces}
        assert by_name["GigabitEthernet0/0/0/3"].lag_member_of == "Bundle-Ether1"

    def test_local_users(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        users = {u.name: u for u in intent.local_users}
        assert set(users) == {"netops", "readonly"}
        assert users["netops"].role == "root-lr"
        assert users["netops"].privilege_level == 15
        assert users["netops"].hashed_password.startswith("10 $6$")
        # Non-admin group → privilege 1, role preserved verbatim.
        assert users["readonly"].role == "operator"
        assert users["readonly"].privilege_level == 1

    def test_dot1q_subinterface_synthesises_vlan(self, codec, kitchen_sink):
        intent = codec.parse(kitchen_sink)
        assert [v.id for v in intent.vlans] == [100]
        assert intent.vlans[0].name == ""

    def test_dot1q_on_interface_dot1q_vlan_field(self, codec, kitchen_sink):
        """GAP 7: the tag is now ALSO recorded on the sub-interface's
        dedicated dot1q_vlan (not only synthesised as a VLAN record)."""
        sub = next(
            i for i in codec.parse(kitchen_sink).interfaces
            if i.name == "GigabitEthernet0/0/0/1.100"
        )
        assert sub.dot1q_vlan == 100

    def test_dot1q_tag_differs_from_unit_number(self, codec):
        """A sub-interface whose unit number differs from its 802.1Q tag
        renders the TRUE tag (the old unit==vlan_id workaround dropped it)."""
        raw = (
            "!! IOS XR Configuration 7.5.2\n"
            "interface GigabitEthernet0/0/0/1.100\n"
            " encapsulation dot1q 50\n"
            " ipv4 address 10.0.0.1 255.255.255.252\n"
            "!\n"
        )
        intent = codec.parse(raw)
        sub = next(
            i for i in intent.interfaces
            if i.name == "GigabitEthernet0/0/0/1.100"
        )
        assert sub.dot1q_vlan == 50
        assert " encapsulation dot1q 50" in codec.render(intent)


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

    def test_render_reparses_as_iosxr(self, codec, kitchen_sink):
        rendered = codec.render(codec.parse(kitchen_sink))
        probe = codec.probe(rendered)
        assert probe is not None and probe[0] >= 90

    def test_render_emits_xr_grammar(self, codec, kitchen_sink):
        out = codec.render(codec.parse(kitchen_sink))
        assert "!! IOS XR Configuration" in out
        assert "hostname xr-kitchensink" in out
        assert "domain name lab.example.net" in out
        assert " ipv4 address 10.255.0.1 255.255.255.255" in out
        assert " ipv6 address 2001:db8:ff::1/64" in out
        assert "router static" in out
        assert "  192.0.2.0/24 Null0" in out
        assert out.rstrip().endswith("end")

    def test_render_ipv6_static_route_under_ipv6_af(self, codec):
        # IOS-XR files a static route under the address-family matching its
        # destination.  A v6 prefix must sit under ``address-family ipv6
        # unicast`` — not ``ipv4 unicast`` (invalid CLI, and the bug the
        # dogfood mesh surfaced).  Covers default + per-VRF.
        intent = CanonicalIntent(hostname="r1", static_routes=[
            CanonicalStaticRoute(destination="10.0.0.0/8", gateway="192.0.2.1"),
            CanonicalStaticRoute(destination="2001:db8:1::/48", gateway="2001:db8::1"),
            CanonicalStaticRoute(
                destination="2001:db8:a::/48", gateway="2001:db8::9", vrf="RED",
            ),
        ])
        out = codec.render(intent)
        assert " address-family ipv4 unicast\n  10.0.0.0/8 192.0.2.1" in out
        assert " address-family ipv6 unicast\n  2001:db8:1::/48 2001:db8::1" in out
        # The per-VRF v6 route nests under vrf RED / ipv6 unicast.
        assert "  address-family ipv6 unicast\n   2001:db8:a::/48 2001:db8::9" in out
        # A v6 prefix must never appear under the ipv4 AF block.
        assert "ipv4 unicast\n  2001" not in out

    def test_render_emits_phase2_grammar(self, codec, kitchen_sink):
        out = codec.render(codec.parse(kitchen_sink))
        # VRF stanza + nested route-target blocks (XR word order).
        assert "vrf CUSTOMER-A" in out
        assert "  import route-target" in out
        assert "   65001:100" in out
        # RD carried in the `router bgp` block (NOT the vrf stanza).
        assert "router bgp 65001" in out
        assert "  rd 65001:100" in out
        # Per-interface vrf membership, bundle membership, dot1q, user.
        assert " vrf CUSTOMER-A" in out
        assert " bundle id 1 mode active" in out
        assert " encapsulation dot1q 100" in out
        assert "username netops" in out
        assert " group root-lr" in out
        # Per-VRF static route nests under `router static / vrf`.
        assert "   10.99.0.0/16 203.0.113.2" in out

    def test_phase2_values_round_trip(self, codec, kitchen_sink):
        """RD / RT / per-iface vrf / LAG / users / dot1q survive a
        parse → render → parse cycle (the focused companion to the
        generic synthetic harness)."""
        second = codec.parse(codec.render(codec.parse(kitchen_sink)))
        ri = {r.name: r for r in second.routing_instances}
        assert ri["CUSTOMER-A"].route_distinguisher == "65001:100"
        assert ri["CUSTOMER-A"].rt_imports == ["65001:100"]
        assert ri["MGMT"].route_distinguisher == "65001:999"
        assert {i.name: i.vrf for i in second.interfaces}[
            "GigabitEthernet0/0/0/1"
        ] == "CUSTOMER-A"
        lag = {lag.name: lag for lag in second.lags}["Bundle-Ether1"]
        assert sorted(lag.members) == [
            "GigabitEthernet0/0/0/3", "GigabitEthernet0/0/0/4",
        ]
        assert {u.name for u in second.local_users} == {"netops", "readonly"}
        assert [v.id for v in second.vlans] == [100]
        # The BGP block re-detects identically (dropped-tier3 stability).
        assert second.dropped_tier3_sections == ["router bgp 65001"]

    def test_render_cross_vendor_tree_tolerated(self, codec):
        """A tree carrying surfaces XR Phase 1 doesn't emit (VLANs, LAGs,
        SNMP) renders cleanly, omitting them, without crashing."""
        from netcanon.migration.canonical.intent import (
            CanonicalLAG,
            CanonicalSNMP,
            CanonicalVlan,
        )
        tree = CanonicalIntent(
            hostname="X",
            source_vendor="arista_eos",
            interfaces=[
                CanonicalInterface(
                    name="GigabitEthernet0/0/0/0",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="1.1.1.1", prefix_length=24),
                    ],
                ),
            ],
            vlans=[CanonicalVlan(id=10, name="X")],
            lags=[CanonicalLAG(name="Bundle-Ether1")],
            snmp=CanonicalSNMP(community="public"),
        )
        out = codec.render(tree)
        assert "interface GigabitEthernet0/0/0/0" in out
        assert "1.1.1.1" in out
        assert codec.parse(out).hostname == "X"


# ---------------------------------------------------------------------------
# Capability matrix honesty
# ---------------------------------------------------------------------------


class TestCapabilityMatrix:
    def test_supported_paths(self, codec):
        sup = set(codec.capabilities.supported)
        for path in [
            "/system/hostname",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv6/address/ip",
            "/routing/static-route",
        ]:
            assert path in sup, path

    def test_deferred_paths_unsupported(self, codec):
        caps = codec.capabilities
        for path in [
            "/snmp/community",                   # out of XR v1 scope
            "/routing/bgp",                      # Tier-3 (RD-only harvest)
            "/routing/ospf",                     # Tier-3
            "/mpls",                             # Tier-3
            "/policy/route-policy",              # Tier-3
            "/vxlan-vnis/vni",                   # out of scope
            "/access-list/extended",             # Tier-3
        ]:
            assert caps.classify(path) == "unsupported", path

    def test_phase2_graduated_paths(self, codec):
        """VRF / VLAN / LAG / users / per-iface-vrf graduated in Phase 2.
        The routing-instances path is supported AND lossy → classifies
        lossy (the RD needs the `router bgp` block)."""
        caps = codec.capabilities
        for path in [
            "/interfaces/interface/config/vrf",
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route/vrf",
            "/lags/lag/name",
            "/lags/lag/members",
            "/lags/lag/mode",
            "/local-users/user/name",
            "/local-users/user/role",
        ]:
            assert caps.classify(path) == "supported", path
        assert caps.classify("/routing-instances/instance") == "lossy"

    def test_config_type_lossy(self, codec):
        assert codec.capabilities.classify(
            "/interfaces/interface/config/type"
        ) == "lossy"

    def test_fourth_port_segment_lossy(self, codec):
        assert codec.capabilities.classify(
            "/interfaces/interface/4th-port-segment"
        ) == "lossy"

    def test_no_overlap_supported_unsupported(self, codec):
        caps = codec.capabilities
        assert not (
            set(caps.supported) & {u.path for u in caps.unsupported}
        )

    def test_walker_yields_only_declared_paths(self, codec, kitchen_sink):
        """Every xpath iter_xpaths emits for the kitchen-sink tree must
        classify supported or lossy — never unsupported."""
        intent = codec.parse(kitchen_sink)
        caps = codec.capabilities
        for xp in set(codec.iter_xpaths(intent)):
            assert caps.classify(xp) in ("supported", "lossy"), xp

    def test_metadata(self, codec):
        assert codec.name == "cisco_iosxr"
        assert codec.input_format == "cli-iosxr"
        assert codec.direction == "bidirectional"
        assert codec.certainty == "certified"
        assert codec.capabilities.vendor_id == "cisco_iosxr"


# ---------------------------------------------------------------------------
# Port-name classification + formatting
# ---------------------------------------------------------------------------


class TestPortNames:
    def test_classify_4seg_physical(self, codec):
        ident = codec.classify_port_name("TenGigE0/1/2/3")
        assert ident.kind == "physical"
        assert (ident.stack, ident.module, ident.port) == (0, 1, 2)
        assert ident.meta["iosxr_port_index"] == "3"
        assert ident.name_speed_hint == "10gig"

    def test_classify_logical_kinds(self, codec):
        assert codec.classify_port_name("Bundle-Ether5").kind == "lag"
        assert codec.classify_port_name("Loopback10").kind == "loopback"
        assert codec.classify_port_name("tunnel-te7").kind == "tunnel"
        assert codec.classify_port_name("MgmtEth0/RP0/CPU0/0").kind == "mgmt"

    def test_classify_unknown(self, codec):
        # Null0 only appears as a static next-hop, never classified.
        assert codec.classify_port_name("Null0").kind == "unknown"

    def test_format_round_trips_physical(self, codec):
        for name in (
            "GigabitEthernet0/0/0/0",
            "TenGigE0/1/2/3",
            "HundredGigE1/0/0/5",
        ):
            ident = codec.classify_port_name(name)
            assert codec.format_port_identity(ident) == name

    def test_format_round_trips_logical(self, codec):
        for name in ("Bundle-Ether5", "Loopback10"):
            ident = codec.classify_port_name(name)
            assert codec.format_port_identity(ident) == name

    def test_format_cross_vendor_3seg_to_4seg(self, codec):
        """An IOS-XE 3-segment identity (no 4th segment) formats as a
        4-segment XR name with the instance segment defaulting to 0."""
        iosxe_ident = PortIdentity(
            kind="physical", stack=1, module=0, port=24, name_speed_hint="gig",
        )
        assert codec.format_port_identity(iosxe_ident) == "GigabitEthernet1/0/24/0"

    def test_format_lag_cross_vendor(self, codec):
        """A Port-channel (IOS-XE) identity renders as Bundle-Ether."""
        ident = PortIdentity(kind="lag", index=5)
        assert codec.format_port_identity(ident) == "Bundle-Ether5"


# ---------------------------------------------------------------------------
# Phase 3 — SP-routing Tier-3 parse-and-display on the real batfish corpus
# ---------------------------------------------------------------------------


_REAL_DIR = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "real" / "cisco_iosxr"
)


@pytest.mark.skipif(
    not (_REAL_DIR / "batfish_vpnv4_pe1.txt").is_file(),
    reason="batfish IOS-XR real-capture corpus not present",
)
class TestTier3Display:
    """The SP-routing / policy stanzas the codec deliberately drops must
    surface on ``dropped_tier3_sections`` (Phase 3), while the Tier-1/2
    surface (interfaces, VRFs, RD-from-BGP) is still harvested — the
    parse-and-display split, validated against real `batfish` captures."""

    def _parse(self, codec, name):
        return codec.parse((_REAL_DIR / name).read_text(encoding="utf-8"))

    def test_vpnv4_pe_surfaces_sp_routing(self, codec):
        intent = self._parse(codec, "batfish_vpnv4_pe1.txt")
        dropped = intent.dropped_tier3_sections
        assert "router bgp 65001" in dropped
        assert "router ospf 1" in dropped
        assert "mpls ldp" in dropped
        assert "route-policy PASS_ALL" in dropped

    def test_vpnv4_pe_still_harvests_vrf_and_rd(self, codec):
        """SP-routing is dropped, but the VRF surface + the RD harvested
        from `router bgp / vrf / rd` (Phase 2) survive on a real config."""
        intent = self._parse(codec, "batfish_vpnv4_pe1.txt")
        assert {ri.name for ri in intent.routing_instances} == {
            "red", "blue", "management",
        }
        red = next(ri for ri in intent.routing_instances if ri.name == "red")
        assert red.route_distinguisher == "10.254.1.1:65102"
        assert red.rt_imports == ["65102:2", "65102:4"]
        # Per-interface VRF membership is harvested too.
        assert any(i.vrf == "blue" for i in intent.interfaces)

    def test_ebgp_border_surfaces_policy_primitives(self, codec):
        intent = self._parse(codec, "batfish_ebgp_border01.txt")
        dropped = intent.dropped_tier3_sections
        assert "router bgp 65100" in dropped
        assert any(d.startswith("prefix-set ") for d in dropped)
        assert any(d.startswith("route-policy ") for d in dropped)
        # The `.35` dot1q subinterface still synthesises a VLAN.
        assert intent.vlans


class TestSameVendorBannerEcho:
    """Sanitize / IOS-XR→IOS-XR re-render echoes the device's own release
    into the ``!! IOS XR Configuration`` banner; cross-vendor / unknown-
    version renders keep the synthetic default."""

    def test_same_vendor_echoes_source_version(self):
        tree = CanonicalIntent(
            hostname="R1", source_vendor="cisco_iosxr", source_version="7.5.2"
        )
        out = CiscoIOSXRCodec().render(tree)
        assert "!! IOS XR Configuration 7.5.2" in out
        assert "6.6.2" not in out

    def test_cross_vendor_and_empty_use_default(self):
        codec = CiscoIOSXRCodec()
        cross = CanonicalIntent(
            hostname="R1", source_vendor="cisco_nxos", source_version="10.3(2)"
        )
        assert "!! IOS XR Configuration 6.6.2" in codec.render(cross)
        empty = CanonicalIntent(hostname="R1", source_vendor="cisco_iosxr")
        assert "!! IOS XR Configuration 6.6.2" in codec.render(empty)
