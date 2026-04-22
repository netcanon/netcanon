"""
``FortiGateCLICodec`` — 5th real codec, Session D.

See package ``__init__`` for scope and structural notes.
"""

from __future__ import annotations

import ipaddress
import re
import shlex
from typing import Any, ClassVar, Iterable

from ....models.migration import (
    CapabilityMatrix,
    DeviceClass,
    LossyPath,
    UnsupportedPath,
)
from ...canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIPv4Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from ..base import CodecBase, ParseError, RenderError
from ..registry import register
from . import port_names as _port_names
from .vlan_heuristics import (
    infer_iface_type as _infer_iface_type,
    looks_like_vlan_iface as _looks_like_vlan_iface,
    parent_for_vlan_iface as _parent_for_vlan_iface,
    vlan_id_for as _vlan_id_for,
)


@register
class FortiGateCLICodec(CodecBase):
    """Codec for FortiGate CLI (``config/edit/set/next/end``)."""

    name: ClassVar[str] = "fortigate_cli"
    version_hint: ClassVar[str | None] = "7.x"
    input_format: ClassVar[str] = "cli-fortigate"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste FortiOS CLI export (`config/edit/set/next/end` grammar).  "
        "The codec parses system global, dns, ntp, interface, and "
        "router static blocks.  Firewall policies are Tier 3 and not "
        "yet auto-translated."
    )
    sample_input: ClassVar[str] = (
        '#config-version=FGT60E-7.4\n'
        'config system global\n'
        '    set hostname "fgt-edge"\n'
        'end\n'
        'config system interface\n'
        '    edit "port1"\n'
        '        set alias "WAN"\n'
        '        set ip 198.51.100.2 255.255.255.252\n'
        '        set status up\n'
        '    next\n'
        'end\n'
        'config router static\n'
        '    edit 1\n'
        '        set dst 0.0.0.0 0.0.0.0\n'
        '        set gateway 198.51.100.1\n'
        '    next\n'
        'end\n'
    )
    output_extension: ClassVar[str] = "conf"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="fortigate_cli",
        vendor_id="fortigate",
        version_range="7.x",
        device_classes=[DeviceClass.firewall, DeviceClass.router],
        supported=[
            "/system/hostname",
            "/system/dns-server",
            "/system/ntp-server",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/config/type",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
            # Tier 2 — SNMP
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/config/description",
                reason=(
                    "FortiOS limits alias to 25 characters; longer "
                    "descriptions from other vendors will be truncated."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "FortiOS has no IANA ifType; inferred from 'type vlan' "
                    "sub-setting or name shape."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/filter/rule",
                reason=(
                    "FortiGate policy rules (config firewall policy) are "
                    "Tier 3 — policy semantics differ fundamentally from "
                    "other vendors (session-based, zone-aware, UTM-enabled)."
                ),
            ),
            UnsupportedPath(
                path="/nat/rule",
                reason=(
                    "FortiGate NAT lives inside firewall policy and "
                    "address/VIP objects — not auto-translatable."
                ),
            ),
        ],
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    # -----------------------------------------------------------------
    # Parse
    # -----------------------------------------------------------------

    def parse(self, raw: str) -> CanonicalIntent:
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
        for block in blocks:
            path = block.config_path
            if path == "system global":
                _apply_system_global(block, intent)
            elif path == "system dns":
                _apply_system_dns(block, intent)
            elif path == "system ntp":
                _apply_system_ntp(block, intent)
            elif path == "system interface":
                _apply_system_interface(block, intent)
            elif path == "router static":
                _apply_router_static(block, intent)
            elif path == "system snmp sysinfo":
                _apply_snmp_sysinfo(block, intent)
            elif path == "system snmp community":
                _apply_snmp_community(block, intent)
            elif path == "system admin":
                _apply_system_admin(block, intent)
            elif path == "system dhcp server":
                _apply_system_dhcp_server(block, intent)
            elif path == "user radius":
                _apply_user_radius(block, intent)
            # Other config paths silently ignored (Tier 3 / out of scope).

        return intent

    # -----------------------------------------------------------------
    # Render
    # -----------------------------------------------------------------

    def render(self, tree: Any) -> str:
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
        if all_ifaces:
            out.append("config system interface")
            for iface in all_ifaces:
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
            out.append("end")

        # --- system snmp (Tier 2) ---
        if tree.snmp is not None and (
            tree.snmp.community or tree.snmp.location
            or tree.snmp.contact or tree.snmp.trap_hosts
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

        # --- system admin (Tier 2 local users) ---
        if tree.local_users:
            out.append("config system admin")
            for user in tree.local_users:
                out.append(f'    edit "{user.name}"')
                # Strip the "fortios:" tag when rendering back to a
                # FortiGate target (lossless for intra-vendor
                # round-trip); foreign hashes get emitted verbatim
                # under a generic ENC marker — deploy-time rejection
                # is the intended failure mode.
                if user.hashed_password:
                    alg, _, raw = user.hashed_password.partition(":")
                    if alg == "fortios":
                        out.append(f"        set password {raw}")
                    elif raw:
                        out.append(f"        set password ENC {raw}")
                    else:
                        out.append(
                            f"        set password ENC {user.hashed_password}"
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
                        import ipaddress
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

    # -----------------------------------------------------------------
    # iter_xpaths
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        if isinstance(tree, CanonicalIntent):
            from ..cisco_iosxe_cli.codec import _walk_canonical
            yield from _walk_canonical(tree)

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation
    # -----------------------------------------------------------------

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation
    # -----------------------------------------------------------------
    # Implementation extracted to :mod:`.port_names` — these methods
    # delegate so the codec class stays focused on parse/render.

    def classify_port_name(self, name: str):
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        return _port_names.format_port_identity(identity)

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect FortiOS CLI.

        Signals:
            * ``#config-version=`` banner on the first line (unique)
            * ``config system global`` stanza header
            * ``config/edit/set/next/end`` 5-keyword grammar presence
        """
        stripped = raw_prefix.lstrip()
        if stripped.startswith("<") or stripped.startswith("{"):
            return None
        if raw_prefix.startswith("#config-version="):
            return (98, "FortiOS '#config-version=' banner present")
        hits = 0
        if re.search(r"^config\s+system\s+global\s*$",
                     raw_prefix, re.MULTILINE):
            hits += 1
        if re.search(r"^config\s+system\s+interface\s*$",
                     raw_prefix, re.MULTILINE):
            hits += 1
        if re.search(r"^\s*edit\s+\"?\S+\"?\s*$",
                     raw_prefix, re.MULTILINE):
            hits += 1
        if re.search(r"^\s*(next|end)\s*$", raw_prefix, re.MULTILINE):
            hits += 1
        if hits >= 3:
            return (92, f"{hits} FortiOS grammar markers present")
        if hits == 2:
            return (75, "partial FortiOS grammar match")
        return None


# ---------------------------------------------------------------------------
# Parser — recursive block model
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
        intent.static_routes.append(CanonicalStaticRoute(
            destination=destination,
            gateway=gateway_tokens[0],
            interface=device_tokens[0],
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
                import ipaddress
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
# Render helpers
# ---------------------------------------------------------------------------


# VLAN-naming heuristics (``_looks_like_vlan_iface``, ``_vlan_id_for``,
# ``_parent_for_vlan_iface``) extracted to :mod:`.vlan_heuristics` —
# they're shared between parse and render paths, so centralising
# them prevents drift if FortiOS adds a new VLAN-naming convention.
# The underscore-prefixed aliases imported at the top of this file
# preserve the existing call sites verbatim.


def _prefix_to_mask(prefix: int) -> str:
    """Convert CIDR prefix length to dotted-decimal mask."""
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


# ``_infer_iface_type`` now lives in :mod:`.vlan_heuristics` alongside
# the VLAN-naming helpers — the ifType inference shares the same
# "name-shape → canonical property" pattern and the rules are
# symmetric with the VLAN-detection rules.
