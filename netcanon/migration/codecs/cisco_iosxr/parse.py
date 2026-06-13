"""
Parse path for Cisco IOS-XR (``show running-config`` form).

Public function: :func:`parse_intent` — raw text in,
:class:`CanonicalIntent` out.  Targets the ASR 9000 / NCS 5500 / 540 /
8000 series on IOS-XR 6.x / 7.x.

Note: probe lives in :mod:`.codec`; this module assumes input has
already been classified as Cisco IOS-XR CLI.

Phase 1 surface (see ``docs/v0.2.0-planning/04-iosxr-codec/``):

* ``hostname <name>`` → :attr:`CanonicalIntent.hostname`.
* ``domain name <fqdn>`` → :attr:`CanonicalIntent.domain`.
* ``interface <name>`` blocks → :class:`CanonicalInterface` carrying
  ``description`` / ``shutdown`` (→ ``enabled=False``) / ``mtu`` /
  ``ipv4 address X Y`` (dotted mask → prefix) / ``ipv6 address X/N``
  (CIDR).  Five name families: 4-segment physical
  (``GigabitEthernet0/0/0/0`` and speed variants), ``Loopback<n>``,
  ``MgmtEth0/RP0/CPU0/<p>``, ``Bundle-Ether<n>``, and ``<parent>.<unit>``
  sub-interfaces.
* ``router static / address-family ipv4 unicast / <CIDR> <next-hop>+``
  (default VRF) → :class:`CanonicalStaticRoute`.

Where IOS-XR diverges from ``cisco_iosxe_cli`` (see
``02-codec-architecture.md`` § "Parse strategy"):

* Stanzas are terminated by a ``!`` line (and close defensively on a
  shallower-indent line); indentation nests 3-4 deep, not 1-2.
* IPv4 addresses use ``ipv4 address X Y`` (note the ``ipv4`` keyword,
  not IOS-XE's ``ip address``); the mask is dotted-decimal.
* Static routes live in a ``router static`` block with CIDR-form
  destinations, not top-level ``ip route X Y Z`` lines.

Deliberately NOT parsed in Phase 1 (declared ``unsupported`` in the
capability matrix — they land in later phases): the top-level ``vrf``
stanza + route-target sub-blocks, per-interface ``vrf <name>``
membership, RD harvested from ``router bgp``, ``Bundle-Ether``
membership (``bundle id``), local users, per-VRF static routes,
``encapsulation dot1q`` → VLAN synthesis, and the SP-routing /
route-policy Tier-3 stanzas (the latter surfaced via
``dropped_tier3_sections``).
"""

from __future__ import annotations

import ipaddress
import logging
import re

from ...canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalStaticRoute,
)
from .._input_shape import detect_input_shape
from ..base import ParseError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex constants — module-level so they compile once per import.
# ---------------------------------------------------------------------------

_HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)", re.IGNORECASE | re.MULTILINE)
#: ``domain name example.com`` — XR form (IOS-XE prefixes it with ``ip``).
_DOMAIN_RE = re.compile(
    r"^domain\s+name\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)

_IFACE_RE = re.compile(r"^interface\s+(\S+)", re.IGNORECASE)
_DESC_RE = re.compile(r"^\s+description\s+(.+)", re.IGNORECASE)
_SHUTDOWN_RE = re.compile(r"^\s+shutdown\s*$", re.IGNORECASE)
_MTU_RE = re.compile(r"^\s+mtu\s+(\d+)\s*$", re.IGNORECASE)
#: ``ipv4 address 198.51.100.1 255.255.255.252 [secondary]`` — dotted
#: mask, NOT CIDR.  Mirrors IOS-XE's ``ip address`` shape but with the
#: ``ipv4`` keyword.
_IPV4_RE = re.compile(
    r"^\s+ipv4\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)"
    r"(?:\s+(secondary))?",
    re.IGNORECASE,
)
#: ``ipv6 address 2001:db8::1/64 [link-local]`` — CIDR form.
_IPV6_RE = re.compile(
    r"^\s+ipv6\s+address\s+(\S+?)/(\d+)(?:\s+(link-local))?\s*$",
    re.IGNORECASE,
)
#: ``router static`` opens the static-route block (Phase 1: default-VRF
#: address-family only).
_ROUTER_STATIC_RE = re.compile(r"^router\s+static\s*$", re.IGNORECASE)
_AF_IPV4_UNICAST_RE = re.compile(
    r"^address-family\s+ipv4\s+unicast\b", re.IGNORECASE,
)
_STATIC_VRF_RE = re.compile(r"^vrf\s+\S+", re.IGNORECASE)
#: A static-route leaf: ``<dest>/<prefix> <token>...`` (CIDR destination).
_STATIC_LEAF_RE = re.compile(
    r"^(\d+\.\d+\.\d+\.\d+/\d+)\s+(.+)$",
)

#: Interface-name prefix → IANA ifType hint.
_TYPE_HINTS: tuple[tuple[str, str], ...] = (
    ("bundle-ether", "ianaift:ieee8023adLag"),
    ("loopback", "ianaift:softwareLoopback"),
    ("mgmteth", "ianaift:ethernetCsmacd"),
    ("tunnel-ip", "ianaift:tunnel"),
    ("tunnel-te", "ianaift:tunnel"),
    ("fastethernet", "ianaift:ethernetCsmacd"),
    ("gigabitethernet", "ianaift:ethernetCsmacd"),
    ("tengige", "ianaift:ethernetCsmacd"),
    ("twentyfivegige", "ianaift:ethernetCsmacd"),
    ("fortygige", "ianaift:ethernetCsmacd"),
    ("hundredgige", "ianaift:ethernetCsmacd"),
    ("twohundredgige", "ianaift:ethernetCsmacd"),
    ("fourhundredgige", "ianaift:ethernetCsmacd"),
)


def _infer_type(iface_name: str) -> str:
    """Best-effort IANA ifType from the IOS-XR interface-name prefix."""
    lower = iface_name.lower()
    for prefix, iftype in _TYPE_HINTS:
        if lower.startswith(prefix):
            return iftype
    return "ianaift:other"


def _is_link_local_v6(addr: str) -> bool:
    """Return True iff *addr* is in the IPv6 link-local prefix fe80::/10.

    Forked from ``cisco_iosxe_cli.parse._is_link_local_v6`` — the prefix
    is vendor-neutral (RFC 4291 §2.4), so scope can be recovered even
    when the operator omits the ``link-local`` keyword.
    """
    if not addr:
        return False
    lo = addr.lower()
    return len(lo) >= 3 and lo[:2] == "fe" and lo[2] in ("8", "9", "a", "b")


def _mask_to_prefix(mask_str: str) -> int:
    """Convert a dotted-decimal subnet mask to a CIDR prefix length.

    Forked from ``cisco_iosxe_cli.parse._mask_to_prefix`` (per the
    architecture doc's "duplicate rather than lift" guidance — the
    helper is small and parse-only).  Raises :class:`ParseError` for a
    non-contiguous mask.
    """
    try:
        addr = ipaddress.IPv4Address(mask_str)
    except ipaddress.AddressValueError:
        raise ParseError(
            f"cisco_iosxr: invalid subnet mask {mask_str!r}",
            snippet=mask_str,
        )
    bits = bin(int(addr))[2:].zfill(32)
    if "01" in bits:
        raise ParseError(
            f"cisco_iosxr: non-contiguous subnet mask {mask_str!r}",
            snippet=mask_str,
        )
    return bits.count("1")


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse IOS-XR ``show running-config`` output into a
    :class:`CanonicalIntent`.

    Raises:
        ParseError: If the input is empty or looks like XML / JSON
            rather than IOS-XR CLI text.
    """
    if not raw.strip():
        raise ParseError("cisco_iosxr: empty input", snippet="")

    shape = detect_input_shape(raw)
    if shape is not None:
        raise ParseError(
            f"cisco_iosxr: input looks like {shape.upper()}, not IOS-XR "
            f"CLI.  Paste the output of `show running-config`.",
            snippet=raw.lstrip()[:120],
        )

    intent = CanonicalIntent(
        source_vendor="cisco_iosxr",
        source_format="cli-iosxr",
    )

    intent.hostname = _extract_hostname(raw)
    intent.domain = _extract_domain(raw)
    intent.source_version = _extract_version(raw)

    intent.interfaces = _parse_interfaces(raw)
    intent.static_routes = _parse_router_static(raw)

    logger.debug(
        "cisco_iosxr parsed: hostname=%r ifaces=%d routes=%d (input=%d chars)",
        intent.hostname,
        len(intent.interfaces),
        len(intent.static_routes),
        len(raw),
    )
    return intent


def _extract_hostname(raw: str) -> str:
    m = _HOSTNAME_RE.search(raw)
    return m.group(1) if m else ""


def _extract_domain(raw: str) -> str:
    m = _DOMAIN_RE.search(raw)
    return m.group(1) if m else ""


def _extract_version(raw: str) -> str:
    """Return the XR release from the ``!! IOS XR Configuration`` banner.

    Stored as :attr:`CanonicalIntent.source_version` (metadata); the
    render path synthesises a fresh banner so it is informational only.
    """
    m = re.search(
        r"^!!\s+IOS XR Configuration\s+(\S+)", raw, re.MULTILINE,
    )
    return m.group(1) if m else ""


def _new_iface_scratch(name: str) -> dict:
    """Fresh per-interface parse-time scratch dict."""
    return {
        "name": name,
        "description": "",
        "enabled": True,
        "type": _infer_type(name),
        "mtu": None,
        "ipv4": [],
        "ipv6": [],
    }


def _parse_interfaces(raw: str) -> list[CanonicalInterface]:
    """Extract ``interface <name>`` stanzas from IOS-XR config text.

    Per interface: description, enabled (``shutdown``), mtu, IPv4 (dotted
    mask → prefix), IPv6 (CIDR + scope).  Stanzas close on a ``!`` line
    or a shallower-indent (non-indented) line.  ``vrf <name>`` membership
    + ``bundle id`` LAG membership are Phase 2 — parse-and-ignore here.
    """
    interfaces: list[CanonicalInterface] = []
    current: dict | None = None

    def _flush() -> None:
        if current is not None:
            interfaces.append(_build_canonical_interface(current))

    for line in raw.splitlines():
        m = _IFACE_RE.match(line)
        if m:
            _flush()
            current = _new_iface_scratch(m.group(1))
            continue

        if current is None:
            continue

        # `!` terminator or any non-indented line closes the stanza.
        if line.strip() == "!" or (line and not line[0].isspace()):
            _flush()
            current = None
            continue

        dm = _DESC_RE.match(line)
        if dm:
            current["description"] = dm.group(1).strip()
            continue
        if _SHUTDOWN_RE.match(line):
            current["enabled"] = False
            continue
        mm = _MTU_RE.match(line)
        if mm:
            try:
                current["mtu"] = int(mm.group(1))
            except ValueError:
                pass
            continue
        im = _IPV4_RE.match(line)
        if im:
            try:
                current["ipv4"].append({
                    "ip": im.group(1),
                    "prefix_length": _mask_to_prefix(im.group(2)),
                    "is_secondary": im.group(3) is not None,
                })
            except ParseError:
                pass
            continue
        v6m = _IPV6_RE.match(line)
        if v6m:
            addr = v6m.group(1)
            keyword_ll = v6m.group(3)
            try:
                scope = (
                    "link-local"
                    if (keyword_ll or _is_link_local_v6(addr))
                    else "global"
                )
                current["ipv6"].append({
                    "ip": addr,
                    "prefix_length": int(v6m.group(2)),
                    "scope": scope,
                })
            except ValueError:
                pass
            continue

    _flush()
    return interfaces


def _build_canonical_interface(raw: dict) -> CanonicalInterface:
    """Convert the parse-time scratch dict into a CanonicalInterface."""
    return CanonicalInterface(
        name=raw["name"],
        description=raw.get("description", ""),
        enabled=raw.get("enabled", True),
        interface_type=raw.get("type", ""),
        mtu=raw.get("mtu"),
        ipv4_addresses=[
            CanonicalIPv4Address(
                ip=a["ip"],
                prefix_length=a["prefix_length"],
                is_secondary=a.get("is_secondary", False),
            )
            for a in raw.get("ipv4", [])
        ],
        ipv6_addresses=[
            CanonicalIPv6Address(
                ip=a["ip"],
                prefix_length=a["prefix_length"],
                scope=a.get("scope", "global"),
            )
            for a in raw.get("ipv6", [])
        ],
    )


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _parse_static_leaf(text: str) -> CanonicalStaticRoute | None:
    """Parse one ``<CIDR> <next-hop>...`` static-route leaf line.

    The next-hop tokens are a mix of an egress interface and/or a
    gateway IP (``10.0.0.0/8 GigabitEthernet0/0/0/2 11.1.1.2`` carries
    both; ``11.0.0.0/8 Null0`` carries only an interface;
    ``0.0.0.0/0 1.2.3.4`` only a gateway).  An IPv4-parseable token is
    the gateway; the first non-IP token is the egress interface.
    """
    m = _STATIC_LEAF_RE.match(text)
    if not m:
        return None
    dest = m.group(1)
    gateway = ""
    iface = ""
    for tok in m.group(2).split():
        try:
            ipaddress.IPv4Address(tok)
            gateway = tok
        except ipaddress.AddressValueError:
            if not iface:
                iface = tok
    return CanonicalStaticRoute(
        destination=dest, gateway=gateway, interface=iface,
    )


def _parse_router_static(raw: str) -> list[CanonicalStaticRoute]:
    """Extract default-VRF routes from the ``router static`` block.

    Phase 1 harvests only the top-level ``address-family ipv4 unicast``
    routes; ``vrf <name>`` sub-blocks (per-VRF static) are skipped and
    land in Phase 2 alongside VRF support.  Block-relative indentation
    drives a small state machine — ``ctx`` tracks whether the current
    depth-1 sub-block is the default address-family or a VRF.
    """
    routes: list[CanonicalStaticRoute] = []
    in_block = False
    base_indent = 0
    ctx: str | None = None  # None | "default-af" | "vrf"

    for line in raw.splitlines():
        if not in_block:
            if _ROUTER_STATIC_RE.match(line):
                in_block = True
                base_indent = _indent(line)
                ctx = None
            continue

        stripped = line.strip()
        if not stripped:
            continue
        indent = _indent(line)
        # A non-indented, non-`!` line ends the whole router-static block.
        if indent <= base_indent and stripped != "!":
            in_block = False
            continue

        rel = indent - base_indent
        if rel == 1:
            # depth-1 sub-block header: address-family / vrf / `!`.
            if stripped == "!":
                ctx = None
            elif _AF_IPV4_UNICAST_RE.match(stripped):
                ctx = "default-af"
            elif _STATIC_VRF_RE.match(stripped):
                ctx = "vrf"
            else:
                ctx = None
            continue
        # depth >= 2 route leaves — only the default address-family.
        if ctx == "default-af":
            r = _parse_static_leaf(stripped)
            if r:
                routes.append(r)
    return routes
