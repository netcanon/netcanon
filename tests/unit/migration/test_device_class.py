"""
Unit tests for the cross-device-class guardrail.

Covers:
    * ``DeviceClass`` enum shape.
    * ``CapabilityMatrix.device_classes`` field + MockCodec declaration.
    * ``check_class_compat`` service helper across every severity branch.
    * ``run_plan`` stage-0 guard (default behaviour + ``force=True`` override).
"""

from __future__ import annotations

import json

import pytest

from netconfig.migration.codecs._mock import MockCodec
from netconfig.migration.codecs.base import CodecBase
from netconfig.models.migration import (
    CapabilityMatrix,
    DeviceClass,
    MigrationJobStatus,
)
from netconfig.services.migration_pipeline import run_plan
from netconfig.services.migration_validate import check_class_compat

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helper — adapter stubs that declare specific device classes
# ---------------------------------------------------------------------------


class _StubCodec(CodecBase):
    """Concrete stub adapter whose class set is supplied at construction.

    Implements every abstract method so the ABC can be instantiated;
    the implementations are intentionally trivial — these tests only
    exercise the pipeline's class guard, never parse/render logic.
    """

    name = "stub"  # overridden per-instance below

    def __init__(self, name: str, classes: list[DeviceClass]) -> None:
        self._name = name
        self._caps = CapabilityMatrix(adapter=name, device_classes=classes)

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._caps

    def parse(self, raw: str) -> dict:
        return {}

    def render(self, tree) -> str:
        return ""


def _make_adapter(
    name: str, classes: list[DeviceClass]
) -> CodecBase:
    """Build a lightweight adapter for compat-check tests."""
    a = _StubCodec(name, classes)
    # Bypass the class-level `name` ClassVar so `check_class_compat`
    # reads the instance-specific value through ``capabilities.adapter``
    # (which is what the compat check actually uses).
    return a


# ---------------------------------------------------------------------------
# DeviceClass enum
# ---------------------------------------------------------------------------


class TestDeviceClassEnum:
    def test_all_expected_members_present(self):
        expected = {
            "switch", "router", "firewall", "load_balancer",
            "wireless_controller", "access_point", "waf",
        }
        assert {c.value for c in DeviceClass} == expected

    def test_is_string_enum(self):
        """DeviceClass members compare equal to their string values so
        the JSON (de)serialisation on the API boundary is trivial."""
        assert DeviceClass.switch == "switch"
        assert DeviceClass.firewall.value == "firewall"


# ---------------------------------------------------------------------------
# CapabilityMatrix field
# ---------------------------------------------------------------------------


class TestCapabilityMatrixDeviceClasses:
    def test_default_is_empty_list(self):
        """No classes declared — "uncommitted" adapter."""
        m = CapabilityMatrix(adapter="test")
        assert m.device_classes == []

    def test_accepts_enum_members(self):
        m = CapabilityMatrix(
            adapter="t", device_classes=[DeviceClass.switch]
        )
        assert m.device_classes == [DeviceClass.switch]

    def test_accepts_string_values_via_pydantic_coercion(self):
        """Pydantic coerces string values to enum members — useful for
        capabilities.yaml loading in Phase 1."""
        m = CapabilityMatrix(
            adapter="t", device_classes=["switch", "router"]  # type: ignore[list-item]
        )
        assert DeviceClass.switch in m.device_classes
        assert DeviceClass.router in m.device_classes

    def test_mock_adapter_declares_switch_and_router(self):
        """MockCodec is multi-class on purpose so tests can exercise
        the intersection logic."""
        caps = MockCodec().capabilities
        assert DeviceClass.switch in caps.device_classes
        assert DeviceClass.router in caps.device_classes


# ---------------------------------------------------------------------------
# check_class_compat severity matrix
# ---------------------------------------------------------------------------


class TestCheckClassCompat:
    def test_identical_classes_is_ok(self):
        a = _make_adapter("a", [DeviceClass.switch])
        b = _make_adapter("b", [DeviceClass.switch])
        report = check_class_compat(a, b)
        assert report.compatible is True
        assert report.severity == "ok"
        assert report.reasons == []

    def test_overlapping_multi_class_is_ok(self):
        """L3 switch (switch+router) → pure router: intersection = {router}."""
        l3_switch = _make_adapter("l3", [DeviceClass.switch, DeviceClass.router])
        router = _make_adapter("r", [DeviceClass.router])
        assert check_class_compat(l3_switch, router).severity == "ok"

    def test_disjoint_classes_is_block(self):
        """Switch → Firewall: no common class, guard refuses."""
        sw = _make_adapter("sw", [DeviceClass.switch])
        fw = _make_adapter("fw", [DeviceClass.firewall])
        report = check_class_compat(sw, fw)
        assert report.compatible is False
        assert report.severity == "block"
        assert any("mismatch" in r.lower() for r in report.reasons)

    def test_neither_declares_is_warn(self):
        """Two uncommitted adapters — allowed but flagged."""
        a = _make_adapter("a", [])
        b = _make_adapter("b", [])
        report = check_class_compat(a, b)
        assert report.compatible is True
        assert report.severity == "warn"
        assert any("Neither" in r for r in report.reasons)

    def test_only_source_undeclared_is_warn(self):
        src = _make_adapter("src", [])
        tgt = _make_adapter("tgt", [DeviceClass.router])
        report = check_class_compat(src, tgt)
        assert report.severity == "warn"
        assert any("Source" in r for r in report.reasons)

    def test_only_target_undeclared_is_warn(self):
        src = _make_adapter("src", [DeviceClass.switch])
        tgt = _make_adapter("tgt", [])
        report = check_class_compat(src, tgt)
        assert report.severity == "warn"
        assert any("Target" in r for r in report.reasons)

    def test_block_reason_surfaces_both_classes(self):
        """The UI banner needs to tell the user WHICH classes clashed."""
        sw = _make_adapter("sw", [DeviceClass.switch])
        fw = _make_adapter("fw", [DeviceClass.firewall])
        report = check_class_compat(sw, fw)
        joined = " ".join(report.reasons)
        assert "switch" in joined
        assert "firewall" in joined


# ---------------------------------------------------------------------------
# run_plan stage-0 guard
# ---------------------------------------------------------------------------


class TestRunPlanClassGuard:
    def test_compatible_pair_proceeds_normally(self):
        """Mock adapter is multi-class (switch+router); self-pair is OK."""
        job = run_plan(MockCodec(), MockCodec(), "{}")
        assert job.status is MigrationJobStatus.completed
        assert job.error is None

    def test_disjoint_classes_fails_before_parse(self):
        """The guard runs BEFORE parse, so a malformed raw_text
        wouldn't even be reached — use that as the signal."""
        # Source is switch-only; target is firewall-only.
        sw = _make_adapter("sw", [DeviceClass.switch])
        # Stub adapter's parse always returns {}, so we can't detect
        # "parse never ran" via a parse error.  Instead, check the
        # error message — the class-guard message is unmistakable.
        fw = _make_adapter("fw", [DeviceClass.firewall])
        job = run_plan(sw, fw, "this would fail parsing if we reached it")
        assert job.status is MigrationJobStatus.failed
        assert "Device-class guard" in (job.error or "")
        # Mentions both sides so the user knows which to fix.
        assert "switch" in (job.error or "")
        assert "firewall" in (job.error or "")

    def test_force_true_overrides_the_guard(self):
        """Deliberate cross-class experiments are legit — force=True skips the guard."""
        sw = _make_adapter("sw", [DeviceClass.switch])
        fw = _make_adapter("fw", [DeviceClass.firewall])
        # Even forced, the parser for the stub accepts any string and
        # returns {}, so the run should reach completed.
        job = run_plan(sw, fw, "irrelevant", force=True)
        assert job.status is MigrationJobStatus.completed
        assert job.error is None

    def test_block_job_has_completed_at(self):
        sw = _make_adapter("sw", [DeviceClass.switch])
        fw = _make_adapter("fw", [DeviceClass.firewall])
        job = run_plan(sw, fw, "{}")
        assert job.completed_at is not None

    def test_undeclared_adapter_is_not_blocked(self):
        """Uncommitted adapters get a warn, not a block — useful while
        adapter capability sets are still being mapped out."""
        a = _make_adapter("a", [])
        b = _make_adapter("b", [])
        job = run_plan(a, b, "{}")
        # A stub adapter's parse returns {}; pipeline reaches completion.
        assert job.status is MigrationJobStatus.completed

    def test_force_flag_has_no_side_effects_when_already_compatible(self):
        """force=True on a pair that would have passed anyway is a no-op."""
        raw = json.dumps({"/interfaces/eth0/ip": "1.1.1.1"})
        unforced = run_plan(MockCodec(), MockCodec(), raw, force=False)
        forced = run_plan(MockCodec(), MockCodec(), raw, force=True)
        assert unforced.status == forced.status == MigrationJobStatus.completed
