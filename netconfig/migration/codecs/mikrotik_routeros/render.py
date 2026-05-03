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

from ..._user_secrets import classify_hash, format_review_comment, is_migratable
from ...canonical.intent import CanonicalIntent, CanonicalVlan
from ..base import RenderError
from .parse import (
    _is_ethernet_name,
    _is_vlan_name,
    _looks_like_bridge_iface,
    _looks_like_lag_iface,
    _looks_like_vlan_iface,
)


# ---------------------------------------------------------------------------
# Render-only constants
# ---------------------------------------------------------------------------


_CANONICAL_MODE_TO_ROUTEROS_BONDING = {
    "active": "802.3ad",
    "passive": "802.3ad",    # RouterOS doesn't distinguish LACP passive
    "static": "active-backup",
}


#: Canonical-privilege → RouterOS user-group threshold mapping.
#: RouterOS ships three built-in groups (``read``, ``write``,
#: ``full``).  Most source vendors use Cisco's 0-15 numeric scale —
#: 15 = admin, 0-1 = read-only, with intermediate values mapping to
#: operator roles (Junos super-user → 15, operator → 10, read-only
#: → 1).  Mapping is threshold-based (``>=`` cutoffs) rather than
#: an exact lookup so real captures with intermediate values resolve
#: to a sane RouterOS group instead of the safe-default ``read``.
#: Use :func:`_routeros_group_for_privilege` to resolve.
_PRIVILEGE_FULL_THRESHOLD = 15
_PRIVILEGE_WRITE_THRESHOLD = 10


def _routeros_group_for_privilege(level: int) -> str:
    """Map a canonical privilege level to a RouterOS user group.

    Threshold rules (most-permissive cutoff wins):

    * ``>= 15`` → ``full`` (admin / superuser).
    * ``>= 10`` → ``write`` (operator / can-modify).
    * ``< 10``  → ``read`` (read-only / safe default).

    The ``read`` floor also covers the canonical default of ``1``
    declared on :class:`CanonicalLocalUser`, which source codecs
    leave untouched when they can't determine privilege from the
    source config.
    """
    if level >= _PRIVILEGE_FULL_THRESHOLD:
        return "full"
    if level >= _PRIVILEGE_WRITE_THRESHOLD:
        return "write"
    return "read"


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
    # Filter by exclusion rather than by MikroTik-shape match.
    # When the source intent comes from a non-MikroTik codec the
    # interface name is the source vendor's native name (`wan`,
    # `lan`, `ge-0/0/0`, `GigabitEthernet0/0/0`, `Loopback0`,
    # `irb`, ...) and `default_name` is empty.  The previous
    # `_is_ethernet_name` filter required `^ether\d`, so all of
    # those non-conforming names dropped out of the render and
    # their description/mtu/enabled/dhcp_client state never made
    # it onto the wire.  Surfaced as a top-rank Phase-4 finding
    # across the juniper_junos / opnsense / cisco_iosxe -> mikrotik
    # cross-vendor matrix.  Loopback / Tunnel emission still has
    # a gap (RouterOS expresses those as bridge / ovpn-server /
    # gre, not ethernet) but the broadened filter at least
    # carries the interface name forward instead of silently
    # dropping the whole row.  The /interface vlan, /interface
    # bridge and /interface bonding sections below own their
    # own ifaces so we exclude those by name shape.
    ethernet_ifaces = [
        i for i in tree.interfaces
        if not _looks_like_vlan_iface(i.name)
        and not _looks_like_bridge_iface(i.name)
        and not _looks_like_lag_iface(i.name)
        and i.interface_type != "ianaift:bridge"
        and i.interface_type != "ianaift:ieee8023adLag"
        and i.interface_type != "ianaift:l3ipvlan"
        and not _is_loopback_type(i)
        and not _is_tunnel_type(i)
    ]
    if ethernet_ifaces:
        lines.append("/interface ethernet")
        for iface in ethernet_ifaces:
            # Find clause: prefer the MikroTik factory ``default-name=``
            # form when we know the original factory port name - either
            # because parse captured it on a ``set [ find default-name=X ]``
            # line, or because the canonical name itself follows the
            # MikroTik ``etherN`` shape (in which case ``default-name``
            # is the right thing for the device to look up).  When
            # ``default_name`` is empty AND the name doesn't match the
            # factory shape - the common case for cross-vendor sources
            # whose interface names came from Junos / OPNsense / Cisco -
            # emit ``[ find name=X ]`` against the canonical name
            # instead.  Using ``default-name`` in that branch would
            # cause a round-trip to synthesise a spurious
            # ``default_name`` field on the second parse pass.
            use_default_name_form = bool(iface.default_name) or _is_ethernet_name(iface.name)
            if use_default_name_form:
                find_key = iface.default_name or iface.name
                parts = [f"set [ find default-name={find_key} ]"]
                # Emit the renamed name only when it differs from
                # the factory default-name - avoids a noisy no-op
                # `name=ether1` on otherwise-default ports.
                if iface.name != find_key:
                    parts.append(
                        f"name={_quote_if_needed(iface.name)}"
                    )
            else:
                parts = [
                    f"set [ find name={_quote_if_needed(iface.name)} ]"
                ]
            if iface.description:
                parts.append(f'comment="{_escape(iface.description)}"')
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
    # Loopback interfaces in RouterOS have no native primitive --
    # the documented idiom is an empty bridge with no slaves
    # (RouterOS community wiki at
    # https://wiki.mikrotik.com/wiki/Manual:Creating_IPv6_loopback_address
    # plus the RouterOS Bridging+Switching docs at
    # https://help.mikrotik.com/docs/spaces/ROS/pages/328068/Bridging+and+Switching).
    # Without an explicit declaration, a cross-vendor source that
    # carried a loopback (Cisco ``Loopback0``, Junos ``lo0``, Arista
    # ``Loopback1``) would get its loopback name dropped on render
    # AND have its IP synthesised as a stub via ``/ip address add
    # interface=lo0`` -- the device would create a phantom ``lo0``
    # ethernet interface with no factory backing.  Emitting the
    # bridge declaration up front means the ``/ip address`` row
    # binds to a real interface.  Phase 4b cisco_iosxe (NETCONF)
    # cross-vendor finding.
    loopback_ifaces = [
        i for i in tree.interfaces
        if _is_loopback_type(i)
    ]
    # Cross-vendor sources (Cisco / Junos / OPNsense / FortiGate)
    # don't model an L2 software-bridge primitive the way RouterOS
    # does, so parse produces zero ``ianaift:bridge`` interfaces.
    # The /interface vlan block below normally pins every VLAN
    # child to ``interface=bridge1`` by convention — RouterOS
    # rejects a ``/interface vlan add interface=bridge1 ...``
    # line when ``bridge1`` doesn't exist yet.
    #
    # BUT: when the source already has a clear "VLAN parent" port
    # (OPNsense ``ixl0`` carrying all five VLANs, or a Cisco
    # router-on-stick with one trunk physical port), we should
    # bind the VLANs to that interface's target-side rename
    # instead of synthesising ``bridge1``.  The bridge-synth path
    # was added for the c9300-style switching topology where
    # there's no single L3 / trunk anchor, just many switchports.
    # Synthesising bridge1 unconditionally hides the source's
    # router-on-stick topology and routes the LAN IP and the
    # VLANs onto disjoint interfaces.
    #
    # Identification rule (kept deliberately narrow for the common
    # case): exactly ONE non-vlan / non-bridge / non-lag /
    # non-loopback interface that carries either an L3 IP or L2
    # trunk semantics.  When zero or many candidates exist, fall
    # back to bridge1.  See :func:`_identify_vlan_parent` for the
    # full logic.
    #
    # Same-vendor round-trips with real bridges (``downstream``,
    # ``upstream``, ``br-lan``) keep their parents — synthetic
    # bridge1 is only added when no other parent exists.  The
    # round-trip stability guard in
    # ``tests/unit/migration/test_real_captures.py`` would catch
    # a phantom ``bridge1`` regression.  Surfaced by the c9300
    # smoke test (issue #4 in
    # ``tests/fixtures/real/user_smoke_findings.md``) and refined
    # by the OPNsense supergate smoke test (issue #7 same file).
    # RouterOS docs:
    # https://help.mikrotik.com/docs/spaces/ROS/pages/328068/VLAN
    # — ``interface=`` must reference an existing parent.
    has_vlan_to_render = bool(tree.vlans) or any(
        i.interface_type == "ianaift:l3ipvlan"
        or _is_vlan_name(i.name)
        for i in tree.interfaces
    )
    vlan_parent_iface = (
        _identify_vlan_parent(tree) if has_vlan_to_render else None
    )
    needs_synthetic_bridge1 = (
        has_vlan_to_render
        and not bridge_ifaces
        and vlan_parent_iface is None
    )
    emitted_bridge_names: set[str] = set()
    if bridge_ifaces or loopback_ifaces or needs_synthetic_bridge1:
        lines.append("/interface bridge")
        for iface in bridge_ifaces:
            parts = ["add"]
            if iface.description:
                parts.append(f'comment="{_escape(iface.description)}"')
            parts.append(f"name={_quote_if_needed(iface.name)}")
            lines.append(" ".join(parts))
            emitted_bridge_names.add(iface.name)
        # Loopback interfaces — same /interface bridge section,
        # no slaves attached.  The default protocol-mode is fine
        # for an unattached bridge; we deliberately don't pin it
        # (matches the same-vendor round-trip baseline where
        # MikroTik /export also omits the default).  Comment
        # carries the canonical description through.
        for iface in loopback_ifaces:
            if iface.name in emitted_bridge_names:
                # Pathological case where an iface is typed both
                # bridge AND loopback — already emitted, skip.
                continue
            parts = ["add"]
            if iface.description:
                parts.append(f'comment="{_escape(iface.description)}"')
            parts.append(f"name={_quote_if_needed(iface.name)}")
            lines.append(" ".join(parts))
            emitted_bridge_names.add(iface.name)
        # The synthetic add is idempotent — track which bridge
        # names have already been emitted so re-entry would not
        # double up.
        if needs_synthetic_bridge1 and "bridge1" not in emitted_bridge_names:
            lines.append("add name=bridge1")
            emitted_bridge_names.add("bridge1")
        lines.append("")
    # The VLAN children below bind to whichever parent we resolved.
    # Synthetic bridge1 wins only when no source-side parent was
    # identified; otherwise we use the source-side parent's
    # (already-renamed) target name verbatim.
    vlan_parent_name = (
        vlan_parent_iface
        if vlan_parent_iface is not None
        else "bridge1"
    )

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

    # ----- /interface gre (tunnel emission) -----
    # Cross-vendor sources (Cisco ``interface Tunnel0``, Junos
    # ``gr-0/0/0``, FortiGate ``gre1``) populate
    # ``interface_type='ianaift:tunnel'`` for tunnel interfaces.
    # Without a dedicated render branch the iface name only
    # surfaces as a target of ``/ip address add interface=<name>``
    # and RouterOS synthesises a phantom stub on the wire.
    # Emitting an explicit ``/interface gre add name=<name>``
    # declaration up front means the address binding is well-
    # formed.  RouterOS docs:
    # https://help.mikrotik.com/docs/spaces/ROS/pages/24805531/GRE
    # -- ``/interface gre add name=... remote-address=...
    # local-address=...``.
    #
    # The canonical :class:`CanonicalInterface` does NOT carry
    # tunnel endpoint addresses (no ``local_address`` /
    # ``remote_address`` fields in v1).  We therefore emit the
    # declaration with a placeholder ``remote-address=0.0.0.0``
    # and a review comment so the operator knows to populate the
    # real endpoint pair before deployment.  EoIP / IPIP / IPSEC
    # tunnel sub-types are deferred: the canonical model has no
    # discriminator to choose between the RouterOS
    # ``/interface gre`` / ``/interface eoip`` / ``/interface
    # ipip`` shapes, so we pick GRE as the most common cross-
    # vendor case (matches Cisco ``Tunnel0`` default mode, Junos
    # ``gr-`` / ``ip-`` interfaces, FortiGate ``gre<N>``).
    # Operators migrating EoIP-specific configs will need to
    # rewrite the section by hand.  Phase 4b cisco_iosxe
    # (NETCONF) cross-vendor finding.
    tunnel_ifaces = [
        i for i in tree.interfaces
        if _is_tunnel_type(i)
    ]
    if tunnel_ifaces:
        lines.append("/interface gre")
        for iface in tunnel_ifaces:
            parts = ["add"]
            # Carry source description; otherwise emit a default
            # review note so operators see the placeholder warning.
            if iface.description:
                parts.append(f'comment="{_escape(iface.description)}"')
            else:
                parts.append(
                    'comment="review: tunnel endpoint placeholder -- set local-address/remote-address"'
                )
            parts.append(f"name={_quote_if_needed(iface.name)}")
            # Placeholder endpoint -- canonical model in v1 carries
            # no tunnel local/remote address pair.  Without
            # ``remote-address`` RouterOS rejects the add line; we
            # pick 0.0.0.0 as an obvious sentinel.
            parts.append("remote-address=0.0.0.0")
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
            # Bind to the parent we resolved above — either an
            # identified source-side parent's renamed target name
            # (router-on-stick: OPNsense ixl0 → sfp-sfpplus0) or
            # the synthesised ``bridge1`` (switching topology).
            parts.append(f"interface={_quote_if_needed(vlan_parent_name)}")
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
            parts.append(f"interface={_quote_if_needed(vlan_parent_name)}")
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
    # RouterOS combines an IP next-hop and an outgoing interface
    # into a single ``gateway=`` argument using the
    # ``<ip>%<iface>`` form (the same shape the device displays
    # under ``immediate-gw=`` for resolved recursive routes).
    # See RouterOS Manual: IP/Route --
    # https://wiki.mikrotik.com/wiki/Manual:IP/Route -- and the
    # RouterOS Policy Routing reference at
    # https://help.mikrotik.com/docs/spaces/ROS/pages/59965508/Policy+Routing
    # which both document the ``gateway=<ip>%<iface>`` shape.
    #
    # The previous emit was an ``elif`` ladder which silently
    # dropped the interface field whenever both ``gateway`` and
    # ``interface`` were populated on the canonical record (e.g.
    # FortiGate ``set gateway 192.168.1.1`` + ``set device port1``
    # on the same static route).  Phase 4b fortigate_cli
    # cross-vendor finding.
    if tree.static_routes:
        lines.append("/ip route")
        for route in tree.static_routes:
            parts = ["add"]
            if route.description:
                parts.append(f'comment="{_escape(route.description)}"')
            parts.append(f"dst-address={route.destination}")
            if route.gateway and route.interface:
                # Both populated -- RouterOS combined form pins the
                # next-hop IP to a specific egress interface.
                parts.append(f"gateway={route.gateway}%{route.interface}")
            elif route.gateway:
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
            # Map canonical privilege onto a RouterOS built-in
            # group via threshold rules; safe default is ``read``.
            group = _routeros_group_for_privilege(user.privilege_level)
            # Password emit gating: RouterOS only accepts plaintext
            # (``mikrotik_routeros`` -> {plaintext} in the central
            # ``_user_secrets._TARGET_ACCEPTS`` policy).  Foreign
            # hashes (bcrypt from OPNsense, type-9 from Cisco, $6$
            # from Arista, FortiOS ENC blobs) are NOT migratable —
            # RouterOS re-hashes the supplied value internally and
            # leaking the hash literal as a "password" would set
            # the user's password to the literal hash string, an
            # auth bypass for anyone who has read access to the
            # original config.  When the canonical carries a
            # plaintext password, emit it; when foreign-hashed,
            # skip the field AND emit a ``# password manager …
            # -- review:`` comment immediately above the ``add``
            # line so the operator has a deterministic signal that
            # a hash existed and must be reset manually.  Without
            # the review comment the user appears to have been
            # created with no password, with no hint that one was
            # ever set.  Surfaced by OPNsense supergate smoke test
            # (issues #13 + #18 in
            # ``tests/fixtures/real/user_smoke_findings.md``).
            parts = ["add", f"group={group}", f"name={user.name}"]
            if user.hashed_password and is_migratable(
                user.hashed_password, "mikrotik_routeros",
            ):
                _alg, payload = classify_hash(user.hashed_password)
                if payload:
                    parts.append(
                        f"password={_quote_if_needed(payload)}"
                    )
            elif user.hashed_password:
                # Unmigratable foreign hash — emit review comment
                # just above this user's add line.  Interleaved
                # shape (rather than block-first) keeps each
                # comment visually adjacent to its user, mirroring
                # the FortiGate / Cisco-IOSXE per-user pattern.
                algorithm, _payload = classify_hash(
                    user.hashed_password,
                )
                lines.append(
                    format_review_comment(
                        user.name,
                        algorithm,
                        comment_syntax="hash",
                        target_label="RouterOS",
                    )
                )
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


def _identify_vlan_parent(tree: CanonicalIntent) -> str | None:
    """Find the single canonical interface that should anchor VLAN
    children, or return None when no clear anchor exists.

    Rationale: when the source config is a router-on-stick (single
    physical / LAG port carrying the LAN IP and all VLAN tags —
    e.g. OPNsense ``ixl0`` carrying VLAN 10/11/20/100/150 plus the
    LAN IP), the MikroTik render should bind the VLAN children to
    that port's renamed target name and skip the ``bridge1`` synth.
    When the source is a many-port switching topology (Cisco c9300
    with 24 trunk ports) there's no single anchor and we fall back
    to bridge1.

    The "single anchor" is identified by:

      1. Excluding VLAN-shape, bridge-shape, LAG-shape and loopback
         interfaces (those have their own sections).
      2. From the rest, picking interfaces that look like an L3
         port (non-empty ``ipv4_addresses`` / ``ipv6_addresses``)
         OR an L2 trunk (non-empty ``trunk_allowed_vlans``).
      3. Returning the unique candidate's ``name`` if and only if
         exactly ONE candidate exists.

    The narrow "exactly one" rule avoids over-engineering for the
    multi-parent case (some VLANs on port A, some on port B) —
    falling back to bridge1 is wrong-but-deployable in that
    rare case, while picking an arbitrary candidate would be
    silently wrong.  The OPNsense supergate fixture is the
    motivating single-parent case (see issue #7 in
    ``tests/fixtures/real/user_smoke_findings.md``).

    Note: this runs AFTER ``translate_port_names`` has rewritten
    the interface names, so the returned value is already in the
    target codec's naming convention.  No further renaming
    required at the call site.
    """
    candidates: list[str] = []
    for iface in tree.interfaces:
        if _looks_like_vlan_iface(iface.name):
            continue
        if _looks_like_bridge_iface(iface.name):
            continue
        if _looks_like_lag_iface(iface.name):
            continue
        if iface.interface_type in (
            "ianaift:bridge",
            "ianaift:ieee8023adLag",
            "ianaift:l3ipvlan",
            "ianaift:softwareLoopback",
            "softwareLoopback",
        ):
            continue
        # Loopback name shape (lo, loN, loopbackN) — the canonical
        # interface_type isn't always populated, so guard by name
        # too.  Mirrors the loopback branch in port_names.classify.
        if re.match(r"^(lo|loopback)\d*$", iface.name, re.IGNORECASE):
            continue
        has_l3 = bool(iface.ipv4_addresses) or bool(iface.ipv6_addresses)
        has_trunk = bool(iface.trunk_allowed_vlans)
        if has_l3 or has_trunk:
            candidates.append(iface.name)
    if len(candidates) == 1:
        return candidates[0]
    return None


#: Canonical interface_type values that mean "this is a loopback".
#: ``ianaift:softwareLoopback`` is the IANA-IF-MIB type (the
#: canonical form per :class:`CanonicalInterface`).  The bare
#: ``softwareLoopback`` form is accepted for parity with codecs
#: that normalise without the prefix.
_LOOPBACK_TYPES = frozenset(
    {"ianaift:softwareLoopback", "softwareLoopback"}
)

#: Canonical interface_type values that mean "this is a tunnel".
#: ``ianaift:tunnel`` is the IANA-IF-MIB type used by FortiGate /
#: Cisco / Junos parsers when classifying ``Tunnel<N>`` /
#: ``gre<N>`` / ``ssl.root`` interfaces.
_TUNNEL_TYPES = frozenset(
    {"ianaift:tunnel", "tunnel"}
)

#: Loopback name shape recognised regardless of ``interface_type``.
#: Mirrors the loopback branch in :mod:`.port_names` and the regex
#: used in :func:`_identify_vlan_parent` -- keeps the two
#: classification points aligned.
_LOOPBACK_NAME_RE = re.compile(r"^(lo|loopback)\d*$", re.IGNORECASE)


def _is_loopback_type(iface: Any) -> bool:
    """Return True if ``iface`` is a loopback by canonical type or
    by name shape.

    The ``interface_type`` check covers cross-vendor sources that
    populate the IANA-IF-MIB type (FortiGate, Junos).  The name-
    shape fallback covers sources that leave the type empty but
    use the canonical loopback naming (Cisco IOS-XE NETCONF,
    Arista EOS), so a renamed ``Loopback0`` -> ``lo0`` still gets
    the right declaration on the wire.
    """
    if iface.interface_type in _LOOPBACK_TYPES:
        return True
    return bool(_LOOPBACK_NAME_RE.match(iface.name))


def _is_tunnel_type(iface: Any) -> bool:
    """Return True if ``iface.interface_type`` indicates a tunnel.

    No name-shape fallback here -- tunnel naming is more vendor-
    specific (``Tunnel0``, ``gre1``, ``gr-0/0/0``, ``ssl.root``)
    and conflating one of those shapes with a loopback or
    ethernet would be silently wrong.  Codecs that emit tunnels
    MUST populate :attr:`CanonicalInterface.interface_type`.
    """
    return iface.interface_type in _TUNNEL_TYPES


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
