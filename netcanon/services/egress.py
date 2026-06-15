"""Egress allow-list guard for backup targets (review finding #3).

When ``Settings.block_private_egress`` is enabled, backup entry points call
:func:`assert_egress_allowed` before enqueuing a device so that a target
resolving to a loopback or link-local address — most notably the cloud
metadata endpoint ``169.254.169.254`` — is refused.  This blunts the SSRF
surface the 2026-06-14 review flagged: the no-auth API + the default
``0.0.0.0`` bind otherwise let any reachable caller turn the backup engine
into an internal port-scanner / metadata probe.

Scope + honest limits:

* Enforced at the **entry points** (``create_backup`` + the schedule
  trigger), not at SSH-connect time, so it does not fully defeat a
  DNS-rebinding attacker who controls a hostname that resolves benign here
  and malicious at connect.  Connect-time re-validation in the collector
  layer is a noted follow-up.
* RFC-1918 (``10/8``, ``172.16/12``, ``192.168/16``) and CGNAT
  (``100.64/10``) are **allowed** — real managed devices live there.  Only
  loopback + link-local are blocked.
* Default-off: with the setting disabled the guard is never invoked, so
  there is zero behaviour change for desktop / trusted-VLAN deployments.
"""

from __future__ import annotations

import ipaddress
import logging
import socket

logger = logging.getLogger(__name__)


class EgressBlocked(Exception):
    """Raised when a backup target is denied by the egress policy."""


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """A target IP is blocked if it is loopback or link-local.

    ``is_link_local`` covers ``169.254.0.0/16`` (and ``fe80::/10``), which
    includes the ``169.254.169.254`` cloud-metadata endpoint.

    IPv4-mapped IPv6 literals (``::ffff:127.0.0.1``) parse as IPv6 and would
    otherwise sidestep the IPv4 loopback/link-local checks, so the embedded
    IPv4 address is unwrapped and re-checked.
    """
    if ip.is_loopback or ip.is_link_local:
        return True
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None and (mapped.is_loopback or mapped.is_link_local):
        return True
    return False


def assert_egress_allowed(host: str) -> None:
    """Raise :class:`EgressBlocked` if *host* resolves to a blocked address.

    *host* may be an IPv4/IPv6 literal or a hostname.  Hostnames are
    resolved and **every** returned address is checked (a single blocked
    answer rejects the target).  A resolution failure is *not* treated as a
    block — the subsequent SSH connect will surface that error on its own;
    failing closed here would turn transient DNS hiccups into spurious
    backup failures.

    Callers must only invoke this when ``Settings.block_private_egress`` is
    enabled.
    """
    host = host.strip()

    # IP literal — check directly, no DNS.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if _is_blocked_ip(ip):
            raise EgressBlocked(
                f"Egress to {host!r} is blocked by policy "
                "(loopback / link-local address; set "
                "NETCANON_BLOCK_PRIVATE_EGRESS=false to allow)."
            )
        return

    # Hostname — resolve and check every answer.
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        logger.warning(
            "Egress guard could not resolve %r (%s); deferring to the "
            "connect attempt.",
            host,
            exc,
        )
        return

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise EgressBlocked(
                f"Egress to {host!r} is blocked by policy: it resolves to "
                f"{addr} (loopback / link-local). Set "
                "NETCANON_BLOCK_PRIVATE_EGRESS=false to allow."
            )
