"""
Render path: emits set-form Junos config from CanonicalIntent.

Public function: :func:`render_intent` — :class:`CanonicalIntent`
in, Junos ``set``-form text out.

Emits the same surfaces the parse path consumes: hostname / domain /
DNS / NTP / syslog (under ``set system``), local users
(``set system login user``), interfaces (with IPv4 / IPv6, MTU,
disable, sub-interface unit splits, access_vlan as per-unit
``vlan-id``), interface-range auto-collapse for >=3 simple
interfaces sharing a (mtu, description, enabled) tuple, VLANs
(plus VLAN-to-VNI mappings for VXLAN), switch-options
(``vtep-source-interface`` / ``vxlan-port`` switch-level globals),
routing-instances (instance-type, RD/RT, interface bindings, L3
VNI for EVPN Type-5), routing-options static routes, SNMP
(community / location / contact / trap-group / v3 USM users +
VACM groups), and apply-groups + group-content for round-trip
fidelity (GAP 9b).

Strings with whitespace or shell-special characters are double-
quoted via :func:`_quote_if_needed`; free-text fields use
:func:`_quote_always`.  Hashes stored under the ``junos:<hash>``
vendor tag get their prefix stripped on render so
``parse(render(tree))`` is a true round-trip.

Apply-groups inheritance is wired both ways: parse buckets group
content separately and replays it via the two-pass dispatch in
``parse.py``; render re-emits the captured group bodies + the
``set apply-groups`` statements so the rendered output looks like
hand-written Junos again.

Extracted verbatim from ``codec.py`` during the parse/render split;
behaviour is identical to the prior in-class implementation.  The
codec module's ``render()`` method is now a one-line delegator to
:func:`render_intent`.

Internal helpers (``_split_subiface_name``, ``_quote_if_needed``,
``_quote_always``) and module-level constants (``_QUOTE_NEEDED_RE``,
``_SUBIFACE_RE``) live here because they are render-only.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ...canonical.intent import CanonicalIntent

logger = logging.getLogger(__name__)


def render_intent(tree: Any) -> str:
    """Render a :class:`CanonicalIntent` to Junos ``set``-form text.

    Emits commands in a deterministic order so repeated renders of
    the same tree produce byte-identical output (important for
    diff-based deployment + snapshot compare).

    Order:
        1. ``set system host-name``
        2. ``set system login user ...`` (role + encrypted-password)
        3. ``set interfaces <name> description / disable / unit 0
           family inet address``
        4. ``set vlans <NAME> vlan-id``
        5. ``set routing-options static route``
        6. ``set snmp community / location / contact / trap-group
           targets``

    Strings with spaces or shell-special chars are double-quoted;
    bare tokens stay unquoted.  Hashes tagged ``junos:<hash>`` get
    their prefix stripped so parse(render(tree)) round-trips.
    """
    if not isinstance(tree, CanonicalIntent):
        raise TypeError(
            "juniper_junos.render: expected CanonicalIntent, got "
            f"{type(tree).__name__}"
        )

    out: list[str] = []

    # --- system ---
    if tree.hostname:
        out.append(f"set system host-name {_quote_if_needed(tree.hostname)}")
    if tree.domain:
        out.append(f"set system domain-name {_quote_if_needed(tree.domain)}")
    for dns in tree.dns_servers:
        out.append(f"set system name-server {dns}")
    for ntp in tree.ntp_servers:
        out.append(f"set system ntp server {ntp}")
    for syslog in tree.syslog_servers:
        out.append(f"set system syslog host {syslog} any any")

    # --- login users ---
    for user in tree.local_users:
        if user.role:
            role = user.role
        elif user.privilege_level >= 15:
            role = "super-user"
        elif user.privilege_level >= 5:
            role = "operator"
        else:
            role = "read-only"
        out.append(
            f"set system login user {_quote_if_needed(user.name)} "
            f"class {_quote_if_needed(role)}"
        )
        if user.hashed_password:
            # Strip the ``junos:`` vendor tag on render; canonical
            # storage prefixes it on parse to mark Junos-sourced
            # hashes.
            hsh = user.hashed_password
            if hsh.startswith("junos:"):
                hsh = hsh[len("junos:"):]
            out.append(
                f"set system login user {_quote_if_needed(user.name)} "
                f"authentication encrypted-password "
                f"{_quote_always(hsh)}"
            )

    # --- structural collapse detection (render-side auto-
    #     synthesise interface-range blocks for ≥3 interfaces
    #     sharing identical shared-attr tuples) ---
    #
    # Only applies to "simple" interfaces (not sub-interfaces,
    # not VRF-bound, not LAG members) since those have richer
    # per-interface semantics.  Shared attrs we collapse on:
    # mtu + description.  Emit `set interfaces interface-range
    # <auto-name> member <iface>` + one line per shared attr.
    # Per-interface render SUPPRESSES the shared attrs when the
    # interface is a range member.
    range_emit_by_name: dict[str, list[str]] = {}
    iface_range_membership: dict[str, str] = {}
    collapsed_iface_count = 0
    _candidates: dict[tuple, list[str]] = {}
    for iface in tree.interfaces:
        # Skip sub-interfaces (they emit under parent/unit).
        _parent, _unit = _split_subiface_name(iface.name)
        if _parent is not None and _unit is not None:
            continue
        # Skip VRF-bound interfaces (per-VRF semantics matter
        # too much to auto-collapse across them).
        if iface.vrf:
            continue
        # Skip access-vlan / switchport / trunk-configured
        # interfaces.  Collapse only ROUTED or BARE interfaces.
        if (
            iface.access_vlan is not None
            or iface.switchport_mode is not None
            or iface.trunk_allowed_vlans
        ):
            continue
        # Collapse key: (mtu, description, enabled).  We DON'T
        # include IP addresses — those are per-interface.
        key = (iface.mtu, iface.description, iface.enabled)
        # Skip all-default tuples — nothing worth collapsing.
        if key == (None, "", True):
            continue
        _candidates.setdefault(key, []).append(iface.name)
    # Promote candidate groups with ≥3 members into
    # interface-range emissions.
    _next_range_id = 1
    for key, members in sorted(_candidates.items(), key=lambda kv: (
        # Sort by member count descending so AUTO-RANGE-1 is the
        # biggest group.
        -len(kv[1]), sorted(kv[1])[0] if kv[1] else "",
    )):
        if len(members) < 3:
            continue
        range_name = f"AUTO-RANGE-{_next_range_id}"
        _next_range_id += 1
        lines: list[str] = []
        for m in members:
            lines.append(
                f"set interfaces interface-range {range_name} "
                f"member {m}"
            )
            iface_range_membership[m] = range_name
        mtu, description, enabled = key
        if description:
            lines.append(
                f"set interfaces interface-range {range_name} "
                f"description {_quote_always(description)}"
            )
        if mtu is not None:
            lines.append(
                f"set interfaces interface-range {range_name} "
                f"mtu {mtu}"
            )
        if not enabled:
            lines.append(
                f"set interfaces interface-range {range_name} "
                f"disable"
            )
        range_emit_by_name[range_name] = lines
        collapsed_iface_count += len(members)

    # Emit interface-range blocks FIRST so operators see the
    # shared config before per-interface specifics.
    for _rname, lines in range_emit_by_name.items():
        out.extend(lines)

    # --- interfaces ---
    for iface in tree.interfaces:
        name = iface.name
        has_renderable_attr = (
            bool(iface.description)
            or (not iface.enabled)
            or bool(iface.ipv4_addresses)
            or bool(iface.ipv6_addresses)              # GAP-EVPN-3
        )
        # Structural collapse: if this interface is a member of
        # an auto-synthesised range, suppress the shared-attr
        # emission (description + mtu + disable).  Per-interface
        # specifics (IP addresses) still emit.
        is_range_member = name in iface_range_membership
        emit_description = (
            bool(iface.description) and not is_range_member
        )
        emit_mtu = (iface.mtu is not None) and not is_range_member
        emit_disable = (not iface.enabled) and not is_range_member
        # GAP 4: sub-interface naming.  The parse side materialises
        # ``set interfaces <parent> unit N ...`` (N>0) as a
        # CanonicalInterface named ``<parent>.<N>``.  Render has to
        # split the compound name back into parent + unit so the
        # emitted set-lines use Junos's native grammar.
        parent, unit_num = _split_subiface_name(name)
        if parent is not None and unit_num is not None:
            # Sub-interface — emit under parent / unit <N>.
            # GAP 7: include access_vlan in the "renderable"
            # predicate so a bare sub-interface carrying only a
            # vlan-id (no description / no IP) still emits lines
            # and round-trips.
            sub_has_renderable = (
                has_renderable_attr
                or iface.access_vlan is not None
            )
            if iface.description:
                out.append(
                    f"set interfaces {parent} unit {unit_num} "
                    f"description {_quote_always(iface.description)}"
                )
            if not iface.enabled:
                out.append(
                    f"set interfaces {parent} unit {unit_num} disable"
                )
            # GAP 7: per-unit 802.1Q tag.
            if iface.access_vlan is not None:
                out.append(
                    f"set interfaces {parent} unit {unit_num} "
                    f"vlan-id {iface.access_vlan}"
                )
            for addr in iface.ipv4_addresses:
                out.append(
                    f"set interfaces {parent} unit {unit_num} "
                    f"family inet address "
                    f"{addr.ip}/{addr.prefix_length}"
                )
            # GAP-EVPN-3: IPv6 addresses on sub-interfaces.
            # Junos emits scope-uniformly under family inet6 —
            # the canonical scope discriminator is informational
            # only on this codec.
            for v6 in iface.ipv6_addresses:
                out.append(
                    f"set interfaces {parent} unit {unit_num} "
                    f"family inet6 address "
                    f"{v6.ip}/{v6.prefix_length}"
                )
            if not sub_has_renderable:
                out.append(
                    f"set interfaces {parent} unit {unit_num}"
                )
            continue
        # Regular (unit-0 or non-unitised) interface.
        if emit_description:
            out.append(
                f"set interfaces {name} description "
                f"{_quote_always(iface.description)}"
            )
        if emit_disable:
            out.append(f"set interfaces {name} disable")
        if emit_mtu:
            out.append(f"set interfaces {name} mtu {iface.mtu}")
        # IPv4 addresses — emit under unit 0 (v1's convention).
        for addr in iface.ipv4_addresses:
            out.append(
                f"set interfaces {name} unit 0 family inet "
                f"address {addr.ip}/{addr.prefix_length}"
            )
        # GAP-EVPN-3: IPv6 addresses also emit under unit 0.
        for v6 in iface.ipv6_addresses:
            out.append(
                f"set interfaces {name} unit 0 family inet6 "
                f"address {v6.ip}/{v6.prefix_length}"
            )
        # Placeholder: the parse side creates an interface entry
        # for every ``set interfaces <name> ...`` line, even when
        # the trailing tokens land entirely in unmodelled (Tier-3)
        # grammar like ``unit 0 family ethernet-switching ...``.
        # Or: the interface IS range-collapsed with no per-
        # interface specifics (no IP) — still need a placeholder
        # so round-trip keeps the interface in the canonical
        # tree even when the range block alone carries all its
        # attributes.
        if not has_renderable_attr and not is_range_member:
            out.append(f"set interfaces {name}")

    # --- vlans + VLAN-to-VNI mappings (GAP 6) ---
    # Pre-index VXLAN VNIs by vlan_id for matched emission.
    vni_by_vlan = {v.vlan_id: v.vni for v in tree.vxlan_vnis}
    for vlan in tree.vlans:
        vlan_key = vlan.name or f"VLAN-{vlan.id}"
        out.append(
            f"set vlans {_quote_if_needed(vlan_key)} vlan-id {vlan.id}"
        )
        if vlan.id in vni_by_vlan:
            out.append(
                f"set vlans {_quote_if_needed(vlan_key)} vxlan vni "
                f"{vni_by_vlan[vlan.id]}"
            )

    # GAP-EVPN-2: emit ``set switch-options vtep-source-interface ...``
    # + ``set switch-options vxlan-port ...`` once per switch.  These
    # are switch-level on Junos; pull from the first CanonicalVxlan
    # record carrying a non-empty / non-default value.  Skip when no
    # VXLAN records exist (no-op for non-VXLAN configs).
    if tree.vxlan_vnis:
        src_iface = ""
        for v in tree.vxlan_vnis:
            if v.source_interface:
                src_iface = v.source_interface
                break
        udp_port = 4789
        for v in tree.vxlan_vnis:
            if v.udp_port and v.udp_port != 4789:
                udp_port = v.udp_port
                break
        if src_iface:
            out.append(
                f"set switch-options vtep-source-interface {src_iface}"
            )
        if udp_port != 4789:
            out.append(f"set switch-options vxlan-port {udp_port}")

    # --- routing-instances (GAP 6) ---
    # Build a map from vrf_name to interfaces that belong there
    # so we can emit ``set routing-instances <name> interface
    # <iface>`` lines.  Empty ``iface.vrf`` = global VRF, skip.
    ifaces_by_vrf: dict[str, list[str]] = {}
    for iface in tree.interfaces:
        if iface.vrf:
            ifaces_by_vrf.setdefault(iface.vrf, []).append(iface.name)
    for ri in tree.routing_instances:
        out.append(
            f"set routing-instances {_quote_if_needed(ri.name)} "
            f"instance-type {ri.instance_type}"
        )
        if ri.description:
            out.append(
                f"set routing-instances {_quote_if_needed(ri.name)} "
                f"description {_quote_always(ri.description)}"
            )
        if ri.route_distinguisher:
            out.append(
                f"set routing-instances {_quote_if_needed(ri.name)} "
                f"route-distinguisher {ri.route_distinguisher}"
            )
        # vrf-target: collapse to the compact ``target:X`` form when
        # import + export are identical; otherwise emit separate
        # import/export lines.
        if (
            ri.rt_imports == ri.rt_exports and ri.rt_imports
        ):
            for rt in ri.rt_imports:
                out.append(
                    f"set routing-instances {_quote_if_needed(ri.name)} "
                    f"vrf-target target:{rt}"
                )
        else:
            for rt in ri.rt_imports:
                out.append(
                    f"set routing-instances {_quote_if_needed(ri.name)} "
                    f"vrf-target import target:{rt}"
                )
            for rt in ri.rt_exports:
                out.append(
                    f"set routing-instances {_quote_if_needed(ri.name)} "
                    f"vrf-target export target:{rt}"
                )
        # Interface bindings.  Interfaces that are physical
        # sub-iface compound names (``ge-0/0/1.0``) get emitted
        # as-is; parent-only names get a ``.0`` suffix since
        # Junos routing-instances always reference a UNIT (the
        # codec's canonical-name convention collapses unit 0
        # into the parent — we have to reverse that on render).
        for iface_name in ifaces_by_vrf.get(ri.name, []):
            if "." in iface_name:
                ri_iface_name = iface_name
            else:
                ri_iface_name = f"{iface_name}.0"
            out.append(
                f"set routing-instances {_quote_if_needed(ri.name)} "
                f"interface {ri_iface_name}"
            )
        # Type-5 L3 VNI.
        if ri.l3_vni is not None:
            out.append(
                f"set routing-instances {_quote_if_needed(ri.name)} "
                f"protocols evpn ip-prefix-routes vni {ri.l3_vni}"
            )

    # --- routing-options ---
    for route in tree.static_routes:
        if not route.gateway:
            # Junos requires a next-hop for static routes; skip
            # connected/blackhole entries we can't express.
            continue
        out.append(
            f"set routing-options static route {route.destination} "
            f"next-hop {route.gateway}"
        )

    # --- snmp ---
    if tree.snmp is not None:
        if tree.snmp.community:
            out.append(
                f"set snmp community "
                f"{_quote_if_needed(tree.snmp.community)} "
                f"authorization read-only"
            )
        if tree.snmp.location:
            out.append(
                f"set snmp location {_quote_always(tree.snmp.location)}"
            )
        if tree.snmp.contact:
            out.append(
                f"set snmp contact {_quote_always(tree.snmp.contact)}"
            )
        for host in tree.snmp.trap_hosts:
            # Synthesise a trap-group name keyed by sanitised host
            # so two trap hosts don't collide.
            group_name = "targets"
            out.append(
                f"set snmp trap-group {group_name} targets {host}"
            )
        # SNMPv3 users — emit USM (auth / priv keys) lines then
        # VACM (group binding).  Inverse mappings of
        # _JUNOS_AUTH_MAP / _JUNOS_PRIV_MAP.  Empty auth / priv
        # emit nothing for that half — noAuthNoPriv leaves just
        # the VACM binding (expressible on Junos too).
        _auth_to_junos = {
            "md5": "authentication-md5",
            "sha": "authentication-sha",
            "sha224": "authentication-sha224",
            "sha256": "authentication-sha256",
            "sha384": "authentication-sha384",
            "sha512": "authentication-sha512",
        }
        _priv_to_junos = {
            "des": "privacy-des",
            "3des": "privacy-3des",
            "aes": "privacy-aes128",        # canonical "aes" → aes128
            "aes128": "privacy-aes128",
            "aes192": "privacy-aes192",
            "aes256": "privacy-aes256",
        }
        for u in tree.snmp.v3_users:
            if u.auth_protocol and u.auth_protocol in _auth_to_junos:
                auth_cmd = _auth_to_junos[u.auth_protocol]
                out.append(
                    f"set snmp v3 usm local-engine user "
                    f"{_quote_if_needed(u.name)} {auth_cmd} "
                    f"authentication-key "
                    f"{_quote_always(u.auth_passphrase)}"
                )
            if u.priv_protocol and u.priv_protocol in _priv_to_junos:
                priv_cmd = _priv_to_junos[u.priv_protocol]
                out.append(
                    f"set snmp v3 usm local-engine user "
                    f"{_quote_if_needed(u.name)} {priv_cmd} "
                    f"privacy-key "
                    f"{_quote_always(u.priv_passphrase)}"
                )
            if u.group:
                out.append(
                    f"set snmp v3 vacm security-to-group "
                    f"security-model usm security-name "
                    f"{_quote_if_needed(u.name)} group "
                    f"{_quote_if_needed(u.group)}"
                )

    # --- apply-groups / group-content (GAP 9b) ---
    # Emit the full `set groups <G> <body...>` blocks for
    # operator round-trip fidelity, followed by the matching
    # `set apply-groups <G>` statements.  Each group body
    # contains the exact tokens we captured on parse, preserving
    # operator-authored structure.  This produces RE-PARSED
    # canonical trees identical to the ORIGINAL parse (thanks
    # to idempotent list _apply_* functions) AND makes the
    # rendered output look like hand-written Junos again.
    if tree.group_content:
        for gname in tree.apply_groups:
            body = tree.group_content.get(gname)
            if not body:
                continue
            for tokens in body:
                # Re-quote tokens containing whitespace or shell-
                # special chars so the re-parser (shlex-based)
                # re-tokenises to the same token list.
                quoted = " ".join(
                    _quote_if_needed(t) for t in tokens
                )
                out.append(
                    f"set groups {_quote_if_needed(gname)} "
                    f"{quoted}"
                )
    for gname in tree.apply_groups:
        out.append(f"set apply-groups {_quote_if_needed(gname)}")

    result = "\n".join(out)
    if result:
        result += "\n"

    logger.debug(
        "juniper_junos rendered: hostname=%r ifaces=%d vlans=%d "
        "routes=%d users=%d snmp=%s (output=%d chars)",
        tree.hostname,
        len(tree.interfaces),
        len(tree.vlans),
        len(tree.static_routes),
        len(tree.local_users),
        "yes" if tree.snmp else "no",
        len(result),
    )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_QUOTE_NEEDED_RE = re.compile(r"[\s\"';$`\\]")

# ``<parent>.<unit>`` — e.g. ``ge-0/0/0.100``.  ``parent`` must
# contain a slash (``ge-0/0/0``) to distinguish from normal names
# like ``irb.10`` where the dot is part of the base port name.
_SUBIFACE_RE = re.compile(r"^(?P<parent>[A-Za-z]+-\d+/\d+/\d+)\.(?P<unit>\d+)$")


def _split_subiface_name(name: str) -> tuple[str | None, int | None]:
    """Return ``(parent, unit)`` if *name* looks like a Junos physical
    sub-interface (``ge-0/0/0.100``), else ``(None, None)``.

    ``irb.N`` / ``vlan.N`` are excluded by the parent-slash requirement
    — those are SVI-like interfaces that keep the dot in their
    canonical name (rendered as top-level entries, not sub-interfaces).
    """
    m = _SUBIFACE_RE.match(name)
    if m is None:
        return (None, None)
    try:
        return (m.group("parent"), int(m.group("unit")))
    except ValueError:
        return (None, None)


def _quote_if_needed(s: str) -> str:
    """Junos-style quoting: wrap in double quotes only if the string
    contains whitespace or shell-special characters.  Mirrors what
    ``show configuration | display set`` emits natively.

    Returns the input verbatim when no quoting is needed — keeps the
    output clean for the common case of simple hostnames, interface
    names, class names.
    """
    if not s:
        return '""'
    if _QUOTE_NEEDED_RE.search(s):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


def _quote_always(s: str) -> str:
    """Always-quoted variant for free-text fields (description,
    location, contact, password hash).  Junos tolerates quoted simple
    strings; operators expect quotes around free-text regardless.
    """
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
