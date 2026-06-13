"""
Render path for Cisco IOS-XR (canonical tree → ``show running-config``).

Public function: :func:`render_intent` — :class:`CanonicalIntent` in,
IOS-XR CLI text out.

Phase 1 emits a synthesised ``!! IOS XR Configuration`` banner, hostname,
domain, interface stanzas (description / admin-state / mtu / IPv4
dotted-mask / IPv6 CIDR), a ``router static`` block (default VRF), and
the closing ``end``.

Phase 2 (this commit) adds: local-user blocks; top-level ``vrf <name>``
stanzas (description + ``address-family ipv4 unicast`` with import/export
route-target blocks); a minimal ``router bgp <asn> / vrf <name> / rd
<rd>`` block that carries the per-VRF route-distinguishers (IOS-XR keeps
the RD in the BGP process, not the ``vrf`` stanza); per-interface ``vrf
<name>`` membership; ``bundle id <N> mode <m>`` on Bundle-Ether members;
per-VRF static routes (``router static / vrf <name>``); and
``encapsulation dot1q <vid>`` on sub-interfaces.

The render path stays deliberately tolerant of canonical surfaces it
does NOT emit (anycast-gateway, VXLAN, SP-routing protocols beyond the
RD carrier) — a cross-vendor source tree carrying those fields renders
cleanly, simply omitting them.  The matrix declares each omission
``unsupported`` so the migrate-page banner surfaces the gap.

Per ``02-codec-architecture.md`` no ``commit`` line is emitted — the
output matches ``show running-config`` shape, which is what operators
consume.

The emitted ``router bgp`` block is a minimal RD carrier: its ASN is
derived from the first route-distinguisher's administrator field (the
near-universal ``<asn>:<nn>`` convention) so a same-vendor round-trip
re-detects the identical ``router bgp <asn>`` Tier-3 header.  The full
BGP grammar (neighbors, address-families, policies) stays unsupported.
"""

from __future__ import annotations

import ipaddress
import re

from ...canonical.intent import CanonicalIntent, CanonicalRoutingInstance
from ..base import RenderError
from . import port_names as _port_names

#: Synthesised IOS-XR release stamped into the banner.  Cosmetic — the
#: parsed ``source_version`` is metadata only and not echoed (mirrors the
#: cisco_nxos render convention).
_DEFAULT_VERSION = "6.6.2"

#: Canonical LAG mode → IOS-XR ``bundle id ... mode`` keyword (inverse of
#: parse._IOSXR_LAG_MODE_MAP; canonical ``static`` → XR ``on``).
_CANON_TO_IOSXR_BUNDLE_MODE = {
    "active": "active",
    "passive": "passive",
    "static": "on",
}

#: Fallback BGP ASN when no route-distinguisher exposes a numeric
#: administrator field (e.g. all RDs are IP-based ``<ip>:<nn>``).
_FALLBACK_BGP_ASN = "65000"


def _prefix_to_mask(prefix: int) -> str:
    """Convert a CIDR prefix length to a dotted-decimal subnet mask.

    Forked from ``cisco_iosxe_cli.render._prefix_to_mask`` (render-only,
    small enough to duplicate per the architecture doc).  IOS-XR's
    ``ipv4 address X Y`` form requires the dotted mask; the canonical
    tree holds prefix lengths, so we expand on render.
    """
    if not (0 <= prefix <= 32):
        raise RenderError(
            f"cisco_iosxr: prefix length {prefix} out of range",
            yang_path="/interfaces/interface/ipv4/address/prefix-length",
        )
    mask_int = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF if prefix else 0
    return str(ipaddress.IPv4Address(mask_int))


def render_intent(tree: CanonicalIntent) -> str:
    """Render a :class:`CanonicalIntent` as Cisco IOS-XR config text."""
    hostname = tree.hostname or "Router"
    lines: list[str] = []

    # ── Banner ──
    lines.append(f"!! IOS XR Configuration {_DEFAULT_VERSION}")
    lines.append("!")
    lines.append(f"hostname {hostname}")
    if tree.domain:
        lines.append(f"domain name {tree.domain}")
    lines.append("!")

    # ── Local users (Phase 2) ──
    for user in tree.local_users:
        lines.extend(_render_local_user(user))

    # ── VRF stanzas (Phase 2) — emit in tree order so a same-vendor
    # round-trip preserves routing_instances ordering (the round-trip
    # invariant does NOT normalise that list). ──
    for ri in tree.routing_instances:
        lines.extend(_render_vrf(ri))

    # ── Interfaces (XR show-output-ish order) ──
    vlan_ids = {v.id for v in tree.vlans}
    lag_mode_by_name = {lag.name: lag.mode for lag in tree.lags}
    for iface in _sort_interfaces_iosxr(tree.interfaces):
        lines.extend(_render_interface(iface, vlan_ids, lag_mode_by_name))

    # ── Static routes (default VRF + per-VRF) ──
    lines.extend(_render_router_static(tree.static_routes))

    # ── router bgp — minimal per-VRF RD carrier (Phase 2) ──
    lines.extend(_render_bgp_rd(tree.routing_instances))

    # ── Footer ──
    lines.append("end")

    return "\n".join(lines) + "\n"


def _render_local_user(user) -> list[str]:
    """Render one ``username`` block.

    Emits ``group <role>`` (the verbatim IOS-XR task-group, or one derived
    from the privilege level for a cross-vendor source) and ``secret
    <type> <hash>``.  The hash is preserved with its type-digit prefix
    (parse stored ``10 $6$...``); a bare value renders as the type-0
    (plaintext-marker) form.
    """
    role = user.role or (
        "root-lr" if user.privilege_level >= 15 else "operator"
    )
    block = [f"username {user.name}", f" group {role}"]
    if user.hashed_password:
        parts = user.hashed_password.split(" ", 1)
        if len(parts) == 2 and parts[0].isdigit() and len(parts[0]) <= 2:
            htype, payload = parts[0], parts[1]
        else:
            htype, payload = "0", user.hashed_password
        block.append(f" secret {htype} {payload}")
    block.append("!")
    return block


def _render_vrf(ri: CanonicalRoutingInstance) -> list[str]:
    """Render one top-level ``vrf <name>`` stanza.

    Emits ``description`` and, when the VRF carries route-targets, an
    ``address-family ipv4 unicast`` sub-block with ``import route-target``
    / ``export route-target`` blocks (each RT on its own line, ``!``-
    terminated — the IOS-XR shape).  The ``route_distinguisher`` is NOT
    emitted here; it lives in the ``router bgp`` block (see
    :func:`_render_bgp_rd`).  ``l3_vni`` is ignored — IOS-XR EVPN is a
    Tier-3 ``l2vpn`` / ``evpn`` surface the codec does not model.
    """
    block = [f"vrf {ri.name}"]
    if ri.description:
        block.append(f" description {ri.description}")
    if ri.rt_imports or ri.rt_exports:
        block.append(" address-family ipv4 unicast")
        if ri.rt_imports:
            block.append("  import route-target")
            for rt in ri.rt_imports:
                block.append(f"   {rt}")
            block.append("  !")
        if ri.rt_exports:
            block.append("  export route-target")
            for rt in ri.rt_exports:
                block.append(f"   {rt}")
            block.append("  !")
        block.append(" !")
    block.append("!")
    return block


def _derive_bgp_asn(instances: list[CanonicalRoutingInstance]) -> str:
    """Pick the BGP ASN for the RD-carrier block from the RDs themselves.

    Uses the first route-distinguisher whose administrator field is a
    plain integer (the ``<asn>:<nn>`` convention, where the administrator
    equals the BGP ASN in virtually every real deployment).  Falls back
    to :data:`_FALLBACK_BGP_ASN` when every RD is IP-based
    (``<ip>:<nn>``).  Deriving rather than storing keeps the BGP ASN out
    of the canonical schema while letting a same-vendor round-trip
    reproduce the ``router bgp <asn>`` header.
    """
    for ri in instances:
        if ri.route_distinguisher:
            admin = ri.route_distinguisher.split(":")[0]
            if admin.isdigit():
                return admin
    return _FALLBACK_BGP_ASN


def _render_bgp_rd(instances: list[CanonicalRoutingInstance]) -> list[str]:
    """Render the minimal ``router bgp`` block carrying per-VRF RDs.

    IOS-XR stores the route-distinguisher under ``router bgp <asn> / vrf
    <name> / rd <rd>``, not in the ``vrf`` stanza — so the RD only
    round-trips when this block is emitted.  Returns an empty list when
    no routing-instance carries an RD (an XR source with no ``router
    bgp`` keeps ``route_distinguisher=''``; declared lossy in the matrix).
    Instances are emitted in tree order to keep the round-trip stable.
    """
    with_rd = [ri for ri in instances if ri.route_distinguisher]
    if not with_rd:
        return []
    asn = _derive_bgp_asn(with_rd)
    block = [f"router bgp {asn}"]
    for ri in with_rd:
        block.append(f" vrf {ri.name}")
        block.append(f"  rd {ri.route_distinguisher}")
        block.append("  address-family ipv4 unicast")
        block.append("  !")
        block.append(" !")
    block.append("!")
    return block


def _static_route_line(route) -> str:
    """Format one static-route leaf: ``<dest> [<interface>] [<gateway>]``.

    Empty components drop out (interface-only for ``Null0`` / blackhole;
    gateway-only for a plain next-hop).
    """
    nexthop = " ".join(t for t in (route.interface, route.gateway) if t)
    return f"{route.destination} {nexthop}".rstrip()


def _render_router_static(routes: list) -> list[str]:
    """Render the ``router static`` block (default VRF + per-VRF).

    Default-VRF routes sit under ``address-family ipv4 unicast``; per-VRF
    routes (``CanonicalStaticRoute.vrf`` set) nest under ``vrf <name> /
    address-family ipv4 unicast``.  Per-VRF groups are emitted in
    first-seen order; the round-trip harness compares routes id-sorted by
    destination, so cosmetic ordering doesn't register as drift.
    """
    default_routes = [r for r in routes if not r.vrf]
    vrf_routes: dict[str, list] = {}
    for r in routes:
        if r.vrf:
            vrf_routes.setdefault(r.vrf, []).append(r)
    if not default_routes and not vrf_routes:
        return []

    out = ["router static"]
    if default_routes:
        out.append(" address-family ipv4 unicast")
        for r in default_routes:
            out.append(f"  {_static_route_line(r)}")
        out.append(" !")
    for vrf_name, vroutes in vrf_routes.items():
        out.append(f" vrf {vrf_name}")
        out.append("  address-family ipv4 unicast")
        for r in vroutes:
            out.append(f"   {_static_route_line(r)}")
        out.append("  !")
        out.append(" !")
    out.append("!")
    return out


def _render_interface(iface, vlan_ids: set, lag_mode_by_name: dict) -> list[str]:
    """Render one ``interface <name>`` stanza (``!``-terminated).

    IPv4 emits the dotted-mask form (``ipv4 address X Y``); IPv6 emits
    CIDR.  ``vrf <name>`` precedes the addresses (changing a VRF wipes the
    IP on a real box).  A sub-interface (name contains ``.``) re-emits
    ``encapsulation dot1q <unit>`` when its unit number matches a
    synthesised VLAN id — the near-universal unit==tag convention; a
    sub-interface whose dot1q tag differs from its unit re-emits the unit
    (lossy, operator-visible).  Bundle members re-emit ``bundle id <N>
    mode <m>``.  Sub-commands are single-space indented per XR convention.
    """
    block = [f"interface {iface.name}"]
    if iface.description:
        block.append(f" description {iface.description}")
    if not iface.enabled:
        block.append(" shutdown")
    if iface.mtu is not None:
        block.append(f" mtu {iface.mtu}")
    if iface.vrf:
        block.append(f" vrf {iface.vrf}")
    if "." in iface.name:
        unit = _subinterface_unit(iface.name)
        if unit is not None and unit in vlan_ids:
            block.append(f" encapsulation dot1q {unit}")
    for addr in iface.ipv4_addresses:
        line = f" ipv4 address {addr.ip} {_prefix_to_mask(addr.prefix_length)}"
        if addr.is_secondary:
            line += " secondary"
        block.append(line)
    for addr in iface.ipv6_addresses:
        block.append(f" ipv6 address {addr.ip}/{addr.prefix_length}")
    if iface.lag_member_of:
        m = re.search(r"(\d+)\s*$", iface.lag_member_of)
        if m:
            mode = _CANON_TO_IOSXR_BUNDLE_MODE.get(
                lag_mode_by_name.get(iface.lag_member_of, "active"), "active",
            )
            block.append(f" bundle id {m.group(1)} mode {mode}")
    block.append("!")
    return block


def _subinterface_unit(name: str) -> int | None:
    """Return the numeric unit suffix of a sub-interface name, or None.

    ``GigabitEthernet0/0/0/1.100`` → ``100``; a name with a non-numeric
    or absent suffix returns ``None``.
    """
    tail = name.rsplit(".", 1)[-1]
    try:
        return int(tail)
    except ValueError:
        return None


#: Interface-kind render order: Loopback → MgmtEth → physical →
#: Bundle-Ether → everything else (sub-interfaces / tunnels / unknown).
_KIND_ORDER: dict[str, int] = {
    "loopback": 0,
    "mgmt": 1,
    "physical": 2,
    "lag": 3,
}


def _sort_interfaces_iosxr(interfaces: list):
    """Return *interfaces* in an XR-natural order.

    Ordering is cosmetic — the round-trip invariant compares canonical
    meaning, not text order — but matching the device's grouping makes
    diffs reviewable.  Keys off ``classify_port_name(name).kind`` then
    the structural indices then the verbatim name.
    """
    def _key(iface):
        ident = _port_names.classify_port_name(iface.name)
        kind_rank = _KIND_ORDER.get(ident.kind, 9)
        nums = (
            ident.stack or 0,
            ident.module or 0,
            ident.port or 0,
            ident.index or 0,
        )
        return (kind_rank, nums, iface.name)

    return sorted(interfaces, key=_key)
