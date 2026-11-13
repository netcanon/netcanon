"""
Aruba AOS-S parser — ``show running-config`` text to ``CanonicalIntent``.

Extracted from ``codec.py`` during the parse/render split per the
``codecs/README.md`` split-codec convention.  Public functions
(consumed by ``codec.py`` and ``deployment_detect.py``):

* :func:`parse_intent` — one-shot parse entry: raw text in, fully-
  populated :class:`CanonicalIntent` out.
* :func:`without_banner_bodies` — the text with every line of each
  banner emptied, which every reader of the parse is given (the
  codec's Tier-3 rows and the deployment detector among them; the
  probe reads the text as it came).

The parser walks the input line by line, from column 0, and hands the
body of a ``vlan``, ``interface`` or ``vrrp vrid`` stanza to its own
reader (``_parse_vlan_stanza`` / ``_parse_interface_stanza`` /
``_parse_vrrp_group_stanza``).  A stanza ends where the switch ends a
context: at its ``exit`` or an ``end`` (:func:`_leaves`), or at a line
in column 0 that enters another context or that the top of the config
reads (``ip route ...``, ``trunk ...``) -- :func:`_ends_the_stanza`.
Indentation alone ends nothing: HPE describes a context by the
commands that enter and leave it, and a config pasted with its
indentation lost (``name "VLAN2"`` and ``untagged A1`` at column 0
under ``vlan 2``) is read as the one it was.  An ``oobm`` stanza is
the management port's, and nothing in it is read
(:func:`_past_the_oobm_stanza`).

A port's VLANs can be stated from the port's side as well:
``interface 4`` / ``untagged vlan 20``, or ``interface 4 untagged vlan
20`` on one line.  Such a line is the VLAN's own line of the same
meaning, read where it stands, and the later of two lines wins
(:class:`_Memberships`).  A stanza for several ports (``interface
1,3``, ``interface 1-4``) gives its VLAN lines to each port, makes no
record named after the list, and says what else it sets.

A switch has one manager and one operator account, set by ``password
manager`` / ``password operator``: of several lines of a role the last
is the switch's, and the earlier are said.  A line printed without
``include-credentials`` names no user and no value, and is an account
of the role's default name that holds no secret.  The local users
beside them (``aaa authentication local-user``) are read too, at the
privilege level of a ``Level-N`` group and at 1 in any other.  The
two accounts come first in the tree, the local users after them.

Wire-format surfaces handled (mirrors the codec's CapabilityMatrix
``supported`` list): hostname, DNS, NTP, syslog, SNMP (community /
location / contact / trap-host / v3 USM users with separate
``snmpv3 user`` and ``snmpv3 group`` lines), local users, RADIUS
servers, VLANs (with absorbed SVI L3), physical interfaces
(IPv4 + IPv6 with global / link-local scope discriminator; a port
that only a VLAN's list or a ``trunk`` line names has a record like
one with a stanza), LAG
trunk membership, static routes / default-gateway, and **VRRP
groups** (``vrrp vrid N`` sub-block inside ``vlan N`` stanza
with virtual-ip-address / priority / preempt / enable /
authentication mode plaintext-password).  VRRP groups attach to
the synthesised ``VlanN`` :class:`CanonicalInterface` via the
existing SVI-absorption path; an SVI is defensively synthesised
when a VLAN has VRRP but no IP.

The switch's own DHCP server is read too (:class:`_DhcpServer`): a
``dhcp-server pool`` that the server would run becomes a DHCP pool of
the tree, on the ``Vlan<N>`` whose subnet it is where that VLAN states
``dhcp-server``, and on no interface where it is not (a pool HPE's
examples serve to clients a relay forwards).  A pool the server would
not run -- the server is not enabled, or the pool is neither a network
with a range nor a static binding -- is left out and said, and what a
pool states that the tree has no place for is said.

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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ..._radius_secrets import AOSS_ENVELOPE
from ..._tier3_detection import left_out_rows
from ...canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVRRPGroup,
)
from ...limits import census, charge, distinct, tick, ticked
from .._helpers import GrowingIndex, _coalesce_vlan_ids, _mask_to_prefix, _parse_vlan_list, a_few_named
from .._input_shape import detect_input_shape
from .._scanner import Body, ends_anywhere, without_text_bodies
from ..base import ParseError
from .port_names import one_spelling

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Top-level regex constants
# ---------------------------------------------------------------------------


# Capture the whole remainder (quoted-with-escapes or bare); ``_unquote``
# strips the outer pair and reverses ``\"`` / ``\\`` escapes.  A prior
# ``"?([^"\n]+)"?`` form truncated at the first *inner* ``\"`` and so
# shredded any name/description containing an embedded quote.  The capture
# starts with ``\S`` (disjoint from the preceding ``\s+``) and carries no
# ``$`` anchor, so ``\s+`` and ``.`` can never both match a run of spaces
# under backtracking — avoids the ``py/polynomial-redos`` shape a
# ``\s+(.+)$`` form would introduce.
_HOSTNAME_RE = re.compile(r"^hostname\s+(\S.*)", re.IGNORECASE)
# Capture the quoted community token.  AOS-S: `snmp-server community "public" Operator`
_SNMP_COMMUNITY_LINE_RE = re.compile(
    r'^snmp-server\s+community\s+"?([^"\s]+)"?', re.IGNORECASE,
)
# ``snmp-server [contact <text>] [location <text>]``: one line may set
# both (HPE prints ``snmp-server contact "IT" location "1OG"``).  A
# quoted value ends at the quote no backslash escapes (as ``_unquote``
# reads one) and the next keyword may follow; a bare one is the rest of
# the line, as before.
_SNMP_SYSTEM_RE = re.compile(
    r'^snmp-server[^\S\n]+(?=(?:contact|location)[^\S\n])', re.IGNORECASE,
)
_SNMP_SYSTEM_FIELD_RE = re.compile(
    r'(contact|location)[^\S\n]+'
    r'(?:"((?:[^"\\\n]|\\.)*)"[^\S\n]*|(\S.*))',
    re.IGNORECASE,
)
# SNMPv3 user grammar on Aruba AOS-S (observed on 2930F/3810M):
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
    # Accepted Aruba forms (regex handles all via optional mask + distance):
    #   ip route DEST/PREFIX GATEWAY [distance D]
    #   ip route DEST MASK GATEWAY [distance D]
    # Group 1: destination (bare IP or CIDR).  Group 2: optional
    # dotted-decimal mask (legacy form).  Group 3: gateway IP.  Group 4:
    # optional administrative distance (canonical ``metric``) — the
    # ``distance N`` keyword form or a bare trailing integer (AOS-S accepts
    # both).  Without group 4 the route used to FAIL the end-anchor and be
    # silently dropped whole (HEAD-review Fid-F7 aruba distance-drop).  When
    # group 2 is present, group 1 is a bare IP and the mask drives the
    # canonical prefix length; when absent, group 1 is CIDR.
    r"^ip\s+route\s+(\S+)"
    r"(?:\s+(\d+\.\d+\.\d+\.\d+))?"
    r"\s+(\d+\.\d+\.\d+\.\d+)"
    r"(?:\s+(?:distance\s+)?(\d+))?"
    r"\s*$",
    re.IGNORECASE,
)
_IPV6_ROUTE_RE = re.compile(
    # ``ipv6 route <prefix>/<len> <next-hop> [distance D]`` — the IPv6 form
    # (does not overlap ``^ip route``; ``ipv6`` != ``ip``).  Group 2 is the
    # next hop, an address: a word there (``vlan``, ``blackhole``) is
    # read by :data:`_IPV6_ROUTE_NAMED_RE` or said, never taken for a
    # gateway.  Group 3 is the optional administrative distance
    # (canonical ``metric``).
    r"^ipv6\s+route\s+([0-9A-Fa-f:]+/\d+)\s+([0-9A-Fa-f]*:[0-9A-Fa-f:.]*)"
    r"(?:\s+(?:distance\s+)?(\d+))?"
    r"\s*$",
    re.IGNORECASE,
)
#: A route whose next hop is a VLAN or the discard, ``ip route <dest>
#: [<mask>] vlan <id> | blackhole [distance <d>]`` and its IPv6 form.
#: HPE: "The next-hop can be either a gateway IP address, a VLAN, or
#: the keyword "reject" or "blackhole"" (ArubaOS-Switch Multicast and
#: Routing Guide, YC.16.04).  A VLAN is read as its interface,
#: ``Vlan<id>``; ``blackhole`` as the tree's discard, :data:`DISCARD_HOP`.
#: ``reject`` is not read: it discards with an ICMP error to the sender,
#: which the tree's one discard does not say, and the line is said
#: (:data:`_ANY_ROUTE_RE`).  An id or a distance of more digits than the
#: device takes is not read either.
_IP_ROUTE_NAMED_RE = re.compile(
    r"^ip[ \t]+route[ \t]+(\S+)"
    r"(?:[ \t]+(\d+\.\d+\.\d+\.\d+))?"
    r"[ \t]+(?:vlan[ \t]+(\d{1,4})|(blackhole))"
    r"(?:[ \t]+distance[ \t]+(\d{1,3}))?"
    r"[ \t]*$",
    re.IGNORECASE,
)
_IPV6_ROUTE_NAMED_RE = re.compile(
    r"^ipv6[ \t]+route[ \t]+([0-9A-Fa-f:]+/\d+)"
    r"[ \t]+(?:vlan[ \t]+(\d{1,4})|(blackhole))"
    r"(?:[ \t]+distance[ \t]+(\d{1,3}))?"
    r"[ \t]*$",
    re.IGNORECASE,
)
#: Any other static route line -- ``reject``, a ``metric`` or
#: ``tag-value`` option, a next hop of no form above -- is left out and
#: said in a row, never passed in silence.
_ANY_ROUTE_RE = re.compile(r"^ip(?:v6)?[ \t]+route\b", re.IGNORECASE)

#: The name the tree gives a next hop that discards the traffic: the
#: interface IOS-XE, NX-OS, EOS and IOS XR route to.
DISCARD_HOP = "Null0"
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
# The switch's two accounts, one line a role (HPE Access Security
# Guide, AOS-S 16.x, "Setting passwords and usernames"):
#
#   password manager user-name "admin" sha1 "<hash>"
#   password operator user-name "monitor" plaintext "<password>"
#   password manager
#
# The last is how the switch prints a role whose password is set while
# ``include-credentials`` is off: no name, no value.  A typed line may
# leave out ``user-name`` (the names are then ``manager`` and
# ``operator``) or the value (``plaintext`` then asks for it).  The
# switch keeps ONE account a role, and a second line re-points it, so
# of several lines of a role the last is the switch's.
_PASSWORD_LINE_RE = re.compile(
    r'^password[ \t]+(manager|operator)'
    r'(?:[ \t]+user-name[ \t]+("[^"]*"|[^\s"]\S*))?'
    r'(?:[ \t]+(?!user-name(?!\S))([^\s"]\S*)(?:[ \t]+("[^"]*"|[^\s"]\S*))?)?'
    r'[ \t]*$',
    re.IGNORECASE,
)
# A line whose terminal wrapped a long hash onto the next one ends with
# its algorithm, and the quoted hash is the next line that is not blank:
#
#   password manager user-name "admin" sha1
#    "deadbeef0000000000000000000000000000dead"
#
# (:func:`_hash_read`).  Without it a copy-paste of `show
# running-config` lost the account.
_PASSWORD_HASH_CONTINUATION_RE = re.compile(
    r'^\s*"([^"]+)"\s*$',
)
# The local users beside the two accounts, each in an authorization
# group (HPE Access Security Guide, AOS-S 16.x, "Configuring a local
# user for a group").  A 2530 prints the first form with
# ``include-credentials`` on, its hash wrapped onto the next line as
# above, and the second with it off; the third is typed, and asks for
# the password:
#
#   aaa authentication local-user "admin2" group "ADMINS" password sha1 "<hash>"
#   aaa authentication local-user "admin2" group "ADMINS"
#   aaa authentication local-user admin2 group Level-15 password plaintext
_LOCAL_USER_LINE_RE = re.compile(
    r'^aaa[ \t]+authentication[ \t]+local-user[ \t]+("[^"]+"|[^\s"]\S*)'
    r'[ \t]+group[ \t]+("[^"]+"|[^\s"]\S*)'
    r'(?:[ \t]+password[ \t]+([^\s"]\S*)(?:[ \t]+("[^"]*"|[^\s"]\S*))?)?'
    r'[ \t]*$',
    re.IGNORECASE,
)
# Any other line of that command: a password policy of one user
# (``aging-period``, ``min-pwd-length``, ``clear-password-history``), or
# a form the parser does not read.  It sets no account, and is said.
_LOCAL_USER_OTHER_RE = re.compile(
    r"^aaa[ \t]+authentication[ \t]+local-user(?!\S)", re.IGNORECASE,
)
# The switch's own groups ``Level-0`` to ``Level-15``, as it spells
# them: a user in ``Level-15`` has "the same access rights as the
# Manager role", one in ``Level-1`` those of the Operator role (HPE
# Access Security Guide, AOS-S 16.11, role-based access control).
_PREDEFINED_GROUP_RE = re.compile(r"Level-(1[0-5]|[0-9])")
# AOS-S RADIUS forms (16.10 Access Security Guide):
#   radius-server host <ip>
#   radius-server host <ip> key "<secret>"
#   radius-server host <ip> encrypted-key "<base64 AES-256 blob>"
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
# ``key`` and ``encrypted-key`` are two words: a ``key`` that follows a
# hyphen is the end of ``encrypted-key``, whose blob the pattern before
# 2026-10 read as the literal secret.
_RADIUS_INLINE_KEY_RE = re.compile(
    r'(?<![\w-])(key|encrypted-key)\s+"?([^"]*)"?\s*$',
    re.IGNORECASE,
)
# Global shared-secret fallback (applies to hosts without inline key):
#   radius-server key "<secret>"
# and, read the same way as the host line's documented ``encrypted-key``
# (the global form is inferred from it, not seen in a vendor document):
#   radius-server encrypted-key "<blob>"
_RADIUS_KEY_GLOBAL_RE = re.compile(
    r'^radius-server\s+(key|encrypted-key)\s+"?([^"]*)"?\s*$',
    re.IGNORECASE,
)


def _radius_key(word: str, value: str) -> str:
    """The canonical value of ``key "<secret>"`` or ``encrypted-key "<blob>"``.

    ``encrypted-key`` is AES-256 under the switch's ``encrypt-credentials``
    key (16.10 Access Security Guide): a form only AOS-S reads, carried
    behind :data:`AOSS_ENVELOPE` so that no other platform takes it for
    the secret.
    """
    value = value.strip().strip('"')
    if value and word.lower() == "encrypted-key":
        return f"{AOSS_ENVELOPE}{value}"
    return value
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

_VLAN_NAME_RE = re.compile(r"^name\s+(\S.*)", re.IGNORECASE)
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
_IFACE_NAME_RE = re.compile(r"^name\s+(\S.*)", re.IGNORECASE)

# VRRP grammar — nested inside ``vlan N`` stanzas, with a global
# ``router vrrp`` enable.
#
#   router vrrp
#   vlan 100
#      ip address 10.0.100.1 255.255.255.0
#      vrrp vrid 10
#         owner | backup
#         virtual-ip-address 10.0.100.254
#         priority 110
#         preempt
#         enable
#         authentication mode plaintext-password "X"
#         exit
#      exit
#
# Aruba AOS-S only mounts VRRP inside ``vlan N`` blocks (the VLAN
# IS the SVI on this platform).  The canonical model attaches the
# group to the synthesised ``Vlan<N>`` :class:`CanonicalInterface`
# created by the SVI-absorption path — see _svi_absorption.py.
#
# The vrid header is ``vrrp vrid N`` (NO ``ip`` prefix) — verified
# against the AOS-S 16.10 "Basic configuration process" CLI reference
# (arubanetworking.hpe.com/techdocs/AOS-S/16.10/MRG) and four
# independent operator captures (E5406/5406R-ZL2/E5400 + AOS-S 16.11
# docs).  The optional ``(?:ip\s+)?`` keeps the older / mis-documented
# ``ip vrrp vrid`` form parseable too (back-compat — the codec emitted
# it through v0.1.8).  ``virtual-ip-address`` tolerates the legacy
# K.15 ``<ip> <mask>`` two-token form (mask dropped — the canonical
# carries the bare VIP); 16.x emits the bare ``<ip>``.
_VRRP_VRID_HEADER_RE = re.compile(
    r"^(?:ip\s+)?vrrp\s+vrid\s+(\d+)\s*$", re.IGNORECASE,
)
_VRRP_VIRTUAL_IP_RE = re.compile(
    r"^virtual-ip-address\s+(\S+)(?:\s+[\d.]+)?\s*$", re.IGNORECASE,
)
_VRRP_PRIORITY_RE = re.compile(
    r"^priority\s+(\d+)\s*$", re.IGNORECASE,
)
# AOS-S grammar for plaintext VRRP authentication:
#   authentication mode plaintext-password "X"
# Captured verbatim; stored as ``"plain:X"`` per the
# :class:`CanonicalVRRPGroup.authentication` opaque-token convention.
# ``(\S.*)`` NOT ``"?([^"\n]+?)"?\s*$``: the lazy body + trailing ``\s*$``
# backtrack O(n^2) on a space-padded line (the #337 ReDoS shape).  The value
# is now captured verbatim (incl. any surrounding quotes) and the consumer
# ``.strip().strip('"')``s it — behaviour-identical to the old inline quote/
# whitespace trimming, but linear.
_VRRP_AUTH_PLAINTEXT_RE = re.compile(
    r'^authentication\s+mode\s+plaintext-password\s+(\S.*)$',
    re.IGNORECASE,
)

# A port's VLANs, stated from the port's side.  In an ``interface``
# stanza (HPE's examples print it in ``show running-config interface
# <port>``; the full config states the same under ``vlan N``):
#
#   interface 3
#      tagged vlan 10,20
#      no untagged vlan 1
#      exit
#
# and on one line at the top, for a list of ports (vendor syntax:
# ``[no] interface <port-list> <tagged | untagged | forbid> vlan
# <vlan-id-list>``):
#
#   interface 1,6,7-10 tagged vlan 1,3,5-10
#
# ``forbid`` is not read in either context, as it is not under ``vlan
# N``: it makes no membership, and GVRP is not modelled.
_PORT_VLAN_LINE_RE = re.compile(
    r"^(no[ \t]+)?(tagged|untagged)[ \t]+vlan[ \t]+(\S+)[ \t]*$", re.IGNORECASE,
)
_GLOBAL_PORT_VLAN_RE = re.compile(
    r"^(no[ \t]+)?interface[ \t]+(\S+)[ \t]+(tagged|untagged)[ \t]+vlan[ \t]+(\S+)[ \t]*$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Where a stanza ends
# ---------------------------------------------------------------------------
#
# The switch reads a configuration as CLI commands.  A command that
# enters a context (``vlan 10``, ``interface 3``, ``oobm``) moves into
# it, ``exit`` returns to the context before, ``end`` to the Manager
# level, and a command that enters another context leaves the open
# one.  No HPE switch guide says indentation plays a part.  HPE's
# examples, and every committed capture a switch printed, indent their
# body lines and close each stanza with ``exit``; whether any release
# prints otherwise is not established.  A config that reached this
# parser through a forum, a web page or a template can have lost the
# indentation and kept the ``exit`` lines.

#: ``oobm``: the context of the out-of-band management port.
_OOBM_HEADER_RE = re.compile(r"^oobm[ \t]*$", re.IGNORECASE)

#: ``interface 1,3``: a context for several ports, which
#: :data:`_IFACE_HEADER_RE` does not take (a range, ``interface 1-4``,
#: it does).  Either is read as a context for the ports it names
#: (:func:`_parse_port_list`), and no record is named after the list.
_PORT_LIST_HEADER_RE = re.compile(
    r"^interface[ \t]+([A-Za-z0-9][A-Za-z0-9./\-]*(?:,[A-Za-z0-9][A-Za-z0-9./\-]*)+)[ \t]*$",
    re.IGNORECASE,
)

#: ``interface loopback 1``: a loopback, as the switch prints it, with a
#: space (HPE, "Managing loopback interfaces": ``interface loopback
#: <0-7>``; the context's prompt is ``lo-1``).  :data:`_IFACE_HEADER_RE`
#: takes one word and read none of it.  ``interface loopback1`` is read
#: the same.  The record is ``loopback1``: a port name is one word.
_LOOPBACK_HEADER_RE = re.compile(
    r"^interface[ \t]+loopback[ \t]*(\d+)[ \t]*$", re.IGNORECASE,
)

#: An address on a loopback, given with no mask: "when you configure an
#: IP address for a loopback interface, you do not specify a network
#: mask" (HPE, "Configuring a loopback interface"), and the switch
#: prints it so (``ip address 10.1.1.1``).  The mask is
#: 255.255.255.255.  An IPv6 address on a loopback is given with no
#: prefix either.  Read only in a loopback's stanza
#: (:func:`_read_a_host_address`).
_IP_ADDR_HOST_RE = re.compile(
    r"^ip[ \t]+address[ \t]+(\d+\.\d+\.\d+\.\d+)$", re.IGNORECASE,
)
_IPV6_ADDR_HOST_RE = re.compile(
    r"^ipv6[ \t]+address[ \t]+([0-9A-Fa-f]*:[0-9A-Fa-f:.]*)$", re.IGNORECASE,
)

#: A line that enters a context the top of the config reads nothing
#: of.  It still ends the context that was open.  (``vlan N``,
#: ``interface X``, ``oobm`` and ``dhcp-server pool <name>`` end it as
#: lines of the top, :data:`_TOP_LEVEL_LINES`; ``interface`` is here for
#: a name the header patterns do not take.)
_OPENS_A_CONTEXT_RE = re.compile(
    r"^(?:interface[ \t]+\S+|router[ \t]+\S+|stacking|vsf"
    r"|device-profile[ \t]+\S+[ \t]+\S+)[ \t]*$",
    re.IGNORECASE,
)


def _leaves(stripped: str) -> str:
    """``"exit"`` or ``"end"`` if *stripped* is that command, in any
    letter case, and ``""`` if it is not.  HPE: ``exit`` returns to the
    context before; ``end`` to the Manager level, out of every context
    that is open."""
    word = stripped.lower()
    return word if word in ("exit", "end") else ""


#: The commands of the ``oobm`` context whose words mean something else
#: outside it (HPE: the OOBM interface's address and gateway are
#: configured "within the OOBM context"; their global forms are ``oobm
#: ip address`` and ``oobm ip default-gateway``).  None of them ends the
#: stanza, whatever it looks like: ``interface enable`` enters no
#: context there.
_OOBM_WORDS_RE = re.compile(
    r"^(?:ip[ \t]+(?:address|default-gateway)|enable|disable"
    r"|interface[ \t]+(?:enable|disable|speed-duplex))\b",
    re.IGNORECASE,
)

#: ``member N`` alone on its line: a stack member's own context, nested
#: in ``oobm``, with an ``exit`` of its own.
_MEMBER_BLOCK_RE = re.compile(r"^member[ \t]+\S+[ \t]*$", re.IGNORECASE)

#: ``dhcp-server pool <name>``: the context of a pool of the switch's
#: own DHCP server (HPE: ``[no] dhcp-server pool <POOL-NAME>``).  The
#: name is quoted, as the switch prints it, or a word.  What follows
#: the name on the line is a statement of the pool, given from the top
#: as the CLI takes a context's command with the context's words before
#: it; the context is not entered then.
_DHCP_POOL_HEADER_RE = re.compile(
    r'^dhcp-server[ \t]+pool[ \t]+("(?:[^"\\]|\\.)*"|[^"\s]\S*)(?:[ \t]+(\S.*))?$',
    re.IGNORECASE,
)

#: Any other line of the top that begins ``dhcp-server`` and a word:
#: ``dhcp-server enable`` and ``disable`` (HPE: ``[no] dhcp-server
#: [enable | disable]``, "Defaults to disabled"), and the server's own
#: settings (``conflict-logging``, ``ping``, ``database``).  The word
#: is all of it that is read.  ``dhcp-server`` alone is a VLAN's line
#: (:data:`_VLAN_DHCP_SERVER_RE`), and no line of the top.
_DHCP_SERVER_LINE_RE = re.compile(
    r"^(no[ \t]+)?dhcp-server[ \t]+([^\s\"]+)(?![^ \t])", re.IGNORECASE,
)

#: ``dhcp-server`` alone, in a ``vlan`` stanza: the switch's DHCP server
#: serves on that VLAN.
_VLAN_DHCP_SERVER_RE = re.compile(r"^dhcp-server$", re.IGNORECASE)

#: Every pattern the top-level loop of :func:`parse_intent` reads a line
#: with.  A line one of them matches is the top's, and a stanza ends at
#: it.  It is this one tuple that :func:`_ends_the_stanza` asks, and a
#: test holds it to the patterns the loop calls.
_TOP_LEVEL_LINES: tuple[re.Pattern[str], ...] = (
    _HOSTNAME_RE,
    _SNMP_COMMUNITY_LINE_RE,
    _SNMP_SYSTEM_RE,
    _SNMP_HOST_RE,
    _SNMPV3_USER_RE,
    _SNMPV3_GROUP_BIND_RE,
    _DNS_SERVER_RE,
    _SNTP_SERVER_RE,
    _DEFAULT_GW_RE,
    _IPV6_ROUTE_RE,
    _IPV6_ROUTE_NAMED_RE,
    _IP_ROUTE_RE,
    _IP_ROUTE_NAMED_RE,
    _ANY_ROUTE_RE,
    _RADIUS_HOST_RE,
    _RADIUS_KEY_GLOBAL_RE,
    _PASSWORD_LINE_RE,
    _LOCAL_USER_LINE_RE,
    _LOCAL_USER_OTHER_RE,
    _TRUNK_LINE_RE,
    _GLOBAL_PORT_VLAN_RE,
    _OOBM_HEADER_RE,
    _DHCP_POOL_HEADER_RE,
    _DHCP_SERVER_LINE_RE,
    _VLAN_HEADER_RE,
    _LOOPBACK_HEADER_RE,
    _PORT_LIST_HEADER_RE,
    _IFACE_HEADER_RE,
)


def _ends_the_stanza(line: str, stripped: str) -> bool:
    """Whether *line*, met in the body of a ``vlan``, ``interface`` or
    ``vrrp vrid`` stanza, ends it.  The line is then read again at the
    top of the config.  (``exit`` and ``end`` are not asked about here:
    each ends the stanza, and is used up -- :func:`_leaves`.)  The
    ``oobm`` stanza asks it too, of a line that is no word of its own
    (:func:`_past_the_oobm_stanza`).

    A line that begins with white space is the stanza's.  A line in
    column 0 ends the stanza if it enters a context
    (:data:`_OPENS_A_CONTEXT_RE`) or if the top of the config has a
    handler for it (:data:`_TOP_LEVEL_LINES`).  Any other line in column
    0 is the stanza's: read if it is one of the stanza's own lines,
    passed if not.  So ``vlan 2`` / ``name "VLAN2"`` / ``untagged A1`` /
    ``exit``, every line at column 0, is the stanza it is indented.

    A line of the top's inside a stanza that has lost its indentation
    (``ip route ...`` between two of a VLAN's lines) is read as the
    line it is, and the stanza ends there: the lines after it are read
    at the top.  Whether the switch stays in the VLAN's context after
    such a command is not established.

    Args:
        line: The line as the config has it.
        stripped: The same line without its white space at either end.
    """
    if line[0].isspace():
        return False
    return bool(_OPENS_A_CONTEXT_RE.match(stripped)) or any(
        pattern.match(stripped) for pattern in _TOP_LEVEL_LINES
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _unescape(value: str) -> str:
    """Reverse :func:`~netcanon.migration.codecs.aruba_aoss.render._esc`.

    Single left-to-right pass: a backslash consumes the next character
    literally (``\\\\`` → ``\\``, ``\\"`` → ``"``), the exact inverse of
    doubling backslashes then escaping quotes.  A trailing lone backslash
    is emitted verbatim."""
    out: list[str] = []
    i = 0
    n = len(value)
    while i < n:
        c = value[i]
        if c == "\\" and i + 1 < n:
            out.append(value[i + 1])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _unquote(s: str) -> str:
    """Strip surrounding ASCII quotes and reverse render-side escaping.

    AOS-S free-text values (hostname / vlan name / interface description)
    are emitted double-quoted with ``\\"`` / ``\\\\`` escapes (see
    ``render._esc``); this strips the outer pair and reverses those
    escapes so a value containing a quote or backslash round-trips
    byte-stable.  A bare (unquoted) value — as some real AOS-S captures
    emit — is returned stripped, unescaped-as-is."""
    s = s.strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return _unescape(s[1:-1])
    return s


def _word(token: str | None) -> str:
    """*token* without the quotes around it, if it has them: a user's
    name or a hash, which the renderer writes between quotes and never
    escapes.  ``""`` for no token."""
    if token and len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1]
    return token or ""


def _hash_read(alg: str | None, token: str | None, lines: list[str], at: int) -> tuple[str, int]:
    """An account's ``hashed_password`` as the line at *at* gives it,
    and the index of the line to read next.

    Args:
        alg: The algorithm the line names, or ``None``: the switch
            printed that a password is set and not what it is.
        token: The value after the algorithm, or ``None``.  A line that
            ends with its algorithm had its value wrapped onto the next
            line that is not blank, if that line is a quoted value and
            nothing else (``_PASSWORD_HASH_CONTINUATION_RE``).
        lines: The config's lines.
        at: The index of the line.

    Returns:
        ``""`` for no algorithm; ``"<alg>:<value>"``; or ``"<alg>:"``
        for an algorithm with no value (a typed ``plaintext``, which
        asks for it, or a hash a paste lost), which holds no secret
        either.
    """
    if not alg:
        return "", at + 1
    if token is not None:
        return f"{alg.lower()}:{_word(token)}", at + 1
    after = at + 1
    while after < len(lines) and not lines[after].strip():
        tick()
        after += 1
    if after < len(lines):
        wrapped = _PASSWORD_HASH_CONTINUATION_RE.match(lines[after])
        if wrapped:
            return f"{alg.lower()}:{wrapped.group(1)}", after + 1
    return f"{alg.lower()}:", at + 1


def _privilege_of_group(group: str) -> int:
    """The privilege level a local user in *group* is read at: ``N`` in
    the switch's own ``Level-N``, and 1 in any other.  What another
    group allows is in its ``aaa authorization group`` rules, which are
    not translated; and the default groups ``manager`` and ``operator``
    are read at 1 as well, the level with the fewer rights."""
    level = _PREDEFINED_GROUP_RE.fullmatch(group)
    return int(level.group(1)) if level else 1


#: AOS-Switch (ProVision) release from the ``Created on release #`` banner
#: comment, e.g. ``; JL258A Configuration Editor; Created on release
#: #WC.16.10.0005`` → ``WC.16.10.0005``.  Rendered templates omit the
#: release token (``Created via template render``) → honest ``""``.
_VERSION_RE = re.compile(r"Created on release #(\S+)", re.MULTILINE)


def _extract_version(raw: str) -> str:
    """Return the AOS-Switch release from the config-editor banner comment.

    Stored as :attr:`CanonicalIntent.source_version` (metadata only); the
    render path does not echo it, so it is informational.  Returns ``""``
    when no release banner is present.
    """
    m = _VERSION_RE.search(raw)
    return m.group(1) if m else ""


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
    r"^(?:[Tt][Rr][Kk]\d+|\d+(?:/[A-Za-z]?\d+)?|[A-Za-z]\d+)$",
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
    # A LAG has one name in the tree, whatever case the line has it in.
    return list(dict.fromkeys(one_spelling(name) for name in result))


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
    hi.  A range is the ports it names, however many: nothing here
    knows which ports the switch has.  What it makes is counted
    before it is made, and a range past the limit in force is
    refused (:class:`~netcanon.migration.limits.LimitExceeded`).
    Up to 0.7.7 a range of more than 1,025 ports was read as its two
    end ports, in a job that said nothing of it.

    Pre-:commit: WC.16.11.0025 2930M fixture landing, the old
    regex ``^([A-Za-z]*)(\\d+)(?:/(\\d+))?$`` silently dropped the
    slot prefix when expanding ``1/1-1/47`` (produced ``["1"]``) and
    failed to match ``1/A1-1/A4`` at all (returned the two endpoints
    verbatim, losing intermediate ports).  Both bugs had slipped
    past the round-trip-stable invariant because the format path
    was symmetrically broken.  Symptomatic VLANs in several shipped
    Aruba fixtures had near-empty port-membership lists on parse;
    the canonical coverage was materially under-reported.
    """
    # ``(?<!\d)``: the number begins where the trailing digits begin,
    # which is where the lazy prefix would stop anyway -- but without
    # it a token of digits and then a letter is tried at every digit.
    m_lo = re.match(r"^(.*?)(?<!\d)(\d+)$", lo)
    m_hi = re.match(r"^(.*?)(?<!\d)(\d+)$", hi)
    if not m_lo or not m_hi:
        return [lo, hi]   # no trailing digits — pass through as-is
    prefix_lo, num_lo = m_lo.group(1), int(m_lo.group(2))
    prefix_hi, num_hi = m_hi.group(1), int(m_hi.group(2))
    if prefix_lo != prefix_hi or num_hi < num_lo:
        return [lo, hi]
    # Counted before the names are made, whatever the line then does
    # with them: ``1-999999999`` is a billion ports in a dozen bytes,
    # and is refused here before one of them is made.  Then the
    # DIFFERENT ports that ranges have named so far: a range can name
    # ports no device has, and every one of them is a port to
    # everything that reads the tree.  (What a range makes before that
    # second count is what the first one charged.)
    charge("memberships", num_hi - num_lo + 1, f"{lo}-{hi}")
    names = [f"{prefix_lo}{n}" for n in range(num_lo, num_hi + 1)]
    distinct("ports", names, f"{lo}-{hi}")
    return names


def _stated_once(items: list, key) -> list:
    """*items* without the later of two that have one *key*, in the
    order they were stated."""
    kept: dict = {}
    for item in items:
        kept.setdefault(key(item), item)
    return list(kept.values())


def _a_record_for_every_port_named(intent: CanonicalIntent) -> None:
    """Give a record to every port the config names and no ``interface``
    stanza configures.

    The device prints an ``interface`` stanza only for a port that has
    a setting of its own.  Every other port is in the config all the
    same: in the ``untagged`` and ``tagged`` lists of its VLANs, or on
    a ``trunk`` line as a member of a LAG.  A port-centric target
    writes a port's VLANs and its LAG on the port's own stanza, from
    its record, so a port with no record is a port in no line of that
    output -- its memberships with it, in a job that reports nothing.

    The record is the one a stanza with no lines would have made (a
    port is enabled unless a line says otherwise, and its type comes
    from its name), so that a config and its own rendering parse
    alike.  Records go on the end, in the order an operator would
    count the ports.

    Called once the lists have been counted (``census``): a port named
    here was held to the ``ports`` limit while it had no record, and
    each record is counted as it is made (``CanonicalInterface``).
    Nothing is made from a few bytes that the lists do not already
    hold a name for.
    """
    from ...canonical.transforms import _natural_port_sort_key

    have = {iface.name for iface in intent.interfaces}
    named: set[str] = set()
    for vlan in intent.vlans:
        named.update(vlan.untagged_ports)
        named.update(vlan.tagged_ports)
    member_of: dict[str, str] = {}
    for lag in intent.lags:
        for member in lag.members:
            member_of.setdefault(member, lag.name)
    named.update(member_of)
    for name in sorted(named - have, key=_natural_port_sort_key):
        tick()
        intent.interfaces.append(CanonicalInterface(
            name=name,
            enabled=True,
            interface_type=_infer_iface_type(name),
            lag_member_of=member_of.get(name),
        ))


def _one_name_per_lag(intent: CanonicalIntent) -> None:
    """Give a LAG one name everywhere the tree refers to it.

    The device writes one LAG two ways: ``trunk 51-52 trk1 lacp`` where
    it is defined, and ``Trk1`` where a VLAN lists it or an ``interface
    Trk1`` stanza configures it.  AOS-S names have no letter case, so
    that is one LAG -- but two names in the tree are two ports to
    everything downstream: the rename map has a key for each, an entry
    for one leaves the other where it was, and anything that counts
    source names on a target counts two (the rename modal showed the
    LAG as a collision and would not apply).

    The one name is ``trk<n>``, in lower case
    (:func:`~.port_names.one_spelling`): what a ``trunk`` line the
    device printed says, and so what the tree has always called the
    LAG.  It does not depend on a definition being in the text, nor on
    how a hand spelt one: ``TRK1`` on a ``trunk`` line is the same
    LAG, and a name that is not a trunk's (``A1``) is nobody's other
    spelling.  The renderer writes each form where the device does,
    whatever the tree holds.

    The lines that hold most references are read that way to begin
    with -- a port list, a ``trunk`` line, an ``interface`` header --
    so that what the parser does with a name while it reads (a port
    moved by a later ``untagged``, a stanza met twice) is done to one
    name.  This pass is for every other place a port name is kept, by
    the same sweep the port translator uses: it cannot be a field
    short of it.  AOS-S has no unit suffix, so none is followed.
    """
    from ...canonical.port_names import rewrite_port_names

    rewrite_port_names(intent, one_spelling, units=False)
    # Two lines of one stanza can name a port twice between them.
    for vlan in intent.vlans:
        vlan.tagged_ports = list(dict.fromkeys(vlan.tagged_ports))
        vlan.untagged_ports = list(dict.fromkeys(vlan.untagged_ports))


#: What the SNMPv3 user index reads while a config has no SNMP section.
_NO_USERS: list[CanonicalSNMPv3User] = []


def _build_lag_from_trunk_line(m: re.Match[str]) -> CanonicalLAG | None:
    """Convert a ``trunk <ports> <name> <type>`` regex match to a CanonicalLAG."""
    port_list_text, trunk_name, trunk_type = m.group(1), m.group(2), m.group(3)
    members = _parse_port_list(port_list_text)
    mode = _AOS_TRUNK_TYPE_TO_MODE.get(trunk_type.lower(), "static")
    return CanonicalLAG(
        name=one_spelling(trunk_name),
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
    if re.fullmatch(r"loopback\d+", lower):
        # The record ``interface loopback <N>`` makes.
        return "ianaift:softwareLoopback"
    return "ianaift:ethernetCsmacd"


# ---------------------------------------------------------------------------
# Stanza parsers
# ---------------------------------------------------------------------------


def _stated_since(ports: list[str], gone: dict[str, int]) -> list[str]:
    """*ports* without the entries a ``no`` line took out: for each
    port in *gone*, those above the place the list had reached when
    its last ``no`` line was read.  An entry stated after that line is
    kept, as it was when the line removed what it found."""
    return [port for at, port in enumerate(ports) if at >= gone.get(port, 0)]


def _parse_vlan_stanza(
    lines: list[str], start: int, vlan_id: int, dhcp_vlans: set[int] | None = None,
) -> tuple[
    CanonicalVlan, list[CanonicalVRRPGroup], list[CanonicalIPv6Address], int
]:
    """Parse a ``vlan N`` stanza starting at *start* (body line).

    Returns the parsed :class:`CanonicalVlan`, the list of nested
    :class:`CanonicalVRRPGroup` instances (one per ``vrrp vrid N``
    sub-block), the list of SVI :class:`CanonicalIPv6Address` records
    (``ipv6 address`` inside the stanza — #10), and the index of the
    first line AFTER the stanza's outer ``exit``.

    VRRP groups and SVI IPv6 addresses parse here (rather than at the
    top level) because AOS-S nests them INSIDE the ``vlan N`` stanza —
    the VLAN is the SVI on this platform.  Both attach to the
    synthesised ``Vlan<N>`` :class:`CanonicalInterface` by the caller
    (the SVI-absorption path in :func:`parse_intent`); ``CanonicalVlan``
    itself is IPv4-only.

    Args:
        lines: The config's lines.
        start: The index of the stanza's first body line.
        vlan_id: The VLAN's id.
        dhcp_vlans: Given *vlan_id* if the stanza has a ``dhcp-server``
            line (the switch's DHCP server serves on the VLAN).
    """
    vlan = CanonicalVlan(id=vlan_id)
    # ``no untagged`` takes a port out of everything stated above it.
    # How long the list is when such a line is read is kept for the
    # port, and the entries above that mark leave the list once, when
    # the stanza ends: the list used to be written again whole for
    # every such line, which cost the square of the lines one VLAN
    # was given.
    untagged_gone: dict[str, int] = {}
    tagged_gone: dict[str, int] = {}
    vrrp_groups: list[CanonicalVRRPGroup] = []
    svi_ipv6: list[CanonicalIPv6Address] = []
    i = start
    while i < len(lines):
        tick()
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith(";"):
            i += 1
            continue
        # The stanza ends at its `exit` or an `end`, or at a line of
        # another context or of the top (`_ends_the_stanza`) -- not at
        # a line that has merely lost its indentation.
        if _leaves(stripped):
            i += 1
            break
        if _ends_the_stanza(line, stripped):
            break

        nm = _VLAN_NAME_RE.match(stripped)
        if nm:
            vlan.name = _unquote(nm.group(1))
            i += 1
            continue

        um = _UNTAGGED_RE.match(stripped)
        if um:
            if um.group(1):  # "no untagged ..." — strip ports
                for port in _parse_port_list(um.group(2)):
                    untagged_gone[port] = len(vlan.untagged_ports)
            else:
                vlan.untagged_ports.extend(_parse_port_list(um.group(2)))
            i += 1
            continue

        tm = _TAGGED_RE.match(stripped)
        if tm:
            if tm.group(1):  # "no tagged ..."
                for port in _parse_port_list(tm.group(2)):
                    tagged_gone[port] = len(vlan.tagged_ports)
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
                prefix_length=_mask_to_prefix(ip_mask.group(2), vendor="aruba_aoss"),
            ))
            i += 1
            continue

        # (#10) Vlan-context IPv6 SVI address.  CanonicalVlan is
        # IPv4-only, so — exactly like VRRP below — collect it here and
        # let the caller attach it to the synthesised ``Vlan<N>``
        # CanonicalInterface (the canonical SVI home).  Previously the
        # line was skipped outright → a SILENT, UNDECLARED drop on both
        # the aoss round-trip and any cross-vendor render.  ``ipv6
        # address dhcp full`` has no static address and doesn't match
        # the regex, so it still falls through.
        v6m = _IPV6_ADDR_RE.match(stripped)
        if v6m:
            scope = "link-local" if v6m.group(3) else "global"
            try:
                svi_ipv6.append(CanonicalIPv6Address(
                    ip=v6m.group(1),
                    prefix_length=int(v6m.group(2)),
                    scope=scope,
                ))
            except ValueError:
                pass
            i += 1
            continue

        # VRRP sub-block — `vrrp vrid N` opens a nested stanza
        # terminated by its own `exit`.  See _parse_vrrp_group_stanza
        # for the body grammar.  The group attaches to the synthesised
        # Vlan<N> CanonicalInterface (NOT to the CanonicalVlan itself)
        # in the caller, matching the cross-vendor canonical surface
        # which models VRRP as an interface property.
        vrid_m = _VRRP_VRID_HEADER_RE.match(stripped)
        if vrid_m:
            gid = int(vrid_m.group(1))
            group, next_i = _parse_vrrp_group_stanza(lines, i + 1, gid)
            vrrp_groups.append(group)
            i = next_i
            continue

        if dhcp_vlans is not None and _VLAN_DHCP_SERVER_RE.match(stripped):
            dhcp_vlans.add(vlan_id)

        i += 1
    if untagged_gone:
        vlan.untagged_ports = _stated_since(vlan.untagged_ports, untagged_gone)
    if tagged_gone:
        vlan.tagged_ports = _stated_since(vlan.tagged_ports, tagged_gone)
    return vlan, vrrp_groups, svi_ipv6, i


def _parse_vrrp_group_stanza(
    lines: list[str], start: int, gid: int,
) -> tuple[CanonicalVRRPGroup, int]:
    """Walk the body of ``vrrp vrid N`` until the inner ``exit``.

    Returns the parsed :class:`CanonicalVRRPGroup` and the index of
    the first line AFTER the sub-block's ``exit``.

    Body grammar (AOS-S 16.10 "Basic configuration process" CLI ref):

      * ``owner``                   — VIP owner → ``priority = 255``
        (RFC 5798 address-owner priority; now representable)
      * ``backup``                  — explicit backup role (no field)
      * ``virtual-ip-address X``    — append to ``virtual_ips``
        (legacy ``X <mask>`` two-token form tolerated; mask dropped)
      * ``priority N``              — integer 1-254
      * ``preempt``                 — presence = enabled
      * ``enable``                  — group is active (implicit on
                                       canonical; tracked but no field)
      * ``authentication mode plaintext-password "X"``
                                    — opaque, stored as ``"plain:X"``

    Default ``preempt`` on AOS-S is False — operators must explicitly
    add ``preempt`` to opt in.  This DIFFERS from the canonical
    default of True (which matches Cisco/Arista); we override to
    False on entry and the parser flips it when ``preempt`` appears.
    """
    # AOS-S vendor-default for preempt is False (unlike Cisco's True);
    # the canonical default is True so we override here.
    group = CanonicalVRRPGroup(group_id=gid, mode="vrrp", preempt=False)
    i = start
    while i < len(lines):
        tick()
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            i += 1
            continue
        # Inner ``exit`` closes the vrrp vrid sub-block.  ``end``
        # closes it and the VLAN's stanza too: it is left for the
        # VLAN's reader, which ends there.
        left = _leaves(stripped)
        if left == "exit":
            return group, i + 1
        if left:
            return group, i
        # A line of another context or of the top ends it as well (a
        # paste without its `exit`); the VLAN's stanza then meets the
        # same line and ends there too.
        if _ends_the_stanza(line, stripped):
            return group, i

        vip = _VRRP_VIRTUAL_IP_RE.match(stripped)
        if vip:
            group.virtual_ips.append(vip.group(1))
            i += 1
            continue

        pri = _VRRP_PRIORITY_RE.match(stripped)
        if pri:
            group.priority = int(pri.group(1))
            i += 1
            continue

        # ``owner`` declares this switch the VIP owner — VRRP reserves
        # priority 255 for the owner (RFC 5798 §6.1).  ``CanonicalVRRPGroup.
        # priority`` now spans the full 0-255 union, so ``owner`` maps to its
        # true value 255 (was clamped to 254 while 255 was unrepresentable);
        # render inverts it back to ``owner`` so the role round-trips.
        # ``backup`` is the complementary explicit role with no priority
        # implication — consume it (priority stays whatever ``priority N``
        # set, or the default).
        if stripped.lower() == "owner":
            group.priority = 255
            i += 1
            continue
        if stripped.lower() == "backup":
            i += 1
            continue

        if stripped.lower() == "preempt":
            group.preempt = True
            i += 1
            continue

        if stripped.lower() == "no preempt":
            group.preempt = False
            i += 1
            continue

        if stripped.lower() == "enable":
            # ``enable`` flag is implicit on the canonical model
            # (groups in the tree are considered active by default).
            # We don't carry a separate per-group ``enabled`` field;
            # the absence of a group from the tree IS its disabled
            # state.  Consume and skip.
            i += 1
            continue

        if stripped.lower() == "disable":
            # Pathological case — explicitly disabled groups still
            # parse into the tree (so cross-vendor migration sees
            # them); the renderer is free to emit them without
            # ``enable`` to mirror.  Consume and skip.
            i += 1
            continue

        auth = _VRRP_AUTH_PLAINTEXT_RE.match(stripped)
        if auth:
            secret = auth.group(1).strip().strip('"')
            group.authentication = f"plain:{secret}"
            i += 1
            continue

        # Unrecognised body line — skip but don't terminate.
        # AOS-S has additional sub-commands (advertise-interval-centisec,
        # track-id, etc.) not modelled here; they parse-and-ignore.
        i += 1
    return group, i


def _fresh_record(name: str) -> CanonicalInterface:
    """The record an ``interface`` stanza with no lines makes."""
    return CanonicalInterface(name=name, enabled=True, interface_type=_infer_iface_type(name))


def _read_a_host_address(iface: CanonicalInterface, stripped: str) -> bool:
    """Read *stripped*, a line of a loopback's stanza, into *iface* if it
    is an address given with no mask (:data:`_IP_ADDR_HOST_RE`): a host
    address, /32 or /128.  An address with a mask or a prefix is read
    as it is written, by the lines every interface reads.

    Returns:
        Whether the line was such an address.
    """
    v4 = _IP_ADDR_HOST_RE.match(stripped)
    if v4:
        iface.ipv4_addresses.append(CanonicalIPv4Address(ip=v4.group(1), prefix_length=32))
        return True
    v6 = _IPV6_ADDR_HOST_RE.match(stripped)
    if v6:
        try:
            iface.ipv6_addresses.append(CanonicalIPv6Address(
                ip=v6.group(1), prefix_length=128, scope="global",
            ))
        except ValueError:
            pass
        return True
    return False


def _parse_interface_stanza(
    lines: list[str],
    start: int,
    iface_name: str,
    into: CanonicalInterface | None = None,
    vlan_lines: list[re.Match[str]] | None = None,
    loopback: bool = False,
) -> tuple[CanonicalInterface, int]:
    """Parse an ``interface X`` stanza starting at *start*.

    Args:
        lines: The config, cut into lines.
        start: Index of the first line after the stanza's header.
        iface_name: The interface the header names.
        into: The record an earlier stanza for the same interface
            made.  The lines of this one are read into it -- a later
            line replaces what an earlier one set, an address is
            added -- which is what the device does with two stanzas
            for one interface.
        vlan_lines: Where the stanza's ``[no] tagged vlan <list>`` and
            ``[no] untagged vlan <id>`` lines go, in the order they
            are met (:data:`_PORT_VLAN_LINE_RE`).  They change VLAN
            records, which the caller holds; the caller applies them
            once the stanza is read (:class:`_Memberships`).  ``None``
            reads them and keeps nothing.
        loopback: The stanza is a loopback's, whose addresses are given
            with no mask (:func:`_read_a_host_address`).

    Returns the parsed :class:`CanonicalInterface` and the index of
    the first line AFTER the stanza's ``exit``.
    """
    iface = into if into is not None else _fresh_record(iface_name)
    i = start
    while i < len(lines):
        tick()
        line = lines[i]
        stripped = line.strip()

        if not stripped or stripped.startswith(";"):
            i += 1
            continue
        if _leaves(stripped):
            i += 1
            break
        if _ends_the_stanza(line, stripped):
            break

        nm = _IFACE_NAME_RE.match(stripped)
        if nm:
            iface.description = _unquote(nm.group(1))
            i += 1
            continue

        vlan_line = _PORT_VLAN_LINE_RE.match(stripped)
        if vlan_line:
            if vlan_lines is not None:
                vlan_lines.append(vlan_line)
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

        if loopback and _read_a_host_address(iface, stripped):
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
                prefix_length=_mask_to_prefix(ip_mask.group(2), vendor="aruba_aoss"),
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


def _past_the_oobm_stanza(lines: list[str], start: int) -> int:
    """The index of the first line after the ``oobm`` stanza whose body
    starts at *start*.

    Nothing in the stanza is read: its lines configure the out-of-band
    management port, and several are lines the top of the config reads
    otherwise.  ``ip default-gateway`` there is the management port's
    gateway and not the switch's default route; ``ip address`` is the
    port's own address; ``interface enable`` turns the port on and
    enters no context.  The open context decides what such a line
    means, so none of them ends the stanza (:data:`_OOBM_WORDS_RE`),
    with its indentation or without.

    The stanza ends at its own ``exit`` -- a stack member's nested
    ``member N`` context has an ``exit`` of its own first -- or at an
    ``end``; or at a line in column 0 that is no word of the context
    and that enters another context or that the top of the config
    reads (:func:`_ends_the_stanza`).  So an ``oobm`` with no ``exit``
    keeps the management port's gateway, and loses no ``hostname``
    or ``vlan`` stanza after it.
    """
    depth = 0
    i = start
    while i < len(lines):
        tick()
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            i += 1
            continue
        left = _leaves(stripped)
        if left:
            i += 1
            if left == "end" or not depth:
                break
            depth -= 1
            continue
        if not _OOBM_WORDS_RE.match(stripped) and _ends_the_stanza(line, stripped):
            break
        if _MEMBER_BLOCK_RE.match(stripped):
            depth += 1
        i += 1
    return i


# ---------------------------------------------------------------------------
# The switch's own DHCP server
# ---------------------------------------------------------------------------
#
# HPE, ArubaOS-Switch Management and Configuration Guide ("DHCPv4
# server"): ``dhcp-server pool <POOL-NAME>`` configures a pool "with
# either a static IP or a network IP range"; ``dhcp-server enable``
# enables the server in the switch, which "Defaults to disabled";
# "Range is configured to enable pool".  HPE's DHCP white paper: a pool
# is valid only as a dynamic pool ("a network address, subnet mask and
# IP range(s)") or a static pool ("a static IP-to-MAC binding"), and
# "The DHCP server will discard the invalid and incomplete pools".  Its
# examples enable the server on a VLAN with ``dhcp-server`` in the
# VLAN's stanza, and serve pools whose network is no VLAN of the
# switch to clients a relay forwards to it.  The switch refuses to
# change the server's configuration while it is enabled, so a printout
# has ``dhcp-server enable`` after its pools.

#: ``network <address>/<length>`` (HPE's syntax) or ``network <address>
#: <mask>`` (as the switch prints it).
_POOL_NETWORK_RE = re.compile(
    r"^network[ \t]+(\d{1,3}(?:\.\d{1,3}){3})(?:/(\d{1,2})|[ \t]+(\d{1,3}(?:\.\d{1,3}){3}))$", re.IGNORECASE,
)
#: ``range <low> [<high>]``.
_POOL_RANGE_RE = re.compile(
    r"^range[ \t]+(\d{1,3}(?:\.\d{1,3}){3})(?:[ \t]+(\d{1,3}(?:\.\d{1,3}){3}))?$", re.IGNORECASE,
)
#: ``default-router`` / ``dns-server``: up to eight addresses, printed in
#: quotes and separated by commas.
_POOL_ADDRESSES_RE = re.compile(r"^(?:default-router|dns-server)[ \t]+(\S.*)$", re.IGNORECASE)
#: ``lease [DD:HH:MM | infinite]``; HPE: "The default lease period is
#: one day".
_POOL_LEASE_RE = re.compile(
    r"^lease[ \t]+(?:(\d{1,5}):(\d{1,2}):(\d{1,2})|infinite)$", re.IGNORECASE,
)
_POOL_DOMAIN_RE = re.compile(r"^domain-name[ \t]+(\S.*)$", re.IGNORECASE)

#: The statements of a pool, in HPE's syntax, that the tree has no
#: place for.  Each is said by its word alone: an ``option`` holds what
#: a vendor's client is given, a key among it often enough.
_POOL_WORDS_NOT_READ = frozenset({
    "authoritative", "bootfile-name", "netbios-name-server", "netbios-node-type",
    "option", "tftp-server",
})

#: What a row of each kind (:func:`_pool_row`) says it stands for.  A
#: kind of ``""`` is a line of a pool in a form the parser does not read
#: (a ``no`` line among them).
_POOL_KINDS = {
    "": "a line in a form this parser does not read",
    "range": "a range after the pool's first",
    "default-router": "a default router after the pool's first",
    "static-bind": "a static binding of an address to a MAC address",
}

#: Lease time HPE calls ``infinite``: DHCP's own "infinity" (RFC 2131),
#: as the IOS-XE CLI parser writes it.
_INFINITE_LEASE = 0xFFFFFFFF


@dataclass
class _Pool:
    """What a ``dhcp-server pool`` states, from every stanza of its name
    (a context entered again is the same pool)."""

    name: str
    network: str = ""
    ranges: list[tuple[str, str]] = field(default_factory=list)
    routers: list[str] = field(default_factory=list)
    dns_servers: list[str] = field(default_factory=list)
    lease_time: int = 86400
    domain_name: str = ""
    static_binds: int = 0
    #: The kinds of statement not read, in the order they were met.
    unread: dict[str, None] = field(default_factory=dict)


def _addresses(text: str) -> list[str]:
    """The IPv4 addresses of a ``default-router`` or ``dns-server`` line,
    quoted and separated by commas as the switch prints them, or by
    spaces as they are typed; none if one of them is no address."""
    found: list[str] = []
    for word in ticked(_unquote(text).replace(",", " ").split()):
        try:
            found.append(str(ipaddress.IPv4Address(word)))
        except ValueError:
            return []
    return found


def _read_pool_statement(pool: _Pool, statement: str) -> None:
    """Read *statement*, a line of *pool*'s context without its white
    space, into *pool*.  A statement the tree has no place for, or in a
    form this parser does not read, is noted by its kind and nothing of
    its value."""
    word = statement.split(None, 1)[0].lower()
    if word == "network":
        found = _POOL_NETWORK_RE.match(statement)
        if found:
            try:
                pool.network = str(ipaddress.IPv4Network(
                    f"{found.group(1)}/{found.group(2) or found.group(3)}", strict=False,
                ))
                return
            except ValueError:
                pass
    elif word == "range":
        found = _POOL_RANGE_RE.match(statement)
        if found:
            try:
                low = str(ipaddress.IPv4Address(found.group(1)))
                high = str(ipaddress.IPv4Address(found.group(2) or found.group(1)))
                pool.ranges.append((low, high))
                return
            except ValueError:
                pass
    elif word in ("default-router", "dns-server"):
        found = _POOL_ADDRESSES_RE.match(statement)
        addresses = _addresses(found.group(1)) if found else []
        if addresses:
            if word == "default-router":
                pool.routers = addresses
            else:
                pool.dns_servers = addresses
            return
    elif word == "lease":
        found = _POOL_LEASE_RE.match(statement)
        if found:
            days, hours, minutes = found.group(1, 2, 3)
            pool.lease_time = (
                _INFINITE_LEASE if days is None
                else int(days) * 86400 + int(hours) * 3600 + int(minutes) * 60
            )
            return
    elif word == "domain-name":
        found = _POOL_DOMAIN_RE.match(statement)
        if found:
            pool.domain_name = _unquote(found.group(1))
            return
    elif word == "static-bind":
        pool.static_binds += 1
        return
    elif word in _POOL_WORDS_NOT_READ:
        pool.unread.setdefault(word, None)
        return
    pool.unread.setdefault("", None)


def _parse_dhcp_pool_stanza(lines: list[str], start: int, pool: _Pool) -> int:
    """Read the body of a ``dhcp-server pool`` stanza, which starts at
    *start*, into *pool*; the index of the first line after it.  The
    stanza ends as every stanza ends (:func:`_ends_the_stanza`)."""
    i = start
    while i < len(lines):
        tick()
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            i += 1
            continue
        if _leaves(stripped):
            i += 1
            break
        if _ends_the_stanza(line, stripped):
            break
        _read_pool_statement(pool, stripped)
        i += 1
    return i


def _pool_row(kind: str, names: list[str]) -> str:
    """The row for the statements of a kind that the pools *names* hold
    and the tree has no place for."""
    head = f"dhcp-server pool {kind}" if kind else "dhcp-server pool"
    what = _POOL_KINDS.get(kind, "a statement of a DHCP pool")
    pools = "pool" if len(names) == 1 else "pools"
    return f"{head} (in {pools} {a_few_named(names)}: {what}; not translated)"


class _DhcpServer:
    """The switch's DHCP server, as the lines of a config state it.

    What is in force is known only once the last line has been read
    (``dhcp-server enable`` comes after the pools), so the lines are
    kept and :meth:`finish` makes the tree's pools and the rows.
    """

    def __init__(self) -> None:
        self.enabled = False
        self.pools: dict[str, _Pool] = {}
        #: The VLANs whose stanza states ``dhcp-server``.
        self.vlans: set[int] = set()
        #: The first words of each line that sets something of the
        #: server, as it begins (``no dhcp-server ping``): no value.
        self._settings: list[list[str]] = []

    def pool(self, name: str) -> _Pool:
        """The pool of *name*, made the first time it is named."""
        found = self.pools.get(name)
        if found is None:
            found = self.pools[name] = _Pool(name)
        return found

    def server_line(self, no: bool, word: str, rest: str) -> None:
        """A line of the top that begins ``dhcp-server`` and *word*.
        ``enable`` and ``disable`` (or ``no`` before either) turn the
        server on and off, and the last such line is the switch's."""
        lowered = word.lower()
        if lowered in ("enable", "disable") and not rest.strip():
            self.enabled = (lowered == "enable") != no
        else:
            self._settings.append([*(["no"] if no else []), "dhcp-server", _shown(lowered)])

    def finish(
        self, vlans: Iterable[CanonicalVlan], say: Callable[[str], None],
    ) -> tuple[list[CanonicalDHCPPool], list[tuple[str, list[str]]]]:
        """The pools of the tree, and the statements left out because
        they are not in force (for :func:`left_out_rows`).  What is in
        force and has no place in the tree is given to *say*: one row
        a kind, which names a few pools."""
        left_out: list[tuple[str, list[str]]] = []
        if not self.enabled:
            for pool in ticked(self.pools.values()):
                left_out.append(("disabled", ["dhcp-server", "pool", _shown(pool.name)]))
            for setting in ticked(self._settings):
                left_out.append(("disabled", setting))
            return [], left_out
        for setting in ticked(self._settings):
            say(f"{' '.join(setting)} (a setting of the DHCP server; not translated)")
        served = self._served(vlans)
        pools: list[CanonicalDHCPPool] = []
        unread: dict[str, list[str]] = {}
        for pool in ticked(self.pools.values()):
            kinds = list(pool.unread)
            if pool.network and pool.ranges:
                pools.append(self._record(pool, served))
                if len(pool.ranges) > 1:
                    kinds.append("range")
                if len(pool.routers) > 1:
                    kinds.append("default-router")
                if pool.static_binds:
                    kinds.append("static-bind")
            elif pool.static_binds:
                # A static pool: a binding the tree has no place for.
                kinds = ["static-bind"]
            else:
                left_out.append(("incomplete", ["dhcp-server", "pool", _shown(pool.name)]))
                continue
            for kind in kinds:
                unread.setdefault(kind, []).append(f'"{_shown(pool.name)}"')
        for kind, names in unread.items():
            say(_pool_row(kind, names))
        return pools, left_out

    def _served(self, vlans: Iterable[CanonicalVlan]) -> dict[ipaddress.IPv4Network, int]:
        """The subnet of each address of a VLAN the server serves on,
        and the VLAN (the first, of two with one subnet)."""
        served: dict[ipaddress.IPv4Network, int] = {}
        for vlan in ticked(vlans):
            if vlan.id not in self.vlans:
                continue
            for address in vlan.ipv4_addresses:
                try:
                    subnet = ipaddress.IPv4Network(f"{address.ip}/{address.prefix_length}", strict=False)
                except ValueError:
                    continue
                served.setdefault(subnet, vlan.id)
        return served

    @staticmethod
    def _record(pool: _Pool, served: dict[ipaddress.IPv4Network, int]) -> CanonicalDHCPPool:
        """The tree's pool for a dynamic *pool*: its first range and its
        first default router (the rest are said), on the ``Vlan<N>``
        whose subnet the pool's network is."""
        vlan_id = served.get(ipaddress.IPv4Network(pool.network))
        low, high = pool.ranges[0]
        return CanonicalDHCPPool(
            interface=f"Vlan{vlan_id}" if vlan_id is not None else "",
            network=pool.network,
            start_ip=low,
            end_ip=high,
            gateway=pool.routers[0] if pool.routers else "",
            dns_servers=list(pool.dns_servers),
            lease_time=pool.lease_time,
            domain_name=pool.domain_name,
        )


#: The most rows :class:`_Memberships` gives for the lines it left out.
#: Every row is in every answer, and a config is whatever was pasted.
_ROWS_SHOWN = 50
#: The most VLAN ids, and the most characters of a line, one row spells
#: out: a line names thousands of ids in a few bytes, and as many ports
#: as it likes.
_IDS_SHOWN = 8
_LINE_SHOWN = 120


def _route_destination(dest: str, mask: str | None) -> str:
    """A route's destination as CIDR.  *mask* is the OPTIONAL
    dotted-decimal mask (legacy Aruba form): when present it gives the
    prefix length; when absent *dest* was already CIDR (or a bare IP,
    defaulting to /32)."""
    if mask is None:
        return _dest_to_cidr(dest)
    try:
        prefix = _mask_to_prefix(mask, vendor="aruba_aoss")
    except ParseError:
        # Non-contiguous mask — unusual; fall back to /32 host-route
        # semantic so render still produces something parseable.
        prefix = 32
    return f"{dest}/{prefix}"


def _shown(line: str) -> str:
    """*line*, or its first :data:`_LINE_SHOWN` characters and a mark
    that it was cut."""
    return line if len(line) <= _LINE_SHOWN else line[: _LINE_SHOWN - 1] + "\u2026"


def _few_ids(ids: list[int]) -> str:
    """*ids*, sorted and distinct, as an id list: its first
    :data:`_IDS_SHOWN` runs, and how many ids are not shown."""
    runs = _coalesce_vlan_ids(ids).split(",")
    if len(runs) <= _IDS_SHOWN:
        return ",".join(runs)
    in_shown = 0
    for run in runs[:_IDS_SHOWN]:
        low, _, high = run.partition("-")
        in_shown += int(high) - int(low) + 1 if high else 1
    return f"{','.join(runs[:_IDS_SHOWN])} and {len(ids) - in_shown} more"


def _cut(cuts: dict[int, tuple[CanonicalVlan, dict[str, int]]], vlan: CanonicalVlan, port: str, at: int) -> None:
    """Note that *port* leaves *vlan*'s list once the config has been
    read: every entry of it above *at*, the length the list had when
    the line that took it out was read.  An entry a later line puts
    there is kept."""
    cuts.setdefault(id(vlan), (vlan, {}))[1][port] = at


class _Memberships:
    """Which VLAN a port is untagged in, and what later lines take out
    of a VLAN's lists, while a config is read.

    Two kinds of line state a port's part in a VLAN: the VLAN's own
    (``vlan 20`` / ``untagged 4``) and the port's (``interface 4`` /
    ``untagged vlan 20``, or ``interface 4 untagged vlan 20`` on one
    line).  Both set the same thing, and the later line wins whichever
    kind it is.  A port is untagged in one VLAN at a time, so a line
    that makes it untagged in another takes it out of the one it was in
    (HPE's own example: a port made untagged in VLAN 10 is printed
    ``no untagged`` under VLAN 1).

    What a line takes out of a VLAN's list leaves the list after the
    last line (:meth:`finish`): until then nothing reads an earlier
    VLAN's list, and a list written again for every such line cost the
    square of the lines.  What leaves is what the list held when the
    line was read, so a later line that puts the port back is kept --
    a port moved out of VLAN 1 and then back into it is in VLAN 1, not
    in no VLAN at all.

    A port's line applies to the VLAN as the config has declared it
    by then (the record of the last ``vlan N`` stanza above it).  A
    line that names a VLAN no stanza above it declares makes no VLAN:
    it is left out, and said in a row of ``dropped_tier3_sections``
    (:meth:`rows`).  On the switch the one-line form is refused for a
    VLAN that does not exist; what it does with the form inside an
    ``interface`` stanza is not established.  The same rows say what
    else a line was left out for (:meth:`say`).
    """

    def __init__(self, intent: CanonicalIntent) -> None:
        self._vlan = GrowingIndex(lambda: intent.vlans, lambda vlan: vlan.id, last=True)
        self._untagged_in: dict[str, CanonicalVlan] = {}
        self._untagged_out: dict[int, tuple[CanonicalVlan, dict[str, int]]] = {}
        self._tagged_out: dict[int, tuple[CanonicalVlan, dict[str, int]]] = {}
        self._left_out: dict[str, int] = {}
        self._not_listed = 0

    def _untagged(self, port: str, vlan: CanonicalVlan) -> None:
        holder = self._untagged_in.get(port)
        if holder is not None and holder is not vlan:
            _cut(self._untagged_out, holder, port, len(holder.untagged_ports))
        self._untagged_in[port] = vlan

    def vlan_read(self, vlan: CanonicalVlan) -> None:
        """A ``vlan`` stanza has been read into *vlan*: each port it
        lists untagged leaves the VLAN it was untagged in before."""
        for port in dict.fromkeys(vlan.untagged_ports):
            self._untagged(port, vlan)

    def port_line(
        self, ports: list[str], no: str | None, kind: str, ids: str, line: str, *, counted: bool,
    ) -> None:
        """Apply one of a port's lines: ``[no] tagged vlan <ids>`` or
        ``[no] untagged vlan <ids>`` for each of *ports*.

        What the line makes (or, with ``no``, notes for removal) is one
        entry a port a VLAN, and it is counted before the first is
        made.

        Args:
            ports: The ports, as the tree names them.
            no: The line's ``no``, if it has one.
            kind: ``tagged`` or ``untagged``.
            ids: The VLAN id list as the line writes it.
            line: The line in the vendor's one-line form (``[no]
                interface 4 untagged vlan 20``), for a row.
            counted: Whether *ports* were made from this very line --
                the one-line form, whose port ranges were counted as
                they were made, for one VLAN.  In a stanza they were
                made once, for its header, and every line of it
                stamps all of them again.
        """
        found: list[CanonicalVlan] = []
        absent: list[int] = []
        for vid in dict.fromkeys(_parse_vlan_list(ids)):
            vlan = self._vlan.get(vid)
            if vlan is None:
                absent.append(vid)
            else:
                found.append(vlan)
        if absent:
            self._say(line, absent)
        stamps = len(ports) * (len(found) - 1 if counted else len(found))
        if stamps > 0:
            charge("memberships", stamps, line)
        tagged = kind.lower() == "tagged"
        for vlan in found:
            for port in ports:
                if no and tagged:
                    _cut(self._tagged_out, vlan, port, len(vlan.tagged_ports))
                elif no:
                    _cut(self._untagged_out, vlan, port, len(vlan.untagged_ports))
                    if self._untagged_in.get(port) is vlan:
                        del self._untagged_in[port]
                elif tagged:
                    vlan.tagged_ports.append(port)
                else:
                    vlan.untagged_ports.append(port)
                    self._untagged(port, vlan)

    def _say(self, line: str, absent: list[int]) -> None:
        self.say(
            f"{_shown(line)} ({'VLAN' if len(absent) == 1 else 'VLANs'} {_few_ids(sorted(absent))}: "
            f"declared by no vlan stanza above the line; not translated)"
        )

    def say(self, row: str) -> None:
        """Keep *row*, which ends in a closing bracket, for a line that
        was left out: one row for the lines that read alike, and no
        more than :data:`_ROWS_SHOWN` rows."""
        if row in self._left_out:
            self._left_out[row] += 1
        elif len(self._left_out) < _ROWS_SHOWN:
            self._left_out[row] = 1
        else:
            self._not_listed += 1

    def finish(self) -> None:
        """Take out of each VLAN's lists what later lines took out."""
        for vlan, gone in self._untagged_out.values():
            vlan.untagged_ports = _stated_since(vlan.untagged_ports, gone)
        for vlan, gone in self._tagged_out.values():
            vlan.tagged_ports = _stated_since(vlan.tagged_ports, gone)

    def rows(self) -> list[str]:
        """The rows for the lines that were left out (a line that named
        a VLAN no stanza declared, what a context for several ports
        set): lines that read alike share one, and past
        :data:`_ROWS_SHOWN` one last row counts the rest."""
        rows = [
            row if count == 1 else f"{row[:-1]}; {count} lines)"
            for row, count in self._left_out.items()
        ]
        if self._not_listed:
            rows.append(
                f"{self._not_listed} more lines left out as the rows above say "
                f"(not translated; not listed)"
            )
        return rows


# ---------------------------------------------------------------------------
# What a written line gives back
# ---------------------------------------------------------------------------
#
# For the renderer.  It leaves a port's ``interface`` stanza out only
# where another line of its output gives the port back, and whether a
# line does is this parser's to say: it is asked here, with the
# patterns and the readers the parse itself uses, of the text as it
# is written -- not answered from what a name looks like.


def _members_read_from(line: str) -> list[str]:
    """The LAG members this parser reads from *line*: those of a
    ``trunk`` line that stands as the top-level loop takes one (one
    line, from column 0), under the names the tree would have for
    them.  None from anything else.

    A member list with a space in it is no ``trunk`` line to
    :data:`_TRUNK_LINE_RE`: such a line gives back none of its ports.
    """
    if line.splitlines() != [line] or line[0].isspace():
        return []
    trunk = _TRUNK_LINE_RE.match(line.strip())
    lag = _build_lag_from_trunk_line(trunk) if trunk else None
    return [] if lag is None else list(lag.members)


def _lists_read_from(stanza: str) -> tuple[list[str], list[str]]:
    """The untagged and the tagged ports this parser reads from a
    ``vlan`` stanza, given as the text of its header and of the lines
    under it: what :func:`_parse_vlan_stanza` makes of them.  Two
    empty lists where the text does not open with a header.

    The stanza and not the one line, because a list is read only
    while its stanza lasts, and the stanza ends where
    :func:`_ends_the_stanza` says.  A line break in a VLAN's name puts
    the rest of the name in column 0; that line is the stanza's unless
    it is a line of another context or of the top, and only then does
    nobody read the lists below it.
    """
    lines = stanza.splitlines()
    if not lines or lines[0][:1].isspace():
        return [], []
    header = _VLAN_HEADER_RE.match(lines[0].strip())
    if header is None:
        return [], []
    vlan = _parse_vlan_stanza(lines, 1, int(header.group(1)))[0]
    return vlan.untagged_ports, vlan.tagged_ports


# ---------------------------------------------------------------------------
# Text that is no line of the config
# ---------------------------------------------------------------------------

#: ``banner motd`` in column 0, and what opens its text.  ``show
#: running-config`` prints a banner as a quoted string that starts on
#: this line, right after the quote, and runs across lines, the text's
#: own line breaks printed as line breaks (HPE's K.11.00 figure; HPE's
#: 16.06 and 16.10 listing prints the escapes ``\'``, ``\n`` and ``\t``
#: as they were typed); the delimiter the operator typed is not
#: printed.  ``banner exec`` is read the same way, though no HPE page
#: shows it (inferred).  The match ends where the quote, or the typed
#: delimiter, begins.  ``banner motd`` with nothing after it opens
#: nothing, nor does ``no banner motd``.
_OPENS_A_BANNER_RE = re.compile(r"^banner[ \t]+(?:motd|exec)[ \t]+(?=[^ \t])", re.IGNORECASE)
#: A backslash and the character after it: an escape, which holds no
#: quote that ends a string.
_ESCAPE_RE = re.compile(r"\\.")

#: Said of a banner that is still open at the end of the text.  Each
#: sentence quotes nothing of the text, and names no delimiter: the
#: delimiter is the operator's.
UNENDED_BODY_MESSAGE = (
    "aruba_aoss: line {line} opens a banner that runs to the end of "
    "this text: `show running-config` prints a banner's text between "
    "two double quotes (one with a backslash in front of it is the "
    "text's own), and a banner typed with another delimiter ends at "
    "the next occurrence of it; this one has no end.  Read as it "
    "stands, every line after line {line} is the banner's text, and no "
    "line of it is configuration.  Paste the output of `show "
    "running-config` whole."
)
#: Said of a printed banner whose closing quote has text after it.
TEXT_AFTER_THE_END_MESSAGE = (
    "aruba_aoss: line {line} ends a banner, and has text after the "
    "double quote that ends it.  `show running-config` prints nothing "
    "there: a double quote in the banner's text ended it early, or the "
    "listing lost a line, so where the banner really ends cannot be "
    "told.  Paste the output of `show running-config` whole."
)
#: Said of a line outside every banner with an odd number of quotes,
#: after a printed banner.
ORPHAN_MESSAGE = (
    "aruba_aoss: line {line} is outside every banner, and holds an odd "
    "number of double quotes, counting none that a backslash escapes: "
    "the text of the banner that line {opened} opens holds a double "
    "quote too, and so ended before its end, and where it really ends, "
    "and where the configuration goes on, cannot be told.  Change the "
    "banner on the switch so that its text holds no double quote, or "
    "remove the banner's lines from the text you paste."
)


def _closing_quote(text: str, start: int) -> int:
    """Where the first double quote in *text* at or after *start* is that
    no backslash escapes, or -1.  A backslash takes the next character
    with it (HPE's escapes: ``\\"``, ``\\\\``, ``\\n``, ...), the line
    end included when it is the last character."""
    at = start
    quote = text.find('"', at)
    while quote >= 0:
        backslash = text.find("\\", at, quote)
        if backslash < 0:
            return quote
        at = backslash + 2
        if at > quote:
            # That quote was the backslash's: look past it.
            quote = text.find('"', at)
    return -1


def _ends_at_a_quote(text: str, number: int, start: int = 0) -> bool:
    """Whether the quoted banner text ends on *text* (from *start*): at
    a double quote no backslash escapes.  A line with text after that
    quote is refused (:data:`TEXT_AFTER_THE_END_MESSAGE`)."""
    at = _closing_quote(text, start)
    if at < 0:
        return False
    if text[at + 1:].strip():
        raise ParseError(
            TEXT_AFTER_THE_END_MESSAGE.format(line=number),
            path=f"line {number}", snippet="",
        )
    return True


def _quotes_in(text: str) -> int:
    """How many double quotes *text* holds once each backslash and the
    character after it are taken out."""
    if "\\" in text:
        text = _ESCAPE_RE.sub("", text)
    return text.count('"')


def _openers() -> Callable[[str, int], Body | None]:
    """The ``opens`` of one pass (:func:`without_banner_bodies`).

    It remembers the line of the last printed (quoted) banner, and
    refuses a later line outside every banner that holds an odd number
    of double quotes (:data:`ORPHAN_MESSAGE`): a stored text that holds
    a quote at the end of a line ends there, early, and the quote the
    switch printed after the text is left behind.  Not seen so: a
    stored text whose part after that quote holds an odd number of
    quotes on its last line (the printed quote makes it even), or opens
    another banner, which then takes that quote for its end.
    """
    quoted_at = 0

    def opens(text: str, number: int) -> Body | None:
        nonlocal quoted_at
        match = _OPENS_A_BANNER_RE.match(text)
        if match is None:
            if quoted_at and '"' in text and _quotes_in(text) % 2:
                raise ParseError(
                    ORPHAN_MESSAGE.format(line=number, opened=quoted_at),
                    path=f"line {number}", snippet="",
                )
            return None
        start = match.end()
        if text[start] == '"':
            # The printed form: the text starts after the quote, on this
            # line, and may end on it (``banner motd "Authorized use
            # only."``).
            quoted_at = number
            return Body(_ends_at_a_quote, ended=_ends_at_a_quote(text, number, start + 1))
        # The typed form, in a pasted script (``banner motd %``): the
        # text ends at the next occurrence of the delimiter, on this
        # line or a later one, and what follows it on its line is
        # discarded.
        delimiter = text[start]
        return Body(ends_anywhere(delimiter), ended=delimiter in text[start + 1:])

    return opens


def without_banner_bodies(raw: str) -> str:
    """*raw* with every line of each banner made empty, keeping its
    number (:func:`.._scanner.without_text_bodies`).

    A printed banner (:data:`_OPENS_A_BANNER_RE` and a double quote)
    ends at the first double quote that no backslash escapes: on the
    line that opens it, at the end of a line of its text, or alone on a
    line.  The lines between are text, whatever they hold.  A banner
    typed with another delimiter ends at the next occurrence of it,
    anywhere (:func:`.._scanner.ends_anywhere`).

    Raises:
        ParseError: A banner has no end before the end of the text; a
            printed one has text after its closing quote; a line of one
            ends in another character than a line feed; or a line
            outside every banner, after a printed one, holds an odd
            number of double quotes (:data:`ORPHAN_MESSAGE`).  Each
            message names the line and quotes nothing of the text.
    """
    return without_text_bodies(raw, _openers(), UNENDED_BODY_MESSAGE, codec="aruba_aoss")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_intent(raw: str) -> CanonicalIntent:  # noqa: C901
    """Parse AOS-S ``show running-config`` text into a
    :class:`CanonicalIntent`.

    Raises:
        ParseError: On empty input or input that clearly isn't AOS-S
            CLI (XML or JSON); or if a banner cannot be told from the
            configuration (:func:`without_banner_bodies`).
    """
    if not raw.strip():
        raise ParseError(
            "aruba_aoss: empty input",
            snippet="",
        )
    # A banner is text, never lines of the config: every reader below --
    # the shape check, the release and the deployment's lines among
    # them -- is given the text with each banner's lines empty, each
    # keeping its number.
    # ``given``: the length of the text as it came, for the debug line
    # at the end.
    given = len(raw)
    raw = without_banner_bodies(raw)
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
    intent.source_version = _extract_version(raw)

    lines = raw.splitlines()
    # One record for an interface and one for a LAG, however many
    # stanzas or ``trunk`` lines the text has for it.
    stanza_of: dict[str, CanonicalInterface] = {}
    lag_by_name: dict[str, CanonicalLAG] = {}
    # The ports each LAG has, so that a later ``trunk`` line for it
    # finds the ones it adds without reading the list again; and the
    # interfaces a second stanza was read into.
    members_of: dict[str, set[str]] = {}
    met_twice: dict[str, CanonicalInterface] = {}
    # What a line looks for among everything the earlier lines made is
    # found by key.  Looked for by reading the whole list -- per user
    # line, per RADIUS line, per trunk line, per VLAN stanza -- a config
    # of N such lines cost N squared.
    v3_users = GrowingIndex(
        lambda: intent.snmp.v3_users if intent.snmp is not None else _NO_USERS,
        lambda user: user.name,
    )
    radius_by_host = GrowingIndex(lambda: intent.radius_servers, lambda server: server.host)
    # The dict a trunk line used to build from every interface: of two
    # records of one name the later one answered.  (Two ``interface``
    # stanzas of one name are one record; a VLAN stanza met twice
    # still makes two ``Vlan<N>`` records.)
    iface_at_trunk = GrowingIndex(lambda: intent.interfaces, lambda iface: iface.name, last=True)
    # RADIUS servers a global ``radius-server key`` line may still have
    # to give its key to, and how many servers have been looked at.
    keyless: list[CanonicalRADIUSServer] = []
    servers_seen = 0
    # Which VLAN record a port is untagged in, and what each record has
    # since lost to a later line (taken out after the loop: until then
    # the record still lists it, and nothing in the loop reads an
    # earlier VLAN's list).
    memberships = _Memberships(intent)
    # The DHCP server's lines: what is in force is known after the last.
    dhcp = _DhcpServer()
    # The account each role has (the last line's), and each local user
    # by name (the last line's): the tree is given the two accounts
    # first, after the last line.
    by_role: dict[str, CanonicalLocalUser] = {}
    by_name: dict[str, CanonicalLocalUser] = {}
    i = 0
    while i < len(lines):
        tick()
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

        system = _SNMP_SYSTEM_RE.match(stripped_line)
        if system:
            if intent.snmp is None:
                intent.snmp = CanonicalSNMP()
            fields, pos = stripped_line, system.end()
            while field := _SNMP_SYSTEM_FIELD_RE.match(fields, pos):
                quoted, bare = field.group(2), field.group(3)
                value = _unescape(quoted) if quoted is not None else bare.strip().strip('"')
                setattr(intent.snmp, field.group(1).lower(), value)
                if bare is not None:
                    break
                pos = field.end()
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
            existing = v3_users.get(name)
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
            bound = v3_users.get(user_name)
            found = bound is not None
            if bound is not None:
                bound.group = group_name
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

        rt6 = _IPV6_ROUTE_RE.match(stripped_line)
        if rt6:
            intent.static_routes.append(CanonicalStaticRoute(
                destination=rt6.group(1),  # already <prefix>/<len>
                gateway=rt6.group(2),
                metric=int(rt6.group(3)) if rt6.group(3) else 0,
            ))
            i += 1
            continue

        rt6n = _IPV6_ROUTE_NAMED_RE.match(stripped_line)
        if rt6n:
            intent.static_routes.append(CanonicalStaticRoute(
                destination=rt6n.group(1),
                interface=f"Vlan{int(rt6n.group(2))}" if rt6n.group(2) else DISCARD_HOP,
                metric=int(rt6n.group(4)) if rt6n.group(4) else 0,
            ))
            i += 1
            continue

        rt = _IP_ROUTE_RE.match(stripped_line)
        if rt:
            # Three-form parse: see _IP_ROUTE_RE above.
            intent.static_routes.append(CanonicalStaticRoute(
                destination=_route_destination(rt.group(1), rt.group(2)),
                gateway=rt.group(3),
                metric=int(rt.group(4)) if rt.group(4) else 0,
            ))
            i += 1
            continue

        rtn = _IP_ROUTE_NAMED_RE.match(stripped_line)
        if rtn:
            intent.static_routes.append(CanonicalStaticRoute(
                destination=_route_destination(rtn.group(1), rtn.group(2)),
                interface=f"Vlan{int(rtn.group(3))}" if rtn.group(3) else DISCARD_HOP,
                metric=int(rtn.group(5)) if rtn.group(5) else 0,
            ))
            i += 1
            continue

        if _ANY_ROUTE_RE.match(stripped_line):
            memberships.say(
                f"{_shown(stripped_line)} (a static route in a form this parser "
                f"does not read; not translated)"
            )
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
                key = _radius_key(km.group(1), km.group(2))
            existing = radius_by_host.get(host)
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
            global_key = _radius_key(rk.group(1), rk.group(2))
            # Only a server with no key can take it.  Those are kept
            # apart, and every server is looked at once to find them.
            # An empty key gives nothing to anyone: after it every
            # server is as it was, and none is read.
            if global_key:
                while servers_seen < len(intent.radius_servers):
                    server = intent.radius_servers[servers_seen]
                    servers_seen += 1
                    if not server.key:
                        keyless.append(server)
                for server in ticked(keyless):
                    if not server.key:
                        server.key = global_key
                keyless = []
            i += 1
            continue

        pwd = _PASSWORD_LINE_RE.match(stripped_line)
        if pwd:
            role = pwd.group(1).lower()
            # The algorithm is kept on the hash (``sha1:<hash>``), so
            # that the renderer writes the line's form again.
            hashed, i = _hash_read(pwd.group(3), pwd.group(4), lines, i)
            if role in by_role:
                memberships.say(
                    f'password {role} (a later "password {role}" line sets the '
                    f"same account, as on the switch; not translated)"
                )
            by_role[role] = CanonicalLocalUser(
                name=_word(pwd.group(2)) or role,
                privilege_level=15 if role == "manager" else 1,
                hashed_password=hashed,
                role=role,
            )
            continue

        local = _LOCAL_USER_LINE_RE.match(stripped_line)
        if local:
            name, group = _word(local.group(1)), _word(local.group(2))
            hashed, i = _hash_read(local.group(3), local.group(4), lines, i)
            if by_name.pop(name, None) is not None:
                memberships.say(
                    "aaa authentication local-user (a later line names the same "
                    "user and sets the account; not translated)"
                )
            if not _PREDEFINED_GROUP_RE.fullmatch(group):
                memberships.say(
                    "aaa authentication local-user ... group (a group other than "
                    "the switch's Level-0 to Level-15: what it allows is not "
                    "translated, and the user is read at privilege level 1)"
                )
            # The group is not a role: no other platform has it.
            by_name[name] = CanonicalLocalUser(
                name=name,
                privilege_level=_privilege_of_group(group),
                hashed_password=hashed,
            )
            continue

        if _LOCAL_USER_OTHER_RE.match(stripped_line):
            memberships.say(
                "aaa authentication local-user (a line that sets no account: a "
                "password policy, or a form not read; not translated)"
            )
            i += 1
            continue

        tk = _TRUNK_LINE_RE.match(stripped_line)
        if tk:
            lag = _build_lag_from_trunk_line(tk)
            defined = None if lag is None else lag_by_name.get(lag.name)
            # The ports THIS line names: the only ones it can add or
            # link.  Going through every port the LAG already had,
            # once per line, cost the square of the lines one LAG is
            # given.
            named_here = [] if lag is None else lag.members
            if lag is not None and defined is not None:
                # A second ``trunk`` line for a LAG adds its ports to
                # the first: one LAG, one record.
                have = members_of[lag.name]
                fresh = [member for member in named_here if member not in have]
                have.update(fresh)
                defined.members.extend(fresh)
                lag = defined
            elif lag is not None:
                lag_by_name[lag.name] = lag
                members_of[lag.name] = set(lag.members)
                intent.lags.append(lag)
            if lag is not None:
                # Reverse-link each member to this LAG so the
                # canonical tree stays consistent.  (The members of
                # earlier lines were linked at their own line, and
                # the pass after the loop links every one again.)
                for member in named_here:
                    m_iface = iface_at_trunk.get(member)
                    if m_iface is not None and m_iface.lag_member_of is None:
                        m_iface.lag_member_of = lag.name
            i += 1
            continue

        vm = _VLAN_HEADER_RE.match(stripped_line)
        if vm:
            vlan_id = int(vm.group(1))
            vlan, vrrp_groups, svi_ipv6, next_i = _parse_vlan_stanza(
                lines, i + 1, vlan_id, dhcp_vlans=dhcp.vlans,
            )
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
            #
            # A port is untagged in one record at a time, so the record
            # that loses it is found by the port -- not by reading
            # every earlier VLAN for every stanza, which made a config
            # of N stanzas cost N squared.
            memberships.vlan_read(vlan)
            intent.vlans.append(vlan)
            # SVI absorption — codepath 1 of 3.  See
            # ._svi_absorption for the full rule.  AOS-S packs
            # the SVI L3 inside the `vlan` stanza; we promote it
            # to a canonical ``Vlan<N>`` CanonicalInterface here
            # so downstream consumers (and renderers of *other*
            # vendors that DO use ``interface Vlan<N>``) see the
            # L3 record at the canonical location.  VRRP groups
            # parsed from the nested ``vrrp vrid N`` blocks
            # attach to this same Vlan<N> interface — VRRP is an
            # interface property in the canonical model.
            #
            # When the VLAN has VRRP groups but NO L3 address
            # (pathological AOS-S — a vrid sub-block normally
            # implies an SVI), we still synthesise the Vlan<N>
            # interface so the groups have somewhere to attach.
            # Render path is robust to either input shape.
            if vlan.ipv4_addresses or vrrp_groups or svi_ipv6:
                intent.interfaces.append(CanonicalInterface(
                    name=f"Vlan{vlan_id}",
                    description=vlan.name,
                    enabled=True,
                    interface_type="ianaift:l3ipvlan",
                    ipv4_addresses=list(vlan.ipv4_addresses),
                    ipv6_addresses=list(svi_ipv6),
                    vrrp_groups=list(vrrp_groups),
                ))
            i = next_i
            continue

        # ``interface <ports> tagged vlan <ids>`` on one line: a port's
        # VLANs, stated at the top.  It enters no context and names no
        # interface of its own.
        port_vlans = _GLOBAL_PORT_VLAN_RE.match(stripped_line)
        if port_vlans:
            memberships.port_line(
                _parse_port_list(port_vlans.group(2)), port_vlans.group(1),
                port_vlans.group(3), port_vlans.group(4), " ".join(stripped_line.split()),
                counted=True,
            )
            i += 1
            continue

        if _OOBM_HEADER_RE.match(stripped_line):
            i = _past_the_oobm_stanza(lines, i + 1)
            continue

        # The switch's own DHCP server (:class:`_DhcpServer`): a pool's
        # stanza, a pool's statement given from the top, and the lines
        # that enable the server or set something of it.
        pool_header = _DHCP_POOL_HEADER_RE.match(stripped_line)
        if pool_header:
            pool = dhcp.pool(_unquote(pool_header.group(1)))
            if pool_header.group(2):
                _read_pool_statement(pool, pool_header.group(2))
                i += 1
            else:
                i = _parse_dhcp_pool_stanza(lines, i + 1, pool)
            continue
        server_line = _DHCP_SERVER_LINE_RE.match(stripped_line)
        if server_line:
            dhcp.server_line(
                bool(server_line.group(1)), server_line.group(2), stripped_line[server_line.end():],
            )
            i += 1
            continue

        loopback = _LOOPBACK_HEADER_RE.match(stripped_line)
        im = (
            loopback
            or _IFACE_HEADER_RE.match(stripped_line)
            or _PORT_LIST_HEADER_RE.match(stripped_line)
        )
        if im:
            # ``interface loopback 1`` is the loopback ``loopback1``.
            iface_name = (
                f"loopback{loopback.group(1)}" if loopback
                else one_spelling(im.group(1).strip('"'))
            )
            # ``interface 1-4`` or ``interface 1,3``: a context for the
            # ports the header names, and no record named after the
            # list.  Its VLAN lines are each port's; anything else it
            # sets is said, not translated.
            ports = _parse_port_list(iface_name)
            several = len(ports) > 1
            # A second stanza for an interface goes on with the first,
            # as the device reads them: one interface, one record.
            earlier = None if several else stanza_of.get(iface_name)
            vlan_lines: list[re.Match[str]] = []
            iface, next_i = _parse_interface_stanza(
                lines, i + 1, iface_name, into=earlier, vlan_lines=vlan_lines,
                loopback=loopback is not None,
            )
            if several:
                if iface != _fresh_record(iface_name):
                    memberships.say(
                        f"{_shown(f'interface {iface_name}')} (a context for several ports: what it "
                        f"sets other than their VLANs is not translated)"
                    )
            elif earlier is None:
                stanza_of[iface_name] = iface
                intent.interfaces.append(iface)
            else:
                met_twice[iface_name] = iface
            # The stanza's VLAN lines, where they stand in the text:
            # no ``vlan`` stanza can come between them and its header.
            # Each stamps every port of the header again, and is
            # counted for all of them (``counted=False``).
            for found in ticked(vlan_lines):
                memberships.port_line(
                    ports, found.group(1), found.group(2), found.group(3),
                    f"{'no ' if found.group(1) else ''}interface {iface_name} "
                    f"{found.group(2)} vlan {found.group(3)}",
                    counted=False,
                )
            i = next_i
            continue

        # Unrecognised top-level line — skip.
        i += 1

    # The two accounts first, as the switch prints them, then the local
    # users: the AOS-S renderer gives the manager slot to the first user
    # of privilege 15, which is the manager's line and not a Level-15
    # user printed above it.
    intent.local_users = [
        *(by_role[role] for role in ("manager", "operator") if role in by_role),
        *by_name.values(),
    ]

    # What each VLAN lost to a later line leaves it now.
    memberships.finish()
    # The DHCP server's pools, once every VLAN has its addresses: what
    # is in force and has no place in the tree is said with the lines
    # above, and what is not in force is left out and said after them.
    intent.dhcp_servers, dhcp_left_out = dhcp.finish(intent.vlans, memberships.say)
    intent.dropped_tier3_sections = [
        *memberships.rows(),
        *left_out_rows(dhcp_left_out, rest="disabled"),
    ]

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

    # A stanza met twice states its addresses twice, and that is one
    # address each: the first statement keeps its place.  Done here,
    # once and by key -- looking through the list at every line would
    # cost the square of the lines one interface is given.
    for again in met_twice.values():
        again.ipv4_addresses = _stated_once(
            again.ipv4_addresses, lambda a: (a.ip, a.prefix_length),
        )
        again.ipv6_addresses = _stated_once(
            again.ipv6_addresses, lambda a: (a.ip, a.prefix_length, a.scope),
        )

    # What the port lists hold, counted before anything sorts or
    # copies them: a list written name by name passed no range.
    census(intent)

    _one_name_per_lag(intent)

    # A port that only a VLAN's list or a ``trunk`` line names is a
    # port of the device, and gets its record here.  Two things fix
    # the place: it is after ``census`` above, which holds such ports
    # to their own limit while they have no record, and before the
    # mirrors below, which give every record its VLANs.
    _a_record_for_every_port_named(intent)

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
    # blank, and a target that writes a port's VLANs from the port's
    # own record writes none.
    #
    # The ``interface`` stanzas are NOT the port inventory -- the
    # device prints one only for a port with a setting of its own, and
    # a switch's own config can have none at all -- so every port a
    # list names was given its record above, and this fills all of
    # them.  ``synthesise_missing=False`` because no port is left for
    # the projection to make, and the record it would make is not the
    # one this parser makes for a stanza: it has no interface type,
    # and a config and its own rendering would then parse differently.
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
        given,
    )
    return intent
