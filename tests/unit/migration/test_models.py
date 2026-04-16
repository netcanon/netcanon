"""
Unit tests for ``netconfig.models.migration``.

Covers the pydantic validation + the ``CapabilityMatrix.classify``
resolution rules.  No service-layer or adapter code is exercised
here.
"""

from __future__ import annotations

import pytest

from netconfig.models.migration import (
    AdapterInfo,
    CapabilityMatrix,
    LossyPath,
    MigrationJob,
    MigrationJobStatus,
    TransformSpec,
    UnsupportedPath,
    ValidationReport,
    XPathDelta,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# CapabilityMatrix.classify
# ---------------------------------------------------------------------------


class TestCapabilityMatrixClassify:
    """``classify`` applies strictest-wins resolution."""

    def _matrix(self) -> CapabilityMatrix:
        return CapabilityMatrix(
            adapter="test",
            supported=["/a", "/b"],
            lossy=[LossyPath(path="/c", reason="lossy c")],
            unsupported=[UnsupportedPath(path="/d", reason="nope")],
        )

    def test_explicit_unsupported_wins(self):
        assert self._matrix().classify("/d") == "unsupported"

    def test_explicit_lossy_wins_over_default(self):
        assert self._matrix().classify("/c") == "lossy"

    def test_unknown_path_defaults_to_supported(self):
        """Matrix authors only need to declare exceptions."""
        assert self._matrix().classify("/anything/else") == "supported"

    def test_explicit_supported_path(self):
        assert self._matrix().classify("/a") == "supported"

    def test_empty_matrix_treats_everything_as_supported(self):
        empty = CapabilityMatrix(adapter="t")
        assert empty.classify("/literally/anything") == "supported"

    def test_strictest_wins_even_with_overlapping_entries(self):
        """If someone accidentally puts the same path in two lists the
        stricter classification must win."""
        m = CapabilityMatrix(
            adapter="t",
            lossy=[LossyPath(path="/x", reason="soft")],
            unsupported=[UnsupportedPath(path="/x", reason="hard")],
        )
        assert m.classify("/x") == "unsupported"


# ---------------------------------------------------------------------------
# LossyPath / UnsupportedPath
# ---------------------------------------------------------------------------


class TestLeafTypes:
    def test_lossy_default_severity_is_warn(self):
        assert LossyPath(path="/x", reason="r").severity == "warn"

    def test_lossy_severity_can_be_error(self):
        lp = LossyPath(path="/x", reason="r", severity="error")
        assert lp.severity == "error"

    def test_unsupported_reason_is_optional(self):
        up = UnsupportedPath(path="/x")
        assert up.reason is None


# ---------------------------------------------------------------------------
# ValidationReport + XPathDelta shape
# ---------------------------------------------------------------------------


class TestValidationReport:
    def test_ok_report(self):
        r = ValidationReport(compatible=True, severity="ok")
        assert r.supported_paths == []
        assert r.lossy_paths == []
        assert r.unsupported_paths == []

    def test_severity_literal_enforced(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ValidationReport(compatible=False, severity="nope")  # type: ignore[arg-type]


class TestXPathDelta:
    def test_kind_literal(self):
        d = XPathDelta(xpath="/a", kind="added")
        assert d.kind == "added"

    def test_severity_defaults_to_info(self):
        d = XPathDelta(xpath="/a", kind="changed")
        assert d.severity == "info"


# ---------------------------------------------------------------------------
# MigrationJob + MigrationJobStatus
# ---------------------------------------------------------------------------


class TestMigrationJob:
    def test_defaults(self):
        j = MigrationJob(source_adapter="src", target_adapter="tgt")
        assert j.status is MigrationJobStatus.pending
        assert j.transforms == []
        assert j.completed_at is None
        assert j.validation is None
        assert j.rendered is None
        # id is a UUID4 hex string of the standard length.
        assert len(j.id) == 36

    def test_unique_ids_across_instances(self):
        a = MigrationJob(source_adapter="s", target_adapter="t")
        b = MigrationJob(source_adapter="s", target_adapter="t")
        assert a.id != b.id


class TestMigrationJobStatus:
    def test_all_states_present(self):
        expected = {
            "pending", "parsing", "transforming", "validating",
            "rendering", "diffing", "awaiting_approval",
            "snapshotting", "deploying",
            "completed", "partial", "failed",
        }
        assert {s.value for s in MigrationJobStatus} == expected

    def test_str_enum(self):
        assert MigrationJobStatus.pending == "pending"


# ---------------------------------------------------------------------------
# TransformSpec + AdapterInfo shape
# ---------------------------------------------------------------------------


class TestTransformSpec:
    def test_default_args_is_empty_dict(self):
        t = TransformSpec(name="rename_interfaces")
        assert t.args == {}

    def test_args_can_hold_arbitrary_json(self):
        t = TransformSpec(name="remap_vlans", args={"10": 100, "20": 200})
        assert t.args["10"] == 100


class TestAdapterInfo:
    def test_counts_are_required(self):
        info = AdapterInfo(
            name="mock",
            version_range="1.x",
            supported_count=4,
            lossy_count=1,
            unsupported_count=1,
        )
        assert info.name == "mock"
        assert info.supported_count == 4
