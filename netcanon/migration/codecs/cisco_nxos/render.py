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

The render path emits the full Phase 2-4 surface (L2 switchport / LAG /
SNMP / local-users / HSRP / VRF RD-RT / per-VRF static / VXLAN-EVPN +
L3VNI) plus IPv4 Distributed Anycast Gateway (per-SVI ``fabric
forwarding mode anycast-gateway`` + the chassis-wide ``fabric forwarding
anycast-gateway-mac``).  It stays deliberately tolerant of the canonical
surfaces it does NOT emit (IPv6 anycast, Tier-3 protocols): a
cross-vendor source tree carrying those fields renders cleanly, simply
omitting them.  The matrix declares each omission ``unsupported`` so the
migrate-page banner surfaces the gap.

``feature`` lines are render-derived (NOT modelled canonically — see
``03-canonical-mapping.md`` § 5); the ``vdc`` / ``line`` / ``boot``
footers are synthesised defaults so the output is a syntactically-valid
single-VDC NX-OS config even for a cross-vendor source.
"""

from __future__ import annotations

import re

from ..._one_value import left_out, one_value_tree, splits
from ..._user_secrets import classify_hash, format_review_comment, is_migratable
from ..._usm_keys import PLAINTEXT, user_usm_is_migratable, user_usm_kind
from ...canonical.intent import CanonicalIntent, CanonicalRoutingInstance
from .._helpers import (
    _coalesce_vlan_ids,
    every_native_vlan_tagged,
    native_vlan_stated,
    same_vendor_version,
    switchport_trunk_allowed_value,
    switchport_trunk_native_value,
    wants_no_untagged_vlan,
)
from . import port_names as _port_names

#: Written where a native line would be, on a trunk that carries no
#: VLAN untagged and whose list holds VLAN 1, in an output that cannot
#: say ``vlan dot1q tag native`` of every trunk
#: (:func:`.._helpers.every_native_vlan_tagged`).  What it says of
#: NX-OS is Cisco's (the vendor reference's VLAN page): a trunk with no
#: native VLAN ID uses the default VLAN, which is VLAN1, and the global
#: line changes the native VLAN of all trunks on the device.
_NO_UNTAGGED_REVIEW = (
    "  ! review: this trunk carries no VLAN untagged in the translated "
    "config; on NX-OS a trunk with no native line uses the default VLAN, "
    "VLAN 1, and this one's allowed list holds VLAN 1; vlan dot1q tag "
    "native would tag it, and changes the native VLAN of every trunk of "
    "the device -- check what this port is to carry untagged"
)

#: Canonical algorithm token -> NX-OS ``password <type>`` digit.  Keys mirror
#: ``_TARGET_ACCEPTS["cisco_nxos"]`` exactly (guarded).  Type 0 is NX-OS's
#: CLEARTEXT marker, so only a genuine plaintext password may reach it.
_NXOS_PASSWORD_TYPE: dict[str, str] = {
    "plaintext": "0",
    "5": "5",
    "md5crypt": "5",
    "sha256crypt": "5",
}

#: Synthesised NX-OS release stamped into the banner when the source device's
#: own release is unknown.  When the tree was parsed from THIS codec and
#: carries a ``source_version`` (i.e. sanitize / NX-OS→NX-OS re-render), that
#: real release is echoed instead — otherwise a same-vendor pass silently
#: relabels the device's config with a constant.  Comparator-invisible
#: (``source_version`` is metadata-excluded from every comparator).
_DEFAULT_VERSION = "9.3(11)"


def _version_token(tree: CanonicalIntent) -> str:
    """The NX-OS release to stamp: the device's own when same-vendor and
    known, else the synthetic default (review #63 — shared helper)."""
    return same_vendor_version(
        tree, vendor_id="cisco_nxos", default=_DEFAULT_VERSION
    )

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


def _render_management_plane(tree: CanonicalIntent) -> list[str]:
    """Domain / DNS / NTP / syslog lines (promotion #4).  NX-OS render-dropped
    these until the wire-up; grammar mirrors the codec's own real fixtures
    (``ip domain-name`` / ``ip name-server`` / ``ntp server`` / ``logging
    server``).  Parse harvests each back (see ``_parse_globals``).  Returns a
    trailing ``""`` separator only when at least one line was emitted."""
    out: list[str] = []
    if tree.domain:
        out.append(f"ip domain-name {tree.domain}")
    out.extend(f"ip name-server {srv}" for srv in tree.dns_servers)
    out.extend(f"ntp server {srv}" for srv in tree.ntp_servers)
    out.extend(f"logging server {srv}" for srv in tree.syslog_servers)
    if out:
        out.append("")
    return out


def render_intent(tree: CanonicalIntent) -> str:
    """Render a :class:`CanonicalIntent` as Cisco NX-OS config text."""
    # A name that is not one word where NX-OS reads one is written as
    # one, at every place it goes; an address is left out; a contact,
    # whose place Cisco's pages disagree on, is written and said.
    # Policy: :mod:`netcanon.migration._one_value`.
    tree, one_value_said = one_value_tree(
        tree, "NX-OS",
        names=("hostname", "vlans[].name", "routing_instances[].name"),
        addresses=(
            "domain", "ntp_servers", "syslog_servers", "dns_servers",
            "static_routes[].gateway",
        ),
        unread_text=("snmp.contact",),
    )
    hostname = tree.hostname or "switch"
    lines: list[str] = []

    # ── Banner / version / vdc wrapper ──
    lines.append("!Command: show running-config")
    lines += [f"! {said}" for said in one_value_said]
    lines.append("")
    lines.append(f"version {_version_token(tree)} Bios:version")
    lines.append(f"hostname {hostname}")
    lines.append(f"vdc {hostname} id 1")
    lines.append("")

    # ── Management plane — domain / DNS / NTP / syslog (promotion #4) ──
    lines.extend(_render_management_plane(tree))

    # ── Render-derived feature block ──
    features = _derive_features(tree)
    for feat in features:
        lines.append(f"feature {feat}")
    if features:
        lines.append("")

    # ── Distributed Anycast Gateway — chassis-wide MAC ──
    # The per-SVI `fabric forwarding mode anycast-gateway` markers are
    # emitted inside the interface stanzas below; both are needed for the
    # DAG fabric to function.  Canonical colon-hex → NX-OS dotted-triplet.
    if tree.anycast_gateway_mac:
        dotted = _mac_to_dotted_triplet(tree.anycast_gateway_mac)
        if dotted:
            lines.append(f"fabric forwarding anycast-gateway-mac {dotted}")
            lines.append("")

    # ── Local users + SNMP (Phase 2b) ──
    for user in tree.local_users:
        lines.append(_render_local_user(user))
    if tree.local_users:
        lines.append("")
    if tree.snmp is not None:
        snmp_lines = _render_snmp(tree.snmp, tree.source_vendor)
        if snmp_lines:
            lines.extend(snmp_lines)
            lines.append("")

    # ── Static routes (default VRF only) ──
    default_vrf_routes = [r for r in tree.static_routes if not r.vrf]
    for route in default_vrf_routes:
        lines.append(_render_static_route(route))
    if default_vrf_routes:
        lines.append("")

    # ── Native VLANs sent tagged ──
    # A trunk that carries no VLAN untagged and whose list holds VLAN 1
    # is said so by the one form Cisco documents for it on the Nexus
    # 9000 (the vendor reference's VLAN page) -- which says it of EVERY
    # trunk of the device, and so is written only where it is true of
    # every one.  Elsewhere such a trunk has a review line.
    tag_every_native = every_native_vlan_tagged("cisco_nxos", tree.interfaces)
    if tag_every_native:
        lines.append("vlan dot1q tag native")
        lines.append("")

    # ── VLANs (coalesced id-list + per-name / vn-segment stanzas) ──
    # A VLAN gets a body stanza when it has a name and/or a VXLAN VNI
    # (``vn-segment``).  VXLAN vlan-ids that lack a top-level vlan record
    # are still declared (the id-list + a body stanza) so the
    # vn-segment binding survives cross-vendor sources.
    vni_by_vlan = {x.vlan_id: x.vni for x in tree.vxlan_vnis}
    all_vlan_ids = sorted({v.id for v in tree.vlans} | set(vni_by_vlan))
    if all_vlan_ids:
        lines.append(f"vlan {_coalesce_vlan_ids(all_vlan_ids)}")
        names = {v.id: v.name for v in tree.vlans if v.name}
        for vid in all_vlan_ids:
            name = names.get(vid)
            vni = vni_by_vlan.get(vid)
            if name or vni is not None:
                lines.append(f"vlan {vid}")
                if name:
                    lines.append(f"  name {name}")
                if vni is not None:
                    lines.append(f"  vn-segment {vni}")
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
    # A trunk may be given the review line where the output does not
    # say the line for every trunk, and no record of its interface
    # has a native VLAN.
    stated = native_vlan_stated(tree.interfaces)
    for iface in _sort_interfaces_nxos(tree.interfaces):
        lines.extend(_render_interface(
            iface, lag_mode_by_name, not tag_every_native and iface.name not in stated,
        ))

    # ── VTEP (interface nve1) — Phase 4 VXLAN-EVPN ──
    lines.extend(_render_nve(tree))

    # ── Footers (synthesised defaults) ──
    lines.append("line console")
    lines.append("line vty")
    lines.append(f"boot nxos bootflash:/nxos.{_version_token(tree)}.bin")

    return "\n".join(lines) + "\n"


def _derive_features(tree: CanonicalIntent) -> list[str]:
    """Return the sorted ``feature`` list the render must emit.

    NX-OS feature-gates are derived from the canonical-tree shape (not a
    canonical primitive — see ``03-canonical-mapping.md`` § 5): any SVI →
    ``interface-vlan``, any LAG → ``lacp``, any FHRP group → ``hsrp``, and
    any VXLAN VNI / L3VNI → ``nv overlay`` + ``vn-segment-vlan-based``.
    """
    features: set[str] = set()
    if any(_is_svi(i.name) for i in tree.interfaces):
        features.add("interface-vlan")
    # A tunnel interface is invalid on a real Nexus without ``feature
    # tunnel``.  Fire on EITHER the ``Tunnel`` name prefix (a bare ``interface
    # TunnelN`` whose canonical carries no tunnel_type) OR a GRE/IP-in-IP encap
    # (``tunnel_type`` set on an ``ianaift:tunnel`` interface).  The second arm
    # matches the same predicate the ``tunnel mode`` emitter uses, so a tunnel
    # whose canonical NAME does not start with "tunnel" (e.g. MikroTik
    # ``gre-tunnel1``) no longer emits ``tunnel mode gre ip`` without its
    # feature gate (HEAD-review Fid-F9).  It deliberately does NOT match
    # ``nve1`` — a VXLAN VTEP is ``interface_type=="ianaift:tunnel"`` but
    # carries no ``tunnel_type`` and is gated by ``feature nv overlay``.
    if any(
        i.name.lower().startswith("tunnel")
        or (i.tunnel_type and i.interface_type == "ianaift:tunnel")
        for i in tree.interfaces
    ):
        features.add("tunnel")
    if tree.lags:
        features.add("lacp")
    if any(i.vrrp_groups for i in tree.interfaces):
        features.add("hsrp")
    if tree.vxlan_vnis or any(
        ri.l3_vni is not None for ri in tree.routing_instances
    ):
        features.add("nv overlay")
        features.add("vn-segment-vlan-based")
    return sorted(features)


def _is_svi(name: str) -> bool:
    return _port_names.classify_port_name(name).kind == "svi"


def _render_static_route(route) -> str:
    """Render one static route as ``ip route DEST/N GW [pref]`` (or
    ``ipv6 route`` for an IPv6 destination).

    ``destination`` is already CIDR (``X/N``).  Next-hop is the gateway
    IP, or the interface name for a directly-attached next-hop.  A
    non-zero ``metric`` re-emits as the trailing preference token.  NX-OS
    keys the address family off the keyword: an IPv6 destination must use
    ``ipv6 route`` (``ip route <v6>`` is invalid and rejected on commit).
    """
    nexthop = route.gateway or route.interface
    # Two-token next-hop ``<iface> <gateway>``: emit BOTH, interface first, per
    # the ``ip route <dest> <iface> <gateway>`` grammar — else a route carrying
    # both fields drops the interface (HEAD-review L1-9 render half).
    if route.interface and route.gateway:
        nexthop = f"{route.interface} {route.gateway}"
    keyword = "ipv6 route" if ":" in (route.destination or "") else "ip route"
    out = f"{keyword} {route.destination} {nexthop}".rstrip()
    if route.metric:
        out += f" {route.metric}"
    return out


def _render_local_user(user) -> str:
    """Render a ``username <name> password <type> <hash> role <role>``.

    The secret goes through the shared :func:`is_migratable` gate first.
    This codec used to re-emit any value without a leading type digit as
    ``password 0 <value>`` — NX-OS's CLEARTEXT marker — so a foreign digest
    (a VyOS ``$6$``, an OPNsense bcrypt, a FortiGate ``ENC`` blob) became
    the literal password.  A secret NX-OS cannot consume now drops the
    account and leaves a review comment instead; a consumable one is
    re-tagged from :data:`_NXOS_PASSWORD_TYPE`.  ``role`` is emitted verbatim when set
    (same-vendor round-trip) and otherwise derived from the privilege
    level (network-admin >= 15, else network-operator).
    """
    role = user.role or (
        "network-admin" if user.privilege_level >= 15 else "network-operator"
    )
    # Name, password and role are one word each on this line: a second
    # word of a password is read as the next keyword (`secret scrypt` sets
    # the password `secret`).  The account is left out whole rather than
    # altered.  Policy: :mod:`netcanon.migration._one_value`.
    payload = (
        classify_hash(user.hashed_password)[1] if user.hashed_password else ""
    )
    # A secret this target cannot take at all is the hash gate's to
    # say (below); this asks only of one it would write.
    if splits(user.name) or splits(role) or (
        splits(payload)
        and is_migratable(user.hashed_password, "cisco_nxos")
    ):
        return "! " + left_out(f"username {user.name}", "Cisco NX-OS")
    if not user.hashed_password:
        return f"username {user.name} role {role}"
    algorithm, payload = classify_hash(user.hashed_password)
    if not is_migratable(user.hashed_password, "cisco_nxos"):
        return format_review_comment(
            user.name, algorithm,
            comment_syntax="exclamation", target_label="Cisco NX-OS",
        )
    htype = _NXOS_PASSWORD_TYPE[algorithm]
    return f"username {user.name} password {htype} {payload} role {role}"


def _render_snmp(snmp, source_vendor: str = "") -> list[str]:
    """Render NX-OS ``snmp-server`` lines (v2c community + v3 USM users).

    v3 privacy cipher denormalises canonical -> NX-OS (``aes128`` ->
    ``aes-128``); opaque keys re-emit verbatim with the ``localizedkey``
    keyword (the 10.x ``localizedV2key`` digest is not modelled —
    declared lossy).  ``engineID`` (colon-decimal) re-emits verbatim.
    """
    lines: list[str] = []
    # A community is one word: `snmp-server community public rw` is a
    # READ-WRITE community `public`.  One that holds white space is left
    # out, with every trap host that would carry it.
    community_splits = splits(snmp.community)
    if community_splits:
        lines.append("! " + left_out("an SNMP community", "Cisco NX-OS"))
    elif snmp.community:
        lines.append(f"snmp-server community {snmp.community}")
    if snmp.location:
        lines.append(f"snmp-server location {snmp.location}")
    if snmp.contact:
        lines.append(f"snmp-server contact {snmp.contact}")
    # NX-OS needs `traps version 2c <community>`; a bare
    # `snmp-server host <ip>` is rejected AND silently discarded
    # snmp.community.  Authentic corpus form:
    # `snmp-server host 10.1.1.1 traps version 2c networktocode`.
    for host in snmp.trap_hosts:
        if community_splits:
            lines.append(
                "! " + left_out(f"snmp-server host {host}", "Cisco NX-OS")
            )
            continue
        community = snmp.community or "public"
        lines.append(f"snmp-server host {host} traps version 2c {community}")
        if not snmp.community:
            lines.append(
                f"! snmp-server host {host} -- review: the source carried "
                f"no SNMP community, so `public` was synthesised to keep "
                f"the trap target valid; set the real community or convert "
                f"this host to v3"
            )
    for user in snmp.v3_users:
        # ⚠️ An SNMPv3 USM key is localised against the agent's OWN engine ID.
        # This render emitted whatever key it was handed and then appended
        # ``localizedkey``, which tells the Nexus "this digest is already mine"
        # — true only for an NX-OS source.  A foreign digest (Junos, VyOS), an
        # AOS-CX ciphertext blob or a FortiGate ``ENC`` value produced a v3 user
        # that commits clean and authenticates nobody.  A PASSPHRASE is the one
        # portable shape: emitted WITHOUT the keyword, NX-OS localises it
        # itself, so those now migrate correctly instead of being mislabelled.
        # Policy: :mod:`netcanon.migration._usm_keys`.
        if user.auth_protocol and not user_usm_is_migratable(
            user, source_vendor, "cisco_nxos",
        ):
            kind = user_usm_kind(user, source_vendor)
            lines.append(
                f"! snmpv3 user {user.name} -- review: a {kind} USM key is "
                f"bound to the source agent's engine ID and cannot be re-used "
                f"on NX-OS; re-create this user and re-key it on the target"
            )
            continue
        # Name, group and both passphrases are one word each here.
        if any(
            splits(v) for v in (
                user.name, user.group, user.auth_passphrase,
                user.priv_passphrase,
            )
        ):
            lines.append(
                "! " + left_out(f"snmpv3 user {user.name}", "Cisco NX-OS")
            )
            continue
        # One keyword covers the whole line, so it must describe the least
        # portable key the user carries.
        localised = user_usm_kind(user, source_vendor) != PLAINTEXT
        line = f"snmp-server user {user.name}"
        if user.group:
            line += f" {user.group}"
        if user.auth_protocol:
            line += f" auth {user.auth_protocol} {user.auth_passphrase}"
            # Emit ``priv`` whenever a privacy passphrase is set — gating on
            # ``priv_protocol`` instead would DROP the key for the bare
            # ``priv <key>`` (default-DES, no explicit cipher) form, whose
            # canonical ``priv_protocol`` is empty.  The cipher token is
            # emitted only when present (``priv aes-128 <key>``); absent it
            # round-trips the default-DES form (``priv <key>``).
            if user.priv_passphrase:
                if user.priv_protocol:
                    priv = _CANON_TO_NXOS_PRIV.get(
                        user.priv_protocol, user.priv_protocol,
                    )
                    line += f" priv {priv} {user.priv_passphrase}"
                else:
                    line += f" priv {user.priv_passphrase}"
            # Claim the key is pre-localised only when it actually is.  A
            # passphrase carrying this keyword is stored as a digest, and
            # authentication then fails on the target.
            if localised:
                line += " localizedkey"
        if user.engine_id:
            line += f" engineID {user.engine_id}"
        lines.append(line)
    return lines


def _render_vrf_context(ri: CanonicalRoutingInstance, routes=None) -> list[str]:
    """Render a ``vrf context <name>`` block.

    Emits ``description``, ``vni`` (the Phase-4 L3VNI for symmetric IRB),
    ``rd`` (the ``auto`` sentinel re-emits verbatim), an ``address-family
    ipv4 unicast`` sub-block with ``route-target`` lines (the compact
    ``both <rt>`` form when an RT is in both import + export), and any
    per-VRF static routes nested inside the block.  The source's ``evpn``
    address-family discriminator is NOT re-emitted (declared lossy — the
    RT survives, the L2VPN-EVPN scope reverts to IPv4 unicast).
    """
    block = [f"vrf context {ri.name}"]
    if ri.description:
        block.append(f"  description {ri.description}")
    if ri.l3_vni is not None:
        block.append(f"  vni {ri.l3_vni}")
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
    exported, imported = set(exports), set(imports)
    both = [rt for rt in imports if rt in exported]
    imp_only = [rt for rt in imports if rt not in exported]
    exp_only = [rt for rt in exports if rt not in imported]
    lines: list[str] = []
    for rt in both:
        lines.append(f"    route-target both {rt}")
    for rt in imp_only:
        lines.append(f"    route-target import {rt}")
    for rt in exp_only:
        lines.append(f"    route-target export {rt}")
    return lines


def _render_nve(tree: CanonicalIntent) -> list[str]:
    """Render the ``interface nve1`` VTEP stanza from VXLAN + L3VNI data.

    NX-OS uses exactly one VTEP (``nve1``).  L2 VNIs come from
    ``tree.vxlan_vnis`` (one ``member vni <vni>`` each, joined to a VLAN
    via the ``vlan N / vn-segment`` lines rendered earlier); L3VNIs come
    from ``routing_instances[].l3_vni`` (``member vni <l3vni>
    associate-vrf``).  ``source-interface`` is the switch-level VTEP
    source (broadcast across every CanonicalVxlan record; falls back to
    ``loopback0`` when undeclared).  ``host-reachability protocol bgp`` is
    the constant modern BGP-EVPN head-end default.  Per-VNI flooding is
    emitted from the canonical record: ``mcast-group`` (multicast
    flood-and-learn) when set, else a ``ingress-replication protocol
    static`` / ``peer-ip`` block when ``flood_list`` is set (static
    head-end replication).  The per-VNI ``suppress-arp`` sub-flag is not
    modelled (declared lossy).  Returns an empty list when the switch
    carries no overlay.
    """
    l3_vnis = sorted(
        ri.l3_vni for ri in tree.routing_instances if ri.l3_vni is not None
    )
    if not tree.vxlan_vnis and not l3_vnis:
        return []
    source_iface = next(
        (x.source_interface for x in tree.vxlan_vnis if x.source_interface), "",
    ) or "loopback0"
    block = [
        "interface nve1",
        "  no shutdown",
        "  host-reachability protocol bgp",
        f"  source-interface {source_iface}",
    ]
    for v in sorted(tree.vxlan_vnis, key=lambda x: x.vni):
        block.append(f"  member vni {v.vni}")
        if v.mcast_group:
            block.append(f"    mcast-group {v.mcast_group}")
        elif v.flood_list:
            block.append("    ingress-replication protocol static")
            for peer in v.flood_list:
                block.append(f"      peer-ip {peer}")
    for l3 in l3_vnis:
        block.append(f"  member vni {l3} associate-vrf")
    return block


def _render_switchport_lines(iface, may_review: bool = False) -> list[str]:
    """The L2 switchport config lines for an interface (empty for the
    inherently-L3 kinds: SVI / loopback / mgmt / VTEP / tunnel).

    *may_review*: the output does not say ``vlan dot1q tag native``,
    and no record of this interface has a native VLAN
    (:func:`.._helpers.native_vlan_stated`), so a trunk that carries no
    VLAN untagged and whose list holds VLAN 1 is given a review line.

    Extracted from ``_render_interface`` to keep it under the cyclomatic-
    complexity gate.  Physical, LAG, and unknown cross-vendor names default
    to L2 on NX-OS, so a routed one gets an explicit ``no switchport``.
    """
    kind = _port_names.classify_port_name(iface.name).kind
    if kind in ("svi", "loopback", "mgmt", "vtep", "tunnel"):
        return []
    out: list[str] = []
    if iface.switchport_mode == "access":
        if iface.access_vlan is not None:
            out.append(f"  switchport access vlan {iface.access_vlan}")
        else:
            out.append("  switchport mode access")
    elif iface.switchport_mode == "trunk":
        out.append("  switchport mode trunk")
        # No native line for VLAN 1 on a trunk whose list holds it:
        # that is the platform's default, and no real capture prints
        # the line.  A native VLAN the list leaves out is written
        # whatever its id (stated, and not carried).
        native_vlan = switchport_trunk_native_value(
            "cisco_nxos", iface.trunk_allowed_vlans, iface.trunk_native_vlan,
        )
        if native_vlan is not None:
            out.append(f"  switchport trunk native vlan {native_vlan}")
        elif may_review and wants_no_untagged_vlan(
            "cisco_nxos", iface.trunk_allowed_vlans, iface.trunk_native_vlan,
        ):
            out.append(_NO_UNTAGGED_REVIEW)
        # The list means what it says.  No VLAN is ``none``.  Every
        # VLAN is no line at all: it is the default and what the
        # device prints, and ``1-4094`` names the ids NX-OS keeps for
        # itself, which it does not take in a list.  Any other list is
        # written as ranges.
        vlist = switchport_trunk_allowed_value(
            "cisco_nxos", iface.trunk_allowed_vlans, coalesce=True,
        )
        if vlist is not None:
            out.append(f"  switchport trunk allowed vlan {vlist}")
    elif iface.ipv4_addresses or iface.ipv6_addresses:
        # Routed physical / LAG port — state the L3 intent explicitly.
        out.append("  no switchport")
    return out


def _render_interface(iface, lag_mode_by_name: dict, may_review: bool = False) -> list[str]:
    """Render one interface stanza (*may_review*: see
    :func:`_render_switchport_lines`).

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

    # Tunnel encapsulation mode.  NX-OS spells GRE ``tunnel mode gre ip``
    # and IP-in-IP ``tunnel mode ipip``.  Only gre/ipip have a clean NX-OS
    # interface-encap equivalent; ipsec/vxlan/eoip carry no such line and
    # stay dropped (declared lossy on /interfaces/interface/tunnel-type).
    if iface.tunnel_type and iface.interface_type == "ianaift:tunnel":
        _tt = iface.tunnel_type.lower()
        if _tt == "gre":
            block.append("  tunnel mode gre ip")
        elif _tt == "ipip":
            block.append("  tunnel mode ipip")

    block.extend(_render_switchport_lines(iface, may_review))

    if iface.vrf:
        block.append(f"  vrf member {iface.vrf}")
    # GAP 7: routed sub-interface 802.1Q tag (lowercase dot1q on NX-OS).
    if iface.dot1q_vlan is not None:
        block.append(f"  encapsulation dot1q {iface.dot1q_vlan}")
    for addr in iface.ipv4_addresses:
        line = f"  ip address {addr.ip}/{addr.prefix_length}"
        if addr.is_secondary:
            line += " secondary"
        block.append(line)
    # ── Distributed Anycast Gateway per-SVI marker ──
    # The primary IP IS the distributed gateway (virtual_gateway_address
    # == ip — the DAG / SD-Access mirror shape), so emit the per-SVI
    # `fabric forwarding mode anycast-gateway` line once.  A cross-vendor
    # source whose virtual_gateway_address differs from the IP (Junos /
    # Arista VARP separate VIP) has no DAG equivalent and is skipped.
    if any(
        a.virtual_gateway_address and a.virtual_gateway_address == a.ip
        for a in iface.ipv4_addresses
    ):
        block.append("  fabric forwarding mode anycast-gateway")
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
            if scheme in ("md5", "plain") and splits(key):
                # The key is one word; the group is kept without it.
                block.append(
                    "    ! " + left_out(
                        f"hsrp {group.group_id} authentication", "Cisco NX-OS",
                    )
                )
            elif scheme == "md5":
                block.append(f"    authentication md5 key-string {key}")
            elif scheme == "plain":
                block.append(f"    authentication text {key}")

    if iface.lag_member_of:
        m = re.search(r"(?<!\d)(\d+)\s*$", iface.lag_member_of)
        if m:
            mode = _CANON_TO_NXOS_LAG_MODE.get(
                lag_mode_by_name.get(iface.lag_member_of, "active"), "active",
            )
            block.append(f"  channel-group {m.group(1)} mode {mode}")
    return block


def _mac_to_dotted_triplet(mac: str) -> str:
    """Convert a canonical colon-hex MAC to NX-OS dotted-triplet form.

    NX-OS emits MAC addresses as ``aabb.ccdd.eeff``; the canonical model
    stores colon-hex (``aa:bb:cc:dd:ee:ff``).  Returns empty string for
    malformed input so the caller skips the emit rather than poisoning
    the wire.  Forked from cisco_iosxe_cli per the duplicate-rather-than-
    lift convention.
    """
    if not mac:
        return ""
    hex_only = re.sub(r"[^0-9a-fA-F]", "", mac).lower()
    if len(hex_only) != 12:
        return ""
    return f"{hex_only[0:4]}.{hex_only[4:8]}.{hex_only[8:12]}"


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
