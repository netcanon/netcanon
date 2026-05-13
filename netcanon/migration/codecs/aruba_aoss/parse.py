"""
Aruba AOS-S parser — ``show running-config`` text to ``CanonicalIntent``.

Extracted from ``codec.py`` during the parse/render split per the
``codecs/README.md`` split-codec convention.  Public function
(consumed by ``codec.py::ArubaAOSSCodec.parse()``):

* :func:`parse_intent` — one-shot parse entry: raw text in, fully-
  populated :class:`CanonicalIntent` out.

The parser walks the input line-by-line at column-0 to dispatch to
per-stanza inner parsers (``_parse_vlan_stanza`` /
``_parse_interface_stanza``) for indented bodies that terminate at
``exit`` or the next un-indented line.

Wire-format surfaces handled (mirrors the codec's CapabilityMatrix
``supported`` list): hostname, DNS, NTP, syslog, SNMP (community /
location / contact / trap-host / v3 USM users with separate
``snmpv3 user`` and ``snmpv3 group`` lines), local users, RADIUS
servers, VLANs (with absorbed SVI L3), physical interfaces
(IPv4 + IPv6 with global / link-local scope discriminator), LAG
trunk membership, and static routes / default-gateway.

Internal helpers re-exported from ``codec.py`` for tests that pin the
parser's structural contract (``_parse_port_list``,
``_format_port_list`` is in :mod:`.render`):

* :func:`_parse_port_list` — expand AOS-S port-list syntax (``1-24``,
  ``A1,A2``, ``1/1-1/24``) into individual port names.
* :func:`_mask_to_prefix` — dotted-decimal mask -> CIDR prefix length
  (shared utility, kept on the parse side because the render path
  emits CIDR directly and never converts back to dotted form).
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
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from .._input_shape import detect_input_shape
from ..base import ParseError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Top-level regex constants
# ---------------------------------------------------------------------------


_HOSTNAME_RE = re.compile(r'^hostname\s+"?([^"\n]+)"?', re.IGNORECASE)
# Capture the quoted community token.  AOS-S: `snmp-server community "public" Operator`
_SNMP_COMMUNITY_LINE_RE = re.compile(
    r'^snmp-server\s+community\s+"?([^"\s]+)"?', re.IGNORECASE,
)
_SNMP_LOCATION_RE = re.compile(
    r'^snmp-server\s+location\s+(.+)$', re.IGNORECASE,
)
_SNMP_CONTACT_RE = re.compile(
    r'^snmp-server\s+contact\s+(.+)$', re.IGNORECASE,
)
# SNMPv3 user grammar on Aruba AOS-S (observed on 2930F/3810M/6300):
#
#   snmpv3 user "<name>" auth {md5|sha} "<pass>" priv {des|aes} "<pass>"
#   snmpv3 group "<group>" user "<name>" sec-model ver3
#
# The grammar uses an `snmpv3` keyword (not `snmp-server`) and
# quotes the user + passphrase tokens.  Auth/priv clauses both
# optional — noAuthNoPriv expressible.  The group binding is on a
# separate line; parser collects both lines and merges.
_SNMPV3_USER_RE = re.compile(
    r'^snmpv3\s+user\s+"?([^"\s]+)"?'
    r'(?:\s+auth\s+(md5|sha|sha256)\s+"?([^"\s]+)"?)?'
    r'(?:\s+priv\s+(des|aes|aes128|aes192|aes256)\s+"?([^"\s]+)"?)?'
    r'\s*$',
    re.IGNORECASE,
)
_SNMPV3_GROUP_BIND_RE = re.compile(
    r'^snmpv3\s+group\s+"?([^"\s]+)"?\s+user\s+"?([^"\s]+)"?'
    r'\s+sec-model\s+ver3\s*$',
    re.IGNORECASE,
)
_SNMP_HOST_RE = re.compile(
    r'^snmp-server\s+host\s+(\d+\.\d+\.\d+\.\d+)', re.IGNORECASE,
)
_DNS_SERVER_RE = re.compile(
    r"^ip\s+dns\s+server-address\s+priority\s+\d+\s+(\S+)",
    re.IGNORECASE,
)
_SNTP_SERVER_RE = re.compile(
    r"^sntp\s+server\s+priority\s+\d+\s+(\S+)", re.IGNORECASE,
)
_DEFAULT_GW_RE = re.compile(
    r"^ip\s+default-gateway\s+(\d+\.\d+\.\d+\.\d+)", re.IGNORECASE,
)
_IP_ROUTE_RE = re.compile(
    # Two accepted Aruba forms (regex handles both via optional gw):
    #   ip route DEST/PREFIX GATEWAY
    #   ip route DEST MASK GATEWAY
    # Group 1: destination (bare IP or CIDR).  Group 2: optional
    # dotted-decimal mask (legacy form).  Group 3: gateway IP.  When
    # group 2 is present, group 1 is a bare IP and the mask drives
    # the canonical prefix length; when absent, group 1 is CIDR.
    r"^ip\s+route\s+(\S+)"
    r"(?:\s+(\d+\.\d+\.\d+\.\d+))?"
    r"\s+(\d+\.\d+\.\d+\.\d+)\s*$",
    re.IGNORECASE,
)
_VLAN_HEADER_RE = re.compile(r"^vlan\s+(\d+)\s*$", re.IGNORECASE)
# ``trunk <port-list> <name> <type>`` — AOS-S link-aggregation form.
# Examples:
#   trunk 1-4 trk1 lacp
#   trunk A1,A2 trk2 trunk
#   trunk 25,26 trk3 dt-lacp
# Types: lacp (802.3ad), trunk (static/manual), fec (HP-proprietary),
# dt-lacp (distributed-trunk LACP).
_TRUNK_LINE_RE = re.compile(
    r"^trunk\s+(\S+)\s+(\S+)\s+(\S+)\s*$", re.IGNORECASE,
)
# ``password manager user-name "admin" sha1 "8db..."``
# Real AOS-S output always quotes both the name and the hash; sha1 is
# the modern algorithm (legacy "plaintext" form is also accepted by
# the parser for backward compatibility but rarely seen).
_PASSWORD_LINE_RE = re.compile(
    r'^password\s+(manager|operator)\s+user-name\s+"([^"]+)"\s+'
    r'(\S+)\s+"([^"]+)"\s*$',
    re.IGNORECASE,
)
# Continuation-line variant: when the operator pastes a config
# whose terminal wrapped the long sha1 hash onto the next line,
# the first line ends with the algorithm token but no quoted hash:
#
#   password manager user-name "admin" sha1
#    "deadbeef0000000000000000000000000000dead"
#
# This regex matches the algorithm-only head line; the loop in
# parse() then peeks the next non-blank line for the trailing
# quoted hash.  Without this fallback the user's copy-paste from
# `show running-config` silently drops the local-user record.
_PASSWORD_HEAD_RE = re.compile(
    r'^password\s+(manager|operator)\s+user-name\s+"([^"]+)"\s+'
    r'(\S+)\s*$',
    re.IGNORECASE,
)
_PASSWORD_HASH_CONTINUATION_RE = re.compile(
    r'^\s*"([^"]+)"\s*$',
)
# AOS-S RADIUS forms (16.10 Access Security Guide):
#   radius-server host <ip>
#   radius-server host <ip> key "<secret>"
#   radius-server host <ip> auth-port <N> acct-port <N>
#   radius-server host <ip> auth-port <N> acct-port <N> key "<secret>"
# Each repeated ``radius-server host <ip>`` line refines the same
# entry on the device (cumulative-update grammar) — the parser
# captures host first, then folds optional port / key clauses into
# the matching record so a key on one line + ports on another
# round-trip onto a single CanonicalRADIUSServer.
_RADIUS_HOST_RE = re.compile(
    r'^radius-server\s+host\s+(\d+\.\d+\.\d+\.\d+)'
    r'(?:\s+(.*))?'
    r'\s*$',
    re.IGNORECASE,
)
_RADIUS_AUTH_PORT_RE = re.compile(r'\bauth-port\s+(\d+)', re.IGNORECASE)
_RADIUS_ACCT_PORT_RE = re.compile(r'\bacct-port\s+(\d+)', re.IGNORECASE)
_RADIUS_INLINE_KEY_RE = re.compile(
    r'\bkey\s+"?([^"]*)"?\s*$',
    re.IGNORECASE,
)
# Global shared-secret fallback (applies to hosts without inline key):
#   radius-server key "<secret>"
_RADIUS_KEY_GLOBAL_RE = re.compile(
    r'^radius-server\s+key\s+"?([^"]*)"?\s*$',
    re.IGNORECASE,
)
_AOS_TRUNK_TYPE_TO_MODE = {
    "lacp": "active",
    "dt-lacp": "active",
    "trunk": "static",
    "fec": "static",
}
# Interface header regex.
#
# AOS-S native port-name forms in the real-capture corpus include:
#   * bare numeric: ``1``, ``25``, ``42``
#   * letter-prefix uplink: ``A1``, ``B2``
#   * stacked slot/port: ``1/1``, ``2/24``
#   * stacked letter-uplink: ``1/A1``
#   * trunk aliases: ``Trk1``, ``Trk10``
#
# In addition, the parser is exercised cross-vendor by Phase 4
# bidirectionality fixtures: a JunOS, IOS-XE, or Cisco-CLI capture
# fed through detection may end up in this codec when the device
# class disagrees with the wire format.  Earlier the regex demanded
# at most one ``/`` segment, a mandatory trailing digit, and no
# hyphen / dot — which silently dropped legitimate cross-vendor
# names like ``ge-0/0/1``, ``ge-0/0/1.100``, ``irb``, ``irb.100``,
# ``GigabitEthernet0/0/0``, ``TenGigabitEthernet1/0/1``,
# ``Port-channel1``, ``Port-Channel10``.  See Phase 4 finding 1 in
# ``tests/fixtures/real/phase4_findings_juniper_junos.md`` (~40
# affected cells) and the rank-1 row in
# ``tests/fixtures/real/PHASE4_RECONCILIATION.md``.
#
# The widened pattern accepts any token starting with an
# alphanumeric followed by alphanumerics, ``.``, ``/``, or ``-``.
# Underscore is intentionally excluded — AOS-S does not use it.
#
# Follow-up: ``_parse_port_list`` / ``_expand_port_range`` below
# split tokens containing ``-`` as ranges.  If a future cross-vendor
# capture surfaces a hyphenated name inside a ``vlan ... untagged
# <list>`` directive (e.g. ``untagged Port-channel1``) it would be
# shredded into ``["Port", "channel1"]``.  This regex fix does not
# address that path; the port-list expansion remains numeric-/
# letter-uplink-shaped per AOS-S native forms.
_IFACE_HEADER_RE = re.compile(
    r'^interface\s+("?[A-Za-z0-9][A-Za-z0-9./\-]*"?)\s*$', re.IGNORECASE,
)

_VLAN_NAME_RE = re.compile(r'^name\s+"?([^"\n]+)"?', re.IGNORECASE)
_UNTAGGED_RE = re.compile(r"^(no\s+)?untagged\s+(.+)$", re.IGNORECASE)
_TAGGED_RE = re.compile(r"^(no\s+)?tagged\s+(.+)$", re.IGNORECASE)
_IP_ADDR_CIDR_RE = re.compile(
    r"^ip\s+address\s+(\d+\.\d+\.\d+\.\d+)/(\d+)$", re.IGNORECASE,
)
_IP_ADDR_MASK_RE = re.compile(
    r"^ip\s+address\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)$",
    re.IGNORECASE,
)
# GAP-EVPN-3: AOS-S `ipv6 address <addr>/<prefix> [link-local]`.
# Real-capture corpus also carries `ipv6 address dhcp full`
# (stateless DHCPv6) which has no static address and is parse-
# and-ignore — the regex below intentionally requires a colon-
# hex address with a prefix length to drop the dhcp form.
_IPV6_ADDR_RE = re.compile(
    r"^ipv6\s+address\s+([0-9A-Fa-f:]+)/(\d+)(?:\s+(link-local))?\s*$",
    re.IGNORECASE,
)
_IFACE_NAME_RE = re.compile(r'^name\s+"?([^"\n]+)"?', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _unquote(s: str) -> str:
    """Strip surrounding ASCII quotes if present."""
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


def _mask_to_prefix(mask: str) -> int:
    """Convert dotted-decimal mask to CIDR prefix length."""
    try:
        addr = ipaddress.IPv4Address(mask)
    except ipaddress.AddressValueError:
        raise ParseError(
            f"aruba_aoss: invalid subnet mask {mask!r}",
            snippet=mask,
        )
    bits = bin(int(addr))[2:]
    if "01" in bits:
        raise ParseError(
            f"aruba_aoss: non-contiguous subnet mask {mask!r}",
            snippet=mask,
        )
    return bits.count("1")


def _dest_to_cidr(dest: str) -> str:
    """Accept either ``A.B.C.D/N`` or just ``A.B.C.D``; default /32."""
    if "/" in dest:
        return dest
    return dest + "/32"


#: AOS-S native port-shape recogniser — used to gate range-expansion
#: when the token contains ``-``.  AOS-S native port names have one
#: of these shapes (see :mod:`.port_names` ``classify_port_name``):
#:   * bare digits             -- ``24``        standalone
#:   * stack/port              -- ``1/24``      stacked plain
#:   * stack/letter+digits     -- ``1/A1``      stacked letter-slot
#:   * letter+digits           -- ``A1``        letter-prefix uplink
#:   * trunk                   -- ``Trk1``      LAG (case-insensitive)
#: Foreign port names from cross-vendor renders (Junos ``xe-0/0/0``,
#: Cisco ``GigabitEthernet1/0/1``, Arista ``Ethernet1``) take other
#: shapes and must NOT be range-expanded — see commit fixing
#: ``tagged xe-0/0/0,xe-0/0/2`` getting shredded into
#: ``["xe", "0/0/0", "0/0/2"]`` on parse-back.
_AOS_PORT_SHAPE_RE = re.compile(
    r"^(?:[Tt]rk\d+|\d+(?:/[A-Za-z]?\d+)?|[A-Za-z]\d+)$",
)


def _parse_port_list(text: str) -> list[str]:
    """Expand AOS-S port-list syntax into individual port names.

    Handles ``1-24``, ``1,3,5``, ``A1-A4``, ``1,3-5,A1``.
    Preserves order; de-duplicates.

    Range-expansion is gated on the lo/hi halves both matching an
    AOS-S native port shape (:data:`_AOS_PORT_SHAPE_RE`).  This keeps
    foreign-vendor port names that contain hyphens (Junos
    ``xe-0/0/0``, Cisco breakout ``Hu1/0/1.1`` style) intact when
    they appear in a cross-vendor round-trip — the round-trip
    renderer emits them comma-joined, and AOS-S range syntax never
    legitimately produces a token whose lo half is a non-numeric
    bare-letter prefix like ``xe``.  Pre-fix, the parser shredded
    ``xe-0/0/0`` into ``["xe", "0/0/0"]`` because ``-`` was treated
    as a range delimiter unconditionally; this broke
    ``vlans[].tagged_ports`` and ``lags[].members`` round-trip on
    every Junos-source -> Aruba-target cell in the Phase 4 mesh.
    """
    result: list[str] = []
    seen: set[str] = set()
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            lo, hi = token.split("-", 1)
            lo, hi = lo.strip(), hi.strip()
            # Only treat as a range if BOTH endpoints match the
            # AOS-S native port-shape grammar.  Foreign-vendor names
            # like ``xe-0/0/0`` have an alpha lo half that doesn't
            # match the shape regex, so they fall through to the
            # single-token branch and survive round-trip intact.
            if _AOS_PORT_SHAPE_RE.match(lo) and _AOS_PORT_SHAPE_RE.match(hi):
                expanded = _expand_port_range(lo, hi)
                for p in expanded:
                    if p not in seen:
                        seen.add(p)
                        result.append(p)
                continue
            # Not a range — treat the whole token as a single port name.
            if token not in seen:
                seen.add(token)
                result.append(token)
        else:
            if token not in seen:
                seen.add(token)
                result.append(token)
    return result


def _expand_port_range(lo: str, hi: str) -> list[str]:
    """Expand an AOS-S port range into individual port names.

    Handles every real-world AOS-S port-naming form surfaced by the
    real-capture corpus:

      * ``1-24``        — pure numeric (2920, 2930F standalone)
      * ``A1-A4``       — letter-prefix uplinks (same-member letter slot)
      * ``1/1-1/24``    — stacked switch, member/port (2930M + 3810M stacks)
      * ``1/A1-1/A4``   — stacked switch, member/letter-port (uplink module
                          on a stack member)
      * ``2/1-2/48``    — second stack member

    Trailing digits vary; everything else must match between lo and
    hi.  Pre-:commit: WC.16.11.0025 2930M fixture landing, the old
    regex ``^([A-Za-z]*)(\\d+)(?:/(\\d+))?$`` silently dropped the
    slot prefix when expanding ``1/1-1/47`` (produced ``["1"]``) and
    failed to match ``1/A1-1/A4`` at all (returned the two endpoints
    verbatim, losing intermediate ports).  Both bugs had slipped
    past the round-trip-stable invariant because the format path
    was symmetrically broken.  Symptomatic VLANs in several shipped
    Aruba fixtures had near-empty port-membership lists on parse;
    the canonical coverage was materially under-reported.
    """
    m_lo = re.match(r"^(.*?)(\d+)$", lo)
    m_hi = re.match(r"^(.*?)(\d+)$", hi)
    if not m_lo or not m_hi:
        return [lo, hi]   # no trailing digits — pass through as-is
    prefix_lo, num_lo = m_lo.group(1), int(m_lo.group(2))
    prefix_hi, num_hi = m_hi.group(1), int(m_hi.group(2))
    if prefix_lo != prefix_hi or num_hi < num_lo:
        return [lo, hi]
    return [f"{prefix_lo}{n}" for n in range(num_lo, num_hi + 1)]


def _build_lag_from_trunk_line(m: re.Match[str]) -> CanonicalLAG | None:
    """Convert a ``trunk <ports> <name> <type>`` regex match to a CanonicalLAG."""
    port_list_text, trunk_name, trunk_type = m.group(1), m.group(2), m.group(3)
    members = _parse_port_list(port_list_text)
    mode = _AOS_TRUNK_TYPE_TO_MODE.get(trunk_type.lower(), "static")
    return CanonicalLAG(
        name=trunk_name,
        members=members,
        mode=mode,
    )


def _infer_iface_type(name: str) -> str:
    """Best-effort IANA ifType from the port name."""
    lower = name.lower()
    if lower.startswith("trk"):
        return "ianaift:ieee8023adLag"
    if lower.startswith("vlan"):
        return "ianaift:l3ipvlan"
    return "ianaift:ethernetCsmacd"


# ---------------------------------------------------------------------------
# Stanza parsers
# ---------------------------------------------------------------------------


def _parse_vlan_stanza(
    lines: list[str], start: int, vlan_id: int,
) -> tuple[CanonicalVlan, int]:
    """Parse a ``vlan N`` stanza starting at *start* (body line).

    Returns the parsed :class:`CanonicalVlan` and the index of the
    first line AFTER the stanza's ``exit``.
    """
    vlan = CanonicalVlan(id=vlan_id)
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith(";"):
            i += 1
            continue
        # Stanza terminates at `exit` or the next un-indented line.
        if stripped == "exit":
            i += 1
            break
        if not line[0].isspace():
            break

        nm = _VLAN_NAME_RE.match(stripped)
        if nm:
            vlan.name = _unquote(nm.group(1))
            i += 1
            continue

        um = _UNTAGGED_RE.match(stripped)
        if um:
            if um.group(1):  # "no untagged ..." — strip ports
                to_remove = set(_parse_port_list(um.group(2)))
                vlan.untagged_ports = [
                    p for p in vlan.untagged_ports if p not in to_remove
                ]
            else:
                vlan.untagged_ports.extend(_parse_port_list(um.group(2)))
            i += 1
            continue

        tm = _TAGGED_RE.match(stripped)
        if tm:
            if tm.group(1):  # "no tagged ..."
                to_remove = set(_parse_port_list(tm.group(2)))
                vlan.tagged_ports = [
                    p for p in vlan.tagged_ports if p not in to_remove
                ]
            else:
                vlan.tagged_ports.extend(_parse_port_list(tm.group(2)))
            i += 1
            continue

        ip_cidr = _IP_ADDR_CIDR_RE.match(stripped)
        if ip_cidr:
            vlan.ipv4_addresses.append(CanonicalIPv4Address(
                ip=ip_cidr.group(1),
                prefix_length=int(ip_cidr.group(2)),
            ))
            i += 1
            continue

        ip_mask = _IP_ADDR_MASK_RE.match(stripped)
        if ip_mask:
            vlan.ipv4_addresses.append(CanonicalIPv4Address(
                ip=ip_mask.group(1),
                prefix_length=_mask_to_prefix(ip_mask.group(2)),
            ))
            i += 1
            continue

        # GAP-EVPN-3: IPv6 address.  CanonicalVlan does not carry an
        # ipv6_addresses list today (the SVI-on-VLAN model is IPv4-
        # only), so we skip the line.  Static IPv6 addresses inside
        # `vlan <N>` stanzas are rare on AOS-S in practice; if they
        # appear in a future fixture corpus we extend CanonicalVlan
        # at that point.
        if _IPV6_ADDR_RE.match(stripped):
            i += 1
            continue

        i += 1
    return vlan, i


def _parse_interface_stanza(
    lines: list[str], start: int, iface_name: str,
) -> tuple[CanonicalInterface, int]:
    """Parse an ``interface X`` stanza starting at *start*.

    Returns the parsed :class:`CanonicalInterface` and the index of
    the first line AFTER the stanza's ``exit``.
    """
    iface = CanonicalInterface(
        name=iface_name,
        enabled=True,
        interface_type=_infer_iface_type(iface_name),
    )
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith(";"):
            i += 1
            continue
        if stripped == "exit":
            i += 1
            break
        if not line[0].isspace():
            break

        nm = _IFACE_NAME_RE.match(stripped)
        if nm:
            iface.description = _unquote(nm.group(1))
            i += 1
            continue

        if stripped == "enable":
            iface.enabled = True
            i += 1
            continue

        if stripped == "disable":
            iface.enabled = False
            i += 1
            continue

        ip_cidr = _IP_ADDR_CIDR_RE.match(stripped)
        if ip_cidr:
            iface.ipv4_addresses.append(CanonicalIPv4Address(
                ip=ip_cidr.group(1),
                prefix_length=int(ip_cidr.group(2)),
            ))
            i += 1
            continue

        ip_mask = _IP_ADDR_MASK_RE.match(stripped)
        if ip_mask:
            iface.ipv4_addresses.append(CanonicalIPv4Address(
                ip=ip_mask.group(1),
                prefix_length=_mask_to_prefix(ip_mask.group(2)),
            ))
            i += 1
            continue

        # GAP-EVPN-3: IPv6 address.  AOS-S form is `ipv6 address
        # <addr>/<prefix> [link-local]`.  `ipv6 address dhcp full`
        # (stateless DHCPv6) does not match the regex (no slash) and
        # falls through silently — that's the desired behaviour since
        # there's no static address to capture.
        v6m = _IPV6_ADDR_RE.match(stripped)
        if v6m:
            scope = "link-local" if v6m.group(3) else "global"
            try:
                iface.ipv6_addresses.append(CanonicalIPv6Address(
                    ip=v6m.group(1),
                    prefix_length=int(v6m.group(2)),
                    scope=scope,
                ))
            except ValueError:
                pass
            i += 1
            continue

        # `routing` keyword toggles L3 mode — informational since we
        # infer from the presence of `ip address`.
        i += 1
    return iface, i


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse AOS-S ``show running-config`` text into a
    :class:`CanonicalIntent`."""
    if not raw.strip():
        raise ParseError(
            "aruba_aoss: empty input",
            snippet="",
        )
    # Shape sanity — Round-4.2 shared helper tolerates leading
    # shell-echo / banner framing on real captures.
    shape = detect_input_shape(raw)
    if shape == "xml":
        raise ParseError(
            "aruba_aoss: input looks like XML, not AOS-S CLI.",
            snippet=raw.lstrip()[:120],
        )
    if shape == "json":
        raise ParseError(
            "aruba_aoss: input looks like JSON, not AOS-S CLI.",
            snippet=raw.lstrip()[:120],
        )

    intent = CanonicalIntent(
        source_vendor="aruba_aoss",
        source_format="cli-aruba-aoss",
    )

    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped_line = line.strip()

        # Skip comments (AOS-S uses ';') and blank lines.
        if not stripped_line or stripped_line.startswith(";"):
            i += 1
            continue

        # Top-level lines start in column 0.
        if line[0].isspace():
            i += 1
            continue

        hm = _HOSTNAME_RE.match(stripped_line)
        if hm:
            intent.hostname = _unquote(hm.group(1))
            i += 1
            continue

        comm = _SNMP_COMMUNITY_LINE_RE.match(stripped_line)
        if comm:
            if intent.snmp is None:
                intent.snmp = CanonicalSNMP()
            if not intent.snmp.community:
                intent.snmp.community = comm.group(1)
            i += 1
            continue

        loc = _SNMP_LOCATION_RE.match(stripped_line)
        if loc:
            if intent.snmp is None:
                intent.snmp = CanonicalSNMP()
            intent.snmp.location = loc.group(1).strip().strip('"')
            i += 1
            continue

        contact = _SNMP_CONTACT_RE.match(stripped_line)
        if contact:
            if intent.snmp is None:
                intent.snmp = CanonicalSNMP()
            intent.snmp.contact = contact.group(1).strip().strip('"')
            i += 1
            continue

        snmp_host = _SNMP_HOST_RE.match(stripped_line)
        if snmp_host:
            if intent.snmp is None:
                intent.snmp = CanonicalSNMP()
            intent.snmp.trap_hosts.append(snmp_host.group(1))
            i += 1
            continue

        # SNMPv3 user line: ``snmpv3 user "<name>" auth <p> "<k>"
        # priv <p> "<k>"``.  Group binding comes on a separate
        # ``snmpv3 group`` line — order agnostic.  If a group
        # binding processed earlier created a stub record for
        # this name, we merge instead of appending.
        v3u = _SNMPV3_USER_RE.match(stripped_line)
        if v3u:
            if intent.snmp is None:
                intent.snmp = CanonicalSNMP()
            name, auth_p, auth_pw, priv_p, priv_pw = v3u.groups()
            priv_norm = ""
            if priv_p:
                pl = priv_p.lower()
                priv_norm = "aes128" if pl == "aes" else pl
            existing = next(
                (u for u in intent.snmp.v3_users if u.name == name),
                None,
            )
            if existing is not None:
                existing.auth_protocol = (auth_p or "").lower()
                existing.auth_passphrase = auth_pw or ""
                existing.priv_protocol = priv_norm
                existing.priv_passphrase = priv_pw or ""
            else:
                intent.snmp.v3_users.append(CanonicalSNMPv3User(
                    name=name,
                    auth_protocol=(auth_p or "").lower(),
                    auth_passphrase=auth_pw or "",
                    priv_protocol=priv_norm,
                    priv_passphrase=priv_pw or "",
                ))
            i += 1
            continue

        # SNMPv3 group binding — attach the group to the matching
        # user record.  Order-agnostic: group lines may appear
        # before or after the user declaration in real configs.
        v3g = _SNMPV3_GROUP_BIND_RE.match(stripped_line)
        if v3g:
            if intent.snmp is None:
                intent.snmp = CanonicalSNMP()
            group_name, user_name = v3g.groups()
            found = False
            for u in intent.snmp.v3_users:
                if u.name == user_name:
                    u.group = group_name
                    found = True
                    break
            if not found:
                # Group declared for user we haven't seen yet —
                # create a stub; later ``snmpv3 user`` merges.
                intent.snmp.v3_users.append(CanonicalSNMPv3User(
                    name=user_name,
                    group=group_name,
                ))
            i += 1
            continue

        dns = _DNS_SERVER_RE.match(stripped_line)
        if dns:
            intent.dns_servers.append(dns.group(1))
            i += 1
            continue

        ntp = _SNTP_SERVER_RE.match(stripped_line)
        if ntp:
            intent.ntp_servers.append(ntp.group(1))
            i += 1
            continue

        gw = _DEFAULT_GW_RE.match(stripped_line)
        if gw:
            intent.static_routes.append(CanonicalStaticRoute(
                destination="0.0.0.0/0",
                gateway=gw.group(1),
            ))
            i += 1
            continue

        rt = _IP_ROUTE_RE.match(stripped_line)
        if rt:
            # Three-form parse: see _IP_ROUTE_RE above.  Group 2
            # is the OPTIONAL dotted-decimal mask (legacy Aruba
            # form).  When present we expand to CIDR via the
            # mask's prefix length; when absent the destination
            # was already CIDR (or a bare IP defaulting to /32).
            dest, mask, gateway = rt.group(1), rt.group(2), rt.group(3)
            if mask is not None:
                try:
                    prefix = _mask_to_prefix(mask)
                except Exception:
                    # Non-contiguous mask — unusual; fall back to
                    # /32 host-route semantic so render still
                    # produces something parseable.
                    prefix = 32
                canonical_dest = f"{dest}/{prefix}"
            else:
                canonical_dest = _dest_to_cidr(dest)
            intent.static_routes.append(CanonicalStaticRoute(
                destination=canonical_dest,
                gateway=gateway,
            ))
            i += 1
            continue

        rad = _RADIUS_HOST_RE.match(stripped_line)
        if rad:
            # AOS-S can emit any of:
            #   radius-server host 10.0.0.4
            #   radius-server host 10.0.0.4 key "secret"
            #   radius-server host 10.0.0.4 auth-port 1812 acct-port 1813
            #   radius-server host 10.0.0.4 auth-port 1812 acct-port 1813
            #     key "secret"
            # In the keyless form the shared secret lives on a
            # separate ``radius-server key`` line that applies
            # globally — we capture that into a local, then
            # backfill hostless servers after the parse loop.
            # Repeated ``radius-server host <ip>`` lines refine
            # the same entry (cumulative-update grammar): the
            # parser folds port / key clauses onto the existing
            # record rather than creating duplicates.
            host = rad.group(1)
            rest = rad.group(2) or ""
            auth_port = None
            acct_port = None
            key = ""
            ap = _RADIUS_AUTH_PORT_RE.search(rest)
            if ap:
                try:
                    auth_port = int(ap.group(1))
                except ValueError:
                    pass
            cp = _RADIUS_ACCT_PORT_RE.search(rest)
            if cp:
                try:
                    acct_port = int(cp.group(1))
                except ValueError:
                    pass
            km = _RADIUS_INLINE_KEY_RE.search(rest)
            if km:
                key = km.group(1).strip().strip('"')
            existing = next(
                (s for s in intent.radius_servers if s.host == host),
                None,
            )
            if existing is None:
                intent.radius_servers.append(CanonicalRADIUSServer(
                    host=host,
                    key=key,
                    auth_port=auth_port if auth_port is not None else 1812,
                    acct_port=acct_port if acct_port is not None else 1813,
                ))
            else:
                if key and not existing.key:
                    existing.key = key
                if auth_port is not None:
                    existing.auth_port = auth_port
                if acct_port is not None:
                    existing.acct_port = acct_port
            i += 1
            continue

        rk = _RADIUS_KEY_GLOBAL_RE.match(stripped_line)
        if rk:
            # Global-scope key — apply to any RADIUS server that
            # didn't carry its own inline key.
            global_key = rk.group(1).strip().strip('"')
            for server in intent.radius_servers:
                if not server.key:
                    server.key = global_key
            i += 1
            continue

        pwd = _PASSWORD_LINE_RE.match(stripped_line)
        if pwd:
            role = pwd.group(1).lower()
            name = pwd.group(2)
            hash_alg = pwd.group(3).lower()
            hash_val = pwd.group(4)
            # Stash hash-alg prefix on the hash so render can
            # reconstruct the `password <role> user-name "X" <alg> "<h>"`
            # form.  Non-standard algorithms fall through verbatim.
            intent.local_users.append(CanonicalLocalUser(
                name=name,
                privilege_level=15 if role == "manager" else 1,
                hashed_password=f"{hash_alg}:{hash_val}",
                role=role,
            ))
            i += 1
            continue

        # Continuation-line fallback for terminal-wrapped pastes
        # where the long sha1 hash landed on the line AFTER the
        # ``password ... <alg>`` head.  Look for an algorithm-
        # only head line, then peek the next non-blank line for
        # the trailing quoted hash; consume both lines on match.
        head = _PASSWORD_HEAD_RE.match(stripped_line)
        if head:
            role = head.group(1).lower()
            name = head.group(2)
            hash_alg = head.group(3).lower()
            # Look ahead for the continuation line carrying the
            # quoted hash.  Tolerate a single blank line between
            # head and continuation in case the operator's paste
            # introduced one.
            cont_idx = i + 1
            while cont_idx < len(lines) and not lines[cont_idx].strip():
                cont_idx += 1
            if cont_idx < len(lines):
                cont = _PASSWORD_HASH_CONTINUATION_RE.match(lines[cont_idx])
                if cont:
                    intent.local_users.append(CanonicalLocalUser(
                        name=name,
                        privilege_level=15 if role == "manager" else 1,
                        hashed_password=f"{hash_alg}:{cont.group(1)}",
                        role=role,
                    ))
                    i = cont_idx + 1
                    continue
            # Head matched but no continuation found — emit a
            # user record without a hash so the operator at least
            # sees the username appearing in the rename pane.
            intent.local_users.append(CanonicalLocalUser(
                name=name,
                privilege_level=15 if role == "manager" else 1,
                hashed_password=f"{hash_alg}:",
                role=role,
            ))
            i += 1
            continue

        tk = _TRUNK_LINE_RE.match(stripped_line)
        if tk:
            lag = _build_lag_from_trunk_line(tk)
            if lag is not None:
                intent.lags.append(lag)
                # Reverse-link each member to this LAG so the
                # canonical tree stays consistent.
                iface_by_name = {i.name: i for i in intent.interfaces}
                for member in lag.members:
                    m_iface = iface_by_name.get(member)
                    if m_iface is not None and m_iface.lag_member_of is None:
                        m_iface.lag_member_of = lag.name
            i += 1
            continue

        vm = _VLAN_HEADER_RE.match(stripped_line)
        if vm:
            vlan_id = int(vm.group(1))
            vlan, next_i = _parse_vlan_stanza(lines, i + 1, vlan_id)
            # Aruba AOS-S VLAN reassignment semantic: when a port
            # is added to a later VLAN's ``untagged`` list, it is
            # *moved* from any earlier VLAN's ``untagged`` list.
            # The VLAN-1 (DEFAULT_VLAN) stanza may claim every
            # port via ``untagged 1/1-1/24`` while subsequent VLAN
            # stanzas reassign sub-ranges of those same ports
            # (``vlan 20 / untagged 1/1-1/12``).  Without override
            # semantics the parser collects both memberships and
            # cross-vendor renderers (Junos / Arista) silently
            # drop the more-specific assignment because their
            # access-port semantic is single-VLAN-per-port.  HPE
            # Aruba 2930F config guide ("Configuring VLANs / VLAN
            # port assignments") confirms move-on-reassign as the
            # canonical AOS-Switch behaviour.
            if vlan.untagged_ports:
                claimed = set(vlan.untagged_ports)
                for prior_vlan in intent.vlans:
                    if not prior_vlan.untagged_ports:
                        continue
                    prior_vlan.untagged_ports = [
                        p for p in prior_vlan.untagged_ports
                        if p not in claimed
                    ]
            intent.vlans.append(vlan)
            # SVI absorption — codepath 1 of 3.  See
            # ._svi_absorption for the full rule.  AOS-S packs
            # the SVI L3 inside the `vlan` stanza; we promote it
            # to a canonical ``Vlan<N>`` CanonicalInterface here
            # so downstream consumers (and renderers of *other*
            # vendors that DO use ``interface Vlan<N>``) see the
            # L3 record at the canonical location.
            if vlan.ipv4_addresses:
                intent.interfaces.append(CanonicalInterface(
                    name=f"Vlan{vlan_id}",
                    description=vlan.name,
                    enabled=True,
                    interface_type="ianaift:l3ipvlan",
                    ipv4_addresses=list(vlan.ipv4_addresses),
                ))
            i = next_i
            continue

        im = _IFACE_HEADER_RE.match(stripped_line)
        if im:
            iface_name = im.group(1).strip('"')
            iface, next_i = _parse_interface_stanza(lines, i + 1, iface_name)
            intent.interfaces.append(iface)
            i = next_i
            continue

        # Unrecognised top-level line — skip.
        i += 1

    # LAG-member linkage post-pass.  The inline linking at the
    # ``trunk`` line above only catches members whose
    # ``interface <name>`` stanzas appeared EARLIER in the
    # source text.  AOS-S's native export orders interfaces
    # before trunks so the inline path works for same-vendor
    # round-trip on device-captured configs.  Our own renderer
    # (and some cross-vendor source orderings) emit trunks
    # first, so we re-link exhaustively here once both lists
    # are fully populated.  Idempotent — skip members that
    # already carry a linkage.
    iface_by_name = {i.name: i for i in intent.interfaces}
    for lag in intent.lags:
        for member in lag.members:
            m_iface = iface_by_name.get(member)
            if m_iface is not None and m_iface.lag_member_of is None:
                m_iface.lag_member_of = lag.name

    # Bug 3 transpose: mirror any per-port switchport state into the
    # VLAN-centric tagged_ports / untagged_ports lists.  AOS-S source
    # is natively VLAN-centric so this is normally a no-op against
    # native captures, but cross-vendor parses that arrive here with
    # per-iface switchport_mode / access_vlan / trunk_allowed_vlans
    # populated (e.g. via shared post-passes) need the projection so
    # round-trip stability is preserved.  See translator-plans.txt BUG 3.
    from ...canonical.transforms import (
        project_switchport_to_vlan,
        project_vlan_to_switchport,
    )
    project_switchport_to_vlan(intent)
    # Inverse projection: AOS-S native source is VLAN-centric — its
    # ``vlan N { tagged <ports> }`` stanzas carry the membership and
    # the per-iface stanzas have NO ``switchport_mode`` /
    # ``trunk_allowed_vlans`` lines.  Without this mirror, any cell
    # that exits Aruba parse with a VLAN-centric tree leaves
    # ``interfaces[].switchport_mode`` and ``trunk_allowed_vlans``
    # blank, so a Phase-4 source -> aruba_aoss -> reparse round-trip
    # loses the per-iface switchport view that the source codec
    # populated upstream.  Synthesise=False because Aruba's iface
    # stanza listing IS the canonical port list — we don't want to
    # add phantom ifaces from VLAN port-lists alone.
    project_vlan_to_switchport(intent, synthesise_missing=False)

    logger.debug(
        "aruba_aoss parsed: hostname=%r ifaces=%d vlans=%d "
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
