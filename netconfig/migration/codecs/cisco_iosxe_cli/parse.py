"""
Parse path for Cisco IOS-XE CLI (``show running-config`` form).

Public function: :func:`parse_intent` — raw text in,
:class:`CanonicalIntent` out.  Stable across IOS 15.x / IOS-XE 16.x /
17.x.

Note: probe is in :mod:`.codec`; this module assumes input has already
been classified as Cisco IOS-XE CLI.

Handles hostname, interfaces (physical / SVI / Loopback / Port-channel /
Tunnel), VLANs (top-level + SVI-synthesised), static routes,
``ip default-gateway``, SNMP (community / location / contact / trap-host
/ v3 USM), local users, DHCP pools, RADIUS servers (modern named
stanza + legacy one-liner), and LAGs (``Port-channelN`` declarations +
per-member ``channel-group N mode M`` lines).

Extracted verbatim from ``codec.py`` during the parse/render split;
behaviour is identical to the prior in-class implementation.  The
codec module's ``parse()`` method is now a one-line delegator to
:func:`parse_intent`.

Internal helpers (``_extract_hostname``, ``_parse_interfaces``,
``_parse_vlans``, ``_synthesize_vlans_from_svis``, ``_parse_lags``,
``_parse_static_routes``, ``_parse_dhcp_pools``,
``_parse_radius_servers``, ``_parse_local_users``, ``_parse_snmp``)
and the module-level regex constants (``_IFACE_RE`` etc.) live here
because they are parse-only.  ``_mask_to_prefix`` lives here too —
the render path uses the inverse helper ``_prefix_to_mask`` from
:mod:`.render` and the two never cross sibling boundaries.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any

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
from ..base import ParseError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI parser internals
# ---------------------------------------------------------------------------

_IFACE_RE = re.compile(r"^interface\s+(\S+)", re.IGNORECASE)
_DESC_RE = re.compile(r"^\s+description\s+(.+)", re.IGNORECASE)
_IP_RE = re.compile(
    r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
# GAP-EVPN-3: ``ipv6 address 2001:db8::1/64`` (global) or
# ``ipv6 address fe80::1 link-local`` (explicit link-local; bare
# address with no prefix on IOS-XE).  Captures the address-token
# (with optional /N suffix) and the optional ``link-local`` trailer.
_IPV6_RE = re.compile(
    r"^\s+ipv6\s+address\s+(\S+)(?:\s+(link-local))?\s*$",
    re.IGNORECASE,
)
_SHUTDOWN_RE = re.compile(r"^\s+shutdown\s*$", re.IGNORECASE)
_NO_SHUTDOWN_RE = re.compile(r"^\s+no\s+shutdown\s*$", re.IGNORECASE)
_MTU_RE = re.compile(r"^\s+mtu\s+(\d+)\s*$", re.IGNORECASE)

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
# ``ip default-gateway X`` is the L2-switch form of a default route.
# Common on Catalyst switches that have no routing enabled — the switch
# itself still needs a gateway for its management SVI.  We map it to the
# same CanonicalStaticRoute shape the Aruba renderer already uses for
# 0.0.0.0/0 destinations.
_DEFAULT_GATEWAY_RE = re.compile(
    r"^ip\s+default-gateway\s+(\d+\.\d+\.\d+\.\d+)",
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
# ``channel-group N mode M`` declares this physical port as a member of
# LAG ``Port-channelN``.  Cisco's mode vocabulary:
#   active  -> LACP active  (canonical: "active")
#   passive -> LACP passive (canonical: "passive")
#   on      -> static        (canonical: "static")
#   auto/desirable -> PAgP (Cisco-proprietary; we fold to "active")
_CHANNEL_GROUP_RE = re.compile(
    r"^\s+channel-group\s+(\d+)\s+mode\s+(\S+)", re.IGNORECASE,
)
_CISCO_LAG_MODE_MAP = {
    "active": "active",
    "passive": "passive",
    "on": "static",
    "auto": "active",       # PAgP → best-effort equivalent
    "desirable": "active",  # PAgP → best-effort equivalent
}
# ``username NAME privilege N [secret|password] [HASHTYPE] HASH``
# Captures:
#   group 1 = user name
#   group 2 = privilege level (digits; optional — defaults to 1)
#   group 3 = secret/password keyword (drives hash interpretation)
#   group 4 = hash-type digit (optional — Cisco uses 0=plaintext,
#             5=MD5, 7=reversible, 8=PBKDF2, 9=scrypt).  We preserve
#             it verbatim so the target codec can tell a plaintext
#             default from a real hash.
#   group 5 = hash payload itself
# ``secret`` is preferred on IOS-XE (strong hashing); ``password`` is
# legacy + reversible and should trigger a lossy-path warning on
# render targets that refuse weak hashes.
_LOCAL_USER_RE = re.compile(
    r"^username\s+(\S+)"
    r"(?:\s+privilege\s+(\d+))?"
    r"\s+(secret|password)\s+(?:(\d+)\s+)?(\S.*)$",
    re.IGNORECASE,
)


def parse_intent(raw: str) -> CanonicalIntent:
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

    # VLANs (top-level `vlan N / name X` stanzas)
    intent.vlans = _parse_vlans(raw)

    # Synthesize VLAN records for any `interface Vlan<N>` SVIs that
    # didn't have a matching top-level stanza.  Without this, VLAN-
    # centric downstream codecs (Aruba, OPNsense) can't find the
    # SVI's IP and silently drop it.  See translator-plans.txt
    # "KNOWN DATA-LOSS BUGS / BUG 1".
    _synthesize_vlans_from_svis(intent)

    # Static routes
    intent.static_routes = _parse_static_routes(raw)

    # SNMP (Tier 2)
    intent.snmp = _parse_snmp(raw)

    # Local users (Tier 2).
    intent.local_users = _parse_local_users(raw)

    # DHCP server pools (Tier 2).
    intent.dhcp_servers = _parse_dhcp_pools(raw)

    # RADIUS servers (Tier 2).  Handles both modern named-server
    # syntax and legacy `radius-server host` one-liner.
    intent.radius_servers = _parse_radius_servers(raw)

    # LAGs (Tier 2) — both the `interface Port-channelN` declaration
    # and the per-member `channel-group N mode M` lines contribute.
    # See translator-plans.txt BUG 2.
    intent.lags = _parse_lags(raw, intent)

    # Bug 3 transpose: mirror per-port switchport state into the
    # VLAN-centric tagged_ports / untagged_ports lists so VLAN-
    # centric renderers (Aruba, OPNsense) can emit the membership.
    # Without this, per-interface `switchport access vlan 20` /
    # `switchport trunk allowed vlan 11,20` never reaches the
    # target config.  See translator-plans.txt BUG 3.
    from ...canonical.transforms import project_switchport_to_vlan
    project_switchport_to_vlan(intent)

    # Parse-end summary: lets ops answer "did parse succeed?" from
    # a debug-level log line without needing to inspect the
    # response JSON.  Zero counts across the board on a non-empty
    # input usually mean a grammar the codec doesn't handle —
    # same signal the real-capture harness enforces at test time.
    logger.debug(
        "cisco_iosxe_cli parsed: hostname=%r ifaces=%d vlans=%d "
        "routes=%d lags=%d users=%d snmp=%s (input=%d chars)",
        intent.hostname,
        len(intent.interfaces),
        len(intent.vlans),
        len(intent.static_routes),
        len(intent.lags),
        len(intent.local_users),
        "yes" if intent.snmp else "no",
        len(raw),
    )
    return intent


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
                "lag_member_of": None,
                "mtu": None,
                "ipv6": [],
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

        mm = _MTU_RE.match(line)
        if mm:
            try:
                current["mtu"] = int(mm.group(1))
            except ValueError:
                pass
            continue

        im = _IP_RE.match(line)
        if im:
            ip_str = im.group(1)
            mask_str = im.group(2)
            prefix_len = _mask_to_prefix(mask_str)
            if not current["ipv4"]:  # primary only
                current["ipv4"].append({"ip": ip_str, "prefix_length": prefix_len})
            continue

        # GAP-EVPN-3: IPv6 address.  IOS-XE uses CIDR form natively
        # (``ipv6 address 2001:db8::1/64``) — unlike its dotted-mask
        # IPv4 form.  The ``link-local`` keyword tags an address as
        # link-local-scope; bare ``ipv6 address fe80::1 link-local``
        # without a prefix takes the implicit /64 from fe80::/10.
        v6m = _IPV6_RE.match(line)
        if v6m:
            addr = v6m.group(1)
            scope = "link-local" if v6m.group(2) else "global"
            if "/" in addr:
                ip_part, prefix_str = addr.split("/", 1)
                try:
                    current["ipv6"].append({
                        "ip": ip_part,
                        "prefix_length": int(prefix_str),
                        "scope": scope,
                    })
                except ValueError:
                    pass
            elif scope == "link-local":
                current["ipv6"].append({
                    "ip": addr,
                    "prefix_length": 64,
                    "scope": "link-local",
                })
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

        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            current["lag_member_of"] = f"Port-channel{int(cgm.group(1))}"
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
        ipv6_addresses=[
            CanonicalIPv6Address(
                ip=a["ip"],
                prefix_length=a["prefix_length"],
                scope=a.get("scope", "global"),
            )
            for a in raw.get("ipv6", [])
        ],
        switchport_mode=raw.get("switchport_mode"),
        access_vlan=raw.get("access_vlan"),
        trunk_allowed_vlans=raw.get("trunk_allowed", []),
        trunk_native_vlan=raw.get("trunk_native"),
        lag_member_of=raw.get("lag_member_of"),
        mtu=raw.get("mtu"),
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


_SVI_NAME_RE = re.compile(r"^Vlan(\d+)$", re.IGNORECASE)


def _synthesize_vlans_from_svis(intent: CanonicalIntent) -> None:
    """Post-parse pass that derives VLAN records from ``interface
    Vlan<N>`` stanzas.

    On Cisco IOS, a VLAN can exist two ways:

    1. Explicit L2 database entry — ``vlan 11 / name Users``
    2. Implicit, via the SVI alone — ``interface Vlan11 / ip address
       X / description Users``

    :func:`_parse_vlans` only catches form (1).  Without this helper
    the L3 data attached to form (2) would get silently dropped by
    any VLAN-centric downstream codec (Aruba, OPNsense) because its
    renderer looks for the IP under ``tree.vlans``, not under the
    ``Vlan<N>`` interface itself.

    Behaviour:
        * SVI with no existing VLAN record → create one with the
          SVI's IPs attached.
        * SVI with an existing VLAN record (matching id) → merge
          the SVI's IPs in.  The top-level stanza's ``name`` wins
          over the SVI's (they're semantically different — VLAN
          name is an L2 tag, SVI description is an L3 interface
          hint — but with no better info we keep whichever came
          first).
        * SVI with no IP (e.g. ``interface Vlan1 / no ip address``)
          still creates/touches a VLAN record so "this VLAN exists"
          is preserved end-to-end.
    """
    existing_by_id: dict[int, CanonicalVlan] = {
        v.id: v for v in intent.vlans
    }
    for iface in intent.interfaces:
        m = _SVI_NAME_RE.match(iface.name)
        if not m:
            continue
        vid = int(m.group(1))
        existing = existing_by_id.get(vid)
        if existing is None:
            synthesised = CanonicalVlan(
                id=vid,
                # SVI description is a reasonable fallback for the
                # VLAN name when no explicit stanza was present.
                name=iface.description,
                ipv4_addresses=list(iface.ipv4_addresses),
            )
            intent.vlans.append(synthesised)
            existing_by_id[vid] = synthesised
            continue
        # Merge SVI IPs into existing VLAN record.  De-dupe in case
        # the same IP was declared both places.
        for addr in iface.ipv4_addresses:
            if addr not in existing.ipv4_addresses:
                existing.ipv4_addresses.append(addr)


def _parse_lags(raw: str, intent: CanonicalIntent) -> list[CanonicalLAG]:
    """Build :class:`CanonicalLAG` records from Cisco CLI.

    Sources of truth in a Cisco config:
      * ``interface Port-channelN`` stanza declares the LAG exists
        (and carries the LAG's description / switchport / IP state
        via the existing interface parse path — that's already on
        ``intent.interfaces``).
      * ``channel-group N mode M`` under a physical interface declares
        that physical port a member of Port-channelN.

    A LAG must exist if EITHER signal is present (Cisco allows defining
    Port-channelN explicitly OR lazily via member channel-group lines).

    Mode is whatever the members agree on; if members disagree, the
    first member's mode wins (rare in practice, but pathological
    configs shouldn't crash us).  If no physical members exist (empty
    LAG stanza), mode defaults to ``CanonicalLAG.mode`` default.
    """
    # Scan: for each `interface X` stanza, note its channel-group (if any).
    members_by_lag: dict[str, list[str]] = {}
    mode_by_lag: dict[str, str] = {}
    declared_lag_names: set[str] = set()

    current_iface: str | None = None
    for line in raw.splitlines():
        m = _IFACE_RE.match(line)
        if m:
            current_iface = m.group(1)
            if current_iface.lower().startswith("port-channel"):
                declared_lag_names.add(current_iface)
            continue
        if current_iface is None:
            continue
        if line.startswith("!") or (line and not line[0].isspace()):
            current_iface = None
            continue
        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            lag_name = f"Port-channel{int(cgm.group(1))}"
            cisco_mode = cgm.group(2).lower()
            canonical_mode = _CISCO_LAG_MODE_MAP.get(cisco_mode, "active")
            # Real configs (and Batfish's grammar-kitchen-sink fixtures)
            # can stack multiple `channel-group N mode M` lines on a
            # single physical interface — either as a historical artefact
            # of mode changes or as test-config variants.  Dedupe so the
            # member list has one entry per physical port.
            members = members_by_lag.setdefault(lag_name, [])
            if current_iface not in members:
                members.append(current_iface)
            # First member's mode wins.
            mode_by_lag.setdefault(lag_name, canonical_mode)

    all_lag_names = declared_lag_names | set(members_by_lag)
    lags: list[CanonicalLAG] = []
    for lag_name in sorted(all_lag_names, key=_lag_sort_key):
        lag = CanonicalLAG(
            name=lag_name,
            members=list(members_by_lag.get(lag_name, [])),
        )
        if lag_name in mode_by_lag:
            lag.mode = mode_by_lag[lag_name]
        lags.append(lag)
    return lags


def _lag_sort_key(name: str) -> tuple[str, int, str]:
    """Stable sort key that groups ``Port-channel<N>`` numerically."""
    m = re.match(r"^(port-channel|trk|bond|lag|lagg)(\d+)$", name, re.IGNORECASE)
    if m:
        return (m.group(1).lower(), int(m.group(2)), "")
    return ("", 0, name)


def _parse_static_routes(raw: str) -> list[CanonicalStaticRoute]:
    """Extract ``ip route`` and ``ip default-gateway`` lines from IOS config text."""
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
            continue
        m = _DEFAULT_GATEWAY_RE.match(line)
        if m:
            # ``ip default-gateway X`` -> 0.0.0.0/0 via X.  Aruba's
            # renderer re-collapses this back to the native
            # ``ip default-gateway`` form.
            routes.append(CanonicalStaticRoute(
                destination="0.0.0.0/0",
                gateway=m.group(1),
            ))
    return routes


# -- SNMP parse helpers (shared via re-export for sibling codecs if needed)

_SNMP_COMMUNITY_RE = re.compile(
    r'^snmp-server\s+community\s+(\S+)', re.IGNORECASE | re.MULTILINE,
)
_SNMP_LOCATION_RE = re.compile(
    r'^snmp-server\s+location\s+(.+)$', re.IGNORECASE | re.MULTILINE,
)
_SNMP_CONTACT_RE = re.compile(
    r'^snmp-server\s+contact\s+(.+)$', re.IGNORECASE | re.MULTILINE,
)
_SNMP_HOST_RE = re.compile(
    r'^snmp-server\s+host\s+(\d+\.\d+\.\d+\.\d+)',
    re.IGNORECASE | re.MULTILINE,
)
# SNMPv3 user line.  Canonical shape on Cisco IOS-XE CLI:
#
#   snmp-server user <name> <group> v3 [auth {md5|sha} <pass>]
#                                     [priv {des|3des|aes {128|192|256}} <pass>]
#
# The ``auth`` and ``priv`` clauses are both optional (noAuthNoPriv
# is expressible).  ``priv aes 128/192/256`` uses two tokens for the
# cipher; every other cipher name is a single token.  The pre-hashed
# form ``auth sha <encrypted_hex> encrypted`` is captured verbatim via
# lazy greedy match — the operator's ``encrypted`` trailer lands in
# the passphrase bucket and round-trips back out on render.
_SNMP_V3_USER_RE = re.compile(
    r"^snmp-server\s+user\s+(\S+)\s+(\S+)\s+v3"
    r"(?:\s+auth\s+(md5|sha|sha224|sha256|sha384|sha512)\s+(\S+))?"
    r"(?:\s+priv\s+(des|3des|aes)(?:\s+(128|192|256))?\s+(\S+))?"
    r"\s*$",
    re.IGNORECASE | re.MULTILINE,
)


_DHCP_POOL_HEADER_RE = re.compile(
    r"^ip\s+dhcp\s+pool\s+(\S+)", re.IGNORECASE,
)
_DHCP_NETWORK_RE = re.compile(
    r"^\s+network\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
_DHCP_DEFAULT_ROUTER_RE = re.compile(
    r"^\s+default-router\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
_DHCP_DNS_SERVER_RE = re.compile(
    r"^\s+dns-server\s+(.+)$", re.IGNORECASE,
)
_DHCP_DOMAIN_NAME_RE = re.compile(
    r"^\s+domain-name\s+(\S+)", re.IGNORECASE,
)
# Cisco lease syntax: `lease <days> [hours] [minutes]` or `lease infinite`
_DHCP_LEASE_RE = re.compile(
    r"^\s+lease\s+(\S+)(?:\s+(\d+))?(?:\s+(\d+))?", re.IGNORECASE,
)


def _parse_dhcp_pools(raw: str) -> list[CanonicalDHCPPool]:
    """Extract ``ip dhcp pool`` stanzas into CanonicalDHCPPool records.

    Cisco pools are defined as a named stanza with indented sub-commands.
    Each pool defines one network and its associated options.  Real
    configs commonly have multiple pools (one per user VLAN).

    Cisco DHCP doesn't use start/end IP ranges natively — instead, the
    pool serves ALL non-excluded IPs in the ``network`` statement, and
    ``ip dhcp excluded-address`` at the global level carves out
    reservations.  We populate ``network`` from the pool stanza and
    leave ``start_ip``/``end_ip`` empty; a future pass can derive them
    from excluded-address lines if needed.
    """
    pools: list[CanonicalDHCPPool] = []
    current: CanonicalDHCPPool | None = None

    for line in raw.splitlines():
        header = _DHCP_POOL_HEADER_RE.match(line)
        if header:
            if current is not None:
                pools.append(current)
            current = CanonicalDHCPPool()
            continue
        if current is None:
            continue
        if line.startswith("!") or (line and not line[0].isspace()):
            pools.append(current)
            current = None
            continue

        nm = _DHCP_NETWORK_RE.match(line)
        if nm:
            ip_str, mask = nm.group(1), nm.group(2)
            prefix = _mask_to_prefix(mask)
            current.network = f"{ip_str}/{prefix}"
            continue
        gm = _DHCP_DEFAULT_ROUTER_RE.match(line)
        if gm:
            current.gateway = gm.group(1)
            continue
        dm = _DHCP_DNS_SERVER_RE.match(line)
        if dm:
            # Cisco allows multiple DNS servers space-separated.
            servers = dm.group(1).split()
            current.dns_servers.extend(servers)
            continue
        dnm = _DHCP_DOMAIN_NAME_RE.match(line)
        if dnm:
            current.domain_name = dnm.group(1)
            continue
        lm = _DHCP_LEASE_RE.match(line)
        if lm:
            lease_val = lm.group(1).lower()
            if lease_val == "infinite":
                # Max uint32 seconds is DHCP's "infinite" marker.
                current.lease_time = 0xFFFFFFFF
            else:
                try:
                    days = int(lease_val)
                    hours = int(lm.group(2) or 0)
                    minutes = int(lm.group(3) or 0)
                    current.lease_time = (
                        days * 86400 + hours * 3600 + minutes * 60
                    )
                except ValueError:
                    pass  # Unparseable; leave default

    if current is not None:
        pools.append(current)
    return pools


# Modern IOS-XE RADIUS: named stanza
#   radius server <name>
#    address ipv4 <ip> auth-port <N> acct-port <N>
#    key [7] <secret>
_RADIUS_SERVER_HEADER_RE = re.compile(
    r"^radius\s+server\s+(\S+)", re.IGNORECASE,
)
_RADIUS_ADDRESS_RE = re.compile(
    r"^\s+address\s+ipv4\s+(\d+\.\d+\.\d+\.\d+)"
    r"(?:\s+auth-port\s+(\d+))?"
    r"(?:\s+acct-port\s+(\d+))?",
    re.IGNORECASE,
)
_RADIUS_KEY_RE = re.compile(
    r"^\s+key\s+(?:(\d+)\s+)?(\S.*)$",
    re.IGNORECASE,
)
# Legacy IOS: single line
#   radius-server host <ip> [auth-port <N>] [acct-port <N>] [key <secret>]
_RADIUS_HOST_LEGACY_RE = re.compile(
    r"^radius-server\s+host\s+(\d+\.\d+\.\d+\.\d+)"
    r"(?:\s+auth-port\s+(\d+))?"
    r"(?:\s+acct-port\s+(\d+))?"
    r"(?:\s+key\s+(?:\d+\s+)?(\S+.*))?",
    re.IGNORECASE,
)


def _parse_radius_servers(raw: str) -> list[CanonicalRADIUSServer]:
    """Extract RADIUS server definitions from IOS CLI text.

    Handles both the modern named-stanza form (``radius server NAME`` /
    ``address ipv4 ...`` / ``key ...``) and the legacy one-liner
    (``radius-server host X auth-port N key SECRET``).
    """
    servers: list[CanonicalRADIUSServer] = []
    current: CanonicalRADIUSServer | None = None

    for line in raw.splitlines():
        # Modern header opens a new stanza.
        header = _RADIUS_SERVER_HEADER_RE.match(line)
        if header:
            if current is not None and current.host:
                servers.append(current)
            current = CanonicalRADIUSServer(host="")
            continue

        # Legacy single-line form.
        legacy = _RADIUS_HOST_LEGACY_RE.match(line)
        if legacy:
            # Flush any in-progress modern stanza before recording legacy.
            if current is not None and current.host:
                servers.append(current)
                current = None
            host = legacy.group(1)
            auth_port = int(legacy.group(2) or 1812)
            acct_port = int(legacy.group(3) or 1813)
            key = (legacy.group(4) or "").strip()
            servers.append(CanonicalRADIUSServer(
                host=host,
                auth_port=auth_port,
                acct_port=acct_port,
                key=key,
            ))
            continue

        if current is None:
            continue

        # Modern-stanza body.
        if line.startswith("!") or (line and not line[0].isspace()):
            if current.host:
                servers.append(current)
            current = None
            continue
        am = _RADIUS_ADDRESS_RE.match(line)
        if am:
            current.host = am.group(1)
            if am.group(2):
                current.auth_port = int(am.group(2))
            if am.group(3):
                current.acct_port = int(am.group(3))
            continue
        km = _RADIUS_KEY_RE.match(line)
        if km:
            key_type = km.group(1) or ""
            key_val = km.group(2).strip()
            # Preserve the type digit prefix so a lossless render
            # back to Cisco can reconstruct it; other codecs can
            # strip the prefix.
            current.key = f"{key_type} {key_val}" if key_type else key_val

    if current is not None and current.host:
        servers.append(current)
    return servers


def _parse_local_users(raw: str) -> list[CanonicalLocalUser]:
    """Extract ``username NAME privilege N secret|password ...`` lines.

    Cisco IOS privilege scale is 1-15 (15 = full admin).  We map that
    to CanonicalLocalUser.privilege_level verbatim and set the
    canonical ``role`` to ``admin`` for privilege 15, ``operator`` for
    anything else — gives VLAN-centric target codecs (Aruba AOS-S
    manager/operator distinction) a deterministic mapping without
    guessing.

    Hashed passwords are preserved verbatim including the Cisco
    type-digit prefix (``5 $1$..``, ``7 091C08``, ``9 $9$..``) so a
    lossless round-trip back to a Cisco target can reconstruct the
    original command.  Other codecs that render plaintext or BCrypt
    hashes can reject these as lossy.
    """
    users: list[CanonicalLocalUser] = []
    seen_names: set[str] = set()
    for line in raw.splitlines():
        m = _LOCAL_USER_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        # Cisco sometimes emits multiple lines per user (e.g. adding
        # ssh pubkeys).  Dedupe by name — first wins.
        if name in seen_names:
            continue
        seen_names.add(name)
        privilege_str = m.group(2)
        privilege = int(privilege_str) if privilege_str else 1
        kw = m.group(3).lower()          # "secret" or "password"
        hash_type = m.group(4) or ""
        hash_payload = m.group(5).strip()
        # Preserve the type digit as part of the opaque hash so the
        # target codec's render can reconstruct if needed.
        if hash_type:
            hashed = f"{hash_type} {hash_payload}"
        else:
            hashed = hash_payload
        # Annotate reversible-type-7 secrets so downstream codecs can
        # warn / refuse.  A `password 7 ...` or `secret 7 ...` is
        # weak and should be flagged.
        if kw == "password":
            # `password` keyword implies legacy weak encoding unless
            # explicitly typed strong.  We just carry it through; the
            # render side can decide policy.
            pass
        users.append(CanonicalLocalUser(
            name=name,
            privilege_level=privilege,
            hashed_password=hashed,
            role="admin" if privilege == 15 else "operator",
        ))
    return users


def _parse_snmp(raw: str) -> CanonicalSNMP | None:
    """Extract SNMP server config from IOS CLI text.

    Returns None when no snmp-server lines are present so the
    downstream canonical tree doesn't carry an empty stub.
    """
    community_m = _SNMP_COMMUNITY_RE.search(raw)
    location_m = _SNMP_LOCATION_RE.search(raw)
    contact_m = _SNMP_CONTACT_RE.search(raw)
    hosts = _SNMP_HOST_RE.findall(raw)
    # SNMPv3 users — each match is (name, group, auth_proto, auth_pass,
    # priv_proto, priv_keybits, priv_pass).  Last three are empty when
    # the user is auth-no-priv; middle two empty when no-auth-no-priv.
    v3_matches = list(_SNMP_V3_USER_RE.finditer(raw))
    if not (community_m or location_m or contact_m or hosts or v3_matches):
        return None
    from ...canonical.intent import CanonicalSNMPv3User  # lazy local import
    snmp = CanonicalSNMP()
    if community_m:
        snmp.community = community_m.group(1).strip()
    if location_m:
        snmp.location = location_m.group(1).strip().strip('"')
    if contact_m:
        snmp.contact = contact_m.group(1).strip().strip('"')
    snmp.trap_hosts = list(hosts)
    for m in v3_matches:
        name, group, auth_p, auth_pw, priv_p, priv_bits, priv_pw = m.groups()
        # Cisco spells ``aes 128`` / ``aes 192`` / ``aes 256`` as two
        # tokens; canonicalise to the single-token form.  ``3des`` /
        # ``des`` are single tokens; preserved.  Missing priv_bits
        # with ``aes`` falls back to aes128 (Cisco default).
        if priv_p and priv_p.lower() == "aes":
            priv_p_norm = f"aes{priv_bits}" if priv_bits else "aes128"
        elif priv_p:
            priv_p_norm = priv_p.lower()
        else:
            priv_p_norm = ""
        snmp.v3_users.append(CanonicalSNMPv3User(
            name=name,
            group=group,
            auth_protocol=(auth_p or "").lower(),
            auth_passphrase=auth_pw or "",
            priv_protocol=priv_p_norm,
            priv_passphrase=priv_pw or "",
        ))
    return snmp
