"""
Cross-adapter pipeline scenarios.

None of the cross-adapter combinations below represent a "meaningful"
real-world migration — that takes canonical YANG to bridge between
vendor-internal shapes, which arrives in Phase 1.  But running the
COMBINATIONS *exercises* stage transitions, error routing, and type
boundaries that no single-adapter test can reach on its own:

    * Does a render error surface as `failed` (not a 500)?
    * Does `validate.severity == block` correctly route to `partial`?
    * Does the class-guard actually block / permit / warn as designed?
    * Do the adapter-specific tree walkers get threaded through to
      `validate_against` correctly?

These tests are the safety net that catches the first FortiGate /
OPNsense adapter wiring up wrong when it arrives in Phase 1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from netconfig.migration.codecs._mock import MockCodec
from netconfig.migration.codecs.cisco_iosxe import CiscoIOSXECodec
from netconfig.models.migration import MigrationJobStatus
from netconfig.services.migration_pipeline import run_plan

pytestmark = pytest.mark.unit


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "iosxe" / "get_config_simple.xml"
)


# ---------------------------------------------------------------------------
# Self-to-self sanity checks (lock in stage transitions)
# ---------------------------------------------------------------------------


class TestSelfToSelf:
    """Each adapter compared to itself: pipeline must advance through
    every expected stage and reach a terminal state."""

    def test_iosxe_to_iosxe_reaches_completed(self):
        raw = FIXTURE.read_text()
        job = run_plan(CiscoIOSXECodec(), CiscoIOSXECodec(), raw)
        assert job.status is MigrationJobStatus.completed
        assert job.error is None
        assert job.rendered is not None
        assert job.completed_at is not None

    def test_iosxe_to_iosxe_validation_is_ok(self):
        raw = FIXTURE.read_text()
        job = run_plan(CiscoIOSXECodec(), CiscoIOSXECodec(), raw)
        assert job.validation is not None
        assert job.validation.severity == "ok"
        # Every supported path is populated (three interfaces, so ≥3).
        assert len(job.validation.supported_paths) >= 3

    def test_mock_to_mock_reaches_completed(self):
        raw = json.dumps({"/interfaces/eth0/ip": "10.0.0.1"})
        job = run_plan(MockCodec(), MockCodec(), raw)
        assert job.status is MigrationJobStatus.completed


# ---------------------------------------------------------------------------
# Cross-adapter: iosxe tree → mock renderer
# ---------------------------------------------------------------------------


class TestIosxeToMock:
    """IOS-XE parses into a nested dict ({'interfaces': {'interface': [...]}}).
    Mock renderer expects a FLAT dict[str, str] (xpath -> value).  Mock's
    `json.dumps` over the nested dict succeeds but the result doesn't
    round-trip; that's intentional — this test proves the pipeline
    handles "renders but produces garbage" and "renders AND lossy
    validation" gracefully in ALL branches."""

    def test_iosxe_to_mock_class_guard_permits(self):
        """IOS-XE declares [router, switch]; mock declares [switch, router].
        Non-empty intersection → not blocked by the class guard."""
        raw = FIXTURE.read_text()
        job = run_plan(CiscoIOSXECodec(), MockCodec(), raw)
        # Guard doesn't block → job doesn't contain the guard's error string.
        assert "Device-class guard" not in (job.error or "")

    def test_iosxe_to_mock_validation_classifies_iosxe_xpaths(self):
        """Mock's capability matrix only knows about four xpaths like
        `/interfaces/eth0/ip`.  IOS-XE's tree walker emits paths like
        `/interfaces/interface/config/description`.  Every iosxe xpath
        is therefore "unknown" to mock — classified as supported by
        default (matrix only declares exceptions)."""
        raw = FIXTURE.read_text()
        job = run_plan(CiscoIOSXECodec(), MockCodec(), raw)
        assert job.validation is not None
        # All iosxe paths pass through mock as "supported" (mock doesn't
        # declare any of them as lossy or unsupported).
        assert job.validation.severity == "ok"
        assert len(job.validation.lossy_paths) == 0
        assert len(job.validation.unsupported_paths) == 0

    def test_iosxe_to_mock_render_still_produces_output(self):
        """Mock's render does `json.dumps(tree, sort_keys=True)` which
        works on ANY JSON-serialisable dict.  So an iosxe tree gets
        serialised as a nested JSON document — not meaningful, but
        proves the pipeline doesn't crash on type mismatch."""
        raw = FIXTURE.read_text()
        job = run_plan(CiscoIOSXECodec(), MockCodec(), raw)
        assert job.status is MigrationJobStatus.completed
        assert job.rendered is not None
        # Output is JSON containing "interfaces".
        assert '"interfaces"' in job.rendered


# ---------------------------------------------------------------------------
# Cross-adapter: mock tree → iosxe renderer
# ---------------------------------------------------------------------------


class TestMockToIosxe:
    """Mock parses a flat dict[str, str].  IOS-XE renderer demands
    {'interfaces': {'interface': [...]}}.  This direction MUST produce
    a clean RenderError-routed `failed` status, not a 500 crash."""

    def test_mock_to_iosxe_render_failure_is_caught(self):
        raw = json.dumps({"/interfaces/eth0/ip": "10.0.0.1"})
        job = run_plan(MockCodec(), CiscoIOSXECodec(), raw)
        assert job.status is MigrationJobStatus.failed
        assert "render failed" in (job.error or "").lower()
        assert "interfaces" in (job.error or "").lower()

    def test_mock_to_iosxe_validation_ran_before_render(self):
        """Even though render fails, the validate stage runs first —
        iosxe's capability matrix classifies the (adapter-unknown)
        mock xpaths as supported, so validation.severity is ok.
        Job.validation should therefore be populated despite failure."""
        raw = json.dumps({"/interfaces/eth0/ip": "10.0.0.1"})
        job = run_plan(MockCodec(), CiscoIOSXECodec(), raw)
        assert job.validation is not None  # validate ran
        assert job.rendered is None        # but render did NOT complete

    def test_mock_to_iosxe_preserves_completed_at(self):
        """Every terminal state — including failure — must set
        completed_at so the UI can show a duration."""
        raw = json.dumps({"/interfaces/eth0/ip": "10.0.0.1"})
        job = run_plan(MockCodec(), CiscoIOSXECodec(), raw)
        assert job.completed_at is not None


# ---------------------------------------------------------------------------
# Adapter-aware walker threading
# ---------------------------------------------------------------------------


class TestAdapterAwareWalkerThreading:
    """Prove that `run_plan` actually passes `source` through to
    `validate_against` — which is what makes adapter-specific tree
    shapes work.  The evidence: a multi-interface iosxe tree yields
    the same xpath multiple times in the supported-paths list.  If
    the pipeline were still using the flat dict walker, it would only
    see the top-level key `interfaces` once."""

    def test_iosxe_walker_reaches_nested_leaves(self):
        raw = FIXTURE.read_text()
        job = run_plan(CiscoIOSXECodec(), CiscoIOSXECodec(), raw)
        assert job.validation is not None
        # Three interfaces, each with a description, prove the walker
        # descended into the list.  Flat-dict fallback would emit
        # "interfaces" ONCE (the top-level key) and nothing else.
        descr_count = job.validation.supported_paths.count(
            "/interfaces/interface/config/description"
        )
        assert descr_count == 3


# ---------------------------------------------------------------------------
# Partial status routing (validation block -> partial, not failed)
# ---------------------------------------------------------------------------


class TestPartialRouting:
    """A job whose RENDER succeeds but whose VALIDATION reported a block
    must land in `partial`, not `completed` or `failed`.  This is the
    subtle status-mapping the pipeline does at terminal time — tested
    explicitly so the rule doesn't silently regress when Phase 1 adds
    more terminal transitions."""

    def test_unsupported_path_in_mock_lands_partial(self):
        raw = json.dumps({"/unsafe/kernel_module": "badness"})
        job = run_plan(MockCodec(), MockCodec(), raw)
        assert job.status is MigrationJobStatus.partial
        assert job.rendered is not None  # still produced for review
        assert job.validation is not None
        assert job.validation.severity == "block"
        # Error message warns the output isn't safe to deploy as-is.
        assert "not be safe to deploy" in (job.error or "")


# ---------------------------------------------------------------------------
# Stage ordering: the class guard is STAGE 0 (runs before parse)
# ---------------------------------------------------------------------------


class TestStageOrdering:
    """Explicit coverage that the class guard runs BEFORE any parse
    work.  If the pipeline ever reorders stages, this test catches it."""

    def test_malformed_input_never_reaches_parser_when_classes_mismatch(self):
        """A disjoint-class pair + syntactically broken input: the
        job MUST fail with the class-guard error, not a parser error.
        If parse ran first we'd get 'malformed XML'; getting the
        class-guard message instead proves stage 0 is really first."""
        from tests.unit.migration.test_device_class import _make_adapter
        from netconfig.models.migration import DeviceClass

        sw = _make_adapter("sw_only", [DeviceClass.switch])
        fw = _make_adapter("fw_only", [DeviceClass.firewall])
        broken_xml = "<not>real</xml"
        job = run_plan(sw, fw, broken_xml)
        assert job.status is MigrationJobStatus.failed
        assert "Device-class guard" in (job.error or "")
        # Parser error string should NOT appear.
        assert "malformed" not in (job.error or "").lower()
