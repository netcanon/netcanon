"""IPv6 transition-format IPv4 extraction — shared primitive (SEC-3 / #42).

Several IPv6 formats smuggle a routable IPv4 in their low bits: 6to4
(``2002::/16``), IPv4-mapped (``::ffff:a.b.c.d``), Teredo (``2001:0::/32``),
NAT64 (``64:ff9b::/96`` + the RFC 8215 local-use prefix), and the deprecated
IPv4-compatible ``::a.b.c.d``.  A check that only inspects the v6 layer misses
the embedded IPv4 entirely — NAT64 and 6to4 even classify as reserved/private
at the v6 layer, so ``is_loopback`` / ``is_private`` on the IPv6 object never
fire on the address that actually gets routed.

Two callers need the same extraction with opposite polarity, so it lives here:

* the sanitizer (:func:`netcanon.tools.sanitize._embedded_public_ipv4`) keeps
  the embedded IPv4 iff it is *public* (a leak to redact), and
* the egress allow-list (:func:`netcanon.services.egress._is_blocked_ip`)
  blocks the target iff the embedded IPv4 is loopback / link-local /
  unspecified — the metadata-endpoint SSRF surface (``64:ff9b::169.254.169.254``
  reaches ``169.254.169.254``).
"""

from __future__ import annotations

import ipaddress

# NAT64 carries the IPv4 in its low 32 bits but — unlike 6to4 / IPv4-mapped /
# Teredo — has no ``ipaddress`` accessor, so we recognise the prefixes and
# slice the bits ourselves.  Both the well-known prefix (RFC 6052) and the
# RFC 8215 local-use prefix are in play.
NAT64_NETWORKS = (
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("64:ff9b:1::/48"),
)


def embedded_ipv4s(
    addr: ipaddress.IPv6Address,
) -> list[ipaddress.IPv4Address]:
    """Every IPv4 embedded in an IPv6 *transition* literal, in precedence order.

    Recognises 6to4, IPv4-mapped, Teredo (server + client), NAT64 (both
    prefixes), and — only when none of the above match — the deprecated
    IPv4-compatible ``::a.b.c.d`` form.  Returns an empty list for a native
    IPv6 address (and never yields ``::`` / ``::1``, whose low word is <= 1).
    """
    candidates: list[ipaddress.IPv4Address] = []
    if addr.sixtofour is not None:
        candidates.append(addr.sixtofour)
    if addr.ipv4_mapped is not None:
        candidates.append(addr.ipv4_mapped)
    if addr.teredo is not None:
        # (server, client): both are clear-text routable IPv4s.
        candidates.extend(addr.teredo)
    if any(addr in net for net in NAT64_NETWORKS):
        candidates.append(ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF))
    if not candidates:
        # IPv4-compatible (deprecated): ``::a.b.c.d`` — all high bits zero
        # with a non-trivial low word (exclude ``::`` and ``::1``).
        low = int(addr) & 0xFFFFFFFF
        if (int(addr) >> 32) == 0 and low > 1:
            candidates.append(ipaddress.IPv4Address(low))
    return candidates
