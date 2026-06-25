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
* Public/global IPv6 anywhere → RFC 3849 docs range (``2001:db8::``);
  ULA (fc00::/7), link-local (fe80::/10), loopback (``::1``),
  unspecified (``::``), multicast (ff00::/8), and the docs range
  itself preserved
* ``CanonicalLocalUser.name`` → ``localuserN`` (Phase-3 R6.1 addition —
  the username is operator-identifying when chosen by the operator,
  e.g. ``alice``, ``john.smith``, or ``user12``)
* ``CanonicalLocalUser.hashed_password`` → format-preserving fake hash
  (e.g. ``$9$...`` Junos form preserved; FortiGate ``ENC ...`` form
  preserved; Cisco type-7 hex preserved; Linux ``$5$`` / ``$6$`` /
  bcrypt ``$2y$`` shapes preserved)
* ``CanonicalSNMP.community`` → ``public_redacted_N``
* ``CanonicalSNMP.contact`` → ``<contact redacted>`` (operator PII —
  email / name)
* ``CanonicalSNMP.location`` → ``<location redacted>`` (operator PII —
  site / address)
* ``CanonicalSNMP.trap_hosts`` (public IP → docs range; FQDN →
  ``host-N.example.test``)
* ``CanonicalSNMPv3User.name`` → ``snmpv3userN`` (Phase-3 R6.1 — same
  rationale as local-user-name above)
* ``CanonicalSNMPv3User.auth_passphrase`` → ``REDACTED-AUTH-N``
* ``CanonicalSNMPv3User.priv_passphrase`` → ``REDACTED-PRIV-N``
* ``CanonicalRADIUSServer.key`` → ``REDACTED-RADIUS-N``
* ``CanonicalRADIUSServer.host`` (public IP → docs range; FQDN →
  ``host-N.example.test``)
* ``CanonicalIntent.ntp_servers`` / ``syslog_servers`` (public IP → docs
  range; FQDN → ``host-N.example.test`` — a DNS name re-leaks the org
  domain).  ``dns_servers`` are IP-only by protocol (resolver addresses)
* ``CanonicalVRRPGroup.authentication`` → ``<scheme>:REDACTED-VRRP-AUTH-N``
  — the ``<scheme>:`` prefix (``plain:`` / ``md5:`` / ``carp-key:``) is
  metadata and is preserved so the renderer still emits valid syntax;
  only the secret value (cleartext for ``plain:`` / ``carp-key:``, a
  key-string for ``md5:``) is replaced
* ``CanonicalVRRPGroup.virtual_ips`` / ``virtual_ipv6s`` (public
  entries) → docs range — a VRRP / CARP VIP is frequently the
  public-facing HA gateway, so it is redacted like any other IP
* ``CanonicalIPv4Address.virtual_gateway_address`` /
  ``CanonicalIPv6Address.virtual_gateway_address`` (public) → docs range
  — the anycast / VARP virtual-gateway IP is the structural twin of a
  VRRP/CARP VIP (a public one reveals real routable infrastructure), and
  is rendered verbatim by Arista/Aruba/Junos/NX-OS/IOS-XE, so it is
  redacted at every address site (interface + VLAN SVI, v4 + v6)
* ``CanonicalInterface.description`` → ``description redacted``
* ``CanonicalDHCPPool.dns_servers`` (public entries) → docs range
* ``CanonicalDHCPPool.gateway`` (public) → docs range
* ``CanonicalDHCPPool.start_ip`` / ``end_ip`` (public) → docs range
* ``CanonicalDHCPPool.network`` (public host portion) → docs range,
  prefix length preserved
* ``CanonicalVlan.ipv4_addresses`` (public SVI L3 addresses) → docs
  range — SEPARATE field from ``interfaces[].ipv4_addresses``; the
  Aruba / Junos SVI-on-VLAN model renders these directly
* ``CanonicalStaticRoute.gateway`` (public) → docs range
* ``CanonicalStaticRoute.destination`` (public destination CIDR) → docs
  range, prefix length preserved
* ``CanonicalIntent.dropped_tier3_sections`` → stripped entirely
  (Tier-3 carry-through may contain anything; never share)

Limitations:

* The canonical model is the AST; whatever the parser doesn't model
  is not visible to this sanitizer.  Banner text, comments, and raw
  Tier-3 stanzas in the source bytes are not field-typed redacted —
  Tier-3 content is dropped on parse, banners are typically
  parse-and-ignore.
* IP-typed redaction covers both IPv4 and IPv6 (interface / SVI /
  DHCP / VRRP-VIP addresses).  Host fields that legitimately hold DNS
  NAMES (NTP / syslog / SNMP-trap / RADIUS targets) are also redacted:
  a multi-label FQDN (``nms.corp.example``) → a stable
  ``host-N.example.test`` placeholder so the org domain does not
  re-leak; a bare single label (``localhost``) has no domain and is
  preserved.  A host written into a field the model does NOT type as a
  host (e.g. inside an unmodelled Tier-3 stanza) still passes through —
  hand-edit those before sharing.
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
from collections.abc import Callable
from dataclasses import dataclass, field

from ..migration.canonical.intent import CanonicalIntent
from ..migration.codecs.registry import get_codec

#: A DNS hostname: dot-separated labels (alnum + internal hyphen), at least
#: two labels (the leading ``(?:...)`` + the ``(?:\.…)+`` group), <= 253
#: chars.  Used by :meth:`_SubstitutionTable.redact_host` to tell an FQDN
#: host field (whose domain suffix re-leaks the org) from a bare single
#: label (``localhost`` / ``nms`` — no domain to leak) or free text.  IP
#: literals are matched + handled BEFORE this regex, so the fact that a
#: dotted-quad also matches the shape is moot.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

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

    # ---- host-list scalars (DNS / NTP / syslog) ----
    # DNS resolvers are IPs by protocol (RFC 2132 option 6); NTP + syslog
    # targets are commonly FQDNs, so those two also redact a DNS-name entry
    # (org-domain re-leak) via ``redact_host``.
    sanitized.dns_servers = _redact_ip_list(
        sanitized.dns_servers, "dns_servers", "ipv4-public", table, subs)
    sanitized.ntp_servers = _redact_ip_list(
        sanitized.ntp_servers, "ntp_servers", "ipv4-public", table, subs,
        redactor=table.redact_host)
    sanitized.syslog_servers = _redact_ip_list(
        sanitized.syslog_servers, "syslog_servers", "ipv4-public", table, subs,
        redactor=table.redact_host)

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
            # The anycast / VARP virtual-gateway address is a SIBLING of
            # ``.ip`` and is rendered verbatim by 5 codecs (Arista
            # ``ip address virtual``, Aruba ``active-gateway ip``, Junos,
            # NX-OS DAG, IOS-XE SD-Access).  A public one reveals real
            # routable infrastructure exactly like a VRRP/CARP VIP, so
            # redact it the same way (cache-keyed, so it tracks ``.ip``).
            if addr.virtual_gateway_address:
                new_vga = table.redact_ipv4(addr.virtual_gateway_address)
                if new_vga != addr.virtual_gateway_address:
                    subs.append(Substitution(
                        category="ipv4-public",
                        field=f"interfaces[{i}].ipv4_addresses[{j}].virtual_gateway_address",
                        original=addr.virtual_gateway_address,
                        redacted=new_vga,
                    ))
                    addr.virtual_gateway_address = new_vga

        for j, addr in enumerate(iface.ipv6_addresses):
            new_ip = table.redact_ipv6(addr.ip)
            if new_ip != addr.ip:
                subs.append(Substitution(
                    category="ipv6-public",
                    field=f"interfaces[{i}].ipv6_addresses[{j}].ip",
                    original=addr.ip,
                    redacted=new_ip,
                ))
                addr.ip = new_ip
            if addr.virtual_gateway_address:
                new_vga = table.redact_ipv6(addr.virtual_gateway_address)
                if new_vga != addr.virtual_gateway_address:
                    subs.append(Substitution(
                        category="ipv6-public",
                        field=f"interfaces[{i}].ipv6_addresses[{j}].virtual_gateway_address",
                        original=addr.virtual_gateway_address,
                        redacted=new_vga,
                    ))
                    addr.virtual_gateway_address = new_vga

        # ---- VRRP / CARP / HSRP authentication ----
        # Cleartext-bearing: the ``plain:`` / ``carp-key:`` schemes
        # hold the literal secret and ``md5:`` holds a key-string, all
        # of which the renderers emit back verbatim.  Preserve the
        # ``<scheme>:`` prefix (each renderer slices a scheme-width
        # prefix and branches on ``startswith``) and redact only the
        # value portion.
        for k, group in enumerate(iface.vrrp_groups):
            if group.authentication:
                new_auth = table.redact_vrrp_authentication(group.authentication)
                subs.append(Substitution(
                    category="vrrp-authentication",
                    field=f"interfaces[{i}].vrrp_groups[{k}].authentication",
                    original=group.authentication,
                    redacted=new_auth,
                ))
                group.authentication = new_auth
            if group.description:
                subs.append(Substitution(
                    category="vrrp-description",
                    field=f"interfaces[{i}].vrrp_groups[{k}].description",
                    original=group.description,
                    redacted="description redacted",
                ))
                group.description = "description redacted"

            # The virtual IP is frequently the public-facing HA gateway
            # address — redact it like every other IP field (the sibling
            # ``authentication`` secret above was redacted, but the VIP
            # bypassed sanitisation entirely before this).  ``redact_ip_
            # string`` handles both the IPv4 and IPv6 VIP lists; private
            # VIPs (the LAN-gateway common case) are preserved.
            if group.virtual_ips:
                new_vips: list[str] = []
                for m, vip in enumerate(group.virtual_ips):
                    new_vip = table.redact_ip_string(vip)
                    if new_vip != vip:
                        subs.append(Substitution(
                            category="ipv4-public",
                            field=(f"interfaces[{i}].vrrp_groups[{k}]"
                                   f".virtual_ips[{m}]"),
                            original=vip,
                            redacted=new_vip,
                        ))
                    new_vips.append(new_vip)
                group.virtual_ips = new_vips
            if group.virtual_ipv6s:
                new_vip6s: list[str] = []
                for m, vip in enumerate(group.virtual_ipv6s):
                    new_vip = table.redact_ip_string(vip)
                    if new_vip != vip:
                        subs.append(Substitution(
                            category="ipv6-public",
                            field=(f"interfaces[{i}].vrrp_groups[{k}]"
                                   f".virtual_ipv6s[{m}]"),
                            original=vip,
                            redacted=new_vip,
                        ))
                    new_vip6s.append(new_vip)
                group.virtual_ipv6s = new_vip6s

    # ---- VLAN SVI IPv4 addresses ----
    # R-16 / CF-04: SVI L3 addressing lives on ``CanonicalVlan.
    # ipv4_addresses`` (intent.py), a SEPARATE field from
    # ``interfaces[].ipv4_addresses``.  The interface walk above does
    # NOT reach it.  On Aruba AOS-S the SVI is a property of the VLAN
    # (no sibling interface) and renders straight off this list, so a
    # public SVI IP would otherwise survive sanitisation verbatim;
    # Junos IRB folds here too, and Cisco/Arista keep an independent
    # synthesised copy.  ``redact_ipv4`` is cache-keyed by IP string,
    # so a copy that mirrors an interface address resolves to the SAME
    # docs-range substitute (cross-reference stable).
    for i, vlan in enumerate(sanitized.vlans):
        # R-16 / CF-04 follow-up (v0.4.0 self-audit): VLAN name +
        # description are operator free text (``CEO-OFFICE``,
        # ``Jane-Desk x4012``).  Name is redacted via a stable table so
        # every ``vlan members <name>`` cross-reference stays consistent;
        # description → opaque placeholder.
        if vlan.name:
            new_name = table.redact_vlan_name(vlan.name)
            subs.append(Substitution(
                category="vlan-name",
                field=f"vlans[{i}].name",
                original=vlan.name,
                redacted=new_name,
            ))
            vlan.name = new_name
        if vlan.description:
            subs.append(Substitution(
                category="vlan-description",
                field=f"vlans[{i}].description",
                original=vlan.description,
                redacted="description redacted",
            ))
            vlan.description = "description redacted"

        for j, addr in enumerate(vlan.ipv4_addresses):
            new_ip = table.redact_ipv4(addr.ip)
            if new_ip != addr.ip:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"vlans[{i}].ipv4_addresses[{j}].ip",
                    original=addr.ip,
                    redacted=new_ip,
                ))
                addr.ip = new_ip
            # Anycast/VARP virtual-gateway companion on the SVI address —
            # same leak class as the interface site above (the SVI's
            # ``active-gateway`` / ``ip address virtual`` line).
            if addr.virtual_gateway_address:
                new_vga = table.redact_ipv4(addr.virtual_gateway_address)
                if new_vga != addr.virtual_gateway_address:
                    subs.append(Substitution(
                        category="ipv4-public",
                        field=f"vlans[{i}].ipv4_addresses[{j}].virtual_gateway_address",
                        original=addr.virtual_gateway_address,
                        redacted=new_vga,
                    ))
                    addr.virtual_gateway_address = new_vga

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

        # R-16 / CF-04: SNMP contact + location are operator PII.
        # ``contact`` commonly carries an email / name
        # (``admin@corp.example``, ``"Jane Doe x4012"``); ``location``
        # carries a physical site / street address.  Free-text →
        # opaque placeholder (mirrors the ``description redacted``
        # pattern), NOT an IP redaction.
        if sanitized.snmp.contact:
            redacted_contact = "<contact redacted>"
            subs.append(Substitution(
                category="snmp-contact",
                field="snmp.contact",
                original=sanitized.snmp.contact,
                redacted=redacted_contact,
            ))
            sanitized.snmp.contact = redacted_contact

        if sanitized.snmp.location:
            redacted_location = "<location redacted>"
            subs.append(Substitution(
                category="snmp-location",
                field="snmp.location",
                original=sanitized.snmp.location,
                redacted=redacted_location,
            ))
            sanitized.snmp.location = redacted_location

        # R-16 / CF-04: SNMP trap-target hosts.  Public IPv4/IPv6 → docs
        # range; private / loopback preserved.  A trap target written as an
        # FQDN re-leaks the org domain, so route through ``redact_host``
        # (65f9c01 #20) — bare single labels still pass through.
        new_traps: list[str] = []
        for j, host in enumerate(sanitized.snmp.trap_hosts):
            new_host = table.redact_host(host)
            if new_host != host:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"snmp.trap_hosts[{j}]",
                    original=host,
                    redacted=new_host,
                ))
            new_traps.append(new_host)
        sanitized.snmp.trap_hosts = new_traps

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
            if v3user.engine_id:
                new_value = table.redact_secret("SNMPV3-ENGINE-ID")
                subs.append(Substitution(
                    category="snmpv3-engine-id",
                    field=f"snmp.v3_users[{j}].engine_id",
                    original=v3user.engine_id,
                    redacted=new_value,
                ))
                v3user.engine_id = new_value

    # ---- RADIUS server host + shared secret (field name: ``key``) ----
    for i, server in enumerate(sanitized.radius_servers):
        # R-16 / CF-04: the RADIUS server address is network-
        # identifying.  Public IPv4/IPv6 → docs range; private preserved.
        # An FQDN target re-leaks the org domain, so route through
        # ``redact_host`` (65f9c01 #20) — bare single labels pass through.
        if server.host:
            new_host = table.redact_host(server.host)
            if new_host != server.host:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"radius_servers[{i}].host",
                    original=server.host,
                    redacted=new_host,
                ))
                server.host = new_host
        if server.key:
            new_value = table.redact_secret("RADIUS")
            subs.append(Substitution(
                category="radius-shared-secret",
                field=f"radius_servers[{i}].key",
                original=server.key,
                redacted=new_value,
            ))
            server.key = new_value

    # ---- DHCP pool DNS servers + gateway ----
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

        # R-16 / CF-04: pool gateway (sibling of the already-redacted
        # static-route gateway).  Public IPv4 → docs range; private
        # preserved (the common case for a LAN default-gateway).
        if pool.gateway:
            new_gw = table.redact_ip_string(pool.gateway)
            if new_gw != pool.gateway:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"dhcp_servers[{i}].gateway",
                    original=pool.gateway,
                    redacted=new_gw,
                ))
                pool.gateway = new_gw

        # Pool range bounds + served subnet are network-location PII
        # (sibling of the already-redacted gateway / dns_servers on the
        # same record — the trust asymmetry the audit flagged).  Public
        # IPv4/IPv6 → docs range; private (the common LAN case) preserved.
        # ``network`` is a CIDR, so redact only its host portion and keep
        # the prefix length.
        if pool.start_ip:
            new_start = table.redact_ip_string(pool.start_ip)
            if new_start != pool.start_ip:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"dhcp_servers[{i}].start_ip",
                    original=pool.start_ip,
                    redacted=new_start,
                ))
                pool.start_ip = new_start
        if pool.end_ip:
            new_end = table.redact_ip_string(pool.end_ip)
            if new_end != pool.end_ip:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"dhcp_servers[{i}].end_ip",
                    original=pool.end_ip,
                    redacted=new_end,
                ))
                pool.end_ip = new_end
        if pool.network:
            new_net = table.redact_cidr(pool.network)
            if new_net != pool.network:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"dhcp_servers[{i}].network",
                    original=pool.network,
                    redacted=new_net,
                ))
                pool.network = new_net

        # v0.4.0 self-audit: the DHCP domain-name is an internal DNS
        # suffix (``corp.acme.example``) — operator/org-identifying PII.
        # Reuse the domain table so it matches the top-level domain
        # redaction style (and stays stable if the same suffix recurs).
        if pool.domain_name:
            new_domain = table.redact_domain(pool.domain_name)
            subs.append(Substitution(
                category="domain",
                field=f"dhcp_servers[{i}].domain_name",
                original=pool.domain_name,
                redacted=new_domain,
            ))
            pool.domain_name = new_domain

    # ---- static-route destinations + gateways + descriptions ----
    for i, route in enumerate(sanitized.static_routes):
        # The destination prefix is a sibling of the already-redacted
        # gateway on the same record — a public destination CIDR (a route
        # to a provider / peer / branch block) is as network-identifying as
        # the next hop, yet bypassed sanitisation entirely before this.
        # ``redact_cidr`` preserves the prefix length; private destinations
        # (the common LAN / aggregate case) are preserved (audit 65f9c01 #20).
        if route.destination:
            new_dest = table.redact_cidr(route.destination)
            if new_dest != route.destination:
                subs.append(Substitution(
                    category="ipv4-public",
                    field=f"static_routes[{i}].destination",
                    original=route.destination,
                    redacted=new_dest,
                ))
                route.destination = new_dest
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
        if route.description:
            subs.append(Substitution(
                category="static-route-description",
                field=f"static_routes[{i}].description",
                original=route.description,
                redacted="description redacted",
            ))
            route.description = "description redacted"

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

    # ---- Tier-3 raw_sections carry-through — strip entirely ----
    # Defense-in-depth (audit finding DATA-02): no production parser
    # populates raw_sections today, but the IOS-XE renderer emits any
    # entries verbatim, so a future parser that fills it must not be
    # able to round-trip unredacted vendor text through the sanitiser.
    if sanitized.raw_sections:
        n = len(sanitized.raw_sections)
        subs.append(Substitution(
            category="tier3-stripped",
            field="raw_sections",
            original=f"{n} entries",
            redacted="(stripped)",
        ))
        sanitized.raw_sections = {}

    # ---- routing-instance descriptions + RD / route-targets ----
    for i, ri in enumerate(sanitized.routing_instances):
        if ri.description:
            subs.append(Substitution(
                category="routing-instance-description",
                field=f"routing_instances[{i}].description",
                original=ri.description,
                redacted="description redacted",
            ))
            ri.description = "description redacted"
        if ri.route_distinguisher:
            new_rd = table.redact_route_target(ri.route_distinguisher)
            subs.append(Substitution(
                category="route-distinguisher",
                field=f"routing_instances[{i}].route_distinguisher",
                original=ri.route_distinguisher,
                redacted=new_rd,
            ))
            ri.route_distinguisher = new_rd
        ri.rt_imports = _redact_route_target_list(
            ri.rt_imports, f"routing_instances[{i}].rt_imports", table, subs
        )
        ri.rt_exports = _redact_route_target_list(
            ri.rt_exports, f"routing_instances[{i}].rt_exports", table, subs
        )

    # ---- VXLAN / EVPN overlay (BUM mcast group, VTEP flood-list, Type-5
    #      route-targets + advertised prefix) — network-identifying fabric
    #      values that bypassed every field-typed redaction above ----
    for i, vni in enumerate(sanitized.vxlan_vnis):
        if vni.mcast_group:
            new_g = table.redact_mcast_group(vni.mcast_group)
            if new_g != vni.mcast_group:
                subs.append(Substitution(
                    category="mcast-group",
                    field=f"vxlan_vnis[{i}].mcast_group",
                    original=vni.mcast_group,
                    redacted=new_g,
                ))
                vni.mcast_group = new_g
        vni.flood_list = _redact_ip_list(
            vni.flood_list, f"vxlan_vnis[{i}].flood_list", "vtep-flood", table, subs
        )
    for i, r5 in enumerate(sanitized.evpn_type5_routes):
        r5.rt_imports = _redact_route_target_list(
            r5.rt_imports, f"evpn_type5_routes[{i}].rt_imports", table, subs
        )
        r5.rt_exports = _redact_route_target_list(
            r5.rt_exports, f"evpn_type5_routes[{i}].rt_exports", table, subs
        )
        if r5.prefix:
            new_p = table.redact_cidr(r5.prefix)
            if new_p != r5.prefix:
                subs.append(Substitution(
                    category="evpn-type5-prefix",
                    field=f"evpn_type5_routes[{i}].prefix",
                    original=r5.prefix,
                    redacted=new_p,
                ))
                r5.prefix = new_p

    # ---- Junos apply-groups verbatim carry-through — strip entirely ----
    # v0.4.0 self-audit (HIGH): ``group_content`` holds the verbatim
    # token tails of every applied ``set groups <G> ...`` line, and the
    # Junos renderer re-emits them byte-for-byte — so a password hash,
    # SNMP community, or username placed INSIDE an apply-group bypasses
    # every field-typed redaction above and round-trips unredacted.  The
    # flattened canonical surfaces (local_users, snmp.community, ...) are
    # already redacted, so dropping the verbatim group bodies loses no
    # *modelled* intent; strip fail-closed like raw_sections rather than
    # re-parsing arbitrary group bodies (same defense-in-depth posture).
    if sanitized.group_content:
        subs.append(Substitution(
            category="apply-groups-stripped",
            field="group_content",
            original=f"{len(sanitized.group_content)} group(s)",
            redacted="(stripped)",
        ))
        sanitized.group_content = {}
    if sanitized.apply_groups:
        subs.append(Substitution(
            category="apply-groups-stripped",
            field="apply_groups",
            original=f"{len(sanitized.apply_groups)} reference(s)",
            redacted="(stripped)",
        ))
        sanitized.apply_groups = []

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
        self._ipv6: dict[str, str] = {}
        self._ipv6_counter: int = 0
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
        self._vlan_names: dict[str, str] = {}
        # Overlay (EVPN/VXLAN/VRF) identifiers — network-identifying AND
        # cross-referenced (a VRF's RD recurs as a route-target across
        # sibling VRFs + EVPN Type-5 routes; a VXLAN BUM group recurs
        # across VNIs), so they redact cross-reference-stable like the
        # name maps above.
        self._route_targets: dict[str, str] = {}
        self._mcast_groups: dict[str, str] = {}
        # DNS-name host fields (NTP / syslog / SNMP-trap / RADIUS targets
        # written as FQDNs) re-leak the org domain.  Map each distinct
        # name to a stable opaque placeholder so cross-references survive.
        self._host_names: dict[str, str] = {}

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

    def redact_ipv6(self, ip: str) -> str:
        """Redact a public/global IPv6 address; preserve ULA / link-local /
        loopback / unspecified / multicast / documentation.

        Mirrors :meth:`redact_ipv4`.  Global unicast maps to a
        deterministic RFC 3849 documentation address (``2001:db8::N``),
        cache-keyed by the source string so the same address redacts
        identically everywhere (cross-reference stable).  Preserved
        as-is: ULA ``fc00::/7``, link-local ``fe80::/10``, loopback
        ``::1``, unspecified ``::``, multicast ``ff00::/8``, reserved,
        and the documentation range ``2001:db8::/32`` itself.
        """
        if ip in self._ipv6:
            return self._ipv6[ip]
        try:
            addr = ipaddress.IPv6Address(ip)
        except ValueError:
            return ip
        # ``is_private`` already covers ULA, link-local, loopback,
        # unspecified, and the 2001:db8::/32 docs range; the rest are
        # listed explicitly for self-documentation / defensive belt.
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        ):
            return ip
        if addr in ipaddress.ip_network("2001:db8::/32"):
            return ip
        # Public global unicast — substitute a deterministic docs address.
        self._ipv6_counter += 1
        new_ip = f"2001:db8::{self._ipv6_counter:x}"
        self._ipv6[ip] = new_ip
        return new_ip

    def redact_ip_string(self, value: str) -> str:
        """Redact a public IPv4 *or* IPv6 address in a free-form string
        field; preserve private addresses and non-IP content."""
        try:
            ipaddress.IPv4Address(value)
            return self.redact_ipv4(value)
        except ValueError:
            pass
        try:
            ipaddress.IPv6Address(value)
            return self.redact_ipv6(value)
        except ValueError:
            return value

    def redact_cidr(self, value: str) -> str:
        """Redact the address portion of a ``host/prefix`` CIDR string,
        preserving the prefix length.  Bare addresses (no ``/``) are
        redacted whole; non-IP content is returned verbatim."""
        addr, sep, prefix = value.partition("/")
        new_addr = self.redact_ip_string(addr)
        return f"{new_addr}{sep}{prefix}" if sep else new_addr

    def redact_host(self, value: str) -> str:
        """Redact a host field that may be an IP *OR* a DNS name.

        IP literals go through :meth:`redact_ip_string` (public → docs
        range; private / loopback preserved) — unchanged behaviour.

        A multi-label DNS name re-leaks the operator's domain: not just
        ``syslog.corp.example.com`` (where the suffix is the org domain)
        but also a bare registered domain like ``acme.com`` (where the
        *first* label is the org).  Because the registered-domain boundary
        can't be found reliably without a public-suffix list, the whole
        name is mapped to a stable opaque placeholder
        (``host-N.example.test``) — same name → same placeholder across the
        config, so cross-references survive.  This deliberately also
        redacts public service names (``pool.ntp.org``): a sanitised config
        is for sharing, and over-redacting a public pool is harmless.

        A bare single label (``localhost`` / ``nms`` — no dot, no domain to
        leak) and any non-host free text are returned unchanged.
        """
        try:
            ipaddress.IPv4Address(value)
            return self.redact_ipv4(value)
        except ValueError:
            pass
        try:
            ipaddress.IPv6Address(value)
            return self.redact_ipv6(value)
        except ValueError:
            pass
        if "." in value and _HOSTNAME_RE.match(value):
            if value not in self._host_names:
                self._host_names[value] = (
                    f"host-{len(self._host_names) + 1}.example.test"
                )
            return self._host_names[value]
        return value

    def redact_route_target(self, value: str) -> str:
        """Cross-reference-stable RD / route-target redaction.

        A route-distinguisher and the route-targets that import/export it
        are network-identifying — they encode the operator's ASN (or a
        loopback IP) plus an internal index — and they are *correlated*:
        a VRF's RD often equals its RT, and the same RT recurs on the
        EVPN Type-5 routes and sibling VRFs that share the VPN.  Map each
        distinct ``<left>:<right>`` token to a stable placeholder built on
        the RFC 5398 documentation ASN ``64496`` so the correlation
        structure survives while the real ASN/IP and index are hidden.
        Same input → same output across the whole config.
        """
        if value not in self._route_targets:
            self._route_targets[value] = f"64496:{len(self._route_targets) + 1}"
        return self._route_targets[value]

    def redact_mcast_group(self, addr: str) -> str:
        """Redact a VXLAN underlay multicast (BUM) group address.

        :meth:`redact_ipv4` deliberately *preserves* multicast (well-known
        groups are non-identifying), but an administratively-scoped VXLAN
        BUM group (``239.0.0.0/8``) is an operator-chosen fabric value
        that correlates configs, so it must be redacted here.  Map each
        distinct group to a stable address in the RFC 5771 MCAST-TEST-NET
        documentation range (``233.252.0.0/24``).  Non-multicast / non-IP
        values fall through to the normal IP redaction.
        """
        try:
            a = ipaddress.IPv4Address(addr)
        except ValueError:
            return self.redact_ip_string(addr)
        if not a.is_multicast:
            return self.redact_ip_string(addr)
        if addr not in self._mcast_groups:
            host = (len(self._mcast_groups) % 254) + 1
            self._mcast_groups[addr] = f"233.252.0.{host}"
        return self._mcast_groups[addr]

    def redact_community(self, community: str) -> str:
        if community not in self._communities:
            self._communities[community] = f"public_redacted_{len(self._communities) + 1}"
        return self._communities[community]

    def redact_secret(self, category: str) -> str:
        """Generate a category-tagged fake secret (counter-per-category)."""
        n = self._secret_counters.get(category, 0) + 1
        self._secret_counters[category] = n
        return f"REDACTED-{category}-{n}"

    def redact_vrrp_authentication(self, value: str) -> str:
        """Redact a VRRP / CARP / HSRP authentication token.

        Canonical form is ``<scheme>:<value>`` (e.g. ``plain:secret``,
        ``carp-key:bytes``, ``md5:keystring``).  The value after the
        scheme is the secret — cleartext for ``plain:`` / ``carp-key:``
        and a key-string for ``md5:`` — and is always replaced.  The
        ``<scheme>:`` prefix is metadata, NOT a secret, and is preserved
        verbatim: every renderer slices a scheme-width prefix
        (``plain:`` → ``[6:]``, ``md5:`` → ``[4:]``, ``carp-key:`` →
        ``[9:]``) and branches on ``startswith``, so the prefix MUST
        survive intact or the rendered output becomes malformed.

        Per-occurrence counter (like :meth:`redact_secret`) — VRRP auth
        is not cross-referenced, so the value need not be stable across
        groups.
        """
        scheme, sep, _secret = value.partition(":")
        placeholder = self.redact_secret("VRRP-AUTH")
        return f"{scheme}{sep}{placeholder}" if sep else placeholder

    def redact_vlan_name(self, name: str) -> str:
        """Cross-reference-stable VLAN-name redaction.

        VLAN membership is modelled by numeric ID (``access_vlan`` /
        ``trunk_allowed_vlans`` are ints), so the human VLAN *name* is a
        display label the renderer resolves from this VLAN object —
        redacting it here flows consistently to every ``set vlans
        <name> ...`` / ``vlan members <name>`` reference.  A VLAN name
        like ``CEO-OFFICE`` or ``Jane-Desk`` is operator PII.
        """
        if name not in self._vlan_names:
            self._vlan_names[name] = f"vlan-{len(self._vlan_names) + 1}"
        return self._vlan_names[name]

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
    *,
    redactor: Callable[[str], str] | None = None,
) -> list[str]:
    """Redact a list of host-string entries; record substitutions inline.

    *redactor* defaults to :meth:`_SubstitutionTable.redact_ip_string`
    (IP-only — VTEP flood-list, DNS resolvers).  Pass
    :meth:`_SubstitutionTable.redact_host` for fields that legitimately
    hold FQDNs (NTP / syslog targets) so a DNS-name entry is redacted too.
    """
    fn = redactor or table.redact_ip_string
    out: list[str] = []
    for j, ip in enumerate(values):
        new_ip = fn(ip)
        if new_ip != ip:
            subs.append(Substitution(
                category=category,
                field=f"{field_name}[{j}]",
                original=ip,
                redacted=new_ip,
            ))
        out.append(new_ip)
    return out


def _redact_route_target_list(
    values: list[str],
    field_name: str,
    table: _SubstitutionTable,
    subs: list[Substitution],
) -> list[str]:
    """Redact a list of RD / route-target entries cross-reference-stable."""
    out: list[str] = []
    for j, rt in enumerate(values):
        new_rt = table.redact_route_target(rt)
        if new_rt != rt:
            subs.append(Substitution(
                category="route-target",
                field=f"{field_name}[{j}]",
                original=rt,
                redacted=new_rt,
            ))
        out.append(new_rt)
    return out
