"""
Parse path for Cisco NX-OS (``show running-config`` form).

Public function: :func:`parse_intent` — raw text in,
:class:`CanonicalIntent` out.  Targets the Nexus 3000 / 5000 / 7000 /
9000 series on NX-OS 9.x / 10.x.

Note: probe is in :mod:`.codec`; this module assumes input has already
been classified as Cisco NX-OS CLI.

Phase 1 surface (see ``docs/v0.2.0-planning/03-nxos-codec/``):

* ``hostname <name>`` → :attr:`CanonicalIntent.hostname`.
* ``version <N.N(N)> Bios:version`` → :attr:`CanonicalIntent.source_version`
  (echoed on same-vendor render, #297; a fresh banner otherwise).
* ``vrf context <name>`` (top-level) → :class:`CanonicalRoutingInstance`
  (name + description + ``rd`` + ``route-target import/export/both``;
  nested per-VRF ``ip route`` → :class:`CanonicalStaticRoute` with
  ``vrf=<name>``).  ``vni`` (L3VNI) is Phase 4 and parse-and-ignore here.
* ``interface <name>`` blocks → :class:`CanonicalInterface` carrying
  ``description`` / ``shutdown`` / ``mtu`` / ``ip address X/N`` (CIDR) /
  ``ipv6 address X/N`` / ``vrf member <name>``.
* top-level ``vlan <id-list>`` (comma + range form) and ``vlan N / name
  <text>`` → :class:`CanonicalVlan`, plus SVI synthesis.
* top-level ``ip route <dest>/<prefix> <gw> [<pref>]`` (default VRF only)
  → :class:`CanonicalStaticRoute`.

Phases 2-4 add: L2 switchport, LAGs, SNMP, local users, HSRP, VRF
RD/RT + per-VRF static routes, VXLAN-EVPN (``vlan N / vn-segment``
+ ``interface nve1`` VTEP source-interface + per-VRF L3VNI ``vrf
context X / vni N``), and IPv4 Distributed Anycast Gateway (per-SVI
``fabric forwarding mode anycast-gateway`` → ``virtual_gateway_address``
+ the chassis-wide ``fabric forwarding anycast-gateway-mac``).  Still
declared ``unsupported``: the IPv6 anycast companion plus the Tier-3
protocol / ACL / QoS blocks.  ``feature`` / ``vdc``
/ ``boot`` / ``line`` lines are discarded on parse and re-synthesised on
render (the matrix declares the cosmetic loss).

Where this codec diverges from ``cisco_iosxe_cli`` (see
``02-codec-architecture.md`` § 14):

* IP addresses are **CIDR only** (``ip address X/N``), never dotted mask.
* VRF stanza keyword is ``vrf context`` (not ``vrf definition``).
* Per-interface VRF bind is ``vrf member`` (not ``vrf forwarding``).
* Physical ports are uniform ``Ethernet<slot>/<port>`` — no speed prefix.
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
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVRRPGroup,
    CanonicalVxlan,
)
from .._helpers import (
    _is_link_local_v6,
    _normalise_mac_to_colon_hex,
    _parse_vlan_list,
    merge_trunk_allowed,
)
from .._input_shape import detect_input_shape
from .._scanner import scan_stanzas
from ..base import ParseError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex constants — module-level so they compile once per import.
# Shapes lifted from cisco_iosxe_cli/parse.py; the IP / VRF families
# diverge per NX-OS grammar (see module docstring).
# ---------------------------------------------------------------------------

_HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)", re.IGNORECASE | re.MULTILINE)
#: ``version 9.2(3) Bios:version`` / ``version 10.3(9)`` — first token
#: after ``version`` is the NX-OS release string.
_VERSION_RE = re.compile(r"^version\s+(\S+)", re.IGNORECASE | re.MULTILINE)

# ── Management-plane globals (promotion #4) — NX-OS render-dropped these
#    until this wire-up.  Grammar attested in the codec's own real fixtures:
#    ``ip domain-name lab.karneliuk.com``, ``ntp server 10.1.1.1 use-vrf
#    default`` / ``ntp server 10.2.2.2 prefer use-vrf default``,
#    ``logging server 10.125.1.171 6 port 7008``. ──
#: ``ip domain-name <fqdn>`` — NX-OS keeps the ``ip`` prefix (unlike IOS-XR).
_DOMAIN_RE = re.compile(r"^ip\s+domain-name\s+(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
#: ``ip name-server [vrf <name>] <ip> [<ip> ...]`` — multiple resolvers per line.
_NAME_SERVER_RE = re.compile(
    r"^ip\s+name-server\s+(?:vrf\s+\S+\s+)?(.+)$", re.IGNORECASE | re.MULTILINE,
)
#: ``ntp server <ip> [prefer] [use-vrf <name>]`` — the address is the first
#: token; the ``prefer`` / ``use-vrf`` tails follow and are dropped.
_NTP_SERVER_RE = re.compile(r"^ntp\s+server\s+(\S+)", re.IGNORECASE | re.MULTILINE)
#: Syslog destinations — NX-OS spells them ``logging server <ip> [severity]
#: [port N] [use-vrf X]``, but ``logging`` also fronts non-destination
#: sub-commands (``logging console``, ``logging monitor``, ``logging level``).
#: Harvest the first IP-literal token per ``logging`` line and validate with
#: :mod:`ipaddress` (mirrors cisco_iosxe_cli / arista_eos ``_SYSLOG_LINE_RE``).
_SYSLOG_LINE_RE = re.compile(r"^\s*logging\s+(\S.*)$", re.IGNORECASE | re.MULTILINE)

_IFACE_RE = re.compile(r"^interface\s+(\S+)", re.IGNORECASE)
_DESC_RE = re.compile(r"^\s+description\s+(.+)", re.IGNORECASE)
_SHUTDOWN_RE = re.compile(r"^\s+shutdown\s*$", re.IGNORECASE)
_NO_SHUTDOWN_RE = re.compile(r"^\s+no\s+shutdown\s*$", re.IGNORECASE)
_MTU_RE = re.compile(r"^\s+mtu\s+(\d+)\s*$", re.IGNORECASE)
# ``tunnel mode <encap>`` inside an ``interface Tunnel<N>`` stanza.  NX-OS
# spells GRE ``tunnel mode gre ip`` and IP-in-IP ``tunnel mode ipip``;
# ``ipv6ip`` (IPv6-over-IPv4) collapses to the canonical ``ipip``.  Ignored
# on non-tunnel interfaces (the field is only meaningful there).
_TUNNEL_MODE_RE = re.compile(
    r"^\s+tunnel\s+mode\s+(gre|ipip|ipsec|vxlan|ipv6ip)\b", re.IGNORECASE,
)
#: ``ip address 10.10.10.1/24`` — CIDR form, NEVER dotted mask.  The
#: optional ``secondary`` trailer is consumed but not modelled in Phase 1.
_IP_CIDR_RE = re.compile(
    r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)/(\d+)(?:\s+(secondary))?",
    re.IGNORECASE,
)
#: ``ipv6 address 2001:db8::1/64`` — CIDR form.  Optional ``link-local``
#: trailer tags scope explicitly; fe80::/10 prefix infers it otherwise.
_IPV6_CIDR_RE = re.compile(
    r"^\s+ipv6\s+address\s+(\S+?)/(\d+)(?:\s+(link-local))?\s*$",
    re.IGNORECASE,
)
#: ``vrf member <name>`` inside an interface stanza (NX-OS form of
#: IOS-XE's ``vrf forwarding``).
_VRF_MEMBER_RE = re.compile(r"^\s+vrf\s+member\s+(\S+)\s*$", re.IGNORECASE)

# ── L2 switchport grammar (Phase 2) ──
# NX-OS Ethernet / port-channel ports default to L2 switchport; a routed
# port requires an explicit ``no switchport``.  Mirrors arista_eos's
# render-decides model: set ``switchport_mode`` only on explicit
# mode/access/trunk lines, leave it ``None`` otherwise, and let render
# emit ``no switchport`` for a physical/LAG port that carries an IP.
# ``no switchport`` is consumed (it marks the port routed) but sets no
# canonical field — ``switchport_mode=None`` already means "routed".
_NO_SWITCHPORT_RE = re.compile(r"^\s+no\s+switchport\s*$", re.IGNORECASE)
#: GAP 7: routed sub-interface 802.1Q tag — NX-OS writes lowercase
#: ``encapsulation dot1q <vlan>`` (e.g. under ``interface Ethernet1/1.100``).
_ENCAP_DOT1Q_RE = re.compile(
    r"^\s+encapsulation\s+dot1q\s+(\d+)\b", re.IGNORECASE,
)
_SWITCHPORT_MODE_RE = re.compile(
    r"^\s+switchport\s+mode\s+(\S+)", re.IGNORECASE,
)
_SWITCHPORT_ACCESS_RE = re.compile(
    r"^\s+switchport\s+access\s+vlan\s+(\d+)", re.IGNORECASE,
)
_SWITCHPORT_TRUNK_ALLOWED_RE = re.compile(
    r"^\s+switchport\s+trunk\s+allowed\s+vlan\s+(.+)", re.IGNORECASE,
)
_SWITCHPORT_TRUNK_NATIVE_RE = re.compile(
    r"^\s+switchport\s+trunk\s+native\s+vlan\s+(\d+)", re.IGNORECASE,
)
# ``channel-group N mode active|passive|on`` declares the port a member
# of ``port-channelN``.  NX-OS mode vocab → canonical LAG modes
# (``on`` is static aggregation).
_CHANNEL_GROUP_RE = re.compile(
    r"^\s+channel-group\s+(\d+)\s+mode\s+(\S+)", re.IGNORECASE,
)
_NXOS_LAG_MODE_MAP = {"active": "active", "passive": "passive", "on": "static"}

# ── HSRP (Phase 2c) ──
# NX-OS HSRP is a nested block under an L3 interface:
#   interface Vlan10
#     hsrp version 2          (interface-level; not modelled)
#     hsrp 10                 (2-indent — opens a group)
#       ip 10.10.10.254       (4-indent — group sub-commands)
#       priority 110
#       preempt
# Maps to CanonicalVRRPGroup(mode="hsrp").  NX-OS HSRP defaults preempt
# DISABLED (unlike VRRP), so the scratch default is preempt=False.
_HSRP_GROUP_RE = re.compile(r"^\s+hsrp\s+(\d+)\s*$", re.IGNORECASE)
_HSRP_VERSION_RE = re.compile(r"^\s+hsrp\s+version\s+\d+\s*$", re.IGNORECASE)
_HSRP_IP_RE = re.compile(r"^\s+ip\s+(\d+\.\d+\.\d+\.\d+)\s*$", re.IGNORECASE)
_HSRP_PRIORITY_RE = re.compile(r"^\s+priority\s+(\d+)\s*$", re.IGNORECASE)
_HSRP_PREEMPT_RE = re.compile(r"^\s+(no\s+)?preempt\b", re.IGNORECASE)
_HSRP_AUTH_MD5_RE = re.compile(
    r"^\s+authentication\s+md5\s+key-string\s+(\S+)", re.IGNORECASE,
)
_HSRP_AUTH_TEXT_RE = re.compile(
    r"^\s+authentication\s+text\s+(\S+)", re.IGNORECASE,
)

# ── SNMP + local users (Phase 2b) ──
_SNMP_COMMUNITY_RE = re.compile(
    r"^snmp-server\s+community\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)
_SNMP_LOCATION_RE = re.compile(
    r"^snmp-server\s+location\s+(.+)$", re.IGNORECASE | re.MULTILINE,
)
_SNMP_CONTACT_RE = re.compile(
    r"^snmp-server\s+contact\s+(.+)$", re.IGNORECASE | re.MULTILINE,
)
_SNMP_HOST_RE = re.compile(
    r"^snmp-server\s+host\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE | re.MULTILINE,
)
# NX-OS SNMPv3 USM user:
#   snmp-server user <name> [<group>] auth <proto> <key>
#       [priv [<cipher>] <key>] [localized[V2]key] [engineID <id>]
# Keys are 0x-prefixed localized digests on the wire — preserved
# verbatim.  ``priv`` is optional (auth-no-priv users); the privacy
# CIPHER inside ``priv`` is ALSO optional — NX-OS emits ``priv <cipher>
# <key>`` (e.g. ``priv aes-128 0x…``) when a cipher is configured but the
# bare ``priv <key>`` form (default DES, no explicit cipher) just as
# often.  The cipher must therefore match an enumerated token set
# (``aes-128``/``aes-192``/``aes-256``/``des``/``3des``); a greedy
# ``(\S+)\s+(\S+)`` instead swallowed the priv KEY as the "cipher" and
# the trailing ``localizedkey`` keyword as the "key", landing the real
# priv key in the un-sanitized ``priv_protocol`` field — an SNMPv3
# priv-key disclosure through the sanitizer (dogfood mesh, napalm NX-OS
# captures).  ``localizedV2key`` (NX-OS 10.x digest) is detected but not
# modelled — render always emits the older ``localizedkey`` form (lossy).
_SNMP_V3_USER_RE = re.compile(
    r"^snmp-server\s+user\s+(\S+)(?:\s+(\S+))?"
    r"\s+auth\s+(md5|sha|sha224|sha256|sha384|sha512)\s+(\S+)"
    r"(?:\s+priv\s+(?:(aes-128|aes-192|aes-256|3des|des)\s+)?(\S+))?"
    r"(?:\s+localized(V2)?key)?"
    r"(?:\s+engineID\s+(\S+))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# ``username <name> password <type> <hash> role <role>``.  NX-OS uses a
# named ``role`` (network-admin / network-operator / custom) rather than
# a numeric privilege level.
_USERNAME_RE = re.compile(
    r"^username\s+(\S+)\s+password\s+(\d+)\s+(\S+)\s+role\s+(\S+)",
    re.IGNORECASE,
)
#: NX-OS roles that map to the cross-vendor admin privilege (15).
_NXOS_ADMIN_ROLES = {"network-admin", "vdc-admin"}


def _normalise_priv_proto(proto: str | None) -> str:
    """NX-OS privacy-cipher token -> canonical short form.

    ``aes-128`` -> ``aes128`` (strip the hyphen); ``des`` / ``3des``
    pass through lower-cased.  Empty for auth-no-priv users.
    """
    if not proto:
        return ""
    return proto.lower().replace("-", "")


# ── Distributed Anycast Gateway (T2) ──
#: ``fabric forwarding anycast-gateway-mac <mac>`` (top-level) — the
#: chassis-wide anycast MAC every DAG SVI shares as its virtual L2
#: next-hop.  NX-OS emits dotted-triplet (``0001.c73a.0000``).
_FABRIC_AG_MAC_RE = re.compile(
    r"^fabric\s+forwarding\s+anycast-gateway-mac\s+(?P<mac>\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
#: ``fabric forwarding mode anycast-gateway`` inside an ``interface
#: Vlan<N>`` SVI marks the primary IP as the distributed anycast gateway.
_FABRIC_AG_MODE_RE = re.compile(
    r"^\s+fabric\s+forwarding\s+mode\s+anycast-gateway\s*$", re.IGNORECASE,
)


#: ``vrf context <name>`` opens a top-level VRF stanza.
_VRF_CONTEXT_RE = re.compile(r"^vrf\s+context\s+(\S+)\s*$", re.IGNORECASE)
# ``(\S.*)`` (not ``(.+)``) so the ``\s+`` separator and the value can't both
# match the same spaces -- the polynomial-ReDoS overlap CodeQL flagged
# (py/polynomial-redos #126).  The consumer ``.strip()``s the group, so a
# non-space first char is behaviour-identical for any real description.
_VRF_DESCRIPTION_RE = re.compile(r"^\s+description\s+(\S.*)$", re.IGNORECASE)
# ── VRF RD / route-target + per-VRF static route (Phase 3) ──
#: ``rd <asn>:<nn>`` / ``rd <ip>:<nn>`` / ``rd auto`` inside a ``vrf
#: context`` block.  ``auto`` (NX-OS derives the RD from the BGP ASN +
#: VRF VNI) is preserved verbatim as a sentinel — declared lossy.
_VRF_RD_RE = re.compile(r"^\s+rd\s+(\S+)\s*$", re.IGNORECASE)
#: ``route-target import|export|both <rt> [evpn]`` (nested under an
#: ``address-family ... unicast`` sub-block).  ``both`` expands to
#: import + export; the trailing ``evpn`` address-family discriminator
#: is consumed but not modelled (declared lossy — the RT is preserved
#: but the L2VPN-EVPN scope reverts to IPv4 unicast cross-vendor).
_VRF_RT_RE = re.compile(
    r"^\s+route-target\s+(import|export|both)\s+(\S+)(?:\s+evpn)?\s*$",
    re.IGNORECASE,
)
#: ``address-family ipv4|ipv6 unicast`` framing inside ``vrf context`` —
#: gates the nested route-target lines on the wire but carries no
#: canonical state of its own (consumed / ignored, like IOS-XE's
#: ``address-family`` / ``exit-address-family`` markers).
_VRF_AF_RE = re.compile(r"^\s+address-family\s+\S+", re.IGNORECASE)
#: Per-VRF static route nested inside ``vrf context X`` (indented).
#: NX-OS form: ``  ip route <dest>/<prefix> <gw> [<pref>]``.  Harvested
#: onto :attr:`CanonicalStaticRoute.vrf` — the instance already exists
#: (the ``vrf context`` header created it), so the harvest can never
#: conjure a phantom routing-instance (see the per-VRF harvest memory).
_VRF_IP_ROUTE_RE = re.compile(
    # Optional group 4 = two-token gateway (``ip route <dest> <iface> <gw>``);
    # group 5 = admin distance.  ``(?=\s|$)`` boundary keeps the distance group
    # from biting a partial digit run (HEAD-review L1-9).
    r"^\s+ip\s+route\s+(\d+\.\d+\.\d+\.\d+)/(\d+)\s+(\S+)"
    r"(?:\s+(\d+\.\d+\.\d+\.\d+))?(?:\s+(\d+))?(?=\s|$)",
    re.IGNORECASE,
)
#: ``  ipv6 route <prefix>/<len> <nh> [<pref>]`` nested in a ``vrf context``
#: block (does not overlap the v4 form; ``ipv6`` != ``ip``).
_VRF_IPV6_ROUTE_RE = re.compile(
    # Optional group 3 = two-token IPv6 gateway (must contain a colon so a
    # bare distance integer in group 4 is not mistaken for it).
    r"^\s+ipv6\s+route\s+([0-9A-Fa-f:]+/\d+)\s+(\S+)"
    r"(?:\s+([0-9A-Fa-f]*:[0-9A-Fa-f:]*))?(?:\s+(\d+))?(?=\s|$)",
    re.IGNORECASE,
)
# ── VXLAN-EVPN (Phase 4) ──
#: ``vni <N>`` inside a ``vrf context`` block → the VRF's L3VNI (symmetric
#: IRB).  Authoritative VRF↔L3VNI binding; the matching ``interface nve1 /
#: member vni N associate-vrf`` line is parse-discard.
_VRF_VNI_RE = re.compile(r"^\s+vni\s+(\d+)\s*$", re.IGNORECASE)
#: ``vn-segment <vni>`` inside a ``vlan <N>`` stanza → the L2 VLAN↔VNI
#: binding.  Joined with the VLAN id to build a :class:`CanonicalVxlan`.
_VN_SEGMENT_RE = re.compile(r"^\s+vn-segment\s+(\d+)\s*$", re.IGNORECASE)
#: ``source-interface <name>`` inside ``interface nve1`` → the switch-level
#: VTEP source, broadcast onto every CanonicalVxlan record.
_NVE_SOURCE_IF_RE = re.compile(
    r"^\s+source-interface\s+(\S+)\s*$", re.IGNORECASE,
)
#: ``member vni <vni> [mcast-group <ip>]`` inside ``interface nve1`` → an
#: L2 VNI's overlay multicast group.  Two real grammar forms exist: the
#: inline form (group 2 captures the address on the same line) and the
#: own-sub-line form where ``mcast-group`` lands on the next indented line
#: (see _NVE_MCAST_RE).  ``member vni N associate-vrf`` (the L3VNI binding)
#: matches with group 2 empty and is skipped — the L3VNI is harvested from
#: ``vrf context X / vni N`` instead.
_NVE_MEMBER_VNI_RE = re.compile(
    r"^\s+member\s+vni\s+(\d+)"
    r"(?:\s+mcast-group\s+(\d+\.\d+\.\d+\.\d+)|\s+associate-vrf)?\s*$",
    re.IGNORECASE,
)
#: ``mcast-group <ip>`` on its own indented line, following a ``member vni``
#: line (the own-sub-line form) → attaches to the current member VNI.
_NVE_MCAST_RE = re.compile(
    r"^\s+mcast-group\s+(\d+\.\d+\.\d+\.\d+)\s*$", re.IGNORECASE,
)
#: ``peer-ip <ip>`` inside a ``member vni N / ingress-replication protocol
#: static`` sub-block → a static head-end-replication flood-list entry for
#: the current member VNI (the alternative to multicast flood-and-learn).
#: The ``ingress-replication protocol static`` marker line itself carries no
#: data and falls through; the peer-ip lines below it are the flood-list.
_NVE_PEER_IP_RE = re.compile(
    r"^\s+peer-ip\s+(\d+\.\d+\.\d+\.\d+)\s*$", re.IGNORECASE,
)
#: ``vlan 1,10,2000`` / ``vlan 10-20`` — comma + range list (unique to
#: NX-OS / Arista in this codebase).
_VLAN_TOP_RE = re.compile(r"^vlan\s+([\d,\-]+)\s*$", re.IGNORECASE)
_VLAN_NAME_RE = re.compile(r"^\s+name\s+(.+)", re.IGNORECASE)
#: ``ip route 0.0.0.0/0 10.0.0.2 [<pref>]`` — top-level (default VRF)
#: static route.  Per-VRF routes (indented inside ``vrf context``) do
#: NOT match this top-level anchor and are deferred to Phase 3.
_STATIC_ROUTE_RE = re.compile(
    # Optional group 4 = two-token gateway (``ip route <dest> <iface> <gw>``);
    # group 5 = admin distance.  ``(?=\s|$)`` boundary as in the per-VRF form.
    r"^ip\s+route\s+(\d+\.\d+\.\d+\.\d+)/(\d+)\s+(\S+)"
    r"(?:\s+(\d+\.\d+\.\d+\.\d+))?(?:\s+(\d+))?(?=\s|$)",
    re.IGNORECASE,
)
#: ``ipv6 route <prefix>/<len> <nh> [<pref>]`` — top-level (default VRF)
#: IPv6 static route (does not overlap the v4 anchor above).
_STATIC_ROUTE_V6_RE = re.compile(
    r"^ipv6\s+route\s+([0-9A-Fa-f:]+/\d+)\s+(\S+)"
    r"(?:\s+([0-9A-Fa-f]*:[0-9A-Fa-f:]*))?(?:\s+(\d+))?(?=\s|$)",
    re.IGNORECASE,
)
_SVI_NAME_RE = re.compile(r"^Vlan(\d+)$", re.IGNORECASE)

#: Interface-name prefix → IANA ifType hint.  NX-OS uses a single
#: ``Ethernet`` prefix for every speed.
_TYPE_HINTS: tuple[tuple[str, str], ...] = (
    ("ethernet", "ianaift:ethernetCsmacd"),
    ("loopback", "ianaift:softwareLoopback"),
    ("vlan", "ianaift:l3ipvlan"),
    ("port-channel", "ianaift:ieee8023adLag"),
    ("nve", "ianaift:tunnel"),
    ("tunnel", "ianaift:tunnel"),   # ``interface Tunnel<N>`` (GRE / IP-in-IP)
    ("mgmt", "ianaift:ethernetCsmacd"),
)

#: A VRF whose name matches this heuristic is the device's management
#: (OOBM) VRF.  NX-OS convention is the literal ``management`` VRF;
#: ``mgmt`` / ``management`` are accepted case-insensitively.
_MGMT_VRF_RE = re.compile(r"^(?:management|mgmt)$", re.IGNORECASE)


def _infer_type(iface_name: str) -> str:
    """Best-effort IANA ifType from the NX-OS interface-name prefix."""
    lower = iface_name.lower()
    for prefix, iftype in _TYPE_HINTS:
        if lower.startswith(prefix):
            return iftype
    return "ianaift:other"


def _is_mgmt_vrf(vrf_name: str) -> bool:
    """Return True when *vrf_name* is the NX-OS management VRF."""
    return bool(_MGMT_VRF_RE.match(vrf_name or ""))


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse NX-OS ``show running-config`` output into a
    :class:`CanonicalIntent`.

    Raises:
        ParseError: If the input is empty or looks like XML / JSON
            rather than NX-OS CLI text.
    """
    if not raw.strip():
        raise ParseError("cisco_nxos: empty input", snippet="")

    # Shape sanity: reject XML / JSON early so the operator gets a clean
    # error instead of a near-empty render.  Mirrors cisco_iosxe_cli.
    shape = detect_input_shape(raw)
    if shape is not None:
        raise ParseError(
            f"cisco_nxos: input looks like {shape.upper()}, not NX-OS "
            f"CLI.  Paste the output of `show running-config`.",
            snippet=raw.lstrip()[:120],
        )

    intent = CanonicalIntent(
        source_vendor="cisco_nxos",
        source_format="cli-nxos",
    )

    intent.hostname = _extract_hostname(raw)
    intent.source_version = _extract_version(raw)

    # Management-plane globals (domain / DNS / NTP / syslog) — promotion #4.
    _parse_globals(raw, intent)

    # Distributed Anycast Gateway: the chassis-wide MAC (`fabric
    # forwarding anycast-gateway-mac`).  Per-SVI anycast-mode markers are
    # harvested in :func:`_parse_interfaces`.
    agm = _FABRIC_AG_MAC_RE.search(raw)
    if agm:
        normalised = _normalise_mac_to_colon_hex(agm.group("mac"))
        if normalised:
            intent.anycast_gateway_mac = normalised

    # VRF declarations (``vrf context <name>`` top-level stanzas).
    # Phase 3 harvests name + description + rd + route-target; the nested
    # per-VRF ``ip route`` lines come back as the second tuple element and
    # merge into static_routes below.  ``vni`` (L3VNI) stays Phase 4.
    # Per-interface ``vrf member`` membership is set by
    # :func:`_parse_interfaces`.
    intent.routing_instances, _vrf_static_routes = _parse_routing_instances(raw)

    intent.interfaces = _parse_interfaces(raw)

    intent.vlans = _parse_vlans(raw)
    # Derive VLAN records from ``interface Vlan<N>`` SVIs that had no
    # matching top-level ``vlan`` stanza — same fix as iosxe_cli to
    # avoid silently dropping the SVI's L3 config on VLAN-centric
    # downstream codecs.
    _synthesize_vlans_from_svis(intent)

    # Static routes — top-level scan harvests default-VRF routes; the
    # per-VRF routes harvested from inside ``vrf context`` blocks (above)
    # carry ``vrf=<name>`` and merge in here.  The two sets are disjoint
    # by indentation (top-level ``^ip route`` vs nested ``  ip route``),
    # so no de-dup is required.
    intent.static_routes = _parse_static_routes(raw) + _vrf_static_routes

    # LAGs (Phase 2) — both the ``interface port-channelN`` declaration
    # and per-member ``channel-group N mode M`` lines contribute.
    intent.lags = _parse_lags(raw)

    # SNMP (Phase 2b) — v2c community + v3 USM users.
    intent.snmp = _parse_snmp(raw)

    # Local users (Phase 2b) — ``username ... role <role>``.
    intent.local_users = _parse_local_users(raw)

    # VXLAN-EVPN (Phase 4) — L2 VLAN↔VNI bindings from ``vlan N /
    # vn-segment <vni>`` + the ``interface nve1`` source-interface
    # (broadcast onto every record).  L3VNIs live on
    # routing_instances[].l3_vni (harvested by _parse_routing_instances).
    intent.vxlan_vnis = _parse_vxlan(raw)

    # Shared switchport→VLAN projection: mirror per-port switchport state
    # into the VLAN-centric tagged/untagged lists so VLAN-centric
    # renderers can emit the membership.  The phantom-VLAN guard
    # (snapshot legitimate VLAN ids before, prune after) mirrors
    # iosxe_cli — a wide ``switchport trunk allowed`` range must not
    # inflate tree.vlans with thousands of phantom records.
    legitimate_vlan_ids = {v.id for v in intent.vlans}
    from ...canonical.transforms import project_switchport_to_vlan
    project_switchport_to_vlan(intent)
    intent.vlans = [v for v in intent.vlans if v.id in legitimate_vlan_ids]

    logger.debug(
        "cisco_nxos parsed: hostname=%r ifaces=%d vlans=%d routes=%d "
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


def _parse_globals(raw: str, intent: CanonicalIntent) -> None:
    """Harvest the NX-OS management-plane globals (promotion #4) that the
    codec render-dropped until this wire-up: ``ip domain-name`` → domain,
    ``ip name-server`` → dns_servers, ``ntp server`` → ntp_servers,
    ``logging server``/``logging <ip>`` → syslog_servers.  Mutates *intent*
    in place (keeps :func:`parse_intent` a flat sequence of phase calls)."""
    m = _DOMAIN_RE.search(raw)
    if m:
        intent.domain = m.group(1)
    for m in _NAME_SERVER_RE.finditer(raw):
        # ``ip name-server 1.1.1.1 8.8.8.8`` is two resolvers on one line; a
        # trailing ``use-vrf <name>`` modifier must NOT be harvested as a
        # resolver.  IP-guard each token (mirrors the syslog loop below) so
        # ``use-vrf`` / ``management`` are skipped (HEAD-review L1-2).
        for token in m.group(1).split():
            try:
                ipaddress.ip_address(token)
            except ValueError:
                continue
            intent.dns_servers.append(token)
    for m in _NTP_SERVER_RE.finditer(raw):
        intent.ntp_servers.append(m.group(1))
    seen_syslog = set(intent.syslog_servers)
    for m in _SYSLOG_LINE_RE.finditer(raw):
        # First IP-literal token on the ``logging`` line is the syslog host;
        # non-destination sub-commands carry no IP token.  De-dup, first-seen
        # (``seen_syslog`` set-guard keeps it O(1) per line -- perf review P2).
        for token in m.group(1).split():
            try:
                ipaddress.ip_address(token)
            except ValueError:
                continue
            if token not in seen_syslog:
                seen_syslog.add(token)
                intent.syslog_servers.append(token)
            break


def _extract_version(raw: str) -> str:
    """Return the NX-OS release string from the ``version`` line.

    Stored as :attr:`CanonicalIntent.source_version` (metadata).  On a
    same-vendor render the device's own release is echoed rather than
    relabelled with a constant (#297); a cross-vendor render synthesises
    a fresh banner.
    """
    m = _VERSION_RE.search(raw)
    return m.group(1) if m else ""


def _parse_routing_instances(
    raw: str,
) -> tuple[list[CanonicalRoutingInstance], list[CanonicalStaticRoute]]:
    """Extract ``vrf context <name>`` blocks + their per-VRF static routes.

    A NX-OS VRF stanza looks like::

        vrf context TENANT-A
          description tenant a
          vni 10001                       ← Phase 4 L3VNI (ignored)
          rd 65001:100                    ← Phase 3
          address-family ipv4 unicast     ← framing (ignored)
            route-target import 65001:100 ← Phase 3
            route-target export 65001:100 ← Phase 3
            route-target both auto evpn   ← Phase 3 (RT kept, evpn dropped)
          ip route 10.50.0.0/16 172.16.0.2  ← Phase 3 (per-VRF static)

    Returns a ``(instances, per_vrf_routes)`` pair.  Phase 3 harvests
    ``name`` / ``description`` / ``rd`` (``auto`` preserved verbatim as a
    sentinel) / ``route-target`` (``both`` expands to import + export; a
    trailing ``evpn`` discriminator is dropped) onto the instance, and
    each nested ``ip route`` onto a :class:`CanonicalStaticRoute` carrying
    ``vrf=<name>``.  ``vni`` (L3VNI) and the ``address-family`` framing
    stay parse-and-ignore (L3VNI is Phase 4).

    The per-VRF route harvest never materialises an instance — the ``vrf
    context`` header already created it — so it cannot conjure a phantom
    routing-instance on cross-vendor round-trip (see the per-VRF harvest
    memory).  Block-walker pattern mirrors ``cisco_iosxe_cli`` — open on
    the header regex, absorb indented sub-lines, close on the first
    non-indented line.
    """
    per_vrf_routes: list[CanonicalStaticRoute] = []

    def _on_line(line: str, current: CanonicalRoutingInstance) -> None:
        dm = _VRF_DESCRIPTION_RE.match(line)
        if dm:
            current.description = dm.group(1).strip()
            return
        rm = _VRF_RD_RE.match(line)
        if rm:
            current.route_distinguisher = rm.group(1)
            return
        rtm = _VRF_RT_RE.match(line)
        if rtm:
            direction = rtm.group(1).lower()
            rt = rtm.group(2)
            if direction in ("import", "both"):
                current.rt_imports.append(rt)
            if direction in ("export", "both"):
                current.rt_exports.append(rt)
            return
        route6_m = _VRF_IPV6_ROUTE_RE.match(line)
        if route6_m:
            per_vrf_routes.append(_make_static_route_v6(
                route6_m.group(1), route6_m.group(2), route6_m.group(4),
                vrf=current.name, second_hop=route6_m.group(3),
            ))
            return
        route_m = _VRF_IP_ROUTE_RE.match(line)
        if route_m:
            per_vrf_routes.append(_make_static_route(
                route_m.group(1), route_m.group(2),
                route_m.group(3), route_m.group(5),
                vrf=current.name, second_hop=route_m.group(4),
            ))
            return
        vnim = _VRF_VNI_RE.match(line)
        if vnim:
            # ``vni <N>`` → the VRF's L3VNI (Phase 4 symmetric IRB).
            current.l3_vni = int(vnim.group(1))
            return
        if _VRF_AF_RE.match(line):
            # ``address-family ... unicast`` — wire framing only; the
            # route-target lines it brackets are matched above by indent.
            return
        # Anything else inside the block — parse-and-ignore.

    # Loop skeleton (open on `vrf context`, close on dedent, flush at EOF)
    # is the shared codecs/_scanner helper; the vendor regex cascade above
    # stays here.  The nested ``ip route`` lines feed a side-channel
    # ``per_vrf_routes`` list (closed over by ``_on_line``), and the scratch
    # IS the canonical record so ``build`` is the identity.  NX-OS does not
    # bracket VRF blocks with ``!``, so the terminator replicates the former
    # rule exactly: only a non-indented line closes a stanza.
    instances = scan_stanzas(
        raw.splitlines(),
        is_header=_VRF_CONTEXT_RE.match,
        open_scratch=lambda m: CanonicalRoutingInstance(name=m.group(1)),
        on_line=_on_line,
        build=lambda ri: ri,
        is_terminator=lambda line: bool(line) and not line[0].isspace(),
    )

    # Deduplicate each instance's route-targets, preserving first-seen
    # order.  The same RT value routinely appears under several
    # ``address-family`` sub-blocks (``ipv4 unicast`` + ``ipv6 unicast``)
    # and in both the unicast and ``... evpn`` scopes — e.g. a tenant VRF
    # with ``route-target both auto`` under ipv4-unicast, ipv6-unicast,
    # AND ``route-target both auto evpn`` yields three identical ``auto``
    # imports.  The canonical model carries a single flat per-direction
    # list with no address-family / evpn dimension (that scope is the
    # already-declared-lossy part), so those repeats are artefacts that
    # carry no canonical information.  Collapsing them (a) matches the
    # set-semantics NX-OS itself applies — importing an RT twice is
    # idempotent — and (b) keeps the same-vendor round-trip STABLE: the
    # renderer emits the compact ``both``/``import``/``export`` form, and
    # without dedup an asymmetric import-only RT interleaved between
    # ``both`` lines gets re-ordered to the tail on re-parse, drifting
    # ``rt_imports`` order (real defect surfaced by the akarneliuk
    # EVPN-VXLAN leaf capture, whose VRFs mix ``both auto`` with an
    # ``import <asn>:<vni>`` route-leak).
    for ri in instances:
        ri.rt_imports = list(dict.fromkeys(ri.rt_imports))
        ri.rt_exports = list(dict.fromkeys(ri.rt_exports))

    return instances, per_vrf_routes


def _new_iface_scratch(name: str) -> dict:
    """Fresh per-interface parse-time scratch dict.

    Single source of truth for the field set so the two stanza-open
    sites in :func:`_parse_interfaces` can't drift apart.
    """
    return {
        "name": name,
        "description": "",
        "enabled": True,
        "type": _infer_type(name),
        "tunnel_type": "",
        "mtu": None,
        "ipv4": [],
        "ipv6": [],
        "vrf": "",
        "kind": "",
        "switchport_mode": None,
        "access_vlan": None,
        "dot1q_vlan": None,
        "trunk_allowed": [],
        "trunk_native": None,
        "lag_member_of": None,
        # Distributed Anycast Gateway: set True by ``fabric forwarding
        # mode anycast-gateway`` → mirrors the primary IP into
        # virtual_gateway_address in _build_canonical_interface.
        "fabric_forwarding_anycast": False,
        # HSRP (Phase 2c): {gid: {virtual_ips, priority, preempt, auth}}.
        "hsrp_groups": {},
        "_hsrp_gid": None,   # active group while inside an ``hsrp N`` block
    }


def _parse_interfaces(raw: str) -> list[CanonicalInterface]:  # noqa: C901
    """Extract ``interface <name>`` stanzas from NX-OS config text.

    Per interface: description, enabled (shutdown / no shutdown), mtu,
    IPv4 (CIDR), IPv6 (CIDR + scope), VRF membership (``vrf member``),
    and (Phase 2) L2 switchport state (mode / access-vlan / trunk-allowed
    / trunk-native) + LAG membership (``channel-group``).  The
    management-VRF heuristic promotes a physical-named port bound to the
    ``management`` VRF to ``kind="mgmt"`` (mgmt0 already classifies mgmt
    by name).  ``interface nve1`` is intercepted as a VXLAN config
    container and not materialised here (see ``_open``).
    """
    def _open(m: re.Match[str]) -> dict | None:
        # VTEP (``interface nve1``) is a VXLAN config container, not a
        # routed/switched port: its source-interface + member-vni
        # sub-commands are harvested by :func:`_parse_vxlan` (L2) and
        # :func:`_parse_routing_instances` (L3VNI).  Returning None leaves
        # the stanza open-but-unmaterialised so its indented body lines
        # fall through the scanner's ``current is None`` skip — mirrors
        # arista_eos's ``Vxlan1`` interception.
        name = m.group(1)
        if name.lower().startswith("nve"):
            return None
        return _new_iface_scratch(name)

    def _on_line(line: str, current: dict) -> None:  # noqa: C901
        # ── HSRP nested block (Phase 2c) ──
        # ``hsrp <N>`` opens a group; its sub-commands are further-indented
        # (>= 4 spaces).  Any shallower indented line ends the block.  This
        # nested-block state lives in the scratch (``_hsrp_gid``), so it
        # stays in this cascade rather than the shared scanner.
        hg = _HSRP_GROUP_RE.match(line)
        if hg:
            gid = int(hg.group(1))
            current["hsrp_groups"].setdefault(gid, {
                "virtual_ips": [],
                "priority": 100,
                "preempt": False,   # NX-OS HSRP default: preempt disabled
                "authentication": "",
            })
            current["_hsrp_gid"] = gid
            return
        if _HSRP_VERSION_RE.match(line):
            # ``hsrp version 2`` is interface-level; not modelled.
            current["_hsrp_gid"] = None
            return
        _gid = current["_hsrp_gid"]
        if _gid is not None and (len(line) - len(line.lstrip())) >= 4:
            g = current["hsrp_groups"][_gid]
            him = _HSRP_IP_RE.match(line)
            if him:
                g["virtual_ips"].append(him.group(1))
                return
            hpm = _HSRP_PRIORITY_RE.match(line)
            if hpm:
                g["priority"] = int(hpm.group(1))
                return
            hpe = _HSRP_PREEMPT_RE.match(line)
            if hpe:
                g["preempt"] = not bool(hpe.group(1))   # ``no preempt`` -> False
                return
            ham = _HSRP_AUTH_MD5_RE.match(line)
            if ham:
                g["authentication"] = f"md5:{ham.group(1)}"
                return
            hat = _HSRP_AUTH_TEXT_RE.match(line)
            if hat:
                g["authentication"] = f"plain:{hat.group(1)}"
                return
            # Unknown hsrp sub-command (timers / mac-address / track) —
            # consume it; still inside the group block.
            return
        # Any other indented line ends the active hsrp group block.
        current["_hsrp_gid"] = None

        dm = _DESC_RE.match(line)
        if dm:
            current["description"] = dm.group(1).strip()
            return

        if _SHUTDOWN_RE.match(line):
            current["enabled"] = False
            return
        if _NO_SHUTDOWN_RE.match(line):
            current["enabled"] = True
            return

        mm = _MTU_RE.match(line)
        if mm:
            try:
                current["mtu"] = int(mm.group(1))
            except ValueError:
                pass
            return

        tmm = _TUNNEL_MODE_RE.match(line)
        if tmm:
            mode = tmm.group(1).lower()
            current["tunnel_type"] = "ipip" if mode == "ipv6ip" else mode
            return

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
            return

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
            return

        vm = _VRF_MEMBER_RE.match(line)
        if vm:
            current["vrf"] = vm.group(1)
            return

        # ── Distributed Anycast Gateway per-SVI marker ──
        if _FABRIC_AG_MODE_RE.match(line):
            current["fabric_forwarding_anycast"] = True
            return

        # ── GAP 7: routed sub-interface 802.1Q tag ──
        # ``encapsulation dot1q <vlan>`` on a sub-interface (e.g.
        # ``interface Ethernet1/1.100``) → dedicated dot1q_vlan, NOT
        # access_vlan (a routed sub-iface is L3, not an L2 access port).
        em = _ENCAP_DOT1Q_RE.match(line)
        if em:
            current["dot1q_vlan"] = int(em.group(1))
            return

        # ── L2 switchport (Phase 2) ──
        if _NO_SWITCHPORT_RE.match(line):
            # Routed port — leave switchport_mode None (render emits
            # ``no switchport`` for a physical/LAG port carrying an IP).
            return
        sm = _SWITCHPORT_MODE_RE.match(line)
        if sm:
            current["switchport_mode"] = sm.group(1).lower()
            return
        am = _SWITCHPORT_ACCESS_RE.match(line)
        if am:
            current["switchport_mode"] = current["switchport_mode"] or "access"
            current["access_vlan"] = int(am.group(1))
            return
        tam = _SWITCHPORT_TRUNK_ALLOWED_RE.match(line)
        if tam:
            current["switchport_mode"] = current["switchport_mode"] or "trunk"
            current["trunk_allowed"] = merge_trunk_allowed(
                current["trunk_allowed"], tam.group(1).strip()
            )
            return
        tnm = _SWITCHPORT_TRUNK_NATIVE_RE.match(line)
        if tnm:
            current["switchport_mode"] = current["switchport_mode"] or "trunk"
            current["trunk_native"] = int(tnm.group(1))
            return

        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            current["lag_member_of"] = f"port-channel{int(cgm.group(1))}"
            return

    # Loop skeleton (open on `interface`, close on dedent, flush at EOF)
    # is the shared codecs/_scanner helper; the vendor regex cascade above
    # — including the in-scratch HSRP sub-block state — stays here.  The
    # terminator replicates the former hand-rolled rule exactly: only a
    # non-indented (column-0) line closes a stanza, so an indented ``!``
    # is consumed as body (not a separator).  Behaviour-identical to the
    # previous loop.
    return scan_stanzas(
        raw.splitlines(),
        is_header=_IFACE_RE.match,
        open_scratch=_open,
        on_line=_on_line,
        build=_build_canonical_interface,
        is_terminator=lambda line: bool(line) and not line[0].isspace(),
    )


def _build_canonical_interface(raw: dict) -> CanonicalInterface:
    """Convert the parse-time scratch dict into a CanonicalInterface."""
    name = raw["name"]
    vrf = raw.get("vrf", "")
    kind = raw.get("kind", "")

    # Management-VRF cascade: a physical-named port bound to the
    # ``management`` VRF is semantically the OOBM port.  mgmt0 already
    # classifies as kind="mgmt" by name, so only promote when the name
    # alone would classify as "physical".  Mirrors iosxe_cli.
    if not kind and _is_mgmt_vrf(vrf):
        from . import port_names as _port_names
        ident = _port_names.classify_port_name(name)
        if ident.kind == "physical":
            kind = "mgmt"

    # HSRP groups (Phase 2c) -> CanonicalVRRPGroup(mode="hsrp"), sorted by
    # group id for deterministic ordering (the round-trip invariant does
    # not normalise vrrp_groups order).
    vrrp_groups = [
        CanonicalVRRPGroup(
            group_id=gid,
            mode="hsrp",
            virtual_ips=list(g.get("virtual_ips", [])),
            priority=g.get("priority", 100),
            preempt=g.get("preempt", False),
            authentication=g.get("authentication", ""),
        )
        for gid, g in sorted(raw.get("hsrp_groups", {}).items())
    ]

    return CanonicalInterface(
        name=name,
        description=raw.get("description", ""),
        enabled=raw.get("enabled", True),
        interface_type=raw.get("type", ""),
        tunnel_type=raw.get("tunnel_type", ""),
        mtu=raw.get("mtu"),
        ipv4_addresses=[
            CanonicalIPv4Address(
                ip=a["ip"],
                prefix_length=a["prefix_length"],
                is_secondary=a.get("is_secondary", False),
                # DAG: the SVI's primary IP IS the distributed anycast
                # gateway, so mirror it into virtual_gateway_address
                # (X == virtual_gateway_address — see the canonical
                # docstring + the IOS-XE SD-Access shape).
                virtual_gateway_address=(
                    a["ip"] if raw.get("fabric_forwarding_anycast") else ""
                ),
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
        vrf=vrf,
        kind=kind,
        switchport_mode=raw.get("switchport_mode"),
        access_vlan=raw.get("access_vlan"),
        dot1q_vlan=raw.get("dot1q_vlan"),  # GAP 7: routed-subif 802.1Q tag
        trunk_allowed_vlans=raw.get("trunk_allowed", []),
        trunk_native_vlan=raw.get("trunk_native"),
        lag_member_of=raw.get("lag_member_of"),
        vrrp_groups=vrrp_groups,
    )


def _lag_sort_key(name: str) -> tuple[int, int, str]:
    """Total-order sort key grouping ``port-channel<N>`` numerically.

    The verbatim *name* is the final tiebreaker so that two case-variants of
    the same channel (e.g. a ``Port-Channel3`` stub and a synthesized
    ``port-channel3``) sort deterministically instead of relying on
    hash-randomized set-iteration order."""
    m = re.match(r"^port-channel(\d+)$", name, re.IGNORECASE)
    return (0, int(m.group(1)), name) if m else (1, 0, name)


def _parse_lags(raw: str) -> list[CanonicalLAG]:
    """Build :class:`CanonicalLAG` records from NX-OS config.

    Two signals, either sufficient (mirrors cisco_iosxe_cli):
      * an ``interface port-channel<N>`` stanza declares the LAG exists;
      * a ``channel-group <N> mode <m>`` line under a physical port
        declares that port a member of ``port-channel<N>``.

    Mode is the first member's mode (NX-OS ``on`` → canonical
    ``static``); an empty LAG keeps :attr:`CanonicalLAG.mode` default.
    """
    members_by_lag: dict[str, list[str]] = {}
    mode_by_lag: dict[str, str] = {}
    declared: set[str] = set()
    current_iface: str | None = None

    def _note_header(name: str) -> None:
        if name.lower().startswith("port-channel"):
            # Canonicalise stub-header casing to the channel-group-synthesised
            # form (lowercase ``port-channel<N>``) so an upstream-rendered
            # ``interface Port-Channel3`` stub and the ``channel-group 3``
            # member binding collapse to ONE CanonicalLAG instead of two
            # case-differing twins.
            m = re.match(r"^port-channel(\d+)$", name, re.IGNORECASE)
            declared.add(f"port-channel{int(m.group(1))}" if m else name.lower())

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
        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            lag_name = f"port-channel{int(cgm.group(1))}"
            mode = _NXOS_LAG_MODE_MAP.get(cgm.group(2).lower(), "active")
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


def _parse_vlans(raw: str) -> list[CanonicalVlan]:
    """Extract VLAN definitions from NX-OS config text.

    NX-OS declares VLANs two ways, often both in one config:

    1. A bare id-list line: ``vlan 1,10,2000`` / ``vlan 10-20`` (declares
       the VLANs exist; no per-VLAN body).
    2. A single-id stanza with a name: ``vlan 10 / name PROD``.

    Both feed the same :class:`CanonicalVlan` set, de-duplicated by id.
    A named single-id stanza wins the ``name`` for its id.
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

    lines = raw.splitlines()
    current_id: int | None = None

    for line in lines:
        tm = _VLAN_TOP_RE.match(line)
        if tm:
            ids = _parse_vlan_list(tm.group(1))
            for vid in ids:
                if 1 <= vid <= 4094:
                    _touch(vid)
            # A single-id ``vlan N`` line opens a stanza whose indented
            # ``name`` sub-command (if any) applies to N.
            current_id = ids[0] if len(ids) == 1 else None
            continue

        if current_id is not None:
            nm = _VLAN_NAME_RE.match(line)
            if nm:
                _touch(current_id).name = nm.group(1).strip()
                continue
            # Any non-indented line closes the stanza.
            if line and not line[0].isspace():
                current_id = None

    return [vlans_by_id[vid] for vid in order]


def _synthesize_vlans_from_svis(intent: CanonicalIntent) -> None:
    """Derive VLAN records from ``interface Vlan<N>`` SVIs.

    Mirrors ``cisco_iosxe_cli._synthesize_vlans_from_svis``: an SVI whose
    VLAN has no top-level ``vlan`` stanza still implies the VLAN exists
    (and carries its L3 config), so create / merge a record.
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


def _make_static_route(
    dest_ip: str,
    prefix: str,
    gw_or_iface: str,
    metric_str: str | None,
    vrf: str = "",
    second_hop: str | None = None,
) -> CanonicalStaticRoute:
    """Build a :class:`CanonicalStaticRoute` from matched NX-OS tokens.

    Shared by the default-VRF top-level scan (:func:`_parse_static_routes`)
    and the per-VRF harvest inside ``vrf context`` blocks
    (:func:`_parse_routing_instances`).  A next-hop that parses as an
    IPv4 address becomes ``gateway``; otherwise it's an egress
    ``interface`` (directly-attached next-hop).  In the two-token
    ``ip route <dest> <iface> <gateway>`` form ``second_hop`` carries the
    trailing dotted-quad gateway and ``gw_or_iface`` is the egress interface
    (HEAD-review L1-9).  The trailing integer (if any) is the route
    preference / administrative distance → ``metric``.
    """
    metric = int(metric_str) if metric_str else 0
    gateway = ""
    iface = ""
    if second_hop:
        iface = gw_or_iface
        gateway = second_hop
    else:
        try:
            ipaddress.IPv4Address(gw_or_iface)
            gateway = gw_or_iface
        except ipaddress.AddressValueError:
            iface = gw_or_iface
    return CanonicalStaticRoute(
        destination=f"{dest_ip}/{prefix}",
        gateway=gateway,
        interface=iface,
        metric=metric,
        vrf=vrf,
    )


def _make_static_route_v6(
    dest: str,
    gw_or_iface: str,
    metric_str: str | None,
    vrf: str = "",
    second_hop: str | None = None,
) -> CanonicalStaticRoute:
    """Build a :class:`CanonicalStaticRoute` from matched ``ipv6 route``
    tokens.  ``dest`` is already ``<prefix>/<len>`` form; a next-hop that
    parses as an IPv6 address becomes ``gateway``, otherwise an egress
    ``interface`` (directly-attached next-hop).  In the two-token
    ``ipv6 route <dest> <iface> <gateway>`` form ``second_hop`` carries the
    trailing IPv6 gateway and ``gw_or_iface`` is the egress interface
    (HEAD-review L1-9)."""
    metric = int(metric_str) if metric_str else 0
    gateway = ""
    iface = ""
    if second_hop:
        iface = gw_or_iface
        gateway = second_hop
    else:
        try:
            ipaddress.IPv6Address(gw_or_iface)
            gateway = gw_or_iface
        except ipaddress.AddressValueError:
            iface = gw_or_iface
    return CanonicalStaticRoute(
        destination=dest,
        gateway=gateway,
        interface=iface,
        metric=metric,
        vrf=vrf,
    )


def _parse_static_routes(raw: str) -> list[CanonicalStaticRoute]:
    """Extract top-level ``ip route`` lines (default VRF) from NX-OS text.

    NX-OS form: ``ip route <dest>/<prefix> <gw> [<pref>]``.  The trailing
    integer (if present) is the route preference / administrative
    distance and maps to :attr:`CanonicalStaticRoute.metric`.

    Per-VRF static routes (indented inside a ``vrf context`` block) do
    NOT match the top-level ``^ip route`` anchor — they are harvested by
    :func:`_parse_routing_instances` (Phase 3) onto
    ``CanonicalStaticRoute.vrf`` and merged into the route list by the
    caller.
    """
    routes: list[CanonicalStaticRoute] = []
    for line in raw.splitlines():
        m6 = _STATIC_ROUTE_V6_RE.match(line)
        if m6:
            routes.append(_make_static_route_v6(
                m6.group(1), m6.group(2), m6.group(4),
                second_hop=m6.group(3),
            ))
            continue
        m = _STATIC_ROUTE_RE.match(line)
        if not m:
            continue
        routes.append(_make_static_route(
            m.group(1), m.group(2), m.group(3), m.group(5),
            second_hop=m.group(4),
        ))
    return routes


def _parse_vxlan(raw: str) -> list[CanonicalVxlan]:
    """Build :class:`CanonicalVxlan` records from NX-OS VXLAN grammar.

    The L2 VLAN↔VNI bindings come from ``vlan <N> / vn-segment <vni>``;
    the switch-level VTEP source comes from ``interface nve1 /
    source-interface <X>`` and broadcasts onto every record (per the
    CanonicalVxlan per-switch convention).  L3VNIs (``vrf context X /
    vni N``) are NOT L2 records — they live on
    :attr:`CanonicalRoutingInstance.l3_vni` (harvested by
    :func:`_parse_routing_instances`).  The ``interface nve1`` ``member
    vni N`` lines carry the L2 overlay multicast group (``mcast-group``),
    harvested onto :attr:`CanonicalVxlan.mcast_group` in either the inline
    (``member vni N mcast-group X``) or the own-sub-line form.  Static
    head-end replication (``member vni N / ingress-replication protocol
    static / peer-ip X``) is harvested onto :attr:`CanonicalVxlan.flood_list`
    (the multicast alternative).  The ``suppress-arp`` sub-flag remains
    parse-discard (declared lossy).
    """
    # Pass 1: vlan_id → vni from ``vlan N / vn-segment <vni>``.
    vn_by_vlan: dict[int, int] = {}
    current_id: int | None = None
    for line in raw.splitlines():
        tm = _VLAN_TOP_RE.match(line)
        if tm:
            ids = _parse_vlan_list(tm.group(1))
            current_id = ids[0] if len(ids) == 1 else None
            continue
        if current_id is not None:
            sm = _VN_SEGMENT_RE.match(line)
            if sm:
                vn_by_vlan[current_id] = int(sm.group(1))
                continue
            if line and not line[0].isspace():
                current_id = None

    # Pass 2: switch-level VTEP source-interface + per-VNI overlay
    # multicast group from ``interface nve1``.  ``member vni N`` carries
    # the L2 ``mcast-group`` in either the inline form or an own-sub-line
    # ``mcast-group X``; ``member vni N associate-vrf`` is the L3VNI
    # binding and is skipped here (harvested from ``vrf context``).
    source_iface = ""
    mcast_by_vni: dict[int, str] = {}
    flood_by_vni: dict[int, list[str]] = {}
    in_nve = False
    current_member_vni: int | None = None
    for line in raw.splitlines():
        im = _IFACE_RE.match(line)
        if im:
            in_nve = im.group(1).lower().startswith("nve")
            current_member_vni = None
            continue
        if line and not line[0].isspace():
            in_nve = False
            current_member_vni = None
            continue
        if not in_nve:
            continue
        sm = _NVE_SOURCE_IF_RE.match(line)
        if sm:
            source_iface = sm.group(1)
            continue
        mm = _NVE_MEMBER_VNI_RE.match(line)
        if mm:
            if mm.group(2):  # inline ``member vni N mcast-group X``
                mcast_by_vni[int(mm.group(1))] = mm.group(2)
                current_member_vni = int(mm.group(1))
            elif "associate-vrf" in line.lower():  # L3VNI — not an L2 record
                current_member_vni = None
            else:  # bare L2 member; an mcast-group may follow on the next line
                current_member_vni = int(mm.group(1))
            continue
        cm = _NVE_MCAST_RE.match(line)
        if cm and current_member_vni is not None:
            mcast_by_vni[current_member_vni] = cm.group(1)
            continue
        pm = _NVE_PEER_IP_RE.match(line)
        if pm and current_member_vni is not None:
            # Static head-end replication flood-list entry for this VNI.
            flood_by_vni.setdefault(current_member_vni, []).append(pm.group(1))

    return [
        CanonicalVxlan(
            vlan_id=vid,
            vni=vn_by_vlan[vid],
            source_interface=source_iface,
            mcast_group=mcast_by_vni.get(vn_by_vlan[vid], ""),
            flood_list=flood_by_vni.get(vn_by_vlan[vid], []),
        )
        for vid in sorted(vn_by_vlan)
    ]


def _parse_snmp(raw: str) -> CanonicalSNMP | None:
    """Extract SNMP config from NX-OS text (v2c community + v3 USM).

    Returns ``None`` when no ``snmp-server`` lines are present so the
    tree doesn't carry an empty stub.  Mirrors cisco_iosxe_cli
    conventions: privacy cipher normalised to the canonical short form,
    opaque keys preserved verbatim, location / contact quote-stripped.
    The ``engineID`` (NX-OS colon-decimal) is preserved verbatim for the
    same-vendor round-trip; it is declared lossy cross-vendor.
    """
    community_m = _SNMP_COMMUNITY_RE.search(raw)
    location_m = _SNMP_LOCATION_RE.search(raw)
    contact_m = _SNMP_CONTACT_RE.search(raw)
    hosts = _SNMP_HOST_RE.findall(raw)
    v3_matches = list(_SNMP_V3_USER_RE.finditer(raw))
    if not (community_m or location_m or contact_m or hosts or v3_matches):
        return None
    snmp = CanonicalSNMP()
    if community_m:
        snmp.community = community_m.group(1).strip()
    if location_m:
        snmp.location = location_m.group(1).strip().strip('"')
    if contact_m:
        snmp.contact = contact_m.group(1).strip().strip('"')
    snmp.trap_hosts = list(hosts)
    for m in v3_matches:
        name, group, auth_p, auth_pw, priv_p, priv_pw, _v2, eng = m.groups()
        snmp.v3_users.append(CanonicalSNMPv3User(
            name=name,
            group=group or "",
            auth_protocol=(auth_p or "").lower(),
            auth_passphrase=auth_pw or "",
            priv_protocol=_normalise_priv_proto(priv_p),
            priv_passphrase=priv_pw or "",
            engine_id=eng or "",
        ))
    return snmp


def _parse_local_users(raw: str) -> list[CanonicalLocalUser]:
    """Extract ``username <name> password <type> <hash> role <role>``.

    NX-OS uses a named ``role`` rather than a numeric privilege; we map
    ``network-admin`` / ``vdc-admin`` -> 15 and everything else -> 1
    (lossy — cross-vendor renderers expecting numeric privilege
    round-trip non-admin roles as 1).  The hash is preserved with its
    type-digit prefix (``5 $5$...``) so a same-vendor round-trip
    reconstructs the line; type 0 (the plaintext marker) is stored bare,
    mirroring cisco_iosxe_cli to avoid the ``password 0 0 X``
    double-prefix bug.
    """
    users: list[CanonicalLocalUser] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        m = _USERNAME_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        hash_type = m.group(2)
        payload = m.group(3)
        role = m.group(4)
        if hash_type and hash_type != "0":
            hashed = f"{hash_type} {payload}"
        else:
            hashed = payload
        users.append(CanonicalLocalUser(
            name=name,
            privilege_level=15 if role.lower() in _NXOS_ADMIN_ROLES else 1,
            hashed_password=hashed,
            role=role,
        ))
    return users
