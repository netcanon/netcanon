"""
OPNsense top-level ``<system>/<dnsserver>`` parse + render coverage.

Real OPNsense stores resolver targets as repeated
``<system>/<dnsserver>`` children (one IP per element) — see
``tests/fixtures/real/opnsense/user_contrib_supergate_opn25.xml``
(lines 221, 223) and the "DNS Servers" section of
https://docs.opnsense.org/manual/settings_general.html.

Distinct from the per-DHCP-pool ``<dhcpd>/<zone>/<dnsserver>`` element,
which carries a comma-joined list of pool-scoped DNS servers and lands
on ``CanonicalDHCPPool.dns_servers`` rather than
``CanonicalIntent.dns_servers``.  Both wire-forms must remain working
side-by-side; the regression test at the bottom guards the DHCP-scope
behaviour while the new tests cover the system-scope wire-up.
"""

from __future__ import annotations

from netconfig.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
)
from netconfig.migration.codecs.opnsense.parse import parse_intent
from netconfig.migration.codecs.opnsense.render import render_intent


def test_opnsense_parse_top_level_dnsserver_populates_intent_dns_servers() -> None:
    raw = (
        "<opnsense>"
        "<system>"
        "<dnsserver>1.1.1.1</dnsserver>"
        "<dnsserver>9.9.9.9</dnsserver>"
        "</system>"
        "</opnsense>"
    )
    intent = parse_intent(raw)
    assert intent.dns_servers == ["1.1.1.1", "9.9.9.9"]


def test_opnsense_render_top_level_dnsserver_emits_per_entry() -> None:
    intent = CanonicalIntent(dns_servers=["1.1.1.1", "9.9.9.9"])
    out = render_intent(intent)

    # Each DNS server must appear as its own <dnsserver> child of <system>.
    assert "<dnsserver>1.1.1.1</dnsserver>" in out
    assert "<dnsserver>9.9.9.9</dnsserver>" in out
    # And NOT in the (incorrect) comma-joined form that would mirror
    # the per-DHCP-pool wire shape.
    assert "<dnsserver>1.1.1.1,9.9.9.9</dnsserver>" not in out
    # The <system> wrapper opened (regression guard against the
    # has_system_content gate dropping a DNS-only intent).
    assert "<system>" in out


def test_opnsense_round_trip_dns_servers() -> None:
    src = CanonicalIntent(dns_servers=["1.1.1.1", "9.9.9.9", "2606:4700:4700::1111"])
    rendered = render_intent(src)
    back = parse_intent(rendered)

    assert back.dns_servers == ["1.1.1.1", "9.9.9.9", "2606:4700:4700::1111"]


def test_opnsense_dhcp_pool_dnsserver_unchanged() -> None:
    """Regression guard: the per-DHCP-pool DNS-server list (canonical
    field ``CanonicalDHCPPool.dns_servers``) still round-trips through
    the ``<dhcpd>/<zone>/<dnsserver>`` comma-joined element — distinct
    from the new top-level ``<system>/<dnsserver>`` wire-form."""
    intent = CanonicalIntent()
    intent.dhcp_servers.append(
        CanonicalDHCPPool(
            interface="lan",
            start_ip="10.0.0.100",
            end_ip="10.0.0.200",
            dns_servers=["10.0.0.1", "10.0.0.2"],
        )
    )
    rendered = render_intent(intent)
    # DHCP-pool list lives under <dhcpd>/<lan>/<dnsserver> as a
    # comma-joined value (the existing wire-form).
    assert "<dnsserver>10.0.0.1,10.0.0.2</dnsserver>" in rendered

    back = parse_intent(rendered)
    assert len(back.dhcp_servers) == 1
    assert back.dhcp_servers[0].dns_servers == ["10.0.0.1", "10.0.0.2"]
    # And the system-scope list stays empty — no leakage.
    assert back.dns_servers == []


def test_opnsense_real_supergate_fixture_picks_up_system_dns() -> None:
    """End-to-end: the real supergate fixture carries two top-level
    ``<system>/<dnsserver>`` entries (9.9.9.9, 1.1.1.2).  Confirm the
    parser surfaces both on ``intent.dns_servers`` rather than dropping
    them."""
    from pathlib import Path

    fixture = (
        Path(__file__).resolve().parents[5]
        / "tests"
        / "fixtures"
        / "real"
        / "opnsense"
        / "user_contrib_supergate_opn25.xml"
    )
    raw = fixture.read_text(encoding="utf-8")
    intent = parse_intent(raw)
    assert "9.9.9.9" in intent.dns_servers
    assert "1.1.1.2" in intent.dns_servers
