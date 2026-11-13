"""
Parse path for Dell SmartFabric OS10 (``show running-configuration`` form).

Public functions: :func:`parse_intent` — raw text in,
:class:`CanonicalIntent` out, for OS10 10.5.x on the S-series
(S3048-ON / S4100 / S5200 / S5232F) and Z-series; and
:func:`without_banner_bodies` — the text with every line of each banner
emptied, which every reader of the parse is given (the codec's Tier-3
rows among them; the probe reads the text as it came).

Note: probe lives in :mod:`.codec`; this module assumes the input has
already been classified as Dell OS10 CLI.

Phase 1 surface (see ``docs/vendor-research/dell_os10/30-codec-plan.md``
§ 8): hostname, ``! Version`` banner, interfaces (description / admin
state / mtu / IPv4 + IPv6 CIDR / ``ip vrf forwarding`` / L2 switchport /
``channel-group``), VLANs (SVI-derived + switchport projection), LAGs,
top-level VRF declarations, and static routes; SNMP (communities,
location, contact, trap hosts, v3 users), local users, VRRP groups
and the management plane (``ip domain-name``, ``ip name-server``,
``ntp server`` and ``logging server``, each in its bare form: see
:func:`_parse_management_plane`) were added after it.  A line in
column 0 that none of these readers
takes is a row of ``dropped_tier3_sections``
(:func:`_rows_for_what_no_reader_takes`).

Grammar notes — every one of these was MEASURED across the 14 OS10
captures held OUT-OF-TREE at ``local/dell-os10/configs/`` (gitignored —
they carry real password hashes), not inferred from another vendor:

* **``interface breakout`` and ``interface range`` are not interfaces.**
  Both sit at column 0 and begin with the word ``interface``
  (``interface breakout 1/1/1 map 100g-1x`` ×148, ``interface range
  ethernet1/1/1-1/1/12`` ×10).  A naive ``^interface\\s+(\\S+)`` header
  anchor creates phantom interfaces named ``breakout`` / ``range`` and
  absorbs the real config that follows.  A header that names no ONE
  interface -- a keyword, a range or a list where a name goes, words
  that are no one name -- has its stanza taken out before any reader
  sees it, and its header line is a section row of
  ``dropped_tier3_sections`` (:func:`_without_headers_of_no_one_interface`);
  up to 0.7.7 such a stanza was in no record and no row.  Every
  ``interface breakout`` line is one row between them, the label the
  Tier-3 detector gives them.  Two of the ``interface range`` lines are
  written with a space in front, after a ``!``; such a header is read
  as one at column 0 (:func:`_range_header_at_column_0`).

* **An indented ``!`` does NOT close a stanza.**  Device dumps separate
  an SVI's L3 block from its VRRP block with a one-space ``!``::

      interface vlan101
       ip address 172.22.56.2/27
       !
       vrrp-group 11
        priority 150
      !

  A rule that closed the stanza on ``line.strip() == "!"`` would close
  it at the INDENTED separator and silently drop everything after it
  (the shared :func:`..._scanner._default_terminator` once did).  This
  module passes a column-0-only terminator of its own (same rule
  ``cisco_nxos`` uses).

* **Interface keyword case and spacing are not stable.**  The SVI header
  appears as ``interface vlan700`` ×161 (device output), ``interface Vlan
  700`` ×28 and ``interface vlan 700`` ×24 (operator-authored).  Parse
  accepts all three and normalises to the device form ``vlan700`` so one
  VLAN cannot enter the canonical tree under two names.  Any other type
  and its number written apart are one name too, in lower case: Dell
  types ``OS10(config)# interface ethernet 1/1/14`` and the prompt
  names ``eth1/1/14`` (Dell KB 000201923), so ``interface ethernet
  1/1/14`` is ``ethernet1/1/14``, as the switch prints it.  Up to 0.7.7
  such a stanza was in no record and no row.

* **``switchport access vlan`` on a TRUNK port is the native VLAN**, not
  an access VLAN — the same semantic as Cisco's ``switchport trunk
  native vlan``, spelled differently.  Both real trunk examples carry it
  (``port-channel100``: ``mode trunk`` + ``access vlan 1`` + ``trunk
  allowed vlan 32,34,47,461``).  The raw value is stashed on the scratch
  and resolved in :func:`_build_canonical_interface` once the stanza has
  closed, so the mapping does not depend on line ORDER within the
  stanza.  OS10 emits no ``switchport trunk native vlan`` line at all
  (measured: 0 occurrences), so this is the only route to a native VLAN.

* **A trunk's allowed list holds its access VLAN.**  The allowed line
  of OS10 names TAGGED VLANs and the access line states the untagged
  one beside it (``BESIDE_THE_LIST`` in ``NATIVE_VLAN_AND_THE_LIST``,
  :mod:`.._helpers`), while in the tree a trunk's list is everything
  the port carries and a native VLAN outside it is not carried.  So
  the access VLAN is added to the list the allowed line states
  (:func:`.._helpers.trunk_list_read`): ``access vlan 1`` beside
  ``trunk allowed vlan 32,34`` is native 1 and the list ``1,32,34``,
  and a trunk with an access line and no allowed line is the list of
  that one VLAN.  ``no switchport access vlan`` takes back an access
  VLAN stated above it in the stanza, and the trunk then has no
  native VLAN.

* **``management route`` is not ``ip route``.**  It outnumbers ``ip
  route`` 8:2 in the corpus and installs a default into the management
  VRF only.  Parsing it as a global static route would put a
  management-only default into the global RIB.  It is harvested onto
  ``CanonicalStaticRoute.vrf="management"`` — OS10's own name for that
  VRF — which preserves the operator's intent without polluting the
  global table.

* **OS10 declares no top-level ``vlan <id>`` stanza.**  Unlike NX-OS /
  Arista there is no ``vlan 10 / name PROD`` form and no ``tagged`` /
  ``untagged`` member lines (measured: 0 of each).  VLANs are implied by
  ``interface vlan<N>`` SVIs and by per-port switchport membership, so
  :func:`_synthesize_vlans_from_svis` plus the shared switchport
  projection are the ONLY sources of ``intent.vlans``.

* ``ipv6 address autoconfig`` (×10) and ``no ip address`` / ``no ip
  address dhcp`` are negations and stateless-autoconfig markers, not
  addresses.  The address regexes require a literal ``/<prefix>`` so
  none of them match.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from collections.abc import Callable

from ..._tier3_detection import (
    LEFT_OUT_ROWS_SHOWN,
    _shown_label,
    is_a_dellos10_section_line,
    no_command_row,
)
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
)
from ...limits import ticked
from .._helpers import (
    TrunksByName,
    Uniques,
    _is_link_local_v6,
    _mask_to_prefix,
    address_key,
    keyword_stanza_rows,
    mtu_read,
    one_interface_named,
    spaced_port_name,
    trunk_list_read,
    without_stanzas_of_no_one_interface,
)
from .._input_shape import detect_input_shape
from .._scanner import Body, first_flat_stanza, scan_stanzas, without_text_bodies
from ..base import ParseError
from . import port_names as _port_names

logger = logging.getLogger(__name__)

_VENDOR = "dell_os10"

# ---------------------------------------------------------------------------
# Top-level globals
# ---------------------------------------------------------------------------

_HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)", re.IGNORECASE | re.MULTILINE)
#: ``! Version 10.5.1.0`` — the first line of a device dump.  Operator-authored
#: configs carry no banner and yield an empty ``source_version``.
_VERSION_RE = re.compile(r"^!\s*Version\s+(\S+)\s*$", re.IGNORECASE | re.MULTILINE)

#: ``ip vrf <name>`` at column 0 declares a VRF.  ``ip vrf default`` is the
#: global RIB stated explicitly (an OS10 tell, ×8) and is NOT a VRF record;
#: ``ip vrf forwarding`` is the per-interface bind and must not match here.
_VRF_DECL_RE = re.compile(
    r"^ip\s+vrf\s+(?!forwarding\b|default\s*$)(\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Interface stanza
# ---------------------------------------------------------------------------

#: Interface header.  Two guards, both load-bearing:
#:
#:   1. the negative lookahead rejects ``breakout`` / ``range``, which are
#:      column-0 ``interface ...`` commands that declare no interface;
#:   2. the trailing ``\s*$`` requires the header to END after the name (or
#:      after a second word that begins with a digit), so any other
#:      multi-token ``interface <verb> ...`` form fails closed instead of
#:      becoming a phantom port.
#:
#: Group 2 captures the number of a type written apart from it
#: (``interface Vlan 700``, ``interface ethernet 1/1/14``); it is
#: ``None`` for the device form.  A header the readers are given
#: names one interface: every other has had its stanza taken out
#: (:func:`_without_headers_of_no_one_interface`).
_IFACE_RE = re.compile(
    r"^interface\s+(?!breakout\b|range\b)(\S+)(?:\s+(\d\S*))?\s*$",
    re.IGNORECASE,
)

#: Splits a single-token SVI name (``vlan700``) so the keyword's case can be
#: normalised without disturbing the index.
_SVI_SPLIT_RE = re.compile(r"^vlan(\d+)$", re.IGNORECASE)
#: Matches an already-normalised SVI name, for VLAN synthesis.
_SVI_NAME_RE = re.compile(r"^vlan(\d+)$")

# ``(\S.*)`` rather than ``(.+)`` keeps the ``\s+`` separator and the value
# from both matching the same run of spaces — the polynomial-ReDoS overlap
# CodeQL flags (py/polynomial-redos).  Consumers ``.strip()`` the group, so
# requiring a non-space first character is behaviour-identical.
_DESC_RE = re.compile(r"^\s+description\s+(\S.*)$", re.IGNORECASE)
_SHUTDOWN_RE = re.compile(r"^\s+shutdown\s*$", re.IGNORECASE)
_NO_SHUTDOWN_RE = re.compile(r"^\s+no\s+shutdown\s*$", re.IGNORECASE)
_MTU_RE = re.compile(r"^\s+mtu\s+(\d+)\s*$", re.IGNORECASE)
#: ``ip address 10.0.0.122/24`` — CIDR, like NX-OS / Arista.  The leading
#: ``\s+`` means ``no ip address`` (negation) can never match.
_IP_CIDR_RE = re.compile(
    r"^\s+ip\s+address\s+(\d+\.\d+\.\d+\.\d+)/(\d+)(?:\s+(secondary))?\s*$",
    re.IGNORECASE,
)
#: ``ipv6 address 2001:db8::1/64``.  The mandatory ``/<len>`` excludes
#: ``ipv6 address autoconfig``.
_IPV6_CIDR_RE = re.compile(
    r"^\s+ipv6\s+address\s+(\S+?)/(\d+)(?:\s+(link-local))?\s*$",
    re.IGNORECASE,
)
_VRF_FORWARDING_RE = re.compile(
    r"^\s+ip\s+vrf\s+forwarding\s+(\S+)\s*$", re.IGNORECASE,
)
_NO_SWITCHPORT_RE = re.compile(r"^\s+no\s+switchport\s*$", re.IGNORECASE)
_SWITCHPORT_MODE_RE = re.compile(
    r"^\s+switchport\s+mode\s+(access|trunk)\s*$", re.IGNORECASE,
)
_SWITCHPORT_ACCESS_RE = re.compile(
    r"^\s+switchport\s+access\s+vlan\s+(\d+)\s*$", re.IGNORECASE,
)
#: ``no switchport access vlan``: the port's access VLAN is taken
#: back.  The line carries no id.
_NO_SWITCHPORT_ACCESS_RE = re.compile(
    r"^\s+no\s+switchport\s+access\s+vlan\s*$", re.IGNORECASE,
)
_SWITCHPORT_TRUNK_ALLOWED_RE = re.compile(
    r"^\s+switchport\s+trunk\s+allowed\s+vlan\s+(\S.*)$", re.IGNORECASE,
)
_CHANNEL_GROUP_RE = re.compile(
    r"^\s+channel-group\s+(\d+)\s+mode\s+(\S+)", re.IGNORECASE,
)
# ── VRRP (Phase 3b) ──
# OS10 runs REAL VRRP, so no HSRP normalisation is needed — unlike the
# NX-OS codec, whose every FHRP group becomes an `hsrp` block.  The group
# is a nested block inside an L3 interface::
#
#     interface vlan101
#      ip address 172.22.56.2/27
#      !                              <- INDENTED separator, not a terminator
#      vrrp-group 11
#       priority 150
#       virtual-address 172.22.56.1
#       no preempt
#
#: ``vrrp-group <1-255>`` opens a group.  Sub-command indent is NOT stable
#: (``virtual-address`` appears at both one and two spaces across the
#: corpus), so the block is tracked by state in the scratch rather than by
#: measuring indent depth.
_VRRP_GROUP_RE = re.compile(r"^\s+vrrp-group\s+(\d+)\s*$", re.IGNORECASE)
#: ``virtual-address <ip1> [... <ip10>]`` — up to TEN addresses on one line
#: (10.5.2 User Guide L58972), so the tail is split rather than captured as
#: a single address.
_VRRP_VADDR_RE = re.compile(
    r"^\s+virtual-address\s+(\S.*)$", re.IGNORECASE,
)
#: ⚠️ Anchored to end-of-line on purpose: a bare ``priority`` prefix also
#: matches ``priority-flow-control mode on``, which appears 24 times in the
#: corpus on ordinary data ports.
_VRRP_PRIORITY_RE = re.compile(r"^\s+priority\s+(\d+)\s*$", re.IGNORECASE)
#: OS10 VRRP preempts by DEFAULT (real VRRP), so only the negation appears
#: in real configs — ``no preempt`` x16, bare ``preempt`` never.
_VRRP_PREEMPT_RE = re.compile(r"^\s+(no\s+)?preempt\s*$", re.IGNORECASE)

#: OS10 ``channel-group ... mode`` vocabulary → canonical LAG modes.
#: ``on`` (static aggregation) is accepted for completeness though the
#: corpus carries only ``active`` (×63) and ``passive`` (×18).
_OS10_LAG_MODE_MAP = {"active": "active", "passive": "passive", "on": "static"}

# ---------------------------------------------------------------------------
# Static routes
# ---------------------------------------------------------------------------

#: ``ip route [vrf <name>] <dest>{/<len>|<mask>} <next-hop...> [<distance>]``.
#: The next-hop tail is captured whole and tokenised by
#: :func:`_split_nexthop` because OS10 accepts a SPACE-separated interface
#: next-hop (``ip route 10.1.1.0/24 ethernet 1/1/1``) that a fixed
#: ``(\S+)`` group would silently fail to match, dropping the route.
#:
#: The tail is ``\S(?:.*\S)?`` -- from its first character that is not
#: white space to its last -- and not a lazy ``\S.*?`` in front of
#: ``\s*$``: the lazy form re-reads the rest of the line for every
#: character it takes, and a run of spaces inside a route line then costs
#: its square.  The two capture the same text.
_IP_ROUTE_RE = re.compile(
    r"^ip\s+route\s+(?:vrf\s+(?P<vrf>\S+)\s+)?"
    r"(?P<dest>\d+\.\d+\.\d+\.\d+)"
    r"(?:/(?P<plen>\d+)|\s+(?P<mask>\d+\.\d+\.\d+\.\d+))"
    r"\s+(?P<rest>\S(?:.*\S)?)\s*$",
    re.IGNORECASE,
)
#: ``ipv6 route [vrf <name>] <prefix>/<len> <next-hop...> [<distance>]``.
_IPV6_ROUTE_RE = re.compile(
    r"^ipv6\s+route\s+(?:vrf\s+(?P<vrf>\S+)\s+)?"
    r"(?P<dest>[0-9A-Fa-f:]+/\d+)\s+(?P<rest>\S(?:.*\S)?)\s*$",
    re.IGNORECASE,
)
#: ``management route <dest>/<len> <gateway>`` — the management-VRF default.
#: Trailing whitespace is real in the corpus, hence ``\s*$``.
_MGMT_ROUTE_RE = re.compile(
    r"^management\s+route\s+(?P<dest>\d+\.\d+\.\d+\.\d+)/(?P<plen>\d+)"
    r"\s+(?P<rest>\S(?:.*\S)?)\s*$",
    re.IGNORECASE,
)

#: The VRF a ``management route`` installs into.  OS10's own name for the
#: out-of-band table; see the module docstring.
_MANAGEMENT_VRF = "management"

# ---------------------------------------------------------------------------
# Local users + SNMP (Phase 3a)
# ---------------------------------------------------------------------------

#: ``username <name> password <secret> role <role> [priv-lvl <0-15>]``.
#:
#: BOTH tails are optional, and for different reasons.  ``priv-lvl`` is
#: genuinely optional in the grammar — 2 of the 8 real ``username`` lines
#: omit it (``username netops password <x> role sysadmin``) — so a
#: parser that requires it silently drops those accounts.  ``password`` is
#: made optional so that a CROSS-VENDOR user carrying no secret, which the
#: render emits without a password clause, is still read back; otherwise
#: the account would vanish on re-parse.
_USERNAME_RE = re.compile(
    r"^username\s+(\S+)(?:\s+password\s+(\S+))?\s+role\s+(\S+)"
    r"(?:\s+priv-lvl\s+(\d+))?\s*$",
    re.IGNORECASE,
)
#: OS10 roles that carry full administrative privilege when the line
#: states no explicit ``priv-lvl``.
_OS10_ADMIN_ROLES = frozenset({"sysadmin", "secadmin"})

_SNMP_COMMUNITY_RE = re.compile(
    r"^snmp-server\s+community\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)
_SNMP_LOCATION_RE = re.compile(
    r"^snmp-server\s+location\s+(\S.*)$", re.IGNORECASE | re.MULTILINE,
)
_SNMP_CONTACT_RE = re.compile(
    r"^snmp-server\s+contact\s+(\S.*)$", re.IGNORECASE | re.MULTILINE,
)
_SNMP_HOST_RE = re.compile(
    r"^snmp-server\s+host\s+(\d+\.\d+\.\d+\.\d+)",
    re.IGNORECASE | re.MULTILINE,
)
#: ``snmp-server user <name> <group> <security-model>
#:      [auth {md5|sha} <key>] [priv {des|aes} <key>] [localized] [access <acl>]``
#: (10.5.2 User Guide L9085).
#:
#: ⚠️ The trailing ``localized`` keyword is the agent's statement about its
#: OWN value: present, the key is already localised against THIS switch's
#: engine ID and cannot travel (L8942); absent, the value is a passphrase
#: the switch localises itself on commit.  The keyword is captured and
#: recorded per value — re-deriving the kind from the value's SHAPE is the
#: #460 fail-open, and a sanitised digest looks exactly like a word.
#:
#: The privacy cipher is an ENUMERATED token, never a bare ``(\S+)``: a
#: greedy pair would swallow the priv KEY as the cipher and the trailing
#: ``localized`` as the key, landing real key material in the unsanitised
#: ``priv_protocol`` field (the NX-OS disclosure this shape exists to
#: avoid).
_SNMP_V3_USER_RE = re.compile(
    r"^snmp-server\s+user\s+(\S+)\s+(\S+)\s+(\d+)"
    r"(?:\s+auth\s+(md5|sha)\s+(\S+))?"
    r"(?:\s+priv\s+(des|aes)\s+(\S+))?"
    r"(?:\s+(localized))?"
    r"(?:\s+access\s+\S+)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

#: Interface-name prefix → IANA ifType hint.  OS10 uses one ``ethernet``
#: prefix for every speed.
_TYPE_HINTS: tuple[tuple[str, str], ...] = (
    ("ethernet", "ianaift:ethernetCsmacd"),
    ("mgmt", "ianaift:ethernetCsmacd"),
    ("port-channel", "ianaift:ieee8023adLag"),
    ("vlan", "ianaift:l3ipvlan"),
    ("loopback", "ianaift:softwareLoopback"),
)


def _infer_type(iface_name: str) -> str:
    """Best-effort IANA ifType from the OS10 interface-name prefix."""
    lower = iface_name.lower()
    for prefix, iftype in _TYPE_HINTS:
        if lower.startswith(prefix):
            return iftype
    return "ianaift:other"


def _column_zero_terminator(line: str) -> bool:
    """Close a stanza only on a non-indented (column-0) line.

    OS10 device dumps use a ONE-SPACE ``!`` to separate an SVI's L3
    block from its nested VRRP block, so a rule that also closed on a
    bare ``!`` at any depth would close the stanza at that separator and
    drop the rest of the interface.  The shared
    :func:`_default_terminator` once did; it now closes on column 0 only
    as well, and this module keeps its own so that its rule does not
    rest on the shared one.  Same rule ``cisco_nxos`` applies, for the
    same reason.
    """
    return bool(line) and not line[0].isspace()


def _iface_name(m: re.Match[str]) -> str:
    """Normalised interface name from an :data:`_IFACE_RE` match.

    Collapses the three measured SVI spellings (``vlan700`` ×161, ``Vlan
    700`` ×28, ``vlan 700`` ×24) onto the device-emitted ``vlan700`` so a
    single VLAN cannot enter the canonical tree under two names — and so
    a render can emit the form a real device produces.  Every other OS10
    interface type is already lower-case and single-token in 100% of
    captures and passes through verbatim; written apart from its number
    (``interface ethernet 1/1/14``, as Dell types it), it is joined to
    it (:func:`.._helpers.spaced_port_name`) in lower case, as the
    switch prints it, so that a header names the interface it names in
    either spelling.  Up to 0.7.7 a spaced ``vlan``, ``port-channel`` or
    ``loopback`` header was read in lower case, and it still is:
    ``interface Port-Channel 10`` is the LAG that ``channel-group 10``
    makes, ``port-channel10``.
    """
    name = spaced_port_name(m.group(1), m.group(2))
    if m.group(2) is not None:
        name = name.lower()
    svi = _SVI_SPLIT_RE.match(name)
    if svi:
        return f"vlan{svi.group(1)}"
    return name


# ---------------------------------------------------------------------------
# Text that is no line of the config
# ---------------------------------------------------------------------------

#: ``banner motd`` / ``banner login`` in column 0, and the delimiter.
#: Dell prints the two characters ``^C`` there, whatever was typed;
#: a generated config has one other character (CANU's ``^``).  The
#: match ends where the delimiter begins.  ``banner motd disable`` /
#: ``banner login disable`` is a command of one line, and opens
#: nothing; nor does ``banner motd`` with nothing after it, nor ``no
#: banner ...``.
_OPENS_A_BANNER_RE = re.compile(r"^banner[ \t]+(?:motd|login)[ \t]+(?=[^ \t])", re.IGNORECASE)
#: The delimiter Dell prints: two characters, one delimiter.
_PRINTED_DELIMITER = "^C"
#: OS10's comment mark: a line that is ``!`` alone, after a banner
#: delimited by ``!``, is a comment as likely as it is that banner's
#: real end, so it is not refused (a known limitation).
_COMMENT_MARK = "!"

#: Said of a banner that is still open at the end of the text.  Each
#: sentence quotes nothing of the text, and names no delimiter: the
#: delimiter is the operator's.
UNENDED_BODY_MESSAGE = (
    "dell_os10: line {line} opens a banner that runs to the end of "
    "this text: a banner ends at a line that holds nothing but the "
    "delimiter written after `banner motd` or `banner login`, in "
    "column 0, and this one has none.  Read as it stands, every line "
    "after line {line} is the banner's text, and no line of it is "
    "configuration.  Paste the output of `show running-configuration` "
    "whole."
)
#: Said of a banner line with more than its delimiter after its type.
MORE_ON_THE_OPENER_MESSAGE = (
    "dell_os10: line {line} opens a banner with more than its delimiter "
    "after `banner motd` or `banner login`.  `show running-configuration` "
    "prints that line with the delimiter after it and nothing else, and "
    "the banner's text on the lines below; so where this banner ends, "
    "and where the configuration goes on, cannot be told.  Paste the "
    "output of `show running-configuration` whole."
)
#: Said of a line outside every banner that is the delimiter of a
#: banner opened before it.
ORPHAN_MESSAGE = (
    "dell_os10: line {line} is outside every banner, and holds nothing "
    "but the delimiter of the banner that line {opened} opens: that "
    "banner's text holds a line of its delimiter alone too, and so "
    "ended before its end, and where it really ends, and where the "
    "configuration goes on, cannot be told.  Change the banner on the "
    "switch so that no line of its text is the delimiter alone, or "
    "remove the banner's lines from the text you paste."
)

#: Said of a text with no indentation whose stanzas have their bodies
#: at the left margin (:func:`_refuse_a_flat_text`).  It quotes
#: nothing of the text, and gives this parser's reason, not the
#: switch's: what the switch makes of such a text is not established
#: here.
FLAT_TEXT_MESSAGE = (
    "dell_os10: this text has no indentation.  No line but a comment "
    "begins with white space.  `show running-configuration` prints the lines of a "
    "stanza indented under it, and this parser tells which lines "
    "belong to a stanza by their indentation, so it cannot tell where "
    "a stanza of this text ends: line {line} opens one, and the line "
    "after it is at the left margin.  "
    "Paste the output of `show running-configuration` as the switch prints "
    "it, with its indentation."
)

#: The headers of the stanzas this parser reads by their indentation
#: (``interface``, a VLAN and a LAG among them).
#: In a text with no indentation, one of them followed by a line that
#: is none of them, no ``!``, no comment, no ``exit`` and no ``end``
#: has its body at the left margin
#: (:func:`.._scanner.first_flat_stanza`).
_STANZA_HEADERS = (_IFACE_RE,)


def _ends_at_a_line_of(delimiter: str) -> Callable[[str, int], bool]:
    """A banner that ends at a line that is *delimiter* and nothing else,
    in column 0, white space after it allowed (Dell: "a line that
    contains only the delimiter character"; the white space is
    inferred).  A line with white space in front of it is the banner's
    text: the safe side, since the banner then runs on to a later line,
    or is refused."""

    def ends(text: str, number: int) -> bool:
        return text.rstrip() == delimiter

    return ends


def _openers() -> Callable[[str, int], Body | None]:
    """The ``opens`` of one pass (:func:`without_banner_bodies`).

    It remembers the line of the last banner each delimiter opened, and
    refuses a later line outside every banner that is that delimiter
    alone (:data:`ORPHAN_MESSAGE`; the comment mark excepted): a stored
    text with a line of the delimiter alone ends there, early, and the
    line the switch printed after the text is left behind.  Not seen
    so: a stored text whose part after that line opens another banner,
    which then takes the line the switch printed for its end.
    """
    opened: dict[str, int] = {}

    def opens(text: str, number: int) -> Body | None:
        match = _OPENS_A_BANNER_RE.match(text)
        if match is None:
            if opened:
                alone = text.rstrip()
                if alone in opened and alone != _COMMENT_MARK:
                    raise ParseError(
                        ORPHAN_MESSAGE.format(line=number, opened=opened[alone]),
                        path=f"line {number}", snippet="",
                    )
            return None
        delimiter = text[match.end():].rstrip()
        if delimiter.lower() == "disable":
            return None
        if len(delimiter) > 1 and delimiter != _PRINTED_DELIMITER:
            raise ParseError(
                MORE_ON_THE_OPENER_MESSAGE.format(line=number),
                path=f"line {number}", snippet="",
            )
        opened[delimiter] = number
        return Body(_ends_at_a_line_of(delimiter))

    return opens


def without_banner_bodies(raw: str) -> str:
    """*raw* with every line of each banner made empty, keeping its
    number (:func:`.._scanner.without_text_bodies`).

    A banner (:data:`_OPENS_A_BANNER_RE`) ends at a line that is its
    delimiter and nothing else, in column 0, white space after it
    allowed.  The delimiter in the middle of a line does not end it
    (inferred from Dell's wording).  The last line of the text may have
    no line end.

    Raises:
        ParseError: A banner has no end before the end of the text; its
            line has more than its delimiter after its type; a line of
            one ends in another character than a line feed; or a line
            outside every banner is the delimiter of one opened before
            it (:data:`ORPHAN_MESSAGE`).  Each message names the line
            and quotes nothing of the text.
    """
    return without_text_bodies(
        raw, _openers(), UNENDED_BODY_MESSAGE,
        codec="dell_os10", command="show running-configuration",
    )


#: The one row every ``interface breakout`` line makes between them:
#: the label the Tier-3 detector gives them (``_tier3_detection``).  A
#: row a line would be a row for every port a switch splits.
_BREAKOUT_ROW = "interface breakout"


def _range_header_at_column_0(raw: str) -> str:
    """*raw* with each ``interface range`` header that is written with
    white space in front of it moved to column 0.

    Two committed inputs write one so, after a ``!``, with the range's
    lines below it at the same depth.  The readers end a stanza at a
    line in column 0 only, so such a header was read as no header at
    all: its stanza was in no record and no row.  Whether the switch
    reads the line as the header is not established (no Dell page
    says how a pasted line's indentation is taken); moved to column 0
    it is a header that names no one interface, and its stanza is
    taken out and said (:func:`_without_headers_of_no_one_interface`)
    -- inside an open stanza too, which it then ends, where a range's
    lines would otherwise have been read as that stanza's.  Only
    ``range`` is moved: an indented ``interface`` line is also a line
    of other contexts (``track <n>`` / ``interface <port>
    line-protocol``), which this parser does not read.

    Returns:
        *raw* itself when it has no such line.
    """
    lines = raw.splitlines(keepends=True)
    moved = False
    for at, line in enumerate(ticked(lines)):
        if not line[:1].isspace():
            continue
        words = line.split(None, 2)
        if len(words) > 1 and words[0].lower() == "interface" and words[1].lower() == "range":
            lines[at] = line.lstrip()
            moved = True
    return "".join(lines) if moved else raw


def _without_headers_of_no_one_interface(raw: str) -> tuple[str, list[str]]:
    """*raw* without each ``interface`` stanza whose header names no
    ONE interface, and the rows of ``dropped_tier3_sections`` that say
    them.

    ``interface range ethernet1/1/1-1/1/12`` configures every port it
    names (Dell KB 000196765 types ``interface range ethernet
    1/1/14-1/1/15`` and ``interface range ethernet 1/1/3,
    1/1/14-1/1/15``), and ``interface breakout 1/1/49 map 10g-4x``
    splits a port; neither names an interface a record can be made
    for, and nor does a range or a list where a name goes, or words
    that are no one name (:func:`.._helpers.one_interface_named`).
    Each such stanza is taken out before any reader sees it, its
    body with it (:func:`.._helpers.without_stanzas_of_no_one_interface`),
    as on NX-OS and EOS.  It is in force where it was typed and is not
    translated, so its header line is a section row
    (:func:`.._helpers.keyword_stanza_rows`), except that every
    ``interface breakout`` line is one row between them
    (:data:`_BREAKOUT_ROW`).

    Returns:
        ``(text, rows)``: *raw* itself and no row when it has no such
        stanza.
    """
    raw, headers = without_stanzas_of_no_one_interface(_range_header_at_column_0(raw))
    breakout = [header for header in headers if header.split()[1].lower() == "breakout"]
    rows = keyword_stanza_rows(header for header in headers if header not in breakout)
    if breakout:
        rows.append(_BREAKOUT_ROW)
    return raw, rows


def _refuse_a_flat_text(raw: str) -> None:
    """Raise :class:`ParseError` for a text with no indentation whose
    stanzas have their bodies at the left margin.

    This parser reads a stanza's lines by their indentation.  Without it, it
    read a body line as a line of the top level: every interface address,
    description, VLAN membership and LAG member was lost, and no job said a
    line was not read.  Reading such a text by the mode each command leaves
    open, as the CLI is typed into, would need every mode's words, which no
    vendor page lists; what the device itself makes of such a text is not
    established here.  So it is refused, in this parser's words.  The shape
    is :func:`.._scanner.first_flat_stanza`'s, with this parser's headers
    (:data:`_STANZA_HEADERS`): a text with SOME lines dedented is read by
    its indentation.  Any white space in front of a line is indentation, a
    no-break space among them: the readers ask ``str.isspace`` and ``\\s``,
    and read a text so indented as it was printed.

    Raises:
        ParseError: For a text of that shape.  The message gives the
            number of the line that opens the first such stanza and
            quotes nothing of the text.
    """
    # The module's tuple, read at the call: a test that changes it
    # changes what is asked.
    flat_at = first_flat_stanza(raw, _STANZA_HEADERS, any_white_space=True)
    if flat_at is not None:
        raise ParseError(
            FLAT_TEXT_MESSAGE.format(line=flat_at),
            path=f"line {flat_at}", snippet="",
        )


#: ``ip vrf default`` names the global table, which every target has: it
#: states nothing to translate (no committed input has anything under
#: it), and :data:`_VRF_DECL_RE` makes no VRF of it.
_GLOBAL_TABLE_RE = re.compile(r"^ip[ \t]+vrf[ \t]+default[ \t]*$", re.IGNORECASE)

#: The management plane, in the forms Dell's User Guide gives (10.4.1.0,
#: the command reference of each: ``ip domain-name``, ``ip
#: name-server``, ``ntp server``, ``logging server``) and the committed
#: inputs print: ``ip domain-name <name>``, ``ip name-server <ip> [<ip>
#: ...]``, ``ntp server <host>`` and ``logging server <host>``, where a
#: host is ``{hostname | ipv4-address | ipv6-address}`` (:func:`a_host`)
#: and a name server an address.  Each is read in that bare form only.
#: A tail says something the tree cannot hold -- a VRF (``ip
#: name-server vrf <name> <ip>``, ``logging server ... vrf <name>``), an
#: NTP key or ``prefer``, a syslog transport, port or severity -- and
#: written without it the server would be another statement, so a line
#: with one is not read and keeps its row
#: (:func:`_rows_for_what_no_reader_takes`).  So does a value the form
#: does not take.
_DOMAIN_NAME_RE = re.compile(
    r"^ip[ \t]+domain-name[ \t]+(\S+)[ \t]*$", re.IGNORECASE,
)
_NAME_SERVER_RE = re.compile(
    r"^ip[ \t]+name-server[ \t]+(\S(?:.*\S)?)[ \t]*$", re.IGNORECASE,
)
_NTP_SERVER_RE = re.compile(r"^ntp[ \t]+server[ \t]+(\S+)[ \t]*$", re.IGNORECASE)
_LOGGING_SERVER_RE = re.compile(
    r"^logging[ \t]+server[ \t]+(\S+)[ \t]*$", re.IGNORECASE,
)


def an_address(value: str) -> bool:
    """Whether *value* is an IPv4 or IPv6 address, which is what the
    management-plane forms this codec reads and writes take."""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def a_domain_name(value: str) -> bool:
    """Whether *value* is shaped as a domain name: ASCII letters,
    digits, ``-`` and ``.``, beginning with a letter or a digit, and
    no longer than the 253 characters a name's text may have (RFC
    1035).  ``vrf`` alone is the first word of the VRF form."""
    return (
        0 < len(value) <= 253
        and value[0].isascii()
        and value[0].isalnum()
        and all(c.isascii() and (c.isalnum() or c in "-.") for c in value)
        and value.lower() != "vrf"
    )


def a_host(value: str) -> bool:
    """Whether *value* is what ``ntp server`` and ``logging server``
    take: Dell's User Guide (10.4.1.0) gives ``{hostname |
    ipv4-address | ipv6-address}`` for each, and a host name in its
    examples.  A host name is shaped as a domain name and holds a
    letter: ``1.2.3`` is neither an address nor a name."""
    return an_address(value) or (
        a_domain_name(value) and any(c.isalpha() for c in value)
    )


def _domain_name_of(line: str) -> str:
    """The domain of an ``ip domain-name <name>`` line, or ``""``."""
    m = _DOMAIN_NAME_RE.match(line)
    return m.group(1) if m and a_domain_name(m.group(1)) else ""


def _name_servers_of(line: str) -> list[str]:
    """The resolvers of an ``ip name-server <ip> [<ip> ...]`` line, or
    ``[]`` where a word of it is not an address (``vrf <name>``)."""
    m = _NAME_SERVER_RE.match(line)
    if not m:
        return []
    servers = m.group(1).split()
    return servers if all(an_address(s) for s in ticked(servers)) else []


def _ntp_server_of(line: str) -> str:
    """The server of an ``ntp server <host>`` line, or ``""``."""
    m = _NTP_SERVER_RE.match(line)
    return m.group(1) if m and a_host(m.group(1)) else ""


def _logging_server_of(line: str) -> str:
    """The server of a ``logging server <host>`` line, or ``""``."""
    m = _LOGGING_SERVER_RE.match(line)
    return m.group(1) if m and a_host(m.group(1)) else ""


#: The lines in column 0 a reader of this module takes, by what each
#: reader asks of a line: a pattern's ``match``, or a function that
#: gives what the line holds and nothing where it is not read.  A line
#: none of them takes is translated by nothing
#: (:func:`_rows_for_what_no_reader_takes`).  A reader that is added to
#: the parse is added here, and the other way round.  An ``interface``
#: header is not here: it is a record or a row of its own
#: (:func:`_an_interface_header_is_said`).
_TOP_LEVEL_READERS: tuple[Callable[[str], object], ...] = (
    _HOSTNAME_RE.match,
    _VRF_DECL_RE.match,
    _GLOBAL_TABLE_RE.match,
    _IP_ROUTE_RE.match,
    _IPV6_ROUTE_RE.match,
    _MGMT_ROUTE_RE.match,
    _USERNAME_RE.match,
    _SNMP_COMMUNITY_RE.match,
    _SNMP_LOCATION_RE.match,
    _SNMP_CONTACT_RE.match,
    _SNMP_HOST_RE.match,
    _SNMP_V3_USER_RE.match,
    _domain_name_of,
    _name_servers_of,
    _ntp_server_of,
    _logging_server_of,
)

#: Words of a session, not of the configuration: a pasted ``configure
#: terminal``, ``end`` or ``write memory`` holds nothing to translate.
_SESSION_WORDS = frozenset({"configure", "end", "exit", "write"})

#: The words OS10 configurations begin a line in column 0 with, which a
#: row may show: a line that begins with another word is said all the
#: same, in a row that counts such lines and shows none of their text
#: (:func:`_rows_for_what_no_reader_takes`).  A word missing here costs
#: a row its name, never the row.
_COMMAND_WORDS = frozenset({
    "aaa", "alias", "banner", "bfd", "boot", "class-map", "clock",
    "control-plane", "crypto", "dcbx", "default", "dot1x", "enable",
    "errdisable", "evpn", "exec-timeout", "hardware", "hash-algorithm",
    "hostname",
    "interface", "ip", "ipv6", "iscsi", "line", "lldp", "load-balancing",
    "logging", "login", "mac", "management", "monitor", "nve", "ntp",
    "object-group", "password-attributes", "policy-map", "port-group",
    "qos-map", "radius-server", "rest", "route-map", "router",
    "scale-profile", "service", "sflow", "snmp-server", "spanning-tree",
    "support-assist", "system", "system-user", "tacacs-server",
    "telemetry", "track", "trust", "uplink-state-group", "username",
    "userrole", "virtual-network", "vlt-domain", "vrrp", "wred", "ztd",
})

#: The words of :data:`_COMMAND_WORDS` whose second word says which of
#: their commands a line is (``ntp server``, ``logging server``, ``clock
#: timezone``, ``snmp-server enable``).  After any other the second word
#: is often a name the operator chose, which a row does not show.
_FAMILIES = frozenset({
    "aaa", "banner", "bfd", "boot", "clock", "crypto", "dcbx", "default",
    "enable", "evpn", "hardware", "interface", "ip", "ipv6", "iscsi",
    "line", "lldp", "logging", "login", "mac", "management", "monitor",
    "ntp", "password-attributes", "radius-server", "rest", "router",
    "service", "snmp-server", "spanning-tree", "system", "tacacs-server",
})

#: A word that says which command of a family a line is: no digit, dot
#: or slash, which a value (an address, a number, a time zone) has, and
#: no longer than a command word.
_A_SUB_COMMAND_RE = re.compile(r"[a-z][a-z-]{0,63}\Z")


def _an_interface_header_is_said(line: str) -> bool:
    """Whether the ``interface`` header *line* is a record
    (:data:`_IFACE_RE`) or the header of a stanza that is taken out and
    has a row of its own (:func:`_without_headers_of_no_one_interface`:
    one that names no one interface)."""
    return bool(_IFACE_RE.match(line)) or (
        len(line.split(None, 2)) > 1 and not one_interface_named(line)
    )


def _command_label(words: list[str]) -> str:
    """The row for a line in column 0 whose first words are *words*: its
    command word, and after a word of :data:`_FAMILIES` the word that
    says which of its commands it is; after ``no``, the same of the
    command it takes back.  Empty where the command word is not one of
    :data:`_COMMAND_WORDS`.  Never a value: cut after a word that names
    a secret, as every row is (``_tier3_detection._shown_label``)."""
    shown: list[str] = []
    if words and words[0].lower() == "no":
        shown.append("no")
        words = words[1:]
    if not words or words[0].lower() not in _COMMAND_WORDS:
        return ""
    shown.append(words[0].lower())
    if (
        shown[-1] in _FAMILIES
        and len(words) > 1
        and _A_SUB_COMMAND_RE.match(words[1].lower())
    ):
        shown.append(words[1].lower())
    return _shown_label(" ".join(shown))


def _rows_for_what_no_reader_takes(raw: str) -> list[str]:
    """The rows of ``dropped_tier3_sections`` for the lines in column
    0 that nothing translates.

    A line in column 0 is a statement of the top level, or the header
    of a stanza whose lines are under it.  One that no reader takes
    (:data:`_TOP_LEVEL_READERS`, :func:`_an_interface_header_is_said`),
    that no Tier-3 pattern gives a row of its own
    (``_tier3_detection.is_a_dellos10_section_line``) and that is
    not a word of a session (:data:`_SESSION_WORDS`) is in no output,
    and a row says so.  It is a row of its command word
    (:func:`_command_label`), one for each kind of line, past
    ``_tier3_detection.LEFT_OUT_ROWS_SHOWN`` of them one that counts
    the rest; a line that begins with a word OS10 configurations are
    not seen to begin with is counted in one row, with the number of
    the first such line and nothing of its text
    (``_tier3_detection.no_command_row``), which is no sign that the
    text was a config.  A line that does not begin with a letter is
    no command, and is not counted.

    Up to 0.7.7 only the kinds a pattern named had a row, and an OS10
    config's NTP and syslog servers, its DNS, its time zone, its
    spanning tree, its DCBX and LLDP settings and its VXLAN overlay
    (``nve``, ``virtual-network``) were in no output and no row, in
    jobs that said ``completed``.  So every line is asked, not a list
    of kinds: a list says nothing of a kind nobody put on it.  Not
    reached: a line of a stanza (indented) that the stanza's reader
    does not take.

    Args:
        raw: The text the readers are given, before any stanza is
            taken out of it, so that a line has the number it has in
            the text that was pasted.

    Returns:
        The rows, in the order their lines come; the row that counts
        lines with no known command word last.
    """
    rows: dict[str, None] = {}
    unknown = 0
    first_unknown = 0
    for number, line in enumerate(ticked(raw.splitlines()), start=1):
        if not line[:1].isalpha():
            continue
        words = line.split(None, 3)
        head = words[0].lower()
        if head in _SESSION_WORDS:
            continue
        if head == "interface" and _an_interface_header_is_said(line):
            continue
        if any(reader(line) for reader in _TOP_LEVEL_READERS):
            continue
        if is_a_dellos10_section_line(line):
            continue
        label = _command_label(words)
        if label:
            rows[label] = None
            continue
        unknown += 1
        first_unknown = first_unknown or number
    shown = list(rows)
    if len(shown) > LEFT_OUT_ROWS_SHOWN:
        unlisted = len(shown) - LEFT_OUT_ROWS_SHOWN
        shown[LEFT_OUT_ROWS_SHOWN:] = [
            f"({unlisted} more kinds of top-level command not read; not listed)"
        ]
    if unknown:
        shown.append(no_command_row(unknown, first_unknown))
    return shown


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse Dell OS10 ``show running-configuration`` output into a
    :class:`CanonicalIntent`.

    Raises:
        ParseError: If the input is empty or looks like XML / JSON rather
            than OS10 CLI text; or if a banner cannot be told from the
            configuration (:func:`without_banner_bodies`); or if the text
            has no indentation (:func:`_refuse_a_flat_text`).
    """
    if not raw.strip():
        raise ParseError("dell_os10: empty input", snippet="")

    # A banner is text, never lines of the config: every reader below --
    # the shape check among them -- is given the text with each banner's
    # lines empty, each keeping its number.
    # ``given``: the length of the text as it came, for the debug line
    # at the end.
    given = len(raw)
    raw = without_banner_bodies(raw)
    shape = detect_input_shape(raw)
    if shape is not None:
        raise ParseError(
            f"dell_os10: input looks like {shape.upper()}, not Dell OS10 "
            f"CLI.  Paste the output of `show running-configuration`.",
            snippet=raw.lstrip()[:120],
        )
    # A text with no indentation is refused in words, before any
    # reader takes a stanza's body for lines of the top level.
    _refuse_a_flat_text(raw)

    intent = CanonicalIntent(
        source_vendor="dell_os10",
        source_format="cli-dellos10",
    )

    # A line in column 0 that no reader below takes is a row, after
    # the others; counted here, where every line has its number.
    unread = _rows_for_what_no_reader_takes(raw)

    # A header that names no one interface (``interface range ...``,
    # ``interface breakout ...``, a range where a name goes) has its
    # stanza taken out of the text every reader below is given, and
    # is a section row.
    raw, intent.dropped_tier3_sections = _without_headers_of_no_one_interface(raw)

    intent.hostname = _extract_hostname(raw)
    intent.source_version = _extract_version(raw)
    intent.routing_instances = _parse_routing_instances(raw)
    intent.interfaces = _parse_interfaces(raw)
    intent.static_routes = _parse_static_routes(raw)
    intent.lags = _parse_lags(raw)
    intent.local_users = _parse_local_users(raw)
    intent.snmp = _parse_snmp(raw)
    _parse_management_plane(raw, intent)
    intent.dropped_tier3_sections += unread

    # OS10 has no top-level ``vlan <id>`` stanza, so every VLAN record is
    # derived — from an SVI, or from per-port switchport membership.
    intent.vlans = []
    _synthesize_vlans_from_svis(intent)

    # Shared switchport→VLAN projection, with the phantom-VLAN guard:
    # snapshot the legitimate ids first, project, then prune.  A wide
    # ``switchport trunk allowed vlan 1-4094`` must not inflate
    # ``intent.vlans`` with thousands of phantom records, but a single
    # operator-declared access / native VLAN with no SVI is legitimate
    # and has to survive — as are the members of a narrow ``switchport
    # trunk allowed`` list, which is a specific declaration rather than
    # the "allow everything" idiom.
    from ...canonical.transforms import (
        project_switchport_to_vlan,
        switchport_declared_vlan_ids,
    )

    # See ``canonical.transforms.switchport_declared_vlan_ids``.
    legitimate_vlan_ids = (
        {v.id for v in intent.vlans} | switchport_declared_vlan_ids(intent)
    )
    project_switchport_to_vlan(intent, keep=legitimate_vlan_ids)
    intent.vlans = [v for v in intent.vlans if v.id in legitimate_vlan_ids]

    logger.debug(
        "dell_os10 parsed: hostname=%r ifaces=%d vlans=%d routes=%d "
        "lags=%d vrfs=%d (input=%d chars)",
        intent.hostname,
        len(intent.interfaces),
        len(intent.vlans),
        len(intent.static_routes),
        len(intent.lags),
        len(intent.routing_instances),
        given,
    )
    return intent


def _extract_hostname(raw: str) -> str:
    m = _HOSTNAME_RE.search(raw)
    return m.group(1) if m else ""


def _extract_version(raw: str) -> str:
    """Return the OS10 release from the ``! Version 10.5.1.0`` banner.

    Stored as :attr:`CanonicalIntent.source_version` (metadata, excluded
    from every comparator) so a same-vendor render can echo the device's
    own release rather than relabelling it with a constant (#297).
    """
    m = _VERSION_RE.search(raw)
    return m.group(1) if m else ""


def _parse_routing_instances(raw: str) -> list[CanonicalRoutingInstance]:
    """Extract column-0 ``ip vrf <name>`` declarations.

    ``ip vrf default`` is excluded by :data:`_VRF_DECL_RE` — OS10 states
    the global RIB as an explicit stanza (it is one of the markers that
    identifies an OS10 config at all), but it is not a VRF and must not
    become a routing-instance record.

    The per-interface ``ip vrf forwarding <name>`` bind is harvested by
    :func:`_parse_interfaces` onto ``CanonicalInterface.vrf``; it never
    materialises an instance here, so a config that binds a port to a VRF
    it never declared cannot conjure a phantom routing-instance.
    """
    seen: set[str] = set()
    instances: list[CanonicalRoutingInstance] = []
    for m in _VRF_DECL_RE.finditer(raw):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)
        instances.append(CanonicalRoutingInstance(name=name))
    return instances


def _new_iface_scratch(name: str) -> dict:
    """Fresh per-interface parse-time scratch dict.

    Single source of truth for the field set so the stanza-open site and
    the build step cannot drift apart.
    """
    return {
        "name": name,
        "description": "",
        "enabled": True,
        "type": _infer_type(name),
        "mtu": None,
        "ipv4": [],
        "ipv6": [],
        "vrf": "",
        "switchport_mode": None,
        # Raw ``switchport access vlan <N>`` value.  Resolved to EITHER
        # access_vlan or trunk_native_vlan at build time — see
        # _build_canonical_interface.
        "access_vlan_raw": None,
        "lag_member_of": None,
        # VRRP (Phase 3b): {gid: {virtual_ips, priority, preempt}}.
        "vrrp_groups": {},
        "_vrrp_gid": None,   # active group while inside a vrrp-group block
    }


def _parse_interfaces(raw: str) -> list[CanonicalInterface]:
    """Extract ``interface <name>`` stanzas from OS10 config text.

    Per interface: description, admin state, mtu, IPv4 / IPv6 (CIDR), VRF
    bind, L2 switchport state and ``channel-group`` LAG membership.
    """
    # What each interface states about its trunk, by the name its
    # header writes: a stanza can be met twice, and the list is the
    # interface's.
    trunks = TrunksByName("dell_os10")

    def _open(m: re.Match[str]) -> dict:
        scratch = _new_iface_scratch(_iface_name(m))
        # Which interface the stanza is of, for ``trunks``: its header
        # line, not the name read from it.
        scratch["trunk_key"] = trunks.key(m.string)
        return scratch

    def _on_line(line: str, current: dict) -> None:
        # ── VRRP nested block (Phase 3b) ──
        # Tracked by scratch state rather than indent depth: the
        # sub-command indent is not stable across the corpus.
        vg = _VRRP_GROUP_RE.match(line)
        if vg:
            current["vrrp_groups"].setdefault(int(vg.group(1)), {
                "virtual_ips": [],
                "priority": 100,
                "preempt": True,   # OS10 VRRP default: preempt ENABLED
            })
            current["_vrrp_gid"] = int(vg.group(1))
            return
        _gid = current["_vrrp_gid"]
        if _gid is not None:
            g = current["vrrp_groups"][_gid]
            vam = _VRRP_VADDR_RE.match(line)
            if vam:
                g["virtual_ips"].extend(vam.group(1).split())
                return
            prm = _VRRP_PRIORITY_RE.match(line)
            if prm:
                g["priority"] = int(prm.group(1))
                return
            pem = _VRRP_PREEMPT_RE.match(line)
            if pem:
                g["preempt"] = not bool(pem.group(1))
                return
            # Anything else closes the group and falls through to the
            # interface-level cascade below.
            current["_vrrp_gid"] = None

        dm = _DESC_RE.match(line)
        if dm:
            # Operator-authored configs quote descriptions containing
            # spaces (``description "mgmt 10.0.1.0/24"``); device output
            # does not.  Strip symmetric quotes so the two dialects agree.
            current["description"] = dm.group(1).strip().strip('"')
            return

        if _NO_SHUTDOWN_RE.match(line):
            current["enabled"] = True
            return
        if _SHUTDOWN_RE.match(line):
            current["enabled"] = False
            return

        mm = _MTU_RE.match(line)
        if mm:
            current["mtu"] = int(mm.group(1))
            return

        im = _IP_CIDR_RE.match(line)
        if im:
            current["ipv4"].append({
                "ip": im.group(1),
                "prefix_length": int(im.group(2)),
                "is_secondary": im.group(3) is not None,
            })
            return

        v6m = _IPV6_CIDR_RE.match(line)
        if v6m:
            addr = v6m.group(1)
            scope = (
                "link-local"
                if (v6m.group(3) or _is_link_local_v6(addr))
                else "global"
            )
            current["ipv6"].append({
                "ip": addr,
                "prefix_length": int(v6m.group(2)),
                "scope": scope,
            })
            return

        vm = _VRF_FORWARDING_RE.match(line)
        if vm:
            current["vrf"] = vm.group(1)
            return

        if _NO_SWITCHPORT_RE.match(line):
            # Routed port.  OS10 defaults physical / LAG ports to L2, so
            # the routed intent is stated explicitly; leaving
            # switchport_mode None already encodes "routed".
            return
        sm = _SWITCHPORT_MODE_RE.match(line)
        if sm:
            current["switchport_mode"] = sm.group(1).lower()
            trunks.mode_line(current["trunk_key"], current["switchport_mode"])
            return
        am = _SWITCHPORT_ACCESS_RE.match(line)
        if am:
            # Stash only — whether this is the access VLAN or the trunk
            # NATIVE VLAN depends on the stanza's final switchport mode,
            # which may be declared on a later line.
            current["access_vlan_raw"] = int(am.group(1))
            return
        if _NO_SWITCHPORT_ACCESS_RE.match(line):
            # Takes back what an access line above it stated: the
            # device applies each line as it meets it.  A trunk is
            # then left with no native VLAN, which is what this
            # codec's renderer writes the line for.
            current["access_vlan_raw"] = None
            return
        tam = _SWITCHPORT_TRUNK_ALLOWED_RE.match(line)
        if tam:
            current["switchport_mode"] = current["switchport_mode"] or "trunk"
            trunks.allowed_line(current["trunk_key"], tam.group(1).strip())
            return

        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            current["lag_member_of"] = f"port-channel{int(cgm.group(1))}"
            return

    interfaces = scan_stanzas(
        raw.splitlines(),
        is_header=_IFACE_RE.match,
        open_scratch=_open,
        on_line=_on_line,
        build=lambda scratch: trunks.made(
            scratch["trunk_key"], _build_canonical_interface(scratch),
        ),
        is_terminator=_column_zero_terminator,
    )
    # A trunk with no allowed line carries what the platform's trunk
    # carries by default: on OS10 its untagged (access) VLAN and no
    # tagged VLAN, which is the empty list.  A port that is not a
    # trunk and states no list has none to keep.
    trunks.settle()
    # The allowed line names the tagged VLANs; the list of the tree
    # is what the trunk carries, so the access VLAN goes into it.
    for iface in interfaces:
        if iface.switchport_mode == "trunk":
            iface.trunk_allowed_vlans = trunk_list_read(
                _VENDOR, iface.trunk_allowed_vlans, iface.trunk_native_vlan,
            )
    return interfaces


def _build_canonical_interface(raw: dict) -> CanonicalInterface:
    """Convert the parse-time scratch dict into a :class:`CanonicalInterface`.

    Resolves the ``switchport access vlan`` ambiguity here, once the whole
    stanza has been seen, so the outcome does not depend on the order the
    switchport lines appeared in:

    * mode ``trunk``  → the value is the NATIVE (untagged) VLAN, which
      :func:`_parse_interfaces` then adds to the trunk's list;
    * otherwise       → it is the access VLAN, and the port is an access
      port even if no explicit ``switchport mode access`` line was given
      (OS10 defaults a switched port to access).

    Mapping the trunk case to ``access_vlan`` would invert the port's L2
    semantics on every downstream codec — the class of defect #239 fixed
    for Junos.

    The record is made with no allowed list.  That list is the
    interface's, which another stanza of the same name can state, and
    :func:`_parse_interfaces` gives it when every stanza has been
    read (:class:`.._helpers.TrunksByName`).
    """
    mode = raw.get("switchport_mode")
    access_raw = raw.get("access_vlan_raw")
    access_vlan = None
    trunk_native = None
    if access_raw is not None:
        if mode == "trunk":
            trunk_native = access_raw
        else:
            access_vlan = access_raw
            mode = mode or "access"

    # VRRP groups (Phase 3b) → CanonicalVRRPGroup(mode="vrrp").  OS10 runs
    # real VRRP, so the canonical mode is the wire protocol, not a
    # normalisation.  Sorted by group id for deterministic ordering (the
    # round-trip invariant does not normalise vrrp_groups order).
    vrrp_groups = [
        CanonicalVRRPGroup(
            group_id=gid,
            mode="vrrp",
            virtual_ips=list(g.get("virtual_ips", [])),
            priority=g.get("priority", 100),
            preempt=g.get("preempt", True),
        )
        for gid, g in sorted(raw.get("vrrp_groups", {}).items())
    ]

    return CanonicalInterface(
        name=raw["name"],
        description=raw.get("description", ""),
        enabled=raw.get("enabled", True),
        interface_type=raw.get("type", ""),
        # The link MTU is a frame size; the tree's MTU is the payload.
        # Copied as it stood, ``mtu 1522`` -- Dell's link MTU for an IP
        # MTU of 1500 on a tagged member -- was ``mtu 1522`` on IOS-XE,
        # a payload 22 bytes larger.
        mtu=(
            mtu_read("dell_os10", raw["mtu"])
            if raw.get("mtu") is not None and _port_names.mtu_is_a_frame(raw["name"])
            else raw.get("mtu")
        ),
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
        switchport_mode=mode,
        access_vlan=access_vlan,
        trunk_native_vlan=trunk_native,
        lag_member_of=raw.get("lag_member_of"),
        vrrp_groups=vrrp_groups,
    )


def _lag_sort_key(name: str) -> tuple[int, int, str]:
    """Total-order sort key grouping ``port-channel<N>`` numerically."""
    m = re.match(r"^port-channel(\d+)$", name, re.IGNORECASE)
    return (0, int(m.group(1)), name) if m else (1, 0, name)


def _parse_lags(raw: str) -> list[CanonicalLAG]:
    """Build :class:`CanonicalLAG` records from OS10 config.

    Two signals, either sufficient:

    * an ``interface port-channel<N>`` stanza declares the LAG exists;
    * a ``channel-group <N> mode <m>`` line under a physical port declares
      that port a member of ``port-channel<N>``.

    Mode is the first member's mode; an empty LAG keeps
    :attr:`CanonicalLAG.mode`'s default.
    """
    members_by_lag: dict[str, list[str]] = {}
    once = Uniques()
    mode_by_lag: dict[str, str] = {}
    declared: set[str] = set()
    current_iface: str | None = None

    def _note_header(name: str) -> None:
        m = re.match(r"^port-channel(\d+)$", name, re.IGNORECASE)
        if m:
            declared.add(f"port-channel{int(m.group(1))}")

    for line in ticked(raw.splitlines()):
        hm = _IFACE_RE.match(line)
        if hm:
            current_iface = _iface_name(hm)
            _note_header(current_iface)
            continue
        if current_iface is None:
            continue
        if _column_zero_terminator(line):
            current_iface = None
            continue
        cgm = _CHANNEL_GROUP_RE.match(line)
        if cgm:
            lag_name = f"port-channel{int(cgm.group(1))}"
            mode = _OS10_LAG_MODE_MAP.get(cgm.group(2).lower(), "active")
            members = members_by_lag.setdefault(lag_name, [])
            once.add(members, current_iface)
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


def _split_nexthop(rest: str) -> tuple[str, str, int]:
    """Split a static route's next-hop tail into ``(gateway, interface, metric)``.

    OS10 accepts several shapes after the destination::

        10.1.1.1                  → gateway
        ethernet1/1/1             → egress interface
        ethernet 1/1/1            → egress interface, SPACE-separated
        ethernet 1/1/1 10.1.1.1   → interface + gateway
        10.1.1.1 200              → gateway + administrative distance

    A fixed ``(\\S+)`` capture would fail to match the space-separated
    interface form outright, silently dropping the route — hence the
    tail is captured whole and tokenised here.  A trailing all-digits
    token is the administrative distance, but only when something else
    precedes it (so a bare numeric next-hop can never be eaten as a
    metric).
    """
    tokens = rest.split()
    metric = 0
    if len(tokens) > 1 and tokens[-1].isdigit():
        metric = int(tokens[-1])
        tokens = tokens[:-1]

    def _is_ip(token: str) -> bool:
        try:
            ipaddress.ip_address(token)
        except ValueError:
            return False
        return True

    if not tokens:
        return "", "", metric
    if len(tokens) == 1:
        return (tokens[0], "", metric) if _is_ip(tokens[0]) else ("", tokens[0], metric)
    if _is_ip(tokens[-1]):
        # ``<interface...> <gateway>`` — the interface name may itself be
        # space-separated, so rejoin everything before the gateway.
        return tokens[-1], " ".join(tokens[:-1]), metric
    return "", " ".join(tokens), metric


def _parse_static_routes(raw: str) -> list[CanonicalStaticRoute]:
    """Extract ``ip route`` / ``ipv6 route`` / ``management route`` lines.

    ``management route`` is harvested with ``vrf="management"`` rather
    than as a global route — see the module docstring.  ``ip route``
    accepts both the dominant CIDR form and the legacy dotted-mask form
    the OS10 manual documents (10.5.2 User Guide L15622); no capture in
    the corpus exercises the dotted-mask form, so it is covered by a
    synthetic unit test instead.
    """
    routes: list[CanonicalStaticRoute] = []
    for line in ticked(raw.splitlines()):
        m6 = _IPV6_ROUTE_RE.match(line)
        if m6:
            gateway, iface, metric = _split_nexthop(m6.group("rest"))
            routes.append(CanonicalStaticRoute(
                destination=m6.group("dest"),
                gateway=gateway,
                interface=iface,
                metric=metric,
                vrf=m6.group("vrf") or "",
            ))
            continue

        mm = _MGMT_ROUTE_RE.match(line)
        if mm:
            gateway, iface, metric = _split_nexthop(mm.group("rest"))
            routes.append(CanonicalStaticRoute(
                destination=f"{mm.group('dest')}/{mm.group('plen')}",
                gateway=gateway,
                interface=iface,
                metric=metric,
                vrf=_MANAGEMENT_VRF,
            ))
            continue

        m4 = _IP_ROUTE_RE.match(line)
        if not m4:
            continue
        plen = m4.group("plen")
        if plen is None:
            # Legacy dotted-mask form.  A malformed / non-contiguous mask
            # raises ParseError naming this codec (shared helper).
            plen = _mask_to_prefix(m4.group("mask"), vendor=_VENDOR)
        gateway, iface, metric = _split_nexthop(m4.group("rest"))
        routes.append(CanonicalStaticRoute(
            destination=f"{m4.group('dest')}/{int(plen)}",
            gateway=gateway,
            interface=iface,
            metric=metric,
            vrf=m4.group("vrf") or "",
        ))
    return routes


def _parse_local_users(raw: str) -> list[CanonicalLocalUser]:
    """Extract ``username ... role ...`` lines.

    OS10 carries a REAL numeric privilege (``priv-lvl 0-15``) alongside the
    named role, unlike NX-OS which has only the role — so the canonical
    privilege level is read directly when stated.  When it is omitted (2 of
    the 8 real lines), it is derived from the role: ``sysadmin`` /
    ``secadmin`` are administrative, everything else is not.

    ``system-user linuxadmin`` is deliberately NOT modelled here.  It is the
    switch's underlying Linux shell account, not a NOS login, and there is
    no canonical field that would distinguish it on render — emitting it
    back as a plain ``username`` would silently convert a shell account into
    a NOS operator.  Its drop is surfaced through
    ``dropped_tier3_sections`` instead (the label is the bare keyword, so no
    hash reaches the banner).
    """
    users: list[CanonicalLocalUser] = []
    seen: set[str] = set()
    for line in ticked(raw.splitlines()):
        m = _USERNAME_RE.match(line)
        if not m:
            continue
        name, secret, role, priv = m.groups()
        if name in seen:
            continue
        seen.add(name)
        users.append(CanonicalLocalUser(
            name=name,
            hashed_password=secret or "",
            role=role,
            privilege_level=(
                int(priv) if priv
                else (15 if role.lower() in _OS10_ADMIN_ROLES else 1)
            ),
        ))
    return users


def _parse_snmp(raw: str) -> CanonicalSNMP | None:
    """Extract SNMP config (v2c community + v3 USM users).

    Returns ``None`` when the config carries no ``snmp-server`` line, so the
    tree does not gain an empty stub.

    ⚠️ The per-line ``localized`` keyword is recorded into ``auth_kind`` /
    ``priv_kind`` rather than inferred from the value.  One keyword governs
    the whole line, so it applies to both keys the user carries.

    Note on corpus coverage: the 14 OS10 captures held contain exactly one
    ``snmp-server user`` line, and it carries NO ``localized`` marker — so
    the marked branch is attested by Dell's manual (L9085) and covered
    synthetically, not by a real capture.  ``snmp-server community`` appears
    in no capture at all and is likewise manual-attested.
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

    from ..._usm_keys import LOCALISED, PLAINTEXT  # lazy: policy module

    for m in v3_matches:
        name, group, _model, auth_p, auth_pw, priv_p, priv_pw, marker = m.groups()
        kind = LOCALISED if marker else PLAINTEXT
        snmp.v3_users.append(CanonicalSNMPv3User(
            name=name,
            group=group or "",
            auth_protocol=(auth_p or "").lower(),
            auth_passphrase=auth_pw or "",
            auth_kind=kind,
            priv_protocol=(priv_p or "").lower(),
            priv_passphrase=priv_pw or "",
            priv_kind=kind,
        ))
    return snmp


def _parse_management_plane(raw: str, intent: CanonicalIntent) -> None:
    """Read the domain, the resolvers, the NTP servers and the syslog
    servers from their bare forms (:func:`_domain_name_of` and the
    readers beside it), each server once and in the order its lines
    come.  A printout holds one ``ip domain-name``; of two, the last is
    kept, and which one a switch keeps is not established.  Mutates
    *intent* in place."""
    once = Uniques()
    for line in ticked(raw.splitlines()):
        if domain := _domain_name_of(line):
            intent.domain = domain
        elif servers := _name_servers_of(line):
            for server in servers:
                once.add(intent.dns_servers, server)
        elif server := _ntp_server_of(line):
            once.add(intent.ntp_servers, server)
        elif server := _logging_server_of(line):
            once.add(intent.syslog_servers, server)


def _synthesize_vlans_from_svis(intent: CanonicalIntent) -> None:
    """Derive VLAN records from ``interface vlan<N>`` SVIs.

    OS10 declares no top-level ``vlan <id>`` stanza (measured: 0 across
    the corpus), so an SVI is the only place a VLAN's identity and its L3
    config are stated.  The SVI's description becomes the VLAN name —
    that is the only human label OS10 carries for a VLAN — and its IPv4
    addresses are mirrored onto the VLAN record so VLAN-centric target
    codecs can render the SVI.  Where the config holds an SVI's stanza
    more than once, OS10 applies them in turn: the name is the last
    description one of them states.
    """
    existing_by_id: dict[int, CanonicalVlan] = {v.id: v for v in intent.vlans}
    once = Uniques()
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
        if iface.description:
            existing.name = iface.description
        for addr in iface.ipv4_addresses:
            once.add(existing.ipv4_addresses, addr, address_key)
