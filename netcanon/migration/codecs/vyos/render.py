"""
Render path for VyOS (canonical tree → ``config.boot`` curly-brace text).

Public function: :func:`render_intent` — :class:`CanonicalIntent` in,
VyOS configuration text out.

Emits the supported subset: the ``interfaces`` tree (ethernet /
loopback / dummy / bonding blocks with ``address`` / ``description`` /
``disable`` / ``mtu`` / per-interface ``vrf``, plus nested ``vif`` VLAN
sub-interfaces and the bonding ``mode`` / ``member`` lines), the
``protocols static`` route tree, the ``service { snmp { ... } }`` block
(v1/v2c community + location / contact + v3 USM users), the ``system``
block (``host-name`` + ``login`` local users + ``ntp`` servers), the
``vrf { name <X> { table <N> } }`` routing instances, and the
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
  ``vrf``), followed by any nested ``vif`` sub-interface blocks, so a
  same-vendor diff against a real ``show configuration`` is reviewable.
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

    iface_lines = _render_interfaces(tree.interfaces, tree.lags)
    if iface_lines:
        lines.append("interfaces {")
        lines.extend(iface_lines)
        lines.append("}")

    static_lines = _render_static(tree.static_routes)
    if static_lines:
        lines.append("protocols {")
        lines.extend(static_lines)
        lines.append("}")

    # ``service { snmp { ... } }`` — emitted between ``protocols`` and
    # ``system`` to match VyOS's alphabetical top-level node order.
    lines.extend(_render_service(tree.snmp))

    # ``system`` always carries at least the host-name; Phase 2 adds the
    # ``login`` (local users) and ``ntp`` sub-blocks.
    lines.append("system {")
    lines.append(f"    host-name {tree.hostname or 'vyos'}")
    lines.extend(_render_login(tree.local_users))
    lines.extend(_render_ntp(tree.ntp_servers))
    lines.append("}")

    # ``vrf { name <X> { table <N> } }`` — the last top-level node
    # (alphabetical), emitted after ``system``.
    lines.extend(_render_vrf(tree.routing_instances))

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
    if iface.vrf:
        out.append(f"{indent}vrf {_q(iface.vrf)}")
    return out


def _render_interfaces(interfaces: list, lags: list | None = None) -> list[str]:
    """Render the body of the ``interfaces { }`` block.

    Splits canonical interfaces into parents and ``vif`` sub-interfaces
    (``ethN.<vid>``), nests each vif inside its parent ethernet block,
    and synthesises an empty parent block for any orphan vif.  A
    ``bonding bondN`` interface additionally emits its LACP ``mode`` and
    1.4-style ``member { interface ethN { } }`` list from the matching
    :class:`CanonicalLAG`.
    """
    lag_by_name = {lag.name: lag for lag in (lags or [])}
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
    # Ensure a block exists for any LAG declared but not separately
    # materialised as an interface.
    for lag_name in lag_by_name:
        if lag_name not in parents:
            parents[lag_name] = None
            order.append(lag_name)

    lines: list[str] = []
    for name in sorted(order, key=_iface_sort_key):
        btype, bname = _vyos_type_and_name(name)
        lines.append(f"    {btype} {bname} {{")
        iface = parents[name]
        if iface is not None:
            lines.extend(_iface_body(iface, "        "))
        if btype == "bonding":
            lines.extend(_bond_extra(lag_by_name.get(name), "        "))
        for vid, viface in sorted(vifs.get(name, []), key=lambda t: t[0]):
            lines.append(f"        vif {vid} {{")
            lines.extend(_iface_body(viface, "            "))
            lines.append("        }")
        lines.append("    }")
    return lines


def _bond_extra(lag, indent: str) -> list[str]:
    """Render a bonding interface's ``mode`` + ``member`` lines from the
    matching :class:`CanonicalLAG` (1.4-style member-interface form;
    members sorted).  ``mode 802.3ad`` is emitted for an ``active``
    (LACP) LAG; a ``static`` LAG omits the line (VyOS applies its
    default)."""
    if lag is None:
        return []
    out: list[str] = []
    if lag.mode == "active":
        out.append(f"{indent}mode 802.3ad")
    if lag.members:
        out.append(f"{indent}member {{")
        for member in sorted(lag.members):
            out.append(f"{indent}    interface {member} {{")
            out.append(f"{indent}    }}")
        out.append(f"{indent}}}")
    return out


def _render_login(users: list) -> list[str]:
    """Render the ``login { }`` sub-block (nested under ``system``).

    Each user emits ``user <name> { authentication { encrypted-password
    <hash> } }``.  Sorted by name for stable output (the round-trip
    compares local_users by name).  A user with no stored hash renders
    the bare ``user <name> { }`` form.
    """
    if not users:
        return []
    out = ["    login {"]
    for u in sorted(users, key=lambda x: x.name):
        out.append(f"        user {u.name} {{")
        if u.hashed_password:
            out.append("            authentication {")
            out.append(
                f"                encrypted-password {u.hashed_password}"
            )
            out.append("            }")
        out.append("        }")
    out.append("    }")
    return out


def _render_ntp(servers: list) -> list[str]:
    """Render the ``ntp { }`` sub-block (nested under ``system``).

    Emits one ``server <host>`` per NTP server in canonical-list order
    (preserved from parse, so the round-trip is stable)."""
    if not servers:
        return []
    out = ["    ntp {"]
    for s in servers:
        out.append(f"        server {s}")
    out.append("    }")
    return out


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


def _snmp_auth_type(proto: str) -> str:
    """Denormalise a canonical SNMPv3 auth protocol to the VyOS keyword
    (``md5`` or ``sha``; the SHA-2 variants collapse to ``sha``)."""
    return "md5" if proto == "md5" else "sha"


def _snmp_priv_type(proto: str) -> str:
    """Denormalise a canonical SNMPv3 privacy cipher to the VyOS keyword
    (``des`` or ``aes``; the AES key-length variants collapse to ``aes``)."""
    return "des" if proto in ("des", "3des") else "aes"


def _render_snmp_v3(users: list) -> list[str]:
    """Render the ``v3 { }`` USM sub-block (nested under ``snmp``).

    Users are sorted by name for stable output.  A single config-wide
    ``engineid`` is emitted when every USM user shares one (the canonical
    model carries the engineID per-user; VyOS declares it once for the
    whole agent).  A user with no auth protocol is skipped — VyOS USM
    requires authentication.  Auth / privacy keys are emitted as
    ``encrypted-password`` (the 1.4 saved-config form); the opaque blob
    round-trips verbatim same-vendor.
    """
    usable = [u for u in users if u.auth_protocol]
    if not usable:
        return []
    out = ["        v3 {"]
    engine_ids = {u.engine_id for u in usable if u.engine_id}
    if len(engine_ids) == 1:
        out.append(f"            engineid {next(iter(engine_ids))}")
    for u in sorted(usable, key=lambda x: x.name):
        out.append(f"            user {u.name} {{")
        if u.group:
            out.append(f"                group {u.group}")
        out.append("                auth {")
        out.append(
            f"                    encrypted-password {u.auth_passphrase}"
        )
        out.append(
            f"                    type {_snmp_auth_type(u.auth_protocol)}"
        )
        out.append("                }")
        if u.priv_protocol:
            out.append("                privacy {")
            out.append(
                f"                    encrypted-password {u.priv_passphrase}"
            )
            out.append(
                f"                    type {_snmp_priv_type(u.priv_protocol)}"
            )
            out.append("                }")
        out.append("            }")
    out.append("        }")
    return out


def _render_service(snmp) -> list[str]:
    """Render the top-level ``service { snmp { ... } }`` block.

    Returns ``[]`` when there is no SNMP configuration so the caller
    omits the enclosing ``service { }`` block entirely.  The v1/v2c
    community is rendered read-only (``authorization ro``) — the
    canonical model carries only the community string, not the ro/rw
    flag.
    """
    if snmp is None:
        return []
    body: list[str] = []
    if snmp.community:
        body.append(f"        community {snmp.community} {{")
        body.append("            authorization ro")
        body.append("        }")
    if snmp.contact:
        body.append(f"        contact {_q(snmp.contact)}")
    if snmp.location:
        body.append(f"        location {_q(snmp.location)}")
    body.extend(_render_snmp_v3(snmp.v3_users))
    if not body:
        return []
    return ["service {", "    snmp {"] + body + ["    }", "}"]


def _render_vrf(instances: list) -> list[str]:
    """Render the top-level ``vrf { }`` block.

    Each routing-instance emits ``name <X> { table <N> }``; the numeric
    ``table`` id is SYNTHESISED (``100 + sort-index``) because the
    canonical :class:`CanonicalRoutingInstance` carries no table number
    (declared lossy ``/routing-instances/instance/table``).  Instances
    are sorted by name for stable, deterministic output (the round-trip
    does not normalise ``routing_instances`` order, and the synthesised
    id must be reproducible).
    """
    usable = [ri for ri in instances if ri.name]
    if not usable:
        return []
    out = ["vrf {"]
    for idx, ri in enumerate(sorted(usable, key=lambda x: x.name)):
        out.append(f"    name {ri.name} {{")
        out.append(f"        table {100 + idx}")
        out.append("    }")
    out.append("}")
    return out
