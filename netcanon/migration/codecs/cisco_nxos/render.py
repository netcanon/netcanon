"""
Render path for Cisco NX-OS (canonical tree → ``show running-config``).

Public function: :func:`render_intent` — :class:`CanonicalIntent` in,
NX-OS CLI text out.

Phase 1 emits the supported subset declared in the capability matrix:
hostname, a synthesised banner / version / ``vdc`` wrapper, render-derived
``feature`` lines, default-VRF static routes, coalesced VLANs (+ names),
``vrf context`` blocks (name + description + rd + route-target + nested
per-VRF static routes), and interface stanzas with description /
admin-state / mtu / IPv4 (CIDR) / IPv6 / ``vrf member``.

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

import re

from ...canonical.intent import CanonicalIntent, CanonicalRoutingInstance
from . import port_names as _port_names

#: Synthesised NX-OS release stamped into the banner.  Cosmetic — the
#: parsed ``source_version`` is metadata only and not echoed.
_DEFAULT_VERSION = "9.3(11)"

#: Canonical LAG mode -> NX-OS ``channel-group ... mode`` keyword
#: (inverse of parse._NXOS_LAG_MODE_MAP; canonical ``static`` -> ``on``).
_CANON_TO_NXOS_LAG_MODE = {
    "active": "active",
    "passive": "passive",
    "static": "on",
}

#: Canonical SNMPv3 privacy cipher -> NX-OS ``priv`` keyword (inverse of
#: parse._normalise_priv_proto; canonical ``aes128`` -> NX-OS ``aes-128``).
_CANON_TO_NXOS_PRIV = {
    "aes": "aes-128",
    "aes128": "aes-128",
    "aes192": "aes-192",
    "aes256": "aes-256",
    "des": "des",
    "3des": "3des",
}


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
    features = _derive_features(tree)
    for feat in features:
        lines.append(f"feature {feat}")
    if features:
        lines.append("")

    # ── Local users + SNMP (Phase 2b) ──
    for user in tree.local_users:
        lines.append(_render_local_user(user))
    if tree.local_users:
        lines.append("")
    if tree.snmp is not None:
        snmp_lines = _render_snmp(tree.snmp)
        if snmp_lines:
            lines.extend(snmp_lines)
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

    # ── VRF contexts (name + description + rd + route-target + per-VRF
    # static routes) ──
    # Emit in tree order (= source order on a same-vendor round-trip).
    # The round-trip invariant does NOT normalise routing_instances
    # ordering, so re-sorting here would register as canonical drift.
    # Per-VRF static routes (CanonicalStaticRoute.vrf set) nest inside
    # their VRF's block — the default-VRF routes were emitted above.
    routes_by_vrf: dict[str, list] = {}
    for r in tree.static_routes:
        if r.vrf:
            routes_by_vrf.setdefault(r.vrf, []).append(r)
    rendered_vrfs: set[str] = set()
    if tree.routing_instances or routes_by_vrf:
        for ri in tree.routing_instances:
            lines.extend(_render_vrf_context(ri, routes_by_vrf.get(ri.name, [])))
            rendered_vrfs.add(ri.name)
        # Defensive: a per-VRF static route whose VRF has no routing-
        # instance record (e.g. a cisco_iosxe_cli source where ``ip route
        # vrf X`` never declared a ``vrf definition X``) still needs a
        # ``vrf context`` wrapper so the route is valid NX-OS and
        # re-parses with vrf=<name>.
        for vrf_name, routes in routes_by_vrf.items():
            if vrf_name not in rendered_vrfs:
                lines.extend(_render_vrf_context(
                    CanonicalRoutingInstance(name=vrf_name), routes,
                ))
                rendered_vrfs.add(vrf_name)
        lines.append("")

    # ── Interfaces (NX-OS sort order) ──
    lag_mode_by_name = {lag.name: lag.mode for lag in tree.lags}
    for iface in _sort_interfaces_nxos(tree.interfaces):
        lines.extend(_render_interface(iface, lag_mode_by_name))

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
    if tree.lags:
        features.add("lacp")
    if any(i.vrrp_groups for i in tree.interfaces):
        features.add("hsrp")
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


def _render_local_user(user) -> str:
    """Render a ``username <name> password <type> <hash> role <role>``.

    The hash is preserved with its type-digit prefix (parse stored
    ``5 $5$...``); a bare value (no leading single-digit type) renders as
    the plaintext type-0 form.  ``role`` is emitted verbatim when set
    (same-vendor round-trip) and otherwise derived from the privilege
    level (network-admin >= 15, else network-operator).
    """
    role = user.role or (
        "network-admin" if user.privilege_level >= 15 else "network-operator"
    )
    if not user.hashed_password:
        return f"username {user.name} role {role}"
    parts = user.hashed_password.split(" ", 1)
    if len(parts) == 2 and parts[0].isdigit() and len(parts[0]) <= 2:
        htype, payload = parts[0], parts[1]
    else:
        htype, payload = "0", user.hashed_password
    return f"username {user.name} password {htype} {payload} role {role}"


def _render_snmp(snmp) -> list[str]:
    """Render NX-OS ``snmp-server`` lines (v2c community + v3 USM users).

    v3 privacy cipher denormalises canonical -> NX-OS (``aes128`` ->
    ``aes-128``); opaque keys re-emit verbatim with the ``localizedkey``
    keyword (the 10.x ``localizedV2key`` digest is not modelled —
    declared lossy).  ``engineID`` (colon-decimal) re-emits verbatim.
    """
    lines: list[str] = []
    if snmp.community:
        lines.append(f"snmp-server community {snmp.community}")
    if snmp.location:
        lines.append(f"snmp-server location {snmp.location}")
    if snmp.contact:
        lines.append(f"snmp-server contact {snmp.contact}")
    for host in snmp.trap_hosts:
        lines.append(f"snmp-server host {host}")
    for user in snmp.v3_users:
        line = f"snmp-server user {user.name}"
        if user.group:
            line += f" {user.group}"
        if user.auth_protocol:
            line += f" auth {user.auth_protocol} {user.auth_passphrase}"
            if user.priv_protocol:
                priv = _CANON_TO_NXOS_PRIV.get(
                    user.priv_protocol, user.priv_protocol,
                )
                line += f" priv {priv} {user.priv_passphrase}"
            line += " localizedkey"
        if user.engine_id:
            line += f" engineID {user.engine_id}"
        lines.append(line)
    return lines


def _render_vrf_context(ri: CanonicalRoutingInstance, routes=None) -> list[str]:
    """Render a ``vrf context <name>`` block.

    Emits ``description``, ``rd`` (the ``auto`` sentinel re-emits
    verbatim), an ``address-family ipv4 unicast`` sub-block with
    ``route-target`` lines (the compact ``both <rt>`` form when an RT is
    in both import + export), and any per-VRF static routes nested inside
    the block.  The source's ``evpn`` address-family discriminator is NOT
    re-emitted (declared lossy — the RT survives, the L2VPN-EVPN scope
    reverts to IPv4 unicast).  ``vni`` (L3VNI) lands in Phase 4.
    """
    block = [f"vrf context {ri.name}"]
    if ri.description:
        block.append(f"  description {ri.description}")
    if ri.route_distinguisher:
        block.append(f"  rd {ri.route_distinguisher}")
    rt_lines = _render_route_targets(ri.rt_imports, ri.rt_exports)
    if rt_lines:
        block.append("  address-family ipv4 unicast")
        block.extend(rt_lines)
    for route in routes or []:
        block.append(f"  {_render_static_route(route)}")
    return block


def _render_route_targets(imports: list, exports: list) -> list[str]:
    """Return ``route-target`` lines for an ``address-family`` sub-block.

    An RT present in BOTH import + export collapses to the compact
    ``route-target both <rt>`` form (matching how operators write it and
    how :func:`parse._parse_routing_instances` re-expands it); the
    import-only and export-only remainders follow.  Lines are indented
    four spaces (nested under ``address-family ipv4 unicast``).
    """
    both = [rt for rt in imports if rt in exports]
    imp_only = [rt for rt in imports if rt not in exports]
    exp_only = [rt for rt in exports if rt not in imports]
    lines: list[str] = []
    for rt in both:
        lines.append(f"    route-target both {rt}")
    for rt in imp_only:
        lines.append(f"    route-target import {rt}")
    for rt in exp_only:
        lines.append(f"    route-target export {rt}")
    return lines


def _render_interface(iface, lag_mode_by_name: dict) -> list[str]:
    """Render one interface stanza.

    Switchport handling is kind-aware: only physical / LAG ports take
    ``switchport`` config.  A routed physical/LAG port (no switchport
    mode but carrying an IP) gets an explicit ``no switchport`` — NX-OS
    defaults those ports to L2, so the routed intent must be stated.
    SVIs / loopbacks / mgmt0 are inherently L3 and emit no switchport
    line.  ``no switchport`` and ``vrf member`` precede ``ip address``
    (NX-OS rejects an IP on an L2 port and wipes it on a VRF change).
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

    kind = _port_names.classify_port_name(iface.name).kind
    # Switchport applies to L2-capable ports.  Exclude the inherently-L3
    # kinds (SVI / loopback / mgmt / VTEP / tunnel); everything else —
    # physical, LAG, and unknown cross-vendor names that default to L2 on
    # NX-OS — is switchport-eligible.
    if kind not in ("svi", "loopback", "mgmt", "vtep", "tunnel"):
        if iface.switchport_mode == "access":
            if iface.access_vlan is not None:
                block.append(f"  switchport access vlan {iface.access_vlan}")
            else:
                block.append("  switchport mode access")
        elif iface.switchport_mode == "trunk":
            block.append("  switchport mode trunk")
            if iface.trunk_native_vlan is not None:
                block.append(
                    f"  switchport trunk native vlan {iface.trunk_native_vlan}"
                )
            if iface.trunk_allowed_vlans:
                vlist = _coalesce_vlan_ids(sorted(set(iface.trunk_allowed_vlans)))
                block.append(f"  switchport trunk allowed vlan {vlist}")
        elif iface.ipv4_addresses or iface.ipv6_addresses:
            # Routed physical / LAG port — state the L3 intent explicitly.
            block.append("  no switchport")

    if iface.vrf:
        block.append(f"  vrf member {iface.vrf}")
    for addr in iface.ipv4_addresses:
        line = f"  ip address {addr.ip}/{addr.prefix_length}"
        if addr.is_secondary:
            line += " secondary"
        block.append(line)
    for addr in iface.ipv6_addresses:
        block.append(f"  ipv6 address {addr.ip}/{addr.prefix_length}")

    # ── HSRP groups (Phase 2c) ── every FHRP group normalises to an
    # NX-OS ``hsrp`` block (the mode discriminator is declared lossy).
    for group in iface.vrrp_groups:
        block.append(f"  hsrp {group.group_id}")
        for vip in group.virtual_ips:
            block.append(f"    ip {vip}")
        if group.priority != 100:
            block.append(f"    priority {group.priority}")
        if group.preempt:
            block.append("    preempt")
        if group.authentication:
            scheme, _, key = group.authentication.partition(":")
            if scheme == "md5":
                block.append(f"    authentication md5 key-string {key}")
            elif scheme == "plain":
                block.append(f"    authentication text {key}")

    if iface.lag_member_of:
        m = re.search(r"(\d+)\s*$", iface.lag_member_of)
        if m:
            mode = _CANON_TO_NXOS_LAG_MODE.get(
                lag_mode_by_name.get(iface.lag_member_of, "active"), "active",
            )
            block.append(f"  channel-group {m.group(1)} mode {mode}")
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
