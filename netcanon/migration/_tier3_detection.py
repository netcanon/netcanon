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
was dropped.

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

Each returns a list of section labels like::

    ["ip access-list extended OUTSIDE_IN",
     "ip nat inside source list 10",
     "crypto isakmp policy 10"]

Detection is best-effort heuristic on stanza headers — not a parse.
False positives are preferred to false negatives (the goal is
"operator sees something" not "operator sees an exact list").  The
output is OUTPUT-ONLY: it never feeds the renderer or any transform.
This is a notification surface, not a translator.
"""

from __future__ import annotations

import re

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
    re.compile(r"^ip nat\s+(?:inside|outside|pool)\b.*$", re.MULTILINE),
    re.compile(r"^class-map\b.*$", re.MULTILINE),
    re.compile(r"^policy-map\b.*$", re.MULTILINE),
    re.compile(r"^route-map\s+\S+", re.MULTILINE),
    re.compile(r"^crypto (?:isakmp|ipsec|map|pki)\b.*$", re.MULTILINE),
    re.compile(r"^zone-pair security\b.*$", re.MULTILINE),
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
    """Detect Tier-3 stanza headers in Junos set-form text."""
    return _detect_regex(raw, _JUNOS_TIER3_HEADERS)


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
    for pattern in patterns:
        for match in pattern.finditer(raw):
            label = match.group(0).strip()
            if label and label not in seen:
                seen.append(label)
    return seen
