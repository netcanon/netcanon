"""
Unit tests for the stateless diff service (``netcanon.services.diff``).

These tests feed synthetic inputs directly to ``compute_diff`` and
``check_compatibility`` — no HTTP, no tmp filesystem, no FastAPI.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from netcanon.models.backup import ConfigRecord
from netcanon.models.diff import DiffLine
from netcanon.services.diff import check_compatibility, compute_diff, fold_context

pytestmark = pytest.mark.unit


def _record(
    device_type: str = "Cisco",
    ext: str = "cfg",
    host: str = "10.0.0.1",
    filename: str | None = None,
) -> ConfigRecord:
    return ConfigRecord(
        device_type=device_type,
        host=host,
        timestamp=datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc),
        filename=filename or f"{device_type}_{host}_20260416_120000.{ext}",
        file_extension=ext,
        size_bytes=100,
    )


# ---------------------------------------------------------------------------
# check_compatibility
# ---------------------------------------------------------------------------


class TestCheckCompatibility:
    def test_same_type_and_extension_is_ok(self):
        r = check_compatibility(_record(), _record())
        assert r.compatible is True
        assert r.severity == "ok"
        assert r.reasons == []

    def test_different_type_key_is_block(self):
        r = check_compatibility(_record("Cisco"), _record("Fortigate"))
        assert r.compatible is False
        assert r.severity == "block"
        assert any("type_key" in s for s in r.reasons)

    def test_different_extension_is_block(self):
        r = check_compatibility(_record(ext="cfg"), _record(ext="xml"))
        assert r.compatible is False
        assert r.severity == "block"
        assert any("file_extension" in s for s in r.reasons)

    def test_both_mismatched_surfaces_both_reasons(self):
        r = check_compatibility(
            _record("Cisco", "cfg"), _record("OPNsense", "xml")
        )
        assert len(r.reasons) == 2
        assert any("type_key" in s for s in r.reasons)
        assert any("file_extension" in s for s in r.reasons)


# ---------------------------------------------------------------------------
# compute_diff
# ---------------------------------------------------------------------------


class TestComputeDiff:
    def test_identical_text_is_all_equal(self):
        text = "line one\nline two\nline three\n"
        report = compute_diff(_record(), text, _record(), text)
        assert report.stats == {"added": 0, "removed": 0, "equal": 3}
        assert all(L.kind == "equal" for L in report.lines)
        # Line numbers are 1-based and aligned on both sides.
        assert [L.left_no for L in report.lines] == [1, 2, 3]
        assert [L.right_no for L in report.lines] == [1, 2, 3]

    def test_pure_addition_produces_add_lines_only(self):
        left = "a\nb\n"
        right = "a\nb\nc\n"
        report = compute_diff(_record(), left, _record(), right)
        assert report.stats == {"added": 1, "removed": 0, "equal": 2}
        added = [L for L in report.lines if L.kind == "add"]
        assert len(added) == 1
        assert added[0].text == "c"
        assert added[0].left_no is None
        assert added[0].right_no == 3

    def test_pure_deletion_produces_remove_lines_only(self):
        left = "a\nb\nc\n"
        right = "a\nc\n"
        report = compute_diff(_record(), left, _record(), right)
        assert report.stats["removed"] == 1
        assert report.stats["added"] == 0
        removed = [L for L in report.lines if L.kind == "remove"]
        assert removed[0].text == "b"
        assert removed[0].left_no == 2
        assert removed[0].right_no is None

    def test_replace_emits_remove_then_add(self):
        left = "a\nOLD\nc\n"
        right = "a\nNEW\nc\n"
        report = compute_diff(_record(), left, _record(), right)
        kinds = [L.kind for L in report.lines]
        # Order must be: equal, remove, add, equal.
        assert kinds == ["equal", "remove", "add", "equal"]
        assert report.stats == {"added": 1, "removed": 1, "equal": 2}

    def test_force_flag_annotates_compat_reasons_when_blocked(self):
        left_text = "a\n"
        right_text = "a\n"
        report = compute_diff(
            _record("Cisco", "cfg"),
            left_text,
            _record("Fortigate", "conf"),
            right_text,
            force=True,
        )
        assert report.compatibility.compatible is False
        assert report.compatibility.severity == "block"
        assert any("force=true" in s for s in report.compatibility.reasons)

    def test_force_is_inert_when_already_compatible(self):
        report = compute_diff(
            _record(), "a\n", _record(), "a\n", force=True
        )
        assert report.compatibility.compatible is True
        assert report.compatibility.severity == "ok"
        # No force-override breadcrumb on a compatible pair.
        assert not any("force=true" in s for s in report.compatibility.reasons)

    def test_empty_inputs_are_handled(self):
        report = compute_diff(_record(), "", _record(), "")
        assert report.lines == []
        assert report.stats == {"added": 0, "removed": 0, "equal": 0}

    def test_trailing_newline_does_not_inflate_line_count(self):
        """``splitlines`` is used so a trailing ``\\n`` doesn't produce a
        phantom empty last line."""
        report = compute_diff(_record(), "a\nb\n", _record(), "a\nb\n")
        assert report.stats["equal"] == 2


# ---------------------------------------------------------------------------
# fold_context — collapsed-context grouping for the rendered diff view
# ---------------------------------------------------------------------------


def _equal_line(i: int) -> DiffLine:
    """Manufacture an equal-kind DiffLine with synthetic line numbers."""
    return DiffLine(kind="equal", left_no=i, right_no=i, text=f"line {i}")


def _add_line(i: int) -> DiffLine:
    return DiffLine(kind="add", left_no=None, right_no=i, text=f"add {i}")


def _remove_line(i: int) -> DiffLine:
    return DiffLine(kind="remove", left_no=i, right_no=None, text=f"remove {i}")


class TestFoldContext:
    """``fold_context`` collapses equal runs that are far from any change."""

    def test_empty_input_returns_empty_list(self):
        assert fold_context([]) == []

    def test_all_equal_is_one_collapsed_group(self):
        """No changes anywhere → every line is cold → one collapsed group."""
        lines = [_equal_line(i) for i in range(1, 11)]
        groups = fold_context(lines, context=3)
        assert len(groups) == 1
        assert groups[0].kind == "collapsed"
        assert len(groups[0].lines) == 10

    def test_all_changes_are_all_visible(self):
        """Zero equal lines → every line is a change → no collapsed groups."""
        lines = [_add_line(i) for i in range(1, 6)]
        groups = fold_context(lines, context=3)
        assert len(groups) == 5
        assert all(g.kind == "add" for g in groups)

    def test_context_kept_on_both_sides_of_change(self):
        """A change at index 10 with context=3 must keep indices 7..13 visible."""
        lines = []
        for i in range(1, 21):  # 20 equal lines
            lines.append(_equal_line(i))
        lines[10] = _add_line(11)  # swap the 11th line for a change
        groups = fold_context(lines, context=3)
        # The visible window around index 10 is 7..13 (7 lines).  Indices
        # 0..6 form one collapsed group (7 lines); 14..19 form another
        # (6 lines).  Visible groups in between: 6 equal + 1 add = 7.
        # Structure: collapsed, 3× equal, add, 3× equal, collapsed.
        kinds = [g.kind for g in groups]
        assert kinds == [
            "collapsed", "equal", "equal", "equal",
            "add",
            "equal", "equal", "equal", "collapsed",
        ]
        assert len(groups[0].lines) == 7
        assert len(groups[-1].lines) == 6

    def test_adjacent_changes_within_context_do_not_collapse_between(self):
        """Two changes separated by <=2*context equal lines never form a
        collapsed group in between — git's standard context behaviour."""
        lines = [
            _equal_line(1), _equal_line(2),
            _add_line(3),
            _equal_line(4), _equal_line(5), _equal_line(6),
            _remove_line(7),
            _equal_line(8), _equal_line(9),
        ]
        groups = fold_context(lines, context=3)
        # All 9 lines are within context of a change → no collapse.
        assert all(g.kind != "collapsed" for g in groups)
        assert len(groups) == 9

    def test_tight_context_yields_more_collapsing(self):
        """context=0 only keeps changes + no equal lines visible."""
        lines = [
            _equal_line(1), _equal_line(2), _equal_line(3),
            _add_line(4),
            _equal_line(5), _equal_line(6), _equal_line(7),
        ]
        groups = fold_context(lines, context=0)
        # Collapsed-add-collapsed.
        assert [g.kind for g in groups] == ["collapsed", "add", "collapsed"]
        assert len(groups[0].lines) == 3
        assert len(groups[2].lines) == 3

    def test_negative_context_rejected(self):
        with pytest.raises(ValueError):
            fold_context([_equal_line(1)], context=-1)

    def test_default_context_is_three(self):
        """Default matches git / unified-diff convention (3 lines)."""
        lines = [_equal_line(i) for i in range(1, 11)]
        lines[5] = _add_line(6)
        default = fold_context(lines)
        explicit = fold_context(lines, context=3)
        assert [g.kind for g in default] == [g.kind for g in explicit]

    def test_hidden_lines_preserved_in_order(self):
        """Collapsed groups retain their lines verbatim — critical because
        the template stashes them in a <template> for click-to-expand."""
        lines = [_equal_line(i) for i in range(1, 21)]
        lines[10] = _add_line(11)
        groups = fold_context(lines, context=3)
        collapsed = [g for g in groups if g.kind == "collapsed"]
        assert len(collapsed) == 2
        # Leading collapse covers indices 0..6 of the original list.
        assert collapsed[0].lines == lines[0:7]
        # Trailing collapse covers indices 14..19.
        assert collapsed[1].lines == lines[14:20]
