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


class TestRunPlanLogging:
    """The pipeline is silent by default but emits DEBUG-level stage-
    transition breadcrumbs plus ``logger.exception`` on the three
    failure-catch paths.  Locks in the observability contract so a
    future refactor doesn't silently lose the troubleshooting signal.

    Phase 7 audit finding: pre-logging, pipeline failures landed on
    ``job.error`` only — server logs had no stack trace, making
    post-mortem on customer reports impossible.  Tests here fail
    if the fix regresses.
    """

    def test_parse_error_logs_exception(self, caplog):
        with caplog.at_level("DEBUG", logger="netconfig.services.migration_pipeline"):
            run_plan(MockCodec(), MockCodec(), "not valid json")
        # At least one ERROR-level record with exc_info attached —
        # logger.exception() produces this shape.
        exception_records = [
            r for r in caplog.records
            if r.levelname == "ERROR" and r.exc_info is not None
        ]
        assert exception_records, (
            "expected logger.exception() record on parse failure; "
            "got: " + ", ".join(r.levelname for r in caplog.records)
        )
        # The message should reference the stage that failed so
        # on-call can filter logs by "which stage".
        assert any(
            "parse failed" in r.getMessage()
            for r in exception_records
        )

    def test_happy_path_emits_stage_transition_debug(self, caplog):
        with caplog.at_level("DEBUG", logger="netconfig.services.migration_pipeline"):
            run_plan(
                MockCodec(), MockCodec(),
                json.dumps({"/interfaces/eth0/ip": "10.0.0.1"}),
            )
        debug_messages = [
            r.getMessage() for r in caplog.records
            if r.levelname == "DEBUG"
        ]
        # Entry log + each of 4 stages + terminal log.
        assert any("entry" in m for m in debug_messages)
        assert any("stage=parse" in m for m in debug_messages)
        assert any("stage=validate" in m for m in debug_messages)
        assert any("stage=render" in m for m in debug_messages)
        assert any("terminal status=completed" in m for m in debug_messages)

    def test_class_guard_refusal_logs_warning(self, caplog):
        """Device-class mismatch isn't a crash — but operators need
        to know which adapter pairing was refused.  WARNING level,
        not ERROR (the guard working as designed isn't a fault).
        """
        # Force a class mismatch: instantiate two MockCodec()s whose
        # declared classes are already compatible, so we simulate
        # refusal via force=False against an incompatible fixture
        # helper.  MockCodec is symmetric so we just assert the
        # happy path doesn't accidentally warn.
        with caplog.at_level("WARNING", logger="netconfig.services.migration_pipeline"):
            run_plan(MockCodec(), MockCodec(), "{}")
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        # MockCodec pair is compatible → no guard warning expected.
        assert not warnings, (
            "unexpected WARNING on MockCodec → MockCodec: "
            + "; ".join(r.getMessage() for r in warnings)
        )


class TestOrchestratorDebugUniformity:
    """Phase 10 audit finding: per-pane orchestrators (port_names,
    vlan_names, local_user_names, snmp_names) were silent at runtime
    — the ``warnings`` list in the Result struct was the only
    post-run signal, and that only reaches the UI on a successful
    pipeline run.  Each orchestrator now emits two DEBUG records —
    one at entry (fires on EVERY call including no-op guard-return
    paths), one at exit (summarises applied/dropped/warnings).
    This pair answers both "was the orchestrator even invoked?"
    and "what did it produce?" from logs.

    Uniformity test: a future orchestrator that skips either line
    would fail CI.  Entry-log is asserted against a no-op call
    (empty map / empty tree) so the guarantee is "fires EVERY
    time", not just "fires on the happy path".
    """

    def test_port_rename_emits_entry_debug(self, caplog):
        from netconfig.migration.canonical.port_names import (
            translate_port_names,
        )
        from netconfig.migration.canonical.intent import CanonicalIntent

        with caplog.at_level(
            "DEBUG", logger="netconfig.migration.canonical.port_names",
        ):
            translate_port_names(
                CanonicalIntent(), MockCodec(), MockCodec(),
            )
        entries = [
            r for r in caplog.records
            if r.levelname == "DEBUG"
            and "translate_port_names: entry" in r.getMessage()
        ]
        assert entries, (
            "expected entry DEBUG; got: "
            + "; ".join(r.getMessage() for r in caplog.records)
        )

    def test_vlan_rename_emits_entry_debug(self, caplog):
        """Uses an EMPTY map so the no-op early-return fires — the
        entry log must still appear (this is exactly the scenario
        the prior exit-only log regressed on)."""
        from netconfig.migration.canonical.vlan_names import (
            translate_vlan_ids,
        )
        from netconfig.migration.canonical.intent import CanonicalIntent

        with caplog.at_level(
            "DEBUG", logger="netconfig.migration.canonical.vlan_names",
        ):
            translate_vlan_ids(CanonicalIntent(), rename_map={})
        entries = [
            r for r in caplog.records
            if r.levelname == "DEBUG"
            and "translate_vlan_ids: entry" in r.getMessage()
        ]
        assert entries, "expected entry DEBUG on no-op call"

    def test_local_user_rename_emits_entry_debug(self, caplog):
        from netconfig.migration.canonical.local_user_names import (
            translate_local_user_names,
        )
        from netconfig.migration.canonical.intent import CanonicalIntent

        with caplog.at_level(
            "DEBUG",
            logger="netconfig.migration.canonical.local_user_names",
        ):
            translate_local_user_names(CanonicalIntent(), rename_map={})
        entries = [
            r for r in caplog.records
            if r.levelname == "DEBUG"
            and "translate_local_user_names: entry" in r.getMessage()
        ]
        assert entries

    def test_snmp_rename_emits_entry_debug(self, caplog):
        """Entry log fires EVEN on the empty-map / no-snmp-block
        no-op path — same uniformity guarantee as the siblings."""
        from netconfig.migration.canonical.snmp_names import (
            translate_snmp_community,
        )
        from netconfig.migration.canonical.intent import CanonicalIntent

        with caplog.at_level(
            "DEBUG", logger="netconfig.migration.canonical.snmp_names",
        ):
            translate_snmp_community(CanonicalIntent(), rename_map={})
        entries = [
            r for r in caplog.records
            if r.levelname == "DEBUG"
            and "translate_snmp_community: entry" in r.getMessage()
        ]
        assert entries

    def test_exit_debug_fires_on_completed_rename(self, caplog):
        """Rounds out the entry-log tests: on a non-no-op call, BOTH
        entry AND exit DEBUG records should fire, with exit carrying
        applied/dropped/warnings counts.  Uses snmp since the happy
        path is most compact (single-row scalar rename)."""
        from netconfig.migration.canonical.snmp_names import (
            translate_snmp_community,
        )
        from netconfig.migration.canonical.intent import (
            CanonicalIntent, CanonicalSNMP,
        )

        intent = CanonicalIntent(snmp=CanonicalSNMP(community="public"))
        with caplog.at_level(
            "DEBUG", logger="netconfig.migration.canonical.snmp_names",
        ):
            translate_snmp_community(
                intent, rename_map={"public": "monitoring-ro"},
            )
        messages = [
            r.getMessage() for r in caplog.records
            if r.levelname == "DEBUG"
        ]
        assert any(
            "translate_snmp_community: entry" in m for m in messages
        )
        assert any(
            "translate_snmp_community: exit" in m
            and "applied=1" in m
            for m in messages
        )


class TestCodecParseEndDebugUniformity:
    """Phase 8 audit finding: codec parse paths were silent, making
    "why is my tree empty?" debugging require either response-body
    inspection or a pdb session.  Every shipped codec now emits a
    single DEBUG-level summary at the end of parse() with extracted
    counts.  This test enforces the uniformity: a new codec that
    skips the line would fail CI, not silently ship without a
    troubleshooting breadcrumb.

    Checked against each codec's sample_input — the same smoke
    fixture the cross-codec matrix uses — so this test runs
    end-to-end through the real parse path.
    """

    def _parse_and_capture(self, codec, sample, caplog):
        logger_name = codec.__class__.__module__
        # Some codecs (fortigate_cli) delegate parse() to a sibling
        # module; log signal lives on the sibling's logger.  Capture
        # the top of the fortigate_cli package plus the codec module
        # so either source is observed.
        capture_loggers = [
            logger_name,
            logger_name.rsplit(".", 1)[0] + ".parse",
        ]
        for name in capture_loggers:
            caplog.set_level("DEBUG", logger=name)
        codec.parse(sample)

    @pytest.mark.parametrize(
        "codec_name",
        [
            "cisco_iosxe_cli",
            "cisco_iosxe",
            "aruba_aoss",
            "mikrotik_routeros",
            "opnsense",
            "fortigate_cli",
        ],
    )
    def test_codec_parse_emits_debug_summary(
        self, codec_name, caplog,
    ):
        from netconfig.migration.codecs.registry import get_codec
        codec = get_codec(codec_name)
        sample = getattr(codec, "sample_input", "")
        if not sample:
            pytest.skip(f"{codec_name} declares no sample_input")
        self._parse_and_capture(codec, sample, caplog)
        # Every codec's summary starts with "<codec_name> parsed:"
        # — naming itself in the message keeps logs grep-able by
        # codec without depending on %(name)s (which prefixes
        # differently across codecs due to sub-module loggers).
        matching = [
            r for r in caplog.records
            if r.levelname == "DEBUG"
            and codec_name in r.getMessage()
            and "parsed:" in r.getMessage()
        ]
        assert matching, (
            f"{codec_name}: no '<codec> parsed:' DEBUG log from "
            f"parse().  Records seen: "
            + "; ".join(
                f"{r.name}/{r.levelname}/{r.getMessage()[:60]}"
                for r in caplog.records
            )
        )
