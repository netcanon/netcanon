"""
Synthetic kitchen-sink coverage test for the opnsense codec.

Pinned to ``tests/fixtures/synthetic/opnsense/kitchen_sink.xml`` — that
fixture is the documented "every canonical field the parser populates"
example for OPNsense's XML wire format.  These tests are the
regression guard: if a future codec change drops a field on parse, or
a render-side regression breaks the round-trip invariant, this module
fails loud.

Three tests, mirroring the cross-vendor convention:

* ``test_parses_without_exceptions`` — OPNsenseCodec().parse() must
  not raise on the kitchen-sink XML.  No empty-intent regression
  (at least one xpath comes out of iter_xpaths).
* ``test_populates_every_expected_canonical_field`` — explicit
  assertion on every CanonicalIntent field the OPNsense parser
  populates today (fixture header docstring documents the list).
* ``test_round_trip_stable`` — parse → render → parse yields a
  CanonicalIntent equal to the first parse for every wired field.
  Within-vendor round-trip is the contract for "lossless on a
  single codec".

The fixture also contains XML for CapabilityMatrix-supported paths
that the parser hasn't wired yet (``<system><dnsserver>``,
``<ntpd>``, ``<system><timezone>``, ``<staticroutes><route>``).  We
don't assert on those here — when parser support lands, those
assertions belong in the wire-up commit, not retroactively in this
file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netconfig.migration.codecs.opnsense import OPNsenseCodec

pytestmark = pytest.mark.unit


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "synthetic" / "opnsense" / "kitchen_sink.xml"
)


@pytest.fixture(scope="module")
def raw_xml() -> str:
    return FIXTURE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1 — parse() must not raise on the kitchen-sink fixture.
# ---------------------------------------------------------------------------


def test_parses_without_exceptions(raw_xml: str) -> None:
    """The kitchen-sink XML must parse cleanly — no ParseError, no
    swallowed-empty-intent regression."""
    codec = OPNsenseCodec()
    intent = codec.parse(raw_xml)

    # Source provenance metadata — set on every successful parse.
    assert intent.source_vendor == "opnsense"
    assert intent.source_format == "xml-opnsense"

    # Empty-intent guard: the kitchen-sink contains real config, so
    # iter_xpaths must yield at least one schema path.
    xpaths = list(codec.iter_xpaths(intent))
    assert xpaths, "kitchen-sink yielded zero xpaths — parser regression"


# ---------------------------------------------------------------------------
# Test 2 — every canonical field the parser populates is present.
# ---------------------------------------------------------------------------


def test_populates_every_expected_canonical_field(raw_xml: str) -> None:
    """Pin the canonical-field coverage of the OPNsense parser.

    Every field below is wired in
    ``netconfig/migration/codecs/opnsense/parse.py``.  When wire-up
    expands (``intent.dns_servers``, ``intent.ntp_servers``,
    ``intent.timezone``, ``intent.syslog_servers``,
    ``intent.static_routes`` are next on deck), add the new
    assertions in the wire-up commit.
    """
    intent = OPNsenseCodec().parse(raw_xml)

    # ── Tier 1 — system identity ──
    assert intent.hostname == "fw-kitchensink"
    assert intent.domain == "example.net"

    # ── Tier 1 — interfaces ──
    # Seven zones (wan, lan, opt1..opt5) backed by the physical names
    # in each zone's <if> child.  Canonical name = <if> text (per
    # opnsense/parse.py::_parse_interface_zone_canonical) so cross-
    # vendor round-trips preserve the original port-name identity
    # through the lossy zone-tag sanitisation in render.
    iface_names = [i.name for i in intent.interfaces]
    assert iface_names == [
        "em0", "em1", "vlan0.20", "vlan0.30", "em2", "em3", "em4",
    ]

    by_name = {i.name: i for i in intent.interfaces}

    # WAN zone (<if>em0</if>) — IPv4 only, MTU set, enabled.
    wan = by_name["em0"]
    assert wan.enabled is True
    assert wan.description == "WAN uplink to upstream carrier"
    assert wan.mtu == 1500
    assert len(wan.ipv4_addresses) == 1
    assert wan.ipv4_addresses[0].ip == "198.51.100.2"
    assert wan.ipv4_addresses[0].prefix_length == 30
    assert wan.ipv6_addresses == []

    # LAN zone (<if>em1</if>) — dual-stack global IPv6.
    lan = by_name["em1"]
    assert lan.enabled is True
    assert lan.ipv4_addresses[0].ip == "192.168.10.1"
    assert lan.ipv4_addresses[0].prefix_length == 24
    assert len(lan.ipv6_addresses) == 1
    assert lan.ipv6_addresses[0].ip == "2001:db8:10::1"
    assert lan.ipv6_addresses[0].prefix_length == 64
    assert lan.ipv6_addresses[0].scope == "global"

    # opt1 zone (<if>vlan0.20</if>) — VLAN child, IPv4 only.
    opt1 = by_name["vlan0.20"]
    assert opt1.description == "Voice VLAN gateway"
    assert opt1.ipv4_addresses[0].ip == "192.168.20.1"

    # opt2 zone (<if>vlan0.30</if>) — link-local IPv6 scope normalisation.
    opt2 = by_name["vlan0.30"]
    assert len(opt2.ipv6_addresses) == 1
    assert opt2.ipv6_addresses[0].ip == "fe80::1"
    assert opt2.ipv6_addresses[0].scope == "link-local"

    # opt5 zone (<if>em4</if>) — disabled (no <enable/> element).
    assert by_name["em4"].enabled is False

    # ── Tier 1 — VLANs (id + name) ──
    vlan_ids = sorted(v.id for v in intent.vlans)
    assert vlan_ids == [10, 20, 30, 100, 200]
    vlan_by_id = {v.id: v for v in intent.vlans}
    assert vlan_by_id[10].name == "USER VLAN"
    assert vlan_by_id[20].name == "VOICE VLAN"
    assert vlan_by_id[200].name == "MGMT VLAN"

    # ── Tier 2 — local users (>= 3) ──
    user_names = [u.name for u in intent.local_users]
    assert user_names == ["root", "netops", "readonly"]
    by_user = {u.name: u for u in intent.local_users}
    # admins group => privilege 15 + role admin
    assert by_user["root"].privilege_level == 15
    assert by_user["root"].role == "admin"
    assert by_user["netops"].privilege_level == 15
    assert by_user["netops"].role == "admin"
    # users group => privilege 1 + role user
    assert by_user["readonly"].privilege_level == 1
    assert by_user["readonly"].role == "user"
    # Hashes are tagged with the bcrypt: prefix per parser convention.
    for user in intent.local_users:
        assert user.hashed_password.startswith("bcrypt:$2b$")

    # ── Tier 2 — RADIUS servers (LDAP authserver must be skipped) ──
    radius_hosts = [s.host for s in intent.radius_servers]
    assert radius_hosts == ["10.0.0.50", "10.0.0.51"]
    primary = intent.radius_servers[0]
    assert primary.auth_port == 1812
    assert primary.acct_port == 1813
    assert primary.key == "fakeRadiusSharedSecret01"
    secondary = intent.radius_servers[1]
    assert secondary.auth_port == 11812
    assert secondary.acct_port == 11813

    # ── Tier 2 — DHCP server pools ──
    assert len(intent.dhcp_servers) == 1
    pool = intent.dhcp_servers[0]
    assert pool.interface == "lan"
    assert pool.start_ip == "192.168.10.100"
    assert pool.end_ip == "192.168.10.199"
    assert pool.gateway == "192.168.10.1"
    assert pool.dns_servers == ["1.1.1.1", "9.9.9.9"]
    assert pool.domain_name == "lan.example.net"
    assert pool.lease_time == 7200

    # ── Tier 2 — LAGs + reverse-link ──
    # LAG <members> carries physical port names (em2, em3) — matches
    # real OPNsense and aligns with the canonical iface name now
    # being sourced from <if> text.
    assert len(intent.lags) == 1
    lag = intent.lags[0]
    assert lag.name == "lagg0"
    assert lag.members == ["em2", "em3"]
    assert lag.mode == "active"  # proto=lacp -> active
    # Reverse-link from interface back to LAG (by canonical name = <if> text).
    assert by_name["em2"].lag_member_of == "lagg0"
    assert by_name["em3"].lag_member_of == "lagg0"
    # Non-members must NOT be back-linked.
    assert by_name["em0"].lag_member_of is None  # wan zone
    assert by_name["vlan0.20"].lag_member_of is None  # opt1 zone

    # ── Tier 2 — SNMP v2c community + sysinfo + traps ──
    assert intent.snmp is not None
    assert intent.snmp.community == "kitchensink-ro"
    assert intent.snmp.location == "Synthetic Lab Rack 7"
    assert intent.snmp.contact == "noc@example.net"
    assert intent.snmp.trap_hosts == ["10.0.0.250", "10.0.0.251"]
    # SNMPv3 is intentionally absent — config.xml doesn't store it.
    assert intent.snmp.v3_users == []


# ---------------------------------------------------------------------------
# Test 3 — within-vendor round-trip stability.
# ---------------------------------------------------------------------------


def test_round_trip_stable(raw_xml: str) -> None:
    """parse → render → parse must reproduce the canonical fields the
    codec wires through.  Within-vendor lossless is the headline
    contract for the OPNsense codec (see codec.py docstring).
    """
    codec = OPNsenseCodec()
    intent_a = codec.parse(raw_xml)
    rendered = codec.render(intent_a)
    intent_b = codec.parse(rendered)

    # Tier 1 scalars
    assert intent_a.hostname == intent_b.hostname
    assert intent_a.domain == intent_b.domain

    # Interfaces — full equality including ipv4/ipv6 addresses, mtu,
    # enabled flag, description, and lag_member_of back-links.
    assert intent_a.interfaces == intent_b.interfaces

    # VLANs (id + name).
    assert intent_a.vlans == intent_b.vlans

    # Tier 2 lists
    assert intent_a.local_users == intent_b.local_users
    assert intent_a.radius_servers == intent_b.radius_servers
    assert intent_a.dhcp_servers == intent_b.dhcp_servers
    assert intent_a.lags == intent_b.lags

    # SNMP block (None vs populated must match exactly).
    assert intent_a.snmp == intent_b.snmp
