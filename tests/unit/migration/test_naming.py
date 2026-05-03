"""Tests for the cross-codec naming-value sanitiser.

The helper under test is imported by the arista_eos and
cisco_iosxe_cli render paths to rewrite whitespace in hostname
tokens (Phase 4b cross-vendor cleanup, flagged by the
mikrotik_routeros source agent).

See also: netconfig/migration/_naming.py
"""

from __future__ import annotations

import pytest

from netconfig.migration._naming import sanitise_hostname

pytestmark = pytest.mark.unit


def test_sanitise_hostname_no_whitespace() -> None:
    """Single-token names emit unchanged — round-trip stability for
    the same-vendor case where source captures already comply."""
    assert sanitise_hostname("foo") == "foo"


def test_sanitise_hostname_single_space() -> None:
    """``Quinta Router`` (the bug-report case) → underscored form."""
    assert sanitise_hostname("Quinta Router") == "Quinta_Router"


def test_sanitise_hostname_multiple_spaces() -> None:
    """Whitespace runs collapse to a SINGLE separator — not one per
    space character.  ``"a  b"`` → ``"a_b"`` (one underscore)."""
    assert sanitise_hostname("a  b") == "a_b"


def test_sanitise_hostname_tabs_and_newlines() -> None:
    """Any whitespace token (``\\t``, ``\\n``, mixed) collapses to
    the separator — the regex is ``\\s+``."""
    assert sanitise_hostname("a\tb\nc") == "a_b_c"


def test_sanitise_hostname_strips_leading_trailing() -> None:
    """Leading/trailing whitespace is dropped before substitution —
    avoids emitting ``_foo_`` for a stray padding capture."""
    assert sanitise_hostname("  foo  ") == "foo"


def test_sanitise_hostname_empty_string() -> None:
    """Empty input returns empty — caller's truthy gate stays valid."""
    assert sanitise_hostname("") == ""


def test_sanitise_hostname_only_whitespace() -> None:
    """Whitespace-only input collapses to empty after the strip."""
    assert sanitise_hostname("   ") == ""


def test_sanitise_hostname_custom_separator() -> None:
    """Caller can override the separator (e.g. ``-`` for vendors that
    prefer hyphens)."""
    assert sanitise_hostname("a b", separator="-") == "a-b"
