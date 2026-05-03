"""
FortiGate CLI renderer — canonical tree to FortiOS ``config / edit /
set / next / end`` text.

Extracted from ``codec.py`` during the parse/render split.  Public
surface (consumed by codec.py's ``render()`` method):

* :func:`render_intent` — one-shot render: ``CanonicalIntent`` in,
  FortiOS CLI string out.

The render emits blocks in the same order operator workflows expect
from a FortiOS export: ``system global`` → ``system dns`` →
``system ntp`` → ``system interface`` → ``system snmp`` →
``system admin`` → ``user radius`` → ``system dhcp server`` →
``router static``.  Ordering is stable for diff-friendliness.

Defaults that FortiOS omits on export (e.g. ``set radius-port 1812``,
``set mtu 1500``) are NOT emitted here so our renders round-trip
against real exports — see comments inline for the specific
default-omission choices.

Shares IP-mask utilities (``_prefix_to_mask`` / ``_split_cidr``) and
the canonical→FortiGate LACP-mode map with :mod:`.parse` — those
live in the parse module and are imported here to avoid duplication.
VLAN-naming helpers (``_looks_like_vlan_iface``, ``_vlan_id_for``,
``_parent_for_vlan_iface``) come from :mod:`.vlan_heuristics`.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from ..base import RenderError
from ..._user_secrets import (
    classify_hash,
    format_review_comment,
    is_migratable,
)
from ...canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
)
from .parse import (
    _CANONICAL_MODE_TO_FORTIGATE_LACP,
    _prefix_to_mask,
    _split_cidr,
)
from .vlan_heuristics import (
    looks_like_vlan_iface as _looks_like_vlan_iface,
    parent_for_vlan_iface as _parent_for_vlan_iface,
    vlan_id_for as _vlan_id_for,
)


def _build_vlan_children(
    tree: CanonicalIntent,
    deduped_ifaces: list[CanonicalInterface],
) -> list[dict]:
    """Build the VLAN-on-parent child interface list (Issue #6).

    For every canonical VLAN, synthesise a FortiOS-style child
    entry that the renderer emits inside ``config system interface``
    as ``edit "vlan<id>" / set type vlan / set vlanid <id> / set
    interface "<parent>" / set ip <addr> <mask>``.

    Resolution rules:

    * **Parent** -- first :class:`CanonicalLAG` on the tree (operators
      almost always trunk VLANs over a LAG); fall back to the first
      non-VLAN-shaped interface in *deduped_ifaces* if no LAG
      exists; ``None`` when neither candidate is available.
    * **SVI IP** -- the canonical's ``CanonicalVlan.ipv4_addresses``
      directly if populated; else walk *deduped_ifaces* for a
      matching ``Vlan<id>`` interface name (Cisco-style) and copy
      its ``ipv4_addresses[0]``.

    Returns a list of dicts with keys ``name``, ``vlanid``,
    ``parent``, ``ip``, ``mask`` -- empty list when *tree.vlans* is
    empty.  Caller filters out names that already appear in
    *deduped_ifaces* (intra-vendor round-trip pre-emits them).
    """
    if not tree.vlans:
        return []

    parent_name = None
    if tree.lags:
        parent_name = tree.lags[0].name
    if parent_name is None:
        for cand in deduped_ifaces:
            if not _looks_like_vlan_iface(cand.name) and (
                cand.interface_type != "ianaift:l3ipvlan"
            ):
                parent_name = cand.name
                break

    iface_by_name = {i.name: i for i in deduped_ifaces}

    children = []
    for vlan in tree.vlans:
        ip = ""
        mask = ""
        if vlan.ipv4_addresses:
            addr = vlan.ipv4_addresses[0]
            ip = addr.ip
            try:
                mask = _prefix_to_mask(addr.prefix_length)
            except Exception:
                mask = ""
        else:
            for cand_name in (f"Vlan{vlan.id}", f"vlan{vlan.id}"):
                cand = iface_by_name.get(cand_name)
                if cand and cand.ipv4_addresses:
                    addr = cand.ipv4_addresses[0]
                    ip = addr.ip
                    try:
                        mask = _prefix_to_mask(addr.prefix_length)
                    except Exception:
                        mask = ""
                    break

        children.append({
            "name": f"vlan{vlan.id}",
            "vlanid": vlan.id,
            "parent": parent_name,
            "ip": ip,
            "mask": mask,
        })
    return children


def render_intent(tree: Any) -> str:
    """Render a :class:`CanonicalIntent` tree to FortiOS CLI text.

    Raises :class:`RenderError` when *tree* is not a
    :class:`CanonicalIntent` (mock adapters produce other shapes).
    """
    if not isinstance(tree, CanonicalIntent):
        raise RenderError(
            "fortigate_cli: tree must be a CanonicalIntent.",
            yang_path="/",
        )

    out: list[str] = []
    out.append("#config-version=netconfig-translator")

    # --- system global ---
    if tree.hostname:
        out.append("config system global")
        out.append(f'    set hostname "{tree.hostname}"')
        out.append("end")

    # --- system dns ---
    if tree.dns_servers:
        out.append("config system dns")
        if len(tree.dns_servers) >= 1:
            out.append(f"    set primary {tree.dns_servers[0]}")
        if len(tree.dns_servers) >= 2:
            out.append(f"    set secondary {tree.dns_servers[1]}")
        out.append("end")

    # --- system ntp (nested subtable) ---
    if tree.ntp_servers:
        out.append("config system ntp")
        out.append("    set ntpsync enable")
        out.append("    config ntpserver")
        for idx, server in enumerate(tree.ntp_servers, start=1):
            out.append(f"        edit {idx}")
            out.append(f'            set server "{server}"')
            out.append("        next")
        out.append("    end")
        out.append("end")

    # --- system interface ---
    # Build a quick lookup: which interface names are LAG aggregates?
    lag_by_name: dict[str, CanonicalLAG] = {
        lag.name: lag for lag in tree.lags
    }
    # Also: which names aren't in intent.interfaces but ARE LAGs
    # from intent.lags?  Synthesize interface edits for them so
    # the FortiOS config is self-consistent.
    existing_iface_names = {i.name for i in tree.interfaces}
    synthetic_lag_ifaces = [
        CanonicalInterface(
            name=lag.name,
            interface_type="ianaift:ieee8023adLag",
            enabled=True,
        )
        for lag in tree.lags
        if lag.name not in existing_iface_names
    ]
    all_ifaces = list(tree.interfaces) + synthetic_lag_ifaces

    # Render-time port-name collision guard (Issue #2 from
    # tests/fixtures/real/user_smoke_findings.md).  Belt-and-braces
    # alongside the multi-axis disambiguation in
    # :func:`port_names.format_port_identity`.  We dedup by emission
    # order -- first occurrence wins, later collisions get a
    # ``# port collision: ...`` comment instead of a duplicate
    # ``edit "..."`` block (which FortiOS rejects on commit).
    seen_iface_names = set()
    deduped_ifaces = []
    collision_comments = []
    for iface in all_ifaces:
        if iface.name in seen_iface_names:
            collision_comments.append(
                f"# port collision: {iface.name} already emitted earlier; "
                f"duplicate dropped -- review source names for unique mapping"
            )
            continue
        seen_iface_names.add(iface.name)
        deduped_ifaces.append(iface)

    # VLAN child interface synthesis (Issue #6).
    vlan_children = _build_vlan_children(tree, deduped_ifaces)
    existing_vlan_ids = set()
    for cand in deduped_ifaces:
        vid = _vlan_id_for(cand.name, tree.vlans)
        if vid is not None:
            existing_vlan_ids.add(vid)
    vlan_children = [
        v for v in vlan_children
        if v["name"] not in seen_iface_names
        and v["vlanid"] not in existing_vlan_ids
    ]

    if deduped_ifaces or vlan_children:
        out.append("config system interface")
        for c in collision_comments:
            out.append(f"    {c}")
        for iface in deduped_ifaces:
            out.append(f'    edit "{iface.name}"')
            if iface.description:
                # FortiOS alias caps at 25 chars per spec.
                alias = iface.description[:25]
                out.append(f'        set alias "{alias}"')
            # LAG aggregate marker takes precedence over VLAN.
            lag = lag_by_name.get(iface.name)
            if lag is not None:
                out.append("        set type aggregate")
                if lag.members:
                    quoted = " ".join(f'"{m}"' for m in lag.members)
                    out.append(f"        set member {quoted}")
                out.append(
                    f"        set lacp-mode "
                    f"{_CANONICAL_MODE_TO_FORTIGATE_LACP.get(lag.mode, 'active')}"
                )
            elif (
                iface.interface_type == "ianaift:l3ipvlan"
                or _looks_like_vlan_iface(iface.name)
            ):
                # VLAN identification can come from either signal —
                # canonical interface_type OR FortiGate-native
                # name convention.  Real configs name VLAN ifaces
                # freely (VL_100, DATA, etc.) so name alone isn't
                # sufficient.
                vid = _vlan_id_for(iface.name, tree.vlans)
                parent = _parent_for_vlan_iface(iface.name, tree.interfaces)
                if vid is not None:
                    out.append("        set type vlan")
                    out.append(f"        set vlanid {vid}")
                    if parent:
                        out.append(f'        set interface "{parent}"')
            if iface.ipv4_addresses:
                addr = iface.ipv4_addresses[0]
                mask = _prefix_to_mask(addr.prefix_length)
                out.append(f"        set ip {addr.ip} {mask}")
                out.append("        set mode static")
            # GAP-EVPN-3: IPv6 addresses.  FortiOS uses CIDR
            # natively (``set ip6-address <addr>/<prefix>``); only
            # one v6 address per interface fits the FortiOS schema.
            if iface.ipv6_addresses:
                v6 = iface.ipv6_addresses[0]
                out.append(
                    f"        set ip6-address {v6.ip}/{v6.prefix_length}"
                )
            if iface.mtu is not None:
                # FortiOS requires mtu-override enable before
                # set mtu has effect on physical ports.  Emit
                # both so the config is deployable.
                out.append("        set mtu-override enable")
                out.append(f"        set mtu {iface.mtu}")
            if iface.enabled:
                out.append("        set status up")
            else:
                out.append("        set status down")
            out.append("    next")

        # VLAN child interface emit (Issue #6).
        for child in vlan_children:
            out.append(f'    edit "{child["name"]}"')
            out.append("        set type vlan")
            out.append(f'        set vlanid {child["vlanid"]}')
            if child.get("parent"):
                out.append(f'        set interface "{child["parent"]}"')
            if child.get("ip") and child.get("mask"):
                out.append(f'        set ip {child["ip"]} {child["mask"]}')
                out.append("        set mode static")
            out.append("    next")
        out.append("end")

    # --- system snmp (Tier 2) ---
    if tree.snmp is not None and (
        tree.snmp.community or tree.snmp.location
        or tree.snmp.contact or tree.snmp.trap_hosts
        or tree.snmp.v3_users
    ):
        out.append("config system snmp sysinfo")
        out.append("    set status enable")
        if tree.snmp.location:
            out.append(f'    set location "{tree.snmp.location}"')
        if tree.snmp.contact:
            out.append(f'    set contact-info "{tree.snmp.contact}"')
        out.append("end")
        if tree.snmp.community:
            out.append("config system snmp community")
            out.append("    edit 1")
            out.append(f'        set name "{tree.snmp.community}"')
            if tree.snmp.trap_hosts:
                out.append("        config hosts")
                for idx, host in enumerate(tree.snmp.trap_hosts, start=1):
                    out.append(f"            edit {idx}")
                    out.append(f'                set ip "{host} 255.255.255.255"')
                    out.append("            next")
                out.append("        end")
            out.append("    next")
            out.append("end")
        # SNMPv3 users.  security-level derives from auth/priv
        # presence (noAuthNoPriv / auth-no-priv / auth-priv — the
        # three FortiOS-accepted values).  Canonical priv_protocol
        # back to FortiOS: aes128 → aes; aes256 / aes192 / des
        # preserved.  Unknown / empty auth_protocol → sha fallback
        # to satisfy FortiOS validation when security-level implies
        # auth.
        _CAN_TO_FG_AUTH = {
            "md5": "md5", "sha": "sha", "sha224": "sha256",
            "sha256": "sha256", "sha384": "sha384", "sha512": "sha512",
        }
        _CAN_TO_FG_PRIV = {
            "des": "des", "aes": "aes", "aes128": "aes",
            "aes192": "aes192", "aes256": "aes256", "3des": "aes",
        }
        if tree.snmp.v3_users:
            out.append("config system snmp user")
            for u in tree.snmp.v3_users:
                out.append(f'    edit "{u.name}"')
                if u.auth_protocol and u.priv_protocol:
                    out.append("        set security-level auth-priv")
                elif u.auth_protocol:
                    out.append("        set security-level auth-no-priv")
                else:
                    out.append("        set security-level no-auth-no-priv")
                if u.auth_protocol:
                    fg_auth = _CAN_TO_FG_AUTH.get(u.auth_protocol, "sha")
                    out.append(f"        set auth-proto {fg_auth}")
                    if u.auth_passphrase:
                        # Preserve operator-supplied hash verbatim.
                        # Source-joined ``ENC <hash>`` round-trips as-is;
                        # cross-vendor hashes get an ENC prefix.
                        val = u.auth_passphrase
                        if val.startswith("ENC "):
                            out.append(f'        set auth-pwd "{val}"')
                        else:
                            out.append(f'        set auth-pwd "ENC {val}"')
                if u.priv_protocol:
                    fg_priv = _CAN_TO_FG_PRIV.get(u.priv_protocol, "aes")
                    out.append(f"        set priv-proto {fg_priv}")
                    if u.priv_passphrase:
                        val = u.priv_passphrase
                        if val.startswith("ENC "):
                            out.append(f'        set priv-pwd "{val}"')
                        else:
                            out.append(f'        set priv-pwd "ENC {val}"')
                out.append("    next")
            out.append("end")

    # --- system admin (Tier 2 local users) ---
    if tree.local_users:
        out.append("config system admin")
        for user in tree.local_users:
            out.append(f'    edit "{user.name}"')
            # Hash-portability gate (Issue #1a from
            # tests/fixtures/real/user_smoke_findings.md).  Foreign
            # hashes (Cisco type-5/7/8/9, Arista sha512, OPNsense
            # bcrypt) are NOT consumable by FortiOS's ``set password
            # ENC <blob>`` -- that ENC blob has FortiOS-internal key
            # semantics, NOT a generic "any hash" wrapper.  Before
            # the fix the renderer leaked the literal source hash on
            # the wire (e.g. ``set password ENC 9 $9$...``) which
            # FortiOS would either reject at commit time or, worse,
            # parse as garbage.  Now we consult the shared
            # :mod:`netconfig.migration._user_secrets` policy and
            # emit a comment-form ``review:`` line instead, naming
            # the source algorithm so the operator knows exactly
            # which user to reset.  Native fortigate hashes tagged
            # ``fortios:<blob>`` still pass through unchanged.
            if user.hashed_password:
                if is_migratable(user.hashed_password, "fortigate_cli"):
                    alg, _, raw = user.hashed_password.partition(":")
                    if alg == "fortios":
                        out.append(f"        set password {raw}")
                    elif raw:
                        out.append(f"        set password ENC {raw}")
                    else:
                        out.append(
                            f"        set password ENC "
                            f"{user.hashed_password}"
                        )
                else:
                    algorithm, _payload = classify_hash(
                        user.hashed_password,
                    )
                    out.append(
                        f"        {format_review_comment(user.name, algorithm, comment_syntax='hash')}"
                    )
            # Map canonical privilege back to accprofile.
            accprofile = (
                "super_admin" if user.privilege_level == 15
                else (user.role or "prof_admin")
            )
            out.append(f'        set accprofile "{accprofile}"')
            out.append("    next")
        out.append("end")

    # --- user radius (Tier 2 RADIUS servers) ---
    if tree.radius_servers:
        out.append("config user radius")
        for idx, server in enumerate(tree.radius_servers, start=1):
            out.append(f'    edit "radius-{idx}"')
            out.append(f'        set server "{server.host}"')
            if server.key:
                alg, _, raw = server.key.partition(":")
                if alg == "fortios":
                    out.append(f"        set secret {raw}")
                elif raw:
                    out.append(f"        set secret ENC {raw}")
                else:
                    out.append(f"        set secret ENC {server.key}")
            if server.auth_port and server.auth_port != 1812:
                out.append(f"        set radius-port {server.auth_port}")
            out.append("    next")
        out.append("end")

    # --- system dhcp server (Tier 2 DHCP pools) ---
    if tree.dhcp_servers:
        out.append("config system dhcp server")
        for idx, pool in enumerate(tree.dhcp_servers, start=1):
            out.append(f"    edit {idx}")
            if pool.lease_time:
                out.append(f"        set lease-time {pool.lease_time}")
            if pool.gateway:
                out.append(f"        set default-gateway {pool.gateway}")
            if pool.network:
                try:
                    net = ipaddress.IPv4Network(pool.network, strict=False)
                    out.append(f"        set netmask {net.netmask}")
                except (ValueError, ipaddress.AddressValueError):
                    pass
            if pool.interface:
                out.append(f'        set interface "{pool.interface}"')
            for i, dns in enumerate(pool.dns_servers[:3], start=1):
                out.append(f"        set dns-server{i} {dns}")
            if pool.dns_servers:
                out.append("        set dns-service specify")
            if pool.domain_name:
                out.append(f'        set domain "{pool.domain_name}"')
            if pool.start_ip or pool.end_ip:
                out.append("        config ip-range")
                out.append("            edit 1")
                if pool.start_ip:
                    out.append(f"                set start-ip {pool.start_ip}")
                if pool.end_ip:
                    out.append(f"                set end-ip {pool.end_ip}")
                out.append("            next")
                out.append("        end")
            out.append("    next")
        out.append("end")

    # --- router static ---
    if tree.static_routes:
        out.append("config router static")
        for idx, route in enumerate(tree.static_routes, start=1):
            out.append(f"    edit {idx}")
            dst_ip, dst_prefix = _split_cidr(route.destination)
            dst_mask = _prefix_to_mask(dst_prefix)
            out.append(f"        set dst {dst_ip} {dst_mask}")
            if route.gateway:
                out.append(f"        set gateway {route.gateway}")
            if route.interface:
                out.append(f'        set device "{route.interface}"')
            out.append("    next")
        out.append("end")

    return "\n".join(out) + "\n"
