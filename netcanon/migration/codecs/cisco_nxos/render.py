"""
Render path for Cisco NX-OS (canonical tree → ``show running-config``).

Public function: :func:`render_intent` — :class:`CanonicalIntent` in,
NX-OS CLI text out.

Phase 1 emits the supported subset declared in the capability matrix:
hostname, a synthesised banner / version / ``vdc`` wrapper, render-derived
``feature`` lines, default-VRF static routes, coalesced VLANs (+ names),
``vrf context`` blocks (name + description), and interface stanzas with
description / admin-state / mtu / IPv4 (CIDR) / IPv6 / ``vrf member``.

The render path is deliberately tolerant of canonical surfaces it does
NOT yet emit (switchport / LAG / SNMP / local-users / VRRP / VXLAN /
anycast — all Phase 2+): a cross-vendor source tree carrying those
fields renders cleanly, simply omitting them.  The matrix declares each
omission ``unsupported`` so the migrate-page banner surfaces the gap.

``feature`` lines are render-derived (NOT modelled canonically — see
``03-canonical-mapping.md`` § 5); the ``vdc`` / ``line`` / ``boot``
footers are synthesised defaults so the output is a syntactically-valid
single-VDC NX-OS config even for a cross-vendor source.
"""

from __future__ import annotations

from ...canonical.intent import CanonicalIntent, CanonicalRoutingInstance
from . import port_names as _port_names

#: Synthesised NX-OS release stamped into the banner.  Cosmetic — the
#: parsed ``source_version`` is metadata only and not echoed.
_DEFAULT_VERSION = "9.3(11)"


def render_intent(tree: CanonicalIntent) -> str:
    """Render a :class:`CanonicalIntent` as Cisco NX-OS config text."""
    hostname = tree.hostname or "switch"
    lines: list[str] = []

    # ── Banner / version / vdc wrapper ──
    lines.append("!Command: show running-config")
    lines.append("")
    lines.append(f"version {_DEFAULT_VERSION} Bios:version")
    lines.append(f"hostname {hostname}")
    lines.append(f"vdc {hostname} id 1")
    lines.append("")

    # ── Render-derived feature block ──
    for feat in _derive_features(tree):
        lines.append(f"feature {feat}")
    if _derive_features(tree):
        lines.append("")

    # ── Static routes (default VRF only) ──
    default_vrf_routes = [r for r in tree.static_routes if not r.vrf]
    for route in default_vrf_routes:
        lines.append(_render_static_route(route))
    if default_vrf_routes:
        lines.append("")

    # ── VLANs (coalesced id-list + per-name stanzas) ──
    if tree.vlans:
        ids = sorted({v.id for v in tree.vlans})
        lines.append(f"vlan {_coalesce_vlan_ids(ids)}")
        for v in sorted(tree.vlans, key=lambda x: x.id):
            if v.name:
                lines.append(f"vlan {v.id}")
                lines.append(f"  name {v.name}")
        lines.append("")

    # ── VRF contexts (name + description) ──
    # Emit in tree order (= source order on a same-vendor round-trip).
    # The round-trip invariant does NOT normalise routing_instances
    # ordering, so re-sorting here would register as canonical drift.
    if tree.routing_instances:
        for ri in tree.routing_instances:
            lines.extend(_render_vrf_context(ri))
        lines.append("")

    # ── Interfaces (NX-OS sort order) ──
    for iface in _sort_interfaces_nxos(tree.interfaces):
        lines.extend(_render_interface(iface))

    # ── Footers (synthesised defaults) ──
    lines.append("line console")
    lines.append("line vty")
    lines.append(f"boot nxos bootflash:/nxos.{_DEFAULT_VERSION}.bin")

    return "\n".join(lines) + "\n"


def _derive_features(tree: CanonicalIntent) -> list[str]:
    """Return the sorted ``feature`` list Phase 1 must emit.

    Phase 1 only renders one feature-gated surface: SVIs require
    ``feature interface-vlan``.  LAG / HSRP / VXLAN / anycast features
    are derived in later phases when their render paths land.
    """
    features: set[str] = set()
    if any(_is_svi(i.name) for i in tree.interfaces):
        features.add("interface-vlan")
    return sorted(features)


def _is_svi(name: str) -> bool:
    return _port_names.classify_port_name(name).kind == "svi"


def _render_static_route(route) -> str:
    """Render one default-VRF static route as ``ip route DEST/N GW [pref]``.

    ``destination`` is already CIDR (``X/N``).  Next-hop is the gateway
    IP, or the interface name for a directly-attached next-hop.  A
    non-zero ``metric`` re-emits as the trailing preference token.
    """
    nexthop = route.gateway or route.interface
    out = f"ip route {route.destination} {nexthop}".rstrip()
    if route.metric:
        out += f" {route.metric}"
    return out


def _render_vrf_context(ri: CanonicalRoutingInstance) -> list[str]:
    """Render a ``vrf context <name>`` block (name + description).

    Phase 1 emits the description only; RD / route-target / vni land in
    later phases.
    """
    block = [f"vrf context {ri.name}"]
    if ri.description:
        block.append(f"  description {ri.description}")
    return block


def _render_interface(iface) -> list[str]:
    """Render one interface stanza.

    Emits ``vrf member`` BEFORE ``ip address`` (NX-OS wipes addressing
    when the VRF binding changes, so VRF must come first) and uses the
    CIDR address form throughout.
    """
    block = [f"interface {iface.name}"]
    if iface.description:
        block.append(f"  description {iface.description}")
    if not iface.enabled:
        block.append("  shutdown")
    else:
        block.append("  no shutdown")
    if iface.mtu is not None:
        block.append(f"  mtu {iface.mtu}")
    if iface.vrf:
        block.append(f"  vrf member {iface.vrf}")
    for addr in iface.ipv4_addresses:
        line = f"  ip address {addr.ip}/{addr.prefix_length}"
        if addr.is_secondary:
            line += " secondary"
        block.append(line)
    for addr in iface.ipv6_addresses:
        block.append(f"  ipv6 address {addr.ip}/{addr.prefix_length}")
    return block


def _coalesce_vlan_ids(ids: list[int]) -> str:
    """Coalesce a sorted, de-duplicated VLAN-id list into NX-OS form.

    ``[1, 10, 11, 12, 20]`` → ``"1,10-12,20"``.  Consecutive runs of
    three or more collapse to ``lo-hi``; the inverse of
    :func:`parse._parse_vlan_list` so the id-list round-trips.
    """
    if not ids:
        return ""
    parts: list[str] = []
    run_start = prev = ids[0]
    for vid in ids[1:]:
        if vid == prev + 1:
            prev = vid
            continue
        parts.append(_run_token(run_start, prev))
        run_start = prev = vid
    parts.append(_run_token(run_start, prev))
    return ",".join(parts)


def _run_token(lo: int, hi: int) -> str:
    """Format a single run for :func:`_coalesce_vlan_ids`.

    A two-wide run (``10,11``) stays comma-separated rather than
    ``10-11`` — both re-parse identically, but the comma form matches
    NX-OS show-output convention for adjacent pairs.
    """
    if hi == lo:
        return str(lo)
    if hi == lo + 1:
        return f"{lo},{hi}"
    return f"{lo}-{hi}"


#: Interface-kind render order (``02-codec-architecture.md`` § 4.1):
#: SVIs, then the VTEP, then physical Ethernet, then port-channels, then
#: the mgmt port, then loopbacks.  Unknown kinds sort last.
_KIND_ORDER: dict[str, int] = {
    "svi": 0,
    "vtep": 1,
    "physical": 2,
    "breakout": 2,
    "lag": 3,
    "mgmt": 4,
    "loopback": 5,
}


def _sort_interfaces_nxos(interfaces: list):
    """Return *interfaces* in NX-OS show-output order.

    Keys off ``classify_port_name(name).kind`` then the numeric index so
    round-tripped output mirrors a real capture's ordering.  Ordering is
    cosmetic — the round-trip invariant compares canonical meaning, not
    text — but matching the device makes diffs reviewable.
    """
    def _key(iface):
        ident = _port_names.classify_port_name(iface.name)
        kind_rank = _KIND_ORDER.get(ident.kind, 99)
        # Build a numeric tuple from whatever positional fields the
        # identity carries so e.g. Ethernet1/2 sorts before Ethernet1/10.
        nums = (
            ident.stack or 0,
            ident.module or 0,
            ident.port or 0,
            ident.index or 0,
        )
        return (kind_rank, nums, iface.name)

    return sorted(interfaces, key=_key)
