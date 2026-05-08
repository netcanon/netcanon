"""
Synthetic kitchen-sink coverage test for the arista_eos codec.

Real-capture fixtures under ``tests/fixtures/real/arista_eos/`` test
"what survives parse on real-world configs" — by definition they only
exercise the subset of features the source operator chose to deploy.
The kitchen-sink fixture under
``tests/fixtures/synthetic/arista_eos/kitchen_sink.txt`` complements
that by exercising EVERY canonical field the arista_eos
:class:`CapabilityMatrix` declares as ``supported`` or ``lossy``, plus
the LAG / local-user / VRF / EVPN-VXLAN surfaces the parser populates.

Three tests:

1. :func:`test_parses_without_exceptions` — sanity: the file parses
   without raising.
2. :func:`test_populates_every_expected_canonical_field` — one
   assertion per supported canonical field; failures here mean either
   the codec regressed or the fixture lost coverage.
3. :func:`test_round_trip_stable` — parse → render → parse produces
   the same canonical content (set-equality on lists; the codec
   itself does not promise textual round-trip stability for synthetic
   input, only canonical stability).

When extending the fixture, add the corresponding assertion in test
(2) so the coverage matrix stays explicit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.arista_eos import AristaEOSCodec

pytestmark = pytest.mark.unit


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "synthetic" / "arista_eos" / "kitchen_sink.txt"
)


@pytest.fixture(scope="module")
def raw_text() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def codec() -> AristaEOSCodec:
    return AristaEOSCodec()


# ---------------------------------------------------------------------------
# Test 1 — sanity parse
# ---------------------------------------------------------------------------


def test_parses_without_exceptions(codec, raw_text):
    """The kitchen-sink fixture must parse without raising."""
    intent = codec.parse(raw_text)
    assert intent is not None
    assert intent.source_vendor == "arista_eos"
    assert intent.source_format == "cli-arista"


# ---------------------------------------------------------------------------
# Test 2 — exhaustive canonical-field coverage
# ---------------------------------------------------------------------------


def test_populates_every_expected_canonical_field(codec, raw_text):
    """Every canonical field the arista_eos codec supports must be
    populated by the kitchen-sink fixture.

    The assertions below mirror the ``supported`` + ``lossy`` lists in
    :class:`AristaEOSCodec._CAPS`.  Fields the codec lists as
    ``unsupported`` (BGP / OSPF) or that aren't applicable to Arista
    (apply_groups, syslog_servers, timezone, dhcp_servers,
    radius_servers — none of which the codec parses) are intentionally
    not asserted.
    """
    intent = codec.parse(raw_text)

    # /system/hostname
    assert intent.hostname == "ks-leaf-01"

    # /system/dns-server (+ domain — bonus surface the codec parses)
    assert len(intent.dns_servers) >= 2
    assert "10.0.0.53" in intent.dns_servers
    assert intent.domain == "example.net"

    # /system/ntp-server
    assert len(intent.ntp_servers) >= 2
    assert "10.0.0.123" in intent.ntp_servers

    # /interfaces/interface — at least 6 covering all required shapes.
    assert len(intent.interfaces) >= 6
    by_name = {i.name: i for i in intent.interfaces}

    # L3-routed Ethernet with IPv4 + global IPv6 + link-local IPv6.
    eth1 = by_name["Ethernet1"]
    assert eth1.description == "Spine uplink (L3 routed)"
    assert eth1.enabled is True
    assert eth1.mtu == 9214                                 # non-default MTU
    assert any(
        a.ip == "10.0.0.1" and a.prefix_length == 31
        for a in eth1.ipv4_addresses
    )
    assert any(
        a.ip == "2001:db8:0:1::1" and a.scope == "global"
        for a in eth1.ipv6_addresses
    )
    assert any(
        a.scope == "link-local" for a in eth1.ipv6_addresses
    )

    # Switchport access mode.
    eth2 = by_name["Ethernet2"]
    assert eth2.switchport_mode == "access"
    assert eth2.access_vlan == 10

    # Switchport trunk mode with allowed-vlan list.
    eth3 = by_name["Ethernet3"]
    assert eth3.switchport_mode == "trunk"
    assert eth3.trunk_allowed_vlans == [10, 20, 100, 200]

    # Vlan SVI with IPv4 + IPv6 + VRF binding.
    vlan100 = by_name["Vlan100"]
    assert vlan100.vrf == "TENANT_A"
    assert any(a.ip == "10.100.0.1" for a in vlan100.ipv4_addresses)
    assert any(a.ip == "2001:db8:100:100::1" for a in vlan100.ipv6_addresses)

    # Loopback with IPv4 + IPv6.
    lo0 = by_name["Loopback0"]
    assert any(a.ip == "10.255.0.1" for a in lo0.ipv4_addresses)
    assert any(a.ip == "2001:db8:ffff::1" for a in lo0.ipv6_addresses)

    # Port-Channel (LAG parent) and member-of-LAG back-pointers.
    eth4 = by_name["Ethernet4"]
    eth5 = by_name["Ethernet5"]
    assert eth4.lag_member_of == "Port-Channel10"
    assert eth5.lag_member_of == "Port-Channel10"
    assert "Port-Channel10" in by_name

    # Management interface.
    mgmt = by_name["Management1"]
    assert any(a.ip == "192.168.100.10" for a in mgmt.ipv4_addresses)
    assert any(a.ip == "2001:db8:100::a" for a in mgmt.ipv6_addresses)

    # /interfaces/interface/config/type — IANA inference (lossy).
    assert eth1.interface_type == "ianaift:ethernetCsmacd"
    assert lo0.interface_type == "ianaift:softwareLoopback"
    assert vlan100.interface_type == "ianaift:l3ipvlan"
    assert by_name["Port-Channel10"].interface_type == "ianaift:ieee8023adLag"
    assert mgmt.interface_type == "ianaift:ethernetCsmacd"

    # /vlans/vlan — at least 4 with names.
    assert len(intent.vlans) >= 4
    vlan_by_id = {v.id: v for v in intent.vlans}
    assert vlan_by_id[10].name == "USERS"
    assert vlan_by_id[20].name == "VOICE"
    assert vlan_by_id[100].name == "TENANT_A_DATA"
    assert vlan_by_id[200].name == "TRANSIT"

    # /routing/static-route — at least 2 IPv4 (the codec doesn't parse
    # IPv6 ``ipv6 route`` lines; the IPv6 route in the fixture is for
    # vendor realism, not canonical population).
    assert len(intent.static_routes) >= 2
    dests = {r.destination for r in intent.static_routes}
    assert "0.0.0.0/0" in dests
    assert "10.50.0.0/16" in dests

    # /snmp/community + /snmp/location + /snmp/contact + /snmp/trap-host
    assert intent.snmp is not None
    assert intent.snmp.community == "public"
    assert intent.snmp.location == "Synthetic Lab Rack 7"
    assert intent.snmp.contact == "noc@example.net"
    assert "10.0.0.250" in intent.snmp.trap_hosts

    # /snmp/v3-user — at least 2 USM users with auth + priv.
    assert len(intent.snmp.v3_users) >= 2
    v3_by_name = {u.name: u for u in intent.snmp.v3_users}
    assert v3_by_name["monitor"].auth_protocol == "sha"
    assert v3_by_name["monitor"].priv_protocol == "aes256"
    assert v3_by_name["monitor"].auth_passphrase != ""
    assert v3_by_name["monitor"].priv_passphrase != ""
    assert v3_by_name["readonly"].auth_protocol == "sha256"
    # ``aes`` (no bits) → canonical aes128.
    assert v3_by_name["readonly"].priv_protocol == "aes128"

    # /aaa/authentication/users/user — at least 3 with different hash
    # types: nopassword admin, sha512 secret, type-5 secret.
    assert len(intent.local_users) >= 3
    user_by_name = {u.name: u for u in intent.local_users}
    assert user_by_name["admin"].privilege_level == 15
    assert user_by_name["admin"].role == "network-admin"
    assert user_by_name["admin"].hashed_password == ""    # nopassword
    assert user_by_name["operator"].hashed_password.startswith("arista:sha512:")
    assert user_by_name["readonly"].hashed_password.startswith("arista:5:")
    assert user_by_name["readonly"].role == "network-operator"

    # /vxlan-vnis/vni + /vxlan-vnis/source-interface + /vxlan-vnis/udp-port
    assert len(intent.vxlan_vnis) >= 3
    vni_map = {v.vlan_id: v.vni for v in intent.vxlan_vnis}
    assert vni_map[10] == 10010
    assert vni_map[20] == 10020
    assert vni_map[100] == 10100
    # source-interface and udp-port are stamped on every record.
    for v in intent.vxlan_vnis:
        assert v.source_interface == "Loopback0"
        assert v.udp_port == 4789

    # /routing-instances/instance — one L3 VRF + one MAC-VRF.
    assert len(intent.routing_instances) >= 2
    ri_by_name = {ri.name: ri for ri in intent.routing_instances}
    # L3 VRF (asymmetric RTs: import has two, export has one).
    tenant_a = ri_by_name["TENANT_A"]
    assert tenant_a.instance_type == "vrf"
    assert tenant_a.route_distinguisher == "10.255.0.1:50100"
    assert "65000:50100" in tenant_a.rt_imports
    assert "65000:99999" in tenant_a.rt_imports
    assert "65000:50100" in tenant_a.rt_exports
    # L3 VNI captured from ``vxlan vrf TENANT_A vni 50100``.
    assert tenant_a.l3_vni == 50100
    # MAC-VRF (router bgp / vlan 100) — keyed by the vlan name.
    mac_vrf = ri_by_name["TENANT_A_DATA"]
    assert mac_vrf.instance_type == "mac-vrf"
    assert mac_vrf.route_distinguisher == "10.255.0.1:100"
    # ``route-target both`` — same RT in both directions.
    assert "65000:100" in mac_vrf.rt_imports
    assert "65000:100" in mac_vrf.rt_exports

    # LAGs — parser synthesises CanonicalLAG records from
    # channel-group lines.  Two channel-groups in the fixture.
    assert len(intent.lags) >= 2
    lag_by_name = {lag.name: lag for lag in intent.lags}
    assert set(lag_by_name["Port-Channel10"].members) == {
        "Ethernet4", "Ethernet5",
    }
    assert set(lag_by_name["Port-Channel20"].members) == {
        "Ethernet6", "Ethernet7",
    }

    # Source provenance metadata.
    assert intent.source_vendor == "arista_eos"
    assert intent.source_format == "cli-arista"


# ---------------------------------------------------------------------------
# Test 3 — round-trip canonical stability
# ---------------------------------------------------------------------------


def test_round_trip_stable(codec, raw_text):
    """parse → render → parse produces the same canonical content.

    Equality is set-based on lists (rendering may re-order entries —
    e.g. interface emission order is whatever the parse path appended,
    which is deterministic) and tuple-based on per-record identity
    fields.  The textual config is NOT expected to be byte-identical
    after a round-trip; the codec only promises canonical-tree
    stability.
    """
    intent1 = codec.parse(raw_text)
    rendered = codec.render(intent1)
    intent2 = codec.parse(rendered)

    # Top-level scalars.
    assert intent1.hostname == intent2.hostname
    assert intent1.domain == intent2.domain
    assert set(intent1.dns_servers) == set(intent2.dns_servers)
    assert set(intent1.ntp_servers) == set(intent2.ntp_servers)

    # VLANs by (id, name).
    assert {(v.id, v.name) for v in intent1.vlans} == {
        (v.id, v.name) for v in intent2.vlans
    }

    # Static routes by (destination, gateway).
    assert {(r.destination, r.gateway) for r in intent1.static_routes} == {
        (r.destination, r.gateway) for r in intent2.static_routes
    }

    # VXLAN VNIs by (vlan_id, vni, source_interface, udp_port).
    def vxlan_key(v):
        return (v.vlan_id, v.vni, v.source_interface, v.udp_port)

    assert {vxlan_key(v) for v in intent1.vxlan_vnis} == {
        vxlan_key(v) for v in intent2.vxlan_vnis
    }

    # Routing instances by full identity (incl. asymmetric RTs).
    def ri_key(ri):
        return (
            ri.name,
            ri.instance_type,
            ri.route_distinguisher,
            tuple(sorted(ri.rt_imports)),
            tuple(sorted(ri.rt_exports)),
            ri.l3_vni,
        )

    assert {ri_key(ri) for ri in intent1.routing_instances} == {
        ri_key(ri) for ri in intent2.routing_instances
    }

    # LAGs by (name, members, mode).
    def lag_key(lag):
        return (lag.name, tuple(sorted(lag.members)), lag.mode)

    assert {lag_key(l) for l in intent1.lags} == {
        lag_key(l) for l in intent2.lags
    }

    # Local users by (name, priv, role, hash).
    def user_key(u):
        return (u.name, u.privilege_level, u.role, u.hashed_password)

    assert {user_key(u) for u in intent1.local_users} == {
        user_key(u) for u in intent2.local_users
    }

    # SNMP — community / location / contact / trap-hosts / v3 users.
    assert intent2.snmp is not None
    assert intent1.snmp.community == intent2.snmp.community
    assert intent1.snmp.location == intent2.snmp.location
    assert intent1.snmp.contact == intent2.snmp.contact
    assert set(intent1.snmp.trap_hosts) == set(intent2.snmp.trap_hosts)

    def v3_key(u):
        return (
            u.name, u.group, u.auth_protocol, u.auth_passphrase,
            u.priv_protocol, u.priv_passphrase,
        )

    assert {v3_key(u) for u in intent1.snmp.v3_users} == {
        v3_key(u) for u in intent2.snmp.v3_users
    }

    # Interfaces — full identity comparison covering every field the
    # arista_eos codec populates.
    def iface_key(i):
        return (
            i.name,
            i.description,
            i.enabled,
            i.mtu,
            i.vrf,
            i.switchport_mode,
            i.access_vlan,
            tuple(sorted(i.trunk_allowed_vlans)),
            i.lag_member_of,
            tuple(sorted((a.ip, a.prefix_length) for a in i.ipv4_addresses)),
            tuple(sorted(
                (a.ip, a.prefix_length, a.scope) for a in i.ipv6_addresses
            )),
        )

    assert {iface_key(i) for i in intent1.interfaces} == {
        iface_key(i) for i in intent2.interfaces
    }
