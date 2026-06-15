"""
Coverage guard for the shared canonical walker (``_walk_canonical``).

The interactive validation report (``validate_against``) is only as
honest as the walker is complete: a populated ``CanonicalIntent`` field
the walker never yields an xpath for can never be classified
lossy / unsupported, so its loss is invisible in the report.  The
2026-06 architecture review flagged that the walker covered only a
narrow slice of Tier 2 — LAGs, local users, RADIUS, DHCP, VXLAN/EVPN
and VRFs were silently dropped.

This module is the inverse of the per-codec render-honesty guard in
``tests/unit/migration/codecs/cisco_iosxe/test_capability_matrix_honesty.py``:
it asserts that for a kitchen-sink intent populating EVERY top-level
field (plus the per-interface sub-fields the review called out), the
walker emits at least one xpath per surface.  A new
``CanonicalIntent`` field that lands without a matching walker yield
trips :func:`test_every_top_level_field_is_walked`.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalEvpnType5Route,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalRoutingInstance,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVxlan,
)
from netcanon.migration.codecs.cisco_iosxe_cli.codec import _walk_canonical

pytestmark = pytest.mark.unit


def _kitchen_sink() -> CanonicalIntent:
    """A CanonicalIntent with every translatable surface populated."""
    return CanonicalIntent(
        # ── Tier 1 scalars / lists ──
        hostname="walk-guard",
        domain="example.test",
        dns_servers=["10.0.0.53"],
        ntp_servers=["10.0.0.123"],
        timezone="UTC",
        syslog_servers=["10.0.0.514"],
        interfaces=[
            CanonicalInterface(
                name="GigabitEthernet1/0/1",
                description="walked",
                enabled=True,
                interface_type="ianaift:ethernetCsmacd",
                mtu=9000,
                vrf="TENANT-A",
                lag_member_of="Port-Channel1",
                switchport_mode="trunk",
                access_vlan=10,
                trunk_allowed_vlans=[10, 20],
                trunk_native_vlan=99,
                voice_vlan=200,
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="198.51.100.1",
                        prefix_length=30,
                        virtual_gateway_address="198.51.100.254",
                    ),
                ],
                ipv6_addresses=[
                    CanonicalIPv6Address(ip="2001:db8::1", prefix_length=64),
                ],
                dhcp_client_v6="dhcp6",
                tunnel_type="gre",
            ),
        ],
        vlans=[CanonicalVlan(id=10, name="USERS")],
        static_routes=[
            CanonicalStaticRoute(
                destination="0.0.0.0/0", gateway="198.51.100.2", vrf="TENANT-A"
            ),
        ],
        # ── Tier 2 ──
        dhcp_servers=[
            CanonicalDHCPPool(network="192.0.2.0/24", start_ip="192.0.2.10"),
        ],
        snmp=CanonicalSNMP(
            community="ro",
            location="lab",
            contact="ops@example.test",
            trap_hosts=["10.0.0.10"],
            v3_users=[
                CanonicalSNMPv3User(
                    name="v3guard",
                    group="g",
                    auth_protocol="sha",
                    auth_passphrase="$9$auth",
                    priv_protocol="aes",
                    priv_passphrase="$9$priv",
                    engine_id="80000009feedface",
                ),
            ],
        ),
        lags=[
            CanonicalLAG(
                name="Port-Channel1",
                members=["GigabitEthernet1/0/1"],
                mode="active",
            ),
        ],
        local_users=[
            CanonicalLocalUser(
                name="admin",
                privilege_level=15,
                hashed_password="$9$hash",
                role="admin",
            ),
        ],
        radius_servers=[CanonicalRADIUSServer(host="10.0.0.1", key="$9$radius")],
        vxlan_vnis=[
            CanonicalVxlan(
                vlan_id=10,
                vni=10010,
                mcast_group="239.1.1.1",
                flood_list=["10.0.0.5"],
                source_interface="Loopback0",
            ),
        ],
        evpn_type5_routes=[
            CanonicalEvpnType5Route(vrf="TENANT-A", prefix="10.10.0.0/16"),
        ],
        routing_instances=[
            CanonicalRoutingInstance(
                name="TENANT-A",
                instance_type="vrf",
                route_distinguisher="65000:100",
                rt_imports=["65000:100"],
                rt_exports=["65000:100"],
                description="tenant a",
                l3_vni=50010,
            ),
        ],
        anycast_gateway_mac="00:1c:73:00:dc:01",
    )


#: Each populated top-level CanonicalIntent surface → an xpath (exact or
#: prefix) the walker MUST emit when that surface carries data.  This is
#: the honesty floor: the live validator cannot flag a surface the
#: walker never yields.
_FIELD_TO_EXPECTED_XPATH: dict[str, str] = {
    "hostname": "/system/hostname",
    "domain": "/system/domain",
    "dns_servers": "/system/dns-server",
    "ntp_servers": "/system/ntp-server",
    "timezone": "/system/timezone",
    "syslog_servers": "/system/syslog-server",
    "interfaces": "/interfaces/interface/name",
    "vlans": "/vlans/vlan/id",
    "static_routes": "/routing/static-route",
    "dhcp_servers": "/dhcp-servers/pool",
    "snmp": "/snmp/community",
    "lags": "/lags/lag/name",
    "local_users": "/local-users/user/name",
    "radius_servers": "/radius-servers/server/host",
    "vxlan_vnis": "/vxlan-vnis/vni",
    "evpn_type5_routes": "/evpn-type5-routes/route",
    "routing_instances": "/routing-instances/instance",
    "anycast_gateway_mac": "/anycast-gateway-mac",
}


def test_every_top_level_field_is_walked():
    """Every populated top-level surface yields at least one xpath."""
    intent = _kitchen_sink()
    emitted = set(_walk_canonical(intent))

    # Sanity: the kitchen-sink really does populate every audited field
    # (so a missing-yield failure below means the WALKER is incomplete,
    # not that the fixture forgot to set something).
    dump = intent.model_dump()
    for field in _FIELD_TO_EXPECTED_XPATH:
        value = dump.get(field)
        assert value not in (None, "", [], {}), (
            f"kitchen-sink fixture left intent.{field} empty — fix the "
            f"fixture, not the walker"
        )

    for field, xpath in _FIELD_TO_EXPECTED_XPATH.items():
        assert xpath in emitted, (
            f"_walk_canonical does not yield {xpath!r} for populated "
            f"intent.{field}: the live validation report is structurally "
            f"blind to this surface.  Add a yield in _walk_canonical."
        )


def test_per_interface_subfields_are_walked():
    """The per-interface Tier-2 sub-fields are walked — mtu / vrf /
    lag-member-of / dhcp-client plus the switchport view (using the
    no-``config/`` spelling that matches the nxos / aoscx matrix
    declarations).  Switchport coverage landed with the registry
    honesty guard (review #9)."""
    emitted = set(_walk_canonical(_kitchen_sink()))
    for xpath in (
        "/interfaces/interface/config/mtu",
        "/interfaces/interface/config/vrf",
        "/interfaces/interface/lag-member-of",
        "/interfaces/interface/switchport-mode",
        "/interfaces/interface/access-vlan",
        "/interfaces/interface/trunk-allowed-vlans",
        "/interfaces/interface/trunk-native-vlan",
    ):
        assert xpath in emitted, f"_walk_canonical drops {xpath!r}"


def test_snmp_v3_subfields_are_walked():
    """SNMPv3 auth/engine sub-fields (declared lossy by several codecs)
    must be walked so the report surfaces the key-portability caveat."""
    emitted = set(_walk_canonical(_kitchen_sink()))
    assert "/snmp/v3-user/auth-passphrase" in emitted
    assert "/snmp/v3-user/engine-id" in emitted


def test_empty_intent_yields_nothing():
    """An empty intent has no populated surface, so the walker yields
    nothing — there is no loss to report."""
    assert list(_walk_canonical(CanonicalIntent())) == []


def test_unpopulated_surfaces_are_not_walked():
    """A surface that carries no data must not yield an xpath — else the
    report would flag a non-existent loss.  Populate ONLY hostname and
    assert no Tier-2 family xpath leaks."""
    intent = CanonicalIntent(hostname="only-host")
    emitted = set(_walk_canonical(intent))
    assert emitted == {"/system/hostname"}
