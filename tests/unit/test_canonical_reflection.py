"""Unit test for the shared canonical-model reflection enumerators
(`tests/support/canonical_reflection.py`).

The fail-surfaced-defaults completeness guards (walker coverage + sanitizer
coverage) both rest on ``scalar_leaves`` / ``str_leaves``. If the enumerator
silently *under*-counts (misses a leaf), both guards develop a hole at their
foundation — the exact failure mode review finding MF-3 flagged. So pin the
enumerators' behaviour against a tiny synthetic model that exercises every
annotation shape the real model uses (scalar, list-of-scalar, optional, dict,
nested model, list-of-nested) plus the ``Literal`` edge the real model does NOT
yet use (so a future ``Literal`` field's handling is predictable, not a surprise).
"""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import BaseModel

from tests.support.canonical_reflection import (
    reachable_models,
    scalar_leaves,
    str_leaves,
)

pytestmark = pytest.mark.unit


class _Child(BaseModel):
    cstr: str = ""
    cint: int = 0


class _Root(BaseModel):
    s: str = ""
    n: int = 0
    b: bool = False
    ls: list[str] = []
    li: list[int] = []
    opt: str | None = None
    d: dict[str, str] = {}
    lit: Literal["a", "b"] = "a"
    child: _Child | None = None          # nested model (optional) — NOT a leaf
    children: list[_Child] = []          # list of nested models — NOT a leaf


class TestReachableModels:
    def test_descends_through_optional_and_list(self):
        assert reachable_models(_Root) == {_Root, _Child}

    def test_resolves_forward_ref_to_a_later_defined_model(self):
        """A field annotating a model defined LATER in its module is a
        ``ForwardRef`` (``get_args() == ()``) until the owner is rebuilt — it
        must NOT be invisible to the walk. The real model hits this:
        ``CanonicalInterface.vrrp_groups: list[CanonicalVRRPGroup]`` (VRRPGroup
        is defined further down ``intent.py``). ``reachable_models`` must reach
        it WITHOUT relying on an instance having been constructed first."""
        from netcanon.migration.canonical.intent import (
            CanonicalIntent,
            CanonicalVRRPGroup,
        )

        assert CanonicalVRRPGroup in reachable_models(CanonicalIntent), (
            "reachable_models missed a forward-referenced nested model — the "
            "completeness guards would silently skip every leaf under it"
        )


class TestScalarLeaves:
    def test_exact_leaf_set(self):
        # Every scalar / list-of-scalar / dict / Literal field is a leaf; the
        # two nested-model containers (child, children) are NOT (their child
        # fields cstr/cint are the leaves, reached by recursion).
        assert scalar_leaves(_Root) == {
            ("_Root", "s"),
            ("_Root", "n"),
            ("_Root", "b"),
            ("_Root", "ls"),
            ("_Root", "li"),
            ("_Root", "opt"),
            ("_Root", "d"),       # dict[str,str] — yielded (caller must classify)
            ("_Root", "lit"),     # Literal — yielded (neither scalar-type nor model)
            ("_Child", "cstr"),
            ("_Child", "cint"),
        }

    def test_nested_model_containers_are_not_leaves(self):
        leaves = scalar_leaves(_Root)
        assert ("_Root", "child") not in leaves
        assert ("_Root", "children") not in leaves


class TestStrLeaves:
    def test_only_str_bearing_leaves(self):
        # str scalar, list[str], Optional[str], dict[..,str] qualify.
        # int/bool/list[int] do NOT. A Literal-of-strings does NOT (its args are
        # string *values*, not the `str` type) — correct: a fixed enum can't hold
        # an arbitrary operator IP/secret literal.
        assert str_leaves(_Root) == {
            ("_Root", "s"),
            ("_Root", "ls"),
            ("_Root", "opt"),
            ("_Root", "d"),
            ("_Child", "cstr"),
        }

    def test_literal_is_not_a_str_leaf(self):
        assert ("_Root", "lit") not in str_leaves(_Root)
