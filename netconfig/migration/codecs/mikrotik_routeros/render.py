"""
MikroTik RouterOS renderer — canonical tree to ``/export`` CLI text.

Extracted from ``codec.py`` during the parse/render split per the
``codecs/README.md`` split-codec convention.  Public function
(consumed by ``codec.py::MikroTikRouterOSCodec.render()``):

* :func:`render_intent` — one-shot render: ``CanonicalIntent`` in,
  RouterOS ``/export``-style command stream out.

Emission order mirrors what ``/export`` itself puts on the wire so a
re-applied script matches device round-trips cleanly: ``/system
identity``, ``/interface ethernet`` (port tweaks), ``/interface bridge``,
``/interface bonding``, ``/interface vlan``, ``/ip address``, ``/ipv6
address`` (GAP-EVPN-3), ``/ip route``, ``/snmp`` (+ ``/snmp community``
for v1/v2c + SNMPv3 USM), ``/radius``, ``/ip pool`` + ``/ip dhcp-server
network``, ``/user``, ``/system dns``, ``/system ntp client``.

Shared name/type helpers (``_is_ethernet_name``, ``_is_vlan_name``)
live in :mod:`.parse` and are imported here — the README's split-codec
guidance keeps those edges directional (parse → render is invalid;
render → parse for shared utilities is fine).
"""

from __future__ import annotations

import re
from typing import Any

from ...canonical.intent import CanonicalIntent, CanonicalVlan
from ..base import RenderError
from .parse import _is_ethernet_name, _is_vlan_name


# ---------------------------------------------------------------------------
# Render-only constants
# ---------------------------------------------------------------------------


_CANONICAL_MODE_TO_ROUTEROS_BONDING = {
    "active": "802.3ad",
    "passive": "802.3ad",    # RouterOS doesn't distinguish LACP passive
    "static": "active-backup",
}


_CANONICAL_PRIVILEGE_TO_ROUTEROS_GROUP = {
    15: "full",
    10: "write",
    1: "read",
}


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


def render_intent(tree: Any) -> str:
    """Render a :class:`CanonicalIntent` to RouterOS ``/export`` text.

    Raises:
        RenderError: If *tree* is not a CanonicalIntent.
    """
    if not isinstance(tree, CanonicalIntent):
        raise RenderError(
            "mikrotik_routeros: tree must be a CanonicalIntent "
            "(legacy dict shapes are not supported by this codec).",
            yang_path="/",
        )

    lines: list[str] = []

    # ----- /system identity -----
    if tree.hostname:
        lines.append("/system identity")
        # Hostnames with spaces or special characters need
        # quoting — without quotes, a hostname like "Quinta Router"
        # renders as `set name=Quinta Router`, which RouterOS
        # parses as `name=Quinta` + an orphan token `Router`.
        # Surfaced by routeros-diff's verbose_export.rsc fixture.
        lines.append(f'set name={_quote_if_needed(tree.hostname)}')
        lines.append("")

    # ----- /interface ethernet (tweaks to default ports) -----
    ethernet_ifaces = [
        i for i in tree.interfaces
        if _is_ethernet_name(i.name) or _is_ethernet_name(i.default_name)
        or (i.interface_type == "ianaift:ethernetCsmacd" and i.default_name)
    ]
    if ethernet_ifaces:
        lines.append("/interface ethernet")
        for iface in ethernet_ifaces:
            # Find key: prefer default_name (factory default, matches
            # what the device finds by default-name=) falling back to
            # the canonical name when no default_name was tracked.
            find_key = iface.default_name or iface.name
            parts = [f"set [ find default-name={find_key} ]"]
            if iface.description:
                parts.append(f'comment="{_escape(iface.description)}"')
            # Emit the renamed name only when it differs from the
            # factory default-name — avoids a noisy no-op
            # `name=ether1` on otherwise-default ports.
            if iface.name != find_key:
                parts.append(f"name={_quote_if_needed(iface.name)}")
            parts.append(f"disabled={_yes_no(not iface.enabled)}")
            if iface.mtu is not None:
                parts.append(f"mtu={iface.mtu}")
            lines.append(" ".join(parts))
        lines.append("")

    # ----- /interface bridge -----
    # Emit any interface typed as a bridge.  Parsed state comes
    # from `_parse_interface_bridge`; without this render branch
    # the bridge survives parse but vanishes on render, which
    # breaks round-trip stability for any config using bridges
    # (surfaced by routeros-diff's verbose_export.rsc and the
    # taqavi provisioning script).
    bridge_ifaces = [
        i for i in tree.interfaces
        if i.interface_type == "ianaift:bridge"
    ]
    if bridge_ifaces:
        lines.append("/interface bridge")
        for iface in bridge_ifaces:
            parts = ["add"]
            if iface.description:
                parts.append(f'comment="{_escape(iface.description)}"')
            parts.append(f"name={_quote_if_needed(iface.name)}")
            lines.append(" ".join(parts))
        lines.append("")

    # ----- /interface bonding (Tier 2 LAGs) -----
    if tree.lags:
        lines.append("/interface bonding")
        for lag in tree.lags:
            parts = ["add"]
            if lag.members:
                parts.append(f"slaves={','.join(lag.members)}")
            parts.append(
                f"mode={_CANONICAL_MODE_TO_ROUTEROS_BONDING.get(lag.mode, '802.3ad')}"
            )
            parts.append(f"name={lag.name}")
            lines.append(" ".join(parts))
        lines.append("")

    # ----- /interface vlan -----
    # Filter by interface_type, not by name pattern.  Real configs
    # name VLAN interfaces freely (gn-mgmt, user-wifi, etc.); the
    # name-pattern filter used to require `vlan\d+` prefix which
    # silently dropped any non-conforming name on render.
    # Surfaced by routeros-diff's verbose_export.rsc (the
    # "gn-mgmt" VLAN interface named after its purpose, not its
    # ID).
    vlan_ifaces = [
        i for i in tree.interfaces
        if i.interface_type == "ianaift:l3ipvlan"
        or _is_vlan_name(i.name)
    ]
    if vlan_ifaces or tree.vlans:
        lines.append("/interface vlan")
        rendered_vlan_ids: set[int] = set()
        for iface in vlan_ifaces:
            vid = _vlan_id_for(iface.name, tree.vlans)
            if vid is None:
                # Can't render a VLAN interface without an id.
                continue
            parts = ["add"]
            if iface.description:
                parts.append(f'comment="{_escape(iface.description)}"')
            parts.append("interface=bridge1")   # convention: single bridge
            parts.append(f"name={_quote_if_needed(iface.name)}")
            parts.append(f"vlan-id={vid}")
            lines.append(" ".join(parts))
            rendered_vlan_ids.add(vid)
        # VLANs defined in intent.vlans but without a matching
        # interface still get rendered so the id survives the
        # round-trip.  Dedupe by vlan-id (not name) so we don't
        # double-emit when an iface carrying vid=N is already out.
        for vlan in tree.vlans:
            if vlan.id in rendered_vlan_ids:
                continue
            synthetic_name = f"vlan{vlan.id}"
            parts = ["add"]
            if vlan.name and vlan.name != synthetic_name:
                parts.append(f'comment="{_escape(vlan.name)}"')
            parts.append("interface=bridge1")
            parts.append(f"name={synthetic_name}")
            parts.append(f"vlan-id={vlan.id}")
            lines.append(" ".join(parts))
            rendered_vlan_ids.add(vlan.id)
        lines.append("")

    # ----- /ip address -----
    ip_rows: list[tuple[str, int, str]] = []  # (ip, prefix, iface)
    for iface in tree.interfaces:
        for addr in iface.ipv4_addresses:
            ip_rows.append((addr.ip, addr.prefix_length, iface.name))
    if ip_rows:
        lines.append("/ip address")
        for ip, prefix, iface_name in ip_rows:
            lines.append(
                f"add address={ip}/{prefix} interface={iface_name}"
            )
        lines.append("")

    # ----- /ipv6 address (GAP-EVPN-3) -----
    ip6_rows: list[tuple[str, int, str]] = []
    for iface in tree.interfaces:
        for v6 in iface.ipv6_addresses:
            ip6_rows.append((v6.ip, v6.prefix_length, iface.name))
    if ip6_rows:
        lines.append("/ipv6 address")
        for ip, prefix, iface_name in ip6_rows:
            lines.append(
                f"add address={ip}/{prefix} interface={iface_name}"
            )
        lines.append("")

    # ----- /ip route -----
    if tree.static_routes:
        lines.append("/ip route")
        for route in tree.static_routes:
            parts = ["add"]
            if route.description:
                parts.append(f'comment="{_escape(route.description)}"')
            parts.append(f"dst-address={route.destination}")
            if route.gateway:
                parts.append(f"gateway={route.gateway}")
            elif route.interface:
                parts.append(f"gateway={route.interface}")
            lines.append(" ".join(parts))
        lines.append("")

    # ----- /snmp (Tier 2) -----
    if tree.snmp is not None and (
        tree.snmp.community or tree.snmp.location
        or tree.snmp.contact or tree.snmp.trap_hosts
        or tree.snmp.v3_users
    ):
        lines.append("/snmp")
        parts = ["set", "enabled=yes"]
        if tree.snmp.contact:
            parts.append(f'contact="{_escape(tree.snmp.contact)}"')
        if tree.snmp.location:
            parts.append(f'location="{_escape(tree.snmp.location)}"')
        if tree.snmp.trap_hosts:
            parts.append(
                f'trap-target={",".join(tree.snmp.trap_hosts)}'
            )
        lines.append(" ".join(parts))
        lines.append("")
        if tree.snmp.community or tree.snmp.v3_users:
            lines.append("/snmp community")
            if tree.snmp.community:
                lines.append(
                    f"set [ find default=yes ] name={tree.snmp.community}"
                )
            # Canonical auth/priv → RouterOS names.  RouterOS
            # only accepts ``MD5`` / ``SHA1`` / ``SHA256`` /
            # ``SHA512`` for auth and ``DES`` / ``AES`` (+
            # CCM/CFB variants) for priv; ``sha`` canonical maps
            # to ``SHA1`` on wire.  aes128 / aes192 / aes256
            # canonical → aes-128-cfb / aes-192-cfb /
            # aes-256-cfb (the default CFB variant).
            _CAN_TO_MT_AUTH = {
                "md5": "MD5", "sha": "SHA1", "sha224": "SHA256",
                "sha256": "SHA256", "sha384": "SHA512",
                "sha512": "SHA512",
            }
            _CAN_TO_MT_PRIV = {
                "des": "DES", "aes": "AES",
                "aes128": "aes-128-cfb",
                "aes192": "aes-192-cfb",
                "aes256": "aes-256-cfb",
                "3des": "DES",      # RouterOS doesn't speak 3DES — fallback
            }
            for u in tree.snmp.v3_users:
                add_parts = ["add", f"name={u.name}"]
                if u.auth_protocol:
                    mt_auth = _CAN_TO_MT_AUTH.get(
                        u.auth_protocol, "SHA1",
                    )
                    add_parts.append(
                        f"authentication-protocol={mt_auth}"
                    )
                    if u.auth_passphrase:
                        add_parts.append(
                            f'authentication-password='
                            f'"{_escape(u.auth_passphrase)}"'
                        )
                if u.priv_protocol:
                    mt_priv = _CAN_TO_MT_PRIV.get(
                        u.priv_protocol, "AES",
                    )
                    add_parts.append(
                        f"encryption-protocol={mt_priv}"
                    )
                    if u.priv_passphrase:
                        add_parts.append(
                            f'encryption-password='
                            f'"{_escape(u.priv_passphrase)}"'
                        )
                lines.append(" ".join(add_parts))
            lines.append("")

    # ----- /radius (Tier 2 RADIUS) -----
    if tree.radius_servers:
        lines.append("/radius")
        for server in tree.radius_servers:
            parts = ["add", f"address={server.host}"]
            if server.key:
                parts.append(f"secret={server.key}")
            if server.auth_port and server.auth_port != 1812:
                parts.append(f"authentication-port={server.auth_port}")
            if server.acct_port and server.acct_port != 1813:
                parts.append(f"accounting-port={server.acct_port}")
            # `service=login` is the default/safe value for a
            # RADIUS server record when nothing more specific
            # is known.  Real configs often use comma-separated
            # `login,ppp,hotspot,wireless,dhcp` — we preserve
            # only the baseline here.
            parts.append("service=login")
            lines.append(" ".join(parts))
        lines.append("")

    # ----- /ip pool + /ip dhcp-server network (Tier 2 DHCP) -----
    # RouterOS splits DHCP across /ip pool (the address range)
    # and /ip dhcp-server network (network-scoped options).  We
    # emit both so the result is deployable without hand-editing.
    # Pool names are synthesised deterministically.
    if tree.dhcp_servers:
        # /ip pool first — depends on nothing else.
        lines.append("/ip pool")
        for idx, pool in enumerate(tree.dhcp_servers, start=1):
            if not (pool.start_ip and pool.end_ip):
                continue
            name = f"dhcp_pool{idx}"
            lines.append(
                f"add name={name} ranges={pool.start_ip}-{pool.end_ip}"
            )
        lines.append("")
        lines.append("/ip dhcp-server network")
        for pool in tree.dhcp_servers:
            if not pool.network:
                continue
            parts = ["add", f"address={pool.network}"]
            if pool.gateway:
                parts.append(f"gateway={pool.gateway}")
            if pool.dns_servers:
                parts.append(f"dns-server={','.join(pool.dns_servers)}")
            if pool.domain_name:
                parts.append(f"domain={pool.domain_name}")
            lines.append(" ".join(parts))
        lines.append("")

    # ----- /user (Tier 2 local users) -----
    if tree.local_users:
        lines.append("/user")
        for user in tree.local_users:
            # Map canonical privilege back to RouterOS group.
            # Unknown/odd privilege levels fall back to ``read``
            # (least privilege) per safe-default principle.
            group = _CANONICAL_PRIVILEGE_TO_ROUTEROS_GROUP.get(
                user.privilege_level, "read"
            )
            parts = ["add", f"group={group}", f"name={user.name}"]
            lines.append(" ".join(parts))
        lines.append("")

    # ----- /system dns -----
    if tree.dns_servers:
        lines.append("/system dns")
        lines.append(f"set servers={','.join(tree.dns_servers)}")
        lines.append("")

    # ----- /system ntp client -----
    if tree.ntp_servers:
        lines.append("/system ntp client")
        lines.append(
            f"set enabled=yes servers={','.join(tree.ntp_servers)}"
        )
        lines.append("")

    # Trim trailing blanks, leave exactly one newline at EOF.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _quote_if_needed(value: str) -> str:
    """Quote a RouterOS key=value value if it contains whitespace
    or characters that would otherwise break parsing.  No-op for
    simple identifiers (the common case, so we keep render output
    tidy by default)."""
    if not value:
        return '""'
    if any(c in value for c in ' \t\n"\\'):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _yes_no(flag: bool) -> str:
    return "yes" if flag else "no"


def _escape(value: str) -> str:
    """Escape double-quotes in a string for inclusion in ``"..."``."""
    return value.replace('"', '\\"')


def _vlan_id_for(name: str, vlans: list[CanonicalVlan]) -> int | None:
    """Find the VLAN id for an interface name.

    Matches on either a ``vlanN`` convention (id parsed from name) or
    an entry in ``vlans`` whose ``name`` equals the interface name.
    """
    m = re.match(r"^vlan(\d+)$", name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    for v in vlans:
        if v.name == name:
            return v.id
    return None
