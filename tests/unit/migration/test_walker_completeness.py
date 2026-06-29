"""Forward completeness guard for the migration walker (silent capability-loss
class — blind-audit meta-finding, ``docs/reviews/2026-06-24-fail-surfaced-defaults``).

THE CLASS (not an instance): ``_walk_canonical`` yields a *subset* of the
canonical model's leaves, and ``classify()`` defaults any *unwalked* leaf to
``supported`` — so a codec that silently drops that field on render reports
``severity: ok``. Five blind-audit rounds each found a NEW instance of this same
class (switchport -> static-route -> VXLAN -> VLAN port-membership #172 ->
VLAN-SVI L3 #175). Point-fixes don't converge.

THE DURABLE FIX (fail-surfaced default): this guard enumerates EVERY scalar leaf
reachable from ``CanonicalIntent`` (recursing into nested models — the two prior
forward-coverage checks stop at top-level ``CanonicalIntent`` fields and never
recurse, which is exactly the hole) and FAILS when a leaf is neither walked nor
in a self-justifying exemption set. A NEW leaf added without a walker yield now
turns CI **red** instead of silently classifying ``supported`` — the default
flips from "silently fine" to "surfaced." This is a CI test: **zero runtime
change, zero phase4 movement** (``classify()``/phase4 do not consume this guard).

WALKED-NESS is derived, not hand-listed per leaf: a leaf ``(Class, field)`` is
"walked" iff the walker emits an xpath equal to one of the leaf's *expected*
xpaths — its class container prefix(es) + the field's segment spelling. This is
robust against a same-named NEW field (e.g. a new ``CanonicalInterface.ip`` does
NOT match the nested ``/interfaces/interface/ipv4/address/ip``, because the
expected ``/interfaces/interface/ip`` is not emitted) — a plain suffix match
would have that class-kill hole. The container map (~16 rows) + segment overrides
(~7 rows) are guarded against typos/staleness below, and the derivation is
verified exhaustively against the live walker by ``_walked_leaves``.

DEFERRED (tracked here as ``KNOWN_GAP`` exemptions, NOT fixed in this run): the
~11 HIGH-value currently-unwalked leaves (VRRP mode/priority/preempt/adv-int/
auth/v6-VIP, SNMPv3 priv-passphrase/protocols/group, IPv6 scope,
routing-instance instance-type). Actually *walking* them is behaviour-changing +
phase4-regen work (the St3-anycast precedent broke a ``tests/unit/audit`` test),
so it is a separate per-surface follow-up. The guard makes every deferral a
visible, greppable ``KNOWN_GAP`` line rather than an invisible silent loss.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.canonical.xpath_walker import _walk_canonical
from tests.support.canonical_reflection import scalar_leaves

# Reuse the established kitchen-sink that populates every conditionally-walked
# surface (the same one that builds the reverse-parity _WALKABLE universe), so
# "what xpaths CAN the walker emit" is computed from one source of truth.
from tests.unit.migration.test_registry_capability_honesty import _maximal_intent

pytestmark = pytest.mark.unit


#: Every xpath the shared walker emits when every surface is populated.
_WALKABLE = frozenset(_walk_canonical(_maximal_intent()))

#: Per-class xpath container prefix(es). A leaf's expected xpath is
#: ``container + segment``; a leaf is "walked" iff any expected xpath is in
#: ``_WALKABLE``. Two prefixes where a class is mounted under two trees
#: (CanonicalIPv4Address: interface + VLAN-SVI) or where some fields sit under a
#: ``config/`` sub-segment (CanonicalInterface). An EMPTY tuple means only the
#: container *anchor* is walked, not its sub-leaves (DHCP pool / EVPN-Type5
#: route) — so all that class's sub-leaves resolve to not-walked and must be
#: exempt. Guarded against typos by ``test_class_containers_have_no_dead_prefixes``.
_CLASS_CONTAINERS: dict[str, tuple[str, ...]] = {
    "CanonicalIntent": ("/system/", "/"),
    "CanonicalInterface": (
        "/interfaces/interface/",
        "/interfaces/interface/config/",
    ),
    "CanonicalIPv4Address": (
        "/interfaces/interface/ipv4/address/",
        "/vlans/vlan/ipv4/address/",
    ),
    "CanonicalIPv6Address": ("/interfaces/interface/ipv6/address/",),
    "CanonicalVlan": ("/vlans/vlan/",),
    "CanonicalVRRPGroup": ("/interfaces/interface/vrrp-groups/group/",),
    "CanonicalStaticRoute": ("/routing/static-route/",),
    "CanonicalSNMP": ("/snmp/",),
    "CanonicalSNMPv3User": ("/snmp/v3-user/",),
    "CanonicalLAG": ("/lags/lag/",),
    "CanonicalLocalUser": ("/local-users/user/",),
    "CanonicalRADIUSServer": ("/radius-servers/server/",),
    "CanonicalVxlan": ("/vxlan-vnis/",),
    "CanonicalRoutingInstance": ("/routing-instances/instance/",),
    # Anchor-only (sub-leaves not walked -> all exempt below):
    "CanonicalDHCPPool": (),
    "CanonicalEvpnType5Route": (),
}

#: Leaves ``(Model, field)`` that must be walked on EVERY mount of their class,
#: not just one.  Only ``CanonicalIPv4Address``'s INDEPENDENT-loss sub-fields
#: qualify: each is mounted on BOTH ``/interfaces/interface/ipv4/address/`` and
#: ``/vlans/vlan/ipv4/address/``, and the interface-mount walk previously MASKED
#: the silent VLAN-SVI sub-field drop — a leaf walked on the interface mount
#: counted as "covered" so the VLAN-SVI gap was structurally invisible to this
#: guard (blind-audit f92e97a T0-2; the meta-finding that "the fix-the-class
#: guard inherited the class's own blind spot").  ``ip`` is already walked on
#: both mounts and ``prefix_length`` travels with it (no independent loss), so
#: both stay on the default any()-over-mounts test — as does every class whose
#: multiple _CLASS_CONTAINERS prefixes are segment ALTERNATIVES (CanonicalIntent
#: /system/ vs /; CanonicalInterface /…/ vs /…/config/), where a field lives
#: under exactly one prefix.
_ALL_MOUNTS_REQUIRED: frozenset[tuple[str, str]] = frozenset({
    ("CanonicalIPv4Address", "is_secondary"),
    ("CanonicalIPv4Address", "virtual_gateway_address"),
    ("CanonicalIPv4Address", "virtual_gateway_mac"),
})

#: Field-name -> xpath-segment overrides where the walker's spelling diverges
#: from ``field.replace("_", "-")`` (singularised list fields; two renames).
#: Guarded against staleness by ``test_segment_overrides_reference_real_leaves``.
_SEGMENT_OVERRIDE: dict[tuple[str, str], str] = {
    ("CanonicalIntent", "dns_servers"): "dns-server",
    ("CanonicalIntent", "ntp_servers"): "ntp-server",
    ("CanonicalIntent", "syslog_servers"): "syslog-server",
    ("CanonicalSNMP", "trap_hosts"): "trap-host",
    ("CanonicalInterface", "interface_type"): "type",
    ("CanonicalIPv4Address", "is_secondary"): "secondary-ip",
    ("CanonicalIPv6Address", "is_secondary"): "secondary-ip",
}

#: Structured reason codes (no free text "I didn't want to walk this" door).
#: METADATA               provenance / notification surface, never a config leaf
#: TRANSFORM_HINT         render mechanism, not an operator fidelity surface
#: DISCRIMINATOR_TRAVELS  identity that travels with its walked container anchor
#: ENVELOPE_AUDIT_BACKSTOPPED  sub-leaf of a walked envelope; the offline
#:                        cross-mesh model_dump audit catches its loss (the live
#:                        migrate-report is blind, but the audit is not)
#: KNOWN_GAP              a REAL currently-silent loss this guard surfaces;
#:                        deferred to a per-surface walk-expansion follow-up
_REASON_CODES = frozenset({
    "METADATA",
    "TRANSFORM_HINT",
    "DISCRIMINATOR_TRAVELS",
    "ENVELOPE_AUDIT_BACKSTOPPED",
    "KNOWN_GAP",
})

#: Leaves the guard does NOT require to be walked, each (code, note). Adding an
#: entry is a visible, reviewable act with a code a reviewer can challenge — a
#: BGP-peer-IP-class leaf has no honest code here (modelled on #149's
#: predicate-based self-justifying exemptions).
_WALK_EXEMPT: dict[tuple[str, str], tuple[str, str]] = {
    # ── Provenance / notification metadata (never a translatable surface) ──
    ("CanonicalIntent", "source_vendor"): ("METADATA", "codec that produced the tree"),
    ("CanonicalIntent", "source_format"): ("METADATA", "source input_format hint"),
    ("CanonicalIntent", "source_version"): ("METADATA", "source OS-version hint"),
    ("CanonicalIntent", "raw_sections"): ("METADATA", "Tier-3 verbatim blob; own banner, never auto-rendered"),
    ("CanonicalIntent", "dropped_tier3_sections"): ("METADATA", "notification-only; own migrate banner"),
    ("CanonicalIntent", "apply_groups"): ("METADATA", "Junos apply-groups provenance hint"),
    ("CanonicalIntent", "group_content"): ("METADATA", "Junos group-body provenance"),
    # ── Transform hints / render mechanics (not operator-visible fidelity) ──
    ("CanonicalInterface", "kind"): ("TRANSFORM_HINT", "rename-mesh hint, not a render surface"),
    ("CanonicalInterface", "default_name"): ("TRANSFORM_HINT", "MikroTik factory-name render mechanism"),
    # ── Identity discriminators that travel with their walked anchor ──
    ("CanonicalVRRPGroup", "group_id"): ("DISCRIMINATOR_TRAVELS", "/vrrp-groups/group anchor keyed by it"),
    ("CanonicalSNMPv3User", "name"): ("DISCRIMINATOR_TRAVELS", "/snmp/v3-user anchor keyed by it"),
    ("CanonicalStaticRoute", "destination"): ("DISCRIMINATOR_TRAVELS", "/routing/static-route anchor is the dest"),
    # ── Envelope-covered sub-leaves: anchor walked; loss caught by the offline
    #    cross-mesh model_dump audit (live migrate-report blind, audit is not) ──
    ("CanonicalDHCPPool", "network"): ("ENVELOPE_AUDIT_BACKSTOPPED", "/dhcp-servers/pool envelope walked"),
    ("CanonicalDHCPPool", "start_ip"): ("ENVELOPE_AUDIT_BACKSTOPPED", "DHCP pool option; audit-backstopped"),
    ("CanonicalDHCPPool", "end_ip"): ("ENVELOPE_AUDIT_BACKSTOPPED", "DHCP pool option; audit-backstopped"),
    ("CanonicalDHCPPool", "gateway"): ("ENVELOPE_AUDIT_BACKSTOPPED", "DHCP pool option; audit-backstopped"),
    ("CanonicalDHCPPool", "dns_servers"): ("ENVELOPE_AUDIT_BACKSTOPPED", "DHCP pool option; audit-backstopped"),
    ("CanonicalDHCPPool", "lease_time"): ("ENVELOPE_AUDIT_BACKSTOPPED", "DHCP pool option; audit-backstopped"),
    ("CanonicalDHCPPool", "domain_name"): ("ENVELOPE_AUDIT_BACKSTOPPED", "DHCP pool option; audit-backstopped"),
    ("CanonicalDHCPPool", "interface"): ("ENVELOPE_AUDIT_BACKSTOPPED", "DHCP pool bind-iface; audit-backstopped"),
    ("CanonicalEvpnType5Route", "vrf"): ("ENVELOPE_AUDIT_BACKSTOPPED", "/evpn-type5-routes/route envelope walked"),
    ("CanonicalEvpnType5Route", "prefix"): ("ENVELOPE_AUDIT_BACKSTOPPED", "EVPN-Type5 sub-leaf; audit-backstopped"),
    ("CanonicalEvpnType5Route", "rt_imports"): ("ENVELOPE_AUDIT_BACKSTOPPED", "EVPN-Type5 sub-leaf; audit-backstopped"),
    ("CanonicalEvpnType5Route", "rt_exports"): ("ENVELOPE_AUDIT_BACKSTOPPED", "EVPN-Type5 sub-leaf; audit-backstopped"),
    ("CanonicalRADIUSServer", "auth_port"): ("ENVELOPE_AUDIT_BACKSTOPPED", "defaulted 1812; non-default backstopped"),
    ("CanonicalRADIUSServer", "acct_port"): ("ENVELOPE_AUDIT_BACKSTOPPED", "defaulted 1813; non-default backstopped"),
    # ── KNOWN_GAP: real currently-silent losses, deferred to walk-expansion ──
    ("CanonicalIPv6Address", "scope"): ("KNOWN_GAP", "link-local discriminator not walked; PR-2"),
    ("CanonicalRoutingInstance", "instance_type"): ("KNOWN_GAP", "mac-vrf vs vrf not walked; PR-2"),
    ("CanonicalStaticRoute", "gateway"): ("KNOWN_GAP", "next-hop not walked; PR-2"),
}


def _expected_xpaths(cls: str, field: str) -> tuple[str, ...]:
    """The xpath(s) the walker is expected to emit for leaf ``(cls, field)``,
    or ``()`` if the leaf's class is anchor-only / unknown (-> not walked)."""
    containers = _CLASS_CONTAINERS.get(cls)
    if not containers:
        return ()
    seg = _SEGMENT_OVERRIDE.get((cls, field), field.replace("_", "-"))
    return tuple(c + seg for c in containers)


def _walked_leaves() -> set[tuple[str, str]]:
    """Every scalar leaf whose expected xpath the walker actually emits.

    A leaf in ``_ALL_MOUNTS_REQUIRED`` counts as walked only when EVERY mount
    is walked (``all``): a leaf walked on one mount must not mask a silent drop
    on another (blind-audit f92e97a T0-2).  For every other leaf the multiple
    container prefixes are segment alternatives (or the leaf travels with a
    base that is walked on every mount), so any one walked prefix suffices
    (``any``).
    """
    out: set[tuple[str, str]] = set()
    for leaf in scalar_leaves(CanonicalIntent):
        expected = _expected_xpaths(*leaf)
        if not expected:
            continue
        combine = all if leaf in _ALL_MOUNTS_REQUIRED else any
        if combine(xp in _WALKABLE for xp in expected):
            out.add(leaf)
    return out


# ---------------------------------------------------------------------------
# The class-kill: every model leaf is walked OR self-justifyingly exempt
# ---------------------------------------------------------------------------


def test_every_model_leaf_is_walked_or_exempt():
    """Every data-bearing scalar leaf reachable from CanonicalIntent (recursing
    into nested models) is either emitted by ``_walk_canonical`` (so the live
    validation report can classify it) OR carries a written, reason-coded
    exemption. A NEW leaf added without a walker yield + per-codec declaration
    turns this RED instead of silently classifying ``supported`` (the class kill).
    """
    walked = _walked_leaves()
    unhandled = sorted(
        leaf
        for leaf in scalar_leaves(CanonicalIntent)
        if leaf not in walked and leaf not in _WALK_EXEMPT
    )
    assert not unhandled, (
        "Canonical model leaf/leaves are neither walked by _walk_canonical nor "
        "exempt — they would silently classify 'supported' and any codec dropping "
        "them reports severity:ok (the silent capability-loss class). For each: "
        "(1) add a yield in _walk_canonical + the per-codec lossy/unsupported "
        "declaration (and, if its xpath spelling is irregular, a _CLASS_CONTAINERS "
        "/ _SEGMENT_OVERRIDE row), OR (2) add a self-justifying _WALK_EXEMPT entry "
        f"with a structured reason code: {unhandled}"
    )


# ---------------------------------------------------------------------------
# Guard-the-guard: keep the derivation + exemption set honest
# ---------------------------------------------------------------------------


def test_no_stale_walk_exemptions():
    """Every _WALK_EXEMPT key is still a real model leaf — a removed/renamed
    leaf must drop out of the exemption set, else the exemption rots into a lie."""
    real = scalar_leaves(CanonicalIntent)
    stale = sorted(k for k in _WALK_EXEMPT if k not in real)
    assert not stale, f"_WALK_EXEMPT references non-existent leaves: {stale}"


def test_walk_exempt_is_not_actually_walked():
    """A leaf that IS walked must NOT also be exempt — a stale exemption on a
    now-walked leaf hides intent and would mask a future un-walking regression."""
    both = sorted(set(_WALK_EXEMPT) & _walked_leaves())
    assert not both, f"leaves both walked AND exempt (drop the exemption): {both}"


def test_exemption_reasons_are_structured_codes():
    """Every exemption carries one of the closed reason codes — no free-text
    'I didn't want to walk this' door (the lazy-exempt path has no green code)."""
    bad = sorted(
        f"{c}.{f} -> {code!r}"
        for (c, f), (code, _note) in _WALK_EXEMPT.items()
        if code not in _REASON_CODES
    )
    assert not bad, f"exemption(s) with an unknown reason code: {bad}"


def test_class_containers_have_no_dead_prefixes():
    """Every non-empty container prefix is a real prefix of some walkable xpath
    — a typo'd prefix would silently mark its class's leaves not-walked."""
    dead = sorted(
        f"{cls}: {c!r}"
        for cls, cs in _CLASS_CONTAINERS.items()
        for c in cs
        if not any(xp.startswith(c) for xp in _WALKABLE)
    )
    assert not dead, f"_CLASS_CONTAINERS prefix(es) match no walkable xpath: {dead}"


def test_segment_overrides_reference_real_leaves():
    """Every _SEGMENT_OVERRIDE key is a real leaf AND resolves to a walked xpath
    (else the override is stale/wrong)."""
    real = scalar_leaves(CanonicalIntent)
    stale = sorted(k for k in _SEGMENT_OVERRIDE if k not in real)
    assert not stale, f"_SEGMENT_OVERRIDE references non-existent leaves: {stale}"
    unwalked = sorted(
        k for k in _SEGMENT_OVERRIDE
        if not any(xp in _WALKABLE for xp in _expected_xpaths(*k))
    )
    assert not unwalked, (
        f"_SEGMENT_OVERRIDE entries that don't resolve to a walked xpath "
        f"(wrong segment spelling?): {unwalked}"
    )


def test_guard_catches_a_synthetic_new_leaf():
    """Prove the class-kill (not just green-today): a synthetic leaf that is
    neither walked nor exempt IS flagged by the guard's logic. This pins that a
    future refactor can't make the main guard pass vacuously."""
    synthetic = ("CanonicalInterface", "synthetic_unwalked_field")
    walked = _walked_leaves()
    assert synthetic not in walked
    assert synthetic not in _WALK_EXEMPT
    leaves = scalar_leaves(CanonicalIntent) | {synthetic}
    unhandled = [lf for lf in leaves if lf not in walked and lf not in _WALK_EXEMPT]
    assert synthetic in unhandled, (
        "the guard would NOT flag a new unwalked leaf — the class-kill is broken"
    )


def test_guard_is_robust_to_a_same_named_new_leaf():
    """A NEW field whose name collides with a walked segment elsewhere (e.g. a
    bare ``ip`` on CanonicalInterface, colliding with the nested address ``ip``)
    must NOT be falsely classified walked — the container-scoped derivation
    prevents the suffix-match class-kill hole."""
    collision = ("CanonicalInterface", "ip")  # expects /interfaces/interface/ip
    assert not any(xp in _WALKABLE for xp in _expected_xpaths(*collision)), (
        "a same-named new leaf falsely matched a walked xpath — class-kill hole "
        "(the nested /interfaces/interface/ipv4/address/ip must NOT count as "
        "/interfaces/interface/ip)"
    )


def test_every_class_with_leaves_is_known():
    """Every model class that owns a scalar leaf is in _CLASS_CONTAINERS (even
    if anchor-only with an empty tuple) — a NEW model class hung off the tree
    without a container entry would otherwise silently resolve all its leaves to
    not-walked-but-also-unmapped; this makes adding a class a conscious act."""
    classes = {cls for cls, _ in scalar_leaves(CanonicalIntent)}
    missing = sorted(classes - set(_CLASS_CONTAINERS))
    assert not missing, (
        "model class(es) own canonical leaves but have no _CLASS_CONTAINERS entry "
        "— add one (use an empty tuple () if only the container anchor is walked): "
        f"{missing}"
    )
