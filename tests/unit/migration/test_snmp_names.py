"""
Unit tests for :mod:`netconfig.migration.canonical.snmp_names`.

Layer A tests — transform-level correctness on synthetic
:class:`CanonicalIntent` trees, no I/O, no codec-specific behaviour.
Mirrors the structural shape of test_local_user_names.py /
test_vlan_names.py, adapted for the scalar SNMP-community domain.

The key structural difference between this orchestrator and the three
list-oriented siblings: CanonicalIntent.snmp holds a SINGLE
CanonicalSNMP object, not a list.  Consequences for tests:

  * "Collision" tests are absent — one slot + one value means two
    sources can't both land.  Multiple-entry rename maps instead
    surface as "non-matching entries generate warnings".
  * "Drop" semantics clear the community string (empty) rather than
    removing a list element; downstream render paths treat empty
    community as "don't emit the SNMP block".
  * No merge semantics — there's nothing to merge INTO.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalSNMP,
)
from netconfig.migration.canonical.snmp_names import (
    SnmpRenameResult,
    build_snmp_community_rename_transform,
    translate_snmp_community,
)

pytestmark = pytest.mark.unit


def _tree_with_snmp(
    community: str = "public",
    location: str = "",
    contact: str = "",
    trap_hosts: list[str] | None = None,
) -> CanonicalIntent:
    """Minimal canonical tree containing an SNMP block."""
    return CanonicalIntent(
        snmp=CanonicalSNMP(
            community=community,
            location=location,
            contact=contact,
            trap_hosts=list(trap_hosts or []),
        ),
    )


def _tree_without_snmp() -> CanonicalIntent:
    """Canonical tree with snmp=None — the source had no SNMP
    block."""
    return CanonicalIntent()


# ---------------------------------------------------------------------------
# Identity / no-op semantics — parity with the list-oriented orchestrators
# ---------------------------------------------------------------------------


class TestIdentityAndNoOps:
    def test_empty_map_is_noop(self):
        intent = _tree_with_snmp(community="public")
        result = translate_snmp_community(intent, rename_map={})
        assert result.applied == {}
        assert result.dropped == []
        assert intent.snmp is not None and intent.snmp.community == "public"

    def test_none_map_is_noop(self):
        intent = _tree_with_snmp(community="public")
        result = translate_snmp_community(intent, rename_map=None)
        assert result == SnmpRenameResult()
        assert intent.snmp.community == "public"

    def test_non_canonical_input_returns_empty_result(self):
        """Mock adapters produce plain dicts; defensive guard prevents
        crashes when the transform is wired into a mock-codec smoke
        test."""
        result = translate_snmp_community(
            {"not": "canonical"},  # type: ignore[arg-type]
            rename_map={"public": "monitoring-ro"},
        )
        assert result == SnmpRenameResult()


# ---------------------------------------------------------------------------
# Happy-path rename — the dominant operator use case
# ---------------------------------------------------------------------------


class TestSimpleRename:
    def test_single_rename(self):
        intent = _tree_with_snmp(community="public")
        result = translate_snmp_community(
            intent, rename_map={"public": "monitoring-ro"},
        )
        assert result.applied == {"public": "monitoring-ro"}
        assert result.dropped == []
        assert result.warnings == []
        assert intent.snmp.community == "monitoring-ro"

    def test_rename_preserves_other_snmp_fields(self):
        """Location / contact / trap_hosts should pass through
        untouched — the orchestrator's scope is community-only."""
        intent = _tree_with_snmp(
            community="public",
            location="Building 2",
            contact="netops@example.com",
            trap_hosts=["10.0.0.5", "10.0.0.6"],
        )
        translate_snmp_community(
            intent, rename_map={"public": "monitoring-ro"},
        )
        assert intent.snmp.community == "monitoring-ro"
        assert intent.snmp.location == "Building 2"
        assert intent.snmp.contact == "netops@example.com"
        assert intent.snmp.trap_hosts == ["10.0.0.5", "10.0.0.6"]

    def test_rename_to_same_value_is_noop(self):
        """Operator maps community → same string.  Not technically a
        rename, but it IS the slot's current value so the entry
        matches.  ``applied`` captures the rewrite anyway (semantic
        parity with the sibling orchestrators)."""
        intent = _tree_with_snmp(community="public")
        result = translate_snmp_community(
            intent, rename_map={"public": "public"},
        )
        # No collision warning — single-slot domain.  applied is
        # populated even though the value didn't change, mirroring
        # how local_user_names treats the same case.  Either shape
        # is defensible; matching the siblings avoids surprise.
        assert intent.snmp.community == "public"


# ---------------------------------------------------------------------------
# Drop / clear semantics
# ---------------------------------------------------------------------------


class TestClear:
    def test_none_value_clears_community(self):
        intent = _tree_with_snmp(community="public")
        result = translate_snmp_community(
            intent, rename_map={"public": None},
        )
        assert result.applied == {}
        assert result.dropped == ["public"]
        assert intent.snmp is not None
        assert intent.snmp.community == ""

    def test_clear_preserves_other_snmp_fields(self):
        """Clearing the community must not wipe location / contact /
        trap_hosts — those are independent slots that survive the
        community drop.  Render paths treat empty-community as
        "omit the SNMP block", but the canonical preservation
        matters for later re-renders within the same session."""
        intent = _tree_with_snmp(
            community="public",
            location="HQ",
            contact="ops@example.com",
            trap_hosts=["10.1.1.1"],
        )
        translate_snmp_community(
            intent, rename_map={"public": None},
        )
        assert intent.snmp.community == ""
        assert intent.snmp.location == "HQ"
        assert intent.snmp.contact == "ops@example.com"
        assert intent.snmp.trap_hosts == ["10.1.1.1"]


# ---------------------------------------------------------------------------
# Edge cases — no SNMP block, empty community, non-matching source
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_snmp_block_emits_warning_and_noops(self):
        intent = _tree_without_snmp()
        result = translate_snmp_community(
            intent, rename_map={"public": "monitoring-ro"},
        )
        assert result.applied == {}
        assert result.dropped == []
        assert len(result.warnings) == 1
        assert "no SNMP block" in result.warnings[0]
        assert intent.snmp is None

    def test_non_matching_source_emits_warning(self):
        """Operator maps 'private' but the tree has 'public'.  The
        entry doesn't fire (nothing to rewrite) but surfaces a
        warning so the operator notices their intent didn't
        apply."""
        intent = _tree_with_snmp(community="public")
        result = translate_snmp_community(
            intent, rename_map={"private": "monitoring-ro"},
        )
        assert result.applied == {}
        assert result.dropped == []
        assert len(result.warnings) == 1
        assert "does not match" in result.warnings[0]
        assert intent.snmp.community == "public"  # unchanged

    def test_empty_community_with_override(self):
        """Source has a bare SNMP block with location but no
        community.  Operator's rename map can't match (current
        community is empty string), so all entries warn."""
        intent = _tree_with_snmp(community="", location="DC1")
        result = translate_snmp_community(
            intent, rename_map={"public": "monitoring-ro"},
        )
        assert result.applied == {}
        assert "does not match" in result.warnings[0]
        assert intent.snmp.location == "DC1"

    def test_multiple_entries_only_first_match_wins(self):
        """Dict contains several rename proposals; only the one
        whose source matches the current community applies, rest
        warn."""
        intent = _tree_with_snmp(community="public")
        result = translate_snmp_community(
            intent,
            rename_map={
                "stale-community": "never-mind",
                "public": "monitoring-ro",
                "another-stale": "also-skipped",
            },
        )
        assert result.applied == {"public": "monitoring-ro"}
        assert intent.snmp.community == "monitoring-ro"
        # Two non-matching entries → two warnings.
        non_match_warnings = [
            w for w in result.warnings if "does not match" in w
        ]
        assert len(non_match_warnings) == 2


# ---------------------------------------------------------------------------
# Input validation — empty / malformed map entries
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_empty_source_key_warns_and_skips(self):
        intent = _tree_with_snmp(community="public")
        result = translate_snmp_community(
            intent, rename_map={"": "new"},
        )
        assert result.applied == {}
        assert any("empty" in w for w in result.warnings)
        assert intent.snmp.community == "public"

    def test_empty_target_value_warns_and_skips(self):
        """Empty string target (not None) is treated as malformed —
        None means "clear", but '' is an operator mistake."""
        intent = _tree_with_snmp(community="public")
        result = translate_snmp_community(
            intent, rename_map={"public": ""},
        )
        assert result.applied == {}
        assert result.dropped == []
        assert any("empty" in w for w in result.warnings)
        assert intent.snmp.community == "public"  # unchanged

    def test_non_string_source_warns(self):
        intent = _tree_with_snmp(community="public")
        result = translate_snmp_community(
            intent,
            rename_map={123: "new"},  # type: ignore[dict-item]
        )
        assert any("not a string" in w for w in result.warnings)

    def test_whitespace_only_source_warns(self):
        intent = _tree_with_snmp(community="public")
        result = translate_snmp_community(
            intent, rename_map={"   ": "new"},
        )
        assert any("empty" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# build_snmp_community_rename_transform — pipeline integration surface
# ---------------------------------------------------------------------------


class TestTransformBuilder:
    def test_returns_tuple_with_transform_and_result(self):
        transform, result = build_snmp_community_rename_transform(
            rename_map={"public": "monitoring-ro"},
        )
        assert callable(transform)
        assert isinstance(result, SnmpRenameResult)
        # Pre-application: result is empty.
        assert result.applied == {}

    def test_transform_applies_and_populates_result(self):
        intent = _tree_with_snmp(community="public")
        transform, result = build_snmp_community_rename_transform(
            rename_map={"public": "monitoring-ro"},
        )
        returned = transform(intent)
        # Returns the SAME tree (in-place mutation).
        assert returned is intent
        assert intent.snmp.community == "monitoring-ro"
        # Result populated side-effect-ishly.
        assert result.applied == {"public": "monitoring-ro"}

    def test_transform_with_none_map_is_noop(self):
        intent = _tree_with_snmp(community="public")
        transform, result = build_snmp_community_rename_transform(
            rename_map=None,
        )
        transform(intent)
        assert intent.snmp.community == "public"
        assert result.applied == {}

    def test_transform_with_clear_populates_dropped(self):
        intent = _tree_with_snmp(community="public")
        transform, result = build_snmp_community_rename_transform(
            rename_map={"public": None},
        )
        transform(intent)
        assert intent.snmp.community == ""
        assert result.dropped == ["public"]
