"""Sanitization tooling — produce a redacted copy of a network config.

Vendor-aware via the canonical-intermediate-model walk.  Operates by:

1. ``parse(raw, source_codec)`` → :class:`CanonicalIntent`
2. :func:`sanitize_intent` walks the canonical tree and applies
   field-typed redactions.  Counter-per-session stable: same input
   value always maps to the same redaction across the whole config
   (so cross-references survive — a hostname referenced in 5 places
   gets the same redacted value all 5 times).
3. ``render(sanitized_intent, source_codec)`` → text

The output is in the SAME vendor's format as the input, with PII
redacted at AST level rather than via per-vendor regex.

Field-typed rules (counter-per-session):

* ``CanonicalIntent.hostname`` → ``device-N``
* ``CanonicalIntent.domain`` → ``example-N.test``
* Public IPv4 anywhere → RFC 5737 docs ranges (192.0.2.x /
  198.51.100.x / 203.0.113.x); private IPs (RFC 1918, ULA, link-local,
  loopback, multicast, CGNAT 100.64/10) preserved
* ``CanonicalLocalUser.name`` → ``localuserN`` (Phase-3 R6.1 addition —
  the username is operator-identifying when chosen by the operator,
  e.g. ``alice``, ``john.smith``, or ``user12``)
* ``CanonicalLocalUser.hashed_password`` → format-preserving fake hash
  (e.g. ``$9$...`` Junos form preserved; FortiGate ``ENC ...`` form
  preserved; Cisco type-7 hex preserved; Linux ``$5$`` / ``$6$`` /
  bcrypt ``$2y$`` shapes preserved)
* ``CanonicalSNMP.community`` → ``public_redacted_N``
* ``CanonicalSNMPv3User.name`` → ``snmpv3userN`` (Phase-3 R6.1 — same
  rationale as local-user-name above)
* ``CanonicalSNMPv3User.auth_passphrase`` → ``REDACTED-AUTH-N``
* ``CanonicalSNMPv3User.priv_passphrase`` → ``REDACTED-PRIV-N``
* ``CanonicalRADIUSServer.key`` → ``REDACTED-RADIUS-N``
* ``CanonicalInterface.description`` → ``description redacted``
* ``CanonicalDHCPPool.dns_servers`` (public entries) → docs range
* ``CanonicalStaticRoute.gateway`` (public) → docs range
* ``CanonicalIntent.dropped_tier3_sections`` → stripped entirely
  (Tier-3 carry-through may contain anything; never share)

Limitations:

* The canonical model is the AST; whatever the parser doesn't model
  is not visible to this sanitizer.  Banner text, comments, and raw
  Tier-3 stanzas in the source bytes are not field-typed redacted —
  Tier-3 content is dropped on parse, banners are typically
  parse-and-ignore.
* Round-trip is sub-lossless: parse drops Tier-3 content, and render
  emits only what the codec models.  Operators sharing a sanitized
  config get the supported subset, not a byte-identical-shape
  original.  This is acceptable for bug reports — operators usually
  don't want to share Tier-3 content (firewall, NAT, VPN) anyway.

CLI invocation::

    netcanon sanitize -i my-config.txt -o sanitised.txt \\
        --source-vendor cisco_iosxe_cli

HTTP API invocation (Docker / running-server users)::

    curl -X POST http://localhost:8000/api/v1/sanitize \\
      -F "source_vendor=cisco_iosxe_cli" \\
      -F "config=@my-config.txt" \\
      -o sanitised.txt
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any

from ..migration.canonical.intent import CanonicalIntent
from ..migration.codecs.registry import get_codec


# ---------------------------------------------------------------------------
# Public API — dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Substitution:
    """A single sanitization replacement.

    Captures both old and new values so ``--dry-run`` can show the
    operator exactly what's about to change before they commit.
    """
    category: str
    field: str
    original: str
    redacted: str


@dataclass
class SanitizationResult:
    """Output of :func:`sanitize_text`."""
    sanitized_text: str
    substitutions: list[Substitution] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API — functions
# ---------------------------------------------------------------------------


def sanitize_text(
    raw: str,
    source_codec_name: str,
    *,
    dry_run: bool = False,
) -> SanitizationResult:
    """Sanitize a raw network config.

    Pipeline: ``parse(raw, source_codec)`` → :func:`sanitize_intent`
    → ``render(sanitized_intent, source_codec)``.  The output is in
    the same vendor's format as the input, with PII redacted at the
    canonical-model level.

    Args:
        raw: Raw config text from the source vendor.
        source_codec_name: Name of the codec to use for parse +
            render (e.g. ``"cisco_iosxe_cli"``).  Must be a key in
            :func:`netcanon.migration.codecs.registry.list_codecs`.
        dry_run: If ``True``, returns the substitution audit log
            without rendering output (``sanitized_text`` will be
            empty string).  Useful for the operator to preview
            what's about to change.

    Returns:
        :class:`SanitizationResult` with sanitized text + the full
        list of :class:`Substitution` entries.

    Raises:
        ValueError: ``source_codec_name`` not in the registry.
        netcanon.migration.codecs.base.ParseError: ``raw`` doesn't
            parse as the declared source vendor.
    """
    try:
        codec = get_codec(source_codec_name)
    except LookupError as e:
        # Wrap for consistent caller contract — operators expect
        # "you passed a bad value" to be ValueError.
        raise ValueError(
            f"Unknown source codec: {source_codec_name!r}. "
            f"See netcanon.migration.codecs.registry.list_codecs()."
        ) from e
    intent = codec.parse(raw)
    sanitized_intent, substitutions = sanitize_intent(intent)

    if dry_run:
        return SanitizationResult(
            sanitized_text="",
            substitutions=substitutions,
        )

    sanitized_text = codec.render(sanitized_intent)
    return SanitizationResult(
        sanitized_text=sanitized_text,
        substitutions=substitutions,
    )


def sanitize_intent(
    intent: CanonicalIntent,
) -> tuple[CanonicalIntent, list[Substitution]]:
    """Apply field-typed redactions to a :class:`CanonicalIntent`.

    Pure function — the input ``intent`` is not mutated; a deep-copy
    is returned with sanitized fields.

    Args:
        intent: The parsed canonical intent to sanitize.

    Returns:
        Tuple of ``(sanitized_intent, substitutions)``.  The
        ``substitutions`` list is the audit log: every replacement
        with original + redacted values for ``--dry-run`` review.
    """
    sanitized = intent.model_copy(deep=True)
    table = _SubstitutionTable()
    subs: list[Substitution] = []

    # ---- top-level scalars ----
    if sanitized.hostname:
        new_value = table.redact_hostname(sanitized.hostname)
        subs.append(Substitution(
            category="hostname",
            field="hostname",
            original=sanitized.hostname,
            redacted=new_value,
        ))
        sanitized.hostname = new_value

    if sanitized.domain:
        new_value = table.redact_domain(sanitized.domain)
        subs.append(Substitution(
            category="domain",
            field="domain",
            original=sanitized.domain,
            redacted=new_value,
        ))
        sanitized.domain = new_value

    # ---- IP-list scalars (DNS / NTP / syslog) ----
    sanitized.dns_servers = _redact_ip_list(
        sanitized.dns_servers, "dns_servers", "ipv4-public", table, subs)
    sanitized.ntp_servers = _redact_ip_list(
        sanitized.ntp_servers, "ntp_servers", "ipv4-public", table, subs)
    sanitized.syslog_servers = _redact_ip_list(
        sanitized.syslog_servers, "syslog_servers", "ipv4-public", table, subs)

    # ---- interfaces ----
    for i, iface in enumerate(sanitized.interfaces):
        if iface.description:
            redacted_desc = "description redacted"
            subs.append(Substitution(
                category="interface-description",
                field=f"interfaces[{i}].description",
                original=iface.description,
                redacted=redacted_desc,
            ))
            iface.description = redacted_desc

        for j, addr in enumerate(iface.ipv4_addresses):
            new_ip = table.redact_ipv4(addr.ip)
            if new_ip != addr.ip:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"interfaces[{i}].ipv4_addresses[{j}].ip",
                    original=addr.ip,
                    redacted=new_ip,
                ))
                addr.ip = new_ip

    # ---- local users (usernames + hashed passwords) ----
    # Phase-3 R6.1: redact the username too.  Operator-chosen
    # usernames (`alice`, `john.smith`, or the Windows-login-mirror
    # case `user12`) are operator-PII when shared in public bug
    # reports — leaking them enables operator-correlation attacks
    # ("the operator at this org uses the same login on their laptop
    # and their network gear; let me cross-reference with public
    # social profiles").  The hashed-password redaction below stays
    # unchanged.
    for i, user in enumerate(sanitized.local_users):
        if user.name:
            new_name = table.redact_local_user_name(user.name)
            subs.append(Substitution(
                category="local-user-name",
                field=f"local_users[{i}].name",
                original=user.name,
                redacted=new_name,
            ))
            user.name = new_name
        if user.hashed_password:
            new_hash = table.redact_hash(user.hashed_password)
            subs.append(Substitution(
                category="local-user-hash",
                field=f"local_users[{i}].hashed_password",
                original=user.hashed_password,
                redacted=new_hash,
            ))
            user.hashed_password = new_hash

    # ---- SNMP (community + v3 passphrases) ----
    if sanitized.snmp:
        if sanitized.snmp.community:
            new_value = table.redact_community(sanitized.snmp.community)
            subs.append(Substitution(
                category="snmp-community",
                field="snmp.community",
                original=sanitized.snmp.community,
                redacted=new_value,
            ))
            sanitized.snmp.community = new_value

        for j, v3user in enumerate(sanitized.snmp.v3_users):
            # Phase-3 R6.1: redact the SNMPv3 username too (same
            # rationale as local-user-name above — USM securityName
            # is operator-chosen identity).
            if v3user.name:
                new_name = table.redact_snmpv3_user_name(v3user.name)
                subs.append(Substitution(
                    category="snmpv3-user-name",
                    field=f"snmp.v3_users[{j}].name",
                    original=v3user.name,
                    redacted=new_name,
                ))
                v3user.name = new_name
            if v3user.auth_passphrase:
                new_value = table.redact_secret("AUTH")
                subs.append(Substitution(
                    category="snmpv3-auth",
                    field=f"snmp.v3_users[{j}].auth_passphrase",
                    original=v3user.auth_passphrase,
                    redacted=new_value,
                ))
                v3user.auth_passphrase = new_value
            if v3user.priv_passphrase:
                new_value = table.redact_secret("PRIV")
                subs.append(Substitution(
                    category="snmpv3-priv",
                    field=f"snmp.v3_users[{j}].priv_passphrase",
                    original=v3user.priv_passphrase,
                    redacted=new_value,
                ))
                v3user.priv_passphrase = new_value

    # ---- RADIUS shared secrets (canonical field name: ``key``) ----
    for i, server in enumerate(sanitized.radius_servers):
        if server.key:
            new_value = table.redact_secret("RADIUS")
            subs.append(Substitution(
                category="radius-shared-secret",
                field=f"radius_servers[{i}].key",
                original=server.key,
                redacted=new_value,
            ))
            server.key = new_value

    # ---- DHCP pool DNS servers ----
    for i, pool in enumerate(sanitized.dhcp_servers):
        new_dns = []
        for j, ip in enumerate(pool.dns_servers):
            new_ip = table.redact_ip_string(ip)
            if new_ip != ip:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"dhcp_servers[{i}].dns_servers[{j}]",
                    original=ip,
                    redacted=new_ip,
                ))
            new_dns.append(new_ip)
        pool.dns_servers = new_dns

    # ---- static-route gateways ----
    for i, route in enumerate(sanitized.static_routes):
        if route.gateway:
            new_gw = table.redact_ip_string(route.gateway)
            if new_gw != route.gateway:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"static_routes[{i}].gateway",
                    original=route.gateway,
                    redacted=new_gw,
                ))
                route.gateway = new_gw

    # ---- Tier-3 carry-through — strip entirely ----
    if sanitized.dropped_tier3_sections:
        n = len(sanitized.dropped_tier3_sections)
        subs.append(Substitution(
            category="tier3-stripped",
            field="dropped_tier3_sections",
            original=f"{n} entries",
            redacted="(stripped)",
        ))
        sanitized.dropped_tier3_sections = []

    return sanitized, subs


# ---------------------------------------------------------------------------
# Substitution-table — counter-per-session for cross-reference stability
# ---------------------------------------------------------------------------


class _SubstitutionTable:
    """Per-session redaction table.

    Same input value → same output across the whole config so
    cross-references survive (a hostname referenced in 5 places gets
    the same redacted value all 5 times).
    """

    def __init__(self) -> None:
        self._hostnames: dict[str, str] = {}
        self._domains: dict[str, str] = {}
        self._ipv4: dict[str, str] = {}
        self._communities: dict[str, str] = {}
        self._secret_counters: dict[str, int] = {}
        self._hash_counter: int = 0
        self._docs_range_counters = {
            "192.0.2": 0,
            "198.51.100": 0,
            "203.0.113": 0,
        }
        # Phase-3 R6.1 additions — operator-chosen identity strings
        # (usernames) that the renderer must preserve across cross-
        # references.  E.g. if an AAA stanza references a local user
        # by name, the rename must apply consistently in both the
        # user definition AND the AAA reference.
        self._local_user_names: dict[str, str] = {}
        self._snmpv3_user_names: dict[str, str] = {}

    def redact_hostname(self, name: str) -> str:
        if name not in self._hostnames:
            self._hostnames[name] = f"device-{len(self._hostnames) + 1}"
        return self._hostnames[name]

    def redact_domain(self, domain: str) -> str:
        if domain not in self._domains:
            self._domains[domain] = f"example-{len(self._domains) + 1}.test"
        return self._domains[domain]

    def redact_ipv4(self, ip: str) -> str:
        """Redact a public IPv4; preserve private / loopback / docs / CGNAT."""
        if ip in self._ipv4:
            return self._ipv4[ip]
        try:
            addr = ipaddress.IPv4Address(ip)
        except ValueError:
            return ip
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        ):
            return ip
        # Already in docs ranges
        if str(addr).startswith(("192.0.2.", "198.51.100.", "203.0.113.")):
            return ip
        # CGNAT
        if addr in ipaddress.ip_network("100.64.0.0/10"):
            return ip
        # Public — substitute via cycle through the three docs ranges
        ranges = ["192.0.2", "198.51.100", "203.0.113"]
        chosen = ranges[len(self._ipv4) % 3]
        self._docs_range_counters[chosen] += 1
        host = self._docs_range_counters[chosen]
        if host > 254:  # wrap if we somehow exceed 254 unique IPs per range
            host = ((host - 1) % 254) + 1
        new_ip = f"{chosen}.{host}"
        self._ipv4[ip] = new_ip
        return new_ip

    def redact_ip_string(self, value: str) -> str:
        """Redact public IPv4 in a free-form string field; preserve other content."""
        try:
            ipaddress.IPv4Address(value)
            return self.redact_ipv4(value)
        except ValueError:
            return value

    def redact_community(self, community: str) -> str:
        if community not in self._communities:
            self._communities[community] = f"public_redacted_{len(self._communities) + 1}"
        return self._communities[community]

    def redact_secret(self, category: str) -> str:
        """Generate a category-tagged fake secret (counter-per-category)."""
        n = self._secret_counters.get(category, 0) + 1
        self._secret_counters[category] = n
        return f"REDACTED-{category}-{n}"

    def redact_local_user_name(self, name: str) -> str:
        """Cross-reference-stable local-user-name redaction.

        Same input → same output across the whole config so any
        reference to the user from another stanza (AAA, sudo, role
        assignments, ACL "permit user X" idioms) resolves to the
        same placeholder.

        Returns ``localuser1`` for the first distinct name seen,
        ``localuser2`` for the second, etc.  Numbering is per-session
        — restart of the sanitizer produces the same numbering for
        the same input (assuming deterministic iteration order of
        the canonical model's ``local_users`` list, which Pydantic
        guarantees).
        """
        if name not in self._local_user_names:
            n = len(self._local_user_names) + 1
            self._local_user_names[name] = f"localuser{n}"
        return self._local_user_names[name]

    def redact_snmpv3_user_name(self, name: str) -> str:
        """Cross-reference-stable SNMPv3 user-name redaction.

        Same input → same output across the whole config so any
        SNMPv3 trap-target reference or group-membership stanza
        resolves to the same placeholder.

        Returns ``snmpv3user1`` / ``snmpv3user2`` / etc.  Numbered
        independently from :meth:`redact_local_user_name` — a config
        with one local user + one SNMPv3 user produces ``localuser1``
        and ``snmpv3user1``, NOT ``localuser1`` and ``snmpv3user2``
        (per-class counter, not session-wide).
        """
        if name not in self._snmpv3_user_names:
            n = len(self._snmpv3_user_names) + 1
            self._snmpv3_user_names[name] = f"snmpv3user{n}"
        return self._snmpv3_user_names[name]

    def redact_hash(self, original: str) -> str:
        """Format-preserving fake hash so the codec's render produces valid syntax.

        Recognises the major prefix-keyed formats — Junos ``$9$``,
        crypt ``$5$``/``$6$``, bcrypt ``$2y$``, FortiGate ``ENC``,
        Cisco type-7 (hex), and falls back to opaque-hex / generic
        for unrecognised formats.
        """
        self._hash_counter += 1
        n = self._hash_counter

        # Junos $9$
        if original.startswith("$9$"):
            return f"$9$fakeSalt$fakeHash{n:04d}ExampleValue"

        # Linux crypt
        for prefix in ("$1$", "$5$", "$6$"):
            if original.startswith(prefix):
                return f"{prefix}fakeSalt$fakeHash{n:04d}ExampleHashValue"

        # bcrypt (OPNsense, FreeBSD)
        if original.startswith(("$2y$", "$2a$", "$2b$")):
            keep = original[:7] if len(original) >= 7 else "$2y$11$"
            return f"{keep}fakeBcryptHashValue{n:04d}AAAAAAAAAAAAAAAA"

        # FortiGate ENC <base64>
        if original.startswith("ENC "):
            return f"ENC fakeEncodedSecret{n:04d}"

        # Cisco type-7 (uppercase hex)
        if re.match(r"^[0-9A-F]{4,}$", original) and len(original) <= 64:
            return f"070C285F4D{n:04X}"

        # Aruba SHA-1 / generic-hex (lowercase or mixed-case hex blob)
        if re.match(r"^[0-9a-fA-F]+$", original):
            length = len(original)
            return ("deadbeef" * (length // 8 + 1))[:length]

        # Unknown format — generic placeholder
        return f"fake-hash-{n:04d}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _redact_ip_list(
    values: list[str],
    field_name: str,
    category: str,
    table: _SubstitutionTable,
    subs: list[Substitution],
) -> list[str]:
    """Redact a list of IP-string entries; record substitutions inline."""
    out: list[str] = []
    for j, ip in enumerate(values):
        new_ip = table.redact_ip_string(ip)
        if new_ip != ip:
            subs.append(Substitution(
                category=category,
                field=f"{field_name}[{j}]",
                original=ip,
                redacted=new_ip,
            ))
        out.append(new_ip)
    return out
