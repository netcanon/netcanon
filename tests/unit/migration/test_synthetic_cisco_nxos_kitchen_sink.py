"""
Synthetic kitchen-sink coverage test for the cisco_nxos codec.

Why this module exists
----------------------
Before this file, ``tests/fixtures/synthetic/cisco_nxos/kitchen_sink.cfg`` was
reached only by the shared round-trip sweep, which proves canonical
*stability* — not *correctness*.  A fixture that silently lost a surface would
keep the suite green: the round-trip still passes on a smaller tree, and
``test_cisco_nxos.py``'s content assertions read INLINE sample strings rather
than the committed fixture.

This module asserts the fixture's CONTENT, so shrinkage fails loudly.  It is
the last of the four modules the 2026-09-21 audit found missing (aruba_aoscx
and vyos landed earlier; cisco_iosxr is its sibling).

Every expected value below was taken from a MEASURED parse of the committed
fixture, not from reading the config text and inferring what ought to happen.
That distinction is deliberate: assertions written from the config are a
restatement of the fixture, while assertions written from the parse pin the
codec's actual behaviour — and one of those two catches a parser regression.

Division of labour (deliberate, do not duplicate)
-------------------------------------------------
* ``test_synthetic_kitchen_sink_round_trips.py`` — parametrised over every
  codec: parses-cleanly, determinism, render→parse canonical stability.  The
  shared version compares the full ``model_dump`` and is strictly stronger;
  not re-implemented here.
* ``test_cisco_nxos.py`` — grammar-level behaviour against inline samples,
  plus matrix-declaration honesty.
* **This module** — asserts the committed fixture actually EXERCISES the
  declared surface.

See also:
- docs/vendors/cisco_nxos.md
- tests/fixtures/synthetic/cisco_nxos/kitchen_sink.cfg
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.cisco_nxos import CiscoNXOSCodec

pytestmark = pytest.mark.unit


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "synthetic" / "cisco_nxos" / "kitchen_sink.cfg"
)


@pytest.fixture(scope="module")
def raw_text() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def codec() -> CiscoNXOSCodec:
    return CiscoNXOSCodec()


@pytest.fixture(scope="module")
def tree(codec, raw_text):
    return codec.parse(raw_text)


def test_parses_with_expected_provenance(tree) -> None:
    assert tree.hostname == "nxos-kitchensink"
    assert tree.source_vendor == "cisco_nxos"
    assert tree.source_format == "cli-nxos"
    # `version 9.3(11)` — source_version is captured by every codec and is
    # what the detection probe keys off; a fixture that loses its version
    # banner degrades detection silently.
    assert tree.source_version == "9.3(11)"


def test_no_tier3_sections_are_detected(tree) -> None:
    """The NX-OS fixture is deliberately all Tier-1/2.

    If a Tier-3 stanza is ever added, this assertion should be updated
    rather than deleted — it is what distinguishes "the fixture has no
    Tier-3 content" from "the detector stopped firing".
    """
    assert tree.dropped_tier3_sections == []


# ---------------------------------------------------------------------------
# Interfaces — the broadest surface, and the one most worth pinning
# ---------------------------------------------------------------------------


def test_every_interface_shape_is_present(tree) -> None:
    """Twelve interfaces spanning six distinct shapes.

    The point is breadth: an SVI, a VRF-bound SVI, a LAG, a routed port with
    MTU, a VRF-bound routed port, access + trunk switchports, two LAG
    members, a bare port, a loopback and the management port.  Losing any one
    of these shapes would narrow the fixture without failing a round-trip.
    """
    by_name = {i.name: i for i in tree.interfaces}
    assert sorted(by_name) == [
        "Ethernet1/1", "Ethernet1/2", "Ethernet1/3", "Ethernet1/4",
        "Ethernet1/5", "Ethernet1/6", "Ethernet1/7",
        "Vlan10", "Vlan20", "loopback0", "mgmt0", "port-channel1",
    ]


def test_interface_types_are_inferred_from_name_shape(tree) -> None:
    """NX-OS declares no IANA ifType; the codec infers it (declared lossy)."""
    got = {i.name: i.interface_type for i in tree.interfaces}
    assert got["Vlan10"] == "ianaift:l3ipvlan"
    assert got["port-channel1"] == "ianaift:ieee8023adLag"
    assert got["loopback0"] == "ianaift:softwareLoopback"
    assert got["Ethernet1/1"] == "ianaift:ethernetCsmacd"
    assert got["mgmt0"] == "ianaift:ethernetCsmacd"


def test_routed_port_carries_address_and_mtu(tree) -> None:
    eth1 = next(i for i in tree.interfaces if i.name == "Ethernet1/1")
    assert eth1.description == "routed uplink to spine"
    assert [(a.ip, a.prefix_length) for a in eth1.ipv4_addresses] == [
        ("192.0.2.1", 31)
    ]
    assert eth1.mtu == 9216
    assert eth1.switchport_mode is None, "a routed port must not be L2"


def test_switchport_modes_are_captured(tree) -> None:
    by_name = {i.name: i for i in tree.interfaces}
    assert by_name["Ethernet1/3"].switchport_mode == "access"
    assert by_name["Ethernet1/3"].access_vlan == 10
    assert by_name["Ethernet1/4"].switchport_mode == "trunk"
    assert by_name["port-channel1"].switchport_mode == "trunk"
    assert by_name["port-channel1"].trunk_allowed_vlans == [10, 20]


def test_per_interface_vrf_binding(tree) -> None:
    """``vrf member`` binds the port; it must NOT conjure an instance.

    The per-VRF-harvest rule: a VRF referenced only by an interface is
    recorded on ``iface.vrf`` and does not materialise a phantom
    ``CanonicalRoutingInstance``.  Both VRFs here ARE declared, so the
    negative half of that rule is pinned in ``test_cisco_nxos.py``.
    """
    by_name = {i.name: i for i in tree.interfaces}
    assert by_name["Vlan20"].vrf == "TENANT-A"
    assert by_name["Ethernet1/2"].vrf == "TENANT-A"
    assert by_name["mgmt0"].vrf == "management"
    assert by_name["Ethernet1/1"].vrf == "", "default-VRF port must be blank"


def test_lag_membership_is_recorded_both_ways(tree) -> None:
    """``channel-group`` on the member AND a LAG record with its members."""
    by_name = {i.name: i for i in tree.interfaces}
    assert by_name["Ethernet1/5"].lag_member_of == "port-channel1"
    assert by_name["Ethernet1/6"].lag_member_of == "port-channel1"
    assert by_name["Ethernet1/7"].lag_member_of is None

    assert len(tree.lags) == 1
    lag = tree.lags[0]
    assert lag.name == "port-channel1"
    assert sorted(lag.members) == ["Ethernet1/5", "Ethernet1/6"]
    assert lag.mode == "active", "`channel-group N mode active` is LACP"


# ---------------------------------------------------------------------------
# FHRP — HSRP is NX-OS's only form and folds onto CanonicalVRRPGroup
# ---------------------------------------------------------------------------


def test_hsrp_group_folds_onto_the_vrrp_surface(tree) -> None:
    """NX-OS expresses FHRP as HSRP; the canonical surface is shared.

    ``mode`` is the discriminator that keeps the wire protocol honest — a
    render that ignored it would silently convert HSRP to VRRP.
    """
    vlan10 = next(i for i in tree.interfaces if i.name == "Vlan10")
    assert len(vlan10.vrrp_groups) == 1
    grp = vlan10.vrrp_groups[0]
    assert grp.group_id == 10
    assert grp.mode == "hsrp"
    assert grp.virtual_ips == ["10.10.10.254"]
    assert grp.priority == 110
    assert grp.preempt is True
    assert grp.authentication == "md5:0x1234abcd5678ef90", (
        "the HSRP key-string must survive with its algorithm tag — an "
        "untagged digest is what the #462 class of bug re-emits as cleartext"
    )


def test_anycast_gateway_is_distinct_from_the_fhrp_group(tree) -> None:
    """Two different redundancy paradigms, deliberately modelled apart.

    Vlan10 has an HSRP election; Vlan20 has an anycast gateway (every leaf
    holds the same address, no election).  Conflating them is the mistake the
    canonical model's HYBRID resolution exists to prevent, so the fixture
    carries one of each.
    """
    vlan20 = next(i for i in tree.interfaces if i.name == "Vlan20")
    assert vlan20.vrrp_groups == [], "anycast is not a group election"
    addr = vlan20.ipv4_addresses[0]
    assert addr.ip == "10.20.20.1"
    assert addr.virtual_gateway_address == "10.20.20.1"
    assert tree.anycast_gateway_mac == "00:01:c7:3a:00:00"


# ---------------------------------------------------------------------------
# VLANs, VRFs, routes
# ---------------------------------------------------------------------------


def test_vlans_carry_names_and_projected_membership(tree) -> None:
    by_id = {v.id: v for v in tree.vlans}
    assert sorted(by_id) == [1, 10, 20, 30]
    assert by_id[10].name == "PROD"
    assert by_id[20].name == "VOICE"
    assert by_id[30].name == "MGMT-VLAN"
    # switchport -> VLAN projection: the access port lands untagged, the
    # trunk ports tagged.
    assert by_id[10].untagged_ports == ["Ethernet1/3"]
    assert sorted(by_id[10].tagged_ports) == ["Ethernet1/4", "port-channel1"]
    assert sorted(by_id[20].tagged_ports) == ["Ethernet1/4", "port-channel1"]


def test_routing_instances_carry_rd_rt_and_l3vni(tree) -> None:
    by_name = {r.name: r for r in tree.routing_instances}
    assert sorted(by_name) == ["TENANT-A", "management"]
    tenant = by_name["TENANT-A"]
    assert tenant.route_distinguisher == "65001:100"
    assert tenant.rt_imports == ["65001:100"]
    assert tenant.rt_exports == ["65001:100"]
    assert tenant.l3_vni == 50001, "symmetric-IRB L3VNI must survive"


def test_static_routes_include_a_per_vrf_route(tree) -> None:
    got = {
        (r.destination, r.vrf) for r in tree.static_routes
    }
    assert ("0.0.0.0/0", "") in got, "default route in the global table"
    assert ("10.100.0.0/16", "") in got
    assert ("10.50.0.0/16", "TENANT-A") in got, (
        "a VRF-scoped static route is a distinct surface from a global one"
    )
    assert len(tree.static_routes) == 3


def test_vxlan_l2_bindings_are_captured(tree) -> None:
    """``interface nve1`` + ``member vni`` + ``vlan N / vn-segment``.

    ⚠️ ``nve1`` must NOT appear as a CanonicalInterface — it is a container
    the codec intercepts, and letting it through was a real defect.
    """
    assert "nve1" not in {i.name for i in tree.interfaces}
    got = {(v.vni, v.vlan_id, v.source_interface) for v in tree.vxlan_vnis}
    assert got == {
        (10010, 10, "loopback0"),
        (10020, 20, "loopback0"),
    }


# ---------------------------------------------------------------------------
# Credentials — the surface with the most hard rules attached
# ---------------------------------------------------------------------------


def test_local_users_keep_role_and_hash_with_its_type_marker(tree) -> None:
    """Two users at different privilege levels, each with a role.

    The hash keeps its Cisco type marker (``5 $5$…``).  That prefix is
    load-bearing: the portability classifier reads the algorithm from the
    payload, and a bare digest with no recognisable shape is what the #460
    fail-open bug re-emitted under a cleartext marker.
    """
    by_name = {u.name: u for u in tree.local_users}
    assert sorted(by_name) == ["admin", "netops"]
    assert by_name["admin"].privilege_level == 15
    assert by_name["netops"].privilege_level == 1
    assert by_name["admin"].role == "network-admin"
    assert by_name["netops"].role == "network-operator"
    for user in tree.local_users:
        assert user.hashed_password.startswith("5 $5$"), (
            f"{user.name}: hash lost its type marker -> "
            f"{user.hashed_password[:12]!r}"
        )
    # ``CanonicalLocalUser`` has no cleartext field at all — only
    # ``hashed_password`` — so there is no slot a digest could be
    # re-emitted through as a literal password.  Pinned so nobody adds one.
    assert set(tree.local_users[0].__class__.model_fields) == {
        "name", "hashed_password", "privilege_level", "role",
    }


def test_snmp_v2c_and_v3_are_both_exercised(tree) -> None:
    snmp = tree.snmp
    assert snmp is not None
    assert snmp.community == "public-ro"
    assert snmp.location == "DataCenter-1-RackB"
    assert snmp.contact == "netops@example.net"
    assert snmp.trap_hosts == ["192.0.2.50"]

    assert len(snmp.v3_users) == 1
    user = snmp.v3_users[0]
    assert user.name == "admin"
    assert user.auth_protocol == "sha"
    assert user.priv_protocol == "aes128", (
        "NX-OS writes `aes-128`; canonical normalises to `aes128`"
    )


def test_the_fixture_still_covers_what_this_module_claims(tree) -> None:
    """Guard the guard — a breadth floor.

    Every assertion above is specific, so a fixture that GREW would still
    pass while quietly becoming the only codec whose kitchen sink is thin.
    These floors are the cheap check that the fixture is still a kitchen
    sink rather than a sample.
    """
    assert len(tree.interfaces) >= 12
    assert len(tree.vlans) >= 4
    assert len(tree.routing_instances) >= 2
    assert len(tree.static_routes) >= 3
    assert len(tree.local_users) >= 2
    assert len(tree.vxlan_vnis) >= 2
    assert tree.snmp is not None and tree.snmp.v3_users
    assert any(i.vrrp_groups for i in tree.interfaces)
    assert any(i.lag_member_of for i in tree.interfaces)
    assert any(i.mtu for i in tree.interfaces)
