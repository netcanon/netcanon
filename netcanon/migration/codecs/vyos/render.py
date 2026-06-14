"""
Render path for VyOS (canonical tree → ``config.boot`` curly-brace text).

Public function: :func:`render_intent` — :class:`CanonicalIntent` in,
VyOS configuration text out.

Emits the Phase-1 supported subset: the ``interfaces`` tree (ethernet /
loopback / dummy blocks with ``address`` / ``description`` / ``disable``
/ ``mtu``, plus nested ``vif`` VLAN sub-interfaces), the ``protocols
static`` route tree, the ``system host-name``, and the
``// vyos-config-version`` trailer every ``config.boot`` carries.

Grammar notes that shape the output (see
``docs/fixture-research-2015/`` + the parse-path docstring):

* Leaf values are emitted **quoted** for ``address`` / ``description``
  (matching VyOS 1.4+ ``show configuration`` output); simple tokens
  (``host-name`` / ``mtu`` / ``distance`` / ``next-hop``) stay bare.
  The parse path strips quotes either way, so the canonical round-trip
  is quote-agnostic.
* Leaves within an interface block are emitted in VyOS's alphabetical
  commit order (``address`` → ``description`` → ``disable`` → ``mtu`` →
  ``vif``) so a same-vendor diff against a real ``show configuration``
  is reviewable.
* A ``vif`` sub-interface (canonical name ``ethN.<vid>``) is nested
  inside its parent ``ethernet ethN`` block; an orphan vif (parent not
  separately declared) synthesises an empty parent block so the output
  is valid VyOS.
"""

from __future__ import annotations

import re

from ...canonical.intent import CanonicalIntent

#: Stamped into the ``// vyos-config-version`` trailer.  Cosmetic — the
#: parser skips the trailer entirely (the probe only substring-matches
#: ``vyos-config-version``).  Mirrors a real VyOS 1.4 component-version
#: line so the synthesised output is recognisably VyOS.
_CONFIG_VERSION = (
    "bgp@5:broadcast-relay@1:cluster@2:config-management@1:conntrack@5:"
    "conntrack-sync@2:dhcp-relay@2:dhcp-server@7:dhcpv6-server@1:"
    "dns-dynamic@4:dns-forwarding@4:firewall@14:flow-accounting@1:"
    "interfaces@29:ipoe-server@1:ipsec@13:isis@3:l2tp@5:lldp@2:mdns@1:"
    "monitoring@1:nat@8:nat66@3:ntp@3:openvpn@3:ospf@2:policy@8:pppoe-server@6:"
    "pptp@2:qos@2:quagga@11:rpki@2:salt@1:snmp@3:ssh@2:sstp@6:system@27:"
    "vrf@3:vrrp@4:wanloadbalance@3:webproxy@2"
)
#: Stamped into the ``// Release version`` trailer (cosmetic).
_RELEASE_VERSION = "1.4"

#: Interface-type render rank — ethernet, then loopback, dummy, bonding.
_TYPE_RANK = {"ethernet": 0, "loopback": 1, "dummy": 2, "bonding": 3}


def render_intent(tree: CanonicalIntent) -> str:
    """Render a :class:`CanonicalIntent` as VyOS ``config.boot`` text."""
    lines: list[str] = []

    iface_lines = _render_interfaces(tree.interfaces)
    if iface_lines:
        lines.append("interfaces {")
        lines.extend(iface_lines)
        lines.append("}")

    static_lines = _render_static(tree.static_routes)
    if static_lines:
        lines.append("protocols {")
        lines.extend(static_lines)
        lines.append("}")

    # ``system`` always carries at least the host-name.
    lines.append("system {")
    lines.append(f"    host-name {tree.hostname or 'vyos'}")
    lines.append("}")

    # Trailer — every config.boot ends with the component-version stamp.
    lines.append("// Warning: Do not remove the following line.")
    lines.append(f'// vyos-config-version: "{_CONFIG_VERSION}"')
    lines.append(f"// Release version: {_RELEASE_VERSION}")

    return "\n".join(lines) + "\n"


def _q(value: str) -> str:
    """Double-quote a leaf value (VyOS 1.4+ ``show configuration`` style)."""
    return f'"{value}"'


def _vyos_type_and_name(name: str) -> tuple[str, str]:
    """Map a canonical interface name to its VyOS ``<type> <name>`` header.

    ``lo`` → ``loopback lo``; ``dumN`` → ``dummy dumN``; ``bondN`` →
    ``bonding bondN``; ``ethN`` (and any unrecognised name) →
    ``ethernet <name>``.
    """
    if name == "lo":
        return ("loopback", "lo")
    if re.match(r"^dum\d+$", name):
        return ("dummy", name)
    if re.match(r"^bond\d+$", name):
        return ("bonding", name)
    return ("ethernet", name)


def _iface_sort_key(name: str) -> tuple[int, int, str]:
    btype, _ = _vyos_type_and_name(name)
    m = re.search(r"(\d+)", name)
    num = int(m.group(1)) if m else 0
    return (_TYPE_RANK.get(btype, 9), num, name)


def _iface_body(iface, indent: str) -> list[str]:
    """Render the leaves of one interface (or vif) block, in VyOS
    alphabetical commit order: address(es), description, disable, mtu."""
    out: list[str] = []
    if iface.dhcp_client:
        out.append(f"{indent}address dhcp")
    if iface.dhcp_client_v6:
        out.append(f"{indent}address dhcpv6")
    for a in iface.ipv4_addresses:
        out.append(f"{indent}address {_q(f'{a.ip}/{a.prefix_length}')}")
    for a in iface.ipv6_addresses:
        out.append(f"{indent}address {_q(f'{a.ip}/{a.prefix_length}')}")
    if iface.description:
        out.append(f"{indent}description {_q(iface.description)}")
    if not iface.enabled:
        out.append(f"{indent}disable")
    if iface.mtu is not None:
        out.append(f"{indent}mtu {iface.mtu}")
    return out


def _render_interfaces(interfaces: list) -> list[str]:
    """Render the body of the ``interfaces { }`` block.

    Splits canonical interfaces into parents and ``vif`` sub-interfaces
    (``ethN.<vid>``), nests each vif inside its parent ethernet block,
    and synthesises an empty parent block for any orphan vif.
    """
    parents: dict[str, object] = {}
    vifs: dict[str, list[tuple[int, object]]] = {}
    order: list[str] = []

    for iface in interfaces:
        m = re.match(r"^(eth\d+)\.(\d+)$", iface.name)
        if m:
            vifs.setdefault(m.group(1), []).append((int(m.group(2)), iface))
        elif iface.name not in parents:
            parents[iface.name] = iface
            order.append(iface.name)

    # Ensure a parent block exists for any orphan vif.
    for parent in vifs:
        if parent not in parents:
            parents[parent] = None
            order.append(parent)

    lines: list[str] = []
    for name in sorted(order, key=_iface_sort_key):
        btype, bname = _vyos_type_and_name(name)
        lines.append(f"    {btype} {bname} {{")
        iface = parents[name]
        if iface is not None:
            lines.extend(_iface_body(iface, "        "))
        for vid, viface in sorted(vifs.get(name, []), key=lambda t: t[0]):
            lines.append(f"        vif {vid} {{")
            lines.extend(_iface_body(viface, "            "))
            lines.append("        }")
        lines.append("    }")
    return lines


def _render_static(routes: list) -> list[str]:
    """Render the ``static { }`` block body (nested under ``protocols``).

    Each route emits ``route <CIDR> { next-hop <gw> { distance <N> } }``
    (``route6`` for IPv6 destinations).  Sorted by destination so the
    output is stable (the round-trip compares by destination anyway).
    """
    usable = [r for r in routes if r.destination and (r.gateway or r.interface)]
    if not usable:
        return []
    lines = ["    static {"]
    for r in sorted(usable, key=lambda x: x.destination):
        kw = "route6" if ":" in r.destination else "route"
        nexthop = r.gateway or r.interface
        lines.append(f"        {kw} {r.destination} {{")
        lines.append(f"            next-hop {nexthop} {{")
        if r.metric:
            lines.append(f"                distance {r.metric}")
        lines.append("            }")
        lines.append("        }")
    lines.append("    }")
    return lines
