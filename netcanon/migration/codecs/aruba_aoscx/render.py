"""
Render path for Aruba AOS-CX (canonical tree → ``show running-config``).

Public function: :func:`render_intent` — :class:`CanonicalIntent` in,
AOS-CX CLI text out.

Emits the supported subset declared in the capability matrix: a
synthesised ``!Version`` banner, hostname, local users (``user <name>
group <group> password ciphertext <blob>``), top-level ``vrf``
declarations, per-id ``vlan`` stanzas (+ name / description), default-VRF
static routes, and interface stanzas with description / admin-state /
mtu, the L2 switchport surface (``no routing`` + ``vlan access`` / ``vlan
trunk``) for physical + LAG ports, IPv4 (CIDR) / ``vrf attach`` / IPv6
for routed ports, LAG membership (``lag N``), and ``lacp mode`` on the
``interface lag N`` stanzas.

Phase 4 adds the ``interface vxlan 1`` VTEP — the L2 VLAN↔VNI bindings
(``vni <VNI>`` / nested ``vlan <VLAN>``) plus the switch-level ``source
ip`` (emitted only when the opaque ``source_interface`` parses as an
IPv4 address).

The render path stays deliberately tolerant of the canonical surfaces it
does NOT emit (the per-VLAN L2VNI RD / route-target, symmetric-IRB
L3VNI, and Tier-3 protocols): a cross-vendor source tree carrying those
fields renders cleanly, simply omitting them.  The matrix declares each
omission ``unsupported`` so the migrate-page banner surfaces the gap.

AOS-CX grammar notes that shape the output (see
``docs/fixture-research-2015/11-aruba_aoscx.md``):

* Interface names are multi-token (``vlan 11`` / ``lag 1`` / ``1/1/1``);
  :mod:`.port_names` is the single source of truth for the spelling.
* L2 is opt-in: an L2 port emits ``no routing`` + ``vlan access`` /
  ``vlan trunk`` (the INVERSE of NX-OS); a routed port carries a bare
  ``ip address`` with no ``routing`` keyword.  Switchport lines are
  kind-gated to physical + LAG ports.
* An empty trunk-allowed list re-emits as ``vlan trunk allowed all``.
* Admin-state is emitted explicitly (``no shutdown`` / ``shutdown``) so
  the round-trip is stable regardless of the parser's type-aware default.
"""

from __future__ import annotations

import ipaddress
import re

from ...canonical.intent import CanonicalIntent

#: Synthesised AOS-CX release stamped into the ``!Version`` banner.
#: Cosmetic — the parsed ``source_version`` is metadata only and not
#: echoed (mirrors the cisco_nxos ``_DEFAULT_VERSION`` convention).  The
#: ``Virtual.`` prefix is the AOS-CX simulator image family.
_DEFAULT_VERSION = "Virtual.10.13.1000"

#: Canonical SNMPv3 privacy cipher -> AOS-CX `priv` keyword.  AOS-CX
#: supports `des` and `aes`; NX-OS-style aes128/192/256 collapse to
#: `aes`, 3des -> des.
_CANON_TO_AOSCX_PRIV = {
    "aes": "aes", "aes128": "aes", "aes192": "aes", "aes256": "aes",
    "des": "des", "3des": "des",
}


def render_intent(tree: CanonicalIntent) -> str:
    """Render a :class:`CanonicalIntent` as Aruba AOS-CX config text."""
    hostname = tree.hostname or "switch"
    lines: list[str] = []

    # ── Banner / version ──
    lines.append("!")
    lines.append(f"!Version ArubaOS-CX {_DEFAULT_VERSION}")
    lines.append("!export-password: default")
    lines.append(f"hostname {hostname}")

    # ── Local users (Phase 2) ──
    for user in tree.local_users:
        lines.append(_render_local_user(user))

    # ── SNMP (Phase 2b) ──
    if tree.snmp is not None:
        lines.extend(_render_snmp(tree.snmp))

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
    lag_mode_by_name = {lag.name: lag.mode for lag in tree.lags}
    for iface in _sort_interfaces(tree.interfaces):
        lines.extend(_render_interface(
            iface, lag_mode_by_name, tree.anycast_gateway_mac,
        ))

    # ── VTEP (interface vxlan 1) — Phase 4 VXLAN-EVPN ──
    lines.extend(_render_vxlan(tree))

    return "\n".join(lines) + "\n"


def _is_ipv4(value: str) -> bool:
    """Return True iff *value* parses as a literal IPv4 address."""
    try:
        ipaddress.IPv4Address(value)
        return True
    except ValueError:
        return False


def _render_vxlan(tree: CanonicalIntent) -> list[str]:
    """Render the ``interface vxlan 1`` VTEP stanza from VXLAN data.

    AOS-CX uses a single VTEP (``vxlan 1``).  Each L2 VNI emits a ``vni
    <VNI>`` sub-block carrying a nested ``vlan <VLAN>`` (the L2 binding);
    the switch-level ``source ip <X>`` is taken from the first record
    whose ``source_interface`` parses as an IPv4 address.  AOS-CX states
    the VTEP source as an address (not an interface name), so a
    cross-vendor source carrying an interface *name* there has no AOS-CX
    ``source ip`` form — the line is omitted rather than emitting a
    malformed address (the VNI bindings still render).  Records are
    emitted sorted by ``vlan_id`` so a same-vendor round-trip is stable
    (the real-capture round-trip compares ``vxlan_vnis`` by list equality
    without re-sorting).  Returns an empty list when there is no overlay.
    """
    if not tree.vxlan_vnis:
        return []
    source_ip = next(
        (
            v.source_interface
            for v in tree.vxlan_vnis
            if v.source_interface and _is_ipv4(v.source_interface)
        ),
        "",
    )
    block = ["interface vxlan 1"]
    if source_ip:
        block.append(f"    source ip {source_ip}")
    block.append("    no shutdown")
    for v in sorted(tree.vxlan_vnis, key=lambda x: x.vlan_id):
        block.append(f"    vni {v.vni}")
        block.append(f"        vlan {v.vlan_id}")
    return block


def _render_local_user(user) -> str:
    """Render ``user <name> group <group> password ciphertext <blob>``.

    ``role`` (the AOS-CX group) is emitted verbatim when set (same-vendor
    round-trip) and otherwise derived from the privilege level
    (administrators >= 15, else operators).  The ``ciphertext`` blob is
    re-emitted verbatim from ``hashed_password``; a user with no stored
    secret renders the bare form (best-effort for a cross-vendor source).
    """
    role = user.role or (
        "administrators" if user.privilege_level >= 15 else "operators"
    )
    if user.hashed_password:
        return (
            f"user {user.name} group {role} "
            f"password ciphertext {user.hashed_password}"
        )
    return f"user {user.name} group {role}"


def _render_snmp(snmp) -> list[str]:
    """Render AOS-CX ``snmp-server`` + ``snmpv3 user`` lines.

    AOS-CX uses ``system-location`` / ``system-contact`` (not ``location``
    / ``contact``).  v3 auth/priv keys re-emit with the ``ciphertext``
    keyword (the ``plaintext`` form is normalised away — declared lossy);
    the auth protocol collapses to ``md5`` / ``sha`` and the privacy
    cipher denormalises canonical -> AOS-CX (aes-family -> ``aes``,
    des/3des -> ``des``).  Trap hosts and the ``snmp-server vrf`` binding
    are not emitted (deferred).
    """
    lines: list[str] = []
    if snmp.community:
        lines.append(f"snmp-server community {snmp.community}")
    if snmp.location:
        lines.append(f"snmp-server system-location {snmp.location}")
    if snmp.contact:
        lines.append(f"snmp-server system-contact {snmp.contact}")
    for user in snmp.v3_users:
        if not user.auth_protocol:
            continue  # AOS-CX snmpv3 users require an auth protocol
        auth = "md5" if user.auth_protocol.lower() == "md5" else "sha"
        line = (
            f"snmpv3 user {user.name} auth {auth} "
            f"auth-pass ciphertext {user.auth_passphrase}"
        )
        if user.priv_protocol:
            priv = _CANON_TO_AOSCX_PRIV.get(user.priv_protocol.lower(), "aes")
            line += (
                f" priv {priv} priv-pass ciphertext {user.priv_passphrase}"
            )
        lines.append(line)
    return lines


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


def _render_interface(
    iface, lag_mode_by_name: dict, anycast_mac: str = "",
) -> list[str]:
    """Render one interface stanza.

    Switchport handling is kind-aware: only physical / LAG ports take the
    L2 ``no routing`` + ``vlan access`` / ``vlan trunk`` surface.  A
    routed port (no switchport mode) emits its IP with no ``routing``
    keyword (routing is the AOS-CX default for an addressed port).  SVIs /
    loopbacks / mgmt are inherently L3.  ``lacp mode`` is emitted on the
    ``interface lag N`` stanza; ``lag N`` membership on the member port.
    An SVI address carrying a ``virtual_gateway_address`` emits the
    ``active-gateway ip mac <mac>`` + ``active-gateway ip <vip>`` anycast
    pair (the MAC is the chassis-wide ``anycast_gateway_mac``).
    """
    from . import port_names as _port_names

    block = [f"interface {iface.name}"]
    if iface.enabled:
        block.append("    no shutdown")
    else:
        block.append("    shutdown")
    if iface.description:
        block.append(f"    description {iface.description}")
    if iface.mtu is not None:
        block.append(f"    mtu {iface.mtu}")

    kind = _port_names.classify_port_name(iface.name).kind
    is_l2 = (
        kind in ("physical", "lag")
        and iface.switchport_mode in ("access", "trunk")
    )

    if is_l2:
        # ── L2 switchport ── (the AOS-CX inverse of NX-OS: state ``no
        # routing`` then the VLAN membership).
        block.append("    no routing")
        if iface.switchport_mode == "access":
            if iface.access_vlan is not None:
                block.append(f"    vlan access {iface.access_vlan}")
        else:  # trunk
            if iface.trunk_native_vlan is not None:
                block.append(
                    f"    vlan trunk native {iface.trunk_native_vlan}"
                )
            allowed = sorted(set(iface.trunk_allowed_vlans))
            if allowed:
                block.append(
                    f"    vlan trunk allowed {_coalesce_vlan_ids(allowed)}"
                )
            else:
                # Empty allowed-list == all (the parser maps ``all`` -> []).
                block.append("    vlan trunk allowed all")
    else:
        # ── L3 (routed) — vrf bind precedes the address ──
        if iface.vrf:
            block.append(f"    vrf attach {iface.vrf}")
        for addr in iface.ipv4_addresses:
            line = f"    ip address {addr.ip}/{addr.prefix_length}"
            if addr.is_secondary:
                line += " secondary"
            block.append(line)
            # ── Active-gateway anycast (Phase 3) ── the per-SVI VIP +
            # the chassis-wide MAC; AOS-CX emits both under the SVI.
            if addr.virtual_gateway_address:
                if anycast_mac:
                    block.append(f"    active-gateway ip mac {anycast_mac}")
                block.append(
                    f"    active-gateway ip {addr.virtual_gateway_address}"
                )
        for addr in iface.ipv6_addresses:
            block.append(f"    ipv6 address {addr.ip}/{addr.prefix_length}")

    # ── LAG membership (``lag N`` on the member port) ──
    if iface.lag_member_of:
        m = re.search(r"(\d+)\s*$", iface.lag_member_of)
        if m:
            block.append(f"    lag {m.group(1)}")

    # ── ``lacp mode`` on the ``interface lag N`` stanza ──
    if kind == "lag":
        mode = lag_mode_by_name.get(iface.name, "static")
        if mode in ("active", "passive"):
            block.append(f"    lacp mode {mode}")

    return block


def _coalesce_vlan_ids(ids: list[int]) -> str:
    """Coalesce a sorted, de-duplicated VLAN-id list into AOS-CX form.

    ``[1, 10, 11, 12, 20]`` → ``"1,10-12,20"``.  Consecutive runs of
    three or more collapse to ``lo-hi``; the inverse of
    :func:`parse._parse_vlan_list` so the ``vlan trunk allowed`` list
    round-trips.
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
    ``10-11`` — both re-parse identically, but the comma form matches the
    show-output convention for adjacent pairs.
    """
    if hi == lo:
        return str(lo)
    if hi == lo + 1:
        return f"{lo},{hi}"
    return f"{lo}-{hi}"


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
