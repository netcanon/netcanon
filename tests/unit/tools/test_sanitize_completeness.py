"""Sanitizer completeness PARTITION guard (sanitizer-bypass CLASS — blind-audit
meta-finding, ``docs/reviews/2026-06-24-fail-surfaced-defaults``).

THE CLASS (not an instance): ``sanitize_intent`` redacts a *subset* of fields,
so a new IP/host/secret-bearing field leaks verbatim until a human names it
(IPv4 -> IPv6 -> RD/RT -> anycast-VGA #174 — each a fresh blind-audit round).
The existing ``TestSecretRedactionCoverage`` reverse guard triggers on a field's
NAME (``_SECRET_NAME_RE``), so a deceptively-named sensitive field (e.g. a future
``CanonicalBGPNeighbor.peer: str`` holding a neighbour IP) is never even a
candidate — the blind spot just relocates to the name list (review finding MF-2).

THE DURABLE FIX (fail-surfaced default): partition EVERY ``str`` / ``list[str]``
leaf reachable from ``CanonicalIntent`` into exactly one of three reason-coded
sets — redacted / sensitive-gap / non-sensitive. The guard triggers on a leaf's
EXISTENCE, not its name: a NEW str leaf in none of the three turns CI red,
forcing the author to make the binary "is this sensitive?" decision before it
can merge. This is the existence-trigger a typed marker would give, WITHOUT the
marker (no per-field ``Annotated[...]`` discipline that fails silently when
forgotten) — the registries double as documentation of sanitizer coverage.

ZERO runtime change: the existing redaction behaviour + its forward tests
(``TestSecretRedactionCoverage``, the R-16 PII block, the overlay-ID block in
``test_sanitize.py``) are untouched; this is a coverage test. A comprehensive
forward sentinel over the whole IP set (crafting per-field public sentinels for
CIDR / multicast / RD-RT / MAC) is a deliberate follow-up — the existing
per-category forward tests already pin actual redaction for the known fields.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from tests.support.canonical_reflection import str_leaves

pytestmark = pytest.mark.unit


_GAP_CODES = frozenset({"REDACTION_NOT_WIRED", "TIER3_OPAQUE"})
_NON_SENSITIVE_CODES = frozenset(
    {"ENUM", "IDENTIFIER", "FREE_TEXT", "METADATA", "IFACE_REF"}
)

#: str / list[str] leaves the sanitiser HANDLES today (redacted, or — for
#: multicast / RD-RT / hostname-form — deliberately format-preserved). Actual
#: redaction behaviour is verified by the existing forward tests in
#: test_sanitize.py; this set documents coverage and anchors the partition.
_SENSITIVE_REDACTED = frozenset({
    ("CanonicalDHCPPool", "dns_servers"),
    ("CanonicalDHCPPool", "domain_name"),
    ("CanonicalDHCPPool", "end_ip"),
    ("CanonicalDHCPPool", "gateway"),
    ("CanonicalDHCPPool", "network"),
    ("CanonicalDHCPPool", "start_ip"),
    ("CanonicalEvpnType5Route", "prefix"),
    ("CanonicalEvpnType5Route", "rt_exports"),
    ("CanonicalEvpnType5Route", "rt_imports"),
    ("CanonicalIPv4Address", "ip"),
    ("CanonicalIPv4Address", "virtual_gateway_address"),
    ("CanonicalIPv4Address", "virtual_gateway_mac"),
    ("CanonicalIPv6Address", "ip"),
    ("CanonicalIPv6Address", "virtual_gateway_address"),
    ("CanonicalIPv6Address", "virtual_gateway_mac"),
    ("CanonicalIntent", "dns_servers"),
    ("CanonicalIntent", "domain"),
    ("CanonicalIntent", "ntp_servers"),
    ("CanonicalIntent", "syslog_servers"),
    ("CanonicalRADIUSServer", "host"),
    ("CanonicalRADIUSServer", "key"),
    ("CanonicalRoutingInstance", "route_distinguisher"),
    ("CanonicalRoutingInstance", "rt_exports"),
    ("CanonicalRoutingInstance", "rt_imports"),
    ("CanonicalSNMP", "community"),
    ("CanonicalSNMP", "contact"),
    ("CanonicalSNMP", "location"),
    ("CanonicalSNMP", "trap_hosts"),
    ("CanonicalSNMPv3User", "auth_passphrase"),
    ("CanonicalSNMPv3User", "engine_id"),
    ("CanonicalSNMPv3User", "priv_passphrase"),
    ("CanonicalStaticRoute", "destination"),
    ("CanonicalStaticRoute", "gateway"),
    ("CanonicalVxlan", "flood_list"),
    ("CanonicalVxlan", "mcast_group"),
    ("CanonicalLocalUser", "hashed_password"),
    ("CanonicalIntent", "anycast_gateway_mac"),
    ("CanonicalVRRPGroup", "authentication"),
    ("CanonicalVRRPGroup", "virtual_ips"),
    ("CanonicalVRRPGroup", "virtual_ipv6s"),
    ("CanonicalVRRPGroup", "virtual_mac"),
})

#: Sensitive str leaves the sanitiser does NOT cover yet — surfaced + tracked +
#: deferred. (The four virtual-MAC leaves graduated to _SENSITIVE_REDACTED once
#: the redact_mac primitive was wired — blind-audit f92e97a T0-3.) TIER3_OPAQUE:
#: verbatim vendor text the STRUCTURED sanitiser can't reach (sanitize_text
#: re-parses + sanitises the text path, but the intent-level walk treats these
#: as a blob).
_SENSITIVE_GAP: dict[tuple[str, str], tuple[str, str]] = {
    ("CanonicalIntent", "raw_sections"): ("TIER3_OPAQUE", "Tier-3 verbatim text; structural walk can't reach it"),
    ("CanonicalIntent", "group_content"): ("TIER3_OPAQUE", "Junos group bodies (verbatim); not structurally sanitised"),
    ("CanonicalIntent", "dropped_tier3_sections"): ("TIER3_OPAQUE", "dropped-section text; not structurally sanitised"),
}

#: str leaves that carry no operator secret / public IP — names, enums,
#: interface references, operator free text, tool provenance. Each reason is one
#: a reviewer can challenge (a real IP/secret leaf has no honest code here).
_NON_SENSITIVE: dict[tuple[str, str], tuple[str, str]] = {
    ("CanonicalDHCPPool", "interface"): ("IFACE_REF", "bind interface name"),
    ("CanonicalEvpnType5Route", "vrf"): ("IDENTIFIER", "VRF name"),
    ("CanonicalIPv6Address", "scope"): ("ENUM", "global | link-local"),
    ("CanonicalIntent", "apply_groups"): ("METADATA", "Junos apply-group names"),
    ("CanonicalIntent", "hostname"): ("IDENTIFIER", "device hostname; passed through by design"),
    ("CanonicalIntent", "source_format"): ("METADATA", "source input_format hint"),
    ("CanonicalIntent", "source_vendor"): ("METADATA", "producing codec"),
    ("CanonicalIntent", "source_version"): ("METADATA", "source OS-version hint"),
    ("CanonicalIntent", "timezone"): ("IDENTIFIER", "tz name (e.g. UTC)"),
    ("CanonicalInterface", "default_name"): ("IDENTIFIER", "factory interface name"),
    ("CanonicalInterface", "description"): ("FREE_TEXT", "interface description"),
    ("CanonicalInterface", "dhcp_client_v6"): ("ENUM", "dhcp6 mode token"),
    ("CanonicalInterface", "interface_type"): ("ENUM", "ianaift interface-type token"),
    ("CanonicalInterface", "kind"): ("ENUM", "transform kind hint"),
    ("CanonicalInterface", "lag_member_of"): ("IFACE_REF", "parent LAG name"),
    ("CanonicalInterface", "name"): ("IDENTIFIER", "interface name"),
    ("CanonicalInterface", "switchport_mode"): ("ENUM", "access | trunk"),
    ("CanonicalInterface", "tunnel_type"): ("ENUM", "tunnel encapsulation token"),
    ("CanonicalInterface", "vrf"): ("IDENTIFIER", "VRF name"),
    ("CanonicalLAG", "members"): ("IFACE_REF", "member interface names"),
    ("CanonicalLAG", "mode"): ("ENUM", "active | passive | on"),
    ("CanonicalLAG", "name"): ("IDENTIFIER", "LAG name"),
    ("CanonicalLocalUser", "name"): ("IDENTIFIER", "account name; passed through (not a secret)"),
    ("CanonicalLocalUser", "role"): ("ENUM", "role / privilege keyword"),
    ("CanonicalRoutingInstance", "description"): ("FREE_TEXT", "VRF description"),
    ("CanonicalRoutingInstance", "instance_type"): ("ENUM", "vrf | mac-vrf"),
    ("CanonicalRoutingInstance", "name"): ("IDENTIFIER", "VRF name"),
    ("CanonicalSNMPv3User", "auth_protocol"): ("ENUM", "md5 | sha | ..."),
    ("CanonicalSNMPv3User", "group"): ("IDENTIFIER", "VACM group name"),
    ("CanonicalSNMPv3User", "name"): ("IDENTIFIER", "SNMPv3 user name; passed through"),
    ("CanonicalSNMPv3User", "priv_protocol"): ("ENUM", "des | aes | ..."),
    ("CanonicalStaticRoute", "description"): ("FREE_TEXT", "route description"),
    ("CanonicalStaticRoute", "interface"): ("IFACE_REF", "egress interface name"),
    ("CanonicalStaticRoute", "vrf"): ("IDENTIFIER", "VRF name"),
    ("CanonicalVlan", "description"): ("FREE_TEXT", "VLAN description"),
    ("CanonicalVlan", "name"): ("IDENTIFIER", "VLAN name"),
    ("CanonicalVlan", "tagged_ports"): ("IFACE_REF", "tagged member interface names"),
    ("CanonicalVlan", "untagged_ports"): ("IFACE_REF", "untagged member interface names"),
    ("CanonicalVxlan", "source_interface"): ("IFACE_REF", "VTEP source interface name"),
    ("CanonicalVRRPGroup", "description"): ("FREE_TEXT", "group description"),
    ("CanonicalVRRPGroup", "mode"): ("ENUM", "vrrp | hsrp | carp"),
    ("CanonicalVRRPGroup", "track_interfaces"): ("IFACE_REF", "tracked interface names"),
}


def _classified() -> set[tuple[str, str]]:
    return _SENSITIVE_REDACTED | set(_SENSITIVE_GAP) | set(_NON_SENSITIVE)


class TestSanitizerFieldPartition:
    """Every str / list[str] leaf is consciously classified — the class-kill."""

    def test_every_str_leaf_is_classified(self):
        """Partition completeness: every str/list[str] leaf reachable from
        CanonicalIntent is in exactly one of redacted / sensitive-gap /
        non-sensitive. A NEW str leaf (even a deceptively-named IP) in none of
        the three turns this RED — the existence-trigger a name-based guard lacks
        (review finding MF-2)."""
        unclassified = sorted(str_leaves(CanonicalIntent) - _classified())
        assert not unclassified, (
            "str-bearing canonical leaf/leaves are unclassified — the sanitiser "
            "default for a new field is leak-verbatim (the sanitizer-bypass class). "
            "Classify each: redact it in sanitize_intent + add to _SENSITIVE_REDACTED; "
            "OR add to _SENSITIVE_GAP (sensitive, redaction deferred) with a code; OR "
            f"add to _NON_SENSITIVE (no secret/IP) with a code: {unclassified}"
        )

    def test_buckets_are_disjoint(self):
        red, gap, non = _SENSITIVE_REDACTED, set(_SENSITIVE_GAP), set(_NON_SENSITIVE)
        assert not (red & gap), f"in both redacted and gap: {sorted(red & gap)}"
        assert not (red & non), f"in both redacted and non-sensitive: {sorted(red & non)}"
        assert not (gap & non), f"in both gap and non-sensitive: {sorted(gap & non)}"

    def test_no_stale_classifications(self):
        """Every classified key is still a real str leaf — a removed/renamed
        field must drop out, else the classification rots into a lie."""
        stale = sorted(_classified() - str_leaves(CanonicalIntent))
        assert not stale, f"classification(s) reference non-existent str leaves: {stale}"

    def test_reason_codes_are_structured(self):
        bad_gap = sorted(
            f"{c}.{f} -> {code!r}"
            for (c, f), (code, _n) in _SENSITIVE_GAP.items()
            if code not in _GAP_CODES
        )
        assert not bad_gap, f"_SENSITIVE_GAP entries with unknown code: {bad_gap}"
        bad_non = sorted(
            f"{c}.{f} -> {code!r}"
            for (c, f), (code, _n) in _NON_SENSITIVE.items()
            if code not in _NON_SENSITIVE_CODES
        )
        assert not bad_non, f"_NON_SENSITIVE entries with unknown code: {bad_non}"

    def test_guard_catches_a_synthetic_deceptively_named_ip_field(self):
        """Prove the class-kill: a deceptively-named NEW IP field (the S4 case a
        name-regex guard misses) is flagged because the partition triggers on
        existence, not name. A ``CanonicalBGPNeighbor.peer`` leaf is in none of
        the three sets -> unclassified -> RED."""
        synthetic = ("CanonicalBGPNeighbor", "peer")  # a neighbour IP, non-IP-ish name
        leaves = str_leaves(CanonicalIntent) | {synthetic}
        assert synthetic in (leaves - _classified()), (
            "the partition would NOT flag a deceptively-named new IP field — the "
            "class-kill is broken (it must trigger on existence, not name)"
        )
