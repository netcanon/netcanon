"""Output-side completeness: whole-input rejection is NOT silent success
(blind audit ``65f9c01`` T0-2 — the output-side half of the silent-loss
meta-finding).

#180 closed the *input-walk* completeness class (a dropped leaf can't ride
the ``classify()`` default). This closes the symmetric *output-side* surface
the input-walk guard structurally can't see: a permissive ``parse()`` returns
an empty canonical tree for input it doesn't understand (wrong source vendor,
garbage), the validator walks nothing, severity stays ``ok``, and the job
would reach ``completed`` with a banner-only render and zero warnings. The web
UI already flagged this (``isEmptyCompleted`` -> parse-failure banner) but the
backend / HTTP-automation contract (``X-Netcanon-Job-Status``) reported
``completed`` — so a CI gate checking only status saw green for a translation
that produced nothing.

``run_plan`` now downgrades such a result to ``partial`` with an explanatory
``error``, tightly gated so a legitimate translation is never mislabelled:
non-trivial input + zero recognized paths + no Tier-3 detected + a real
``CanonicalIntent`` tree (the internal mock / stub codecs return a plain dict
by design and are exempt).
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs.arista_eos import AristaEOSCodec
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import (
    MigrationJob,
    MigrationJobStatus,
    ValidationReport,
)
from netcanon.services.migration_pipeline import (
    _input_not_recognized,
    run_plan,
)

pytestmark = pytest.mark.unit

# A non-empty input that the cisco_iosxe_cli parser recognizes nothing in
# (not XML/JSON-shaped, so it bypasses the shape guard and falls through the
# line-scan loop to an empty intent) — the audit's exact T0-2 repro shape.
_GARBAGE = "@@@ this is not a real network config @@@\nlorem ipsum dolor\n"


class TestWholeInputRejectionStatus:
    def test_garbage_input_is_partial_not_completed(self):
        job = run_plan(CiscoIOSXECLICodec(), AristaEOSCodec(), _GARBAGE)
        assert job.status is MigrationJobStatus.partial, (
            "non-trivial input that parsed to an empty tree must report "
            "partial, not a silent completed (audit T0-2)"
        )
        assert job.error and "recognized" in job.error.lower()
        # Confirm the precondition: the validator genuinely recognized nothing.
        v = job.validation
        assert not (v.supported_paths or v.lossy_paths or v.unsupported_paths)

    def test_minimal_valid_input_stays_completed(self):
        # `hostname EDGE1` IS recognized (one supported path) -> a real,
        # if tiny, translation. Must NOT be mislabelled partial.
        job = run_plan(CiscoIOSXECLICodec(), AristaEOSCodec(), "hostname EDGE1\n")
        assert job.status is MigrationJobStatus.completed
        assert job.error is None
        assert job.validation.supported_paths

    def test_mock_dict_tree_is_exempt(self):
        # The internal mock codec returns a plain dict (a deliberate no-op
        # parse), not a CanonicalIntent — it is not a real "recognized
        # nothing" signal and must stay completed even though its tree has
        # zero recognized paths. `{}` is the mock's valid (JSON) input shape.
        mock = get_codec("mock")
        job = run_plan(mock, mock, "{}")
        assert job.status is MigrationJobStatus.completed


class TestInputNotRecognizedHelper:
    """White-box: the tightly-gated predicate behind the status downgrade."""

    def _job(self, *, supported=(), tier3=()):
        return MigrationJob(
            source_codec="src",
            target_codec="tgt",
            validation=ValidationReport(
                compatible=True, severity="ok", supported_paths=list(supported)
            ),
            dropped_tier3_sections=list(tier3),
        )

    def test_flags_empty_canonical_from_nontrivial_input(self):
        assert _input_not_recognized("real text", CanonicalIntent(), self._job())

    def test_empty_or_whitespace_input_not_flagged(self):
        assert not _input_not_recognized("   ", CanonicalIntent(), self._job())

    def test_a_recognized_path_is_not_flagged(self):
        assert not _input_not_recognized(
            "real", CanonicalIntent(),
            self._job(supported=["/system/hostname"]),
        )

    def test_tier3_detected_is_not_flagged(self):
        # An all-Tier-3 config carries its own honest "detected but not
        # translated" signal -> recognized (if untranslatable), not rejected.
        assert not _input_not_recognized(
            "real", CanonicalIntent(), self._job(tier3=["firewall"])
        )

    def test_non_canonical_tree_is_not_flagged(self):
        # mock / stub dict tree -> not a real parse, exempt.
        assert not _input_not_recognized("real", {"a": "b"}, self._job())

    def test_missing_validation_is_not_flagged(self):
        job = MigrationJob(source_codec="src", target_codec="tgt")
        assert not _input_not_recognized("real", CanonicalIntent(), job)
