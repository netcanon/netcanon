"""
Tier-3 section detection — surface what the codecs deliberately drop.

The canonical model classifies firewall_rules / nat_rules / vpn /
routing_protocols as Tier-3 ("parse for display, never auto-render";
see ``netcanon/migration/canonical/intent.py`` Tier 3 docstring).
Codec parsers silently skip these stanzas because there's no canonical
surface to populate.

This module surfaces the silent drop honestly: each codec calls a
per-vendor detector (``detect_tier3_sections_<vendor>(raw)``) before
returning its parsed intent, populating
:attr:`CanonicalIntent.dropped_tier3_sections` with a list of
human-readable section labels.  The migrate page renders these as a
"Detected in source but not translated" banner so operators see what
was dropped.  (The detectors here are not the list's only writers:
a parser that reads something and does not translate it adds a row
itself -- the IOS-XE CLI and IOS XR parsers for a stanza a keyword
opens, the OPNsense parser for a DHCP pool with no interface -- and
its codec's ``parse()`` puts those rows after the detector's.)

Public functions:
    * :func:`detect_tier3_sections_iosxe_cli` — IOS-XE / Arista CLI shape
    * :func:`detect_tier3_sections_junos` — Junos ``set`` form
    * :func:`detect_tier3_sections_fortios` — FortiOS ``config <path>`` shape
    * :func:`detect_tier3_sections_routeros` — RouterOS ``/path`` shape
    * :func:`detect_tier3_sections_opnsense` — OPNsense XML element list
    * :func:`detect_tier3_sections_iosxe_xml` — Cisco IOS-XE NETCONF / OpenConfig
      XML; currently a no-op (NETCONF input is rarely a vehicle for
      firewall / QoS / route-map config — those live in CLI), but
      retained for symmetry so the per-codec hook is structurally
      identical.
    * :func:`left_out_row` / :func:`left_out_rows` /
      :func:`is_left_out_row` — the row for a statement a parser
      read and left out on purpose (a Junos statement the source
      had deactivated, an IOS XR stanza held for an interface the
      router does not have), the rows for all of them (bounded,
      and one row for statements that read alike), and the test
      that tells such a row from a section header.

Each returns a list of section labels like::

    ["ip access-list extended OUTSIDE_IN",
     "ip nat inside source list 10",
     "crypto isakmp policy 10"]

Detection is best-effort heuristic on stanza headers — not a parse.
False positives are preferred to false negatives (the goal is
"operator sees something" not "operator sees an exact list").  The
output is OUTPUT-ONLY: it never feeds the renderer or any transform.
This is a notification surface, not a translator.

Every pattern here is applied to the whole source text, which is
whatever was pasted.  A pattern for an indented line begins
``^[^\\S\\n]`` — white space that is not a newline — never ``^\\s``:
``\\s`` crosses newlines, so from every line start it would walk the
whole run of blank lines it is in, and a run costs its square.
``tests/unit/test_untrusted_text_cost.py`` times each of them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from .limits import ticked

# IOS-XE CLI / Arista EOS shape — patterns target only stanzas that
# the CLI parsers do NOT consume (firewall, QoS, route-maps, crypto).
# Stanzas that the parsers DO consume (`interface`, `vlan`, `router`,
# `snmp-server`, `ntp server`, `username`, `radius server`, etc.) are
# deliberately excluded so the banner doesn't lie about what was
# dropped.
_IOSXE_TIER3_HEADERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^ip access-list (?:extended|standard)\s+\S+", re.MULTILINE),
    re.compile(r"^ipv6 access-list\s+\S+", re.MULTILINE),
    re.compile(r"^access-list\s+\d+\s+(?:permit|deny)\b.*$", re.MULTILINE),
    # Indented interface-level ACL binding (`ip access-group BLOCK in`). The
    # ACL *definition* above is column-0, but the per-interface *binding* is
    # indented under `interface`, so it slipped past the column-0 anchors —
    # and a config that lost an inbound/outbound packet filter validated
    # `severity=ok` with no banner (worse: when the ACL definition lives
    # off-box, NOTHING fired). Require `ip`/`ipv6` immediately before
    # `access-group` so `ip igmp access-group` (a multicast join-filter) is
    # excluded, plus a trailing `in`/`out` direction (blind audit 81d9740 T0-4).
    re.compile(r"^[^\S\n]+ip(?:v6)?\s+access-group\s+\S+\s+(?:in|out)\b", re.MULTILINE),
    re.compile(r"^ip nat\s+(?:inside|outside|pool)\b.*$", re.MULTILINE),
    re.compile(r"^class-map\b.*$", re.MULTILINE),
    re.compile(r"^policy-map\b.*$", re.MULTILINE),
    re.compile(r"^route-map\s+\S+", re.MULTILINE),
    re.compile(r"^crypto (?:isakmp|ipsec|map|pki)\b.*$", re.MULTILINE),
    re.compile(r"^zone-pair security\b.*$", re.MULTILINE),
    # Arista MLAG.  Neither half has a canonical surface — there is no
    # MLAG/peer record on `CanonicalIntent` and no codec models one — so
    # before 2026-09-24 BOTH were dropped with no banner at all, which is
    # a silent loss rather than a declared one.
    #
    # `mlag configuration` is the column-0 peer block (domain-id,
    # peer-address, peer-link).  `mlag <N>` is the INDENTED per-bundle
    # marker that makes a Port-Channel dual-homed across the pair; without
    # it the same Port-Channel is local to one switch.  Same shape as the
    # `ip access-group` entry above and as `vlt-port-channel` in the Dell
    # set: the meaning-bearing line is indented, so the column-0 anchors
    # every other entry uses walked straight past it.
    #
    # The bundle id is kept in the label because it is the payload — an
    # operator told "MLAG existed" cannot act; one told WHICH
    # Port-Channels were dual-homed can.
    re.compile(r"^mlag configuration\b", re.MULTILINE),
    re.compile(r"^[^\S\n]+mlag\s+\d+\s*$", re.MULTILINE),
)

# FortiOS shape — `config <path>` headers for sections the FortiGate
# CLI codec does NOT consume.  Excludes `config system interface`,
# `config system zone`, `config system dns`, etc. (parsed) and
# `config system global` (parsed for hostname / timezone).
_FORTIOS_TIER3_HEADERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^config firewall policy\b", re.MULTILINE),
    re.compile(r"^config firewall policy6\b", re.MULTILINE),
    re.compile(r"^config firewall vip\b", re.MULTILINE),
    re.compile(r"^config firewall vip6\b", re.MULTILINE),
    re.compile(r"^config firewall central-snat-map\b", re.MULTILINE),
    re.compile(r"^config firewall (?:address|addrgrp|service)\b", re.MULTILINE),
    re.compile(r"^config firewall shaper\b", re.MULTILINE),
    re.compile(r"^config vpn ipsec\b", re.MULTILINE),
    re.compile(r"^config vpn ssl\b", re.MULTILINE),
    re.compile(r"^config webfilter\b", re.MULTILINE),
    re.compile(r"^config antivirus\b", re.MULTILINE),
    re.compile(r"^config ips\b", re.MULTILINE),
    re.compile(r"^config dlp\b", re.MULTILINE),
    re.compile(r"^config application\b", re.MULTILINE),
    re.compile(r"^config router policy\b", re.MULTILINE),
    re.compile(r"^config router route-map\b", re.MULTILINE),
)

# Junos set-form shape — `set firewall ...`, `set security policies ...`,
# `set policy-options ...`, `set class-of-service ...`.  Excludes
# `set interfaces`, `set vlans`, `set system`, `set routing-instances`,
# `set protocols`, etc. which the Junos parser DOES consume.
_JUNOS_TIER3_HEADERS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^set firewall(?:\s+family\s+\S+)?\s+filter\s+\S+",
        re.MULTILINE,
    ),
    re.compile(
        r"^set security (?:policies|nat|ike|ipsec|zones|address-book|"
        r"flow|screen|alg|utm|application-tracking|forwarding-options)",
        re.MULTILINE,
    ),
    re.compile(r"^set policy-options policy-statement\s+\S+", re.MULTILINE),
    re.compile(r"^set policy-options prefix-list\s+\S+", re.MULTILINE),
    re.compile(r"^set policy-options community\s+\S+", re.MULTILINE),
    re.compile(r"^set class-of-service\b", re.MULTILINE),
)

# RouterOS shape — `/ip firewall ...`, `/queue ...`, `/ip ipsec ...`.
# Excludes `/ip address`, `/ip route`, `/ip dns`, `/interface`, `/snmp`,
# `/system`, `/user` etc. which are parsed.
_ROUTEROS_TIER3_HEADERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/ip firewall (?:filter|nat|mangle|raw|address-list)", re.MULTILINE),
    re.compile(r"^/ipv6 firewall (?:filter|nat|mangle|address-list)", re.MULTILINE),
    re.compile(r"^/queue\b", re.MULTILINE),
    re.compile(r"^/ip ipsec\b", re.MULTILINE),
    re.compile(r"^/routing filter\b", re.MULTILINE),
    re.compile(r"^/routing bgp\b", re.MULTILINE),
    re.compile(r"^/routing ospf\b", re.MULTILINE),
)

# NX-OS shape — Cisco Nexus `show running-config` headers for sections
# the NX-OS codec does NOT consume (routing protocols, ACLs, route-maps,
# QoS class/policy-maps, crypto, AAA, SPAN, multicast).  Excludes
# `interface`, `vlan`, `vrf context`, `ip route`, `hostname`, `feature`
# (discarded / render-derived) which the parser handles.
_NXOS_TIER3_HEADERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^router (?:bgp|ospf|eigrp|isis)\b.*$", re.MULTILINE),
    re.compile(r"^ip access-list\s+\S+", re.MULTILINE),
    re.compile(r"^ipv6 access-list\s+\S+", re.MULTILINE),
    re.compile(r"^mac access-list\s+\S+", re.MULTILINE),
    re.compile(r"^route-map\s+\S+", re.MULTILINE),
    re.compile(r"^class-map\b.*$", re.MULTILINE),
    re.compile(r"^policy-map\b.*$", re.MULTILINE),
    re.compile(r"^crypto\b.*$", re.MULTILINE),
    re.compile(r"^aaa\b.*$", re.MULTILINE),
    re.compile(r"^monitor session\s+\d+", re.MULTILINE),
    re.compile(r"^feature pim\b", re.MULTILINE),
    re.compile(r"^ip pim\b.*$", re.MULTILINE),
)

# IOS-XR shape — Cisco IOS-XR `show running-config` headers for the
# SP-routing / policy / L2VPN sections the codec does NOT consume.
# Excludes `interface`, `router static`, `vrf`, `hostname`, `domain name`
# (parsed or Phase-2) which the parser handles.
_IOSXR_TIER3_HEADERS: tuple[re.Pattern[str], ...] = (
    # Routing protocols
    re.compile(r"^router bgp\s+\d+", re.MULTILINE),
    re.compile(r"^router ospf(?:v3)?\s+\S+", re.MULTILINE),
    re.compile(r"^router isis\s+\S+", re.MULTILINE),
    re.compile(r"^router rip\b", re.MULTILINE),
    re.compile(r"^router pim\b", re.MULTILINE),
    # MPLS
    re.compile(r"^mpls ldp\b", re.MULTILINE),
    re.compile(r"^mpls traffic-eng\b", re.MULTILINE),
    re.compile(r"^mpls oam\b", re.MULTILINE),
    # Policy primitives (XR set-form DSL)
    re.compile(r"^route-policy\s+\S+", re.MULTILINE),
    re.compile(r"^prefix-set\s+\S+", re.MULTILINE),
    re.compile(r"^community-set\s+\S+", re.MULTILINE),
    re.compile(r"^extcommunity-set\s+\S+", re.MULTILINE),
    re.compile(r"^as-path-set\s+\S+", re.MULTILINE),
    re.compile(r"^rd-set\s+\S+", re.MULTILINE),
    # Filters
    re.compile(r"^ipv4 access-list\s+\S+", re.MULTILINE),
    re.compile(r"^ipv6 access-list\s+\S+", re.MULTILINE),
    re.compile(r"^class-map\b.*$", re.MULTILINE),
    re.compile(r"^policy-map\b.*$", re.MULTILINE),
    # L2VPN / EVPN
    re.compile(r"^l2vpn\b", re.MULTILINE),
    re.compile(r"^evpn\b", re.MULTILINE),
    re.compile(r"^bridge group\s+\S+", re.MULTILINE),
    # Misc
    re.compile(r"^multicast-routing\b", re.MULTILINE),
    re.compile(r"^call-home\b", re.MULTILINE),
)

# Aruba AOS-CX shape — `show running-config` headers for the routing /
# ACL / QoS / policy sections the codec does NOT consume.  Excludes
# `interface`, `vlan`, `vrf`, `ip route`, `hostname` (parsed) and the
# deferred Tier-2 `evpn` / `vsx` / `interface vxlan` blocks (which have
# planned canonical surfaces, so flagging them as Tier-3 would mislead).
_AOSCX_TIER3_HEADERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^router (?:bgp|ospf|ospfv3|rip|pim)\b.*$", re.MULTILINE),
    re.compile(r"^access-list (?:ip|ipv6|mac)\s+\S+", re.MULTILINE),
    re.compile(r"^route-map\s+\S+", re.MULTILINE),
    re.compile(r"^class (?:ip|ipv6|mac)\s+\S+", re.MULTILINE),
    re.compile(r"^policy\s+\S+", re.MULTILINE),
)

# VyOS curly-brace shape — block openers for the routing-protocol / NAT /
# firewall / policy sections the codec does NOT consume.  Excludes
# `interfaces`, `protocols static` (parsed), `system` (host-name parsed),
# and the deferred Tier-2 `service` (SSH/NTP/SNMP/DHCP) / `vrf` blocks
# (planned canonical surfaces, so flagging them Tier-3 would mislead).
# Matches the keyword at a line start (with optional indent for the
# blocks nested under `protocols {`); `\b` keeps the label to the bare
# keyword (the trailing ` {` is not captured).
_VYOS_TIER3_HEADERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^[^\S\n]*nat\b", re.MULTILINE),
    re.compile(r"^[^\S\n]*nat66\b", re.MULTILINE),
    re.compile(r"^[^\S\n]*firewall\b", re.MULTILINE),
    re.compile(r"^[^\S\n]*policy\b", re.MULTILINE),
    re.compile(r"^[^\S\n]*vpn\b", re.MULTILINE),
    re.compile(r"^[^\S\n]+bgp\b", re.MULTILINE),
    re.compile(r"^[^\S\n]+ospf(?:v3)?\b", re.MULTILINE),
    re.compile(r"^[^\S\n]+rip\b", re.MULTILINE),
    re.compile(r"^[^\S\n]+isis\b", re.MULTILINE),
)

# OPNsense XML element shape (heuristic — substring presence check on
# top-level elements that the parser doesn't currently extract).  The
# OPNsense codec consumes ``<vlans>``, ``<interfaces>``, ``<dhcpd>``,
# ``<system>``, ``<staticroutes>``, etc.; everything below is dropped.
_OPNSENSE_TIER3_HEADERS: tuple[str, ...] = (
    "<filter>",
    "<nat>",
    "<ipsec>",
    "<openvpn>",
    "<wireguard>",
    "<shaper>",
    "<load_balancer>",
    "<captiveportal>",
)


# Dell SmartFabric OS10 shape — `show running-configuration` headers for
# the sections the OS10 codec does NOT consume.  Excludes `interface`,
# `hostname`, `ip vrf`, `ip route` / `management route` (parsed), and the
# deferred VXLAN blocks (`nve` / `virtual-network`), which have a planned
# canonical surface — flagging those as Tier-3 would mislead, and their
# drop is already declared in the capability matrix (the same line the
# AOS-CX header set draws).
#
# `interface breakout` is matched WITHOUT its port/profile tail on
# purpose: a 32-port switch carries 32 distinct breakout lines, and
# `_detect_regex` dedupes by label, so capturing the tail would flood the
# operator's dropped-sections banner with 32 near-identical entries
# instead of one.
_DELLOS10_TIER3_HEADERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^router (?:bgp|ospf|ospfv3|isis|rip)\b.*$", re.MULTILINE),
    re.compile(r"^ip access-list\s+\S+", re.MULTILINE),
    re.compile(r"^ipv6 access-list\s+\S+", re.MULTILINE),
    re.compile(r"^mac access-list\s+\S+", re.MULTILINE),
    re.compile(r"^route-map\s+\S+", re.MULTILINE),
    # DCB / RoCE QoS — heavy in real Azure Local switch configs.
    re.compile(r"^class-map\b.*$", re.MULTILINE),
    re.compile(r"^policy-map\b.*$", re.MULTILINE),
    re.compile(r"^trust dot1p-map\s+\S+", re.MULTILINE),
    re.compile(r"^qos-map\s+\S+", re.MULTILINE),
    re.compile(r"^system qos\b", re.MULTILINE),
    # VLT (Dell's MLAG) — no canonical surface; present in 10 of 12
    # OS10 captures, so this banner fires on most real configs.
    re.compile(r"^vlt-domain\s+\d+", re.MULTILINE),
    # The SECOND half of VLT, and the one that silently changes meaning.
    # `vlt-port-channel <N>` is what makes a bundle dual-homed ACROSS the
    # peer pair; without it the same `port-channel <N>` is local to one
    # chassis.  Nothing models it, so the bundle renders as an ordinary
    # single-chassis LAG — a semantic downgrade that looks like a clean
    # translation.  The `vlt-domain` pattern above does NOT cover it: this
    # line is INDENTED inside an `interface port-channel` stanza, and every
    # other entry here is anchored at column 0.  Measured 2026-09-24: 6 of
    # the 9 committed captures carry it and none was detected.
    #
    # Unlike `interface breakout` the tail is KEPT.  The bundle id is the
    # payload — an operator told "VLT existed" still cannot act; one told
    # WHICH port-channels were dual-homed can.  Cardinality is bounded by
    # the number of dual-homed bundles (1 per capture on the committed
    # corpus), not by port count, so this does not flood the banner.
    re.compile(r"^[^\S\n]*vlt-port-channel\s+\d+", re.MULTILINE),
    re.compile(r"^interface breakout\b", re.MULTILINE),
    # `system-user linuxadmin` is the switch's underlying LINUX shell
    # account, not a NOS login, so the codec deliberately does not model it
    # as a local user (re-emitting it as `username` would convert a shell
    # account into a NOS operator).  Matched WITHOUT its tail so the
    # secret-bearing `password <hash>` never reaches the banner.
    re.compile(r"^system-user\b", re.MULTILINE),
    # Chassis-wide VRRP settings (`vrrp version 2|3`, `vrrp delay reload
    # <s>`).  The per-group canonical record is per-interface, so a
    # SYSTEM-wide setting has no canonical home and is permanently
    # dropped — surfaced here rather than silently discarded.  Matched
    # without the value so the label stays constant.
    re.compile(r"^vrrp\s+(?:version|delay)\b", re.MULTILINE),
    re.compile(r"^telemetry\b", re.MULTILINE),
    re.compile(r"^support-assist\b", re.MULTILINE),
    re.compile(r"^aaa\b.*$", re.MULTILINE),
)


def detect_tier3_sections_iosxe_cli(raw: str) -> list[str]:
    """Detect Tier-3 stanza headers in IOS-XE / Arista CLI text.

    Args:
        raw: Source config as a single newline-joined string.

    Returns:
        Ordered list of unique stanza headers found.  Empty list when
        the input contains no Tier-3 stanzas.
    """
    return _detect_regex(raw, _IOSXE_TIER3_HEADERS)


def detect_tier3_sections_fortios(raw: str) -> list[str]:
    """Detect Tier-3 stanza headers in FortiOS CLI text."""
    return _detect_regex(raw, _FORTIOS_TIER3_HEADERS)


def detect_tier3_sections_junos(raw: str) -> list[str]:
    """Detect Tier-3 stanza headers in Junos set-form text.

    Every pattern begins ``set ``, so hierarchical text has to be
    handed over as the set-form the parser read it as
    (``juniper_junos.parse.read_intent`` returns that text): given the
    hierarchical text itself this found nothing, and a firewall's
    filters, NAT and policies were dropped with no row to say so.
    """
    return _detect_regex(raw, _JUNOS_TIER3_HEADERS)


def detect_tier3_sections_nxos(raw: str) -> list[str]:
    """Detect Tier-3 stanza headers in Cisco NX-OS CLI text."""
    return _detect_regex(raw, _NXOS_TIER3_HEADERS)


def detect_tier3_sections_iosxr(raw: str) -> list[str]:
    """Detect Tier-3 stanza headers in Cisco IOS-XR CLI text."""
    return _detect_regex(raw, _IOSXR_TIER3_HEADERS)


def detect_tier3_sections_aoscx(raw: str) -> list[str]:
    """Detect Tier-3 stanza headers in Aruba AOS-CX CLI text."""
    return _detect_regex(raw, _AOSCX_TIER3_HEADERS)


def detect_tier3_sections_dellos10(raw: str) -> list[str]:
    """Detect Tier-3 stanza headers in Dell SmartFabric OS10 CLI text."""
    return _detect_regex(raw, _DELLOS10_TIER3_HEADERS)


def detect_tier3_sections_vyos(raw: str) -> list[str]:
    """Detect Tier-3 block keywords in VyOS curly-brace config text."""
    return _detect_regex(raw, _VYOS_TIER3_HEADERS)


def detect_tier3_sections_routeros(raw: str) -> list[str]:
    """Detect Tier-3 stanza headers in RouterOS ``.rsc`` text."""
    return _detect_regex(raw, _ROUTEROS_TIER3_HEADERS)


def detect_tier3_sections_opnsense(raw: str) -> list[str]:
    """Detect Tier-3 elements in OPNsense XML — heuristic substring match."""
    return [hdr for hdr in _OPNSENSE_TIER3_HEADERS if hdr in raw]


def detect_tier3_sections_iosxe_xml(raw: str) -> list[str]:
    """Detect Tier-3 elements in Cisco IOS-XE NETCONF / OpenConfig XML.

    Currently a no-op — NETCONF input typically contains only the
    OpenConfig ``<interfaces>`` subtree the codec is wired to consume,
    so there's nothing Tier-3 to surface.  Retained for parity so every
    codec's parse() goes through the same one-line hook; if future
    NETCONF inputs include ``<acl>`` / ``<nat>`` subtrees a substring
    list can be added here without changing the call site.

    Args:
        raw: Source XML as a single string.

    Returns:
        Empty list (no-op detector).
    """
    del raw  # unused; reserved for future extension
    return []


# ---------------------------------------------------------------------------
# Statements a parser read and left out
# ---------------------------------------------------------------------------

#: Kind of statement to what its row begins with and why it is there.
#: Such a row is in the list because the statement is not in the
#: output; it is not a section the parser has no model for, and it is
#: not something to apply by hand.  (A ``preconfigure`` stanza is,
#: where the target is to hold configuration for the same hardware,
#: and there alone: the migrate page gives that kind its own words.)
_LEFT_OUT: dict[str, tuple[str, str]] = {
    "inactive": ("inactive: ", "deactivated in the source; not translated"),
    "delete": ("delete: ", "marked for deletion in a load file; not translated"),
    "preconfigure": (
        "preconfigure: ",
        "held for an interface the source does not have; not translated",
    ),
    "untagged": (
        "untagged: ",
        "states no 802.1Q tag, so the source passes no traffic on it; not translated",
    ),
}

#: A word of a path that names a secret.  What follows it is the
#: secret (a community string, a hash, a key) or leads to it, and is
#: not shown.
_NAMES_A_SECRET = ("community", "password", "secret", "key", "psk", "authentication")


def shown_words(path: Sequence[str]) -> list[str]:
    """The words of a statement's path that may be shown to someone:
    all of them, or those up to and including the first that names
    a secret and has something after it (:data:`_NAMES_A_SECRET`).
    A statement is keyed by its secret often enough (``snmp
    community <string>``) or ends in one (``authentication
    encrypted-password <hash>``)."""
    shown = list(path)
    for at, word in enumerate(shown[:-1]):
        lowered = word.lower()
        if any(name in lowered for name in _NAMES_A_SECRET):
            del shown[at + 1:]
            break
    return shown


def left_out_row(kind: str, path: Sequence[str]) -> str:
    """The row for a statement a parser read and left out.

    The row names the statement and never a secret: a path is the
    words of the statement, and a statement is keyed by its secret
    often enough (``snmp community <string>``) or ends in one
    (``authentication encrypted-password <hash>``).  The words are
    cut after the first that names a secret and has something after
    it (:func:`shown_words`), and the cut is marked ``...``.

    Args:
        kind: ``"inactive"`` (deactivated in the source),
            ``"delete"`` (under a load file's ``delete:``) or
            ``"preconfigure"`` (an IOS XR ``interface preconfigure``
            stanza: configuration for an interface that is not there)
            or ``"untagged"`` (an IOS XR or EOS sub-interface that
            states no tag, which passes no traffic there).
        path: The words of the statement's path, outermost first.

    Returns:
        ``"<kind>: <path> (<why it was left out>)"``.
    """
    shown = shown_words(path)
    words = [f'"{word}"' if not word or any(ch.isspace() for ch in word) else word for word in shown]
    if len(shown) < len(path):
        words.append("...")
    prefix, why = _LEFT_OUT[kind]
    return f"{prefix}{' '.join(words)} ({why})"


#: The most rows given for the statements a parser left out.  The
#: list is in every answer, and a row is longer than the statement
#: it names: eighty thousand deactivated leaves made an answer of
#: thirty-six megabytes to a request of one and a half.
LEFT_OUT_ROWS_SHOWN = 200


def left_out_rows(
    statements: Iterable[tuple[str, Sequence[str]]], rest: str = "inactive",
) -> list[str]:
    """The rows for the statements a parser read and left out.

    Statements whose rows read alike share one, which says how
    many it stands for: two deactivated NTP servers are both
    ``inactive: system ntp server``, the value of a leaf being
    left out of its row.  Past :data:`LEFT_OUT_ROWS_SHOWN` rows
    one last row counts the statements that are not listed.

    Args:
        statements: ``(kind, path)`` for each, in the order the
            rows are to have (see :func:`left_out_row`).
        rest: The kind whose prefix the last row begins with when
            it counts statements that are not listed.

    Returns:
        The rows, each one :func:`is_left_out_row` knows.
    """
    counts: dict[str, int] = {}
    for kind, path in statements:
        row = left_out_row(kind, path)
        counts[row] = counts.get(row, 0) + 1
    rows = [
        row if count == 1 else f"{row[:-1]}; {count} statements)"
        for row, count in counts.items()
    ]
    if len(rows) > LEFT_OUT_ROWS_SHOWN:
        unlisted = sum(list(counts.values())[LEFT_OUT_ROWS_SHOWN:])
        rows[LEFT_OUT_ROWS_SHOWN:] = [
            f"{_LEFT_OUT[rest][0]}... ({unlisted} more statements left out; not listed)"
        ]
    return rows


def is_left_out_row(label: str) -> bool:
    """Whether *label* is a row made by :func:`left_out_row`.

    A reader of ``dropped_tier3_sections`` that takes a row for a sign
    that the parser recognised something has to ask this first: a
    deactivated statement is named whether or not any handler would
    have read a line of it, and so is a stanza held for an interface
    that is not there.
    """
    return label.startswith(tuple(prefix for prefix, _why in _LEFT_OUT.values()))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_regex(
    raw: str, patterns: tuple[re.Pattern[str], ...]
) -> list[str]:
    """Run every pattern; dedupe matches preserving first-occurrence order.

    Args:
        raw: Source config text.
        patterns: Ordered tuple of compiled regexes; each match's
            ``group(0)`` is taken as the section label after stripping
            trailing whitespace.

    Returns:
        Ordered list of unique section labels.
    """
    seen: list[str] = []
    # Looked for in a set, kept in the list: where a pattern takes
    # the whole line, every distinct `class-map` or `policy-map` line
    # is a label, and looking through the list for each match cost
    # the square of their number.
    known: set[str] = set()
    for pattern in patterns:
        for match in ticked(pattern.finditer(raw)):
            label = match.group(0).strip()
            if label and label not in known:
                known.add(label)
                seen.append(label)
    return seen
