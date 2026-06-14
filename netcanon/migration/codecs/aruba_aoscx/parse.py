"""
Parse path for Aruba AOS-CX (``show running-config`` form).

Public function: :func:`parse_intent` — raw text in,
:class:`CanonicalIntent` out.  Targets the AOS-CX switch portfolio
(6000 / 6100 / 6200 / 6300 / 6400 / 8100 / 8320 / 8325 / 8360 / 8400 /
9300 / CX-10000) on AOS-CX 10.x.

Note: probe is in :mod:`.codec`; this module assumes input has already
been classified as Aruba AOS-CX CLI text.

Phase 1 surface (Tier-1, mirrors the ``cisco_nxos`` Phase 1 scope):

* ``hostname <name>`` → :attr:`CanonicalIntent.hostname`.
* ``!Version ArubaOS-CX <ver>`` → :attr:`CanonicalIntent.source_version`
  (metadata only; the banner is synthesised on render).
* ``vlan <id>`` stanzas (one id per line) + nested ``name`` / ``description``
  → :class:`CanonicalVlan`, plus SVI synthesis from ``interface vlan N``.
* ``vrf <name>`` (top-level) → :class:`CanonicalRoutingInstance` (name
  only in Phase 1).
* ``interface <name>`` blocks → :class:`CanonicalInterface` carrying
  ``description`` / admin-state (``no shutdown`` / ``shutdown``) / ``mtu``
  / ``ip address X/N`` (CIDR) / ``ipv6 address X/N`` / ``vrf attach <name>``.
* top-level ``ip route <dest>/<prefix> <gw> [<dist>]`` (default VRF only)
  → :class:`CanonicalStaticRoute`.

Where this codec diverges from ``cisco_nxos`` (its closest template) —
see ``docs/fixture-research-2015/11-aruba_aoscx.md``:

* **Interface names are multi-token**: ``interface 1/1/1`` (member /
  slot / port triple), ``interface vlan 11``, ``interface lag 1``,
  ``interface loopback 0``, ``interface mgmt``.  The canonical ``name``
  carries the space; :mod:`.port_names` splits it back.
* **Default admin-state is DOWN** for physical / SVI / mgmt ports
  (active ports carry an explicit ``no shutdown``); loopbacks are up by
  default.  The scratch default is therefore type-aware.
* VRF stanza keyword is bare ``vrf <name>`` (not ``vrf context``);
  per-interface bind is ``vrf attach <name>`` (not ``vrf member`` /
  ``vrf forwarding``).
* L2 ports declare ``no routing`` + ``vlan access`` / ``vlan trunk``;
  L3 ports carry a bare ``ip address`` (routing is implicit).  Phase 1
  parses the L3 addressing and defers the L2 switchport surface to a
  later phase.

Deferred to later phases (parse-and-ignore in v1): L2 switchport
(``no routing`` / ``vlan access`` / ``vlan trunk``), LAG membership
(``interface lag`` + per-port ``lag N``), local users
(``user ... password ciphertext``), the ``active-gateway`` anycast
surface, VSX, VXLAN / EVPN (``interface vxlan`` / ``evpn``), and the
Tier-3 protocol / ACL / QoS blocks.  Those lines fall through the parser
silently; the matrix declares each ``unsupported``.
"""

from __future__ import annotations

import ipaddress
import logging
import re

from ...canonical.intent import (
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalRoutingInstance,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from .._input_shape import detect_input_shape
from ..base import ParseError
from . import port_names as _port_names

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex constants — module-level so they compile once per import.
# ---------------------------------------------------------------------------

_HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)", re.IGNORECASE | re.MULTILINE)
#: ``!Version ArubaOS-CX FL.10.13.1000`` — the platform-family-prefixed
#: release string after the ``ArubaOS-CX`` marker.
_VERSION_RE = re.compile(
    r"^!Version\s+ArubaOS-CX\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)

#: ``interface <name>`` — captures the type token plus an OPTIONAL
#: space-separated numeric index, so ``interface vlan 11`` -> ``vlan 11``,
#: ``interface lag 1 multi-chassis`` -> ``lag 1`` (modifier dropped), and
#: ``interface 1/1/1`` -> ``1/1/1`` (the triple is one ``\S+`` token).
_IFACE_RE = re.compile(r"^interface\s+(\S+)(?:\s+(\d+))?\b", re.IGNORECASE)
_DESC_RE = re.compile(r"^\s+description\s+(.+)", re.IGNORECASE)
_SHUTDOWN_RE = re.compile(r"^\s+shutdown\s*$", re.IGNORECASE)
_NO_SHUTDOWN_RE = re.compile(r"^\s+no\s+shutdown\s*$", re.IGNORECASE)
#: ``mtu 9198`` — the L2 frame MTU.  The separate ``ip mtu`` line (L3
#: MTU) is parse-and-ignore in Phase 1.
_MTU_RE = re.compile(r"^\s+mtu\s+(\d+)\s*$", re.IGNORECASE)
#: ``ip address 10.0.0.1/24`` — CIDR form, never dotted mask.  The mgmt
#: port's ``ip static`` / ``ip dhcp`` forms are deferred (not this regex).
_IP_CIDR_RE = re.compile(
    r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)/(\d+)(?:\s+(secondary))?\s*$",
    re.IGNORECASE,
)
#: ``ipv6 address 2001:db8::1/64`` — CIDR form.  An optional ``link-local``
#: trailer tags scope explicitly; the fe80::/10 prefix infers it otherwise.
_IPV6_CIDR_RE = re.compile(
    r"^\s+ipv6\s+address\s+(\S+?)/(\d+)(?:\s+(link-local))?\s*$",
    re.IGNORECASE,
)
#: ``vrf attach <name>`` inside an interface stanza (AOS-CX form of
#: NX-OS's ``vrf member`` / IOS-XE's ``vrf forwarding``).
_VRF_ATTACH_RE = re.compile(r"^\s+vrf\s+attach\s+(\S+)\s*$", re.IGNORECASE)

#: ``vrf <name>`` opens a top-level VRF declaration (single token, whole
#: line).  Distinct from the interface-level ``vrf attach`` (indented) and
#: from ``ssh server vrf mgmt`` / ``ntp vrf mgmt`` (different leading
#: keyword), so the anchored single-token match is unambiguous.
_VRF_DECL_RE = re.compile(r"^vrf\s+(\S+)\s*$", re.IGNORECASE)

#: ``vlan <id>`` — AOS-CX declares one VLAN id per line (no comma / range
#: list in ``show running-config``).
_VLAN_TOP_RE = re.compile(r"^vlan\s+(\d+)\s*$", re.IGNORECASE)
_VLAN_NAME_RE = re.compile(r"^\s+name\s+(.+)", re.IGNORECASE)
_VLAN_DESC_RE = re.compile(r"^\s+description\s+(.+)", re.IGNORECASE)

#: ``ip route <dest>/<prefix> <gw> [<dist>]`` — top-level (default VRF)
#: static route.  AOS-CX uses CIDR destinations.
_STATIC_ROUTE_RE = re.compile(
    r"^ip\s+route\s+(\d+\.\d+\.\d+\.\d+)/(\d+)\s+(\S+)(?:\s+(\d+))?",
    re.IGNORECASE,
)

#: ``interface vlan <N>`` SVI name (post-capture; the canonical name is
#: the space-separated ``vlan N``).
_SVI_NAME_RE = re.compile(r"^vlan\s+(\d+)$", re.IGNORECASE)

#: PortIdentity kind -> IANA ifType hint.  AOS-CX declares no ifType, so
#: this is inferred from the name shape (declared lossy in the matrix).
_KIND_TO_IFTYPE: dict[str, str] = {
    "physical": "ianaift:ethernetCsmacd",
    "svi": "ianaift:l3ipvlan",
    "lag": "ianaift:ieee8023adLag",
    "loopback": "ianaift:softwareLoopback",
    "mgmt": "ianaift:ethernetCsmacd",
    "vtep": "ianaift:tunnel",
}


def _infer_type(iface_name: str) -> str:
    """Best-effort IANA ifType from the AOS-CX interface-name shape."""
    kind = _port_names.classify_port_name(iface_name).kind
    return _KIND_TO_IFTYPE.get(kind, "ianaift:other")


def _default_enabled(iface_name: str) -> bool:
    """Return the AOS-CX default admin-state for an interface by name.

    Loopbacks come up without an explicit ``no shutdown``; every other
    port type (physical / SVI / mgmt / LAG) is admin-down by default and
    needs an explicit ``no shutdown`` to enable.  An explicit
    ``shutdown`` / ``no shutdown`` line in the stanza overrides this.
    """
    return _port_names.classify_port_name(iface_name).kind == "loopback"


def _is_link_local_v6(addr: str) -> bool:
    """Return True iff *addr* is in the IPv6 link-local prefix fe80::/10.

    Mirrors ``cisco_nxos.parse._is_link_local_v6`` — the prefix is
    vendor-neutral (RFC 4291 §2.4), so scope can be recovered even when
    the operator omits the ``link-local`` keyword.
    """
    if not addr:
        return False
    lo = addr.lower()
    return len(lo) >= 3 and lo[:2] == "fe" and lo[2] in ("8", "9", "a", "b")


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse AOS-CX ``show running-config`` output into a
    :class:`CanonicalIntent`.

    Raises:
        ParseError: If the input is empty or looks like XML / JSON
            rather than AOS-CX CLI text.
    """
    if not raw.strip():
        raise ParseError("aruba_aoscx: empty input", snippet="")

    shape = detect_input_shape(raw)
    if shape is not None:
        raise ParseError(
            f"aruba_aoscx: input looks like {shape.upper()}, not AOS-CX "
            f"CLI.  Paste the output of `show running-config`.",
            snippet=raw.lstrip()[:120],
        )

    intent = CanonicalIntent(
        source_vendor="aruba_aoscx",
        source_format="cli-aoscx",
    )

    intent.hostname = _extract_hostname(raw)
    intent.source_version = _extract_version(raw)

    # VRF declarations (``vrf <name>`` top-level).  Phase 1 harvests the
    # name only; per-interface ``vrf attach`` membership is set by
    # :func:`_parse_interfaces`.
    intent.routing_instances = _parse_routing_instances(raw)

    intent.interfaces = _parse_interfaces(raw)

    intent.vlans = _parse_vlans(raw)
    # Derive VLAN records from ``interface vlan <N>`` SVIs with no matching
    # top-level ``vlan`` stanza (mirrors cisco_nxos) so VLAN-centric
    # downstream codecs don't silently drop the SVI's L3 config.
    _synthesize_vlans_from_svis(intent)

    intent.static_routes = _parse_static_routes(raw)

    logger.debug(
        "aruba_aoscx parsed: hostname=%r ifaces=%d vlans=%d routes=%d "
        "vrfs=%d (input=%d chars)",
        intent.hostname,
        len(intent.interfaces),
        len(intent.vlans),
        len(intent.static_routes),
        len(intent.routing_instances),
        len(raw),
    )
    return intent


def _extract_hostname(raw: str) -> str:
    m = _HOSTNAME_RE.search(raw)
    return m.group(1) if m else ""


def _extract_version(raw: str) -> str:
    """Return the AOS-CX release string from the ``!Version`` banner.

    Stored as :attr:`CanonicalIntent.source_version` (metadata).  The
    render path synthesises a fresh banner rather than echoing this, so
    it is informational only.
    """
    m = _VERSION_RE.search(raw)
    return m.group(1) if m else ""


def _parse_routing_instances(raw: str) -> list[CanonicalRoutingInstance]:
    """Extract top-level ``vrf <name>`` declarations.

    AOS-CX creates a VRF with a bare ``vrf <name>`` line (no nested body
    in the common case — RD / route-target live under the ``evpn`` /
    ``router bgp`` stanzas, which are deferred).  Phase 1 harvests the
    name only.  The built-in ``mgmt`` VRF is created the same way when it
    appears as an explicit declaration; references such as ``ssh server
    vrf mgmt`` do NOT match this anchored single-token pattern.
    """
    instances: list[CanonicalRoutingInstance] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        m = _VRF_DECL_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        instances.append(CanonicalRoutingInstance(name=name))
    return instances


def _new_iface_scratch(name: str) -> dict:
    """Fresh per-interface parse-time scratch dict.

    Single source of truth for the field set so the two stanza-open sites
    in :func:`_parse_interfaces` can't drift apart.  ``enabled`` defaults
    type-aware (loopbacks up, everything else down — see
    :func:`_default_enabled`).
    """
    return {
        "name": name,
        "description": "",
        "enabled": _default_enabled(name),
        "type": _infer_type(name),
        "mtu": None,
        "ipv4": [],
        "ipv6": [],
        "vrf": "",
    }


def _iface_name(m: re.Match) -> str:
    """Reconstruct the canonical interface name from an :data:`_IFACE_RE`
    match: the type token plus the optional space-separated index."""
    base = m.group(1)
    idx = m.group(2)
    return f"{base} {idx}" if idx else base


def _parse_interfaces(raw: str) -> list[CanonicalInterface]:
    """Extract ``interface <name>`` stanzas from AOS-CX config text.

    Per interface: description, admin-state (``no shutdown`` / ``shutdown``
    over the type-aware default), mtu, IPv4 (CIDR), IPv6 (CIDR + scope),
    and VRF membership (``vrf attach``).  ``interface lag`` and
    ``interface vxlan`` stanzas are intercepted and NOT materialised as
    interfaces (LAGs are a later phase; the VTEP is a VXLAN config
    container) — mirrors cisco_nxos's ``interface nve1`` interception.
    """
    lines = raw.splitlines()
    interfaces: list[CanonicalInterface] = []
    current: dict | None = None

    def _flush() -> None:
        if current is not None:
            interfaces.append(_build_canonical_interface(current))

    def _open(m: re.Match) -> dict | None:
        """Return a fresh scratch for an interface header, or None for the
        ``lag`` / ``vxlan`` kinds Phase 1 deliberately skips."""
        name = _iface_name(m)
        low = name.lower()
        if low.startswith("lag ") or low.startswith("vxlan "):
            return None
        return _new_iface_scratch(name)

    for line in lines:
        m = _IFACE_RE.match(line)
        if m:
            _flush()
            current = _open(m)
            continue

        if current is None:
            continue

        # Non-indented line closes the current stanza.
        if line and not line[0].isspace():
            _flush()
            current = None
            m = _IFACE_RE.match(line)
            if m:
                current = _open(m)
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

        mm = _MTU_RE.match(line)
        if mm:
            try:
                current["mtu"] = int(mm.group(1))
            except ValueError:
                pass
            continue

        im = _IP_CIDR_RE.match(line)
        if im:
            try:
                current["ipv4"].append({
                    "ip": im.group(1),
                    "prefix_length": int(im.group(2)),
                    "is_secondary": im.group(3) is not None,
                })
            except ValueError:
                pass
            continue

        v6m = _IPV6_CIDR_RE.match(line)
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

        vm = _VRF_ATTACH_RE.match(line)
        if vm:
            current["vrf"] = vm.group(1)
            continue

        # Any other indented line (no routing / routing / vlan access /
        # vlan trunk / lag N / active-gateway / lacp / ...) is deferred to
        # a later phase — parse-and-ignore.

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
        vrf=raw.get("vrf", ""),
    )


def _parse_vlans(raw: str) -> list[CanonicalVlan]:
    """Extract VLAN definitions from AOS-CX config text.

    AOS-CX declares one VLAN id per line (``vlan 101``) optionally
    followed by indented ``name`` / ``description`` sub-commands.  De-
    duplicated by id, preserving first-seen order.
    """
    vlans_by_id: dict[int, CanonicalVlan] = {}
    order: list[int] = []

    def _touch(vid: int) -> CanonicalVlan:
        v = vlans_by_id.get(vid)
        if v is None:
            v = CanonicalVlan(id=vid, name="")
            vlans_by_id[vid] = v
            order.append(vid)
        return v

    current_id: int | None = None
    for line in raw.splitlines():
        tm = _VLAN_TOP_RE.match(line)
        if tm:
            vid = int(tm.group(1))
            if 1 <= vid <= 4094:
                _touch(vid)
                current_id = vid
            else:
                current_id = None
            continue

        if current_id is not None:
            nm = _VLAN_NAME_RE.match(line)
            if nm:
                _touch(current_id).name = nm.group(1).strip()
                continue
            dm = _VLAN_DESC_RE.match(line)
            if dm:
                _touch(current_id).description = dm.group(1).strip()
                continue
            # Any non-indented line closes the stanza.
            if line and not line[0].isspace():
                current_id = None

    return [vlans_by_id[vid] for vid in order]


def _synthesize_vlans_from_svis(intent: CanonicalIntent) -> None:
    """Derive VLAN records from ``interface vlan <N>`` SVIs.

    Mirrors ``cisco_nxos._synthesize_vlans_from_svis``: an SVI whose VLAN
    has no top-level ``vlan`` stanza still implies the VLAN exists (and
    carries its L3 config), so create / merge a record.
    """
    existing_by_id: dict[int, CanonicalVlan] = {v.id: v for v in intent.vlans}
    for iface in intent.interfaces:
        m = _SVI_NAME_RE.match(iface.name)
        if not m:
            continue
        vid = int(m.group(1))
        if not (1 <= vid <= 4094):
            continue
        existing = existing_by_id.get(vid)
        if existing is None:
            synthesised = CanonicalVlan(
                id=vid,
                name=iface.description,
                ipv4_addresses=list(iface.ipv4_addresses),
            )
            intent.vlans.append(synthesised)
            existing_by_id[vid] = synthesised
            continue
        for addr in iface.ipv4_addresses:
            if addr not in existing.ipv4_addresses:
                existing.ipv4_addresses.append(addr)


def _parse_static_routes(raw: str) -> list[CanonicalStaticRoute]:
    """Extract top-level ``ip route`` lines (default VRF) from AOS-CX text.

    AOS-CX form: ``ip route <dest>/<prefix> <gw> [<dist>]``.  The trailing
    integer (if present) is the administrative distance and maps to
    :attr:`CanonicalStaticRoute.metric`.  A next-hop that parses as an
    IPv4 address becomes ``gateway``; otherwise it's an egress
    ``interface``.  Per-VRF static routes are deferred (declared
    unsupported).
    """
    routes: list[CanonicalStaticRoute] = []
    for line in raw.splitlines():
        m = _STATIC_ROUTE_RE.match(line)
        if not m:
            continue
        dest_ip, prefix, gw_or_iface, metric_str = m.groups()
        metric = int(metric_str) if metric_str else 0
        gateway = ""
        iface = ""
        try:
            ipaddress.IPv4Address(gw_or_iface)
            gateway = gw_or_iface
        except ipaddress.AddressValueError:
            iface = gw_or_iface
        routes.append(CanonicalStaticRoute(
            destination=f"{dest_ip}/{prefix}",
            gateway=gateway,
            interface=iface,
            metric=metric,
        ))
    return routes
