"""Frozen-signature guard for the migration pipeline entry points.

``run_plan``, ``run_plan_with_rename``, and ``run_plan_with_overrides``
are a deliberately *frozen* public contract — documented in
``netcanon/services/migration_pipeline.py``, ``ARCHITECTURE.md``, and
``AGENTS.md`` — because the UI, integration/e2e tests, and README
examples call them positionally.  The standing rule is "add a NEW
function rather than change one of these signatures."

This test mechanically enforces that rule (project review 2026-06-06,
finding R-11 / CD-03): it pins each function's parameter names, order,
kind, and defaults, so a reordered positional, a renamed parameter, a
changed default, or a new required argument fails CI instead of silently
breaking positional callers.  Annotations are intentionally NOT pinned —
only the call-shape contract — so re-typing a parameter (e.g. widening a
hint) doesn't trip the guard.
"""

from __future__ import annotations

import inspect

import pytest

from netcanon.services.migration_pipeline import (
    run_plan,
    run_plan_with_overrides,
    run_plan_with_rename,
)

pytestmark = pytest.mark.unit

_REQUIRED = "<required>"


def _param_spec(fn):
    """``(name, kind, default)`` per parameter; ``<required>`` = no default."""
    spec = []
    for name, p in inspect.signature(fn).parameters.items():
        default = p.default if p.default is not inspect.Parameter.empty else _REQUIRED
        spec.append((name, p.kind.name, default))
    return spec


# The frozen contracts.  Changing any of these is a deliberate decision
# that must update BOTH this guard AND the FROZEN docstrings +
# AGENTS.md / ARCHITECTURE.md notes — or, preferably, add a new function.
_FROZEN = {
    run_plan: [
        ("source", "POSITIONAL_OR_KEYWORD", _REQUIRED),
        ("target", "POSITIONAL_OR_KEYWORD", _REQUIRED),
        ("raw_text", "POSITIONAL_OR_KEYWORD", _REQUIRED),
        ("transforms", "POSITIONAL_OR_KEYWORD", None),
        ("transform_specs", "POSITIONAL_OR_KEYWORD", None),
        ("force", "POSITIONAL_OR_KEYWORD", False),
    ],
    run_plan_with_rename: [
        ("source", "POSITIONAL_OR_KEYWORD", _REQUIRED),
        ("target", "POSITIONAL_OR_KEYWORD", _REQUIRED),
        ("raw_text", "POSITIONAL_OR_KEYWORD", _REQUIRED),
        ("port_rename_map", "POSITIONAL_OR_KEYWORD", None),
        ("transforms", "POSITIONAL_OR_KEYWORD", None),
        ("transform_specs", "POSITIONAL_OR_KEYWORD", None),
        ("force", "POSITIONAL_OR_KEYWORD", False),
    ],
    run_plan_with_overrides: [
        ("source", "POSITIONAL_OR_KEYWORD", _REQUIRED),
        ("target", "POSITIONAL_OR_KEYWORD", _REQUIRED),
        ("raw_text", "POSITIONAL_OR_KEYWORD", _REQUIRED),
        ("port_rename_map", "POSITIONAL_OR_KEYWORD", None),
        ("vlan_rename_map", "POSITIONAL_OR_KEYWORD", None),
        ("local_user_rename_map", "POSITIONAL_OR_KEYWORD", None),
        ("snmp_community_rename_map", "POSITIONAL_OR_KEYWORD", None),
        ("snmpv3_user_rename_map", "POSITIONAL_OR_KEYWORD", None),
        ("transforms", "POSITIONAL_OR_KEYWORD", None),
        ("transform_specs", "POSITIONAL_OR_KEYWORD", None),
        ("force", "POSITIONAL_OR_KEYWORD", False),
    ],
}


@pytest.mark.parametrize("fn", list(_FROZEN), ids=lambda f: f.__name__)
def test_pipeline_signature_is_frozen(fn):
    assert _param_spec(fn) == _FROZEN[fn], (
        f"{fn.__name__} signature drifted from its frozen contract. These "
        "entry points are called positionally by the UI, tests, and README "
        "examples — add a NEW function instead of changing this one (see the "
        "FROZEN docstrings in migration_pipeline.py + AGENTS.md)."
    )
