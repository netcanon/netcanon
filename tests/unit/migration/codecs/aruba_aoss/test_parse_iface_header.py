"""
Regression tests for ``_IFACE_HEADER_RE`` widening.

Phase 4 finding (rank 1, ~66 cells) — the original regex was

    ^interface\\s+("?[A-Za-z]*\\d+(?:/\\d+)?"?)\\s*$

which silently dropped cross-vendor interface names whenever a
JunOS / IOS-XE / Cisco-CLI capture flowed through this codec via
Phase 4 bidirectionality fixtures.  The widened pattern accepts
any token starting with an alphanumeric followed by alphanumerics,
``.``, ``/``, or ``-``.  See ``netconfig/migration/codecs/aruba_aoss/
parse.py`` and ``tests/fixtures/real/PHASE4_RECONCILIATION.md``.
"""

from __future__ import annotations

import pytest

from netconfig.migration.codecs.aruba_aoss.parse import _IFACE_HEADER_RE

pytestmark = pytest.mark.unit


def test_iface_header_accepts_cross_vendor_names() -> None:
    """Cross-vendor interface names must match after the widening.

    These are the names surfaced by Phase 4 finding 1 — JunOS
    sub-interfaces (``ge-0/0/1.100``), routed VLAN interfaces
    (``irb``, ``irb.100``), full-form Cisco port names
    (``GigabitEthernet0/0/0``, ``TenGigabitEthernet1/0/1``), and
    EtherChannel aggregates (``Port-channel1``, ``Port-Channel10``).
    """
    for name in [
        "ge-0/0/1",
        "ge-0/0/1.100",
        "irb",
        "irb.100",
        "GigabitEthernet0/0/0",
        "TenGigabitEthernet1/0/1",
        "Port-channel1",
        "Port-Channel10",
    ]:
        assert _IFACE_HEADER_RE.match(f"interface {name}"), f"failed: {name}"


def test_iface_header_native_aoss_forms_still_match() -> None:
    """Native AOS-S port-name forms must continue to match.

    Drawn from the real-capture corpus under
    ``tests/fixtures/real/aruba_aoss/*.cfg`` — bare numerics
    (2920 / 2930F standalone), letter-prefix uplinks, stacked
    slot/port (2930M / 3810M / 5-member-stack), and trunk aliases.
    """
    for name in ["1", "25", "A1", "Trk1", "1/A1"]:
        assert _IFACE_HEADER_RE.match(f"interface {name}"), f"failed: {name}"


def test_iface_header_quoted_names_still_match() -> None:
    """Quoted forms remain accepted (the capture group preserves quotes)."""
    for name in ['"1"', '"1/A1"', '"ge-0/0/1.100"']:
        assert _IFACE_HEADER_RE.match(f"interface {name}"), f"failed: {name}"


def test_iface_header_rejects_garbage() -> None:
    """Non-interface-shaped tokens must still be rejected."""
    for line in [
        "interface",  # no name
        "interface ",  # whitespace only
        "interface !weird",  # leading punctuation
        "interface _underscore",  # underscore not in AOS-S native forms
        "ip address 1.2.3.4",  # not an interface header at all
    ]:
        assert not _IFACE_HEADER_RE.match(line), f"unexpectedly matched: {line!r}"
