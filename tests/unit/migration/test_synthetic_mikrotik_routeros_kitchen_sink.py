"""
Synthetic kitchen-sink fixture tests for the ``MikroTikRouterOSCodec``.

Loads ``tests/fixtures/synthetic/mikrotik_routeros/kitchen_sink.rsc`` and
verifies:

1. The fixture parses without exceptions.
2. The parsed :class:`CanonicalIntent` populates every canonical field
   that the codec's CapabilityMatrix marks ``supported`` or ``lossy``,
   plus the Tier-2 surfaces the parser populates (LAGs, local users,
   DHCP, RADIUS, SNMPv3 USM).
3. ``parse(render(parse(raw)))`` is byte-stable on the second pass — a
   single round-trip is sufficient to drive the canonical tree to a
   fixed point regardless of which RouterOS-defaulted attributes the
   source happened to carry.

This is the cross-vendor "every field" smoke fixture for
mikrotik_routeros — companion to the same idea for arista_eos.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netconfig.migration.canonical.intent import CanonicalIntent
from netconfig.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec

pytestmark = pytest.mark.unit


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "synthetic"
    / "mikrotik_routeros"
    / "kitchen_sink.rsc"
)


@pytest.fixture(scope="module")
def raw_fixture() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parsed_intent(raw_fixture: str) -> CanonicalIntent:
    return MikroTikRouterOSCodec().parse(raw_fixture)


# ---------------------------------------------------------------------------
# 1. Parses cleanly
# ---------------------------------------------------------------------------


def test_parses_without_exceptions(raw_fixture: str) -> None:
    """The fixture parses to a CanonicalIntent without raising."""
    intent = MikroTikRouterOSCodec().parse(raw_fixture)
    assert isinstance(intent, CanonicalIntent)
    assert intent.source_vendor == "mikrotik_routeros"
    assert intent.source_format == "cli-mikrotik"


# ---------------------------------------------------------------------------
# 2. Populates every expected canonical field
# ---------------------------------------------------------------------------


def test_populates_every_expected_canonical_field(
    parsed_intent: CanonicalIntent,
) -> None:
    """Per CapabilityMatrix supported + lossy paths, every canonical
    field that mikrotik_routeros claims to handle must have data."""
    intent = parsed_intent

    # ----- /system/hostname -----
    assert intent.hostname == "ks-edge-01"

    # ----- /system/dns-server -----
    assert "1.1.1.1" in intent.dns_servers
    assert "8.8.8.8" in intent.dns_servers

    # ----- /system/ntp-server -----
    assert "10.0.0.123" in intent.ntp_servers
    assert "pool.ntp.org" in intent.ntp_servers

    # ----- /interfaces/interface (≥6 with descriptions, enabled flags) -----
    assert len(intent.interfaces) >= 6
    iface_by_name = {i.name: i for i in intent.interfaces}

    # ether1 — physical with comment
    assert "ether1" in iface_by_name
    ether1 = iface_by_name["ether1"]
    assert ether1.description == "WAN uplink to ISP"
    assert ether1.enabled is True
    assert ether1.interface_type == "ianaift:ethernetCsmacd"
    assert ether1.default_name == "ether1"

    # ether6 — physical, admin disabled
    assert "ether6" in iface_by_name
    assert iface_by_name["ether6"].enabled is False

    # bridge1 — bridge interface
    assert "bridge1" in iface_by_name
    bridge1 = iface_by_name["bridge1"]
    assert bridge1.interface_type == "ianaift:bridge"
    assert bridge1.description == "Primary LAN bridge"

    # bond1 — LAG interface (LACP)
    assert "bond1" in iface_by_name
    bond1 = iface_by_name["bond1"]
    assert bond1.interface_type == "ianaift:ieee8023adLag"
    assert bond1.description == "LACP bond to upstream core"

    # vlan100 — VLAN child interface (l3ipvlan)
    assert "vlan100" in iface_by_name
    vlan100 = iface_by_name["vlan100"]
    assert vlan100.interface_type == "ianaift:l3ipvlan"
    assert vlan100.description == "Users VLAN"

    # ----- /interfaces/interface/ipv4/address -----
    # ether1 has 198.51.100.2/30
    assert any(
        a.ip == "198.51.100.2" and a.prefix_length == 30
        for a in ether1.ipv4_addresses
    )
    # bridge1 has 10.0.0.1/24
    assert any(
        a.ip == "10.0.0.1" and a.prefix_length == 24
        for a in bridge1.ipv4_addresses
    )
    # vlan100 has 10.100.0.1/24
    assert any(
        a.ip == "10.100.0.1" and a.prefix_length == 24
        for a in vlan100.ipv4_addresses
    )
    # bond1 has 10.255.0.1/32
    assert any(
        a.ip == "10.255.0.1" and a.prefix_length == 32
        for a in bond1.ipv4_addresses
    )

    # ----- /interfaces/interface/ipv6/address (GAP-EVPN-3) -----
    # ether1 has both global + link-local
    ether1_v6 = ether1.ipv6_addresses
    assert any(
        a.ip == "2001:db8:0:1::2" and a.prefix_length == 64
        and a.scope == "global"
        for a in ether1_v6
    )
    assert any(
        a.ip == "fe80::1" and a.scope == "link-local"
        for a in ether1_v6
    )
    # vlan100 has IPv6 too
    assert any(
        a.ip == "2001:db8:100::1" and a.prefix_length == 64
        for a in vlan100.ipv6_addresses
    )

    # ----- /vlans/vlan/id + /vlans/vlan/name -----
    vlan_ids = {v.id for v in intent.vlans}
    assert {100, 200, 300}.issubset(vlan_ids)
    vlan_by_id = {v.id: v for v in intent.vlans}
    assert vlan_by_id[100].name == "vlan100"
    assert vlan_by_id[200].name == "vlan200"
    assert vlan_by_id[300].name == "vlan300"
    # description carried from RouterOS comment field
    assert vlan_by_id[100].description == "Users VLAN"

    # ----- /routing/static-route (≥3 IPv4 + IPv6 + via interface) -----
    assert len(intent.static_routes) >= 3
    destinations = {r.destination for r in intent.static_routes}
    assert "0.0.0.0/0" in destinations
    assert "::/0" in destinations
    assert "10.50.0.0/16" in destinations
    # via-interface route stores iface name in gateway field
    blackhole = next(
        r for r in intent.static_routes
        if r.destination == "192.168.99.0/24"
    )
    assert blackhole.gateway == "bridge1"

    # ----- LAGs (Tier 2) -----
    assert len(intent.lags) >= 2
    lag_by_name = {l.name: l for l in intent.lags}
    assert "bond1" in lag_by_name
    assert lag_by_name["bond1"].mode == "active"        # 802.3ad → LACP
    assert "ether3" in lag_by_name["bond1"].members
    assert "ether4" in lag_by_name["bond1"].members
    assert "bond2" in lag_by_name
    assert lag_by_name["bond2"].mode == "static"        # active-backup
    # LAG members back-link
    assert iface_by_name["ether3"].lag_member_of == "bond1"
    assert iface_by_name["ether5"].lag_member_of == "bond2"

    # ----- Local users (≥3, different groups → privilege) -----
    assert len(intent.local_users) >= 3
    users_by_name = {u.name: u for u in intent.local_users}
    assert users_by_name["admin"].privilege_level == 15      # full
    assert users_by_name["admin"].role == "admin"
    assert users_by_name["operator"].privilege_level == 10   # write
    assert users_by_name["auditor"].privilege_level == 1     # read

    # ----- SNMP community + v3 (Tier 2) -----
    assert intent.snmp is not None
    assert intent.snmp.community == "public"
    assert intent.snmp.contact == "noc@example.net"
    assert intent.snmp.location == "Synthetic Lab Rack 7"
    assert "10.0.0.250" in intent.snmp.trap_hosts

    # ≥2 v3 users with different auth + priv protocols
    assert len(intent.snmp.v3_users) >= 2
    v3_by_name = {u.name: u for u in intent.snmp.v3_users}
    assert "monitor-v3" in v3_by_name
    assert v3_by_name["monitor-v3"].auth_protocol == "sha"   # SHA1 → sha
    assert v3_by_name["monitor-v3"].priv_protocol == "aes128"
    assert v3_by_name["monitor-v3"].auth_passphrase == "fake-auth-passphrase-1"
    assert v3_by_name["monitor-v3"].priv_passphrase == "fake-priv-passphrase-1"
    assert "audit-v3" in v3_by_name
    assert v3_by_name["audit-v3"].auth_protocol == "sha256"
    assert v3_by_name["audit-v3"].priv_protocol == "aes256"

    # ----- RADIUS (Tier 2) -----
    assert len(intent.radius_servers) >= 1
    radius_by_host = {r.host: r for r in intent.radius_servers}
    assert "10.0.0.10" in radius_by_host
    assert radius_by_host["10.0.0.10"].key == "fake-radius-shared-secret-1"
    assert radius_by_host["10.0.0.10"].auth_port == 1812
    assert radius_by_host["10.0.0.10"].acct_port == 1813
    # The non-default-port server
    assert "10.0.0.11" in radius_by_host
    assert radius_by_host["10.0.0.11"].auth_port == 1645
    assert radius_by_host["10.0.0.11"].acct_port == 1646

    # ----- DHCP servers (Tier 2) -----
    assert len(intent.dhcp_servers) >= 2
    dhcp_by_network = {p.network: p for p in intent.dhcp_servers}
    assert "10.0.0.0/24" in dhcp_by_network
    lan = dhcp_by_network["10.0.0.0/24"]
    assert lan.gateway == "10.0.0.1"
    assert "10.0.0.1" in lan.dns_servers
    assert "1.1.1.1" in lan.dns_servers
    assert lan.domain_name == "lab.example.net"
    # range merged from /ip pool
    assert lan.start_ip == "10.0.0.100"
    assert lan.end_ip == "10.0.0.200"


# ---------------------------------------------------------------------------
# 3. Round-trip stability
# ---------------------------------------------------------------------------


def test_round_trip_stable(raw_fixture: str) -> None:
    """``parse(render(parse(raw)))`` reaches a fixed point on the
    second pass — i.e. parse → render → parse → render → parse
    matches parse → render → parse.

    A single round-trip is enough to drive the canonical tree to its
    canonical (no-defaults-noise) form; further passes must not change
    it.  This is the standard codec round-trip invariant.
    """
    codec = MikroTikRouterOSCodec()
    tree1 = codec.parse(raw_fixture)
    rendered1 = codec.render(tree1)
    tree2 = codec.parse(rendered1)
    rendered2 = codec.render(tree2)

    # Second-pass render must be byte-stable.
    assert rendered2 == rendered1, (
        "render output is not stable across a second round-trip"
    )

    # The canonical trees must be equal too (modulo source-metadata
    # fields that the parser stamps fresh on each parse).
    tree3 = codec.parse(rendered2)
    # Strip the source-vendor / source-format fields for comparison
    # — they're parser-injected metadata, not user data.
    def _normalised(t: CanonicalIntent) -> dict:
        d = t.model_dump()
        d.pop("source_vendor", None)
        d.pop("source_format", None)
        d.pop("source_version", None)
        return d

    assert _normalised(tree2) == _normalised(tree3)
