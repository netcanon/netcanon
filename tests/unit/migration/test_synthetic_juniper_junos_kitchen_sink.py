"""
Unit tests for the synthetic kitchen-sink fixture for the
juniper_junos codec.

Fixture: ``tests/fixtures/synthetic/juniper_junos/kitchen_sink.set``

The fixture exercises every canonical surface declared 'supported' or
'lossy' in :class:`JunosCodec._CAPS`, plus the apply-groups two-pass
parse (GAP 8) and group-content round-trip (GAP 9b) which is unique
to Junos amongst the shipped codecs.

Tests:
    1. ``test_parses_without_exceptions`` — fixture parses cleanly.
    2. ``test_populates_every_expected_canonical_field`` — every
       canonical field that the codec is wired for has a non-default
       value (with rationale for the few that don't).
    3. ``test_round_trip_stable`` — parse(render(parse(raw))) yields
       the same rendered output as parse(render(parse(raw))) (the
       canonical equality after one round-trip).
    4. ``test_apply_groups_inheritance`` — GLOBAL-SETTINGS group's
       interface description+mtu flow into the ge-0/0/0
       CanonicalInterface, and the syslog host added under the group
       flows into intent.syslog_servers.
"""

from __future__ import annotations

import pathlib

import pytest

from netconfig.migration.codecs.juniper_junos import JunosCodec

pytestmark = pytest.mark.unit


FIXTURE_PATH = pathlib.Path(
    "tests/fixtures/synthetic/juniper_junos/kitchen_sink.set"
)


def _load_raw() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Parse without exceptions
# ---------------------------------------------------------------------------


def test_parses_without_exceptions():
    """The kitchen-sink fixture parses cleanly into a CanonicalIntent."""
    raw = _load_raw()
    intent = JunosCodec().parse(raw)
    # Sanity guard — non-trivial tree.
    assert intent.hostname
    assert intent.interfaces
    assert intent.vlans


# ---------------------------------------------------------------------------
# 2. Per-canonical-field coverage
# ---------------------------------------------------------------------------


def test_populates_every_expected_canonical_field():
    """Every canonical surface the codec is wired for has a non-default
    value populated by the fixture.

    Surfaces NOT asserted (and why):
      * ``intent.timezone`` — Junos parser does not yet wire
        ``set system time-zone`` into the canonical surface; the line
        is included in the fixture but parses-and-ignores.
      * ``intent.lags`` — Junos LAG modelling (``set interfaces aeN``
        + ``ether-options 802.3ad``) is parse-and-ignore in v1; the
        codec does NOT populate :attr:`CanonicalIntent.lags`.  Lines
        are included for round-trip realism.
      * ``intent.radius_servers`` — same story; ``set system
        radius-server`` parses-and-ignores in v1.
      * ``CanonicalLocalUser.hashed_password`` for the no-password
        user — the third user (``readonly``) authenticates via ssh-rsa
        which is unmodelled, so its hashed_password stays empty.  The
        other two users carry their encrypted-password hashes.
    """
    intent = JunosCodec().parse(_load_raw())

    # --- system scalars ---
    assert intent.hostname == "kitchen-sink-junos"
    assert intent.domain == "lab.example.net"
    assert intent.dns_servers == ["10.0.0.53", "10.0.0.54"]
    # NTP `prefer` keyword tail is dropped; both servers list.
    assert "10.0.0.123" in intent.ntp_servers
    assert "10.0.0.124" in intent.ntp_servers
    # Syslog: 10.0.0.250 + 10.0.0.251 from top level + 10.0.0.252 from
    # the GLOBAL-SETTINGS apply-group (validates two-pass dispatch
    # carries syslog inheritance).
    assert "10.0.0.250" in intent.syslog_servers
    assert "10.0.0.251" in intent.syslog_servers
    assert "10.0.0.252" in intent.syslog_servers

    # --- local users (3) ---
    user_names = {u.name for u in intent.local_users}
    assert {"admin", "operator", "readonly"} <= user_names
    admin = next(u for u in intent.local_users if u.name == "admin")
    assert admin.role == "super-user"
    assert admin.privilege_level == 15  # super-user maps to 15
    assert admin.hashed_password.startswith("junos:$6$")
    operator = next(u for u in intent.local_users if u.name == "operator")
    assert operator.role == "operator"
    assert operator.hashed_password.startswith("junos:$6$")
    readonly = next(u for u in intent.local_users if u.name == "readonly")
    assert readonly.role == "read-only"
    # ssh-rsa public key isn't wired into hashed_password — empty.
    assert readonly.hashed_password == ""

    # --- VLANs (4 named) ---
    vlan_ids = {v.id for v in intent.vlans}
    assert vlan_ids == {10, 20, 100, 200}
    vlan_names = {v.name for v in intent.vlans}
    assert vlan_names == {"USERS", "VOICE", "TENANT_A_DATA", "TRANSIT"}

    # --- VXLAN VNIs (3 — USERS / VOICE / TENANT_A_DATA) ---
    vni_by_vlan = {x.vlan_id: x.vni for x in intent.vxlan_vnis}
    assert vni_by_vlan == {10: 10010, 20: 10020, 100: 10100}
    # Switch-options globals stamped on every VXLAN record.
    for x in intent.vxlan_vnis:
        assert x.source_interface == "lo0.0"
        assert x.udp_port == 4789

    # --- static routes (3 — IPv4 default, IPv4 named, IPv6 default) ---
    route_dests = {r.destination for r in intent.static_routes}
    assert route_dests == {"0.0.0.0/0", "10.50.0.0/16", "::/0"}
    by_dest = {r.destination: r for r in intent.static_routes}
    assert by_dest["0.0.0.0/0"].gateway == "10.0.0.2"
    assert by_dest["10.50.0.0/16"].gateway == "10.0.0.3"
    assert by_dest["::/0"].gateway == "2001:db8::2"

    # --- routing instances (3 — vrf, mac-vrf, virtual-router) ---
    ri_names = {r.name for r in intent.routing_instances}
    assert ri_names == {"TENANT_A", "TENANT_B", "RTR_C"}
    by_name = {r.name: r for r in intent.routing_instances}
    # TENANT_A: full vrf with RD + RT + L3 VNI for Type-5
    a = by_name["TENANT_A"]
    assert a.instance_type == "vrf"
    assert a.route_distinguisher == "172.16.0.1:10000"
    assert "65000:10000" in a.rt_imports
    assert "65000:10000" in a.rt_exports
    assert a.l3_vni == 50100
    assert a.description == "Tenant A L3 VRF"
    # TENANT_B: mac-vrf with asymmetric RT import/export
    b = by_name["TENANT_B"]
    assert b.instance_type == "mac-vrf"
    assert b.route_distinguisher == "172.16.0.1:20000"
    assert b.rt_imports == ["65000:20000"]
    assert b.rt_exports == ["65000:20001"]
    # RTR_C: virtual-router (no RD/RT) — type passthrough check
    c = by_name["RTR_C"]
    assert c.instance_type == "virtual-router"

    # --- interface VRF membership flowed from routing-instances ---
    # irb.100 → TENANT_A, irb.200 → TENANT_B, ge-0/0/0 → RTR_C
    iface_by_name = {i.name: i for i in intent.interfaces}
    assert iface_by_name["irb.100"].vrf == "TENANT_A"
    assert iface_by_name["irb.200"].vrf == "TENANT_B"
    assert iface_by_name["ge-0/0/0"].vrf == "RTR_C"

    # --- interfaces (≥7) covering each shape ---
    iface_names = set(iface_by_name)
    expected_present = {
        "ge-0/0/0",       # IPv4 + IPv6 + apply-group inheritance
        "ge-0/0/1",       # parent of trunk port (with mtu)
        "ge-0/0/1.100",   # sub-interface with vlan-id (access_vlan)
        "lo0",            # IPv4 + IPv6 global + IPv6 link-local
        "ae0",            # LAG aggregate (with IP)
        "ae1",            # LAG aggregate
        "irb.100",        # SVI (sub-interface of irb)
        "irb.200",        # SVI
        "em0",            # management
        "fxp0",           # OOB management
        "ge-0/0/9",       # disabled interface
    }
    assert expected_present <= iface_names

    # ge-0/0/0 — IPv4 + IPv6
    g0 = iface_by_name["ge-0/0/0"]
    assert any(a.ip == "10.0.0.1" and a.prefix_length == 31 for a in g0.ipv4_addresses)
    assert any(a.ip == "2001:db8::1" and a.prefix_length == 64 for a in g0.ipv6_addresses)

    # ge-0/0/1 — non-default MTU
    g1 = iface_by_name["ge-0/0/1"]
    assert g1.mtu == 9100

    # ge-0/0/1.100 — sub-interface with per-unit vlan-id (access_vlan)
    g1_100 = iface_by_name["ge-0/0/1.100"]
    assert g1_100.access_vlan == 100
    assert any(a.ip == "10.100.0.1" for a in g1_100.ipv4_addresses)

    # lo0 — IPv4 + IPv6 global + IPv6 link-local (scope inferred)
    lo = iface_by_name["lo0"]
    assert any(a.ip == "172.16.0.1" for a in lo.ipv4_addresses)
    v6_global = [a for a in lo.ipv6_addresses if a.scope == "global"]
    v6_link = [a for a in lo.ipv6_addresses if a.scope == "link-local"]
    assert v6_global, "lo0 should carry a global IPv6 address"
    assert v6_link, "lo0 should carry a link-local IPv6 address (fe80::/10)"

    # ae0 — LAG aggregate with IP + MTU
    ae0 = iface_by_name["ae0"]
    assert ae0.mtu == 9192
    assert any(a.ip == "10.1.0.1" for a in ae0.ipv4_addresses)

    # irb.100 — SVI with IPv4 + IPv6
    irb100 = iface_by_name["irb.100"]
    assert any(a.ip == "172.16.100.1" for a in irb100.ipv4_addresses)
    assert any(a.ip == "2001:db8:100::1" for a in irb100.ipv6_addresses)

    # em0 — management interface populated
    em0 = iface_by_name["em0"]
    assert any(a.ip == "192.168.100.10" for a in em0.ipv4_addresses)

    # fxp0 — OOB management
    fxp0 = iface_by_name["fxp0"]
    assert any(a.ip == "192.168.99.10" for a in fxp0.ipv4_addresses)

    # ge-0/0/9 — disabled interface
    g9 = iface_by_name["ge-0/0/9"]
    assert g9.enabled is False

    # --- SNMP (community + location + contact + traps + 2 v3 users) ---
    assert intent.snmp is not None
    # First community wins (RO public).
    assert intent.snmp.community == "public"
    assert intent.snmp.location == "Synthetic Lab Rack 7"
    assert intent.snmp.contact == "noc@example.net"
    assert "10.0.0.250" in intent.snmp.trap_hosts
    assert "10.0.0.251" in intent.snmp.trap_hosts
    v3_by_name = {u.name: u for u in intent.snmp.v3_users}
    assert {"monitor", "readonly_v3"} <= set(v3_by_name)
    monitor = v3_by_name["monitor"]
    assert monitor.auth_protocol == "md5"
    assert monitor.priv_protocol == "des"
    assert monitor.group == "netadmin"
    ro_v3 = v3_by_name["readonly_v3"]
    assert ro_v3.auth_protocol == "sha256"
    assert ro_v3.priv_protocol == "aes256"
    assert ro_v3.group == "readonly"

    # --- apply-groups (Junos-specific two-pass parse + group-content) ---
    assert intent.apply_groups == ["GLOBAL-SETTINGS"]
    assert "GLOBAL-SETTINGS" in intent.group_content
    # The captured group body is a list of token-lists.
    body = intent.group_content["GLOBAL-SETTINGS"]
    assert isinstance(body, list)
    assert all(isinstance(t, list) for t in body)
    # At least the three known group-scoped lines made it through.
    assert len(body) >= 3


# ---------------------------------------------------------------------------
# 3. Round-trip stability
# ---------------------------------------------------------------------------


def test_round_trip_stable():
    """``render(parse(render(parse(raw))))`` equals
    ``render(parse(raw))`` — second-generation render is byte-identical
    to first-generation render.
    """
    codec = JunosCodec()
    raw = _load_raw()
    first_intent = codec.parse(raw)
    rendered_a = codec.render(first_intent)
    # Re-parse the rendered output and re-render.  Junos parsers
    # accept rendered output; second render must match first byte-for-
    # byte.
    second_intent = codec.parse(rendered_a)
    rendered_b = codec.render(second_intent)
    assert rendered_a == rendered_b, (
        "Junos kitchen-sink round-trip is not stable: render → parse "
        "→ render must produce byte-identical output."
    )
    # And the canonical interfaces / VRFs / VNIs counts are preserved.
    assert len(first_intent.interfaces) == len(second_intent.interfaces)
    assert len(first_intent.vlans) == len(second_intent.vlans)
    assert len(first_intent.vxlan_vnis) == len(second_intent.vxlan_vnis)
    assert len(first_intent.routing_instances) == len(
        second_intent.routing_instances
    )
    assert first_intent.apply_groups == second_intent.apply_groups


# ---------------------------------------------------------------------------
# 4. Apply-groups inheritance — Junos two-pass parse (GAP 8 / GAP 9b)
# ---------------------------------------------------------------------------


def test_apply_groups_inheritance():
    """Verify the GLOBAL-SETTINGS apply-group's content actually flows
    into the canonical tree.

    Specifically:
      * ge-0/0/0 has NO top-level ``description`` or ``mtu`` lines in
        the fixture — only ``set groups GLOBAL-SETTINGS interfaces
        ge-0/0/0 description ...`` and ``... mtu 9000``.  So the
        CanonicalInterface fields must come purely from the apply-
        groups two-pass.
      * The group also adds a syslog host (10.0.0.252).  Top level
        only declares 10.0.0.250 + 10.0.0.251.
    """
    intent = JunosCodec().parse(_load_raw())

    # Apply-groups statement preserved.
    assert intent.apply_groups == ["GLOBAL-SETTINGS"]
    # Group content captured for round-trip re-emission.
    assert "GLOBAL-SETTINGS" in intent.group_content

    # ge-0/0/0 description comes from the group (top-level lines only
    # add IP addresses; description is exclusively on the group).
    iface_by_name = {i.name: i for i in intent.interfaces}
    g0 = iface_by_name["ge-0/0/0"]
    assert g0.description == "Inherited from GLOBAL-SETTINGS apply-group"
    assert g0.mtu == 9000

    # Syslog 10.0.0.252 came from the group (top-level only declared
    # 250 + 251).
    assert "10.0.0.252" in intent.syslog_servers

    # And critically: the IPv4/IPv6 addresses on ge-0/0/0 (declared at
    # top level) survive the two-pass too — apply-groups inheritance
    # must not clobber direct intent.
    assert any(
        a.ip == "10.0.0.1" and a.prefix_length == 31
        for a in g0.ipv4_addresses
    )
    assert any(
        a.ip == "2001:db8::1" and a.prefix_length == 64
        for a in g0.ipv6_addresses
    )
