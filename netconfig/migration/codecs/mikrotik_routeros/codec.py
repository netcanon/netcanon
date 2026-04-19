"""
``MikroTikRouterOSCodec`` — third real codec, Session 2 of the
vendor-config-research plan.

Input format
------------
RouterOS ``/export verbose`` output.  Line-oriented, section-oriented
grammar::

    # leading comment banner

    /system identity
    set name=router1

    /interface ethernet
    set [ find default-name=ether1 ] comment="WAN uplink" disabled=no
    set [ find default-name=ether2 ] comment="LAN trunk"  disabled=no

    /interface vlan
    add comment="Users" interface=bridge1 name=vlan10 vlan-id=10

    /ip address
    add address=192.168.10.1/24 interface=vlan10 network=192.168.10.0

    /ip route
    add dst-address=0.0.0.0/0 gateway=198.51.100.1

    /system dns
    set servers=1.1.1.1,8.8.8.8

    /system ntp client
    set enabled=yes servers=pool.ntp.org

Tree shape
----------
Every ``parse()`` returns a :class:`CanonicalIntent`; every
``render()`` consumes one.  Same contract as every other canonical-
bridged codec.

Round-trip invariant
--------------------
``parse(render(tree)) == tree`` for the supported canonical subset
(hostname, interfaces, VLANs, static_routes, DNS/NTP servers).
RouterOS defaults that we don't model (auto-mac, distance, etc.) are
either omitted on render or stamped with the MikroTik-conventional
default, so repeated parse/render cycles stabilise after one pass.
"""

from __future__ import annotations

import re
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
class MikroTikRouterOSCodec(CodecBase):
    """Codec for MikroTik RouterOS ``/export verbose`` text.

    Declares ``device_classes=[router, firewall]`` — RouterOS runs the
    gamut from SOHO routers to carrier-grade firewalls; translation
    against anything that shares ``router`` (IOS-XE, OPNsense) is
    permitted by the class guard.
    """

    name: ClassVar[str] = "mikrotik_routeros"
    version_hint: ClassVar[str | None] = "7.x"
    input_format: ClassVar[str] = "cli-mikrotik"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "best_effort"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the output of `/export verbose` on RouterOS.  The codec "
        "parses the section/add/set grammar (/system identity, "
        "/interface ethernet, /ip address, etc)."
    )
    sample_input: ClassVar[str] = (
        '# by RouterOS 7.13\n'
        '/system identity\n'
        'set name=router1\n'
        '\n'
        '/interface ethernet\n'
        'set [ find default-name=ether1 ] comment="WAN uplink" disabled=no\n'
        '\n'
        '/ip address\n'
        'add address=198.51.100.2/30 interface=ether1\n'
        '\n'
        '/ip route\n'
        'add dst-address=0.0.0.0/0 gateway=198.51.100.1\n'
    )
    output_extension: ClassVar[str] = "rsc"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="mikrotik_routeros",
        vendor_id="mikrotik_routeros",
        version_range="7.x",
        device_classes=[DeviceClass.router, DeviceClass.firewall],
        supported=[
            "/system/hostname",
            "/system/dns-server",
            "/system/ntp-server",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
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
                path="/interfaces/interface/config/type",
                reason=(
                    "RouterOS does not expose IANA ifType; the codec "
                    "infers it from the interface-name prefix "
                    "(etherN → ethernetCsmacd, vlanN → l3ipvlan)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/name",
                reason=(
                    "MikroTik stores a VLAN's name as the L3 interface "
                    "name (e.g. vlan10), NOT a separate descriptive "
                    "name field.  Cross-vendor rendering may conflate "
                    "the two."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/filter/rule",
                reason=(
                    "Firewall filter rules are Tier 3 (informational) "
                    "and not auto-rendered by the canonical bridge."
                ),
            ),
            UnsupportedPath(
                path="/nat/rule",
                reason="NAT rules are Tier 3 — informational only.",
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
        """Parse RouterOS ``/export verbose`` text into a
        :class:`CanonicalIntent`.

        Raises:
            ParseError: On empty input or input that clearly isn't
                RouterOS (XML, JSON, etc).
        """
        if not raw.strip():
            raise ParseError(
                "mikrotik_routeros: empty input",
                snippet="",
            )
        stripped = raw.lstrip()
        if stripped.startswith("<"):
            raise ParseError(
                "mikrotik_routeros: input looks like XML, not RouterOS "
                "export.  Use the opnsense or cisco_iosxe codec instead.",
                snippet=stripped[:120],
            )
        if stripped.startswith("{"):
            raise ParseError(
                "mikrotik_routeros: input looks like JSON, not RouterOS "
                "export.",
                snippet=stripped[:120],
            )

        intent = CanonicalIntent(
            source_vendor="mikrotik_routeros",
            source_format="cli-mikrotik",
        )

        # Pre-process: join `\` line continuations.
        joined = _join_continuations(raw)

        # Group lines by their /section context.
        sections = _group_by_section(joined)

        # Walk each section with a section-specific handler.
        # Interfaces need to be assembled across multiple sections
        # (ethernet sets properties, vlan adds a new interface, ip
        # address attaches addresses) so we carry an accumulator.
        iface_by_name: dict[str, CanonicalInterface] = {}

        for section, lines in sections:
            if section == "/system identity":
                _parse_system_identity(lines, intent)
            elif section == "/system dns":
                _parse_system_dns(lines, intent)
            elif section == "/system ntp client":
                _parse_system_ntp(lines, intent)
            elif section == "/interface ethernet":
                _parse_interface_ethernet(lines, iface_by_name)
            elif section == "/interface vlan":
                _parse_interface_vlan(lines, iface_by_name, intent)
            elif section == "/interface bridge":
                _parse_interface_bridge(lines, iface_by_name)
            elif section == "/interface bonding":
                _parse_interface_bonding(lines, iface_by_name, intent)
            elif section == "/ip address":
                _parse_ip_address(lines, iface_by_name)
            elif section == "/ip route":
                _parse_ip_route(lines, intent)
            elif section == "/snmp":
                _parse_snmp_root(lines, intent)
            elif section == "/snmp community":
                _parse_snmp_community(lines, intent)
            # Other sections silently ignored — not in scope yet.

        # Order interfaces deterministically: ethernet ports first
        # (by natural-sort name), then bridges, then VLANs, then rest.
        intent.interfaces = _sort_interfaces(iface_by_name.values())

        return intent

    # -----------------------------------------------------------------
    # Render
    # -----------------------------------------------------------------

    def render(self, tree: Any) -> str:
        """Render a :class:`CanonicalIntent` to RouterOS ``/export``
        text.

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
            lines.append(f"set name={tree.hostname}")
            lines.append("")

        # ----- /interface ethernet (tweaks to default ports) -----
        ethernet_ifaces = [
            i for i in tree.interfaces if _is_ethernet_name(i.name)
        ]
        if ethernet_ifaces:
            lines.append("/interface ethernet")
            for iface in ethernet_ifaces:
                parts = [f"set [ find default-name={iface.name} ]"]
                if iface.description:
                    parts.append(f'comment="{_escape(iface.description)}"')
                parts.append(f"disabled={_yes_no(not iface.enabled)}")
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
        vlan_ifaces = [
            i for i in tree.interfaces if _is_vlan_name(i.name)
        ]
        if vlan_ifaces or tree.vlans:
            lines.append("/interface vlan")
            # Match by name: each VLAN definition becomes one `add` line.
            rendered_vlan_names: set[str] = set()
            for iface in vlan_ifaces:
                vid = _vlan_id_for(iface.name, tree.vlans)
                if vid is None:
                    # Can't render a VLAN interface without an id.
                    continue
                parts = ["add"]
                if iface.description:
                    parts.append(f'comment="{_escape(iface.description)}"')
                parts.append("interface=bridge1")   # convention: single bridge
                parts.append(f"name={iface.name}")
                parts.append(f"vlan-id={vid}")
                lines.append(" ".join(parts))
                rendered_vlan_names.add(iface.name)
            # VLANs defined in intent.vlans but without a matching interface
            # still get rendered so the id survives the round-trip.
            for vlan in tree.vlans:
                synthetic_name = f"vlan{vlan.id}"
                if synthetic_name in rendered_vlan_names:
                    continue
                parts = ["add"]
                if vlan.name:
                    parts.append(f'comment="{_escape(vlan.name)}"')
                parts.append("interface=bridge1")
                parts.append(f"name={synthetic_name}")
                parts.append(f"vlan-id={vlan.id}")
                lines.append(" ".join(parts))
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
            if tree.snmp.community:
                lines.append("/snmp community")
                lines.append(
                    f"set [ find default=yes ] name={tree.snmp.community}"
                )
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

    # -----------------------------------------------------------------
    # iter_xpaths
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        """Yield schema xpaths from a :class:`CanonicalIntent`."""
        if isinstance(tree, CanonicalIntent):
            # Reuse the shared canonical walker so every codec emits
            # the same set of xpaths for the same tree.
            from ..cisco_iosxe_cli.codec import _walk_canonical
            yield from _walk_canonical(tree)

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect MikroTik RouterOS ``/export`` text.

        Unique markers: ``/system identity``, ``/interface ethernet``
        section headers, RouterOS banner ``# ... by RouterOS``, or
        the ``set [ find default-name=`` idiom.
        """
        # XML or JSON - not RouterOS.
        stripped = raw_prefix.lstrip()
        if stripped.startswith("<") or stripped.startswith("{"):
            return None
        # Banner comment from /export is the single strongest signal.
        if re.search(r"^#\s*.*by RouterOS", raw_prefix, re.MULTILINE):
            return (98, "'# ... by RouterOS' banner header present")

        # Gather all weaker signals, pick the strongest.  Two+ section
        # headers AND the find-default-name idiom together is a very
        # strong signal; either alone is medium-strong.
        section_hits = 0
        if re.search(r"^/system identity", raw_prefix, re.MULTILINE):
            section_hits += 1
        if re.search(r"^/interface (ethernet|vlan|bridge|wireless)",
                     raw_prefix, re.MULTILINE):
            section_hits += 1
        if re.search(r"^/ip (address|route|dns)",
                     raw_prefix, re.MULTILINE):
            section_hits += 1
        has_find_idiom = "[ find default-name=" in raw_prefix

        if section_hits >= 2 and has_find_idiom:
            return (97, "multiple RouterOS sections + find-default-name idiom")
        if section_hits >= 2:
            return (95, f"{section_hits} RouterOS section headers present")
        if has_find_idiom:
            return (90, "RouterOS 'set [ find default-name=...]' idiom present")
        if section_hits == 1:
            return (80, "one RouterOS section header present")
        return None


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------


_SECTION_RE = re.compile(r"^(/[a-zA-Z][a-zA-Z0-9 \-]*)$")
_COMMENT_RE = re.compile(r"^\s*#")


def _join_continuations(raw: str) -> str:
    """Collapse RouterOS ``\\`` line continuations into single lines."""
    out: list[str] = []
    buffer = ""
    for line in raw.splitlines():
        if buffer:
            buffer += " " + line.strip()
        else:
            buffer = line
        if buffer.rstrip().endswith("\\"):
            # Strip the trailing backslash and keep buffering.
            buffer = buffer.rstrip()[:-1].rstrip()
            continue
        out.append(buffer)
        buffer = ""
    if buffer:
        out.append(buffer)
    return "\n".join(out)


def _group_by_section(raw: str) -> list[tuple[str, list[str]]]:
    """Group lines by their ``/section`` heading.

    Returns a list of (section, lines) pairs preserving order.  Lines
    that don't belong to any section (file-level banner) are dropped.
    """
    groups: list[tuple[str, list[str]]] = []
    current_section: str | None = None
    current_lines: list[str] = []

    for line in raw.splitlines():
        stripped = line.rstrip()
        if not stripped or _COMMENT_RE.match(stripped):
            continue
        m = _SECTION_RE.match(stripped)
        if m:
            if current_section is not None:
                groups.append((current_section, current_lines))
            current_section = m.group(1)
            current_lines = []
            continue
        if current_section is None:
            continue
        current_lines.append(stripped)

    if current_section is not None:
        groups.append((current_section, current_lines))
    return groups


_KV_RE = re.compile(
    r"""
    ([\w\-]+)             # key
    =
    (                     # value:
        "[^"]*"           #   double-quoted string, OR
      | [^\s]+            #   bare token (no spaces)
    )
    """,
    re.VERBOSE,
)


def _parse_kv(line: str) -> dict[str, str]:
    """Parse ``key=value`` pairs from a single command line.

    Handles quoted values with spaces.  Unquotes the result so the
    caller gets the raw value.  Ignores the leading verb
    (``add``/``set``/``remove``) and any ``[ find ... ]`` predicate.
    """
    pairs: dict[str, str] = {}
    for m in _KV_RE.finditer(line):
        key = m.group(1)
        val = m.group(2)
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        pairs[key] = val
    return pairs


_FIND_DEFAULT_NAME_RE = re.compile(r"\[\s*find\s+default-name=(\S+)\s*\]")


def _parse_system_identity(lines: list[str], intent: CanonicalIntent) -> None:
    for line in lines:
        if line.startswith("set"):
            kv = _parse_kv(line)
            if "name" in kv:
                intent.hostname = kv["name"]
                return


def _parse_system_dns(lines: list[str], intent: CanonicalIntent) -> None:
    for line in lines:
        if line.startswith("set"):
            kv = _parse_kv(line)
            if "servers" in kv:
                intent.dns_servers = [
                    s.strip() for s in kv["servers"].split(",") if s.strip()
                ]


def _parse_system_ntp(lines: list[str], intent: CanonicalIntent) -> None:
    for line in lines:
        if line.startswith("set"):
            kv = _parse_kv(line)
            if "servers" in kv:
                intent.ntp_servers = [
                    s.strip() for s in kv["servers"].split(",") if s.strip()
                ]


def _parse_interface_ethernet(
    lines: list[str],
    iface_by_name: dict[str, CanonicalInterface],
) -> None:
    """Parse ``set [ find default-name=etherN ] ...`` tweaks."""
    for line in lines:
        if not line.startswith("set"):
            continue
        fm = _FIND_DEFAULT_NAME_RE.search(line)
        if not fm:
            continue
        name = fm.group(1)
        kv = _parse_kv(line)
        iface = iface_by_name.setdefault(
            name,
            CanonicalInterface(
                name=name,
                interface_type="ianaift:ethernetCsmacd",
            ),
        )
        if "comment" in kv:
            iface.description = kv["comment"]
        if "disabled" in kv:
            iface.enabled = kv["disabled"].lower() == "no"


def _parse_interface_vlan(
    lines: list[str],
    iface_by_name: dict[str, CanonicalInterface],
    intent: CanonicalIntent,
) -> None:
    """Parse ``add ... vlan-id=N name=X ...`` VLAN interface definitions."""
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        name = kv.get("name")
        if not name:
            continue
        vlan_id_str = kv.get("vlan-id")
        if not vlan_id_str or not vlan_id_str.isdigit():
            continue
        vlan_id = int(vlan_id_str)
        iface = iface_by_name.setdefault(
            name,
            CanonicalInterface(
                name=name,
                interface_type="ianaift:l3ipvlan",
            ),
        )
        if "comment" in kv:
            iface.description = kv["comment"]
        # Disabled flag (defaults to enabled if not present).
        if "disabled" in kv:
            iface.enabled = kv["disabled"].lower() == "no"
        # Also record in intent.vlans so the VLAN database is complete.
        descriptive_name = kv.get("comment", name)
        intent.vlans.append(CanonicalVlan(
            id=vlan_id,
            name=descriptive_name,
        ))


def _parse_interface_bridge(
    lines: list[str],
    iface_by_name: dict[str, CanonicalInterface],
) -> None:
    """Parse bridge interface definitions (just record existence + name)."""
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        name = kv.get("name")
        if not name:
            continue
        iface = iface_by_name.setdefault(
            name,
            CanonicalInterface(
                name=name,
                interface_type="ianaift:bridge",
            ),
        )
        if "comment" in kv:
            iface.description = kv["comment"]


def _parse_interface_bonding(
    lines: list[str],
    iface_by_name: dict[str, CanonicalInterface],
    intent: CanonicalIntent,
) -> None:
    """Parse ``/interface bonding`` section into :class:`CanonicalLAG`
    records plus a synthetic LAG interface.

    Expected shape::

        /interface bonding
        add name=bond1 slaves=ether1,ether2 mode=802.3ad

    ``mode`` values:
        802.3ad -> LACP (canonical "active")
        active-backup / balance-* / broadcast -> static
    """
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        name = kv.get("name")
        if not name:
            continue
        slaves_raw = kv.get("slaves", "")
        members = [s.strip() for s in slaves_raw.split(",") if s.strip()]
        mode = _ROUTEROS_BONDING_MODE_TO_CANONICAL.get(
            kv.get("mode", "").lower(), "static"
        )
        lag = CanonicalLAG(name=name, members=members, mode=mode)
        intent.lags.append(lag)

        # Also materialise the LAG as a CanonicalInterface so the
        # rest of the canonical model treats it uniformly (IP
        # addresses can be attached, etc.).
        iface = iface_by_name.setdefault(
            name,
            CanonicalInterface(
                name=name,
                interface_type="ianaift:ieee8023adLag",
            ),
        )
        if "comment" in kv:
            iface.description = kv["comment"]
        # Reverse-link members.
        for m in members:
            m_iface = iface_by_name.setdefault(
                m, CanonicalInterface(name=m)
            )
            if m_iface.lag_member_of is None:
                m_iface.lag_member_of = name


_ROUTEROS_BONDING_MODE_TO_CANONICAL = {
    "802.3ad": "active",
    "active-backup": "static",
    "balance-rr": "static",
    "balance-xor": "static",
    "balance-tlb": "static",
    "balance-alb": "static",
    "broadcast": "static",
}
_CANONICAL_MODE_TO_ROUTEROS_BONDING = {
    "active": "802.3ad",
    "passive": "802.3ad",    # RouterOS doesn't distinguish LACP passive
    "static": "active-backup",
}


def _parse_ip_address(
    lines: list[str],
    iface_by_name: dict[str, CanonicalInterface],
) -> None:
    """Parse ``add address=X/Y interface=Z`` lines and attach to iface."""
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        addr = kv.get("address")
        iface_name = kv.get("interface")
        if not addr or not iface_name:
            continue
        if "/" not in addr:
            raise ParseError(
                f"mikrotik_routeros: address {addr!r} missing CIDR prefix",
                path=f"/ip address/{iface_name}",
                snippet=line[:120],
            )
        ip_str, prefix_str = addr.split("/", 1)
        try:
            prefix_len = int(prefix_str)
        except ValueError:
            raise ParseError(
                f"mikrotik_routeros: invalid CIDR prefix {prefix_str!r}",
                path=f"/ip address/{iface_name}",
                snippet=line[:120],
            )
        iface = iface_by_name.setdefault(
            iface_name,
            CanonicalInterface(name=iface_name),
        )
        iface.ipv4_addresses.append(CanonicalIPv4Address(
            ip=ip_str.strip(),
            prefix_length=prefix_len,
        ))


def _parse_snmp_root(lines: list[str], intent: CanonicalIntent) -> None:
    """Parse ``/snmp set enabled=yes contact=X location=Y`` (Tier 2).

    Sets global SNMP agent properties (contact + location).  The
    community strings live under ``/snmp community`` and are handled
    by :func:`_parse_snmp_community`.
    """
    for line in lines:
        if not line.startswith("set"):
            continue
        kv = _parse_kv(line)
        if intent.snmp is None:
            intent.snmp = CanonicalSNMP()
        if "contact" in kv:
            intent.snmp.contact = kv["contact"]
        if "location" in kv:
            intent.snmp.location = kv["location"]
        if "trap-target" in kv:
            for host in kv["trap-target"].split(","):
                h = host.strip()
                if h:
                    intent.snmp.trap_hosts.append(h)


def _parse_snmp_community(lines: list[str], intent: CanonicalIntent) -> None:
    """Parse ``/snmp community set [ find default=yes ] name=X``
    + ``add name=Y`` lines.

    RouterOS supports multiple community entries; we record the first
    one as the canonical community (CanonicalSNMP has a single
    community field — full multi-community is a Tier 2.5 refinement).
    """
    for line in lines:
        kv = _parse_kv(line)
        name = kv.get("name")
        if not name:
            continue
        if intent.snmp is None:
            intent.snmp = CanonicalSNMP()
        if not intent.snmp.community:
            intent.snmp.community = name


def _parse_ip_route(lines: list[str], intent: CanonicalIntent) -> None:
    """Parse ``add dst-address=... gateway=...`` static routes."""
    for line in lines:
        if not line.startswith("add"):
            continue
        kv = _parse_kv(line)
        dest = kv.get("dst-address")
        if not dest:
            continue
        gateway = kv.get("gateway", "")
        # gateway may be an IP or an interface name; both are fine for
        # the canonical form since we expose both fields.
        route = CanonicalStaticRoute(
            destination=dest,
            gateway=gateway,
            description=kv.get("comment", ""),
        )
        intent.static_routes.append(route)


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _is_ethernet_name(name: str) -> bool:
    """Does this name look like a MikroTik default ethernet port?"""
    return bool(re.match(r"^ether\d", name, re.IGNORECASE))


def _is_vlan_name(name: str) -> bool:
    """Does this name look like a VLAN interface?"""
    return bool(re.match(r"^vlan\d", name, re.IGNORECASE))


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


def _yes_no(flag: bool) -> str:
    return "yes" if flag else "no"


def _escape(value: str) -> str:
    """Escape double-quotes in a string for inclusion in ``"..."``."""
    return value.replace('"', '\\"')


def _sort_interfaces(
    ifaces: Iterable[CanonicalInterface],
) -> list[CanonicalInterface]:
    """Deterministic interface ordering for reproducible output.

    Ethernet ports first (natural-sort by numeric suffix), then bridges,
    then VLAN interfaces, then everything else.
    """
    def sort_key(iface: CanonicalInterface) -> tuple[int, int, str]:
        name = iface.name
        if _is_ethernet_name(name):
            m = re.match(r"^ether(\d+)", name, re.IGNORECASE)
            return (0, int(m.group(1)) if m else 0, name)
        if name.startswith("bridge"):
            return (1, 0, name)
        if _is_vlan_name(name):
            m = re.match(r"^vlan(\d+)", name, re.IGNORECASE)
            return (2, int(m.group(1)) if m else 0, name)
        return (3, 0, name)
    return sorted(ifaces, key=sort_key)
