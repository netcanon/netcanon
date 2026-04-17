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

    def parse(self, raw: str) -> dict[str, Any]:
        """Parse IOS-XE ``show running-config`` output.

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

        interfaces = _parse_interfaces(raw)
        return {"interfaces": {"interface": interfaces}}

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
        """Yield schema xpaths — delegates to the NETCONF codec's walker
        since the tree shapes are identical."""
        from ..cisco_iosxe.codec import _walk
        if not isinstance(tree, dict):
            return
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


def _parse_interfaces(raw: str) -> list[dict[str, Any]]:
    """Extract interface stanzas from IOS config text."""
    lines = raw.splitlines()
    interfaces: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in lines:
        # Start of a new interface stanza?
        m = _IFACE_RE.match(line)
        if m:
            if current is not None:
                interfaces.append(current)
            iface_name = m.group(1)
            current = {
                "name": iface_name,
                "config": {
                    "name": iface_name,
                    "enabled": True,  # default; overridden by `shutdown`
                    "type": _infer_type(iface_name),
                },
            }
            continue

        # Are we inside an interface stanza?
        if current is None:
            continue

        # End of stanza?
        if line.startswith("!") or (line and not line[0].isspace()):
            interfaces.append(current)
            current = None
            continue

        # Sub-commands within the stanza.
        dm = _DESC_RE.match(line)
        if dm:
            current["config"]["description"] = dm.group(1).strip()
            continue

        if _SHUTDOWN_RE.match(line):
            current["config"]["enabled"] = False
            continue

        if _NO_SHUTDOWN_RE.match(line):
            current["config"]["enabled"] = True
            continue

        im = _IP_RE.match(line)
        if im:
            ip_str = im.group(1)
            mask_str = im.group(2)
            prefix_len = _mask_to_prefix(mask_str)
            current.setdefault("subinterfaces", {
                "subinterface": [{
                    "index": 0,
                    "ipv4": {
                        "addresses": {
                            "address": []
                        }
                    },
                }]
            })
            addr_list = (
                current["subinterfaces"]["subinterface"][0]
                ["ipv4"]["addresses"]["address"]
            )
            # Only take the first (primary) address.
            if not addr_list:
                addr_list.append({
                    "ip": ip_str,
                    "config": {
                        "ip": ip_str,
                        "prefix-length": prefix_len,
                    },
                })

    # Don't forget the last stanza if there's no trailing '!'.
    if current is not None:
        interfaces.append(current)

    return interfaces
