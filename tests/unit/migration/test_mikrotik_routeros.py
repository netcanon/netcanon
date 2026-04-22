"""
Unit tests for the ``MikroTikRouterOSCodec`` — third real codec,
Session 2 of the vendor-config-research plan.

Covers the same contract points as every canonical-bridged codec
(parse / render / round-trip / xpath / capabilities / registry), plus
MikroTik-specific structural quirks (section grammar, ``[ find ... ]``
predicate, key=value parsing with quoted strings, line continuations).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netconfig.migration.codecs._mock import MockCodec
from netconfig.migration.codecs.base import ParseError, RenderError
from netconfig.migration.codecs.cisco_iosxe import CiscoIOSXECodec
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netconfig.migration.codecs.opnsense import OPNsenseCodec
from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from netconfig.models.migration import DeviceClass, MigrationJobStatus
from netconfig.services.migration_pipeline import run_plan

pytestmark = pytest.mark.unit


FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "mikrotik_routeros"
)


_MIN = """\
/system identity
set name=router1

/interface ethernet
set [ find default-name=ether1 ] comment="Up to ISP" disabled=no

/ip address
add address=10.0.0.2/30 interface=ether1
"""


# ---------------------------------------------------------------------------
# R3 field declarations
# ---------------------------------------------------------------------------


class TestR3Fields:
    def test_direction_is_bidirectional(self):
        assert MikroTikRouterOSCodec.direction == "bidirectional"

    def test_certainty_is_best_effort(self):
        assert MikroTikRouterOSCodec.certainty == "best_effort"

    def test_canonical_model(self):
        assert MikroTikRouterOSCodec.canonical_model == "openconfig-lite"

    def test_input_format(self):
        assert MikroTikRouterOSCodec.input_format == "cli-mikrotik"

    def test_vendor_id(self):
        caps = MikroTikRouterOSCodec().capabilities
        assert caps.vendor_id == "mikrotik_routeros"


# ---------------------------------------------------------------------------
# Parse — basic
# ---------------------------------------------------------------------------


class TestParse:
    def test_parse_hostname(self):
        tree = MikroTikRouterOSCodec().parse(_MIN)
        assert tree.hostname == "router1"

    def test_parse_single_ethernet_interface(self):
        tree = MikroTikRouterOSCodec().parse(_MIN)
        ifaces = tree.interfaces
        assert len(ifaces) == 1
        assert ifaces[0].name == "ether1"
        assert ifaces[0].description == "Up to ISP"
        assert ifaces[0].enabled is True
        assert ifaces[0].interface_type == "ianaift:ethernetCsmacd"

    def test_parse_ip_address_attaches_to_interface(self):
        tree = MikroTikRouterOSCodec().parse(_MIN)
        addrs = tree.interfaces[0].ipv4_addresses
        assert len(addrs) == 1
        assert addrs[0].ip == "10.0.0.2"
        assert addrs[0].prefix_length == 30

    def test_parse_disabled_flag(self):
        raw = (
            "/interface ethernet\n"
            "set [ find default-name=ether9 ] comment=Reserved disabled=yes\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.interfaces[0].enabled is False

    def test_parse_fixture_produces_full_tree(self):
        raw = FIXTURES.joinpath("export_simple.rsc").read_text()
        tree = MikroTikRouterOSCodec().parse(raw)

        # Hostname
        assert tree.hostname == "edge-gw"

        # DNS + NTP
        assert tree.dns_servers == ["1.1.1.1", "8.8.8.8"]
        assert tree.ntp_servers == ["pool.ntp.org", "time.google.com"]

        # Interface count: bridge + ether1-3 + vlan10,20 = 6
        names = [i.name for i in tree.interfaces]
        assert "bridge1" in names
        assert "ether1" in names
        assert "ether2" in names
        assert "ether3" in names
        assert "vlan10" in names
        assert "vlan20" in names

        # Disabled ether3 from the fixture
        e3 = next(i for i in tree.interfaces if i.name == "ether3")
        assert e3.enabled is False

        # VLANs
        vlans = {v.id: v.name for v in tree.vlans}
        assert vlans == {10: "Corporate users", 20: "Guest WiFi"}

        # Static routes
        assert len(tree.static_routes) == 1
        assert tree.static_routes[0].destination == "0.0.0.0/0"
        assert tree.static_routes[0].gateway == "198.51.100.1"

    def test_quoted_comment_with_spaces(self):
        """Key=\"value with spaces\" must be parsed as a single value."""
        raw = (
            "/interface ethernet\n"
            'set [ find default-name=ether1 ] comment="Has spaces here" disabled=no\n'
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.interfaces[0].description == "Has spaces here"

    def test_line_continuation_joined(self):
        """Backslash at line end should join to the next line."""
        raw = (
            "/interface ethernet\n"
            'set [ find default-name=ether1 ] \\\n'
            '    comment="Multi line" disabled=no\n'
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.interfaces[0].description == "Multi line"

    def test_comment_banner_ignored(self):
        """# lines at the top (or anywhere outside a section) are skipped."""
        raw = (
            "# jan/15/2024 by RouterOS 7.13\n"
            "# software id = ABCD\n"
            "#\n"
            "/system identity\n"
            "set name=ignore-banner\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.hostname == "ignore-banner"

    def test_ip_address_to_vlan_interface(self):
        """Addresses may target VLAN interfaces, not just ethernet."""
        raw = (
            "/interface vlan\n"
            'add interface=bridge1 name=vlan10 vlan-id=10\n'
            "/ip address\n"
            "add address=192.168.10.1/24 interface=vlan10\n"
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        vlan_iface = next(i for i in tree.interfaces if i.name == "vlan10")
        assert vlan_iface.ipv4_addresses[0].ip == "192.168.10.1"
        assert vlan_iface.ipv4_addresses[0].prefix_length == 24


class TestParseErrors:
    def test_empty_input_raises(self):
        with pytest.raises(ParseError, match="empty input"):
            MikroTikRouterOSCodec().parse("")

    def test_xml_input_rejected(self):
        with pytest.raises(ParseError, match="looks like XML"):
            MikroTikRouterOSCodec().parse('<?xml version="1.0"?><data/>')

    def test_json_input_rejected(self):
        with pytest.raises(ParseError, match="looks like JSON"):
            MikroTikRouterOSCodec().parse('{"key": "value"}')

    def test_ip_address_missing_prefix_raises(self):
        raw = (
            "/ip address\n"
            "add address=10.0.0.2 interface=ether1\n"
        )
        with pytest.raises(ParseError, match="missing CIDR prefix"):
            MikroTikRouterOSCodec().parse(raw)

    def test_ip_address_bogus_prefix_raises(self):
        raw = (
            "/ip address\n"
            "add address=10.0.0.2/bogus interface=ether1\n"
        )
        with pytest.raises(ParseError, match="invalid CIDR prefix"):
            MikroTikRouterOSCodec().parse(raw)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


class TestRender:
    def test_render_deterministic(self):
        tree = MikroTikRouterOSCodec().parse(_MIN)
        a = MikroTikRouterOSCodec().render(tree)
        b = MikroTikRouterOSCodec().render(tree)
        assert a == b

    def test_render_rejects_non_canonical(self):
        with pytest.raises(RenderError, match="CanonicalIntent"):
            MikroTikRouterOSCodec().render("not a tree")  # type: ignore[arg-type]

    def test_render_emits_hostname(self):
        tree = CanonicalIntent(hostname="test-router")
        out = MikroTikRouterOSCodec().render(tree)
        assert "/system identity" in out
        assert "set name=test-router" in out

    def test_render_emits_dns_and_ntp(self):
        tree = CanonicalIntent(
            dns_servers=["1.1.1.1", "8.8.8.8"],
            ntp_servers=["pool.ntp.org"],
        )
        out = MikroTikRouterOSCodec().render(tree)
        assert "/system dns" in out
        assert "set servers=1.1.1.1,8.8.8.8" in out
        assert "/system ntp client" in out
        assert "set enabled=yes servers=pool.ntp.org" in out

    def test_render_static_routes(self):
        tree = CanonicalIntent(static_routes=[
            CanonicalStaticRoute(
                destination="0.0.0.0/0",
                gateway="10.0.0.1",
            ),
        ])
        out = MikroTikRouterOSCodec().render(tree)
        assert "/ip route" in out
        assert "add dst-address=0.0.0.0/0 gateway=10.0.0.1" in out

    def test_render_ethernet_port_tweak(self):
        tree = CanonicalIntent(interfaces=[
            CanonicalInterface(
                name="ether1",
                description="WAN",
                enabled=True,
            ),
        ])
        out = MikroTikRouterOSCodec().render(tree)
        assert "set [ find default-name=ether1 ]" in out
        assert 'comment="WAN"' in out
        assert "disabled=no" in out

    def test_render_vlan_interface(self):
        tree = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="vlan10", description="Users"),
            ],
        )
        out = MikroTikRouterOSCodec().render(tree)
        assert "/interface vlan" in out
        assert 'name=vlan10' in out
        assert 'vlan-id=10' in out


class TestRoundTrip:
    """parse(render(tree)) == tree for every tree in the supported subset."""

    def test_roundtrip_minimal(self):
        c = MikroTikRouterOSCodec()
        tree = c.parse(_MIN)
        assert c.parse(c.render(tree)) == tree

    def test_roundtrip_fixture(self):
        """Full fixture round-trips cleanly through canonical.

        Note: the fixture contains a bridge definition that gets stripped
        on render (we don't emit ``/interface bridge`` yet).  Round-trip
        check is on the rendered-then-re-parsed tree, not the original.
        """
        c = MikroTikRouterOSCodec()
        raw = FIXTURES.joinpath("export_simple.rsc").read_text()
        tree = c.parse(raw)
        round_tripped = c.parse(c.render(tree))
        # Hostname, DNS, NTP, static routes survive exactly.
        assert round_tripped.hostname == tree.hostname
        assert round_tripped.dns_servers == tree.dns_servers
        assert round_tripped.ntp_servers == tree.ntp_servers
        assert round_tripped.static_routes == tree.static_routes
        # VLANs survive (order-preserving).
        assert [(v.id, v.name) for v in round_tripped.vlans] == [
            (v.id, v.name) for v in tree.vlans
        ]


# ---------------------------------------------------------------------------
# iter_xpaths
# ---------------------------------------------------------------------------


class TestIterXpaths:
    def test_xpaths_match_capability_matrix(self):
        """Every emitted path must be in the declared supported/lossy set."""
        caps = MikroTikRouterOSCodec().capabilities
        declared = (
            set(caps.supported)
            | {lp.path for lp in caps.lossy}
            | {up.path for up in caps.unsupported}
        )
        raw = FIXTURES.joinpath("export_simple.rsc").read_text()
        tree = MikroTikRouterOSCodec().parse(raw)
        for x in MikroTikRouterOSCodec().iter_xpaths(tree):
            assert x in declared, f"walker emitted undeclared xpath: {x!r}"

    def test_no_list_key_predicates(self):
        """Canonical walker emits schema-style paths without list indices."""
        tree = MikroTikRouterOSCodec().parse(_MIN)
        xs = list(MikroTikRouterOSCodec().iter_xpaths(tree))
        assert not any("[" in x for x in xs), f"list-key predicate leaked: {xs}"


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_declares_router_and_firewall(self):
        classes = MikroTikRouterOSCodec().capabilities.device_classes
        assert DeviceClass.router in classes
        assert DeviceClass.firewall in classes

    def test_filter_rule_unsupported(self):
        paths = [
            up.path for up in MikroTikRouterOSCodec().capabilities.unsupported
        ]
        assert "/filter/rule" in paths
        assert "/nat/rule" in paths


# ---------------------------------------------------------------------------
# Cross-adapter story
# ---------------------------------------------------------------------------


class TestCrossAdapter:
    def test_ios_cli_to_mikrotik(self):
        """Cisco IOS-XE CLI parsed and rendered as MikroTik export."""
        ios_cli = """\
hostname ios-to-mt
!
interface GigabitEthernet0/0/0
 description ISP uplink
 ip address 198.51.100.2 255.255.255.252
 no shutdown
!
ip route 0.0.0.0 0.0.0.0 198.51.100.1
!
end
"""
        src = CiscoIOSXECLICodec()
        tgt = MikroTikRouterOSCodec()
        job = run_plan(src, tgt, ios_cli)
        assert job.status is MigrationJobStatus.completed
        assert job.rendered is not None
        assert "/system identity" in job.rendered
        assert "set name=ios-to-mt" in job.rendered
        assert "/ip route" in job.rendered
        assert "dst-address=0.0.0.0/0" in job.rendered
        assert "gateway=198.51.100.1" in job.rendered

    def test_mikrotik_to_iosxe_netconf(self):
        """MikroTik export rendered as OpenConfig NETCONF XML."""
        mt_cfg = """\
/system identity
set name=mt-to-xe

/interface ethernet
set [ find default-name=ether1 ] comment="ISP" disabled=no

/ip address
add address=10.0.0.2/30 interface=ether1
"""
        src = MikroTikRouterOSCodec()
        tgt = CiscoIOSXECodec()
        job = run_plan(src, tgt, mt_cfg)
        assert job.status is MigrationJobStatus.completed
        assert job.rendered is not None
        assert "<interfaces" in job.rendered
        assert "<name>ether1</name>" in job.rendered
        assert "10.0.0.2" in job.rendered

    def test_mikrotik_to_opnsense(self):
        """MikroTik export rendered as OPNsense config.xml."""
        mt_cfg = """\
/system identity
set name=mt-to-op

/interface ethernet
set [ find default-name=ether1 ] comment="WAN" disabled=no

/ip address
add address=198.51.100.2/30 interface=ether1
"""
        src = MikroTikRouterOSCodec()
        tgt = OPNsenseCodec()
        job = run_plan(src, tgt, mt_cfg)
        assert job.status is MigrationJobStatus.completed
        assert job.rendered is not None
        assert "<opnsense>" in job.rendered
        assert "<hostname>mt-to-op</hostname>" in job.rendered

    def test_class_guard_permits_mikrotik_mock(self):
        """MikroTik [router,firewall] ∩ Mock [switch,router] = {router}.

        Class guard should PERMIT — the test exists to make the
        cross-class contract explicit."""
        job = run_plan(MikroTikRouterOSCodec(), MockCodec(), _MIN)
        assert "Device-class guard" not in (job.error or "")


# ---------------------------------------------------------------------------
# Round-trip stability: interface_type inference must be consistent
# regardless of which section first mentions an interface name.
# Surfaced by real-capture validation against the NTC
# ip_address_export_verbose fixture (parse→render→parse was unstable).
# ---------------------------------------------------------------------------


class TestBridgeRender:
    """Parse captures bridge interfaces; render must emit them back
    under `/interface bridge`.  Without this, any config using bridges
    has the bridge disappear on round-trip — surfaced by
    routeros-diff's verbose_export.rsc and taqavi's provisioning
    script."""

    def test_bridge_interface_round_trips(self):
        raw = "/interface bridge\nadd name=bridge-lan comment=\"Main LAN\"\n"
        c = MikroTikRouterOSCodec()
        first = c.parse(raw)
        assert first.interfaces[0].name == "bridge-lan"
        assert first.interfaces[0].interface_type == "ianaift:bridge"
        assert first.interfaces[0].description == "Main LAN"

        rendered = c.render(first)
        assert "/interface bridge" in rendered
        assert "name=bridge-lan" in rendered
        assert 'comment="Main LAN"' in rendered

        second = c.parse(rendered)
        assert second.interfaces[0].name == "bridge-lan"
        assert second.interfaces[0].interface_type == "ianaift:bridge"
        assert second.interfaces[0].description == "Main LAN"

    def test_bridge_name_with_spaces_quoted(self):
        """Real bridge names can contain spaces (e.g. `"main
        infrastructure"` from the Defm capxl capture).  Must be
        quoted on render."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[CanonicalInterface(
                name="main infrastructure",
                interface_type="ianaift:bridge",
            )],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert 'name="main infrastructure"' in out


class TestVlanInterfaceNamePreservation:
    """Real VLAN interfaces are named after their purpose, not by the
    synthetic `vlan<N>` convention.  Render must preserve the original
    name instead of emitting `vlan<N>`.  Surfaced by the `gn-mgmt`
    interface in routeros-diff's verbose_export.rsc."""

    def test_named_vlan_iface_round_trips(self):
        raw = (
            "/interface vlan\n"
            "add interface=ether3 name=gn-mgmt vlan-id=84\n"
        )
        c = MikroTikRouterOSCodec()
        first = c.parse(raw)
        gn_mgmt = next(i for i in first.interfaces if i.name == "gn-mgmt")
        assert gn_mgmt.interface_type == "ianaift:l3ipvlan"

        rendered = c.render(first)
        assert "name=gn-mgmt" in rendered
        assert "vlan-id=84" in rendered
        # Must NOT synthesize a vlan84 name in place of gn-mgmt.
        assert "name=vlan84" not in rendered

        second = c.parse(rendered)
        names = {i.name for i in second.interfaces}
        assert "gn-mgmt" in names
        assert "vlan84" not in names

    def test_synthetic_name_still_used_for_vlans_without_iface(self):
        """When a CanonicalVlan has no matching interface, render
        still falls back to `vlan<N>` as a safe default."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            vlans=[CanonicalVlan(id=50, name="")],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "name=vlan50" in out

    def test_no_duplicate_vlan_when_iface_and_vlan_both_present(self):
        """Iface named `gn-mgmt` with matching CanonicalVlan(id=84,
        name="gn-mgmt") should render once, not twice."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[CanonicalInterface(
                name="gn-mgmt",
                interface_type="ianaift:l3ipvlan",
            )],
            vlans=[CanonicalVlan(id=84, name="gn-mgmt")],
        )
        out = MikroTikRouterOSCodec().render(intent)
        # Count `vlan-id=84` occurrences — exactly one.
        assert out.count("vlan-id=84") == 1
        assert "name=vlan84" not in out


class TestHostnameQuoting:
    """Real RouterOS configs (e.g. routeros-diff's verbose_export
    fixture) carry hostnames with spaces like "Quinta Router".  Our
    render must quote the value — without quotes,
    `set name=Quinta Router` is parsed by RouterOS as
    `name=Quinta` plus an orphan `Router` token, which breaks the
    parse/render/parse round-trip."""

    def test_hostname_with_space_round_trips(self):
        c = MikroTikRouterOSCodec()
        raw = '/system identity\nset name="Quinta Router"\n'
        first = c.parse(raw)
        assert first.hostname == "Quinta Router"
        second = c.parse(c.render(first))
        assert second.hostname == "Quinta Router"

    def test_simple_hostname_not_quoted_unnecessarily(self):
        """No quotes on values that don't need them — keeps the
        render output tidy and matches RouterOS output style."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            hostname="router1",
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "set name=router1" in out
        assert 'set name="router1"' not in out


class TestInterfaceTypeInferenceRoundTrip:
    def test_ethernet_name_from_ip_address_only_gets_typed(self):
        """``/ip address add interface=etherN`` with no matching
        ``/interface ethernet`` section must still populate
        interface_type via name-pattern inference.  Without this the
        second parse (after render emits the /interface ethernet
        stub) adds the type, breaking round-trip equality."""
        raw = (
            "/ip address\n"
            "add address=10.0.0.1/24 interface=ether2\n"
        )
        intent = MikroTikRouterOSCodec().parse(raw)
        assert len(intent.interfaces) == 1
        assert intent.interfaces[0].name == "ether2"
        assert intent.interfaces[0].interface_type == "ianaift:ethernetCsmacd"

    def test_round_trip_stable_with_ip_only_interface(self):
        c = MikroTikRouterOSCodec()
        raw = (
            "/ip address\n"
            "add address=10.0.0.1/24 interface=ether2\n"
            "add address=10.0.1.1/24 interface=eth3_vlan1\n"
        )
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.model_dump(exclude={'source_vendor', 'source_format', 'source_version'}) \
               == second.model_dump(exclude={'source_vendor', 'source_format', 'source_version'})

    def test_bond_name_infers_lag_type(self):
        """``bond1`` -> ianaift:ieee8023adLag so a LAG materialised from
        /interface bonding and a LAG mentioned only in /ip address get
        the same type."""
        raw = (
            "/ip address\n"
            "add address=10.0.0.1/24 interface=bond1\n"
        )
        intent = MikroTikRouterOSCodec().parse(raw)
        assert intent.interfaces[0].interface_type == "ianaift:ieee8023adLag"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_mikrotik_in_registry(self):
        import netconfig.migration  # side-effect
        from netconfig.migration.codecs.registry import list_codecs
        assert "mikrotik_routeros" in list_codecs()

    def test_four_codecs_registered(self):
        """The canonical-bridged codec ecosystem has 4 real codecs now."""
        import netconfig.migration  # side-effect
        from netconfig.migration.codecs.registry import list_codecs
        codecs = list_codecs()
        assert "cisco_iosxe" in codecs
        assert "cisco_iosxe_cli" in codecs
        assert "opnsense" in codecs
        assert "mikrotik_routeros" in codecs
