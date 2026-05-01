"""Synthetic kitchen-sink fixture tests for ``FortiGateCLICodec``.

Documents WHICH canonical fields the FortiGate CLI codec actually
populates from a single hand-crafted FortiOS config that exercises
every supported / lossy capability listed in
:class:`FortiGateCLICodec._CAPS`.  Complements the real-capture
corpus in ``tests/fixtures/real/fortigate/`` with a focused
exhaustive case where the parser-side behaviour is fully predictable.

Skipped intentionally — the codec's CapabilityMatrix marks these
unsupported in the current canonical mapping:

* BGP / route-maps / EVPN / VXLAN  — Tier-3 firewall semantics.
* timezone / syslog_servers        — not wired in the parse dispatcher
  (FortiOS exports them via ``config system global / set timezone``
  and ``config log syslogd setting`` respectively, but neither path
  has a canonical applier yet).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import netconfig.migration  # noqa: F401  (registers the codec)

from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec

pytestmark = pytest.mark.unit


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "synthetic"
    / "fortigate_cli"
    / "kitchen_sink.conf"
)


def test_parses_without_exceptions():
    """The kitchen-sink fixture parses cleanly into a CanonicalIntent."""
    raw = FIXTURE.read_text()
    tree = FortiGateCLICodec().parse(raw)
    # Sanity: source provenance is stamped by parse_intent.
    assert tree.source_vendor == "fortigate"
    assert tree.source_format == "cli-fortigate"


def test_populates_every_expected_canonical_field():
    """Per-canonical-field coverage assertions.

    Each block corresponds to a capability listed in the codec's
    CapabilityMatrix or wired in the parse dispatcher.  Failing
    assertions here mean either (a) the fixture stopped exercising
    a feature or (b) the parser regressed.
    """
    raw = FIXTURE.read_text()
    tree = FortiGateCLICodec().parse(raw)

    # --- Tier 1: hostname / dns / ntp ---
    assert tree.hostname == "fgt-kitchensink"
    assert tree.dns_servers == ["1.1.1.1", "8.8.8.8"]
    assert tree.ntp_servers == ["0.pool.ntp.org", "time.google.com"]

    # --- Tier 1: interfaces (>=5 covering physical, vlan, loopback,
    # aggregate, IPv4 + IPv6 + MTU + alias) ---
    assert len(tree.interfaces) >= 5
    by_name = {i.name: i for i in tree.interfaces}

    # Physical port with IPv4, IPv6, MTU, alias.
    port1 = by_name["port1"]
    assert port1.description == "WAN-uplink"
    assert port1.enabled is True
    assert port1.mtu == 1500
    assert port1.ipv4_addresses[0].ip == "198.51.100.2"
    assert port1.ipv4_addresses[0].prefix_length == 30
    assert port1.ipv6_addresses[0].ip == "2001:db8:cafe::2"
    assert port1.ipv6_addresses[0].prefix_length == 64

    # Loopback shape inferred from the name.
    loop = by_name["loopback0"]
    assert loop.interface_type == "ianaift:softwareLoopback"
    assert loop.ipv6_addresses[0].prefix_length == 128

    # VLAN child interface — interface_type set + IPv6 carried
    # through the VLAN sub-interface.
    v100 = by_name["agg1.100"]
    assert v100.interface_type == "ianaift:l3ipvlan"
    assert v100.ipv4_addresses[0].ip == "10.100.0.1"
    assert v100.ipv6_addresses[0].ip == "2001:db8:100::1"

    # User-named VLAN (no `set type vlan` — vlanid + parent
    # interface alone are enough; matches the FGT-70G real-capture
    # idiom).
    vl200 = by_name["VL_200"]
    assert vl200.interface_type == "ianaift:l3ipvlan"

    # Disabled VLAN child.
    v300 = by_name["port4.300"]
    assert v300.enabled is False

    # Aggregate ifaces have aggregate type.
    agg1 = by_name["agg1"]
    assert agg1.interface_type == "ianaift:ieee8023adLag"

    # --- Tier 1: vlans (>=3, implicit via VLAN child interfaces) ---
    vlan_ids = sorted(v.id for v in tree.vlans)
    assert vlan_ids == [100, 200, 300]

    # --- Tier 1: static_routes (>=2, IPv4 + a secondary route) ---
    assert len(tree.static_routes) >= 2
    routes_by_dst = {r.destination: r for r in tree.static_routes}
    default = routes_by_dst["0.0.0.0/0"]
    assert default.gateway == "198.51.100.1"
    assert default.interface == "port1"
    aggr_route = routes_by_dst["10.99.0.0/16"]
    assert aggr_route.gateway == "10.20.0.254"
    assert aggr_route.interface == "agg1"

    # --- Tier 2: lags (>=2 via `config system interface / type
    # aggregate`) ---
    assert len(tree.lags) >= 2
    lag_by_name = {lag.name: lag for lag in tree.lags}
    assert lag_by_name["agg1"].members == ["port2", "port3"]
    assert lag_by_name["agg1"].mode == "active"
    assert lag_by_name["agg2"].members == ["port5", "port6"]
    assert lag_by_name["agg2"].mode == "passive"
    # Cross-link: members carry lag_member_of back-pointer.
    assert by_name["port2"].lag_member_of == "agg1"
    assert by_name["port5"].lag_member_of == "agg2"

    # --- Tier 2: local_users (>=3 via `config system admin`) ---
    assert len(tree.local_users) >= 3
    users_by_name = {u.name: u for u in tree.local_users}
    # super_admin -> privilege 15.
    assert users_by_name["admin"].privilege_level == 15
    assert users_by_name["admin"].role == "super_admin"
    # Hash carried verbatim with the fortios: tag.
    assert users_by_name["admin"].hashed_password.startswith("fortios:ENC ")
    # Custom profile preserved on `role`.
    assert users_by_name["netops"].role == "prof_admin"
    assert users_by_name["netops"].privilege_level == 1
    assert users_by_name["auditor"].role == "super_admin_readonly"

    # --- Tier 2: SNMP community + sysinfo ---
    assert tree.snmp is not None
    assert tree.snmp.community == "public-ro"
    assert tree.snmp.location == "data-center-rack-7"
    assert tree.snmp.contact == "noc@example.org"
    # Trap-host targets sourced from the nested `config hosts` block.
    assert tree.snmp.trap_hosts == ["10.50.0.10", "10.50.0.11"]

    # --- Tier 2: SNMPv3 USM users (>=2) ---
    assert len(tree.snmp.v3_users) >= 2
    v3_by_name = {u.name: u for u in tree.snmp.v3_users}
    monitor = v3_by_name["monitor-readonly"]
    assert monitor.auth_protocol == "sha256"
    assert monitor.priv_protocol == "aes256"
    assert "ENC" in monitor.auth_passphrase
    assert "ENC" in monitor.priv_passphrase
    noc = v3_by_name["noc-fullaccess"]
    assert noc.auth_protocol == "sha512"
    assert noc.priv_protocol == "aes256"

    # --- Tier 2: radius_servers ---
    assert len(tree.radius_servers) >= 1
    radius_by_host = {s.host: s for s in tree.radius_servers}
    primary = radius_by_host["10.50.0.20"]
    assert primary.auth_port == 1812
    assert primary.key.startswith("fortios:ENC ")
    secondary = radius_by_host["10.50.0.21"]
    assert secondary.auth_port == 1645

    # --- Tier 2: dhcp_servers ---
    assert len(tree.dhcp_servers) >= 1
    dhcp_by_iface = {p.interface: p for p in tree.dhcp_servers}
    pool_lan = dhcp_by_iface["port4"]
    assert pool_lan.network == "10.10.0.0/24"
    assert pool_lan.gateway == "10.10.0.1"
    assert pool_lan.start_ip == "10.10.0.100"
    assert pool_lan.end_ip == "10.10.0.200"
    assert pool_lan.dns_servers == ["1.1.1.1", "8.8.8.8"]
    assert pool_lan.domain_name == "lab.example.org"
    assert pool_lan.lease_time == 86400
    pool_guest = dhcp_by_iface["port4.300"]
    assert pool_guest.lease_time == 43200
    assert pool_guest.dns_servers == ["9.9.9.9"]


def test_round_trip_stable():
    """``parse(render(parse(raw))) == parse(raw)`` — canonical-tree fixed
    point.

    Within-vendor round-trip is the contract that lets the FortiGate
    codec be used as both source and target.  Defaults that FortiOS
    omits on export (``radius-port 1812``, ``mtu 1500`` baseline) are
    handled by the renderer's omit-on-default rules; this test
    catches drift if those rules diverge from the parser's defaults.
    """
    codec = FortiGateCLICodec()
    raw = FIXTURE.read_text()
    tree1 = codec.parse(raw)
    emitted = codec.render(tree1)
    tree2 = codec.parse(emitted)
    assert tree1 == tree2
