"""Regression tests for the Arista EOS hostname-whitespace sanitiser.

Phase 4b cross-vendor cleanup — flagged by the mikrotik_routeros
source agent.  ``intent.hostname = "Quinta Router"`` previously
emitted ``hostname Quinta Router`` which the EOS parser
(`\\s*$` anchor) refused at parse-time, so the round-trip lost
the hostname entirely.  Render now routes the value through
:func:`netconfig.migration._naming.sanitise_hostname` so the
emitted form is consumable.

See also:
- netconfig/migration/_naming.py — shared sanitiser
- netconfig/migration/codecs/arista_eos/render.py — call site
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import CanonicalIntent
from netconfig.migration.codecs.arista_eos import AristaEOSCodec

pytestmark = pytest.mark.unit


def test_arista_hostname_with_space_emits_underscored() -> None:
    """``"Quinta Router"`` (with space) emits ``hostname
    Quinta_Router`` — the unquoted ``hostname Quinta Router`` form
    must NOT appear (would be rejected by Arista's parser)."""
    intent = CanonicalIntent(hostname="Quinta Router")
    out = AristaEOSCodec().render(intent)
    assert "hostname Quinta_Router" in out
    assert "hostname Quinta Router" not in out


def test_arista_hostname_without_space_unchanged() -> None:
    """Single-token name passes through verbatim — regression guard
    for the same-vendor round-trip path."""
    intent = CanonicalIntent(hostname="sw-edge-01")
    out = AristaEOSCodec().render(intent)
    assert "hostname sw-edge-01" in out


def test_arista_hostname_round_trips_through_arista_parser() -> None:
    """Build with a space, render, parse back — the parser sees the
    sanitised form (``Quinta_Router``), not the original.  Source
    state is intentionally lost on round-trip; this is the wire
    boundary, not a model boundary."""
    codec = AristaEOSCodec()
    out = codec.render(CanonicalIntent(hostname="Quinta Router"))
    parsed = codec.parse(out)
    assert parsed.hostname == "Quinta_Router"


def test_mikrotik_to_arista_hostname_with_space() -> None:
    """End-to-end: a synthetic mikrotik-shaped intent with
    ``hostname="Quinta Router"`` (the bug-report case from the
    Phase 4b mikrotik agent) renders to Arista as a consumable
    ``hostname Quinta_Router`` line.  Pinned at the cross-codec
    boundary so future refactors can't silently regress the wire
    form."""
    # The "source" canonical tree carries the literal source-side
    # hostname with whitespace preserved — that's the canonical
    # contract, the source state is honest about what was on the
    # MikroTik device.  Render is the wire boundary that sanitises.
    intent = CanonicalIntent(hostname="Quinta Router")
    out = AristaEOSCodec().render(intent)
    assert "hostname Quinta_Router" in out
