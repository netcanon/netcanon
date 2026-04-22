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
    CanonicalIPv4Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from ..base import CodecBase, ParseError, RenderError
from ..registry import register


@register
class FortiGateCLICodec(CodecBase):
    """Codec for FortiGate CLI (``config/edit/set/next/end``)."""

    name: ClassVar[str] = "fortigate_cli"
    version_hint: ClassVar[str | None] = "7.x"
    input_format: ClassVar[str] = "cli-fortigate"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "best_effort"
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


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _looks_like_vlan_iface(name: str) -> bool:
    """FortiOS VLAN interfaces are commonly named ``vlanN`` or ``<parent>.N``."""
    if re.match(r"^vlan\d+$", name, re.IGNORECASE):
        return True
    if re.match(r"^[A-Za-z0-9_-]+\.\d+$", name):
        return True
    return False


def _vlan_id_for(name: str, vlans: list[CanonicalVlan]) -> int | None:
    """Resolve the VLAN id for an interface name.

    Checks ``vlan<N>`` naming, ``<parent>.<N>`` naming, then falls
    back to a matching VLAN definition name.
    """
    m1 = re.match(r"^vlan(\d+)$", name, re.IGNORECASE)
    if m1:
        return int(m1.group(1))
    m2 = re.match(r"^[A-Za-z0-9_-]+\.(\d+)$", name)
    if m2:
        return int(m2.group(1))
    for v in vlans:
        if v.name == name:
            return v.id
    return None


def _parent_for_vlan_iface(
    name: str, all_interfaces: list[CanonicalInterface],
) -> str | None:
    """Find the parent physical interface for a VLAN sub-interface name."""
    if "." in name:
        parent = name.split(".", 1)[0]
        if any(i.name == parent for i in all_interfaces):
            return parent
    # Fallback: first non-VLAN interface.
    for i in all_interfaces:
        if not _looks_like_vlan_iface(i.name):
            return i.name
    return None


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


def _infer_iface_type(name: str) -> str:
    """IANA ifType from FortiOS interface-name shape."""
    lower = name.lower()
    if re.match(r"^(port|ethernet|internal|wan|lan|dmz)\d*$", lower):
        return "ianaift:ethernetCsmacd"
    if lower.startswith("agg") or lower.startswith("trunk"):
        return "ianaift:ieee8023adLag"
    if lower.startswith("loopback"):
        return "ianaift:softwareLoopback"
    if lower.startswith("tunnel"):
        return "ianaift:tunnel"
    return "ianaift:ethernetCsmacd"
