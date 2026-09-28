"""
Synthetic kitchen-sink coverage test for the cisco_iosxr codec.

Why this module exists
----------------------
Before this file, ``tests/fixtures/synthetic/cisco_iosxr/kitchen_sink.cfg`` was
reached only by the shared round-trip sweep, which proves canonical
*stability* — not *correctness*.  A fixture that silently lost a surface would
keep the suite green: the round-trip still passes on a smaller tree, and
``test_cisco_iosxr.py``'s content assertions read INLINE sample strings.

This module asserts the fixture's CONTENT so shrinkage fails loudly.  It
completes the set the 2026-09-21 audit found missing (aruba_aoscx and vyos
landed earlier; cisco_nxos is its sibling).

Every expected value below was taken from a MEASURED parse of the committed
fixture, not inferred from reading the config text — assertions derived from
the config merely restate the fixture, while assertions derived from the parse
pin the codec's behaviour.

⭐ Why IOS-XR is worth its own module.  Two of its grammar traits are unique
in-tree and nothing else would notice if they regressed:

* **Four-segment port names** (``GigabitEthernet0/0/0/0``,
  ``MgmtEth0/RP0/CPU0/0``) — every other codec's ports are two or three
  segments, so the port-name classifier's XR branch is exercised here alone.
* **RD harvested from ``router bgp``**, not from the VRF stanza.  XR declares
  ``vrf X`` with no RD inside it; the RD lives under
  ``router bgp / vrf X / rd``.  That indirection is the trap the codec track
  rediscovered, and this fixture is where it stays proven.

Division of labour (deliberate, do not duplicate)
-------------------------------------------------
* ``test_synthetic_kitchen_sink_round_trips.py`` — parametrised over every
  codec: parses-cleanly, determinism, render→parse canonical stability.  The
  shared version compares the full ``model_dump`` and is strictly stronger.
* ``test_cisco_iosxr.py`` — grammar behaviour against inline samples, plus
  matrix-declaration honesty.
* **This module** — asserts the committed fixture actually EXERCISES it.

See also:
- docs/vendors/cisco_iosxr.md
- tests/fixtures/synthetic/cisco_iosxr/kitchen_sink.cfg
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.cisco_iosxr import CiscoIOSXRCodec

pytestmark = pytest.mark.unit


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "synthetic" / "cisco_iosxr" / "kitchen_sink.cfg"
)


@pytest.fixture(scope="module")
def raw_text() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def codec() -> CiscoIOSXRCodec:
    return CiscoIOSXRCodec()


@pytest.fixture(scope="module")
def tree(codec, raw_text):
    return codec.parse(raw_text)


def test_parses_with_expected_provenance(tree) -> None:
    assert tree.hostname == "xr-kitchensink"
    assert tree.source_vendor == "cisco_iosxr"
    assert tree.source_format == "cli-iosxr"
    assert tree.source_version == "6.6.2"
    assert tree.domain == "lab.example.net"


def test_bgp_is_surfaced_as_a_tier3_drop(tree) -> None:
    """XR's reason for existing is SP routing, and netcanon translates the
    L2/L3 layer only.

    ``router bgp`` must appear in the banner rather than vanish — for an XR
    config that stanza is usually the bulk of the file, so a missing banner
    line here is the difference between an honest translation and a
    misleading one.
    """
    assert tree.dropped_tier3_sections == ["router bgp 65001"]


# ---------------------------------------------------------------------------
# Interfaces — four-segment naming is the XR-specific surface
# ---------------------------------------------------------------------------


def test_every_interface_shape_is_present(tree) -> None:
    by_name = {i.name: i for i in tree.interfaces}
    assert sorted(by_name) == [
        "Bundle-Ether1",
        "GigabitEthernet0/0/0/0",
        "GigabitEthernet0/0/0/1",
        "GigabitEthernet0/0/0/1.100",
        "GigabitEthernet0/0/0/3",
        "GigabitEthernet0/0/0/4",
        "Loopback0",
        "MgmtEth0/RP0/CPU0/0",
        "TenGigE0/0/0/2",
    ]


def test_four_segment_port_names_survive_verbatim(tree) -> None:
    """The XR-unique shape.  ``MgmtEth0/RP0/CPU0/0`` is the extreme case —
    a slot path with non-numeric segments (``RP0``, ``CPU0``)."""
    names = {i.name for i in tree.interfaces}
    assert "GigabitEthernet0/0/0/0" in names
    assert "MgmtEth0/RP0/CPU0/0" in names
    assert "TenGigE0/0/0/2" in names, "the 10G name form must also be present"


def test_dot1q_subinterface_is_its_own_interface(tree) -> None:
    """A routed subinterface is a distinct interface carrying its own tag.

    Its VLAN tag lands on ``dot1q_vlan`` (GAP 7), NOT on the parent, and the
    subinterface inherits the parent's VRF.
    """
    by_name = {i.name: i for i in tree.interfaces}
    sub = by_name["GigabitEthernet0/0/0/1.100"]
    assert sub.dot1q_vlan == 100
    assert [(a.ip, a.prefix_length) for a in sub.ipv4_addresses] == [
        ("203.0.113.129", 25)
    ]
    assert sub.vrf == "CUSTOMER-A"
    parent = by_name["GigabitEthernet0/0/0/1"]
    assert parent.dot1q_vlan is None, "the tag must not leak onto the parent"


def test_dot1q_tag_synthesises_a_vlan_record(tree) -> None:
    """The only VLAN in the tree comes from the subinterface's tag.

    XR has no VLAN database; VID 100 exists solely because a subinterface is
    tagged with it, so it carries no name.
    """
    assert [(v.id, v.name) for v in tree.vlans] == [(100, "")]


def test_dual_stack_and_mtu_on_the_core_uplink(tree) -> None:
    core = next(
        i for i in tree.interfaces if i.name == "GigabitEthernet0/0/0/0"
    )
    assert core.description == "core uplink to P1"
    assert [(a.ip, a.prefix_length) for a in core.ipv4_addresses] == [
        ("198.51.100.1", 30)
    ]
    assert [a.ip for a in core.ipv6_addresses] == ["2001:db8:ff::1"], (
        "IPv6 is a distinct surface; only this port exercises it"
    )
    assert core.mtu == 9192


def test_shutdown_interface_is_recorded_as_disabled(tree) -> None:
    """``shutdown`` is the one attribute whose ABSENCE means enabled, so a
    parser that ignored it would read as a clean config."""
    ten = next(i for i in tree.interfaces if i.name == "TenGigE0/0/0/2")
    assert ten.enabled is False
    assert all(
        i.enabled
        for i in tree.interfaces
        if i.name != "TenGigE0/0/0/2"
    ), "only the shut port may be disabled"


def test_bundle_membership_is_recorded_both_ways(tree) -> None:
    """XR's LAG is ``Bundle-Ether``, joined via ``bundle id N mode active``."""
    by_name = {i.name: i for i in tree.interfaces}
    assert by_name["GigabitEthernet0/0/0/3"].lag_member_of == "Bundle-Ether1"
    assert by_name["GigabitEthernet0/0/0/4"].lag_member_of == "Bundle-Ether1"

    assert len(tree.lags) == 1
    lag = tree.lags[0]
    assert lag.name == "Bundle-Ether1"
    assert sorted(lag.members) == [
        "GigabitEthernet0/0/0/3",
        "GigabitEthernet0/0/0/4",
    ]
    assert lag.mode == "active"
    # The bundle itself is L3 — a LAG carrying an address, not a switchport.
    assert [(a.ip, a.prefix_length)
            for a in by_name["Bundle-Ether1"].ipv4_addresses] == [
        ("10.0.0.1", 31)
    ]


def test_per_interface_vrf_binding(tree) -> None:
    by_name = {i.name: i for i in tree.interfaces}
    assert by_name["GigabitEthernet0/0/0/1"].vrf == "CUSTOMER-A"
    assert by_name["MgmtEth0/RP0/CPU0/0"].vrf == "MGMT"
    assert by_name["GigabitEthernet0/0/0/0"].vrf == ""


# ---------------------------------------------------------------------------
# VRFs — the RD-from-`router bgp` indirection
# ---------------------------------------------------------------------------


def test_rd_and_rts_are_harvested_from_router_bgp(tree) -> None:
    """⭐ The XR trap.

    ``vrf CUSTOMER-A`` declares no RD.  The RD lives under
    ``router bgp 65001 / vrf CUSTOMER-A / rd 65001:100`` — a different stanza
    entirely — and the route-targets under the VRF's address-family block.
    A parser that only read the ``vrf`` stanza would produce instances with
    empty RDs and never fail a round-trip.

    Note this is harvested from the SAME ``router bgp`` stanza that is
    reported as a Tier-3 drop: the banner says BGP is not translated, and
    that remains true — only the VRF's RD/RT leaves are lifted out of it.
    """
    by_name = {r.name: r for r in tree.routing_instances}
    assert sorted(by_name) == ["CUSTOMER-A", "MGMT"]
    cust = by_name["CUSTOMER-A"]
    assert cust.route_distinguisher == "65001:100"
    assert cust.rt_imports == ["65001:100"]
    assert cust.rt_exports == ["65001:100"]
    mgmt = by_name["MGMT"]
    assert mgmt.route_distinguisher == "65001:999"
    assert mgmt.rt_imports == ["65001:999"]


# ---------------------------------------------------------------------------
# Routes — three distinct next-hop shapes
# ---------------------------------------------------------------------------


def test_static_routes_cover_three_next_hop_shapes(tree) -> None:
    """A gateway, a gateway-plus-egress-interface, and a discard route.

    ``192.0.2.0/24 Null0`` has NO gateway — a null-route is expressed by
    egress interface alone.  A parser requiring a gateway would drop it.
    """
    got = {
        (r.destination, r.gateway, r.interface, r.vrf)
        for r in tree.static_routes
    }
    assert ("0.0.0.0/0", "198.51.100.2", "", "") in got
    assert (
        "10.50.0.0/16", "203.0.113.2", "GigabitEthernet0/0/0/1", "",
    ) in got
    assert ("192.0.2.0/24", "", "Null0", "") in got, (
        "a discard route has an egress interface and no gateway"
    )
    assert ("10.99.0.0/16", "203.0.113.2", "", "CUSTOMER-A") in got, (
        "a VRF-scoped static route is a distinct surface"
    )
    assert len(tree.static_routes) == 4


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def test_local_users_keep_role_and_hash_with_its_type_marker(tree) -> None:
    """XR writes ``secret 10 $6$…`` — type 10 is SHA-512.

    The ``10 `` marker is load-bearing: the portability classifier reads the
    algorithm from the payload's crypt(3) id, and an untagged digest is what
    the #460 fail-open bug re-emitted under a cleartext marker.
    """
    by_name = {u.name: u for u in tree.local_users}
    assert sorted(by_name) == ["netops", "readonly"]
    assert by_name["netops"].privilege_level == 15
    assert by_name["netops"].role == "root-lr"
    assert by_name["readonly"].privilege_level == 1
    assert by_name["readonly"].role == "operator"
    for user in tree.local_users:
        assert user.hashed_password.startswith("10 $6$"), (
            f"{user.name}: hash lost its type marker -> "
            f"{user.hashed_password[:12]!r}"
        )


def test_snmp_is_absent_and_that_is_deliberate(tree) -> None:
    """Pinned as a NEGATIVE so it reads as a known gap, not an oversight.

    This fixture carries no SNMP stanza.  If SNMP coverage is ever added to
    the fixture, update this assertion — do not delete it, or the next reader
    cannot tell whether absence was intended.
    """
    assert tree.snmp is None or not tree.snmp.community


def test_the_fixture_still_covers_what_this_module_claims(tree) -> None:
    """Guard the guard — a breadth floor, so a shrunken fixture that happens
    to satisfy the specific assertions above still fails."""
    assert len(tree.interfaces) >= 9
    assert len(tree.routing_instances) >= 2
    assert len(tree.static_routes) >= 4
    assert len(tree.local_users) >= 2
    assert len(tree.lags) >= 1
    assert any(i.dot1q_vlan for i in tree.interfaces)
    assert any(i.ipv6_addresses for i in tree.interfaces)
    assert any(not i.enabled for i in tree.interfaces)
    assert any(i.mtu for i in tree.interfaces)
    assert any("/RP0/CPU0/" in i.name for i in tree.interfaces)
