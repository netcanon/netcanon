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
  sub-interfaces.  A type and its number written apart (``interface
  Bundle-Ether 10``) are one name.  ``interface preconfigure <name>``
  is configuration for an interface the system does not have: it makes
  no interface, its body is read by nothing, and a row that names it
  (``preconfigure: interface <name> ...``, a left-out row) is left on
  ``dropped_tier3_sections`` for the codec's ``parse()``.
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

* Indentation nests 3-4 deep, not 1-2, and it is what places a line:
  when the router loads a file, a line goes to the submode its
  indentation puts it in, and a line in column 0 is a line of the top
  level (inferred, strongly: Cisco's CLI model has "indentation
  tracking", and a Cisco engineer's router output shows a file with no
  indentation loaded with its lines in the wrong mode; no manual says
  it in a sentence, and what the router does with such text typed at
  its prompt is not established).  A stanza ends at a line in column
  0 (its own closing ``!`` is one).  A submode inside it (``ptp`` /
  ``lldp`` under an ``interface``) is closed by a ``!`` at the
  submode's own depth, which does not end the stanza, and a line
  indented deeper than the stanza's own first body line is the
  submode's, not the stanza's.
* IPv4 addresses use ``ipv4 address X Y`` (note the ``ipv4`` keyword,
  not IOS-XE's ``ip address``); the mask is dotted-decimal.
* Static routes live in a ``router static`` block with CIDR-form
  destinations, not top-level ``ip route X Y Z`` lines.
* Route-targets nest as ``import|export route-target`` sub-blocks with
  the RT values on their own further-indented lines (the opposite word
  order from NX-OS / IOS-XE's single-line ``route-target import <rt>``).
* The route-distinguisher lives under ``router bgp``, not the VRF stanza.

A banner is text, not configuration (:func:`without_banner_bodies`):
read as lines, a banner line ``username <name>`` with `` group
root-lr`` under it was an account on 12 of the 13 public targets.
Each banner's lines are emptied, keeping their numbers, before any
reader -- the Tier-3 rows included.  A banner opens at a line in
column 0, ``banner <type>`` or ``aaa banner login``, ends at the next
occurrence of the one character after its type (anywhere, on the line
that opens it too), and is a row of ``dropped_tier3_sections`` with its
count of lines (:func:`banner_rows`).  A banner with no end, a line
that names a banner IOS XR does not print, and a ``^`` alone in a
banner printed with ``^C`` (where it ends cannot be told) are refused
in words.

Two forms of text are refused with a :class:`ParseError` that says why
and names a line number (and quotes nothing of the text), before any
reader runs (:func:`_refuse_a_form_the_router_misplaces`):

* a text with NO indentation, where the body of a stanza this parser
  reads stands at the left margin.  The router itself would load such a
  text (as above) as lines of the top
  level -- a VRF's address-family moved to the global one, the VRF left
  empty -- and no reading of its ``!`` lines gives the tree back;
  read here it was interfaces and VRFs made of lines nested under
  routing protocols, users with no secret, and no address at all.  A
  text with SOME lines dedented is read by its indentation, as the
  router reads it.
* a line in column 0 that states an interface's setting on the
  ``interface`` line itself (``interface <name> description ...``):
  the form ``show running-config formal`` prints, by the shape Cisco
  shows it printing for class and policy maps, or a one-line command
  typed into a printed text.  Read as a header, it was a second record
  of the interface with the setting lost.  The formal form is not read,
  and a formal excerpt with no such ``interface`` line (``show
  running-config formal router static``) is not recognised.

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
from collections.abc import Callable

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
from ...limits import ticked
from .._helpers import (
    Uniques,
    _is_link_local_v6,
    _mask_to_prefix,
    keyword_stanza_rows,
    mtu_read,
    spaced_port_name,
    without_keyword_stanzas,
)
from .._input_shape import detect_input_shape
from .._scanner import Body, first_flat_stanza, scan_stanzas, without_text_bodies
from ..base import ParseError
from . import port_names as _port_names

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regex constants — module-level so they compile once per import.
# ---------------------------------------------------------------------------

_HOSTNAME_RE = re.compile(r"^hostname\s+(\S+)", re.IGNORECASE | re.MULTILINE)
#: ``domain name example.com`` — XR form (IOS-XE prefixes it with ``ip``).
_DOMAIN_RE = re.compile(
    r"^domain\s+name\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)

# ── Management-plane globals (promotion #13) — XR render-dropped DNS / NTP /
#    syslog until this wire-up (``/system/domain`` was already wired). ──
#: ``domain name-server <ip>`` — disjoint from ``domain name <fqdn>`` above
#: (``name-server`` has no whitespace after ``name``, so ``_DOMAIN_RE`` can't
#: match it, and vice-versa).
_NAMESERVER_RE = re.compile(
    r"^domain\s+name-server\s+(\S+)", re.IGNORECASE | re.MULTILINE,
)
#: NTP is a block: ``ntp`` on its own line, then indented ``server <ip>
#: [maxpoll N] [prefer]`` / ``source <iface>`` / ``update-calendar`` leaves.
#: Capture the indented body, then pull ``server`` leaves from it (the
#: ``source`` / ``update-calendar`` tails carry no ``server`` keyword).
#:
#: A body line is ``[ \t].*`` -- one space or tab, then the rest -- and
#: not ``[ \t]+.*``: the two accept the same lines, but with ``+`` a
#: long indent that is not followed by a newline is split between the
#: two every way there is, and costs its square.
_NTP_BLOCK_RE = re.compile(
    r"^ntp[ \t]*\r?\n((?:[ \t].*\r?\n)+)", re.IGNORECASE | re.MULTILINE,
)
#: The optional ``vrf <name>`` infix precedes the address on IOS-XR
#: (``server vrf MGMT 10.11.23.7``); without it the ``vrf`` keyword was
#: captured as the server and the real IP lost (HEAD-review L1-3; the
#: arista_eos ``_NTP_SERVER_RE`` twin already carries this infix).
_NTP_SERVER_LINE_RE = re.compile(
    r"^[ \t]+server\s+(?:vrf\s+\S+\s+)?(\S+)", re.IGNORECASE | re.MULTILINE,
)
#: Syslog destinations — XR spells them bare ``logging <ip>``, but ``logging``
#: also fronts non-destination sub-commands (``logging console debugging``,
#: ``logging monitor``, ``logging trap``).  Harvest the first IP-literal token
#: per ``logging`` line, validated with :mod:`ipaddress` (mirrors the sibling
#: Cisco codecs' ``_SYSLOG_LINE_RE``).
_SYSLOG_LINE_RE = re.compile(r"^[^\S\n]*logging\s+(\S.*)$", re.IGNORECASE | re.MULTILINE)

#: ``interface <name>``.  The second group is the word after the
#: name: its number, when the type and the number are written apart
#: (:func:`_header_name`).
_IFACE_RE = re.compile(r"^interface\s+(\S+)(?:\s+(\S+))?", re.IGNORECASE)
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
_AF_IPV6_UNICAST_RE = re.compile(
    r"^address-family\s+ipv6\s+unicast\b", re.IGNORECASE,
)
_STATIC_VRF_RE = re.compile(r"^vrf\s+(\S+)", re.IGNORECASE)
#: A static-route leaf: ``<dest>/<prefix> <token>...`` (CIDR destination,
#: IPv4 or IPv6).  The destination char class covers both dotted-decimal
#: (``10.0.0.0/8``) and colon-hex (``2001:db8::/32``) prefixes; the address
#: family is discriminated by the enclosing ``address-family`` block.
_STATIC_LEAF_RE = re.compile(
    r"^([0-9A-Fa-f:.]+/\d+)\s+(.+)$",
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
#: ``secret`` / ``password`` sub-lines follow, ended by a column-0 line
#: (the block's own ``!`` is one).
_USERNAME_HDR_RE = re.compile(r"^username\s+(\S+)\s*$", re.IGNORECASE)
#: single-line variant ``username <name> {secret|password} <type> <hash>``.
_USERNAME_INLINE_RE = re.compile(
    r"^username\s+(\S+)\s+(?:secret|password)\s+(\d+)\s+(\S+)", re.IGNORECASE,
)
_USER_GROUP_RE = re.compile(r"^\s+group\s+(\S+)", re.IGNORECASE)
_USER_SECRET_RE = re.compile(
    r"^\s+(?:secret|password)\s+(\d+)\s+(\S+)", re.IGNORECASE,
)
#: ``ntp`` alone on a line opens the NTP block (:data:`_NTP_BLOCK_RE`).
_NTP_HDR_RE = re.compile(r"^ntp[ \t]*$", re.IGNORECASE)

# ── A text the router would place otherwise than it reads ──
#: The headers of the stanzas this parser reads.  In a text with no
#: indentation, one of them followed by a line that is none of them,
#: no ``!``, no comment, no ``exit`` and no ``end`` has its body at the
#: left margin.
_STANZA_HEADERS = (
    _IFACE_RE, _VRF_TOP_RE, _ROUTER_STATIC_RE, _ROUTER_BGP_RE,
    _USERNAME_HDR_RE, _NTP_HDR_RE,
)
#: ``interface [preconfigure ]<name>[ <number>][ l2transport] <setting>
#: ...`` in column 0: a setting of the interface on the interface's own
#: line, as ``show running-config formal`` prints it (by the shape Cisco
#: shows it printing for class and policy maps; no source shows a formal
#: ``interface`` line).  ``show running-config`` never prints one: its
#: ``interface`` line is the name alone, or with ``l2transport``, or
#: after ``preconfigure``, and each setting is a line of its own under
#: it.  The settings are the words a body line this parser reads begins
#: with.
_SETTING_ON_THE_HEADER_RE = re.compile(
    r"^interface[ \t]+(?:preconfigure[ \t]+)?\S+(?:[ \t]+\d\S*)?"
    r"(?:[ \t]+l2transport)?[ \t]+"
    r"(?:description|ipv4|ipv6|shutdown|mtu|vrf|bundle|encapsulation)"
    r"(?![^ \t])",
    re.IGNORECASE,
)

# ── A banner is text ──
#: A line in column 0 that opens a banner: ``banner`` and one of the six
#: types of ``Cisco-IOS-XR-um-banner-cfg.yang`` (Cisco's IOS XR 3.7
#: command reference lists five of them, each in global configuration
#: only), or ``aaa banner login``, whose value Cisco's AAA model
#: describes in the same words ("c banner-text c, where 'c' is a
#: delimiting character"); then white space and the delimiter.
#: ``show running-config`` prints ``banner <type> `` and the text as it
#: is stored, which begins with the delimiter that was TYPED -- printed
#: configs show ``;``, ``#``, ``/``, ``^``, ``"``, ``c`` and ``^C`` --
#: where IOS prints every banner between two ``^C``.  The delimiter is
#: ONE character ("a delimiting character"; "End with the character
#: 'c'"): ``^C`` is ``^`` and a text that begins with ``C``, as
#: Batfish and scrapli_cfg read it.
_OPENS_A_BANNER_RE = re.compile(
    r"(?:banner[ \t]+(?:exec|incoming|login|motd|prompt-timeout|slip-ppp)"
    r"|aaa[ \t]+banner[ \t]+login)[ \t]+(?=\S)",
    re.IGNORECASE,
)
#: Any other line in column 0 that names a banner: a type IOS XR does
#: not list (``banner config-save``, or ``banner`` and a delimiter, as
#: IOS has them), or a banner with no text after its type.  Where its
#: text would end cannot be told.
_NAMES_A_BANNER_RE = re.compile(r"(?:aaa[ \t]+)?banner(?![^ \t])", re.IGNORECASE)

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


#: Said of a text with no indentation.  It quotes nothing of the text:
#: a parse failure is logged, and what a message quotes from a config
#: never goes to a log.
FLAT_TEXT_MESSAGE = (
    "cisco_iosxr: this text has no indentation.  No line but a comment "
    "begins with a space or a tab.  IOS XR places each line "
    "of a configuration by its indentation: `show running-config` prints "
    "a stanza's lines indented under it, and when it loads a "
    "configuration file the router reads a line at the left margin as a "
    "line of the top level.  So neither the router nor this parser can "
    "tell where a stanza of this text ends: line {line} opens one, and "
    "the line after it is at the left margin.  "
    "Paste the output of `show running-config` as the router prints it, "
    "with its indentation."
)
#: Said of a setting written on an ``interface`` line.  It quotes
#: nothing of the text either.
FORMAL_LINE_MESSAGE = (
    "cisco_iosxr: line {line} states an interface's setting on the "
    "`interface` line itself.  That is the form `show running-config "
    "formal` prints (or a one-line command typed into the text), and this "
    "parser reads the form `show running-config` prints, where each "
    "setting is a line of its own, indented under the `interface` line: "
    "read as it is, the line would be a second record of the interface "
    "with its setting lost.  Paste the output of `show running-config` "
    "without `formal`; if the line was typed into the text, write the "
    "setting on a line of its own under the interface."
)
#: Said of a banner that is still open at the end of the text.  It
#: quotes nothing of the text, and names no delimiter: the delimiter is
#: the operator's.
UNENDED_BODY_MESSAGE = (
    "cisco_iosxr: line {line} opens a banner that runs to the end of this "
    "text: a banner's text ends at the next occurrence of the character "
    "written after its type, and this one has none.  Read as it stands, "
    "every line after line {line} is text, and no line of it is "
    "configuration.  A banner set through NETCONF or another programmatic "
    "interface can be printed with no end of its own: give it one on the "
    "router, or remove the banner's lines from the text you paste.  "
    "Otherwise paste the output of `show running-config` whole."
)
#: Said of a line of a banner opened with ``^C`` that holds a ``^`` and
#: not the two.  It quotes nothing of the text and names no delimiter.
CARET_MESSAGE = (
    "cisco_iosxr: line {line} is a line of a banner whose delimiter is "
    "printed as a caret and a letter C, and holds a caret with no C after "
    "it.  IOS XR takes a banner's delimiter to be one character, which "
    "would end the banner there, and whether it takes those two for one "
    "is not established, which would not: where the banner ends, and "
    "where the configuration goes on, cannot be told.  Change the banner "
    "on the router so that its text holds no caret, or remove the "
    "banner's lines from the text you paste."
)
#: Said of a line in column 0 that names a banner IOS XR does not print.
UNKNOWN_BANNER_MESSAGE = (
    "cisco_iosxr: line {line} names a banner that IOS XR does not print.  "
    "`show running-config` prints a banner as `banner`, its type (exec, "
    "incoming, login, motd, prompt-timeout or slip-ppp) and its text "
    "between two of the same character, and `aaa banner login` the same "
    "way.  Where the text of this one ends, and where the configuration "
    "goes on, cannot be told.  Paste the output of `show running-config` "
    "whole, as the router prints it.  If the line was typed into the "
    "text, remove it."
)


def _refuse_a_form_the_router_misplaces(raw: str) -> None:
    """Raise :class:`ParseError` for a text this parser would misread.

    Two shapes:

    * a line in column 0 that states an interface's setting on the
      ``interface`` line (:data:`_SETTING_ON_THE_HEADER_RE`), anywhere in
      the text: the ``show running-config formal`` form, or a one-line
      command typed into a printed text;
    * a text in which no line but a comment is indented, and a stanza
      this parser reads (:data:`_STANZA_HEADERS`) is followed by a line
      that is no header of one, no ``!``, no ``exit`` and no ``end``:
      its body is at the left margin, where the router loading the file
      would read it as lines of the top level.  The shared
      :func:`.._scanner.first_flat_stanza` finds it, with this parser's
      headers: blank lines and comments (``!`` and more) are passed
      over, at any depth -- a comment belongs to the line after it, and
      is never indentation -- and indentation is a space or a tab (the
      ``ntp`` block reader, :data:`_NTP_BLOCK_RE`, takes no other).  A
      text with SOME lines dedented is not this shape: the router reads
      it by its indentation, and so does this parser.

    The first formal line is named before a flat stanza.  Each message
    gives a line number (counted as ``str.splitlines`` counts) and
    quotes nothing of the text.

    Raises:
        ParseError: For either shape.
    """
    for number, line in enumerate(ticked(raw.splitlines()), 1):
        if _SETTING_ON_THE_HEADER_RE.match(line):
            raise ParseError(
                FORMAL_LINE_MESSAGE.format(line=number),
                path=f"line {number}", snippet="",
            )
    # The module's tuple, read at the call: a test that changes it
    # changes what is asked.
    flat_at = first_flat_stanza(raw, _STANZA_HEADERS)
    if flat_at is not None:
        raise ParseError(
            FLAT_TEXT_MESSAGE.format(line=flat_at),
            path=f"line {flat_at}", snippet="",
        )


def _openers(spans: list[list] | None = None) -> Callable[[str, int], Body | None]:
    """The ``opens`` of one pass (:func:`without_banner_bodies`).

    A banner (:data:`_OPENS_A_BANNER_RE`) ends at the next occurrence of
    its delimiter, anywhere: on the line that opens it (``banner motd
    cc``, ``banner motd "Welcome"``), or in a later line, at its start,
    in its middle or at its end (Cisco: "terminating the message with
    the second occurrence of the delimiting character").  The whole of
    the line that ends it is the banner's: XR prints what follows the
    delimiter there (spaces, or more text) as part of the stored text.
    Every other line in column 0 that names a banner
    (:data:`_NAMES_A_BANNER_RE`) is refused.  So is a line of a banner
    opened with ``^C`` (or ``^c``) that holds a ``^`` and not the two
    (:data:`CARET_MESSAGE`): read as one character, the delimiter ends
    the banner there, and read as two it does not.

    Args:
        spans: Given, each banner is appended to it as ``[what, the
            number of its first line, the number of its last]``, where
            *what* is ``banner <type>`` or ``aaa banner login``.
    """

    def opens(text: str, number: int) -> Body | None:
        match = _OPENS_A_BANNER_RE.match(text)
        if match is None:
            if _NAMES_A_BANNER_RE.match(text):
                raise ParseError(
                    UNKNOWN_BANNER_MESSAGE.format(line=number),
                    path=f"line {number}", snippet="",
                )
            return None
        rest = text[match.end():]
        delimiter = rest[0]
        # ``^C`` / ``^c``, IOS's printed form: the delimiter is ``^``,
        # unless the router takes the two characters for one (not
        # established).  The two readings end the banner on the same
        # line unless a line holds a ``^`` and not the two: refused.
        caret = rest[:2] if rest[:2] in ("^C", "^c") else None
        after = rest[2:] if caret else rest[1:]
        span = [" ".join(match.group(0).lower().split()), number, number]
        if spans is not None:
            spans.append(span)

        def _end_in(line: str, at: int) -> bool:
            if delimiter not in line:
                return False
            if caret and caret not in line:
                raise ParseError(
                    CARET_MESSAGE.format(line=at), path=f"line {at}", snippet="",
                )
            return True

        def ends(line: str, at: int) -> bool:
            span[2] = at
            return _end_in(line, at)

        return Body(ends, ended=_end_in(after, number))

    return opens


def without_banner_bodies(raw: str) -> str:
    """*raw* with every line of each banner made empty, keeping its
    number (:func:`.._scanner.without_text_bodies`, with the openers of
    :func:`_openers`).

    Not handled: the value of ``crypto key generate rsa ... pubkey``,
    which Cisco's model calls "Generated keys in pem format" and whose
    printed form no source shows.  No other body of free text was found
    in Cisco's IOS XR configuration models or in printed configs.

    Raises:
        ParseError: A banner has no end before the end of the text
            (:data:`UNENDED_BODY_MESSAGE`); a line in column 0 names a
            banner IOS XR does not print (:data:`UNKNOWN_BANNER_MESSAGE`);
            a line of a banner printed with ``^C`` holds a ``^`` and not
            the two (:data:`CARET_MESSAGE`); or a line of a banner ends
            in another character than a line feed.  Each message names
            the line and quotes nothing of the text.
    """
    return without_text_bodies(raw, _openers(), UNENDED_BODY_MESSAGE, codec="cisco_iosxr")


def banner_rows(raw: str) -> list[str]:
    """A row of ``dropped_tier3_sections`` for each kind of banner in
    *raw*: what it is, how many lines its banners take and where the
    first begins (``banner motd (9 lines, from line 4)``).  It quotes
    nothing of the text, and there are at most seven.

    A banner is in force on the router and is not translated.  The count
    is there for a banner set through a programmatic interface, which XR
    can print with no end of its own (Cisco's xrdocs.io shows one): its
    text then runs on to the next occurrence of its first character, and
    lines of the configuration are taken for its text -- the safe side,
    since none of them is read, but a banner of many lines says so.
    """
    spans: list[list] = []
    without_text_bodies(raw, _openers(spans), UNENDED_BODY_MESSAGE, codec="cisco_iosxr")
    lines: dict[str, int] = {}
    first: dict[str, int] = {}
    for what, start, end in spans:
        first.setdefault(what, start)
        lines[what] = lines.get(what, 0) + end - start + 1
    return [
        f"{what} ({count} line{'' if count == 1 else 's'}, from line {first[what]})"
        for what, count in lines.items()
    ]


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse IOS-XR ``show running-config`` output into a
    :class:`CanonicalIntent`.

    Raises:
        ParseError: If the input is empty or looks like XML / JSON
            rather than IOS-XR CLI text; if it has no indentation and a
            stanza's body stands at the left margin; or if a line in
            column 0 states an interface's setting on the ``interface``
            line (the ``show running-config formal`` form).  See
            :func:`_refuse_a_form_the_router_misplaces`.  Or if a banner
            cannot be told from the configuration
            (:func:`without_banner_bodies`).
    """
    if not raw.strip():
        raise ParseError("cisco_iosxr: empty input", snippet="")

    # A banner is text, never lines of the config: read as lines, a
    # banner line ``username <name>`` with `` group root-lr`` under it
    # was an account on the target.  Every reader
    # below -- the shape check and the two refusals among them -- is
    # given the text with each banner's lines empty, each keeping its
    # number.  ``given``: the text as it came, for the banners' rows and
    # the debug line.
    given = raw
    raw = without_banner_bodies(raw)
    # A banner is not translated: a row for each kind says so, and how
    # many lines it took (:func:`banner_rows`).  The text is read again
    # only where it held one.
    rows = banner_rows(given) if raw is not given else []

    shape = detect_input_shape(raw)
    if shape is not None:
        raise ParseError(
            f"cisco_iosxr: input looks like {shape.upper()}, not IOS-XR "
            f"CLI.  Paste the output of `show running-config`.",
            snippet=raw.lstrip()[:120],
        )

    # A text the router would place otherwise than this parser reads it:
    # refused in words, before any reader makes a record of it.
    _refuse_a_form_the_router_misplaces(raw)

    intent = CanonicalIntent(
        source_vendor="cisco_iosxr",
        source_format="cli-iosxr",
    )

    # ``interface preconfigure <name>`` is configuration the router
    # holds for an interface it does not have: applied when the line
    # card is put in, and not before.  It is not translated.  Read as
    # an interface it was one named ``preconfigure``, in every target's
    # output; read as the port it names it is a second name for a cage
    # the config may already have under another speed.  The stanza is
    # taken out of the text every reader below is given, and a row of
    # ``dropped_tier3_sections`` says so: a left-out row, as for any
    # statement a device holds and does not run, so that a text with
    # nothing else in it is not taken for a config that was read.
    # (A header that begins with another word that is no type,
    # ``range`` or ``breakout``, is taken out the same way; its row
    # is the header line, a section.)
    raw, headers = without_keyword_stanzas(raw)
    intent.dropped_tier3_sections = [*keyword_stanza_rows(headers), *rows]

    intent.hostname = _extract_hostname(raw)
    intent.domain = _extract_domain(raw)
    intent.source_version = _extract_version(raw)

    # Management-plane globals (DNS / NTP / syslog) — promotion #13.
    _parse_globals(raw, intent)

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
        len(given),
    )
    return intent


def _extract_hostname(raw: str) -> str:
    m = _HOSTNAME_RE.search(raw)
    return m.group(1) if m else ""


def _extract_domain(raw: str) -> str:
    m = _DOMAIN_RE.search(raw)
    return m.group(1) if m else ""


def _parse_globals(raw: str, intent: CanonicalIntent) -> None:
    """Harvest the XR management-plane globals DNS / NTP / syslog (promotion
    #13) that the codec render-dropped until this wire-up (``domain`` is
    handled by :func:`_extract_domain`).  Mutates *intent* in place."""
    for m in _NAMESERVER_RE.finditer(raw):
        intent.dns_servers.append(m.group(1))
    for block in ticked(_NTP_BLOCK_RE.finditer(raw)):
        # ``server <ip>`` leaves inside the ``ntp`` block; drop the
        # ``maxpoll`` / ``prefer`` tails and the ``source`` / ``update-
        # calendar`` sibling lines (no ``server`` keyword).
        intent.ntp_servers.extend(_NTP_SERVER_LINE_RE.findall(block.group(1)))
    seen_syslog = set(intent.syslog_servers)
    for m in _SYSLOG_LINE_RE.finditer(raw):
        # First IP-literal token on a ``logging`` line is the syslog host;
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
    """Return the XR release from the ``!! IOS XR Configuration`` banner.

    Stored as :attr:`CanonicalIntent.source_version` (metadata).  On a
    same-vendor render the device's own release is echoed (#297); a
    cross-vendor render synthesises a fresh banner.
    """
    # Two banner forms occur in the wild:
    #   ``!! IOS XR Configuration 6.3.1``            (older)
    #   ``!! IOS XR Configuration version = 6.2.1``  (newer; also ``version 7.x``)
    # Skip the optional ``version [=]`` keyword so the capture is the release
    # number, not the literal word ``version``.  The white space before an
    # ``=`` belongs to the ``=`` (``(?:\s*=)?``): written ``\s*=?\s*``, a
    # run of spaces after ``version`` was shared out between the two every
    # way there is before the release was found not to follow.
    m = re.search(
        r"^!!\s+IOS XR Configuration\s+(?:version(?:\s*=)?\s*)?(\S+)",
        raw, re.MULTILINE,
    )
    return m.group(1) if m else ""


def _header_name(m: re.Match[str]) -> str:
    """The interface an :data:`_IFACE_RE` match names: its first word,
    or the first two as one name when they are a type and its number
    (``interface Bundle-Ether 10``; see ``spaced_port_name``)."""
    return spaced_port_name(m.group(1), m.group(2))


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
        "dot1q_vlan": None,
        # The indent of the stanza's first body line: a line indented
        # deeper is a submode's (:func:`_in_a_submode`).
        "body_indent": None,
    }


def _in_a_submode(line: str, current: dict) -> bool:
    """Whether *line* of an open stanza belongs to a submode of it.

    The stanza's own lines are at the indent of its first body line; a
    line indented deeper is under a submode (``ptp``, ``lldp``) and is
    the submode's, whatever its words.  A blank line is no body line.
    """
    if not line.strip():
        return True
    width = _indent(line)
    if current["body_indent"] is None:
        current["body_indent"] = width
    return width > current["body_indent"]


def _parse_interfaces(raw: str) -> list[CanonicalInterface]:
    """Extract ``interface <name>`` stanzas from IOS-XR config text.

    Per interface: description, enabled (``shutdown``), mtu, IPv4 (dotted
    mask → prefix), IPv6 (CIDR + scope), VRF membership (bare ``vrf
    <name>``), and Bundle-Ether membership (``bundle id <N> mode <m>`` →
    ``lag_member_of``).  A stanza ends at a line in column 0 (its closing
    ``!`` is one, the shared scanner's default); the indented ``!`` that
    closes a submode (``ptp``, ``lldp``) does not end it, and the
    submode's own lines are not the interface's (:func:`_in_a_submode`).
    ``encapsulation dot1q`` is handled by :func:`_parse_dot1q_vlans` (a
    separate scan) — it falls through this loop harmlessly.
    """
    def _on_line(line: str, current: dict) -> None:
        if _in_a_submode(line, current):
            return
        dm = _DESC_RE.match(line)
        if dm:
            current["description"] = dm.group(1).strip()
            return
        if _SHUTDOWN_RE.match(line):
            current["enabled"] = False
            return
        mm = _MTU_RE.match(line)
        if mm:
            try:
                current["mtu"] = int(mm.group(1))
            except ValueError:
                pass
            return
        im = _IPV4_RE.match(line)
        if im:
            try:
                current["ipv4"].append({
                    "ip": im.group(1),
                    "prefix_length": _mask_to_prefix(im.group(2), vendor="cisco_iosxr"),
                    "is_secondary": im.group(3) is not None,
                })
            except ParseError:
                pass
            return
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
            return
        bm = _BUNDLE_ID_RE.match(line)
        if bm:
            current["lag_member_of"] = f"Bundle-Ether{int(bm.group(1))}"
            return
        vm = _INDENTED_VRF_RE.match(line)
        if vm:
            current["vrf"] = vm.group(1)
            return
        # GAP 7: routed sub-interface 802.1Q tag.  ``encapsulation dot1q
        # <vid>`` also feeds _parse_dot1q_vlans (VLAN synthesis for
        # VLAN-centric targets); here we ALSO record it on the interface's
        # dedicated dot1q_vlan so the render emits the true tag (not just
        # when the sub-iface unit number coincides with the tag).
        em = _ENCAP_DOT1Q_RE.match(line)
        if em:
            try:
                current["dot1q_vlan"] = int(em.group(1))
            except ValueError:
                pass
            return

    # Loop skeleton (open on `interface`, close on a column-0 line, flush
    # at EOF) is the shared codecs/_scanner helper; the vendor regex
    # cascade above, and which lines are a submode's, stay here.
    return scan_stanzas(
        raw.splitlines(),
        is_header=_IFACE_RE.match,
        open_scratch=lambda m: _new_iface_scratch(_header_name(m)),
        on_line=_on_line,
        build=_build_canonical_interface,
    )


def _payload(raw: dict) -> int | None:
    """The tree's MTU, the payload, of an interface whose stanza states
    ``mtu``: the number less the Ethernet header, and 4 bytes for the
    tag of a sub-interface that carries one (Cisco: "add 4 bytes for
    each VLAN tag configured on the sub-interface").  Copied as it
    stood, ``mtu 1514`` -- the default of an IOS XR Ethernet interface
    -- was ``mtu 1514`` on IOS-XE, NX-OS, EOS and AOS-CX, an IP MTU 14
    bytes larger than the source's.  (A second tag is not read here,
    and its 4 bytes are counted in the payload.)"""
    stated = raw.get("mtu")
    if stated is None or not _port_names.mtu_counts_a_header(raw["name"]):
        return stated
    return mtu_read("cisco_iosxr", stated, tags=1 if raw.get("dot1q_vlan") is not None else 0)


def _build_canonical_interface(raw: dict) -> CanonicalInterface:
    """Convert the parse-time scratch dict into a CanonicalInterface."""
    return CanonicalInterface(
        name=raw["name"],
        description=raw.get("description", ""),
        enabled=raw.get("enabled", True),
        interface_type=raw.get("type", ""),
        mtu=_payload(raw),
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
        dot1q_vlan=raw.get("dot1q_vlan"),  # GAP 7: routed-subif 802.1Q tag
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
    # Scratch wraps the record plus the transient import/export RT-block
    # state-machine flag (``rt_mode``); a pydantic model can't carry that
    # parse-time state, and the dict is fresh per stanza so the flag resets
    # naturally on each open.  ``build`` unwraps the record.
    def _open(m: re.Match[str]) -> dict:
        return {"ri": CanonicalRoutingInstance(name=m.group(1)), "rt_mode": None}

    def _on_line(line: str, current: dict) -> None:
        if _IMPORT_RT_RE.match(line):
            current["rt_mode"] = "import"
            return
        if _EXPORT_RT_RE.match(line):
            current["rt_mode"] = "export"
            return

        stripped = line.strip()
        if current["rt_mode"] is not None:
            if stripped == "!":
                current["rt_mode"] = None
                return
            rtm = _RT_VALUE_RE.match(stripped)
            if rtm:
                rt = rtm.group(1)
                if current["rt_mode"] == "import":
                    current["ri"].rt_imports.append(rt)
                else:
                    current["ri"].rt_exports.append(rt)
            # Any other line inside an RT block — ignore (stay in mode).
            return

        dm = _VRF_DESC_RE.match(line)
        if dm:
            current["ri"].description = dm.group(1).strip()
            return
        # ``address-family`` framing / ``!`` separators / other — ignore.

    # Loop skeleton (open on `vrf`, close on dedent, flush at EOF) is the
    # shared codecs/_scanner helper; the vendor cascade + the intra-stanza
    # RT-block state machine stay here.  A column-0 ``!`` separator closes
    # the stanza; an indented ``!`` (the RT-block terminator) is handled in
    # _on_line — so the terminator replicates the former rule exactly (only
    # a non-indented line closes a stanza).  Behaviour-identical.
    return scan_stanzas(
        raw.splitlines(),
        is_header=_VRF_TOP_RE.match,
        open_scratch=_open,
        on_line=_on_line,
        build=lambda s: s["ri"],
        is_terminator=lambda line: bool(line) and not line[0].isspace(),
    )


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

    for line in ticked(raw.splitlines()):
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
    for line in ticked(raw.splitlines()):
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
    metric = 0
    tokens = m.group(2).split()
    t = 0
    while t < len(tokens):
        tok = tokens[t]
        low = tok.lower()
        # Trailing route attributes carry no canonical home (``description`` is
        # declared lossy; ``tag`` / ``track`` are dropped).  Consume the keyword
        # AND its value so it never leaks into gateway / interface / metric.
        # Pre-fix ``tag 100`` mis-filed 100 as the admin distance, and
        # ``description CORP`` / ``bfd fast-detect`` mis-filed the keyword as
        # the egress interface — re-rendering invalid CLI (HEAD-review L1-4).
        if low in ("tag", "track") and t + 1 < len(tokens):
            t += 2
            continue
        if low in ("description", "bfd"):
            # Free-text ``description`` / multi-token ``bfd fast-detect ...``
            # run to end of line — consume the remainder.
            break
        if low == "permanent":
            t += 1
            continue
        try:
            ipaddress.ip_address(tok)  # IPv4 or IPv6 next-hop
            gateway = tok
        except ValueError:
            if tok.isdigit():
                # A bare integer trailing the next-hop is the administrative
                # distance (metric).  IOS-XR interface names are never bare
                # digits, so this is unambiguous — without it the distance
                # was mis-filed as the egress interface and re-rendered as
                # ``<dest> <distance> <gw>`` (invalid CLI).
                metric = int(tok)
            elif not iface:
                iface = tok
        t += 1
    return CanonicalStaticRoute(
        destination=dest, gateway=gateway, interface=iface,
        metric=metric, vrf=vrf,
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

    for line in ticked(raw.splitlines()):
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

        if _AF_IPV4_UNICAST_RE.match(stripped) or _AF_IPV6_UNICAST_RE.match(stripped):
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


def _lag_sort_key(name: str) -> tuple[int, int, str]:
    """Total-order sort key grouping ``Bundle-Ether<N>`` numerically, with
    the verbatim name as a final tiebreaker so case-variants sort
    deterministically rather than by hash-randomised set iteration."""
    m = re.match(r"^bundle-ether(\d+)$", name, re.IGNORECASE)
    return (0, int(m.group(1)), name) if m else (1, 0, name)


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
    once = Uniques()
    mode_by_lag: dict[str, str] = {}
    declared: set[str] = set()
    current_iface: str | None = None
    # The open stanza's depth, as :func:`_parse_interfaces` keeps it: a
    # ``bundle id`` under a submode is not the port's.
    depth: dict = {"body_indent": None}

    def _note_header(name: str) -> None:
        if name.lower().startswith("bundle-ether"):
            declared.add(name)

    for line in ticked(raw.splitlines()):
        m = _IFACE_RE.match(line)
        if m:
            current_iface = _header_name(m)
            _note_header(current_iface)
            depth["body_indent"] = None
            continue
        if current_iface is None:
            continue
        if line and not line[0].isspace():
            current_iface = None
            m = _IFACE_RE.match(line)
            if m:
                current_iface = _header_name(m)
                _note_header(current_iface)
                depth["body_indent"] = None
            continue
        if _in_a_submode(line, depth):
            continue
        bm = _BUNDLE_ID_RE.match(line)
        if bm:
            lag_name = f"Bundle-Ether{int(bm.group(1))}"
            mode = _IOSXR_LAG_MODE_MAP.get(bm.group(2).lower(), "active")
            members = members_by_lag.setdefault(lag_name, [])
            if current_iface:
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

    for line in ticked(raw.splitlines()):
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
            current = {
                "name": hm.group(1), "group": "", "secret": "",
                "body_indent": None,
            }
            continue

        if current is None:
            continue

        # A line in column 0 closes the block (its own `!` is one).  An
        # indented `!` closes a submode inside it, whose lines are not
        # the user's, as for an interface.
        if line and not line[0].isspace():
            _flush()
            continue
        if _in_a_submode(line, current):
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
