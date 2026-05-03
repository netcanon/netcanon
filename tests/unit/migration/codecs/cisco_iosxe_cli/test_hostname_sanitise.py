"""Regression tests for the Cisco IOS-XE hostname-whitespace sanitiser.

Phase 4b cross-vendor cleanup — flagged by the mikrotik_routeros
source agent.  ``intent.hostname = "Quinta Router"`` previously
emitted ``hostname Quinta Router`` which the IOS-XE parser
(``\\S+``) silently truncated to ``Quinta`` on round-trip, dropping
the trailing token.  Render now routes the value through
:func:`netconfig.migration._naming.sanitise_hostname` so the
emitted form survives the parser without truncation.

See also:
- netconfig/migration/_naming.py — shared sanitiser
- netconfig/migration/codecs/cisco_iosxe_cli/render.py — call site
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import CanonicalIntent
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec

pytestmark = pytest.mark.unit


def test_cisco_hostname_with_space_emits_underscored() -> None:
    """``"Quinta Router"`` (with space) emits ``hostname
    Quinta_Router`` — the unquoted ``hostname Quinta Router`` form
    must NOT appear (would silently truncate to ``Quinta`` at
    parse-time)."""
    intent = CanonicalIntent(hostname="Quinta Router")
    out = CiscoIOSXECLICodec().render(intent)
    assert "hostname Quinta_Router" in out
    assert "hostname Quinta Router" not in out


def test_cisco_hostname_without_space_unchanged() -> None:
    """Single-token name passes through verbatim — regression guard
    for the same-vendor round-trip path."""
    intent = CanonicalIntent(hostname="rtr-edge-01")
    out = CiscoIOSXECLICodec().render(intent)
    assert "hostname rtr-edge-01" in out


def test_cisco_hostname_round_trips_through_cisco_parser() -> None:
    """Build with a space, render, parse back — the parser sees the
    sanitised form (``Quinta_Router``), not the original.  Source
    state is intentionally lost on round-trip; this is the wire
    boundary, not a model boundary."""
    codec = CiscoIOSXECLICodec()
    out = codec.render(CanonicalIntent(hostname="Quinta Router"))
    parsed = codec.parse(out)
    assert parsed.hostname == "Quinta_Router"
