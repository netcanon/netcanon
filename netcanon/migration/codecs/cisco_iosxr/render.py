"""
Render path for Cisco IOS-XR (canonical tree → ``show running-config``).

Public function: :func:`render_intent` — :class:`CanonicalIntent` in,
IOS-XR CLI text out.

Phase 1 emits the supported subset declared in the capability matrix:
a synthesised ``!! IOS XR Configuration`` banner, hostname, domain,
interface stanzas (description / admin-state / mtu / IPv4 dotted-mask /
IPv6 CIDR), a ``router static`` block (default VRF), and the closing
``end``.

The render path stays deliberately tolerant of canonical surfaces it
does NOT emit in Phase 1 (VRF stanzas + per-interface VRF membership,
LAGs, local users, VLANs, VXLAN, SP-routing) — a cross-vendor source
tree carrying those fields renders cleanly, simply omitting them.  The
matrix declares each omission ``unsupported`` so the migrate-page banner
surfaces the gap.

Per ``02-codec-architecture.md`` no ``commit`` line is emitted — the
output matches ``show running-config`` shape, which is what operators
consume.
"""

from __future__ import annotations

import ipaddress

from ...canonical.intent import CanonicalIntent
from ..base import RenderError
from . import port_names as _port_names

#: Synthesised IOS-XR release stamped into the banner.  Cosmetic — the
#: parsed ``source_version`` is metadata only and not echoed (mirrors the
#: cisco_nxos render convention).
_DEFAULT_VERSION = "6.6.2"


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

    # ── Interfaces (XR show-output-ish order) ──
    for iface in _sort_interfaces_iosxr(tree.interfaces):
        lines.extend(_render_interface(iface))

    # ── Static routes (default VRF) ──
    lines.extend(_render_router_static(tree.static_routes))

    # ── Footer ──
    lines.append("end")

    return "\n".join(lines) + "\n"


def _render_interface(iface) -> list[str]:
    """Render one ``interface <name>`` stanza (``!``-terminated).

    IPv4 emits the dotted-mask form (``ipv4 address X Y``); IPv6 emits
    CIDR.  Sub-commands are single-space indented per XR convention.
    """
    block = [f"interface {iface.name}"]
    if iface.description:
        block.append(f" description {iface.description}")
    if not iface.enabled:
        block.append(" shutdown")
    if iface.mtu is not None:
        block.append(f" mtu {iface.mtu}")
    for addr in iface.ipv4_addresses:
        line = f" ipv4 address {addr.ip} {_prefix_to_mask(addr.prefix_length)}"
        if addr.is_secondary:
            line += " secondary"
        block.append(line)
    for addr in iface.ipv6_addresses:
        block.append(f" ipv6 address {addr.ip}/{addr.prefix_length}")
    block.append("!")
    return block


def _render_router_static(routes: list) -> list[str]:
    """Render the ``router static`` block for default-VRF routes.

    Per-VRF routes (``CanonicalStaticRoute.vrf`` set) are Phase 2 —
    Phase 1 emits only the global address-family.  Each leaf is
    ``<dest> <interface> <gateway>`` with the empty components dropped
    (interface-only for ``Null0`` / blackhole; gateway-only for a plain
    next-hop).
    """
    default_routes = [r for r in routes if not r.vrf]
    if not default_routes:
        return []
    out = ["router static", " address-family ipv4 unicast"]
    for r in default_routes:
        nexthop = " ".join(t for t in (r.interface, r.gateway) if t)
        out.append(f"  {r.destination} {nexthop}".rstrip())
    out.append(" !")
    out.append("!")
    return out


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
