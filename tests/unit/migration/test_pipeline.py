"""
Unit tests for ``netconfig.services.migration_pipeline.run_plan``.

Phase 0 pipeline: parse → transform → validate → render.  No collect
(caller supplies ``raw_text``), no diff, no deploy, no snapshot.
"""

from __future__ import annotations

import json

import pytest

from netconfig.migration.codecs._mock import MockCodec
from netconfig.models.migration import (
    MigrationJobStatus,
    TransformSpec,
)
from netconfig.services.migration_pipeline import run_plan

pytestmark = pytest.mark.unit


class TestRunPlanHappyPath:
    def test_minimal_roundtrip_reaches_completed(self):
        src = MockCodec()
        tgt = MockCodec()
        raw = json.dumps({"/interfaces/eth0/ip": "10.0.0.1"})
        job = run_plan(src, tgt, raw)
        assert job.status is MigrationJobStatus.completed
        assert job.error is None
        assert job.rendered is not None
        assert job.validation is not None
        assert job.validation.severity == "ok"
        assert job.completed_at is not None

    def test_rendered_output_roundtrips_back_through_source(self):
        """render() output must be parseable by the same adapter."""
        src = MockCodec()
        tgt = MockCodec()
        raw = json.dumps({"/interfaces/eth0/ip": "10.0.0.1"})
        job = run_plan(src, tgt, raw)
        assert job.rendered is not None
        reparsed = src.parse(job.rendered)
        assert reparsed == {"/interfaces/eth0/ip": "10.0.0.1"}

    def test_job_records_source_and_target_names(self):
        job = run_plan(MockCodec(), MockCodec(), "{}")
        assert job.source_codec == "mock"
        assert job.target_codec == "mock"


class TestRunPlanTransforms:
    def test_transforms_applied_in_order(self):
        """Transforms are applied as an ordered chain."""
        call_order: list[str] = []

        def first(tree):
            call_order.append("first")
            tree = dict(tree)
            tree["/seen_by_first"] = "yes"
            return tree

        def second(tree):
            call_order.append("second")
            tree = dict(tree)
            tree["/seen_by_second"] = "yes"
            return tree

        job = run_plan(
            MockCodec(), MockCodec(), "{}",
            transforms=[first, second],
        )
        assert call_order == ["first", "second"]
        # The final rendered tree contains both transform markers.
        final = MockCodec().parse(job.rendered or "")
        assert final == {"/seen_by_first": "yes", "/seen_by_second": "yes"}

    def test_transform_specs_recorded_on_job(self):
        """Caller-supplied specs are kept on the job for audit trails."""
        specs = [
            TransformSpec(name="rename_interfaces", args={"eth0": "ether1"}),
        ]
        job = run_plan(
            MockCodec(), MockCodec(), "{}",
            transforms=[lambda t: t],
            transform_specs=specs,
        )
        assert job.transforms == specs

    def test_transform_raising_marks_job_failed(self):
        def exploder(tree):
            raise RuntimeError("boom")

        job = run_plan(
            MockCodec(), MockCodec(), "{}", transforms=[exploder]
        )
        assert job.status is MigrationJobStatus.failed
        assert "boom" in (job.error or "")


class TestRunPlanFailures:
    def test_parse_error_marks_job_failed(self):
        job = run_plan(MockCodec(), MockCodec(), "not valid json")
        assert job.status is MigrationJobStatus.failed
        assert "parse failed" in (job.error or "")
        # Validation + render never happened.
        assert job.validation is None
        assert job.rendered is None

    def test_validation_block_marks_job_partial_not_failed(self):
        """An unsupported path is a USER-caught issue, not a crash.

        The pipeline still renders (so the UI can show the user what
        would have been emitted) but flags the result as ``partial``
        so downstream code won't auto-deploy it.
        """
        raw = json.dumps({"/unsafe/kernel_module": "rootkit.ko"})
        job = run_plan(MockCodec(), MockCodec(), raw)
        assert job.status is MigrationJobStatus.partial
        assert job.validation is not None
        assert job.validation.severity == "block"
        assert job.rendered is not None  # still produced for review

    def test_failed_job_still_has_completed_at(self):
        job = run_plan(MockCodec(), MockCodec(), "not valid json")
        assert job.completed_at is not None
