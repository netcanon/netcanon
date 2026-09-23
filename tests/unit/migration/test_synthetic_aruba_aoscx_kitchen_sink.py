"""
Synthetic kitchen-sink coverage test for the aruba_aoscx codec.

Why this module exists
----------------------
``tests/unit/migration/test_aruba_aoscx.py`` is thorough (43 tests) but
almost all of it runs against an INLINE ``_SAMPLE`` string.  The
committed fixture
``tests/fixtures/synthetic/aruba_aoscx/kitchen_sink.cfg`` was reached by
exactly one test — ``test_round_trip_kitchen_sink`` — which proves
canonical *stability*, not *correctness*.

That combination leaves a real hole: if the committed fixture lost a
surface, every existing test would stay green.  The round-trip would
still pass (a fixture with less in it still round-trips), and every
content assertion would pass because it reads the inline sample
instead.  Nothing would notice the corpus had shrunk.

This module closes that by asserting the fixture's CONTENT, one
assertion per canonical surface the ``CapabilityMatrix`` declares
``supported`` or ``lossy``.

Division of labour (deliberate, do not duplicate)
-------------------------------------------------
* ``test_synthetic_kitchen_sink_round_trips.py`` — parametrised over
  every codec: parses-cleanly, parse-is-deterministic, and
  render→parse canonical stability (with a field-targeted
  ``_KNOWN_ROUNDTRIP_GAPS`` rot-detector).  Those drift guards are NOT
  re-implemented here; the shared version compares the full
  ``model_dump`` and is strictly stronger than any hand-picked tuple.
* ``test_aruba_aoscx.py::test_matrix_supported`` / ``…_lossy`` — assert
  the matrix DECLARATIONS are honest (``classify()`` returns the right
  verdict).  They do not assert the fixture exercises those paths.
* **This module** — asserts the fixture actually EXERCISES them.

When extending the fixture, add the matching assertion below so the
coverage stays explicit.

See also:
- docs/vendors/aruba_aoscx.md
- tests/fixtures/synthetic/aruba_aoscx/kitchen_sink.cfg
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.aruba_aoscx import ArubaAOSCXCodec

pytestmark = pytest.mark.unit


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "synthetic" / "aruba_aoscx" / "kitchen_sink.cfg"
)


@pytest.fixture(scope="module")
def raw_text() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def codec() -> ArubaAOSCXCodec:
    return ArubaAOSCXCodec()


# ---------------------------------------------------------------------------
# Test 1 — sanity parse + provenance
# ---------------------------------------------------------------------------


def test_parses_with_expected_provenance(codec, raw_text):
    """Parses, and stamps the provenance the cross-vendor mesh keys on.

    ``source_version`` comes from the ``!Version ArubaOS-CX`` banner —
    a same-vendor render echoes it back, so losing it silently changes
    rendered output.
    """
    intent = codec.parse(raw_text)
    assert intent is not None
    assert intent.source_vendor == "aruba_aoscx"
    assert intent.source_format == "cli-aoscx"
    assert intent.source_version == "FL.10.13.1000"


# ---------------------------------------------------------------------------
# Test 2 — exhaustive canonical-field coverage
# ---------------------------------------------------------------------------


def test_populates_every_expected_canonical_field(codec, raw_text):
    """One assertion per canonical surface the matrix declares.

    A failure here means either the codec regressed or the fixture lost
    coverage — both are real defects.
    """
    intent = codec.parse(raw_text)

    # /system/hostname
    assert intent.hostname == "aoscx-kitchen-sink"

    # /anycast-gateway-mac — chassis-wide, from `active-gateway ip mac`.
    assert intent.anycast_gateway_mac == "02:00:0a:14:14:01"

    # /interfaces/interface — 13 covering every shape AOS-CX models.
    assert len(intent.interfaces) == 13
    by_name = {i.name: i for i in intent.interfaces}

    # Routed physical: description + enabled + mtu + ipv4.
    p1 = by_name["1/1/1"]
    assert p1.description == "Uplink to spine"
    assert p1.enabled is True
    assert p1.mtu == 9198
    assert [(a.ip, a.prefix_length) for a in p1.ipv4_addresses] == [
        ("198.51.100.1", 31),
    ]

    # /interfaces/interface/switchport-mode + access-vlan.
    assert by_name["1/1/2"].switchport_mode == "access"
    assert by_name["1/1/2"].access_vlan == 10

    # `shutdown` → admin-down (enabled is False, not None).
    assert by_name["1/1/3"].enabled is False
    assert by_name["1/1/3"].description == "Reserved port"

    # /interfaces/interface/trunk-allowed-vlans + trunk-native-vlan.
    # `vlan trunk allowed 10,20-30` expands the range.
    p4 = by_name["1/1/4"]
    assert p4.switchport_mode == "trunk"
    assert p4.trunk_allowed_vlans == [10, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30]
    assert p4.trunk_native_vlan == 1

    # /interfaces/interface/lag-member-of — back-pointer on the member.
    assert by_name["1/1/5"].lag_member_of == "lag 1"
    assert by_name["1/1/6"].lag_member_of == "lag 1"

    # /interfaces/interface/config/type — IANA inference (lossy).
    assert p1.interface_type == "ianaift:ethernetCsmacd"
    assert by_name["lag 1"].interface_type == "ianaift:ieee8023adLag"
    assert by_name["vlan 10"].interface_type == "ianaift:l3ipvlan"
    assert by_name["loopback 0"].interface_type == "ianaift:softwareLoopback"

    # /interfaces/interface/config/vrf — `vrf attach RED` on an SVI.
    assert by_name["vlan 10"].vrf == "RED"
    assert [(a.ip, a.prefix_length) for a in by_name["vlan 10"].ipv4_addresses] == [
        ("10.10.10.1", 24),
    ]

    # SVI with active-gateway + dual-stack.
    v20 = by_name["vlan 20"]
    assert v20.ipv4_addresses[0].virtual_gateway_address == "10.20.20.254"
    assert [(a.ip, a.prefix_length, a.scope) for a in v20.ipv6_addresses] == [
        ("2001:db8:20::1", 64, "global"),
    ]

    # Loopbacks — two, one carrying a description.
    assert [(a.ip, a.prefix_length) for a in by_name["loopback 0"].ipv4_addresses] == [
        ("10.255.0.1", 32),
    ]
    assert by_name["loopback 1"].description == "Router-ID"

    # Management port is present and named bare `mgmt`.
    assert by_name["mgmt"].enabled is True

    # /lags/lag/name + members + mode.
    assert len(intent.lags) == 2
    lag_by_name = {lag.name: lag for lag in intent.lags}
    assert sorted(lag_by_name["lag 1"].members) == ["1/1/5", "1/1/6"]
    assert lag_by_name["lag 1"].mode == "active"          # `lacp mode active`
    # lag 2 has no `lacp mode` line → static, and no members.
    assert lag_by_name["lag 2"].mode == "static"
    assert lag_by_name["lag 2"].members == []

    # /vlans/vlan — id + name + description + tagged/untagged ports.
    #
    # 4 are declared by a `vlan <N>` stanza (1, 10, 20, 30); the other 9
    # (21-29) are carried only by 1/1/4's twelve-entry
    # `vlan trunk allowed 10,20-30` list.  A twelve-entry list is a
    # specific operator declaration, so those VIDs survive the
    # phantom prune — see
    # ``canonical.transforms.switchport_declared_vlan_ids``.
    assert len(intent.vlans) == 13
    vlan_by_id = {v.id: v for v in intent.vlans}
    assert sorted(vlan_by_id) == [1, 10, 20, 21, 22, 23, 24, 25, 26, 27,
                                  28, 29, 30]
    assert vlan_by_id[10].name == "USERS"
    assert vlan_by_id[10].description == "User access VLAN"
    assert vlan_by_id[10].tagged_ports == ["1/1/4"]
    assert vlan_by_id[10].untagged_ports == ["1/1/2"]
    assert vlan_by_id[20].name == "VOICE"
    assert vlan_by_id[20].untagged_ports == ["lag 2"]
    assert vlan_by_id[30].name == "MGMT-NET"
    assert vlan_by_id[30].description == "Out-of-band management"
    # VLAN 1 is synthesised from the native-vlan references only.
    assert sorted(vlan_by_id[1].untagged_ports) == ["1/1/4", "lag 1"]

    # /vlans/vlan/ipv4/address/ip (lossy) — SVI address projected onto
    # the VLAN record, carrying the active-gateway with it.
    assert vlan_by_id[20].ipv4_addresses[0].ip == "10.20.20.1"
    assert vlan_by_id[20].ipv4_addresses[0].virtual_gateway_address == "10.20.20.254"

    # /routing/static-route — default + a metric-bearing route.
    assert len(intent.static_routes) == 2
    routes = {r.destination: r for r in intent.static_routes}
    assert routes["0.0.0.0/0"].gateway == "198.51.100.2"
    assert routes["10.99.0.0/16"].gateway == "203.0.113.254"
    assert routes["10.99.0.0/16"].metric == 200

    # /routing-instances/instance/name — two bare VRFs.
    assert {ri.name for ri in intent.routing_instances} == {"RED", "BLUE"}
    assert all(ri.instance_type == "vrf" for ri in intent.routing_instances)

    # /local-users/user — name + role + hashed-password + privilege.
    assert len(intent.local_users) == 2
    user_by_name = {u.name: u for u in intent.local_users}
    assert user_by_name["admin"].role == "administrators"
    assert user_by_name["admin"].privilege_level == 15
    assert user_by_name["admin"].hashed_password == "AQBFAKECIPHERTEXTBLOBADMIN"
    assert user_by_name["netops"].role == "operators"
    assert user_by_name["netops"].privilege_level == 1

    # /snmp/community + location + contact.
    assert intent.snmp is not None
    assert intent.snmp.community == "FAKECOMMUNITY"
    assert intent.snmp.location == "Data Center 1"
    assert intent.snmp.contact == "noc@example.net"

    # /snmp/v3-user — one USM user with auth + priv, both ciphertext.
    assert len(intent.snmp.v3_users) == 1
    v3 = intent.snmp.v3_users[0]
    assert v3.name == "monitor"
    assert v3.auth_protocol == "sha"
    assert v3.priv_protocol == "aes"
    assert v3.auth_passphrase == "FAKEAUTHBLOB"
    assert v3.priv_passphrase == "FAKEPRIVBLOB"

    # /vxlan-vnis/vni + source-interface + udp-port.
    assert len(intent.vxlan_vnis) == 2
    vni_map = {v.vlan_id: v.vni for v in intent.vxlan_vnis}
    assert vni_map == {10: 10010, 20: 10020}
    for v in intent.vxlan_vnis:
        assert v.source_interface == "10.255.0.1"
        assert v.udp_port == 4789


# ---------------------------------------------------------------------------
# AOS-CX-specific trap guards
# ---------------------------------------------------------------------------


def test_usm_key_provenance_is_ciphertext_not_passphrase(codec, raw_text):
    """``password ciphertext`` marks a DEVICE-ENCRYPTED blob.

    Misreading it as a portable passphrase would let the value be
    re-emitted on another switch, where it decrypts to nothing — the
    #466 defect.  ``auth_kind`` / ``priv_kind`` carry that provenance
    per value and must say ``ciphertext``.
    """
    v3 = codec.parse(raw_text).snmp.v3_users[0]
    assert v3.auth_kind == "ciphertext"
    assert v3.priv_kind == "ciphertext"


def test_trunk_allowed_all_is_an_empty_list_not_every_vlan(codec, raw_text):
    """``vlan trunk allowed all`` means "whatever exists", not 1-4094.

    Expanding it to an explicit list would pin today's VLAN set into
    the canonical tree and silently change meaning on the target.
    """
    by_name = {i.name: i for i in codec.parse(raw_text).interfaces}
    assert by_name["lag 1"].switchport_mode == "trunk"
    assert by_name["lag 1"].trunk_allowed_vlans == []


def test_multi_chassis_modifier_is_stripped_from_the_lag_name(codec, raw_text):
    """``interface lag 1 multi-chassis`` names the LAG ``lag 1``.

    Keeping the modifier would create a phantom interface that matches
    no member's ``lag 1`` back-pointer, splitting the LAG in two.
    """
    names = {i.name for i in codec.parse(raw_text).interfaces}
    assert "lag 1" in names
    assert "lag 1 multi-chassis" not in names


def test_vxlan_stanza_does_not_become_an_interface(codec, raw_text):
    """``interface vxlan 1`` is an overlay container, not a port.

    It must populate ``vxlan_vnis`` only — materialising it as an
    interface would invent a port that does not exist on the device.
    """
    intent = codec.parse(raw_text)
    assert not any(i.name.startswith("vxlan") for i in intent.interfaces)
    assert len(intent.vxlan_vnis) == 2


def test_no_routing_marks_l2_which_is_the_inverse_of_nxos(codec, raw_text):
    """AOS-CX ports are L3 by default; ``no routing`` makes them L2.

    That is the INVERSE of NX-OS (``no switchport`` makes a port L3), so
    a parser that copied the Cisco polarity would invert every port's
    L2/L3 role on this fixture.
    """
    by_name = {i.name: i for i in codec.parse(raw_text).interfaces}
    # `no routing` present → switched.
    assert by_name["1/1/2"].switchport_mode == "access"
    # No `no routing` → routed, so it carries an IP and no switchport mode.
    assert by_name["1/1/1"].switchport_mode is None
    assert by_name["1/1/1"].ipv4_addresses
