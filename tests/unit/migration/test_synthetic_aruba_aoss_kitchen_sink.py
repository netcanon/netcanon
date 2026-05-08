"""
Synthetic kitchen-sink coverage for the ``ArubaAOSSCodec``.

Real-capture fixtures have feature gaps — the synthetic kitchen-sink
fills them so the cross-vendor mesh matrix can exercise every
canonical feature the aruba_aoss codec marks supported / lossy in
its :class:`CapabilityMatrix`, not just whatever happens to appear
in the third-party real captures.

The companion fixture lives at
``tests/fixtures/synthetic/aruba_aoss/kitchen_sink.cfg``.

Three checkpoints:

* :class:`TestParsesWithoutExceptions` — clean parse end-to-end.
* :class:`TestPopulatesEveryExpectedCanonicalField` — per-canonical-
  field assertions; one method per top-level CanonicalIntent
  attribute the codec is expected to populate.
* :class:`TestRoundTripStable` — ``parse(render(parse(raw)))`` ==
  ``parse(raw)`` (the canonical lossless-within-vendor invariant).

See also: ``tests/unit/migration/test_aruba_aoss.py`` for the
codec's structural / regression tests against shipped real captures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.aruba_aoss import ArubaAOSSCodec

pytestmark = pytest.mark.unit


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "synthetic"
    / "aruba_aoss"
    / "kitchen_sink.cfg"
)


@pytest.fixture(scope="module")
def raw() -> str:
    return FIXTURE.read_text()


@pytest.fixture(scope="module")
def tree(raw: str):
    return ArubaAOSSCodec().parse(raw)


# ---------------------------------------------------------------------------
# 1. Clean parse
# ---------------------------------------------------------------------------


class TestParsesWithoutExceptions:
    """The synthetic must parse cleanly under the codec's normal contract."""

    def test_parses_without_exceptions(self, raw: str) -> None:
        ArubaAOSSCodec().parse(raw)

    def test_source_metadata_set(self, tree) -> None:
        assert tree.source_vendor == "aruba_aoss"
        assert tree.source_format == "cli-aruba-aoss"


# ---------------------------------------------------------------------------
# 2. Every expected canonical field is populated
# ---------------------------------------------------------------------------


class TestPopulatesEveryExpectedCanonicalField:
    """One assertion per supported canonical field.

    The list of fields here mirrors the aruba_aoss codec's
    ``CapabilityMatrix.supported`` xpaths plus the Tier 2 sections
    the parser explicitly populates (RADIUS, local users, LAGs).
    Anything the codec marks unsupported (VXLAN, EVPN, routing-
    instances, syslog, timezone, MTU) is intentionally NOT asserted
    on so this test stays a coverage *floor*, not a cross-codec
    feature creep magnet.
    """

    # ── Tier 1 — auto-translatable ──

    def test_hostname(self, tree) -> None:
        assert tree.hostname == "ks-aoss-edge-01"

    def test_dns_servers(self, tree) -> None:
        # ≥1; synthetic ships 2 with explicit priorities.
        assert tree.dns_servers == ["10.0.10.53", "10.0.10.54"]

    def test_ntp_servers(self, tree) -> None:
        # AOS-S uses ``sntp`` keyword; canonical ntp_servers list.
        assert tree.ntp_servers == ["10.0.10.123", "10.0.10.124"]

    def test_vlans_count_and_names(self, tree) -> None:
        ids = [v.id for v in tree.vlans]
        assert ids == [1, 10, 20, 30, 40]
        names = {v.id: v.name for v in tree.vlans}
        assert names[1] == "DEFAULT_VLAN"
        assert names[10] == "USERS"
        assert names[20] == "VOICE"
        assert names[30] == "MGMT"
        assert names[40] == "GUESTS"

    def test_vlan_tagged_and_untagged_membership(self, tree) -> None:
        users = next(v for v in tree.vlans if v.id == 10)
        # Untagged 1-12 expanded.
        assert users.untagged_ports == [str(n) for n in range(1, 13)]
        # Tagged uplink range 23-24.
        assert users.tagged_ports == ["23", "24"]
        # Trunk-only VLAN — no untagged.
        mgmt = next(v for v in tree.vlans if v.id == 30)
        assert mgmt.untagged_ports == []
        assert mgmt.tagged_ports == ["23", "24"]

    def test_vlan_svi_ipv4(self, tree) -> None:
        users = next(v for v in tree.vlans if v.id == 10)
        assert len(users.ipv4_addresses) == 1
        assert users.ipv4_addresses[0].ip == "10.10.10.1"
        assert users.ipv4_addresses[0].prefix_length == 24

    def test_vlan_svi_dotted_decimal_mask_normalised(self, tree) -> None:
        # vlan 10 used the dotted-decimal form ``255.255.255.0`` —
        # canonical normalises to /24 prefix.
        users = next(v for v in tree.vlans if v.id == 10)
        assert users.ipv4_addresses[0].prefix_length == 24

    def test_svi_absorbed_into_vlan_iface(self, tree) -> None:
        # AOS-S absorbs the SVI L3 into the vlan stanza — the codec
        # promotes it to a Vlan<N> CanonicalInterface for cross-
        # vendor consumers.
        names = {i.name for i in tree.interfaces}
        for vlan_id in (10, 20, 30, 40):
            assert f"Vlan{vlan_id}" in names

    def test_interfaces_minimum_count(self, tree) -> None:
        # ≥6 covering the requested categories.  Vlan<N> SVIs +
        # access ports + routed uplinks + LAG iface stanzas.
        assert len(tree.interfaces) >= 6

    def test_interface_access_with_description(self, tree) -> None:
        access = next(i for i in tree.interfaces if i.name == "1")
        assert access.description == "user-desk-01"
        assert access.enabled is True

    def test_interface_disabled_state(self, tree) -> None:
        # Port 21 is in the disabled state.
        disabled = next(i for i in tree.interfaces if i.name == "21")
        assert disabled.enabled is False

    def test_routed_port_ipv4(self, tree) -> None:
        a1 = next(i for i in tree.interfaces if i.name == "A1")
        assert len(a1.ipv4_addresses) == 1
        assert a1.ipv4_addresses[0].ip == "10.0.0.2"
        assert a1.ipv4_addresses[0].prefix_length == 30

    def test_routed_port_ipv6_global(self, tree) -> None:
        a1 = next(i for i in tree.interfaces if i.name == "A1")
        globals_ = [
            a for a in a1.ipv6_addresses if a.scope == "global"
        ]
        assert len(globals_) == 1
        assert globals_[0].ip == "2001:db8:0:a::2"
        assert globals_[0].prefix_length == 64

    def test_routed_port_ipv6_link_local(self, tree) -> None:
        a1 = next(i for i in tree.interfaces if i.name == "A1")
        ll = [a for a in a1.ipv6_addresses if a.scope == "link-local"]
        assert len(ll) == 1
        assert ll[0].ip == "fe80::a:2"
        assert ll[0].prefix_length == 64

    def test_lag_iface_stanzas_present(self, tree) -> None:
        # The Trk1/Trk2 interface stanzas surface as canonical
        # interfaces (separate from the LAG record below).
        names = {i.name for i in tree.interfaces}
        assert "Trk1" in names
        assert "Trk2" in names

    def test_static_routes_default_gateway(self, tree) -> None:
        defaults = [
            r for r in tree.static_routes
            if r.destination == "0.0.0.0/0"
        ]
        assert len(defaults) == 1
        assert defaults[0].gateway == "10.0.0.1"

    def test_static_routes_explicit_cidr_and_mask(self, tree) -> None:
        # Two ``ip route`` lines — one CIDR form, one dotted-mask.
        cidr = [
            r for r in tree.static_routes
            if r.destination == "192.168.99.0/24"
        ]
        mask = [
            r for r in tree.static_routes
            if r.destination == "172.16.0.0/16"
        ]
        assert len(cidr) == 1
        assert cidr[0].gateway == "10.0.0.254"
        assert len(mask) == 1
        assert mask[0].gateway == "10.0.0.254"

    # ── Tier 2 — auto-translate w/ review banner ──

    def test_snmp_community(self, tree) -> None:
        assert tree.snmp is not None
        assert tree.snmp.community == "public"

    def test_snmp_location(self, tree) -> None:
        assert tree.snmp.location == "Synthetic-Lab Rack 7"

    def test_snmp_contact(self, tree) -> None:
        assert tree.snmp.contact == "netops@example.invalid"

    def test_snmp_trap_hosts(self, tree) -> None:
        assert tree.snmp.trap_hosts == ["10.0.10.200", "10.0.10.201"]

    def test_snmpv3_users_count(self, tree) -> None:
        # ≥2 distinct USM identities.
        assert len(tree.snmp.v3_users) >= 2

    def test_snmpv3_user_auth_priv(self, tree) -> None:
        # The SHA + AES user.
        m = next(u for u in tree.snmp.v3_users if u.name == "monitor-usr")
        assert m.group == "auth-priv-grp"
        assert m.auth_protocol == "sha"
        assert m.priv_protocol == "aes128"  # canonical normalises bare 'aes'

    def test_snmpv3_user_md5_des(self, tree) -> None:
        # The MD5 + DES user — exercises the legacy auth/priv combo.
        a = next(u for u in tree.snmp.v3_users if u.name == "audit-usr")
        assert a.group == "auth-priv-grp"
        assert a.auth_protocol == "md5"
        assert a.priv_protocol == "des"

    def test_snmpv3_passphrases_preserved(self, tree) -> None:
        # Opaque pass-through (never plaintext on real configs;
        # synthetic uses fake-but-real-shaped tokens).
        m = next(u for u in tree.snmp.v3_users if u.name == "monitor-usr")
        assert m.auth_passphrase
        assert m.priv_passphrase

    def test_radius_servers(self, tree) -> None:
        assert len(tree.radius_servers) == 2
        hosts = {r.host for r in tree.radius_servers}
        assert hosts == {"10.0.20.10", "10.0.20.11"}
        keys = {r.key for r in tree.radius_servers}
        assert keys == {"fakeRadiusSecret-A", "fakeRadiusSecret-B"}

    def test_radius_default_ports(self, tree) -> None:
        # AOS-S parser doesn't extract per-server port overrides
        # (and the synthetic doesn't include any), so canonical
        # carries the IANA defaults.
        for r in tree.radius_servers:
            assert r.auth_port == 1812
            assert r.acct_port == 1813

    def test_local_users_count_and_roles(self, tree) -> None:
        # ≥3 distinct accounts spanning manager + operator roles.
        assert len(tree.local_users) >= 3
        roles = {u.role for u in tree.local_users}
        assert "manager" in roles
        assert "operator" in roles

    def test_local_users_sha1_form(self, tree) -> None:
        admin = next(u for u in tree.local_users if u.name == "admin")
        assert admin.role == "manager"
        assert admin.privilege_level == 15
        assert admin.hashed_password.startswith("sha1:")
        # Hash is opaque pass-through; just sanity-check we kept
        # the digest material.
        assert len(admin.hashed_password) > len("sha1:")

    def test_local_users_plaintext_form(self, tree) -> None:
        siteops = next(
            u for u in tree.local_users if u.name == "siteops"
        )
        assert siteops.role == "manager"
        assert siteops.hashed_password.startswith("plaintext:")

    def test_local_users_operator_role_priv1(self, tree) -> None:
        monitor = next(
            u for u in tree.local_users if u.name == "monitor"
        )
        assert monitor.role == "operator"
        assert monitor.privilege_level == 1

    def test_lags(self, tree) -> None:
        # ≥2 LAGs declared via ``trunk`` lines.
        assert len(tree.lags) == 2
        names = {l.name for l in tree.lags}
        # AOS-S trunk names are normalised lower-case (``trk<N>``)
        # by the codec's _build_lag_from_trunk_line → _lag_name_to_aos_trunk
        # round-trip pair.
        assert names == {"trk1", "trk2"}

    def test_lag_modes_lacp_and_static(self, tree) -> None:
        # ``lacp`` AOS-S type maps to canonical ``active``;
        # ``trunk`` maps to ``static``.
        modes = {l.name: l.mode for l in tree.lags}
        assert modes["trk1"] == "active"
        assert modes["trk2"] == "static"

    def test_lag_members(self, tree) -> None:
        trk1 = next(l for l in tree.lags if l.name == "trk1")
        assert trk1.members == ["23", "24"]

    def test_lag_member_back_link(self, tree) -> None:
        # The post-pass linkage walks ``trunk`` members back to
        # their ``interface <N>`` stanzas and stamps the LAG name.
        m23 = next(i for i in tree.interfaces if i.name == "23")
        assert m23.lag_member_of == "trk1"


# ---------------------------------------------------------------------------
# 3. Round-trip stability
# ---------------------------------------------------------------------------


class TestRoundTripStable:
    """``parse(render(parse(raw))) == parse(raw)``.

    This is the canonical lossless-within-vendor invariant — the
    contract every codec maintains for its supported feature subset.
    Cross-vendor migration is allowed to be lossy; same-vendor
    round-trip is not.
    """

    def test_round_trip_stable(self, raw: str) -> None:
        codec = ArubaAOSSCodec()
        first = codec.parse(raw)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        assert first == second, (
            "kitchen-sink fixture lost canonical state through "
            "render → parse — a feature is silently asymmetric"
        )

    def test_render_is_deterministic(self, raw: str) -> None:
        # Two render calls must produce byte-identical output —
        # render must not depend on dict ordering or randomness.
        codec = ArubaAOSSCodec()
        tree = codec.parse(raw)
        a = codec.render(tree)
        b = codec.render(tree)
        assert a == b
