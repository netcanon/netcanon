"""Unit tests for the shared IPv6 transition-format IPv4 extractor (SEC-3 / #42).

``embedded_ipv4s`` is the primitive behind both the sanitizer's public-IPv4
leak guard and the egress allow-list's embedded-loopback guard, so it is
pinned directly here in addition to the two consumers' behavioural tests.
"""

from __future__ import annotations

import ipaddress

import pytest

from netcanon.ip_transition import embedded_ipv4s

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        ("::ffff:127.0.0.1", ["127.0.0.1"]),        # IPv4-mapped
        ("2002:7f00:0001::", ["127.0.0.1"]),        # 6to4 -> 127.0.0.1
        ("2002:0808:0808::", ["8.8.8.8"]),          # 6to4 -> 8.8.8.8
        ("64:ff9b::a9fe:a9fe", ["169.254.169.254"]),   # NAT64 well-known
        ("64:ff9b:1::a9fe:a9fe", ["169.254.169.254"]),  # NAT64 local-use
        ("::127.0.0.1", ["127.0.0.1"]),             # deprecated IPv4-compatible
    ],
)
def test_extracts_embedded_ipv4(literal: str, expected: list[str]) -> None:
    addr = ipaddress.IPv6Address(literal)
    assert [str(v) for v in embedded_ipv4s(addr)] == expected


@pytest.mark.parametrize(
    "literal",
    [
        "2606:4700::1111",  # native public IPv6 — nothing embedded
        "2001:db8::1",      # documentation range
        "::",               # unspecified — low word 0, excluded
        "::1",              # loopback — low word 1, excluded
    ],
)
def test_native_ipv6_yields_nothing(literal: str) -> None:
    assert embedded_ipv4s(ipaddress.IPv6Address(literal)) == []
