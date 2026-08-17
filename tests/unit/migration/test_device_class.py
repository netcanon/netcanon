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

from netcanon.migration.codecs._mock import MockCodec
from netcanon.migration.codecs.base import CodecBase
from netcanon.migration.codecs.registry import get_codec, list_codecs
from netcanon.models.migration import (
    CapabilityMatrix,
    DeviceClass,
    MigrationJobStatus,
)
from netcanon.services.migration_pipeline import run_plan
from netcanon.services.migration_validate import check_class_compat, check_scope_advisory

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


class TestScopeAdvisory:
    """``check_scope_advisory`` — the firewall-target NOTICE (not a gate).

    Deliberately a separate function from ``check_class_compat``: three of
    that function's arms already return ``severity="warn"`` for "an adapter
    declared no device_classes", so a caller demuxing on severity alone would
    render those under this advisory's heading.  See the comment above
    ``check_class_compat``'s final return.
    """

    def test_fires_switch_source_into_firewall_target(self):
        rep = check_scope_advisory(
            get_codec("cisco_iosxe_cli"), get_codec("fortigate_cli")
        )
        assert rep is not None
        assert rep.compatible is True, "an advisory must never refuse the job"
        assert rep.severity == "warn"
        assert len(rep.reasons) == 2

    @pytest.mark.parametrize("target_name", ["fortigate_cli", "opnsense"])
    def test_every_non_firewall_source_advises_on_both_firewall_targets(
        self, target_name
    ):
        target = get_codec(target_name)
        fired = [
            name
            for name in list_codecs()
            if check_scope_advisory(get_codec(name), target) is not None
        ]
        assert "fortigate_cli" not in fired
        assert "opnsense" not in fired
        assert len(fired) == len(list_codecs()) - 2

    @pytest.mark.parametrize("target_name", ["mikrotik_routeros", "vyos", "juniper_junos"])
    def test_secondary_firewall_targets_do_not_advise(self, target_name):
        """R1 regression.

        These three declare ``firewall`` but not FIRST, so they are full-scope
        router/switch platforms.  A membership test (``firewall in tgt``)
        misfires on every one of them -- that was the plan's original bug.
        """
        rep = check_scope_advisory(
            get_codec("cisco_iosxe_cli"), get_codec(target_name)
        )
        assert rep is None

    def test_firewall_to_firewall_does_not_advise(self):
        """That direction is not silent: the source codec's Tier-3 detector
        already names the lost policy stanzas in ``dropped_tier3_sections``.
        """
        assert check_scope_advisory(get_codec("opnsense"), get_codec("fortigate_cli")) is None
        assert check_scope_advisory(get_codec("fortigate_cli"), get_codec("opnsense")) is None

    def test_binding_phrase_is_per_target_not_generic(self):
        """Naming FortiOS syntax on an OPNsense job would be a small,
        falsifiable error of exactly the kind this wave exists to remove.
        """
        fg = check_scope_advisory(get_codec("cisco_iosxe_cli"), get_codec("fortigate_cli"))
        opn = check_scope_advisory(get_codec("cisco_iosxe_cli"), get_codec("opnsense"))
        assert "set srcintf" in fg.reasons[1]
        assert "set srcintf" not in opn.reasons[1]
        assert "<interface>" in opn.reasons[1]

    def test_advisory_makes_no_security_posture_claim(self):
        """Binding retraction: both platforms fail CLOSED (FortiOS transit
        needs an explicit policy; OPNsense pf blocks WAN ingress by default),
        so any "no security posture" / "traffic is permitted" framing is
        falsifiable.  The defensible mechanisms are rebinding and silence.
        """
        for target in ("fortigate_cli", "opnsense"):
            text = " ".join(
                check_scope_advisory(get_codec("cisco_iosxe_cli"), get_codec(target)).reasons
            ).lower()
            for banned in ("security posture", "wide open", "permits all", "unprotected"):
                assert banned not in text, f"{target}: advisory must not claim {banned!r}"

    def test_class_guard_still_blocks_disjoint_pairs(self):
        """R2 regression.

        The advisory lives OUTSIDE ``check_class_compat`` precisely so it can
        never shadow the block arm.  A switch-only source against a
        firewall-only target must still be refused.
        """
        src = _StubCodec("switch_only", [DeviceClass.switch])
        tgt = _StubCodec("firewall_only", [DeviceClass.firewall])
        assert check_class_compat(src, tgt).severity == "block"
        assert check_scope_advisory(src, tgt) is not None


class TestScopeAdvisoryReachesTheJob:
    """R3 -- the advisory must be attached to the job, not computed and lost."""

    def test_run_plan_attaches_the_advisory_without_changing_status(self):
        job = run_plan(
            get_codec("cisco_iosxe_cli"),
            get_codec("fortigate_cli"),
            "hostname edge-01\n!\ninterface GigabitEthernet0/0\n ip address 10.0.0.1 255.255.255.0\n",
        )
        assert len(job.scope_advisories) == 2
        assert job.status is not MigrationJobStatus.failed
        assert job.rendered is not None, "an advisory must not suppress the render"

    def test_advisory_does_not_leak_into_the_rename_warning_channel(self):
        """``job.warnings`` is a port-rename side-channel: every UI consumer
        treats an entry as a renameable port name, and one carrying quotes
        renders as a phantom interface row.  The advisory must not go there.
        """
        job = run_plan(
            get_codec("cisco_iosxe_cli"),
            get_codec("fortigate_cli"),
            "hostname edge-01\n!\ninterface GigabitEthernet0/0\n ip address 10.0.0.1 255.255.255.0\n",
        )
        assert job.warnings == []

    def test_switch_to_switch_job_carries_no_advisory(self):
        job = run_plan(
            get_codec("cisco_iosxe_cli"),
            get_codec("juniper_junos"),
            "hostname access-01\n!\nvlan 10\n name DATA\n",
        )
        assert job.scope_advisories == []
