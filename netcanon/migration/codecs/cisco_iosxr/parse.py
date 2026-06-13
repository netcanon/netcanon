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

Phase 2 surface (this commit):

* top-level ``vrf <name>`` stanzas → :class:`CanonicalRoutingInstance`
  (name + description + nested ``address-family ipv4 unicast /
  import|export route-target`` blocks → ``rt_imports`` / ``rt_exports``).
* ``router bgp <asn> / vrf <name> / rd <rd>`` → the VRF's
  ``route_distinguisher`` (IOS-XR keeps the RD in the BGP block, NOT in
  the ``vrf`` stanza — the big XR/XE structural divergence).  Harvested
  by :func:`_merge_bgp_rd`; an XR config without a ``router bgp`` stanza
  keeps ``route_distinguisher=''`` (declared lossy in the matrix).
* per-interface ``vrf <name>`` membership → :attr:`CanonicalInterface.vrf`
  (IOS-XR uses a bare ``vrf``; IOS-XE uses ``vrf forwarding``, NX-OS
  ``vrf member``).
* ``router static / vrf <name> / address-family ipv4 unicast`` per-VRF
  static routes → :class:`CanonicalStaticRoute` with ``vrf=<name>``.
* ``Bundle-Ether<N>`` LAGs — the ``interface Bundle-Ether<N>``
  declaration plus member ports' ``bundle id <N> mode <m>`` →
  :class:`CanonicalLAG` + :attr:`CanonicalInterface.lag_member_of`.
* local users — the block form ``username <name> / group <role> /
  secret <type> <hash>`` (and the single-line variant) →
  :class:`CanonicalLocalUser`.
* sub-interface ``encapsulation dot1q <vid>`` → synthesised
  :class:`CanonicalVlan` records (id-only; XR routers have no classic
  ``vlan`` stanza — see the matrix note).

Where IOS-XR diverges from ``cisco_iosxe_cli`` (see
``02-codec-architecture.md`` § "Parse strategy"):

* Stanzas are terminated by a ``!`` line (and close defensively on a
  shallower-indent line); indentation nests 3-4 deep, not 1-2.
* IPv4 addresses use ``ipv4 address X Y`` (note the ``ipv4`` keyword,
  not IOS-XE's ``ip address``); the mask is dotted-decimal.
* Static routes live in a ``router static`` block with CIDR-form
  destinations, not top-level ``ip route X Y Z`` lines.
* Route-targets nest as ``import|export route-target`` sub-blocks with
  the RT values on their own further-indented lines (the opposite word
  order from NX-OS / IOS-XE's single-line ``route-target import <rt>``).
* The route-distinguisher lives under ``router bgp``, not the VRF stanza.

Deliberately NOT parsed (declared ``unsupported`` in the capability
matrix — Tier-3): the SP-routing protocol blocks (``router bgp`` beyond
the per-VRF RD harvest, ``router ospf`` / ``isis``), MPLS, the
``route-policy`` / ``prefix-set`` DSL, ACLs, and ``l2vpn`` / ``evpn``
(the latter surfaced via ``dropped_tier3_sections``).
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
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRoutingInstance,
    CanonicalStaticRoute,
    CanonicalVlan,
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
#: ``vrf <name>`` inside an interface stanza → per-interface VRF
#: membership (IOS-XR's bare-``vrf`` form).  Indented; the column-0
#: ``vrf <name>`` is a top-level routing-instance stanza handled by
#: :func:`_parse_routing_instances`.  Reused by the BGP-RD walker.
_INDENTED_VRF_RE = re.compile(r"^\s+vrf\s+(\S+)\s*$", re.IGNORECASE)
#: ``encapsulation dot1q <vid>`` on a sub-interface → the 802.1Q tag,
#: harvested into a synthesised :class:`CanonicalVlan`.
_ENCAP_DOT1Q_RE = re.compile(
    r"^\s+encapsulation\s+dot1q\s+(\d+)", re.IGNORECASE,
)
#: ``bundle id <N> mode <active|passive|on>`` → member of Bundle-Ether<N>.
_BUNDLE_ID_RE = re.compile(
    r"^\s+bundle\s+id\s+(\d+)\s+mode\s+(\S+)", re.IGNORECASE,
)
#: IOS-XR LACP mode vocab → canonical LAG mode (``on`` is static
#: aggregation).  Inverse map lives in :mod:`.render`.
_IOSXR_LAG_MODE_MAP = {"active": "active", "passive": "passive", "on": "static"}

#: ``router static`` opens the static-route block.
_ROUTER_STATIC_RE = re.compile(r"^router\s+static\s*$", re.IGNORECASE)
_AF_IPV4_UNICAST_RE = re.compile(
    r"^address-family\s+ipv4\s+unicast\b", re.IGNORECASE,
)
_STATIC_VRF_RE = re.compile(r"^vrf\s+(\S+)", re.IGNORECASE)
#: A static-route leaf: ``<dest>/<prefix> <token>...`` (CIDR destination).
_STATIC_LEAF_RE = re.compile(
    r"^(\d+\.\d+\.\d+\.\d+/\d+)\s+(.+)$",
)

# ── VRF top-level stanza + route-target blocks (Phase 2) ──
#: ``vrf <name>`` at column 0 opens a top-level VRF stanza.  IOS-XR uses
#: a bare ``vrf NAME`` (not IOS-XE's ``vrf definition`` / NX-OS's ``vrf
#: context``).  The ``router static`` / ``router bgp`` sub-blocks also
#: contain ``vrf NAME`` lines, but those are indented and never match
#: this column-0 anchor.
_VRF_TOP_RE = re.compile(r"^vrf\s+(\S+)\s*$", re.IGNORECASE)
_VRF_DESC_RE = re.compile(r"^\s+description\s+(.+)", re.IGNORECASE)
#: ``import route-target`` / ``export route-target`` open an RT sub-block
#: inside ``address-family ipv4 unicast``; the RT values sit on their own
#: further-indented lines, terminated by ``!``.
_IMPORT_RT_RE = re.compile(r"^\s+import\s+route-target\s*$", re.IGNORECASE)
_EXPORT_RT_RE = re.compile(r"^\s+export\s+route-target\s*$", re.IGNORECASE)
#: An RT value line inside an import/export block — ``65001:100`` or
#: ``10.0.0.1:100`` (administrator:assigned-number).
_RT_VALUE_RE = re.compile(r"^(\S+:\d+)\s*$")

# ── router bgp / vrf / rd harvest (Phase 2) ──
#: ``router bgp <asn>`` opens the BGP process; only the per-VRF ``rd`` is
#: harvested (the rest is Tier-3, surfaced via ``dropped_tier3_sections``).
_ROUTER_BGP_RE = re.compile(r"^router\s+bgp\s+\d+", re.IGNORECASE)
#: ``rd <rd>`` nested under ``router bgp / vrf <name>``.
_BGP_RD_RE = re.compile(r"^\s+rd\s+(\S+)\s*$", re.IGNORECASE)

# ── local users (Phase 2) ──
#: ``username <name>`` alone on a line opens a user block; ``group`` /
#: ``secret`` / ``password`` sub-lines follow, terminated by ``!`` or a
#: column-0 line.
_USERNAME_HDR_RE = re.compile(r"^username\s+(\S+)\s*$", re.IGNORECASE)
#: single-line variant ``username <name> {secret|password} <type> <hash>``.
_USERNAME_INLINE_RE = re.compile(
    r"^username\s+(\S+)\s+(?:secret|password)\s+(\d+)\s+(\S+)", re.IGNORECASE,
)
_USER_GROUP_RE = re.compile(r"^\s+group\s+(\S+)", re.IGNORECASE)
_USER_SECRET_RE = re.compile(
    r"^\s+(?:secret|password)\s+(\d+)\s+(\S+)", re.IGNORECASE,
)
#: IOS-XR task-groups that map to the cross-vendor admin privilege (15).
#: Other groups round-trip their name verbatim but map to privilege 1.
_IOSXR_ADMIN_GROUPS = {"root-lr", "root-system"}

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


def _fmt_secret(hash_type: str | None, payload: str) -> str:
    """Normalise a ``secret``/``password`` ``<type> <hash>`` pair.

    Preserves the type-digit prefix (``10 $6$...``) so a same-vendor
    round-trip reconstructs the line; type 0 (the plaintext marker) is
    stored bare to avoid the ``secret 0 0 X`` double-prefix bug (mirrors
    the cisco_iosxe_cli / cisco_nxos convention).
    """
    if hash_type and hash_type != "0":
        return f"{hash_type} {payload}"
    return payload


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

    # VRF declarations (top-level ``vrf <name>`` stanzas: description +
    # route-target import/export).  The route-distinguisher lives in the
    # BGP block, so it's harvested separately and merged in by name.
    intent.routing_instances = _parse_routing_instances(raw)
    _merge_bgp_rd(raw, intent.routing_instances)

    # Sub-interface ``encapsulation dot1q`` → synthesised VLAN records.
    intent.vlans = _parse_dot1q_vlans(raw)

    # Static routes — default-VRF + per-VRF (``router static / vrf X``).
    intent.static_routes = _parse_router_static(raw)

    # Bundle-Ether LAGs + local users (Phase 2).
    intent.lags = _parse_lags(raw)
    intent.local_users = _parse_local_users(raw)

    logger.debug(
        "cisco_iosxr parsed: hostname=%r ifaces=%d vrfs=%d vlans=%d "
        "routes=%d lags=%d users=%d (input=%d chars)",
        intent.hostname,
        len(intent.interfaces),
        len(intent.routing_instances),
        len(intent.vlans),
        len(intent.static_routes),
        len(intent.lags),
        len(intent.local_users),
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
        "vrf": "",
        "lag_member_of": None,
    }


def _parse_interfaces(raw: str) -> list[CanonicalInterface]:
    """Extract ``interface <name>`` stanzas from IOS-XR config text.

    Per interface: description, enabled (``shutdown``), mtu, IPv4 (dotted
    mask → prefix), IPv6 (CIDR + scope), VRF membership (bare ``vrf
    <name>``), and Bundle-Ether membership (``bundle id <N> mode <m>`` →
    ``lag_member_of``).  Stanzas close on a ``!`` line or a
    shallower-indent (non-indented) line.  ``encapsulation dot1q`` is
    handled by :func:`_parse_dot1q_vlans` (a separate scan) — it falls
    through this loop harmlessly.
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
        bm = _BUNDLE_ID_RE.match(line)
        if bm:
            current["lag_member_of"] = f"Bundle-Ether{int(bm.group(1))}"
            continue
        vm = _INDENTED_VRF_RE.match(line)
        if vm:
            current["vrf"] = vm.group(1)
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
        vrf=raw.get("vrf", ""),
        lag_member_of=raw.get("lag_member_of"),
    )


# ---------------------------------------------------------------------------
# VRF stanzas + route-targets (Phase 2)
# ---------------------------------------------------------------------------


def _parse_routing_instances(raw: str) -> list[CanonicalRoutingInstance]:
    """Extract top-level ``vrf <name>`` stanzas → routing-instances.

    An IOS-XR VRF stanza looks like::

        vrf CUSTOMER-A
         description customer a l3vpn
         address-family ipv4 unicast
          import route-target
           65001:100
          !
          export route-target
           65001:100
          !
         !
        !

    Harvests ``name`` / ``description`` and the ``import|export
    route-target`` block values.  The ``route_distinguisher`` is NOT here
    — IOS-XR keeps it under ``router bgp`` (see :func:`_merge_bgp_rd`).
    A small ``rt_mode`` state machine collects the RT values that sit on
    their own lines inside each import/export block (terminated by ``!``).
    """
    instances: list[CanonicalRoutingInstance] = []
    current: CanonicalRoutingInstance | None = None
    rt_mode: str | None = None  # None | "import" | "export"

    for line in raw.splitlines():
        header = _VRF_TOP_RE.match(line)
        if header:
            if current is not None:
                instances.append(current)
            current = CanonicalRoutingInstance(name=header.group(1))
            rt_mode = None
            continue

        if current is None:
            continue

        # Any non-indented line closes the stanza (a sibling top-level
        # stanza or a ``!`` separator at column 0).
        if line and not line[0].isspace():
            instances.append(current)
            current = None
            rt_mode = None
            header = _VRF_TOP_RE.match(line)
            if header:
                current = CanonicalRoutingInstance(name=header.group(1))
            continue

        if _IMPORT_RT_RE.match(line):
            rt_mode = "import"
            continue
        if _EXPORT_RT_RE.match(line):
            rt_mode = "export"
            continue

        stripped = line.strip()
        if rt_mode is not None:
            if stripped == "!":
                rt_mode = None
                continue
            rtm = _RT_VALUE_RE.match(stripped)
            if rtm:
                rt = rtm.group(1)
                if rt_mode == "import":
                    current.rt_imports.append(rt)
                else:
                    current.rt_exports.append(rt)
            # Any other line inside an RT block — ignore (stay in mode).
            continue

        dm = _VRF_DESC_RE.match(line)
        if dm:
            current.description = dm.group(1).strip()
            continue
        # ``address-family`` framing / ``!`` separators / other — ignore.

    if current is not None:
        instances.append(current)
    return instances


def _parse_bgp_rd(raw: str) -> dict[str, str]:
    """Harvest per-VRF route-distinguishers from the ``router bgp`` block.

    IOS-XR stores the RD in the BGP process, not the ``vrf`` stanza::

        router bgp 65001
         vrf CUSTOMER-A
          rd 65001:100
          address-family ipv4 unicast
          !
         !
        !

    Returns ``{vrf_name: rd}``.  Only the per-VRF ``rd`` lines are read;
    the rest of the BGP block is Tier-3 (surfaced via
    ``dropped_tier3_sections``, never modelled).
    """
    rd_by_vrf: dict[str, str] = {}
    in_bgp = False
    current_vrf: str | None = None

    for line in raw.splitlines():
        if _ROUTER_BGP_RE.match(line):
            in_bgp = True
            current_vrf = None
            continue
        if not in_bgp:
            continue
        # A non-indented line ends the BGP block.
        if line and not line[0].isspace():
            in_bgp = False
            current_vrf = None
            continue
        vm = _INDENTED_VRF_RE.match(line)
        if vm:
            current_vrf = vm.group(1)
            continue
        if current_vrf is not None:
            rdm = _BGP_RD_RE.match(line)
            if rdm:
                rd_by_vrf[current_vrf] = rdm.group(1)
                continue
    return rd_by_vrf


def _merge_bgp_rd(
    raw: str, instances: list[CanonicalRoutingInstance],
) -> None:
    """Merge ``router bgp`` per-VRF RDs onto the matching routing-instances.

    A BGP ``vrf`` block with no matching top-level ``vrf <name>`` stanza
    is skipped rather than materialising a phantom instance — the ``vrf``
    stanza is the authoritative VRF declaration, and conjuring an empty
    instance from an orphan RD would register as cross-vendor CODEC_BUG
    drift (see the per-VRF-harvest memory).
    """
    rd_by_vrf = _parse_bgp_rd(raw)
    if not rd_by_vrf:
        return
    by_name = {ri.name: ri for ri in instances}
    for vrf_name, rd in rd_by_vrf.items():
        ri = by_name.get(vrf_name)
        if ri is not None:
            ri.route_distinguisher = rd


# ---------------------------------------------------------------------------
# Sub-interface dot1q → VLAN synthesis (Phase 2)
# ---------------------------------------------------------------------------


def _parse_dot1q_vlans(raw: str) -> list[CanonicalVlan]:
    """Synthesise :class:`CanonicalVlan` records from sub-interface tags.

    IOS-XR routers have no classic ``vlan N / name X`` stanza — VLAN ids
    appear only on sub-interfaces via ``encapsulation dot1q <vid>``.  Each
    distinct tag becomes a bare ``CanonicalVlan`` (``name`` always empty;
    no port membership) so VLAN-centric downstream codecs see the id-list.
    Records are returned sorted + de-duplicated by id for a stable
    round-trip (the round-trip harness compares VLANs id-sorted).
    """
    seen: set[int] = set()
    for line in raw.splitlines():
        m = _ENCAP_DOT1Q_RE.match(line)
        if m:
            vid = int(m.group(1))
            if 1 <= vid <= 4094:
                seen.add(vid)
    return [CanonicalVlan(id=vid, name="") for vid in sorted(seen)]


# ---------------------------------------------------------------------------
# Static routes — default VRF + per-VRF (Phase 2)
# ---------------------------------------------------------------------------


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _parse_static_leaf(
    text: str, vrf: str = "",
) -> CanonicalStaticRoute | None:
    """Parse one ``<CIDR> <next-hop>...`` static-route leaf line.

    The next-hop tokens are a mix of an egress interface and/or a
    gateway IP (``10.0.0.0/8 GigabitEthernet0/0/0/2 11.1.1.2`` carries
    both; ``11.0.0.0/8 Null0`` carries only an interface;
    ``0.0.0.0/0 1.2.3.4`` only a gateway).  An IPv4-parseable token is
    the gateway; the first non-IP token is the egress interface.  *vrf*
    tags the route's routing-table membership (empty = default VRF).
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
        destination=dest, gateway=gateway, interface=iface, vrf=vrf,
    )


def _parse_router_static(raw: str) -> list[CanonicalStaticRoute]:
    """Extract routes from the ``router static`` block (default + per-VRF).

    The default address-family routes sit directly under ``address-family
    ipv4 unicast``; per-VRF routes nest one level deeper under ``vrf
    <name> / address-family ipv4 unicast`` and are tagged with
    ``vrf=<name>``.  Block-relative scope is driven by the ``!``
    terminators IOS-XR always emits — ``in_af`` gates leaf harvesting and
    ``current_vrf`` discriminates the routing table.
    """
    routes: list[CanonicalStaticRoute] = []
    in_block = False
    base_indent = 0
    current_vrf = ""
    in_af = False

    for line in raw.splitlines():
        if not in_block:
            if _ROUTER_STATIC_RE.match(line):
                in_block = True
                base_indent = _indent(line)
                current_vrf = ""
                in_af = False
            continue

        stripped = line.strip()
        if not stripped:
            continue
        indent = _indent(line)
        # A non-indented, non-`!` line ends the whole router-static block.
        if indent <= base_indent and stripped != "!":
            in_block = False
            continue

        if _AF_IPV4_UNICAST_RE.match(stripped):
            in_af = True
            continue
        vrfm = _STATIC_VRF_RE.match(stripped)
        if vrfm:
            current_vrf = vrfm.group(1)
            in_af = False
            continue
        if stripped == "!":
            # Close the innermost open scope: the address-family first,
            # then the enclosing vrf.
            if in_af:
                in_af = False
            elif current_vrf:
                current_vrf = ""
            continue
        if in_af:
            r = _parse_static_leaf(stripped, vrf=current_vrf)
            if r:
                routes.append(r)
    return routes


# ---------------------------------------------------------------------------
# Bundle-Ether LAGs (Phase 2)
# ---------------------------------------------------------------------------


def _lag_sort_key(name: str) -> tuple[int, int]:
    """Stable sort key grouping ``Bundle-Ether<N>`` numerically."""
    m = re.match(r"^bundle-ether(\d+)$", name, re.IGNORECASE)
    return (0, int(m.group(1))) if m else (1, 0)


def _parse_lags(raw: str) -> list[CanonicalLAG]:
    """Build :class:`CanonicalLAG` records from IOS-XR bundle config.

    Two signals, either sufficient (mirrors cisco_nxos / cisco_iosxe_cli):
      * an ``interface Bundle-Ether<N>`` stanza declares the LAG exists;
      * a ``bundle id <N> mode <m>`` line under a physical port declares
        that port a member of ``Bundle-Ether<N>``.

    Mode is the first member's mode (XR ``on`` → canonical ``static``);
    an empty bundle keeps :attr:`CanonicalLAG.mode` default.
    """
    members_by_lag: dict[str, list[str]] = {}
    mode_by_lag: dict[str, str] = {}
    declared: set[str] = set()
    current_iface: str | None = None

    def _note_header(name: str) -> None:
        if name.lower().startswith("bundle-ether"):
            declared.add(name)

    for line in raw.splitlines():
        m = _IFACE_RE.match(line)
        if m:
            current_iface = m.group(1)
            _note_header(current_iface)
            continue
        if current_iface is None:
            continue
        if line and not line[0].isspace():
            current_iface = None
            m = _IFACE_RE.match(line)
            if m:
                current_iface = m.group(1)
                _note_header(current_iface)
            continue
        bm = _BUNDLE_ID_RE.match(line)
        if bm:
            lag_name = f"Bundle-Ether{int(bm.group(1))}"
            mode = _IOSXR_LAG_MODE_MAP.get(bm.group(2).lower(), "active")
            members = members_by_lag.setdefault(lag_name, [])
            if current_iface and current_iface not in members:
                members.append(current_iface)
            mode_by_lag.setdefault(lag_name, mode)

    lags: list[CanonicalLAG] = []
    for lag_name in sorted(declared | set(members_by_lag), key=_lag_sort_key):
        lag = CanonicalLAG(
            name=lag_name, members=list(members_by_lag.get(lag_name, [])),
        )
        if lag_name in mode_by_lag:
            lag.mode = mode_by_lag[lag_name]
        lags.append(lag)
    return lags


# ---------------------------------------------------------------------------
# Local users (Phase 2)
# ---------------------------------------------------------------------------


def _build_user(scratch: dict) -> CanonicalLocalUser:
    """Convert a parse-time user scratch dict into a CanonicalLocalUser.

    The IOS-XR ``group`` (task-group) maps to the canonical ``role``
    verbatim; ``root-lr`` / ``root-system`` additionally map to the
    cross-vendor admin privilege (15), everything else to 1 (lossy —
    cross-vendor renderers expecting numeric privilege round-trip non-
    admin groups as 1).
    """
    group = scratch.get("group", "")
    return CanonicalLocalUser(
        name=scratch["name"],
        privilege_level=15 if group.lower() in _IOSXR_ADMIN_GROUPS else 1,
        hashed_password=scratch.get("secret", ""),
        role=group,
    )


def _parse_local_users(raw: str) -> list[CanonicalLocalUser]:
    """Extract ``username`` blocks (and the single-line variant).

    The block form::

        username netops
         group root-lr
         secret 10 $6$abc...
        !

    The single-line form ``username admin secret 5 $1$...`` is accepted
    defensively.  Duplicate usernames keep the first occurrence.  The
    secret preserves its type-digit prefix for a same-vendor round-trip
    (see :func:`_fmt_secret`).
    """
    users: list[CanonicalLocalUser] = []
    seen: set[str] = set()
    current: dict | None = None

    def _flush() -> None:
        nonlocal current
        if current is not None and current["name"] not in seen:
            seen.add(current["name"])
            users.append(_build_user(current))
        current = None

    for line in raw.splitlines():
        im = _USERNAME_INLINE_RE.match(line)
        if im:
            _flush()
            name = im.group(1)
            if name not in seen:
                seen.add(name)
                users.append(CanonicalLocalUser(
                    name=name,
                    privilege_level=1,
                    hashed_password=_fmt_secret(im.group(2), im.group(3)),
                    role="",
                ))
            continue
        hm = _USERNAME_HDR_RE.match(line)
        if hm:
            _flush()
            current = {"name": hm.group(1), "group": "", "secret": ""}
            continue

        if current is None:
            continue

        # `!` terminator or any non-indented line closes the block.
        if line.strip() == "!" or (line and not line[0].isspace()):
            _flush()
            continue

        gm = _USER_GROUP_RE.match(line)
        if gm and not current["group"]:
            current["group"] = gm.group(1)
            continue
        sm = _USER_SECRET_RE.match(line)
        if sm:
            current["secret"] = _fmt_secret(sm.group(1), sm.group(2))
            continue

    _flush()
    return users
