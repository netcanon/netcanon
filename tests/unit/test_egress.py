"""Unit tests for the backup egress allow-list guard (review finding #3).

`assert_egress_allowed` blocks targets that resolve to loopback or
link-local addresses (the latter covers the 169.254.169.254 cloud-metadata
endpoint) while leaving RFC-1918 / CGNAT / public addresses alone.  A
resolution failure is deferred to the connect attempt, never treated as a
block.
"""

from __future__ import annotations

import pytest

from netcanon.services.egress import EgressBlocked, assert_egress_allowed

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.5.5.5",
        "::1",
        "169.254.169.254",  # cloud metadata endpoint
        "169.254.0.1",
        "fe80::1",
        "::ffff:127.0.0.1",      # IPv4-mapped IPv6 loopback (bypass guard)
        "::ffff:169.254.169.254",  # IPv4-mapped metadata endpoint
    ],
)
def test_loopback_and_link_local_are_blocked(host: str) -> None:
    with pytest.raises(EgressBlocked):
        assert_egress_allowed(host)


@pytest.mark.parametrize(
    "host",
    [
        "8.8.8.8",
        "1.1.1.1",
        "192.168.1.1",   # RFC-1918 — real managed devices live here
        "10.0.0.1",
        "172.16.0.1",
        "100.64.0.1",    # CGNAT
        "2001:db8::1",
    ],
)
def test_public_and_private_ranges_are_allowed(host: str) -> None:
    assert assert_egress_allowed(host) is None


def test_localhost_hostname_is_blocked() -> None:
    # 'localhost' resolves locally (no network) to a loopback address.
    with pytest.raises(EgressBlocked):
        assert_egress_allowed("localhost")


def test_unresolvable_host_is_not_blocked() -> None:
    # A resolution failure defers to the connect attempt — failing closed
    # here would turn DNS hiccups into spurious backup failures.  The
    # `.invalid` TLD is guaranteed non-resolvable (RFC 6761).
    assert assert_egress_allowed("netcanon-egress-test.invalid") is None
