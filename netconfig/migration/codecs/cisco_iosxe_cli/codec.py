"""
``CiscoIOSXECLICodec`` — parse ``show running-config`` text.

Direction: ``parse_only``.  No ``render()`` — generating syntactically
valid IOS CLI from a tree is substantially harder than parsing it and
is deferred to a future phase.

Parser strategy
---------------
IOS ``show running-config`` is a line-oriented, indentation-significant
format.  Interfaces are delimited by ``interface <name>`` lines and
terminated by ``!`` comment lines.  The parser:

1. Scans for ``interface <name>`` lines.
2. Captures indented sub-commands until the next ``!`` or un-indented
   line.
3. Extracts known keywords: ``description``, ``shutdown`` / ``no
   shutdown``, ``ip address <ip> <mask>``.
4. Builds the same nested dict shape as ``CiscoIOSXECodec`` so the
   two codecs are interchangeable as pipeline SOURCEs.

Limitations (``experimental`` certainty):
    * Only parses interface stanzas — routing protocols, ACLs, VLANs,
      AAA, crypto, and everything else is silently skipped.
    * Subnet mask → prefix-length conversion handles standard masks
      only (``255.255.255.0`` → ``/24``).  Non-contiguous masks are
      rejected.
    * ``secondary`` IP addresses are ignored (first address only).
    * ``switchport`` interfaces are treated as having no IP.
"""

from __future__ import annotations

import ipaddress
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
    CanonicalStaticRoute,
    CanonicalVlan,
)
from ..base import CodecBase, ParseError, RenderError
from ..registry import register


@register
class CiscoIOSXECLICodec(CodecBase):
    """Parse-only codec for Cisco IOS-XE ``show running-config`` output.

    Shares ``vendor_id=cisco_iosxe`` with the NETCONF codec — both
    target the same vendor YAML.
    """

    name: ClassVar[str] = "cisco_iosxe_cli"
    version_hint: ClassVar[str | None] = "15.x / 16.x / 17.x"
    input_format: ClassVar[str] = "cli-ios"
    direction: ClassVar[str] = "parse_only"
    certainty: ClassVar[str] = "experimental"
    canonical_model: ClassVar[str] = "openconfig-lite"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="cisco_iosxe_cli",
        vendor_id="cisco_iosxe",
        version_range="15.x+",
        device_classes=[DeviceClass.router, DeviceClass.switch],
        supported=[
            "/interfaces/interface/name",
            "/interfaces/interface/config/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/subinterfaces/subinterface/index",
            "/interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/ip",
            "/interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/config/ip",
            "/interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/config/prefix-length",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "CLI parser infers interface type from the name prefix "
                    "(GigabitEthernet → ethernetCsmacd, Loopback → "
                    "softwareLoopback) but cannot detect all IANA types."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/interfaces/interface/subinterfaces/subinterface/ipv6",
                reason="Phase 0.5 scope — IPv4 only.",
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
        """Parse IOS-XE ``show running-config`` output into a
        :class:`CanonicalIntent`.

        Raises:
            ParseError: If the input doesn't look like IOS config at all
                (e.g. XML or JSON).
        """
        if not raw.strip():
            raise ParseError(
                "cisco_iosxe_cli: empty input",
                snippet="",
            )
        # Quick sanity: if it starts with '<' it's XML, not CLI.
        stripped = raw.lstrip()
        if stripped.startswith("<") or stripped.startswith("{"):
            raise ParseError(
                "cisco_iosxe_cli: input looks like XML or JSON, not IOS CLI. "
                "Use the cisco_iosxe (NETCONF) codec for XML input.",
                snippet=stripped[:120],
            )

        intent = CanonicalIntent(
            source_vendor="cisco_iosxe",
            source_format="cli-ios",
        )

        # System-level fields
        intent.hostname = _extract_hostname(raw)

        # Interfaces
        intent.interfaces = _parse_interfaces(raw)

        # VLANs
        intent.vlans = _parse_vlans(raw)

        # Static routes
        intent.static_routes = _parse_static_routes(raw)

        return intent

    # -----------------------------------------------------------------
    # Render — NOT IMPLEMENTED (parse_only codec)
    # -----------------------------------------------------------------

    def render(self, tree: Any) -> str:
        """Not implemented — this codec is parse-only.

        Raises:
            RenderError: Always.
        """
        raise RenderError(
            "cisco_iosxe_cli is a parse-only codec; rendering IOS CLI "
            "from a tree is not yet implemented. Use cisco_iosxe "
            "(NETCONF) as the TARGET codec instead.",
            yang_path="/",
        )

    # -----------------------------------------------------------------
    # iter_xpaths — same shape as the NETCONF codec
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        """Yield schema xpaths from a :class:`CanonicalIntent`."""
        if isinstance(tree, CanonicalIntent):
            yield from _walk_canonical(tree)
        elif isinstance(tree, dict):
            # Back-compat fallback for old-shape trees.
            from ..cisco_iosxe.codec import _walk
            yield from _walk(tree, "")


# ---------------------------------------------------------------------------
# CLI parser internals
# ---------------------------------------------------------------------------

_IFACE_RE = re.compile(r"^interface\s+(\S+)", re.IGNORECASE)
_DESC_RE = re.compile(r"^\s+description\s+(.+)", re.IGNORECASE)
_IP_RE = re.compile(
    r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
_SHUTDOWN_RE = re.compile(r"^\s+shutdown\s*$", re.IGNORECASE)
_NO_SHUTDOWN_RE = re.compile(r"^\s+no\s+shutdown\s*$", re.IGNORECASE)

#: Interface-name prefix → IANA ifType hint.
_TYPE_HINTS: dict[str, str] = {
    "gigabitethernet": "ianaift:ethernetCsmacd",
    "fastethernet": "ianaift:ethernetCsmacd",
    "tengigabitethernet": "ianaift:ethernetCsmacd",
    "twentyfivegige": "ianaift:ethernetCsmacd",
    "fortygigabitethernet": "ianaift:ethernetCsmacd",
    "hundredgige": "ianaift:ethernetCsmacd",
    "ethernet": "ianaift:ethernetCsmacd",
    "loopback": "ianaift:softwareLoopback",
    "vlan": "ianaift:l3ipvlan",
    "port-channel": "ianaift:ieee8023adLag",
    "tunnel": "ianaift:tunnel",
    "bdi": "ianaift:l3ipvlan",
}


def _infer_type(iface_name: str) -> str:
    """Best-effort IANA ifType from the interface name prefix."""
    lower = iface_name.lower()
    for prefix, iftype in _TYPE_HINTS.items():
        if lower.startswith(prefix):
            return iftype
    return "ianaift:other"


def _mask_to_prefix(mask_str: str) -> int:
    """Convert a dotted-decimal subnet mask to a CIDR prefix length.

    Raises ParseError for non-contiguous masks.
    """
    try:
        addr = ipaddress.IPv4Address(mask_str)
    except ipaddress.AddressValueError:
        raise ParseError(
            f"cisco_iosxe_cli: invalid subnet mask {mask_str!r}",
            snippet=mask_str,
        )
    bits = bin(int(addr))[2:]
    if "01" in bits:
        raise ParseError(
            f"cisco_iosxe_cli: non-contiguous subnet mask {mask_str!r}",
            snippet=mask_str,
        )
    return bits.count("1")


_HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)", re.IGNORECASE | re.MULTILINE)
_VLAN_RE = re.compile(r"^vlan\s+(\d+)", re.IGNORECASE)
_VLAN_NAME_RE = re.compile(r"^\s+name\s+(.+)", re.IGNORECASE)
_STATIC_ROUTE_RE = re.compile(
    r"^ip\s+route\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)",
    re.IGNORECASE,
)
_SWITCHPORT_ACCESS_RE = re.compile(
    r"^\s+switchport\s+access\s+vlan\s+(\d+)", re.IGNORECASE
)
_SWITCHPORT_TRUNK_ALLOWED_RE = re.compile(
    r"^\s+switchport\s+trunk\s+allowed\s+vlan\s+(.+)", re.IGNORECASE
)
_SWITCHPORT_TRUNK_NATIVE_RE = re.compile(
    r"^\s+switchport\s+trunk\s+native\s+vlan\s+(\d+)", re.IGNORECASE
)
_SWITCHPORT_MODE_RE = re.compile(
    r"^\s+switchport\s+mode\s+(\S+)", re.IGNORECASE
)


def _extract_hostname(raw: str) -> str:
    m = _HOSTNAME_RE.search(raw)
    return m.group(1) if m else ""


def _parse_interfaces(raw: str) -> list[CanonicalInterface]:
    """Extract interface stanzas from IOS config text."""
    lines = raw.splitlines()
    interfaces: list[CanonicalInterface] = []
    current: dict[str, Any] | None = None

    for line in lines:
        m = _IFACE_RE.match(line)
        if m:
            if current is not None:
                interfaces.append(_build_canonical_interface(current))
            iface_name = m.group(1)
            current = {
                "name": iface_name,
                "description": "",
                "enabled": True,
                "type": _infer_type(iface_name),
                "ipv4": [],
                "switchport_mode": None,
                "access_vlan": None,
                "trunk_allowed": [],
                "trunk_native": None,
            }
            continue

        if current is None:
            continue

        if line.startswith("!") or (line and not line[0].isspace()):
            interfaces.append(_build_canonical_interface(current))
            current = None
            continue

        dm = _DESC_RE.match(line)
        if dm:
            current["description"] = dm.group(1).strip()
            continue

        if _SHUTDOWN_RE.match(line):
            current["enabled"] = False
            continue

        if _NO_SHUTDOWN_RE.match(line):
            current["enabled"] = True
            continue

        im = _IP_RE.match(line)
        if im:
            ip_str = im.group(1)
            mask_str = im.group(2)
            prefix_len = _mask_to_prefix(mask_str)
            if not current["ipv4"]:  # primary only
                current["ipv4"].append({"ip": ip_str, "prefix_length": prefix_len})
            continue

        sm = _SWITCHPORT_MODE_RE.match(line)
        if sm:
            current["switchport_mode"] = sm.group(1).lower()
            continue

        am = _SWITCHPORT_ACCESS_RE.match(line)
        if am:
            current["access_vlan"] = int(am.group(1))
            continue

        tm = _SWITCHPORT_TRUNK_ALLOWED_RE.match(line)
        if tm:
            current["trunk_allowed"] = _parse_vlan_list(tm.group(1).strip())
            continue

        nm = _SWITCHPORT_TRUNK_NATIVE_RE.match(line)
        if nm:
            current["trunk_native"] = int(nm.group(1))
            continue

    if current is not None:
        interfaces.append(_build_canonical_interface(current))

    return interfaces


def _build_canonical_interface(raw: dict[str, Any]) -> CanonicalInterface:
    """Convert the parse-time dict into a CanonicalInterface."""
    return CanonicalInterface(
        name=raw["name"],
        description=raw.get("description", ""),
        enabled=raw.get("enabled", True),
        interface_type=raw.get("type", ""),
        ipv4_addresses=[
            CanonicalIPv4Address(ip=a["ip"], prefix_length=a["prefix_length"])
            for a in raw.get("ipv4", [])
        ],
        switchport_mode=raw.get("switchport_mode"),
        access_vlan=raw.get("access_vlan"),
        trunk_allowed_vlans=raw.get("trunk_allowed", []),
        trunk_native_vlan=raw.get("trunk_native"),
    )


def _parse_vlan_list(text: str) -> list[int]:
    """Parse a Cisco VLAN list like '10,20,30-40' into a flat list of ints."""
    result: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            result.extend(range(int(lo.strip()), int(hi.strip()) + 1))
        elif part.isdigit():
            result.append(int(part))
    return result


def _parse_vlans(raw: str) -> list[CanonicalVlan]:
    """Extract VLAN definitions from IOS config text.

    Looks for ``vlan <id>`` stanzas followed by indented ``name``
    sub-commands.
    """
    lines = raw.splitlines()
    vlans: list[CanonicalVlan] = []
    current_id: int | None = None
    current_name: str = ""

    for line in lines:
        vm = _VLAN_RE.match(line)
        if vm:
            if current_id is not None:
                vlans.append(CanonicalVlan(id=current_id, name=current_name))
            current_id = int(vm.group(1))
            current_name = ""
            continue

        if current_id is not None:
            nm = _VLAN_NAME_RE.match(line)
            if nm:
                current_name = nm.group(1).strip()
                continue
            if line.startswith("!") or (line and not line[0].isspace()):
                vlans.append(CanonicalVlan(id=current_id, name=current_name))
                current_id = None
                current_name = ""

    if current_id is not None:
        vlans.append(CanonicalVlan(id=current_id, name=current_name))

    return vlans


def _parse_static_routes(raw: str) -> list[CanonicalStaticRoute]:
    """Extract ``ip route`` lines from IOS config text."""
    routes: list[CanonicalStaticRoute] = []
    for line in raw.splitlines():
        m = _STATIC_ROUTE_RE.match(line)
        if m:
            dest_ip = m.group(1)
            mask = m.group(2)
            gw_or_iface = m.group(3)
            prefix_len = _mask_to_prefix(mask)
            dest = f"{dest_ip}/{prefix_len}"
            # Gateway could be an IP or an interface name.
            gateway = ""
            iface = ""
            try:
                ipaddress.IPv4Address(gw_or_iface)
                gateway = gw_or_iface
            except ipaddress.AddressValueError:
                iface = gw_or_iface
            routes.append(CanonicalStaticRoute(
                destination=dest,
                gateway=gateway,
                interface=iface,
            ))
    return routes


def _walk_canonical(intent: CanonicalIntent) -> Iterable[str]:
    """Yield schema xpaths from a CanonicalIntent for validation."""
    if intent.hostname:
        yield "/system/hostname"
    for _ in intent.dns_servers:
        yield "/system/dns-server"
    for _ in intent.ntp_servers:
        yield "/system/ntp-server"
    for iface in intent.interfaces:
        yield "/interfaces/interface/name"
        if iface.description:
            yield "/interfaces/interface/config/description"
        yield "/interfaces/interface/config/enabled"
        if iface.interface_type:
            yield "/interfaces/interface/config/type"
        for _ in iface.ipv4_addresses:
            yield "/interfaces/interface/ipv4/address/ip"
            yield "/interfaces/interface/ipv4/address/prefix-length"
    for _ in intent.vlans:
        yield "/vlans/vlan/id"
        yield "/vlans/vlan/name"
    for _ in intent.static_routes:
        yield "/routing/static-route"
