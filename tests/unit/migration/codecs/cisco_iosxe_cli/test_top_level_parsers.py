"""
Regression tests for the cisco_iosxe_cli top-level parsers added in
Phase 4 rank-6 fix backlog.

Before this fix, ``netcanon/migration/codecs/cisco_iosxe_cli/parse.py``
silently dropped:

* ``ip name-server`` (top-level form — the DHCP-pool form was the only
  thing parsed)
* ``ip domain name`` / ``ip domain-name``
* ``ntp server``
* ``vrf definition`` blocks (no parser awareness at all)
* per-interface ``vrf forwarding <name>``

The four tests below pin each addition.  See
``tests/fixtures/real/PHASE4_RECONCILIATION.md`` (rank 6) for the
backlog ticket and ``tests/fixtures/real/phase4_findings_*.md`` for the
per-pair finding rows that motivated each parser.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.cisco_iosxe_cli.parse import parse_intent

pytestmark = pytest.mark.unit


def test_top_level_resolver_and_ntp_parse() -> None:
    """``ip name-server`` (multi-line + multi-server-per-line),
    ``ip domain name``, and ``ntp server`` all reach canonical."""
    cfg = (
        "hostname r1\n"
        "ip domain name example.com\n"
        "ip name-server 1.1.1.1\n"
        "ip name-server 8.8.8.8 9.9.9.9\n"
        "ntp server 10.0.0.1\n"
        "ntp server 10.0.0.2\n"
    )
    intent = parse_intent(cfg)
    assert intent.domain == "example.com"
    assert intent.dns_servers == ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
    assert intent.ntp_servers == ["10.0.0.1", "10.0.0.2"]


def test_legacy_ip_domain_name_hyphen_form() -> None:
    """Pre-12.4T Cisco IOS spelled this ``ip domain-name`` (hyphen).
    Real captures from older devices still carry that form."""
    cfg = "ip domain-name legacy.example.com\n"
    intent = parse_intent(cfg)
    assert intent.domain == "legacy.example.com"


def test_vrf_definition_parses() -> None:
    """``vrf definition <name>`` block lands as a CanonicalRoutingInstance
    with RD + RT metadata.  ``route-target both`` expands to both
    import and export lists."""
    cfg = (
        "vrf definition TENANT_A\n"
        " description tenant a\n"
        " rd 65000:1\n"
        " route-target both 65000:1\n"
        " address-family ipv4\n"
        " exit-address-family\n"
    )
    intent = parse_intent(cfg)
    assert len(intent.routing_instances) == 1
    ri = intent.routing_instances[0]
    assert ri.name == "TENANT_A"
    assert ri.route_distinguisher == "65000:1"
    assert ri.description == "tenant a"
    # ``route-target both`` expands canonically into both lists.
    assert ri.rt_imports == ["65000:1"]
    assert ri.rt_exports == ["65000:1"]


def test_per_interface_vrf_forwarding_assigns_canonical_vrf() -> None:
    """``vrf forwarding <name>`` inside an interface stanza populates
    :attr:`CanonicalInterface.vrf` so downstream renderers can emit the
    matching membership directive on the target side."""
    cfg = (
        "vrf definition TENANT_A\n"
        " rd 65000:1\n"
        "interface GigabitEthernet0/0\n"
        " vrf forwarding TENANT_A\n"
        " ip address 10.0.0.1 255.255.255.0\n"
    )
    intent = parse_intent(cfg)
    gi = next(i for i in intent.interfaces if i.name == "GigabitEthernet0/0")
    assert gi.vrf == "TENANT_A"
