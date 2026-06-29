"""Ratchet guard for the McCabe cyclomatic-complexity gate (audit e5b77d7 #4).

The audit flagged "19 F-rank cyclomatic functions and no complexity gate in CI"
-- nothing stopped new high-complexity code from merging.  The gate now lives in
``pyproject.toml`` (``C90`` in ruff's select + ``[tool.ruff.lint.mccabe]
max-complexity = 25``), enforced by the existing ``Lint (ruff)`` CI job.

A gate alone is not enough for a legacy codebase: the ~25 pre-existing offenders
(codec parse/render hot spots, the walker, the sanitiser) are grandfathered with
an inline ``C901`` suppression at their def site.  Without a cap, a contributor
could dodge the gate by sprinkling more such suppressions instead of refactoring
-- the exact regression the audit warned about, just relocated.

This guard makes the grandfather list a RATCHET: the count is pinned, so it can
only go DOWN (refactor a hot spot below 25, drop its suppression, decrement the
number here) -- never up.  A new function over 25 forces a real choice: refactor
it, or consciously bump both the suppression AND this ceiling in one diff.

(The marker string is assembled from fragments so this file does not itself
carry a directive ruff's textual noqa scanner would try to parse.)
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_TREES = ("netcanon", "netcanon_desktop", "tools")

#: The inline-suppression marker, assembled so the literal directive text never
#: appears verbatim in this source file.
_MARKER = "# noqa:" + " C901"

#: Pre-existing functions over the max-complexity ceiling, grandfathered with an
#: inline ``C901`` suppression.  RATCHET: decrement as hot spots are refactored;
#: a new suppression (count > this) must not be added to dodge the gate.
_GRANDFATHERED = 25


def _c901_suppression_count() -> int:
    n = 0
    for tree in _TREES:
        for path in (_ROOT / tree).rglob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if _MARKER in line:
                    n += 1
    return n


def test_complexity_debt_does_not_grow() -> None:
    """The grandfathered-complexity backlog can only shrink.  If this fails high,
    a new over-25 function was suppressed instead of refactored -- refactor it (or
    consciously raise this ceiling).  If it fails low, you refactored a hot spot
    below 25: drop the stale suppression and decrement ``_GRANDFATHERED`` to lock
    in the win."""
    found = _c901_suppression_count()
    assert found == _GRANDFATHERED, (
        f"expected {_GRANDFATHERED} grandfathered C901 suppressions, found {found}. "
        "The cyclomatic-complexity debt must only ratchet DOWN -- do not add a "
        "suppression to dodge the max-complexity=25 gate; refactor the function "
        "(then decrement _GRANDFATHERED), or consciously raise the ceiling here."
    )


def test_mccabe_gate_is_configured() -> None:
    """The gate itself must stay wired -- a silent removal of ``C90`` from select
    or of the max-complexity setting would make every suppression above inert."""
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lint = data["tool"]["ruff"]["lint"]
    assert "C90" in lint["select"], "`C90` (mccabe) dropped from ruff select -- the complexity gate is off"
    assert lint["mccabe"]["max-complexity"] == 25, "mccabe max-complexity ceiling changed unexpectedly"
