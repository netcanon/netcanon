"""Honesty-machinery lossy declarations — 2026-07-06 review theme 3 (#23/#24).

Two declared-supported-but-actually-lossy surfaces were silent (classify()
fail-opened to "supported"):

* #23 MikroTik + AOS-S substitute SNMPv3 auth/priv algorithms on render
  (sha224->SHA256, 3des->DES, aes128->aes, ...) with no lossy declaration, so
  validation reported ok during a crypto change.
* #24 DHCP pool had zero sub-field walker vocabulary, so MikroTik (which drops
  a non-default lease_time to the 86400 default) could not declare the loss —
  a /dhcp-servers/pool/lease-time declaration was flagged a dead path.

Matrix/walker-only — no parse/render change, so mesh-flat.  Each assertion
fails against the pre-fix code (verified by stashing).
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
)
from netcanon.migration.canonical.xpath_walker import _walk_canonical
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit


# ── #23 SNMPv3 algorithm substitution declared lossy ───────────────────


@pytest.mark.parametrize("codec_name", ["mikrotik_routeros", "aruba_aoss"])
@pytest.mark.parametrize(
    "path", ["/snmp/v3-user/auth-protocol", "/snmp/v3-user/priv-protocol"]
)
def test_snmpv3_algorithm_substitution_declared_lossy(codec_name, path):
    caps = get_codec(codec_name).capabilities
    assert caps.classify(path) == "lossy", (
        f"{codec_name} silently substitutes {path} — must declare it lossy "
        "so validation surfaces the crypto downgrade (#23)"
    )


# ── #24 DHCP lease-time walker vocabulary + MikroTik lossy ──────────────


def _pool_intent(lease_time: int) -> CanonicalIntent:
    return CanonicalIntent(
        dhcp_servers=[CanonicalDHCPPool(
            interface="vlan10",
            network="10.0.0.0/24", start_ip="10.0.0.10", end_ip="10.0.0.99",
            gateway="10.0.0.1", dns_servers=["10.0.0.2"],
            domain_name="lab.example", lease_time=lease_time,
        )],
    )


def test_dhcp_subfields_are_walked_when_populated():
    walked = set(_walk_canonical(_pool_intent(7200)))
    # The addresses a pool hands out, and where it is served: a target
    # that writes neither serves another set, on another interface.
    assert "/dhcp-servers/pool/range" in walked
    assert "/dhcp-servers/pool/interface" in walked
    assert "/dhcp-servers/pool/gateway" in walked
    assert "/dhcp-servers/pool/dns-servers" in walked
    assert "/dhcp-servers/pool/domain-name" in walked
    # Non-default lease -> walked (so a dropping codec can declare it).
    assert "/dhcp-servers/pool/lease-time" in walked


def test_default_lease_time_is_not_walked():
    # The 86400 default round-trips implicitly, so no codec need declare it.
    walked = set(_walk_canonical(_pool_intent(86400)))
    assert "/dhcp-servers/pool/lease-time" not in walked


def test_a_pool_with_no_range_and_no_interface_walks_neither():
    walked = set(_walk_canonical(CanonicalIntent(
        dhcp_servers=[CanonicalDHCPPool(network="10.0.0.0/24")],
    )))
    assert "/dhcp-servers/pool/range" not in walked
    assert "/dhcp-servers/pool/interface" not in walked


def test_eos_writes_where_a_pool_is_served():
    # EOS writes `dhcp server ipv4` under the interface that serves a
    # pool's subnet, and its parser reads the pool's interface from it
    # (tests/unit/migration/codecs/arista_eos/test_dhcp_pool_round_trip.py):
    # where a pool is served is no longer declared lossy.
    caps = get_codec("arista_eos").capabilities
    assert caps.classify("/dhcp-servers/pool/interface") == "supported"


@pytest.mark.parametrize(
    "path", ["/dhcp-servers/pool/interface", "/dhcp-servers/pool/lease-time"],
)
def test_mikrotik_writes_where_a_pool_is_served_and_its_lease(path):
    # RouterOS writes each pool's `/ip dhcp-server` on its interface,
    # with its lease-time, and reads both back
    # (tests/unit/migration/codecs/mikrotik_routeros/test_dhcp_server.py):
    # the two are no longer declared lossy.
    caps = get_codec("mikrotik_routeros").capabilities
    assert caps.classify(path) == "supported"
