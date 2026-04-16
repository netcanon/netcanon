"""
Unit tests for ``netconfig.services.migration_validate``.

Exercises every branch of severity aggregation (ok / warn / block)
and the helper that classifies tree xpaths against a matrix.
"""

from __future__ import annotations

import pytest

from netconfig.migration.adapters._mock import MockAdapter
from netconfig.models.migration import (
    CapabilityMatrix,
    LossyPath,
    UnsupportedPath,
)
from netconfig.services.migration_validate import (
    classify_tree,
    validate_against,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# classify_tree helper
# ---------------------------------------------------------------------------


def _matrix() -> CapabilityMatrix:
    return CapabilityMatrix(
        adapter="t",
        supported=["/ok/a", "/ok/b"],
        lossy=[LossyPath(path="/lossy/x", reason="soft", severity="warn")],
        unsupported=[UnsupportedPath(path="/unsupp/y", reason="hard")],
    )


class TestClassifyTree:
    def test_empty_tree_returns_empty_lists(self):
        s, l, u = classify_tree({}, _matrix())
        assert s == [] and l == [] and u == []

    def test_non_dict_tree_yields_nothing(self):
        """Phase 0 only walks dict shapes; other shapes degrade silently."""
        s, l, u = classify_tree("not a dict", _matrix())
        assert s == [] and l == [] and u == []

    def test_supported_paths_sorted_to_first_bucket(self):
        tree = {"/ok/a": "v", "/ok/b": "v"}
        s, l, u = classify_tree(tree, _matrix())
        assert set(s) == {"/ok/a", "/ok/b"}

    def test_lossy_paths_return_full_objects(self):
        """classify_tree returns LossyPath objects (not bare strings)
        so callers can propagate the reason + severity."""
        s, l, u = classify_tree({"/lossy/x": "v"}, _matrix())
        assert len(l) == 1
        assert l[0].path == "/lossy/x"
        assert l[0].reason == "soft"

    def test_unsupported_paths_return_full_objects(self):
        s, l, u = classify_tree({"/unsupp/y": "v"}, _matrix())
        assert len(u) == 1
        assert u[0].path == "/unsupp/y"
        assert u[0].reason == "hard"

    def test_unknown_path_classified_as_supported(self):
        """Matrix only declares exceptions; unknowns are assumed safe."""
        s, l, u = classify_tree({"/new/path": "v"}, _matrix())
        assert "/new/path" in s


# ---------------------------------------------------------------------------
# validate_against severity aggregation
# ---------------------------------------------------------------------------


class TestValidateAgainst:
    """A clean tree → ok; lossy → warn; unsupported → block."""

    def test_all_supported_is_ok(self):
        tree = {
            "/interfaces/eth0/ip": "1",
            "/interfaces/eth0/description": "d",
        }
        report = validate_against(tree, MockAdapter())
        assert report.severity == "ok"
        assert report.compatible is True
        assert report.reasons == []
        assert len(report.supported_paths) == 2
        assert report.lossy_paths == []
        assert report.unsupported_paths == []

    def test_lossy_only_is_warn(self):
        tree = {"/legacy/deprecated": "v"}
        report = validate_against(tree, MockAdapter())
        assert report.severity == "warn"
        assert report.compatible is True
        assert len(report.lossy_paths) == 1
        assert any("lossy" in r for r in report.reasons)

    def test_unsupported_is_block(self):
        tree = {"/unsafe/kernel_module": "v"}
        report = validate_against(tree, MockAdapter())
        assert report.severity == "block"
        assert report.compatible is False
        assert len(report.unsupported_paths) == 1
        assert any("unsupported" in r for r in report.reasons)

    def test_error_severity_lossy_escalates_to_block(self):
        """A lossy path marked severity=error behaves like unsupported."""
        matrix = CapabilityMatrix(
            adapter="t",
            lossy=[
                LossyPath(path="/hard", reason="cannot verify", severity="error"),
            ],
        )

        class _FakeAdapter:
            name = "t"
            capabilities = matrix

        report = validate_against({"/hard": "v"}, _FakeAdapter())  # type: ignore[arg-type]
        assert report.severity == "block"
        assert report.compatible is False

    def test_mixed_lossy_and_unsupported_is_block(self):
        """A tree with both classes: severity is ``block`` (unsupported
        dominates).  Both finding-lists are populated so the UI can
        show the full picture, even though the banner focuses on the
        stricter class."""
        tree = {
            "/legacy/deprecated": "v",
            "/unsafe/kernel_module": "v",
        }
        report = validate_against(tree, MockAdapter())
        assert report.severity == "block"
        assert len(report.unsupported_paths) == 1
        assert len(report.lossy_paths) == 1
        # The primary banner reason mentions the hard block.
        assert any("unsupported" in r for r in report.reasons)

    def test_empty_tree_is_ok_with_no_findings(self):
        report = validate_against({}, MockAdapter())
        assert report.severity == "ok"
        assert report.supported_paths == []
