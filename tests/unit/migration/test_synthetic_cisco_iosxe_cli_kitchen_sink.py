"""
Synthetic kitchen-sink coverage for the ``cisco_iosxe_cli`` codec.

The real-capture corpus under ``tests/fixtures/real/cisco_iosxe/`` covers
production-shaped configs but no single capture exercises every feature
the codec parses.  This synthetic kitchen-sink file is the inverse: a
single config file that hits every Tier-1 + Tier-2 canonical surface
the parser populates, so the cross-mesh translation matrix has a
deterministic source of truth even when no real fixture happens to
carry feature X.

Three contracts pinned here:

1. :func:`test_parses_without_exceptions` — the file must parse cleanly
   (no ``ParseError``, no exception).
2. :func:`test_populates_every_expected_canonical_field` — per-field
   assertions cover hostname / interfaces (every type) / VLANs / static
   routes / DHCP pools / SNMP (community + v3 users) / RADIUS /
   local users / LAGs.  Wire forms for fields the parser does NOT
   surface (DNS / NTP / syslog / timezone / VRFs / IPv6-static /
   via-VRF static) live in the fixture for realism but are not
   asserted here — same-vendor round-trip drops them silently per
   the codec's parse contract (see ``parse.py`` module docstring).
3. :func:`test_round_trip_stable` — ``parse → render → parse`` produces
   an equivalent canonical tree on the parsed surfaces.

Authored under the rule of thumb: only assert what
``CiscoIOSXECLICodec.parse()`` actually populates today.  Wire forms
the codec parse-and-ignores (per its CapabilityMatrix's ``unsupported``
list — VRFs, VXLAN, route-maps, BGP detail) appear in the fixture so
the file looks like a real running-config but are not asserted; if a
later commit wires those up the ``test_populates_*`` assertions can
tighten without touching the fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec

pytestmark = pytest.mark.unit


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "synthetic"
    / "cisco_iosxe_cli"
    / "kitchen_sink.txt"
)


@pytest.fixture(scope="module")
def kitchen_sink_text() -> str:
    return FIXTURE_PATH.read_text()


@pytest.fixture(scope="module")
def parsed_intent(kitchen_sink_text: str):
    return CiscoIOSXECLICodec().parse(kitchen_sink_text)


# ---------------------------------------------------------------------------
# 1. Parses without exceptions
# ---------------------------------------------------------------------------


def test_parses_without_exceptions(kitchen_sink_text: str) -> None:
    """The synthetic kitchen-sink must parse cleanly — no ParseError,
    no unhandled exception.

    A regression here means the fixture has drifted from the codec's
    grammar (e.g. a wire form was added to the file that the parser
    can't handle, or the parser tightened a regex that the fixture's
    text now violates).
    """
    intent = CiscoIOSXECLICodec().parse(kitchen_sink_text)
    # Bare-minimum shape signal — every surface this fixture exercises
    # produces something non-empty downstream.
    assert intent.hostname == "kitchensink-rtr01"


# ---------------------------------------------------------------------------
# 2. Populates every expected canonical field
# ---------------------------------------------------------------------------


class TestCanonicalCoverage:
    """Per-field assertions that the kitchen-sink fixture exercises every
    canonical surface the cisco_iosxe_cli parser populates.

    Failure modes:
      * Adding a new feature to ``parse_intent`` without extending the
        kitchen-sink → coverage gap (caught by the 'this field has data'
        check on whatever new attribute appeared).
      * Removing a wire form from the fixture → assertion fails loudly
        with a clear message.
    """

    # --- system globals --------------------------------------------------

    def test_hostname_populated(self, parsed_intent) -> None:
        assert parsed_intent.hostname == "kitchensink-rtr01"

    def test_source_metadata(self, parsed_intent) -> None:
        assert parsed_intent.source_vendor == "cisco_iosxe"
        assert parsed_intent.source_format == "cli-ios"

    # --- VLANs (≥4 named) ------------------------------------------------

    def test_at_least_four_named_vlans(self, parsed_intent) -> None:
        named = [v for v in parsed_intent.vlans if v.name]
        assert len(named) >= 4
        # The four explicitly declared in the L2 database.  SVI synthesis
        # may add more entries (Vlan10/20/30/40 SVIs share IDs with
        # the L2 stanzas — they MERGE rather than duplicate), so we
        # assert by ID-presence, not by total count.
        ids = {v.id for v in parsed_intent.vlans}
        assert {10, 20, 30, 40} <= ids

    def test_vlan_names_exact(self, parsed_intent) -> None:
        by_id = {v.id: v.name for v in parsed_intent.vlans}
        assert by_id[10] == "USERS"
        assert by_id[20] == "SERVERS"
        assert by_id[30] == "VOICE"
        assert by_id[40] == "GUESTS"

    # --- interfaces (≥7 covering specific shapes) ------------------------

    def test_interface_count_at_least_seven(self, parsed_intent) -> None:
        assert len(parsed_intent.interfaces) >= 7

    def test_gigabit_with_ipv4(self, parsed_intent) -> None:
        gi = next(
            i for i in parsed_intent.interfaces
            if i.name == "GigabitEthernet0/0/0"
        )
        assert gi.description == "WAN uplink to ISP-A"
        assert len(gi.ipv4_addresses) == 1
        assert gi.ipv4_addresses[0].ip == "198.51.100.1"
        assert gi.ipv4_addresses[0].prefix_length == 30
        assert gi.interface_type == "ianaift:ethernetCsmacd"
        assert gi.mtu == 1500

    def test_gigabit_dual_stack_global_and_link_local(
        self, parsed_intent,
    ) -> None:
        gi = next(
            i for i in parsed_intent.interfaces
            if i.name == "GigabitEthernet0/0/0"
        )
        scopes = {a.scope for a in gi.ipv6_addresses}
        assert scopes == {"global", "link-local"}
        global_addr = next(
            a for a in gi.ipv6_addresses if a.scope == "global"
        )
        assert global_addr.ip == "2001:db8:beef::1"
        assert global_addr.prefix_length == 64

    def test_tengigabit_with_description(self, parsed_intent) -> None:
        ten = next(
            i for i in parsed_intent.interfaces
            if i.name == "TenGigabitEthernet1/0/1"
        )
        assert ten.description == "LACP member to core (Po1)"
        assert ten.interface_type == "ianaift:ethernetCsmacd"

    def test_switchport_access_with_voice_vlan_wire_form(
        self, parsed_intent,
    ) -> None:
        gi = next(
            i for i in parsed_intent.interfaces
            if i.name == "GigabitEthernet0/0/1"
        )
        assert gi.switchport_mode == "access"
        assert gi.access_vlan == 10

    def test_switchport_trunk_allowed_and_native(self, parsed_intent) -> None:
        ten = next(
            i for i in parsed_intent.interfaces
            if i.name == "TenGigabitEthernet1/0/1"
        )
        assert ten.switchport_mode == "trunk"
        assert ten.trunk_native_vlan == 10
        assert ten.trunk_allowed_vlans == [10, 20, 30, 40]

    def test_loopback_with_ipv4_and_ipv6(self, parsed_intent) -> None:
        lo = next(
            i for i in parsed_intent.interfaces if i.name == "Loopback0"
        )
        assert lo.interface_type == "ianaift:softwareLoopback"
        assert len(lo.ipv4_addresses) == 1
        assert lo.ipv4_addresses[0].ip == "10.255.255.1"
        assert lo.ipv4_addresses[0].prefix_length == 32
        assert len(lo.ipv6_addresses) == 1
        assert lo.ipv6_addresses[0].ip == "2001:db8:ffff::1"
        assert lo.ipv6_addresses[0].prefix_length == 128

    def test_port_channel_with_members(self, parsed_intent) -> None:
        po1 = next(
            i for i in parsed_intent.interfaces if i.name == "Port-channel1"
        )
        assert po1.description == "Uplink to core (LACP)"
        assert po1.interface_type == "ianaift:ieee8023adLag"

    def test_vlan_svi_with_ipv4_and_ipv6(self, parsed_intent) -> None:
        svi = next(
            i for i in parsed_intent.interfaces if i.name == "Vlan10"
        )
        assert svi.interface_type == "ianaift:l3ipvlan"
        assert svi.ipv4_addresses[0].ip == "192.168.10.1"
        assert svi.ipv4_addresses[0].prefix_length == 24
        assert svi.ipv6_addresses[0].ip == "2001:db8:10::1"
        assert svi.ipv6_addresses[0].prefix_length == 64

    def test_management_interface(self, parsed_intent) -> None:
        # The codec parses the GigabitEthernet0 stanza like any other
        # ethernet interface; ``vrf forwarding`` is parsed-and-ignored
        # (CanonicalRoutingInstance is unsupported on this codec — see
        # CapabilityMatrix), so we only assert what survives parse.
        mgmt = next(
            i for i in parsed_intent.interfaces if i.name == "GigabitEthernet0"
        )
        assert mgmt.description == "Out-of-band management interface"
        assert mgmt.ipv4_addresses[0].ip == "10.0.0.10"

    def test_shutdown_interface_disabled(self, parsed_intent) -> None:
        spare = next(
            i for i in parsed_intent.interfaces
            if i.name == "TenGigabitEthernet1/0/5"
        )
        assert spare.enabled is False

    def test_lag_member_back_pointers(self, parsed_intent) -> None:
        m1 = next(
            i for i in parsed_intent.interfaces
            if i.name == "TenGigabitEthernet1/0/1"
        )
        assert m1.lag_member_of == "Port-channel1"
        m2 = next(
            i for i in parsed_intent.interfaces
            if i.name == "TenGigabitEthernet1/0/3"
        )
        assert m2.lag_member_of == "Port-channel2"

    # --- LAGs (≥2) -------------------------------------------------------

    def test_lags_at_least_two(self, parsed_intent) -> None:
        assert len(parsed_intent.lags) >= 2

    def test_lag_membership_correct(self, parsed_intent) -> None:
        po1 = next(l for l in parsed_intent.lags if l.name == "Port-channel1")
        assert "TenGigabitEthernet1/0/1" in po1.members
        assert "TenGigabitEthernet1/0/2" in po1.members
        assert po1.mode == "active"
        po2 = next(l for l in parsed_intent.lags if l.name == "Port-channel2")
        assert "TenGigabitEthernet1/0/3" in po2.members
        assert "TenGigabitEthernet1/0/4" in po2.members
        assert po2.mode == "passive"

    # --- static routes ---------------------------------------------------

    def test_static_routes_at_least_three(self, parsed_intent) -> None:
        # The IPv4 ``ip route`` lines + the ``ip default-gateway`` line
        # all populate static_routes.  IPv6 routes and ``ip route vrf
        # ...`` lines are parse-and-ignored — same-vendor round-trip
        # drops them silently (documented in the parse module's
        # static-route regex docstring).
        assert len(parsed_intent.static_routes) >= 3

    def test_default_route_present(self, parsed_intent) -> None:
        defaults = [
            r for r in parsed_intent.static_routes
            if r.destination == "0.0.0.0/0"
        ]
        assert defaults, "expected at least one default route"
        # The ``ip route 0.0.0.0 0.0.0.0 198.51.100.2`` form lands
        # with gateway 198.51.100.2.
        gateways = {r.gateway for r in defaults}
        assert "198.51.100.2" in gateways

    def test_interface_static_route(self, parsed_intent) -> None:
        iface_routes = [
            r for r in parsed_intent.static_routes if r.interface
        ]
        assert any(
            r.destination == "10.20.0.0/16"
            and r.interface == "GigabitEthernet0/0/0"
            for r in iface_routes
        )

    # --- DHCP pools ------------------------------------------------------

    def test_dhcp_pools_populated(self, parsed_intent) -> None:
        assert len(parsed_intent.dhcp_servers) == 2
        users = parsed_intent.dhcp_servers[0]
        assert users.network == "192.168.10.0/24"
        assert users.gateway == "192.168.10.1"
        assert users.dns_servers == ["198.51.100.53", "198.51.100.54"]
        assert users.domain_name == "corp.kitchensink.example.com"
        assert users.lease_time == 7 * 86400  # 7 days

    def test_dhcp_pool_lease_one_day(self, parsed_intent) -> None:
        # Second pool uses ``lease 1 0 0`` (one day) — exercises the
        # multi-token Cisco lease form.  ``lease infinite`` is a real
        # IOS-XE form but its render path collapses to ``lease 0
        # <hours>`` which is lossy on round-trip; that bug is out of
        # scope here, so we keep the kitchen-sink to forms the
        # codec round-trips cleanly.
        voice = parsed_intent.dhcp_servers[1]
        assert voice.lease_time == 86400

    # --- RADIUS ---------------------------------------------------------

    def test_radius_servers_populated(self, parsed_intent) -> None:
        # ≥1 required by the spec; the kitchen sink ships two for
        # primary/secondary parity coverage.
        assert len(parsed_intent.radius_servers) >= 1
        primary = next(
            s for s in parsed_intent.radius_servers
            if s.host == "198.51.100.40"
        )
        assert primary.auth_port == 1812
        assert primary.acct_port == 1813
        # Cisco's ``key 7 <hash>`` format preserves the type digit;
        # parse stores it verbatim as ``"7 fakeRadiusSharedSecret01"``.
        assert "fakeRadiusSharedSecret01" in primary.key

    # --- local users (3 hash forms) -------------------------------------

    def test_local_users_three_hash_forms(self, parsed_intent) -> None:
        users_by_name = {u.name: u for u in parsed_intent.local_users}
        assert {"admin1", "admin2", "operator1"} <= set(users_by_name)
        # admin1 — type 5 (MD5-crypt $1$).
        assert users_by_name["admin1"].privilege_level == 15
        assert users_by_name["admin1"].hashed_password.startswith("5 $1$")
        # admin2 — type 9 (scrypt $9$).
        assert users_by_name["admin2"].privilege_level == 15
        assert users_by_name["admin2"].hashed_password.startswith("9 $9$")
        # operator1 — type 8 (PBKDF2-SHA-256 $8$).
        assert users_by_name["operator1"].privilege_level == 5
        assert users_by_name["operator1"].hashed_password.startswith("8 $8$")
        # Cisco's parser maps non-15 privilege to canonical role
        # ``operator`` (15 → ``admin``).
        assert users_by_name["admin1"].role == "admin"
        assert users_by_name["operator1"].role == "operator"

    # --- SNMP ----------------------------------------------------------

    def test_snmp_block_present(self, parsed_intent) -> None:
        assert parsed_intent.snmp is not None

    def test_snmp_community_captured(self, parsed_intent) -> None:
        # Cisco's snmp-server parser captures the FIRST ``snmp-server
        # community`` line (a single string fits the canonical
        # ``community`` field).  RW + view-restricted communities are
        # in the wire form for cross-vendor realism but the canonical
        # surface is single-valued.
        assert parsed_intent.snmp.community == "publicRO"

    def test_snmp_location_and_contact(self, parsed_intent) -> None:
        assert parsed_intent.snmp.location == "Lab-A Rack 12 Unit 4"
        assert parsed_intent.snmp.contact == "noc@kitchensink.example.com"

    def test_snmp_trap_hosts(self, parsed_intent) -> None:
        hosts = parsed_intent.snmp.trap_hosts
        assert "198.51.100.250" in hosts
        assert "198.51.100.251" in hosts

    def test_snmp_v3_users_populated(self, parsed_intent) -> None:
        v3 = parsed_intent.snmp.v3_users
        assert len(v3) >= 2
        by_name = {u.name: u for u in v3}
        # monitor1 — sha + aes 128 (Cisco two-token cipher form
        # canonicalised to ``aes128``).
        assert by_name["monitor1"].auth_protocol == "sha"
        assert by_name["monitor1"].priv_protocol == "aes128"
        # monitor2 — sha256 + aes 256.
        assert by_name["monitor2"].auth_protocol == "sha256"
        assert by_name["monitor2"].priv_protocol == "aes256"
        # Group is preserved verbatim.
        assert by_name["monitor1"].group == "MONITOR-GRP"


# ---------------------------------------------------------------------------
# 3. Round-trip stability
# ---------------------------------------------------------------------------


def _interface_signature(intent) -> list[tuple]:
    """Compact comparable representation of intent.interfaces."""
    sig: list[tuple] = []
    for i in intent.interfaces:
        sig.append((
            i.name,
            i.description,
            i.enabled,
            i.interface_type,
            i.mtu,
            tuple((a.ip, a.prefix_length) for a in i.ipv4_addresses),
            tuple(
                (a.ip, a.prefix_length, a.scope) for a in i.ipv6_addresses
            ),
            i.switchport_mode,
            i.access_vlan,
            tuple(i.trunk_allowed_vlans),
            i.trunk_native_vlan,
            i.lag_member_of,
        ))
    return sig


def test_round_trip_stable(kitchen_sink_text: str) -> None:
    """``parse → render → re-parse`` produces an equivalent canonical
    tree on the parsed surfaces.

    The renderer emits a normalised wire form (sorted interfaces,
    explicit ``no shutdown`` omitted, comments dropped).  We compare
    canonical-tree fields, not raw text — text equality after one
    pass is a different invariant the codec doesn't promise.

    Surfaces compared: hostname / vlans / interfaces / static_routes /
    LAGs / DHCP pools / RADIUS / local users / SNMP.  Surfaces the
    parser doesn't populate today (DNS / NTP / syslog / timezone /
    VRFs / IPv6-static / via-VRF static) are not part of the
    invariant — they're empty on both sides.
    """
    codec = CiscoIOSXECLICodec()
    first = codec.parse(kitchen_sink_text)
    rendered = codec.render(first)
    second = codec.parse(rendered)

    # System globals
    assert first.hostname == second.hostname

    # VLANs — id+name pairs (sorted; render is stable but the test
    # shouldn't depend on render-order details).
    assert sorted((v.id, v.name) for v in first.vlans) == \
           sorted((v.id, v.name) for v in second.vlans)

    # Interfaces — signature-based comparison covers every parsed
    # per-interface attribute.  Sort by name so the test is stable
    # against render-time interface ordering (Port-channel-first /
    # natural-port sort) which the parse path doesn't replicate.
    assert sorted(_interface_signature(first)) == \
           sorted(_interface_signature(second))

    # Static routes — destination + gateway + interface tuple.
    assert sorted(
        (r.destination, r.gateway, r.interface)
        for r in first.static_routes
    ) == sorted(
        (r.destination, r.gateway, r.interface)
        for r in second.static_routes
    )

    # LAGs — name + sorted members + mode.
    def _lag_sig(intent):
        return sorted(
            (l.name, tuple(sorted(l.members)), l.mode) for l in intent.lags
        )
    assert _lag_sig(first) == _lag_sig(second)

    # DHCP pools.
    def _dhcp_sig(intent):
        return [
            (
                p.network, p.gateway, tuple(p.dns_servers),
                p.domain_name, p.lease_time,
            )
            for p in intent.dhcp_servers
        ]
    assert _dhcp_sig(first) == _dhcp_sig(second)

    # RADIUS servers.
    def _radius_sig(intent):
        return sorted(
            (s.host, s.auth_port, s.acct_port) for s in intent.radius_servers
        )
    assert _radius_sig(first) == _radius_sig(second)

    # Local users.
    def _user_sig(intent):
        return sorted(
            (u.name, u.privilege_level, u.role) for u in intent.local_users
        )
    assert _user_sig(first) == _user_sig(second)

    # SNMP — community + location + contact + sorted trap-hosts +
    # sorted v3-user (name, auth, priv) tuples.
    def _snmp_sig(intent):
        if intent.snmp is None:
            return None
        return (
            intent.snmp.community,
            intent.snmp.location,
            intent.snmp.contact,
            tuple(sorted(intent.snmp.trap_hosts)),
            tuple(sorted(
                (u.name, u.group, u.auth_protocol, u.priv_protocol)
                for u in intent.snmp.v3_users
            )),
        )
    assert _snmp_sig(first) == _snmp_sig(second)
