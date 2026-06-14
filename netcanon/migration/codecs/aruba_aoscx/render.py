"""
Render path for Aruba AOS-CX (canonical tree → ``show running-config``).

Public function: :func:`render_intent` — :class:`CanonicalIntent` in,
AOS-CX CLI text out.

Phase 1 emits the supported Tier-1 subset declared in the capability
matrix: a synthesised ``!Version`` banner, hostname, top-level ``vrf``
declarations, per-id ``vlan`` stanzas (+ name / description), default-VRF
static routes, and interface stanzas with description / admin-state /
mtu / IPv4 (CIDR) / ``vrf attach`` / IPv6.

The render path stays deliberately tolerant of the canonical surfaces it
does NOT yet emit (L2 switchport, LAG membership, active-gateway anycast,
VXLAN / EVPN, Tier-3 protocols): a cross-vendor source tree carrying
those fields renders cleanly, simply omitting them.  The matrix declares
each omission ``unsupported`` so the migrate-page banner surfaces the gap.

AOS-CX grammar notes that shape the output (see
``docs/fixture-research-2015/11-aruba_aoscx.md``):

* Interface names are multi-token (``vlan 11`` / ``lag 1`` / ``1/1/1``);
  :mod:`.port_names` is the single source of truth for the spelling.
* A routed port carries a bare ``ip address`` (routing is implicit — no
  ``routing`` keyword is emitted).
* Admin-state is emitted explicitly (``no shutdown`` / ``shutdown``)
  rather than relying on the type-aware default, so the round-trip is
  stable regardless of the parser's default.
"""

from __future__ import annotations

from ...canonical.intent import CanonicalIntent

#: Synthesised AOS-CX release stamped into the ``!Version`` banner.
#: Cosmetic — the parsed ``source_version`` is metadata only and not
#: echoed (mirrors the cisco_nxos ``_DEFAULT_VERSION`` convention).  The
#: ``Virtual.`` prefix is the AOS-CX simulator image family.
_DEFAULT_VERSION = "Virtual.10.13.1000"


def render_intent(tree: CanonicalIntent) -> str:
    """Render a :class:`CanonicalIntent` as Aruba AOS-CX config text."""
    hostname = tree.hostname or "switch"
    lines: list[str] = []

    # ── Banner / version ──
    lines.append("!")
    lines.append(f"!Version ArubaOS-CX {_DEFAULT_VERSION}")
    lines.append("!export-password: default")
    lines.append(f"hostname {hostname}")
    lines.append("!")

    # ── VRF declarations ──
    # Emit in tree order (= source order on a same-vendor round-trip).
    # The round-trip invariant does NOT normalise routing_instances
    # ordering, so re-sorting here would register as canonical drift.
    for ri in tree.routing_instances:
        lines.append(f"vrf {ri.name}")

    # ── VLANs (one stanza per id, sorted) ──
    for vlan in sorted(tree.vlans, key=lambda v: v.id):
        lines.append(f"vlan {vlan.id}")
        if vlan.name:
            lines.append(f"    name {vlan.name}")
        if vlan.description:
            lines.append(f"    description {vlan.description}")

    # ── Static routes (default VRF only) ──
    for route in tree.static_routes:
        if route.vrf:
            continue  # per-VRF static is deferred (declared unsupported)
        lines.append(_render_static_route(route))

    # ── Interfaces (AOS-CX show-output order) ──
    for iface in _sort_interfaces(tree.interfaces):
        lines.extend(_render_interface(iface))

    return "\n".join(lines) + "\n"


def _render_static_route(route) -> str:
    """Render one default-VRF static route as ``ip route DEST/N GW [dist]``.

    ``destination`` is already CIDR (``X/N``).  Next-hop is the gateway
    IP, or the interface name for a directly-attached next-hop.  A
    non-zero ``metric`` re-emits as the trailing administrative-distance
    token.
    """
    nexthop = route.gateway or route.interface
    out = f"ip route {route.destination} {nexthop}".rstrip()
    if route.metric:
        out += f" {route.metric}"
    return out


def _render_interface(iface) -> list[str]:
    """Render one interface stanza.

    Admin-state is always stated explicitly.  A routed port emits its IP
    with no ``routing`` keyword (routing is the AOS-CX default for a port
    carrying an address).  ``vrf attach`` precedes the IP (AOS-CX wipes
    the address on a VRF change, so the binding must come first).
    """
    block = [f"interface {iface.name}"]
    if iface.enabled:
        block.append("    no shutdown")
    else:
        block.append("    shutdown")
    if iface.description:
        block.append(f"    description {iface.description}")
    if iface.mtu is not None:
        block.append(f"    mtu {iface.mtu}")
    if iface.vrf:
        block.append(f"    vrf attach {iface.vrf}")
    for addr in iface.ipv4_addresses:
        line = f"    ip address {addr.ip}/{addr.prefix_length}"
        if addr.is_secondary:
            line += " secondary"
        block.append(line)
    for addr in iface.ipv6_addresses:
        block.append(f"    ipv6 address {addr.ip}/{addr.prefix_length}")
    return block


#: Interface-kind render order: SVIs, then physical, then LAGs, then the
#: mgmt port, then loopbacks, then the VTEP.  Unknown kinds sort last.
#: Ordering is cosmetic (the round-trip invariant compares canonical
#: meaning, not text) but matching the device makes diffs reviewable.
_KIND_ORDER: dict[str, int] = {
    "svi": 0,
    "physical": 1,
    "lag": 2,
    "mgmt": 3,
    "loopback": 4,
    "vtep": 5,
}


def _sort_interfaces(interfaces: list):
    """Return *interfaces* in AOS-CX show-output order.

    Keys off ``classify_port_name(name).kind`` then the numeric position
    so e.g. ``1/1/2`` sorts before ``1/1/10`` and ``vlan 2`` before
    ``vlan 10``.
    """
    from . import port_names as _port_names

    def _key(iface):
        ident = _port_names.classify_port_name(iface.name)
        kind_rank = _KIND_ORDER.get(ident.kind, 99)
        nums = (
            ident.stack or 0,
            ident.module or 0,
            ident.port or 0,
            ident.index or 0,
        )
        return (kind_rank, nums, iface.name)

    return sorted(interfaces, key=_key)
