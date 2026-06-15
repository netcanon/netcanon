"""
Registry-wide capability-matrix honesty guard (review finding #9).

The 2026-06 architecture review flagged that the two-sided
render/walker honesty invariant was enforced for exactly ONE codec
(the cisco_iosxe NETCONF stub, in
``tests/unit/migration/codecs/cisco_iosxe/test_capability_matrix_honesty.py``)
and left the 11 production codecs ungated: a render expansion or a
matrix loosening could drift a codec's declared capabilities away from
its real behaviour with no failing test.

This module promotes the guard to the whole registry.  It enforces the
two *robust* directions of the honesty invariant — the ones that have
no false positives across a single universal kitchen-sink:

1. **Reverse-parity** (``test_declared_supported_is_walkable``): every
   ``supported`` xpath a codec declares must be a string the shared
   canonical walker (``_walk_canonical``) can actually emit.  A declared
   path the walker never yields is unreachable by ``validate_against``
   (``CapabilityMatrix.classify`` is exact-string match) — a dead
   declaration.  This is the guard the project's own expectation YAML
   asked for (``cisco_iosxe_cli__cisco_iosxe.yaml``: "assert every
   supported path is actually walked by the codec's iter_xpaths").

2. **Rendered ⇒ not-unsupported** (``test_rendered_field_not_unsupported``):
   render a kitchen-sink, re-parse it, and for every top-level field
   that SURVIVES the round-trip (i.e. the codec demonstrably renders it)
   assert the codec does NOT declare that field ``unsupported``.  A
   matrix that calls a surface unsupported while the codec actually
   round-trips it is a lie that would wrongly block / warn a migration.
   Field *survival* is unambiguous (no vendor-naming false positives),
   so this direction is safe to enforce registry-wide.

3. **No supported/unsupported overlap** (``test_no_supported_unsupported_overlap``).

The third honesty direction — *dropped*-field ⇒ ``unsupported`` — is
NOT enforced here.  Detecting a "drop" from a single universal
kitchen-sink produces vendor-naming false positives (e.g. a LAG whose
member interface name isn't valid for a given vendor fails to render,
which looks like "drops all LAGs" when the codec supports LAGs with
native names).  Forcing declarations from those false positives would
make the matrices *less* honest.  That direction stays covered by the
per-codec round-trip tests (``parse(render(x)) == x`` for the supported
subset) and the offline cross-mesh fidelity audit, plus the dedicated
cisco_iosxe stub guard.
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
    CanonicalVRRPGroup,
    CanonicalVxlan,
)
from netcanon.migration.codecs.cisco_iosxe_cli.codec import _walk_canonical
from netcanon.migration.codecs.registry import get_codec, list_codecs

# Explicit imports so every codec is registered when this module runs
# standalone (mirrors run_full_mesh.py / test_cross_mesh_overrides.py).
from netcanon.migration.codecs import (  # noqa: F401
    arista_eos,
    aruba_aoscx,
    aruba_aoss,
    cisco_iosxe,
    cisco_iosxe_cli,
    cisco_iosxr,
    cisco_nxos,
    fortigate_cli,
    juniper_junos,
    mikrotik_routeros,
    opnsense,
    vyos,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Registry under test — every BIDIRECTIONAL codec except the reference
# mock adapter (which uses a flat-dict tree, not the canonical walker).
# ---------------------------------------------------------------------------

def _bidirectional_codec_names() -> list[str]:
    names = []
    for name in sorted(list_codecs()):
        if name == "mock":
            continue
        codec = get_codec(name)
        if getattr(codec, "direction", "bidirectional") == "bidirectional":
            names.append(name)
    return names


_CODEC_NAMES = _bidirectional_codec_names()


def _maximal_intent() -> CanonicalIntent:
    """A CanonicalIntent populating every canonical sub-field the walker
    yields conditionally, so ``set(_walk_canonical(intent))`` is the full
    universe of emittable xpaths.

    Internally consistent (LAG members + VLAN ports reference defined
    interfaces) so codecs render + re-parse it without raising.
    """
    addr4 = CanonicalIPv4Address(
        ip="10.0.0.1", prefix_length=24,
        virtual_gateway_address="10.0.0.254",
        virtual_gateway_mac="00:00:5e:00:01:01",
    )
    addr6 = CanonicalIPv6Address(
        ip="2001:db8::1", prefix_length=64,
        virtual_gateway_address="2001:db8::254",
        virtual_gateway_mac="00:00:5e:00:02:01",
    )
    iface = CanonicalInterface(
        name="Ethernet1", default_name="Ethernet1", description="d",
        enabled=True, interface_type="ianaift:ethernetCsmacd", mtu=9000,
        ipv4_addresses=[addr4], ipv6_addresses=[addr6],
        switchport_mode="trunk", access_vlan=10, trunk_allowed_vlans=[10, 20],
        trunk_native_vlan=99, voice_vlan=200, lag_member_of="Port-Channel1",
        dhcp_client=True, dhcp_client_v6="dhcp6", tunnel_type="gre",
        vrf="TENANT",
        vrrp_groups=[CanonicalVRRPGroup(
            group_id=10,
            # >1 VIP + virtual_mac + track exercise the VRRP sub-field
            # losses several codecs declare lossy, so the walker yields
            # those granular xpaths and reverse-parity confirms the lossy
            # declarations are reachable.
            virtual_ips=["10.0.0.254", "10.0.0.253"],
            virtual_mac="00:00:5e:00:01:0a",
            track_interfaces=["Ethernet2"])],
    )
    iface2 = CanonicalInterface(
        name="Ethernet2", enabled=True,
        interface_type="ianaift:ethernetCsmacd",
    )
    return CanonicalIntent(
        hostname="h", domain="d.test", dns_servers=["10.0.0.53"],
        ntp_servers=["10.0.0.123"], timezone="UTC",
        syslog_servers=["10.0.0.514"],
        interfaces=[iface, iface2],
        vlans=[CanonicalVlan(
            id=10, name="V", description="desc",
            tagged_ports=["Ethernet1"], untagged_ports=["Ethernet2"],
            ipv4_addresses=[addr4])],
        static_routes=[CanonicalStaticRoute(
            destination="0.0.0.0/0", gateway="10.0.0.2", vrf="TENANT")],
        anycast_gateway_mac="00:1c:73:00:dc:01",
        dhcp_servers=[CanonicalDHCPPool(
            network="10.0.0.0/24", start_ip="10.0.0.10", end_ip="10.0.0.99")],
        snmp=CanonicalSNMP(
            community="c", location="l", contact="ct", trap_hosts=["10.0.0.9"],
            v3_users=[CanonicalSNMPv3User(
                name="u", group="g", auth_protocol="sha",
                auth_passphrase="$9$a", priv_protocol="aes",
                priv_passphrase="$9$p", engine_id="80000009ff")]),
        lags=[CanonicalLAG(
            name="Port-Channel1", members=["Ethernet1"], mode="active")],
        local_users=[CanonicalLocalUser(
            name="admin", privilege_level=15, hashed_password="$9$h",
            role="admin")],
        radius_servers=[CanonicalRADIUSServer(host="10.0.0.1", key="$9$r")],
        vxlan_vnis=[CanonicalVxlan(
            vlan_id=10, vni=10010, mcast_group="239.1.1.1",
            flood_list=["10.0.0.5"], source_interface="Loopback0",
            udp_port=4789)],
        evpn_type5_routes=[CanonicalEvpnType5Route(
            vrf="TENANT", prefix="10.0.0.0/16")],
        routing_instances=[CanonicalRoutingInstance(
            name="TENANT", instance_type="vrf",
            route_distinguisher="65000:1", rt_imports=["65000:1"],
            rt_exports=["65000:1"], description="t", l3_vni=50010)],
    )


#: Every xpath the shared walker can emit when every surface is populated.
_WALKABLE = frozenset(_walk_canonical(_maximal_intent()))


#: Top-level CanonicalIntent fields → the xpath markers that declare the
#: WHOLE field unsupported (the top-level field-marker ``/{field}`` plus
#: the field's primary-identity / base path).  Deliberately exact-match,
#: NOT prefix-match: a codec that declares a *sub-field* unsupported
#: (e.g. opnsense ``/snmp/v3-user``, vyos ``/vxlan-vnis/l2vni-route-target``,
#: aoscx ``/routing-instances/instance/description``) while supporting the
#: base surface is exercising normal partial support, not declaring the
#: field unsupported — so a prefix match would mis-fire on it.
_FIELD_TO_UNSUPPORTED_MARKERS: dict[str, tuple[str, ...]] = {
    "hostname": ("/system/hostname", "/hostname"),
    "domain": ("/system/domain", "/domain"),
    "dns_servers": ("/system/dns-server", "/dns_servers"),
    "ntp_servers": ("/system/ntp-server", "/ntp_servers"),
    "syslog_servers": ("/system/syslog-server", "/syslog_servers"),
    "vlans": ("/vlans", "/vlans/vlan/id"),
    "static_routes": ("/routing/static-route", "/static_routes"),
    "dhcp_servers": ("/dhcp-servers/pool", "/dhcp_servers"),
    "snmp": ("/snmp", "/snmp/community"),
    "lags": ("/lags", "/lags/lag/name"),
    "local_users": ("/local_users", "/local-users/user/name"),
    "radius_servers": ("/radius_servers", "/radius-servers/server/host"),
    "vxlan_vnis": ("/vxlan_vnis", "/vxlan-vnis/vni"),
    "evpn_type5_routes": ("/evpn_type5_routes", "/evpn-type5-routes/route"),
    "routing_instances": (
        "/routing_instances",
        "/routing-instances/instance",
        "/routing-instances/instance/name",
    ),
    "timezone": ("/system/timezone", "/timezone"),
    "interfaces": ("/interfaces/interface/name",),
    "anycast_gateway_mac": ("/anycast-gateway-mac",),
}


#: Top-level fields carrying ONLY naming-independent data (bare scalars /
#: IP lists / opaque secrets — no vendor-specific interface/LAG names), keyed
#: to the granular walker xpath(s) that prove a codec declared the drop.  For
#: these, a TOTAL drop on render→re-parse is unambiguous (no vendor-naming
#: false positive), so the matrix MUST declare the surface unsupported/lossy
#: — otherwise live validation reports ``severity: ok`` while the render
#: silently discards the data.  (Contrast the naming-SENSITIVE surfaces —
#: lags, switchport — where a single universal kitchen-sink can't tell a true
#: drop from a vendor-name mismatch; those stay out of this check.)
_NAMING_INDEPENDENT_DROP_FIELDS: dict[str, tuple[str, ...]] = {
    "domain": ("/system/domain",),
    "timezone": ("/system/timezone",),
    "dns_servers": ("/system/dns-server",),
    "ntp_servers": ("/system/ntp-server",),
    "syslog_servers": ("/system/syslog-server",),
    "dhcp_servers": ("/dhcp-servers/pool",),
    "radius_servers": ("/radius-servers/server/host", "/radius-servers/server/key"),
    "routing_instances": ("/routing-instances/instance", "/routing-instances/instance/name"),
    # NB: `vlans` is intentionally absent.  Its drop is codec-specific, not a
    # clean universal pattern: SP-router codecs (cisco_iosxr) model VLANs as
    # dot1q sub-interface encapsulation rather than a standalone VLAN DB, so a
    # standalone CanonicalVlan "drops" on round-trip while the L2 intent
    # survives via interfaces — a nuance this total-drop check would
    # mis-attribute.  Left to a per-codec capability decision.
}


def _declares_unsupported(unsupported: set[str], markers: tuple[str, ...]) -> bool:
    """True iff the WHOLE field is declared unsupported (exact match on a
    field-marker / primary-identity path)."""
    return any(m in unsupported for m in markers)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_registry_is_non_empty():
    """Sanity: the bidirectional registry resolved to the expected fleet."""
    assert len(_CODEC_NAMES) >= 11, _CODEC_NAMES


@pytest.mark.parametrize("name", _CODEC_NAMES)
def test_declared_supported_is_walkable(name: str):
    """Every ``supported`` xpath a codec declares must be a string the
    shared canonical walker can emit (reverse-parity, review #8c).

    A ``supported`` path the walker never yields is unreachable by
    ``validate_against`` — exact-string ``classify`` can never be invoked
    with it — so it is a dead declaration that silently drifts the matrix
    from the walker's vocabulary."""
    codec = get_codec(name)
    supported = set(codec.capabilities.supported)
    unreachable = sorted(supported - _WALKABLE)
    assert not unreachable, (
        f"{name}: declares supported xpath(s) the canonical walker never "
        f"emits, so validate_against can never reach them: {unreachable}.  "
        f"Either normalise the declaration to the walker's vocabulary or "
        f"add the yield to _walk_canonical."
    )


@pytest.mark.parametrize("name", _CODEC_NAMES)
def test_rendered_field_not_unsupported(name: str):
    """A top-level field that SURVIVES a render→re-parse round-trip is
    demonstrably emitted by the codec, so it must NOT be declared
    ``unsupported`` (review #9, the safe half of the render-honesty
    invariant — field survival has no vendor-naming false positives).

    NB: for the ``cisco_iosxe`` NETCONF stub (renders interfaces only)
    this check is expected to be near-vacuous — almost every field
    short-circuits at ``survived=False`` — and that codec's dropped-field
    honesty is covered by its dedicated guard
    (``codecs/cisco_iosxe/test_capability_matrix_honesty.py``).  The
    finer-grained :func:`test_roundtrip_emitted_xpath_not_unsupported`
    still does real work on its surviving interface xpaths."""
    codec = get_codec(name)
    intent = _maximal_intent()
    src = intent.model_dump()
    rendered = codec.render(intent)
    reparsed = codec.parse(rendered).model_dump()
    unsupported = {u.path for u in codec.capabilities.unsupported}

    lies = []
    for field, markers in _FIELD_TO_UNSUPPORTED_MARKERS.items():
        survived = bool(src.get(field)) and bool(reparsed.get(field))
        if survived and _declares_unsupported(unsupported, markers):
            lies.append(field)
    assert not lies, (
        f"{name}: declares these field(s) unsupported yet round-trips them "
        f"(render→parse preserves the surface): {lies}.  The matrix lies in "
        f"the dangerous direction — a real migration would be wrongly "
        f"warned/blocked.  Remove the UnsupportedPath or fix the render."
    )


@pytest.mark.parametrize("name", _CODEC_NAMES)
def test_roundtrip_emitted_xpath_not_unsupported(name: str):
    """Walker-grounded render-honesty (review #9, sub-field granularity).

    Render the kitchen-sink, re-parse it, then walk the RE-PARSED intent:
    every xpath that walk yields is one the codec demonstrably emitted and
    read back, so NONE of them may be declared ``unsupported``.  This is
    the same survival-based (false-positive-free) logic as
    :func:`test_rendered_field_not_unsupported` but at the granularity
    ``validate_against`` actually uses, so it also catches a *sub-field*
    lie (e.g. declaring ``/snmp/location`` unsupported while round-tripping
    it) that the top-level whole-field check cannot see."""
    codec = get_codec(name)
    reparsed = codec.parse(codec.render(_maximal_intent()))
    emitted = set(_walk_canonical(reparsed))
    unsupported = {u.path for u in codec.capabilities.unsupported}
    lies = sorted(emitted & unsupported)
    assert not lies, (
        f"{name}: declares these xpath(s) unsupported yet emits + re-parses "
        f"them from a kitchen-sink render: {lies}.  Dangerous-direction lie — "
        f"validate_against would wrongly warn/block a surface the codec "
        f"actually round-trips.  Remove the UnsupportedPath or fix the render."
    )


@pytest.mark.parametrize("name", _CODEC_NAMES)
def test_dropped_naming_independent_field_is_declared(name: str):
    """A naming-independent top-level field that TOTALLY drops on
    render→re-parse must be declared ``unsupported`` or ``lossy`` (review
    #9 follow-up; the 2026-06 adversarial pass showed the walker now SEES
    these surfaces but the dropping codecs hadn't declared them, so
    ``validate_against`` reported ``severity: ok`` while the render
    discarded the data — e.g. RADIUS host + shared secret silently lost).

    Restricted to surfaces whose data carries no vendor-specific names, so
    a total drop is unambiguous and has no false positive (unlike LAG /
    switchport, whose member names can mismatch a vendor and merely *look*
    dropped)."""
    codec = get_codec(name)
    intent = _maximal_intent()
    src = intent.model_dump()
    reparsed = codec.parse(codec.render(intent)).model_dump()
    caps = codec.capabilities
    declared = {u.path for u in caps.unsupported} | {lp.path for lp in caps.lossy}

    gaps = []
    for field, paths in _NAMING_INDEPENDENT_DROP_FIELDS.items():
        if not src.get(field):
            continue
        if reparsed.get(field):
            continue  # survived (whole or partial) — not a total drop
        if not any(p in declared for p in paths):
            gaps.append(field)
    assert not gaps, (
        f"{name}: render totally DROPS these naming-independent surface(s) "
        f"yet the matrix declares none of them unsupported/lossy, so live "
        f"validation reports them 'supported' while the data is discarded: "
        f"{gaps}.  Add an UnsupportedPath (exact walker spelling, e.g. "
        f"/system/syslog-server, /radius-servers/server/key, "
        f"/routing-instances/instance) to the codec's CapabilityMatrix."
    )


@pytest.mark.parametrize("name", _CODEC_NAMES)
def test_no_supported_unsupported_overlap(name: str):
    """No xpath may appear in BOTH supported and unsupported (copy-paste
    drift guard; generalises the per-codec cisco_iosxe check)."""
    caps = get_codec(name).capabilities
    overlap = set(caps.supported) & {u.path for u in caps.unsupported}
    assert not overlap, f"{name}: xpath(s) both supported AND unsupported: {overlap}"


#: Top-level CanonicalIntent fields that are Tier-3 / metadata / provenance —
#: carried through but never a translatable capability surface, so they need
#: no honesty marker.  Everything else MUST have a marker entry.
_NON_CAPABILITY_FIELDS = frozenset({
    "raw_sections", "dropped_tier3_sections",
    "source_vendor", "source_format", "source_version",
    "apply_groups", "group_content",
})


def test_marker_dict_covers_every_data_bearing_field():
    """Guard the guard: every data-bearing top-level CanonicalIntent field
    must have a `_FIELD_TO_UNSUPPORTED_MARKERS` entry, so a NEW field added
    to the model can't silently slip past the rendered-⇒-not-unsupported
    check (the 2026-06 adversarial pass found anycast_gateway_mac /
    interfaces / timezone missing — a rendered-but-declared-unsupported lie
    on them was uncaught)."""
    model_fields = set(CanonicalIntent.model_fields)
    must_have = model_fields - _NON_CAPABILITY_FIELDS
    missing = sorted(must_have - set(_FIELD_TO_UNSUPPORTED_MARKERS))
    assert not missing, (
        f"CanonicalIntent gained data-bearing field(s) with no honesty "
        f"marker: {missing}.  Add each to _FIELD_TO_UNSUPPORTED_MARKERS "
        f"(or to _NON_CAPABILITY_FIELDS if it is Tier-3/metadata)."
    )


def test_maximal_intent_exercises_every_top_level_field():
    """Guard the guard: the kitchen-sink must populate every marked field
    (with real content, not just a truthy empty container), else the
    reverse-parity universe (_WALKABLE) would be too small and the checks
    above would pass vacuously."""
    intent = _maximal_intent()
    dump = intent.model_dump()
    for field in _FIELD_TO_UNSUPPORTED_MARKERS:
        assert dump.get(field), f"_maximal_intent left {field!r} empty"
    # The one model-valued marked field: assert its primary sub-field is
    # populated (an empty CanonicalSNMP() dumps truthy but would gut the
    # /snmp/* walker coverage).
    assert intent.snmp and intent.snmp.community, "_maximal_intent snmp.community empty"
