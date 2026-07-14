"""cisco_iosxe_cli VXLAN-EVPN ``nve1`` harvest + render — promotion #16.

Parse now intercepts ``interface nve1`` (mirrors cisco_nxos — the VTEP is
an overlay container, not a routed/switched port) and correlates the
``vlan configuration N / member [evpn-instance M] vni V`` bindings into
``CanonicalVxlan`` records; render re-emits both.  The L3VNI (``member vni
V vrf <name>``) lands on the matching ``CanonicalRoutingInstance.l3_vni``.

Matrix: /vxlan-vnis/{vni,source-interface,mcast-group} +
/routing-instances/instance/l3-vni are supported; /vxlan-vnis/udp-port +
/vxlan-vnis/flood-list are lossy (the NVE render keeps the VNI identity but
drops those sub-details).
"""
from __future__ import annotations

import pathlib

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalRoutingInstance,
    CanonicalVxlan,
)
from netcanon.migration.codecs.cisco_iosxe_cli.codec import CiscoIOSXECLICodec

pytestmark = pytest.mark.unit

_FIXTURE = (
    pathlib.Path(__file__).parents[2]
    / "fixtures" / "real" / "cisco_iosxe"
    / "ciscolive_brkops1104_evpn_leaf_iosxe1715.txt"
)


def _codec() -> CiscoIOSXECLICodec:
    return CiscoIOSXECLICodec()


# ---------------------------------------------------------------------------
# Real EVPN-leaf fixture
# ---------------------------------------------------------------------------


def test_real_fixture_harvests_l2_vni_and_intercepts_nve():
    intent = _codec().parse(_FIXTURE.read_text(encoding="utf-8"))

    # nve1 is intercepted — no generic CanonicalInterface materialises.
    assert not any(i.name.lower().startswith("nve") for i in intent.interfaces)

    # The one L2 VNI (VLAN 100 -> VNI 100100, multicast flood-and-learn).
    assert len(intent.vxlan_vnis) == 1
    vx = intent.vxlan_vnis[0]
    assert vx.vlan_id == 100
    assert vx.vni == 100100
    assert vx.mcast_group == "239.0.0.100"
    assert vx.source_interface == "Loopback2"

    # The L3VNI (member vni 100200 vrf cml_demo) rides the routing instance.
    by_vrf = {ri.name: ri for ri in intent.routing_instances}
    assert by_vrf["cml_demo"].l3_vni == 100200
    assert by_vrf["management"].l3_vni is None


def test_real_fixture_round_trip_stable():
    """parse -> render -> parse preserves the overlay (same-vendor lossless
    on the wired surface).  The interception drops the iface count
    identically on both parses, so the canonical tree is stable."""
    codec = _codec()
    a = codec.parse(_FIXTURE.read_text(encoding="utf-8"))
    b = codec.parse(codec.render(a))

    assert [(v.vlan_id, v.vni, v.mcast_group, v.source_interface)
            for v in a.vxlan_vnis] == \
           [(v.vlan_id, v.vni, v.mcast_group, v.source_interface)
            for v in b.vxlan_vnis]
    assert {ri.name: ri.l3_vni for ri in a.routing_instances} == \
           {ri.name: ri.l3_vni for ri in b.routing_instances}
    assert len(a.interfaces) == len(b.interfaces)


def test_nve_member_vni_tolerates_ingress_replication_tail():
    # HEAD-review L1-5: ``member vni <V> ingress-replication`` (the explicit
    # BGP-EVPN head-end spelling) under ``interface nve1``.  The ``$``-anchored
    # regex previously rejected the whole line, so the VLAN<->VNI binding
    # silently vanished (vxlan_vnis == []).  The tail is tolerated (not
    # modelled) and the binding survives on this supported path.
    raw = (
        "hostname leaf1\n"
        "vlan configuration 100\n"
        " member evpn-instance 1 vni 10100\n"
        "interface nve1\n"
        " no ip address\n"
        " source-interface Loopback0\n"
        " host-reachability protocol bgp\n"
        " member vni 10100 ingress-replication\n"
    )
    intent = _codec().parse(raw)
    assert [(v.vlan_id, v.vni, v.mcast_group) for v in intent.vxlan_vnis] == \
           [(100, 10100, "")]


# ---------------------------------------------------------------------------
# Synthetic round-trips (canonical -> render -> parse)
# ---------------------------------------------------------------------------


def _rt(intent: CanonicalIntent) -> CanonicalIntent:
    codec = _codec()
    return codec.parse(codec.render(intent))


def test_l2_vni_multicast_round_trips():
    src = CanonicalIntent(
        hostname="leaf1",
        vxlan_vnis=[CanonicalVxlan(
            vlan_id=10, vni=10010, mcast_group="239.1.1.1",
            source_interface="Loopback0")],
    )
    rp = _rt(src)
    assert len(rp.vxlan_vnis) == 1
    vx = rp.vxlan_vnis[0]
    assert (vx.vlan_id, vx.vni, vx.mcast_group, vx.source_interface) == \
           (10, 10010, "239.1.1.1", "Loopback0")


def test_l2_vni_headend_bare_round_trips_vni_without_mcast():
    """A head-end (BGP-EVPN) L2 VNI with no multicast group re-parses with an
    empty mcast_group — the VNI identity survives, mcast simply isn't set."""
    src = CanonicalIntent(
        hostname="leaf1",
        vxlan_vnis=[CanonicalVxlan(
            vlan_id=20, vni=10020, source_interface="Loopback0")],
    )
    rp = _rt(src)
    assert len(rp.vxlan_vnis) == 1
    assert rp.vxlan_vnis[0].vni == 10020
    assert rp.vxlan_vnis[0].mcast_group == ""


def test_l3vni_round_trips_onto_routing_instance():
    src = CanonicalIntent(
        hostname="border1",
        routing_instances=[CanonicalRoutingInstance(
            name="TENANT_A", route_distinguisher="65000:1", l3_vni=50010)],
        vxlan_vnis=[CanonicalVxlan(
            vlan_id=30, vni=10030, source_interface="Loopback0")],
    )
    rp = _rt(src)
    by_vrf = {ri.name: ri for ri in rp.routing_instances}
    assert by_vrf["TENANT_A"].l3_vni == 50010


def test_multiple_l2_vnis_round_trip():
    src = CanonicalIntent(
        hostname="leaf2",
        vxlan_vnis=[
            CanonicalVxlan(vlan_id=10, vni=10010, mcast_group="239.1.1.1",
                           source_interface="Loopback0"),
            CanonicalVxlan(vlan_id=20, vni=10020,
                           source_interface="Loopback0"),
        ],
    )
    rp = _rt(src)
    got = sorted((v.vlan_id, v.vni, v.mcast_group) for v in rp.vxlan_vnis)
    assert got == [(10, 10010, "239.1.1.1"), (20, 10020, "")]


def test_flood_list_drops_but_vni_survives():
    """Head-end static ingress-replication peers (flood_list) have no IOS-XE
    nve1 grammar — declared lossy.  The VNI identity survives; the peers drop."""
    src = CanonicalIntent(
        hostname="leaf3",
        vxlan_vnis=[CanonicalVxlan(
            vlan_id=40, vni=10040, flood_list=["10.0.0.5", "10.0.0.6"],
            source_interface="Loopback0")],
    )
    rp = _rt(src)
    assert len(rp.vxlan_vnis) == 1
    assert rp.vxlan_vnis[0].vni == 10040
    assert rp.vxlan_vnis[0].flood_list == []


# ---------------------------------------------------------------------------
# Negative control — no overlay
# ---------------------------------------------------------------------------


def test_no_nve_config_yields_empty_vxlan():
    raw = (
        "hostname plain\n"
        "!\n"
        "interface GigabitEthernet0/1\n"
        " ip address 10.0.0.1 255.255.255.0\n"
        "!\n"
        "vlan 10\n"
        " name USERS\n"
        "!\n"
    )
    intent = _codec().parse(raw)
    assert intent.vxlan_vnis == []
    assert all(ri.l3_vni is None for ri in intent.routing_instances)


def test_matrix_dispositions():
    caps = _codec().capabilities
    assert caps.classify("/vxlan-vnis/vni") == "supported"
    assert caps.classify("/vxlan-vnis/source-interface") == "supported"
    assert caps.classify("/vxlan-vnis/mcast-group") == "supported"
    assert caps.classify("/routing-instances/instance/l3-vni") == "supported"
    assert caps.classify("/vxlan-vnis/udp-port") == "lossy"
    assert caps.classify("/vxlan-vnis/flood-list") == "lossy"
