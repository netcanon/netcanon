"""
Unit tests for the synthetic ``cisco_iosxe`` kitchen-sink fixture.

The cisco_iosxe codec is a Phase-0.5 NETCONF/OpenConfig stub: it
parses ONLY the ``/openconfig-interfaces/`` subtree into the
:class:`CanonicalIntent` (sibling cisco_iosxe_cli covers hostname /
DNS / NTP / VLANs / static routes / SNMP / users via running-config
text).  This module locks in the supported feature surface — every
canonical-tree field the codec actually populates from the wire — so
that a future codec wire-up (e.g. /openconfig-system → hostname) is
visible as a NEW assertion failing here, not as silent drift.

Coverage targets:

* ``test_parses_without_exceptions`` — fixture is well-formed and the
  parser accepts it.
* ``test_populates_every_expected_canonical_field`` — one assertion
  per canonical field exercised by the fixture.  Honest about what
  this NETCONF stub does NOT cover vs the CLI sibling (asserts those
  fields stay empty / default — a future wire-up flips them).
* ``test_round_trip_stable`` — ``parse(render(parse(raw))) == parse(raw)``,
  the codec's load-bearing invariant.

See ``tests/fixtures/synthetic/cisco_iosxe/kitchen_sink.xml`` for the
fixture itself; the per-interface scope notes in that file mirror this
suite's assertions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netconfig.migration.canonical.intent import CanonicalIntent
from netconfig.migration.codecs.cisco_iosxe import CiscoIOSXECodec

pytestmark = pytest.mark.unit


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "synthetic"
    / "cisco_iosxe"
    / "kitchen_sink.xml"
)


@pytest.fixture(scope="module")
def raw_xml() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed(raw_xml: str) -> CanonicalIntent:
    return CiscoIOSXECodec().parse(raw_xml)


# ---------------------------------------------------------------------------
# 1. Parse without exceptions
# ---------------------------------------------------------------------------


def test_parses_without_exceptions(raw_xml: str) -> None:
    """The synthetic kitchen-sink XML must round-trip cleanly through
    :meth:`CiscoIOSXECodec.parse` with no :class:`ParseError`.  A new
    parser-level strictness check (e.g. tighter YANG-boolean handling)
    that breaks this fixture is a signal that either the fixture or
    the matrix needs updating.
    """
    intent = CiscoIOSXECodec().parse(raw_xml)
    assert isinstance(intent, CanonicalIntent)
    # Source-provenance metadata gets stamped by parse().
    assert intent.source_vendor == "cisco_iosxe"
    assert intent.source_format == "xml-netconf"


# ---------------------------------------------------------------------------
# 2. One assertion per canonical field the codec actually populates
# ---------------------------------------------------------------------------


class TestPopulatesEveryExpectedCanonicalField:
    """One assertion per canonical-tree field this codec writes.

    The cisco_iosxe NETCONF stub populates a strict subset of the
    full :class:`CanonicalIntent` schema; tests below assert both
    what IS exercised (positive surface) and what is NOT (negative
    surface — those fields remain at their default empty / None
    values in the parsed tree until a future wire-up).
    """

    # ── Positive surface: fields the codec DOES populate ──

    def test_interface_count(self, parsed: CanonicalIntent) -> None:
        """Ten interfaces of varied flavours are declared in the fixture."""
        assert len(parsed.interfaces) == 10

    def test_interface_name(self, parsed: CanonicalIntent) -> None:
        """Every interface carries its OpenConfig <name> verbatim."""
        names = [iface.name for iface in parsed.interfaces]
        assert names == [
            "GigabitEthernet0/0/0",
            "GigabitEthernet0/0/1",
            "GigabitEthernet0/0/2",
            "GigabitEthernet0/0/3",
            "Loopback0",
            "Loopback1",
            "Tunnel100",
            "Vlan10",
            "Port-channel1",
            "GigabitEthernet0/0/4",
        ]

    def test_interface_description(self, parsed: CanonicalIntent) -> None:
        """description is populated from <config><description>."""
        by_name = {i.name: i for i in parsed.interfaces}
        assert (
            by_name["GigabitEthernet0/0/0"].description
            == "WAN uplink to upstream carrier"
        )
        assert (
            by_name["Loopback0"].description
            == "Router ID / iBGP peering loopback"
        )
        # The bare interface (no <description> element) gets "" as
        # the canonical default — empty string, never None.
        assert by_name["GigabitEthernet0/0/4"].description == ""

    def test_interface_enabled_true(self, parsed: CanonicalIntent) -> None:
        """``<enabled>true</enabled>`` parses to Python ``True``."""
        by_name = {i.name: i for i in parsed.interfaces}
        assert by_name["GigabitEthernet0/0/0"].enabled is True
        assert by_name["Loopback0"].enabled is True

    def test_interface_enabled_false(self, parsed: CanonicalIntent) -> None:
        """``<enabled>false</enabled>`` parses to Python ``False``."""
        by_name = {i.name: i for i in parsed.interfaces}
        assert by_name["GigabitEthernet0/0/2"].enabled is False

    def test_interface_type_ethernet(self, parsed: CanonicalIntent) -> None:
        """``ianaift:ethernetCsmacd`` round-trips into ``interface_type``."""
        by_name = {i.name: i for i in parsed.interfaces}
        assert by_name["GigabitEthernet0/0/0"].interface_type == "ianaift:ethernetCsmacd"

    def test_interface_type_softwareloopback(self, parsed: CanonicalIntent) -> None:
        """``ianaift:softwareLoopback`` round-trips into ``interface_type``."""
        by_name = {i.name: i for i in parsed.interfaces}
        assert by_name["Loopback0"].interface_type == "ianaift:softwareLoopback"
        assert by_name["Loopback1"].interface_type == "ianaift:softwareLoopback"

    def test_interface_type_tunnel(self, parsed: CanonicalIntent) -> None:
        """``ianaift:tunnel`` round-trips into ``interface_type``."""
        by_name = {i.name: i for i in parsed.interfaces}
        assert by_name["Tunnel100"].interface_type == "ianaift:tunnel"

    def test_interface_type_l2vlan(self, parsed: CanonicalIntent) -> None:
        """SVI / VLAN-interface l2vlan type round-trips."""
        by_name = {i.name: i for i in parsed.interfaces}
        assert by_name["Vlan10"].interface_type == "ianaift:l2vlan"

    def test_interface_type_lag(self, parsed: CanonicalIntent) -> None:
        """``ianaift:ieee8023adLag`` round-trips into ``interface_type``."""
        by_name = {i.name: i for i in parsed.interfaces}
        assert by_name["Port-channel1"].interface_type == "ianaift:ieee8023adLag"

    def test_ipv4_single_address(self, parsed: CanonicalIntent) -> None:
        """Single-address subinterface populates one entry in
        :attr:`CanonicalInterface.ipv4_addresses`."""
        by_name = {i.name: i for i in parsed.interfaces}
        wan = by_name["GigabitEthernet0/0/0"]
        assert len(wan.ipv4_addresses) == 1
        assert wan.ipv4_addresses[0].ip == "198.51.100.1"
        assert wan.ipv4_addresses[0].prefix_length == 30

    def test_ipv4_multiple_addresses_on_one_subinterface(
        self, parsed: CanonicalIntent
    ) -> None:
        """A subinterface with three <address> children produces three
        :class:`CanonicalIPv4Address` entries on the parent interface."""
        by_name = {i.name: i for i in parsed.interfaces}
        lan = by_name["GigabitEthernet0/0/1"]
        assert len(lan.ipv4_addresses) == 3
        ips = sorted(a.ip for a in lan.ipv4_addresses)
        assert ips == ["10.0.10.1", "10.0.11.1", "10.0.12.1"]
        # All three carry their /24 prefix length.
        for addr in lan.ipv4_addresses:
            assert addr.prefix_length == 24

    def test_ipv4_addresses_collapse_across_subinterfaces(
        self, parsed: CanonicalIntent
    ) -> None:
        """The canonical bridge flattens addresses across ALL
        ``<subinterface>`` entries into the parent's flat list — one
        with index=0 plus one with index=100 yield two entries."""
        by_name = {i.name: i for i in parsed.interfaces}
        port3 = by_name["GigabitEthernet0/0/3"]
        ips = sorted(a.ip for a in port3.ipv4_addresses)
        assert ips == ["172.16.0.1", "172.16.100.1"]

    def test_ipv4_loopback_host_route(self, parsed: CanonicalIntent) -> None:
        """``/32`` is a valid YANG inet:ipv4-prefix length and
        round-trips for the classic router-id pattern."""
        by_name = {i.name: i for i in parsed.interfaces}
        lo0 = by_name["Loopback0"]
        assert len(lo0.ipv4_addresses) == 1
        assert lo0.ipv4_addresses[0].ip == "10.255.255.1"
        assert lo0.ipv4_addresses[0].prefix_length == 32

    def test_ipv6_single_global_address(self, parsed: CanonicalIntent) -> None:
        """An ``<ipv6>`` subtree alongside ``<ipv4>`` on the same
        subinterface produces a separate ipv6_addresses entry."""
        by_name = {i.name: i for i in parsed.interfaces}
        wan = by_name["GigabitEthernet0/0/0"]
        assert len(wan.ipv6_addresses) == 1
        assert wan.ipv6_addresses[0].ip == "2001:db8:cafe::1"
        assert wan.ipv6_addresses[0].prefix_length == 64

    def test_ipv6_multiple_addresses_global_and_ula(
        self, parsed: CanonicalIntent
    ) -> None:
        """An IPv6-only loopback with two addresses (global + ULA)
        produces two :class:`CanonicalIPv6Address` entries."""
        by_name = {i.name: i for i in parsed.interfaces}
        lo1 = by_name["Loopback1"]
        assert len(lo1.ipv6_addresses) == 2
        assert {a.ip for a in lo1.ipv6_addresses} == {
            "2001:db8::1",
            "fd00:db8:1::1",
        }
        for addr in lo1.ipv6_addresses:
            assert addr.prefix_length == 128

    def test_ipv6_scope_defaults_to_global(self, parsed: CanonicalIntent) -> None:
        """The codec stub does not yet infer link-local scope from the
        wire — every parsed IPv6 address comes back ``scope='global'``.
        This test pins the current behaviour so a future scope-inference
        commit visibly flips the assertion (and forces a fixture refresh)."""
        for iface in parsed.interfaces:
            for addr in iface.ipv6_addresses:
                assert addr.scope == "global"

    def test_dual_stack_on_svi(self, parsed: CanonicalIntent) -> None:
        """Vlan10 SVI carries both an IPv4 and an IPv6 address — the
        canonical model holds both lists side-by-side without conflict."""
        by_name = {i.name: i for i in parsed.interfaces}
        svi = by_name["Vlan10"]
        assert len(svi.ipv4_addresses) == 1
        assert svi.ipv4_addresses[0].ip == "10.10.10.1"
        assert len(svi.ipv6_addresses) == 1
        assert svi.ipv6_addresses[0].ip == "2001:db8:10::1"

    def test_lag_dual_stack_addressing(self, parsed: CanonicalIntent) -> None:
        """The Port-channel itself carries L3 — exercises both v4 and
        v6 on the LAG aggregator (not on a member port)."""
        by_name = {i.name: i for i in parsed.interfaces}
        po1 = by_name["Port-channel1"]
        assert po1.ipv4_addresses[0].ip == "10.20.30.1"
        assert po1.ipv4_addresses[0].prefix_length == 30
        assert po1.ipv6_addresses[0].ip == "2001:db8:20::1"
        assert po1.ipv6_addresses[0].prefix_length == 126

    def test_bare_interface_has_no_addresses(self, parsed: CanonicalIntent) -> None:
        """A <config>-only interface with no <subinterfaces> yields
        empty ipv4 / ipv6 address lists — never ``None``."""
        by_name = {i.name: i for i in parsed.interfaces}
        bare = by_name["GigabitEthernet0/0/4"]
        assert bare.ipv4_addresses == []
        assert bare.ipv6_addresses == []

    # ── Negative surface: fields the codec does NOT populate ──

    def test_mtu_is_dropped_at_canonical_bridge(
        self, parsed: CanonicalIntent
    ) -> None:
        """``<mtu>`` is parsed into the intermediate dict but the canonical
        bridge does NOT carry it through — declared lossy in the
        capability matrix.  The CLI sibling (cisco_iosxe_cli) populates
        ``CanonicalInterface.mtu``; this NETCONF stub leaves it ``None``.

        Pinning this here makes a future MTU wire-up flip the assertion
        visibly instead of silently changing semantics on real fixtures.
        """
        for iface in parsed.interfaces:
            assert iface.mtu is None, (
                f"{iface.name}: MTU unexpectedly carried through "
                f"(got {iface.mtu!r}); did the canonical bridge gain "
                f"MTU support?  Update this fixture's assertions."
            )

    def test_switchport_state_not_populated(
        self, parsed: CanonicalIntent
    ) -> None:
        """OpenConfig switchport semantics live in
        ``openconfig-vlan`` augmented onto ``ethernet``, which the
        stub doesn't parse.  All interfaces remain "routed" (``None``)
        until a future wire-up."""
        for iface in parsed.interfaces:
            assert iface.switchport_mode is None
            assert iface.access_vlan is None
            assert iface.trunk_allowed_vlans == []
            assert iface.trunk_native_vlan is None

    def test_vrf_membership_not_populated(self, parsed: CanonicalIntent) -> None:
        """VRF membership lives under ``openconfig-network-instance``,
        not yet wired into this codec."""
        for iface in parsed.interfaces:
            assert iface.vrf == ""

    def test_lag_member_back_pointer_not_populated(
        self, parsed: CanonicalIntent
    ) -> None:
        """``CanonicalInterface.lag_member_of`` is back-filled by codecs
        that parse aggregate-id from member ports.  The OpenConfig
        ``aggregate-id`` augment isn't wired into this stub — every
        parsed interface remains "unbundled"."""
        for iface in parsed.interfaces:
            assert iface.lag_member_of is None

    def test_top_level_sections_unpopulated(
        self, parsed: CanonicalIntent
    ) -> None:
        """The cisco_iosxe NETCONF codec parses ONLY the
        ``<interfaces>`` subtree.  Top-level system / VLANs /
        routing / SNMP / users sections stay at their canonical
        defaults — empty strings, empty lists, ``None``.

        The capability matrix declares many of these as ``supported``
        (so cross-codec translations targeting iosxe don't see the
        paths classified as unsupported) but the parse() stub does
        not yet extract them from XML.  The cisco_iosxe_cli sibling
        provides the working implementation today.
        """
        assert parsed.hostname == ""
        assert parsed.domain == ""
        assert parsed.dns_servers == []
        assert parsed.ntp_servers == []
        assert parsed.timezone == ""
        assert parsed.syslog_servers == []
        assert parsed.vlans == []
        assert parsed.static_routes == []
        assert parsed.dhcp_servers == []
        assert parsed.snmp is None
        assert parsed.lags == []
        assert parsed.local_users == []
        assert parsed.radius_servers == []
        assert parsed.vxlan_vnis == []
        assert parsed.evpn_type5_routes == []
        assert parsed.routing_instances == []
        assert parsed.raw_sections == {}


# ---------------------------------------------------------------------------
# 3. Round-trip stability
# ---------------------------------------------------------------------------


def test_round_trip_stable(raw_xml: str) -> None:
    """``parse(render(parse(raw))) == parse(raw)`` — the codec's
    load-bearing invariant.  Asserted across the entire kitchen-sink
    fixture, not just one interface, so any asymmetry between the
    parse and render paths (e.g. an XML element silently dropped on
    re-render) shows up here.

    Render takes the canonical tree (not the original XML), so this
    guarantees only that the SUPPORTED subset round-trips.  Anything
    the codec drops on parse (top-level system data, VLANs, MTU)
    cannot possibly come back on re-parse — but every field that
    survives the parse must come back identically.
    """
    codec = CiscoIOSXECodec()
    first_parse = codec.parse(raw_xml)
    rendered = codec.render(first_parse)
    second_parse = codec.parse(rendered)
    assert second_parse == first_parse
