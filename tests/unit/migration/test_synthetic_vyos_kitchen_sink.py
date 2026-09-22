"""
Synthetic kitchen-sink coverage test for the vyos codec.

Why this module exists
----------------------
``tests/unit/migration/test_vyos.py`` is large (69 tests) but almost
every content assertion runs against INLINE sample strings.  The
committed fixture ``tests/fixtures/synthetic/vyos/kitchen_sink.conf``
was reached by exactly one test — ``test_round_trip_kitchen_sink`` —
which proves canonical *stability*, not *correctness*.

So if the committed fixture lost a surface, the whole suite would stay
green: the round-trip still passes on a smaller fixture, and every
content assertion is reading the inline sample instead.  This module
asserts the fixture's CONTENT so that shrinkage fails loudly.

⭐ It matters more here than for most codecs.  This fixture is in
**curly-brace `config.boot` form**, and it is the only in-tree config
exercising that grammar against the full canonical surface — the real
VyOS capture the 2026-06-17 VM lab pulled was ``set``-form, and
``WANTED.md`` still lists a permissive curly-brace real capture as an
open ask.  Nothing else would notice if curly-brace coverage regressed.

Division of labour (deliberate, do not duplicate)
-------------------------------------------------
* ``test_synthetic_kitchen_sink_round_trips.py`` — parametrised over
  every codec: parses-cleanly, parse-is-deterministic, render→parse
  canonical stability.  Not re-implemented here; the shared version
  compares the full ``model_dump`` and is strictly stronger.
* ``test_vyos.py::test_matrix_supported`` / ``…_lossy`` — assert the
  matrix DECLARATIONS are honest, not that the fixture exercises them.
* **This module** — asserts the fixture actually EXERCISES them.

See also:
- docs/vendors/vyos.md
- tests/fixtures/synthetic/vyos/kitchen_sink.conf
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.vyos import VyOSCodec

pytestmark = pytest.mark.unit


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "synthetic" / "vyos" / "kitchen_sink.conf"
)


@pytest.fixture(scope="module")
def raw_text() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def codec() -> VyOSCodec:
    return VyOSCodec()


# ---------------------------------------------------------------------------
# Test 1 — sanity parse + provenance
# ---------------------------------------------------------------------------


def test_parses_with_expected_provenance(codec, raw_text):
    """Parses, and reads the version from the RELEASE comment.

    ``source_version`` must be ``1.4`` (from ``// Release version:``),
    NOT the ``vyos-config-version`` schema string on the line above it —
    those are different numbers and confusing them misreports the OS.
    """
    intent = codec.parse(raw_text)
    assert intent is not None
    assert intent.source_vendor == "vyos"
    assert intent.source_format == "cli-vyos"
    assert intent.source_version == "1.4"


# ---------------------------------------------------------------------------
# Test 2 — exhaustive canonical-field coverage
# ---------------------------------------------------------------------------


def test_populates_every_expected_canonical_field(codec, raw_text):
    """One assertion per canonical surface the matrix declares."""
    intent = codec.parse(raw_text)

    # /system/hostname
    assert intent.hostname == "vyos-kitchen-sink"

    # /system/ntp-server
    assert intent.ntp_servers == ["0.pool.ntp.org", "1.pool.ntp.org"]

    # /interfaces/interface — 11 across ethernet / vif / loopback /
    # dummy / bonding + members.
    assert len(intent.interfaces) == 11
    by_name = {i.name: i for i in intent.interfaces}

    # Ethernet with description + mtu + ipv4 + vrf binding.
    eth0 = by_name["eth0"]
    assert eth0.description == "uplink to core"
    assert eth0.mtu == 1500
    assert eth0.vrf == "BLUE"
    assert [(a.ip, a.prefix_length) for a in eth0.ipv4_addresses] == [
        ("198.51.100.1", 31),
    ]

    # /interfaces/interface/dot1q-vlan — `vif` becomes its own interface.
    assert by_name["eth1.100"].dot1q_vlan == 100
    assert by_name["eth1.100"].description == "tenant vlan 100"
    assert by_name["eth1.200"].dot1q_vlan == 200

    # /interfaces/interface/dhcp-client — `address dhcp` is a flag, not
    # an address.
    eth2 = by_name["eth2"]
    assert eth2.dhcp_client is True
    assert eth2.ipv4_addresses == []

    # `disable` → admin-down (False, not None).
    assert by_name["eth3"].enabled is False
    assert by_name["eth1.200"].enabled is False

    # Loopback dual-stack, IPv6 /128 at global scope.
    lo = by_name["lo"]
    assert [(a.ip, a.prefix_length) for a in lo.ipv4_addresses] == [
        ("10.255.0.1", 32),
    ]
    assert [(a.ip, a.prefix_length, a.scope) for a in lo.ipv6_addresses] == [
        ("2001:db8::1", 128, "global"),
    ]

    # Dummy interface is a first-class port.
    assert [(a.ip, a.prefix_length) for a in by_name["dum0"].ipv4_addresses] == [
        ("10.255.1.1", 32),
    ]

    # /interfaces/interface/lag-member-of — back-pointers on members.
    assert by_name["eth4"].lag_member_of == "bond0"
    assert by_name["eth5"].lag_member_of == "bond0"
    assert by_name["bond0"].description == "server lag"

    # /lags/lag — members + mode from `mode 802.3ad`.
    assert len(intent.lags) == 1
    bond = intent.lags[0]
    assert bond.name == "bond0"
    assert sorted(bond.members) == ["eth4", "eth5"]
    assert bond.mode == "active"

    # /routing/static-route — v4 default, a distance-bearing v4 route,
    # and a `route6` IPv6 route.
    assert len(intent.static_routes) == 3
    routes = {r.destination: r for r in intent.static_routes}
    assert routes["0.0.0.0/0"].gateway == "198.51.100.0"
    assert routes["10.99.0.0/16"].gateway == "10.10.10.254"
    assert routes["10.99.0.0/16"].metric == 20
    assert routes["2001:db8:ffff::/48"].gateway == "2001:db8::2"

    # /routing-instances/instance/name
    assert [ri.name for ri in intent.routing_instances] == ["BLUE"]
    assert intent.routing_instances[0].instance_type == "vrf"

    # /local-users/user — name + role + hashed-password + privilege.
    assert len(intent.local_users) == 2
    user_by_name = {u.name: u for u in intent.local_users}
    assert user_by_name["vyos"].hashed_password == "$6$FAKEKITCHENSINKHASHvyos"
    assert user_by_name["vyos"].role == "admin"
    assert user_by_name["vyos"].privilege_level == 15
    assert user_by_name["netops"].hashed_password == "$6$FAKEKITCHENSINKHASHnetops"

    # /snmp/community + location + contact.
    assert intent.snmp is not None
    assert intent.snmp.community == "FAKEPUBLIC"
    assert intent.snmp.location == "rack 4 / row B"
    assert intent.snmp.contact == "netops@example.com"

    # /snmp/v3-user — group + auth + priv + engine-id.
    assert len(intent.snmp.v3_users) == 1
    v3 = intent.snmp.v3_users[0]
    assert v3.name == "snmpv3admin"
    assert v3.group == "operators"
    assert v3.auth_protocol == "sha"
    assert v3.priv_protocol == "aes"
    assert v3.auth_passphrase == "$6$FAKEsnmpAUTHsha"
    assert v3.priv_passphrase == "$6$FAKEsnmpPRIVaes"
    assert v3.engine_id == "0xFEEDFACE00"

    # /vxlan-vnis — vni + flood-list + source-interface + udp-port.
    assert len(intent.vxlan_vnis) == 1
    vx = intent.vxlan_vnis[0]
    assert vx.vni == 10100
    assert vx.flood_list == ["198.51.100.9"]
    assert vx.source_interface == "10.255.0.1"
    assert vx.udp_port == 4789


# ---------------------------------------------------------------------------
# VyOS-specific trap guards
# ---------------------------------------------------------------------------


def test_vxlan_stanza_does_not_become_an_interface(codec, raw_text):
    """``vxlan vxlan0`` lives under ``interfaces`` but is an overlay.

    Materialising it as a port would invent an interface the device
    does not present as one, and would double-count the VNI.
    """
    intent = codec.parse(raw_text)
    assert not any(i.name.startswith("vxlan") for i in intent.interfaces)
    assert len(intent.vxlan_vnis) == 1


def test_vxlan_vlan_id_is_synthesised_not_configured(codec, raw_text):
    """VyOS binds a VNI to no VLAN, so ``vlan_id`` is SYNTHESISED.

    The canonical model keys VNIs by VLAN, so the codec must invent a
    stable id rather than drop the record or emit a real-looking VLAN.
    Pinned because a change here silently rewrites cross-vendor output.
    """
    intent = codec.parse(raw_text)
    assert intent.vxlan_vnis[0].vlan_id == 1912
    # The synthesised id must NOT appear as a real VLAN record.
    assert [v.id for v in intent.vlans if v.id == 1912] == []


def test_vif_is_its_own_interface_not_an_attribute_of_the_parent(codec, raw_text):
    """``vif 100 { }`` nested inside ``ethernet eth1`` becomes
    ``eth1.100``, a sibling interface.

    Folding it into the parent would lose the sub-interface's own
    address and admin state — ``eth1.200`` is ``disable``d while its
    parent ``eth1`` is up, which only survives as separate records.
    """
    by_name = {i.name: i for i in codec.parse(raw_text).interfaces}
    assert "eth1" in by_name and "eth1.100" in by_name and "eth1.200" in by_name
    assert by_name["eth1"].enabled is True
    assert by_name["eth1.200"].enabled is False
    assert by_name["eth1"].dot1q_vlan is None


def test_interface_vrf_binding_does_not_conjure_an_instance(codec, raw_text):
    """``vrf "BLUE"`` on eth0 must not create a second BLUE instance.

    The VRF is declared once under the top-level ``vrf { name BLUE }``
    stanza; the interface only REFERENCES it.  A parser that created an
    instance per reference would emit duplicates on render.
    """
    intent = codec.parse(raw_text)
    assert len(intent.routing_instances) == 1
    assert intent.routing_instances[0].name == "BLUE"


def test_usm_keys_are_marked_localised(codec, raw_text):
    """``encrypted-password`` under ``auth``/``privacy`` is a key that
    is already localised to this agent's engine ID.

    It must never be re-emitted to another device as if it were a
    portable passphrase — the #463 defect.  ``auth_kind`` /
    ``priv_kind`` carry that provenance per value.
    """
    v3 = codec.parse(raw_text).snmp.v3_users[0]
    assert v3.auth_kind == "localised"
    assert v3.priv_kind == "localised"
