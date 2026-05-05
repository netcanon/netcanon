"""
FortiGate CLI parser — recursive block model + per-stanza dispatch.

Extracted from ``codec.py`` during the parse/render split.  Everything
that consumes FortiOS text and produces a ``CanonicalIntent`` lives
here; ``render.py`` holds the reverse path.  ``codec.py`` is now a
thin class that delegates ``parse()`` and ``render()`` to module-level
functions here and in the sibling render module.

Public surface (consumed by codec.py's ``parse()`` method):

* :func:`parse_intent` — one-shot parse entry: raw text in, fully-
  populated :class:`CanonicalIntent` out.

Internal block model (still importable as ``_parse_blocks`` /
``_prefix_to_mask`` / ``_mask_to_prefix`` for tests that pin the
parser's structural contract):

* :class:`_ConfigBlock` + :class:`_EditBlock` — two-tier container
  model reflecting FortiOS's ``config / edit / set / next / end``
  5-keyword grammar.
* :func:`_parse_blocks` — recursive tokeniser producing a list of
  top-level ``_ConfigBlock`` instances.
* ``_apply_<path>`` functions — one per supported ``config <path>``
  stanza; each mutates the passed-in ``CanonicalIntent`` in-place.

IP mask utilities (shared with the render module):

* :func:`_prefix_to_mask`, :func:`_mask_to_prefix`, :func:`_split_cidr`.

The constants ``_FORTIGATE_LACP_TO_CANONICAL`` + the canonical-to-
FortiGate inverse live here (parse consumes the forward map; render
imports the inverse).  Keeping them together next to the parse
logic avoids the circular-import hazard of splitting them across
both modules.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import shlex
from typing import ClassVar

from ..base import ParseError
from ...canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from .vlan_heuristics import infer_iface_type as _infer_iface_type

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IP helpers (shared with render.py)
# ---------------------------------------------------------------------------


def _prefix_to_mask(prefix: int) -> str:
    """Convert CIDR prefix length to dotted-decimal mask."""
    # Import kept local to the function that actually raises — the
    # module-level import is enough for the isinstance check the
    # render path does, and keeping this here avoids a circular
    # dependency with base.py.
    from ..base import RenderError
    if prefix < 0 or prefix > 32:
        raise RenderError(
            f"fortigate_cli: invalid CIDR prefix {prefix}",
            yang_path="/interfaces/interface/ipv4/address/prefix-length",
        )
    mask_int = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
    return str(ipaddress.IPv4Address(mask_int))


def _mask_to_prefix(mask: str) -> int:
    """Convert dotted-decimal mask to CIDR prefix length."""
    try:
        addr = ipaddress.IPv4Address(mask)
    except ipaddress.AddressValueError:
        raise ParseError(
            f"fortigate_cli: invalid subnet mask {mask!r}",
            snippet=mask,
        )
    bits = bin(int(addr))[2:]
    if "01" in bits:
        raise ParseError(
            f"fortigate_cli: non-contiguous subnet mask {mask!r}",
            snippet=mask,
        )
    return bits.count("1")


def _split_cidr(destination: str) -> tuple[str, int]:
    """Accept ``A.B.C.D/N`` OR ``A.B.C.D`` (implicit /32)."""
    if "/" in destination:
        ip, prefix = destination.split("/", 1)
        return ip, int(prefix)
    return destination, 32


# ---------------------------------------------------------------------------
# LACP-mode mapping (parse uses forward; render imports the inverse)
# ---------------------------------------------------------------------------


_FORTIGATE_LACP_TO_CANONICAL = {
    "active": "active",
    "passive": "passive",
    "static": "static",
}
_CANONICAL_MODE_TO_FORTIGATE_LACP = {
    "active": "active",
    "passive": "passive",
    "static": "static",
}


# ---------------------------------------------------------------------------
# Block model
# ---------------------------------------------------------------------------


class _ConfigBlock:
    """One ``config <path> ... end`` block, possibly with ``edit``s.

    May also contain nested ``config`` sub-blocks directly (e.g.
    ``config ntpserver`` inside ``config system ntp``).  Most FortiOS
    sub-tables nest inside an ``edit`` entry, but a few live at the
    config level.
    """

    def __init__(self, config_path: str) -> None:
        self.config_path: str = config_path
        self.settings: dict[str, list[str]] = {}
        self.edits: list["_EditBlock"] = []
        # Nested config-subtables at the config level.
        self.sub_blocks: list["_ConfigBlock"] = []


class _EditBlock:
    """One ``edit <id> ... next`` entry inside a ``config`` block."""

    def __init__(self, edit_id: str) -> None:
        self.edit_id: str = edit_id
        self.settings: dict[str, list[str]] = {}
        # Nested config-subtables (e.g. per-policy sub-tables).
        self.sub_blocks: list["_ConfigBlock"] = []


_CONFIG_HEADER_RE = re.compile(r"^config\s+(.+?)\s*$", re.IGNORECASE)
_EDIT_HEADER_RE = re.compile(r"^edit\s+(.+?)\s*$", re.IGNORECASE)
_SET_RE = re.compile(r"^set\s+(\S+)\s*(.*)$", re.IGNORECASE)
_COMMENT_RE = re.compile(r"^\s*#")


def _tokenize_set(value: str) -> list[str]:
    """Split a ``set`` value into tokens, honouring quoted strings."""
    value = value.strip()
    if not value:
        return []
    try:
        return shlex.split(value, posix=True)
    except ValueError:
        # Unbalanced quote — fall back to whitespace split.
        return value.split()


def _parse_blocks(raw: str) -> list[_ConfigBlock]:
    """Parse a FortiOS CLI text into a list of top-level ``config`` blocks.

    Nested ``config`` blocks inside an ``edit`` attach to the
    enclosing :class:`_EditBlock.sub_blocks`; otherwise they become
    new top-level entries.
    """
    lines = raw.splitlines()
    blocks: list[_ConfigBlock] = []

    # Stack of "open containers" — either ``_ConfigBlock`` or
    # ``_EditBlock``.  Top of stack is the one receiving new tokens.
    stack: list[_ConfigBlock | _EditBlock] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line or _COMMENT_RE.match(line):
            continue

        # Stanza terminators.
        if line == "end":
            # Pop everything up to and including the innermost
            # ``_ConfigBlock``.  Spurious extra ``end`` tokens are
            # tolerated silently — real FortiOS exports are
            # well-formed, but misbehaved-input resilience is cheap.
            while stack:
                top = stack.pop()
                if isinstance(top, _ConfigBlock):
                    if not stack:
                        blocks.append(top)
                    else:
                        parent = stack[-1]
                        # Nested config attaches to whichever enclosing
                        # container has a ``sub_blocks`` list — both
                        # _EditBlock and _ConfigBlock do.
                        parent.sub_blocks.append(top)
                    break
            continue
        if line == "next":
            # Pop the innermost ``_EditBlock``, re-attach to its
            # enclosing ``_ConfigBlock``.
            while stack:
                top = stack.pop()
                if isinstance(top, _EditBlock):
                    if stack and isinstance(stack[-1], _ConfigBlock):
                        stack[-1].edits.append(top)
                    break
            continue

        cm = _CONFIG_HEADER_RE.match(line)
        if cm:
            path = cm.group(1).strip().strip('"').strip("'")
            stack.append(_ConfigBlock(config_path=path))
            continue

        em = _EDIT_HEADER_RE.match(line)
        if em:
            edit_id = em.group(1).strip().strip('"').strip("'")
            stack.append(_EditBlock(edit_id=edit_id))
            continue

        sm = _SET_RE.match(line)
        if sm and stack:
            key = sm.group(1).strip()
            tokens = _tokenize_set(sm.group(2))
            stack[-1].settings[key] = tokens

    # Any unclosed containers at EOF — best-effort rescue.
    while stack:
        top = stack.pop()
        if isinstance(top, _ConfigBlock):
            if not stack:
                blocks.append(top)

    return blocks


# ---------------------------------------------------------------------------
# Per-stanza dispatchers — one ``_apply_<path>`` per supported
# ``config <path>`` at the top level.
# ---------------------------------------------------------------------------


def _apply_system_global(block: _ConfigBlock, intent: CanonicalIntent) -> None:
    hostname = block.settings.get("hostname")
    if hostname:
        intent.hostname = hostname[0]


def _apply_system_dns(block: _ConfigBlock, intent: CanonicalIntent) -> None:
    primary = block.settings.get("primary")
    if primary:
        intent.dns_servers.append(primary[0])
    secondary = block.settings.get("secondary")
    if secondary:
        intent.dns_servers.append(secondary[0])
    # ``set domain "<fqdn>"`` is the FortiOS-native domain-name form
    # inside ``config system dns`` (mirrors render emit at
    # ``fortigate_cli/render.py`` ~line 450).  Without this read the
    # renderer-emitted line was silently dropped on parse, breaking
    # round-trip ``parse(render(tree))`` for ``CanonicalIntent.domain``
    # (Phase 4b finding flagged by 3 agents — arista_eos, opnsense,
    # cisco_iosxe_cli source-side).  The DHCP-pool ``set domain``
    # handler (~line 707) targets a different field
    # (``CanonicalDHCPPool.domain_name``, the per-pool search domain)
    # and remains unchanged.
    domain = block.settings.get("domain")
    if domain:
        intent.domain = domain[0]


def _apply_system_ntp(block: _ConfigBlock, intent: CanonicalIntent) -> None:
    for sub in block.sub_blocks:
        if sub.config_path != "ntpserver":
            continue
        for edit in sub.edits:
            server = edit.settings.get("server")
            if server:
                intent.ntp_servers.append(server[0])


def _apply_system_interface(
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    for edit in block.edits:
        name = edit.edit_id
        iface = CanonicalInterface(name=name, enabled=True)

        alias = edit.settings.get("alias")
        if alias:
            iface.description = alias[0]

        status = edit.settings.get("status")
        if status:
            # FortiOS uses "up" / "down" for interface admin status.
            iface.enabled = status[0].lower() == "up"

        mtu_tokens = edit.settings.get("mtu")
        if mtu_tokens:
            try:
                iface.mtu = int(mtu_tokens[0])
            except ValueError:
                pass
        # FortiOS uses `set mtu-override enable` + `set mtu N` — we
        # capture mtu regardless; the override flag is not canonically
        # modelled.

        ip_tokens = edit.settings.get("ip")
        if ip_tokens and len(ip_tokens) >= 2:
            ip, mask = ip_tokens[0], ip_tokens[1]
            iface.ipv4_addresses.append(CanonicalIPv4Address(
                ip=ip,
                prefix_length=_mask_to_prefix(mask),
            ))

        # IPv6 dynamic-address mode: ``set ip6-mode {static|dhcp|
        # delegated|pppoe}`` on FortiOS.  The ``dhcp`` value populates
        # the canonical ``dhcp_client_v6`` field.  Other modes
        # (``delegated`` is RFC 3633 prefix delegation, ``pppoe`` is
        # the LAC client) don't have a clean cross-vendor mapping and
        # are intentionally not surfaced here.  ``static`` is the
        # FortiOS default and means "no DHCPv6"; we don't populate
        # the field.
        ip6_mode_tokens = edit.settings.get("ip6-mode")
        if ip6_mode_tokens and ip6_mode_tokens[0]:
            mode_value = ip6_mode_tokens[0].lower().strip('"')
            if mode_value == "dhcp":
                iface.dhcp_client_v6 = "dhcp6"

        # GAP-EVPN-3: ``set ip6-address <addr>/<prefix>`` (CIDR form,
        # FortiOS native).  ``set ip6-address ::/0`` is "no IPv6
        # address" — drop the all-zero placeholder rather than emit
        # a canonical record for it.
        ip6_tokens = edit.settings.get("ip6-address")
        if ip6_tokens and ip6_tokens[0]:
            v6_token = ip6_tokens[0]
            if "/" in v6_token:
                ip_part, prefix_str = v6_token.split("/", 1)
                # Filter the FortiOS placeholder ``::/0`` (semantic
                # "no v6 address" — every interface in the corpus
                # carries this default and treating it as a real
                # address would flood the canonical tree).
                if ip_part not in ("::", "0::"):
                    try:
                        iface.ipv6_addresses.append(CanonicalIPv6Address(
                            ip=ip_part,
                            prefix_length=int(prefix_str),
                            scope="global",
                        ))
                    except ValueError:
                        pass

        iface_type = edit.settings.get("type")
        vlanid = edit.settings.get("vlanid")
        parent_iface = edit.settings.get("interface")
        member_tokens = edit.settings.get("member")
        type_value = iface_type[0].lower() if iface_type else ""

        # Real FortiOS configs often omit `set type vlan`, leaving
        # vlanid + interface (parent) as the only VLAN signals.  Treat
        # either form as a VLAN subinterface.  Surfaced by
        # KevinGuenay/fortinet-resources FGT-70G-BRANCH.conf: VL_100
        # has no `set type` line but carries vlanid=100 /
        # interface=LAG_INTERNAL and is unambiguously a VLAN iface.
        looks_like_vlan = (
            type_value == "vlan"
            or (vlanid is not None and parent_iface is not None)
        )
        if looks_like_vlan and vlanid:
            iface.interface_type = "ianaift:l3ipvlan"
            try:
                vid = int(vlanid[0])
                # Use the iface name as the canonical VLAN name so the
                # render path can map the iface back to its VLAN id
                # via `_vlan_id_for`.  The alias (set via `set alias`)
                # is preserved on the interface's description field.
                intent.vlans.append(CanonicalVlan(id=vid, name=name))
            except ValueError:
                pass
        elif type_value == "aggregate":
            # LAG / 802.3ad bundle.  Members arrive as a space-
            # separated token list on the `set member` line.
            iface.interface_type = "ianaift:ieee8023adLag"
            members: list[str] = []
            if member_tokens:
                for tok in member_tokens:
                    members.extend(m for m in tok.split() if m)
            lacp_mode = edit.settings.get("lacp-mode")
            mode = _FORTIGATE_LACP_TO_CANONICAL.get(
                lacp_mode[0].lower() if lacp_mode else "active", "active"
            )
            intent.lags.append(CanonicalLAG(
                name=name,
                members=members,
                mode=mode,
            ))
            # Reverse-link on members we already know about.  Members
            # defined later in the same block will be wired up on the
            # second-pass below.
            for m in members:
                for prev in intent.interfaces:
                    if prev.name == m and prev.lag_member_of is None:
                        prev.lag_member_of = name
        else:
            iface.interface_type = _infer_iface_type(name)

        intent.interfaces.append(iface)

    # Second pass: interface-order independence — members defined after
    # their aggregate edit still get their lag_member_of stamped.
    lag_members: dict[str, str] = {}
    for lag in intent.lags:
        for m in lag.members:
            lag_members.setdefault(m, lag.name)
    for iface in intent.interfaces:
        if iface.lag_member_of is None and iface.name in lag_members:
            iface.lag_member_of = lag_members[iface.name]


def _apply_snmp_sysinfo(
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    """Parse ``config system snmp sysinfo`` — contact + location + desc."""
    contact = block.settings.get("contact-info")
    location = block.settings.get("location")
    if contact or location:
        if intent.snmp is None:
            intent.snmp = CanonicalSNMP()
        if contact:
            intent.snmp.contact = contact[0]
        if location:
            intent.snmp.location = location[0]


def _apply_snmp_community(
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    """Parse ``config system snmp community`` — community strings +
    trap host sub-tables."""
    for edit in block.edits:
        name = edit.settings.get("name")
        if not name:
            continue
        if intent.snmp is None:
            intent.snmp = CanonicalSNMP()
        if not intent.snmp.community:
            intent.snmp.community = name[0]
        # Nested hosts sub-block records trap targets.
        for sub in edit.sub_blocks:
            if sub.config_path != "hosts":
                continue
            for host_edit in sub.edits:
                ip_tokens = host_edit.settings.get("ip")
                if not ip_tokens:
                    continue
                # FortiOS writes `set ip "1.2.3.4 255.255.255.255"`
                # as a single quoted string — shlex keeps it together.
                # Split on whitespace to pull out just the IP.
                first_token = ip_tokens[0].split()[0]
                intent.snmp.trap_hosts.append(first_token)


def _apply_snmp_user(
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    """Parse ``config system snmp user`` — SNMPv3 USM users.

    FortiOS grammar (7.0+ stable; 7.2+ keeps same knobs with added
    SHA-256/384/512 support):

    .. code-block:: text

        config system snmp user
            edit "netadmin"
                set security-level auth-priv
                set auth-proto sha256
                set auth-pwd ENC encrypted-hash-blob==
                set priv-proto aes256
                set priv-pwd ENC encrypted-hash-blob==
            next
        end

    FortiOS doesn't carry an explicit "group" surface — each user is
    self-grouped by its security-level.  ``group`` lands empty on
    canonical; renderers that require one (Cisco, Junos, Aruba)
    synthesise a default.

    The ``ENC`` prefix on password fields is FortiOS's encrypted-
    blob marker.  We carry it verbatim: shlex keeps ``ENC <hash>``
    together as one quoted string when the operator exported with
    quotes, or as two tokens otherwise.  Either shape round-trips
    because the renderer re-quotes on output.
    """
    for edit in block.edits:
        name_tokens = [edit.edit_id] if edit.edit_id else (
            edit.settings.get("name") or []
        )
        if not name_tokens:
            continue
        if intent.snmp is None:
            intent.snmp = CanonicalSNMP()
        name = name_tokens[0]
        from ...canonical.intent import CanonicalSNMPv3User
        # FortiOS auth-proto → canonical.
        _FG_AUTH_MAP = {
            "md5": "md5",
            "sha": "sha",
            "sha1": "sha",
            "sha224": "sha224",
            "sha256": "sha256",
            "sha384": "sha384",
            "sha512": "sha512",
        }
        # FortiOS priv-proto → canonical.  ``aes`` on older FOS =
        # AES-128; newer ``aes256`` / ``aes256cisco`` are distinct.
        _FG_PRIV_MAP = {
            "des": "des",
            "aes": "aes128",
            "aes128": "aes128",
            "aes192": "aes192",
            "aes256": "aes256",
            # ``aes256cisco`` is an interop mode — treat as aes256
            # on the canonical (lossy) and let operators re-key on
            # non-FortiGate targets.
            "aes256cisco": "aes256",
        }
        auth_proto_tokens = edit.settings.get("auth-proto") or [""]
        priv_proto_tokens = edit.settings.get("priv-proto") or [""]
        auth_proto = _FG_AUTH_MAP.get(
            auth_proto_tokens[0].lower(), "",
        )
        priv_proto = _FG_PRIV_MAP.get(
            priv_proto_tokens[0].lower(), "",
        )
        # FortiOS exports ``set auth-pwd ENC <hash>`` as two tokens
        # when unquoted, or a single quoted string when the operator
        # exported with `show full-configuration`.  Join with space
        # so the canonical passphrase carries the ``ENC`` marker
        # + hash verbatim, matching the local-user pattern above.
        auth_pwd_tokens = edit.settings.get("auth-pwd") or []
        priv_pwd_tokens = edit.settings.get("priv-pwd") or []
        auth_passphrase = " ".join(auth_pwd_tokens) if auth_pwd_tokens else ""
        priv_passphrase = " ".join(priv_pwd_tokens) if priv_pwd_tokens else ""
        intent.snmp.v3_users.append(CanonicalSNMPv3User(
            name=name,
            auth_protocol=auth_proto,
            auth_passphrase=auth_passphrase,
            priv_protocol=priv_proto,
            priv_passphrase=priv_passphrase,
        ))


def _apply_router_static(
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    for edit in block.edits:
        dst = edit.settings.get("dst")
        if not dst or len(dst) < 2:
            # Default-route entries sometimes use `dstaddr` instead;
            # keep the scope narrow for now.
            continue
        ip, mask = dst[0], dst[1]
        destination = f"{ip}/{_mask_to_prefix(mask)}"
        gateway_tokens = edit.settings.get("gateway") or [""]
        device_tokens = edit.settings.get("device") or [""]
        # FortiOS `set comment "<text>"` (singular) is the per-route
        # description slot; the render emits it via
        # ``CanonicalStaticRoute.description``.  Closing the parser
        # gap so the canonical description round-trips through a
        # FortiGate -> FortiGate (or any source -> FortiGate) pipe.
        # Ref: https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/522620/config-router-static
        comment_tokens = edit.settings.get("comment") or [""]
        intent.static_routes.append(CanonicalStaticRoute(
            destination=destination,
            gateway=gateway_tokens[0],
            interface=device_tokens[0],
            description=comment_tokens[0],
        ))


def _apply_system_admin(
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    """Parse ``config system admin`` into CanonicalLocalUser records.

    Each ``edit "NAME"`` is an administrator account.  Relevant fields:
        set password ENC <hash>      - current encrypted password
        set old-password ENC <hash>  - previous password (seen in some
                                       exports; we use as fallback if
                                       `password` isn't present)
        set accprofile "<profile>"   - admin profile; super_admin = 15
        set trusthost<N> <net> <mask>- IP allowlist (not modelled)

    FortiOS encrypts passwords with an internal-key scheme; the ``ENC``
    prefix denotes this.  We preserve the ENC-prefixed hash verbatim
    under canonical ``hashed_password`` so a lossless round-trip back
    to a FortiGate target reconstructs the original command.
    """
    for edit in block.edits:
        name = edit.edit_id
        pw_tokens = edit.settings.get("password") or edit.settings.get("old-password")
        hashed = ""
        if pw_tokens:
            # FortiOS form: `set password ENC <base64>` -> tokens
            # split by whitespace inside the shlex-aware settings dict
            # end up as ["ENC", "<base64>"]; join them back with a
            # "fortios:" prefix so target renderers can route.
            joined = " ".join(pw_tokens)
            hashed = f"fortios:{joined}"
        accprofile_tokens = edit.settings.get("accprofile")
        accprofile = (
            accprofile_tokens[0].lower() if accprofile_tokens else ""
        )
        # super_admin is FortiOS's built-in full-access profile.
        # prof_admin / custom profiles are usually scoped.
        is_admin = accprofile == "super_admin"
        intent.local_users.append(CanonicalLocalUser(
            name=name,
            privilege_level=15 if is_admin else 1,
            hashed_password=hashed,
            role=accprofile or ("admin" if is_admin else "operator"),
        ))


def _apply_user_radius(
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    """Parse ``config user radius`` into CanonicalRADIUSServer records.

    FortiOS shape:
        edit "MyRadius"
            set server "10.0.0.4"
            set secret ENC <encoded>
            set auth-type auto
            set radius-port 1812
            set acct-interim-interval 600
        next

    The ``ENC`` prefix is preserved on the canonical key so a lossless
    round-trip back to FortiGate reconstructs the original command.
    """
    for edit in block.edits:
        server_tokens = edit.settings.get("server")
        if not server_tokens:
            continue
        host = server_tokens[0]
        secret_tokens = edit.settings.get("secret")
        key = ""
        if secret_tokens:
            key = f"fortios:{' '.join(secret_tokens)}"
        auth_port = 1812
        acct_port = 1813
        port_tokens = edit.settings.get("radius-port")
        if port_tokens:
            try:
                raw_port = int(port_tokens[0])
            except ValueError:
                raw_port = 1812
            # FortiOS uses `set radius-port 0` to mean "use the default
            # port 1812" — real FG100E captures written by FortiGate's
            # own config export contain this idiom.  Canonicalise to the
            # effective value (1812) so round-trip stays stable:
            # renderer omits when auth_port == 1812 (matching FortiOS's
            # own default-omission pattern), re-parse sees no
            # radius-port, defaults to 1812.  Storing 0 would drift.
            if raw_port != 0:
                auth_port = raw_port
        intent.radius_servers.append(CanonicalRADIUSServer(
            host=host,
            key=key,
            auth_port=auth_port,
            acct_port=acct_port,
        ))


def _apply_system_dhcp_server(
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    """Parse ``config system dhcp server`` into CanonicalDHCPPool records.

    Each ``edit <id>`` is a DHCP pool.  Relevant fields:
        set lease-time <seconds>
        set default-gateway <ip>
        set netmask <dotted-decimal>
        set interface "<iface>"
        set dns-service default|specify
        set dns-server1 <ip>
        set dns-server2 <ip>
        set domain "<domain>"
        config ip-range                         (nested)
            edit 1
                set start-ip <ip>
                set end-ip <ip>
            next
        end
    """
    for edit in block.edits:
        pool = CanonicalDHCPPool()
        iface_tokens = edit.settings.get("interface")
        if iface_tokens:
            pool.interface = iface_tokens[0]
        gw_tokens = edit.settings.get("default-gateway")
        if gw_tokens:
            pool.gateway = gw_tokens[0]
        netmask_tokens = edit.settings.get("netmask")
        if netmask_tokens and gw_tokens:
            # Derive network CIDR from gateway + netmask.  Gateway
            # typically sits on the pool's network; masking gives the
            # network address.
            try:
                gw = ipaddress.IPv4Interface(
                    f"{gw_tokens[0]}/{_mask_to_prefix(netmask_tokens[0])}"
                )
                pool.network = str(gw.network)
            except (ipaddress.AddressValueError, ValueError):
                pass
        # DNS servers come in as dns-server1 / dns-server2 / dns-server3
        for i in range(1, 4):
            key = f"dns-server{i}"
            dns_tokens = edit.settings.get(key)
            if dns_tokens:
                pool.dns_servers.append(dns_tokens[0])
        domain_tokens = edit.settings.get("domain")
        if domain_tokens:
            pool.domain_name = domain_tokens[0]
        lease_tokens = edit.settings.get("lease-time")
        if lease_tokens:
            try:
                pool.lease_time = int(lease_tokens[0])
            except ValueError:
                pass

        # Nested `config ip-range` block carves out the allocation range.
        for sub in edit.sub_blocks:
            if sub.config_path != "ip-range":
                continue
            for range_edit in sub.edits:
                start_tokens = range_edit.settings.get("start-ip")
                end_tokens = range_edit.settings.get("end-ip")
                if start_tokens and not pool.start_ip:
                    pool.start_ip = start_tokens[0]
                if end_tokens and not pool.end_ip:
                    pool.end_ip = end_tokens[0]

        intent.dhcp_servers.append(pool)


# ---------------------------------------------------------------------------
# Public parse entry point
# ---------------------------------------------------------------------------


#: Dispatch table from ``config <path>`` (as captured after the
#: ``config`` keyword) to the per-stanza applier.  Paths absent from
#: this table are silently ignored — FortiOS exports carry many
#: Tier-3 sections (firewall policies, SD-WAN rules, UTM profiles)
#: that we deliberately don't model.
_DISPATCH: ClassVar[dict[str, object]] = {
    "system global": _apply_system_global,
    "system dns": _apply_system_dns,
    "system ntp": _apply_system_ntp,
    "system interface": _apply_system_interface,
    "router static": _apply_router_static,
    "system snmp sysinfo": _apply_snmp_sysinfo,
    "system snmp community": _apply_snmp_community,
    "system snmp user": _apply_snmp_user,
    "system admin": _apply_system_admin,
    "system dhcp server": _apply_system_dhcp_server,
    "user radius": _apply_user_radius,
}


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse a FortiOS CLI export into :class:`CanonicalIntent`.

    Raises :class:`ParseError` when the input is empty or looks like
    a different format (XML / JSON).  Unrecognised ``config`` paths
    fall through as silent drops; if you need tolerant-mode guarantees
    for a new path, add it to the ``_DISPATCH`` table with an
    ``_apply_<path>`` function.
    """
    if not raw.strip():
        raise ParseError(
            "fortigate_cli: empty input", snippet="",
        )
    stripped = raw.lstrip()
    if stripped.startswith("<"):
        raise ParseError(
            "fortigate_cli: input looks like XML, not FortiOS CLI.",
            snippet=stripped[:120],
        )
    if stripped.startswith("{"):
        raise ParseError(
            "fortigate_cli: input looks like JSON, not FortiOS CLI.",
            snippet=stripped[:120],
        )

    intent = CanonicalIntent(
        source_vendor="fortigate",
        source_format="cli-fortigate",
    )

    blocks = _parse_blocks(raw)
    # Track which top-level paths we saw vs which we dispatched — the
    # gap is the set of silently-ignored stanzas (Tier 3 / out of
    # scope).  DEBUG surface lets ops see what was dropped without
    # requiring a separate grep pass.
    ignored_paths: list[str] = []
    for block in blocks:
        applier = _DISPATCH.get(block.config_path)
        if applier is not None:
            applier(block, intent)
        else:
            ignored_paths.append(block.config_path)

    logger.debug(
        "fortigate_cli parsed: hostname=%r ifaces=%d vlans=%d "
        "routes=%d lags=%d users=%d snmp=%s dhcp=%d radius=%d "
        "blocks=%d ignored=%d (input=%d chars)",
        intent.hostname,
        len(intent.interfaces),
        len(intent.vlans),
        len(intent.static_routes),
        len(intent.lags),
        len(intent.local_users),
        "yes" if intent.snmp else "no",
        len(intent.dhcp_servers),
        len(intent.radius_servers),
        len(blocks),
        len(ignored_paths),
        len(raw),
    )
    # Only emit the ignored-paths detail when there's actual gap to
    # report — avoids noise on clean round-trip cases.
    if ignored_paths:
        logger.debug(
            "fortigate_cli: %d unhandled config path(s) dropped: %s",
            len(ignored_paths),
            ", ".join(sorted(set(ignored_paths))[:15]),
        )

    return intent
