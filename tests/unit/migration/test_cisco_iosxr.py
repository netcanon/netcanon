"""
Unit tests for the Cisco IOS-XR codec — Phase 1 surface.

Phase 1 scope (see ``docs/v0.2.0-planning/04-iosxr-codec/``): hostname,
domain, interfaces (4-segment physical / Loopback / MgmtEth /
Bundle-Ether / sub-interfaces, with IPv4 dotted-mask + IPv6 CIDR +
description / admin-state / mtu), and default-VRF ``router static``
routes.  Shipped bidirectional (not the dossier's transient parse_only)
to satisfy the no-orphan-parse_only-cli invariant — same call NX-OS made.

VRF stanzas + RT, RD-from-BGP, Bundle-Ether membership / LAGs, local
users, per-VRF static, dot1q->VLAN synth, and SP-routing harvest are
declared ``unsupported`` and explicitly NOT parsed — guarded below so a
future phase landing one of them updates this test deliberately.

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
        # Phase 1 is default-VRF only.
        assert all(r.vrf == "" for r in intent.static_routes)

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

    def test_render_cross_vendor_tree_tolerated(self, codec):
        """A tree carrying surfaces XR Phase 1 doesn't emit (VLANs, LAGs,
        SNMP) renders cleanly, omitting them, without crashing."""
        from netcanon.migration.canonical.intent import (
            CanonicalLAG, CanonicalSNMP, CanonicalVlan,
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
            "/routing-instances/instance",      # Phase 2 (VRF)
            "/lags/lag",                         # Phase 2
            "/local-users/user",                 # Phase 2
            "/vlans/vlan/id",                    # Phase 2 (dot1q synth)
            "/routing/bgp",                      # Tier-3
            "/policy/route-policy",              # Tier-3
            "/vxlan-vnis/vni",                   # out of scope
            "/access-list/extended",             # Tier-3
        ]:
            assert caps.classify(path) == "unsupported", path

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
        assert codec.certainty == "experimental"
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
