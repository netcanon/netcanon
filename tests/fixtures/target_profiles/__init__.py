"""Synthetic target profiles for tests -- never shipped.

Real profiles live under ``netcanon/definitions/library/target_profiles/``
and the tests load them from there.  This package holds the profiles
that exist only so a code path has something to run on.

``unverified_profile.yaml`` is graded ``evidence: inferred``.  No shipped
profile carries that grade (the set is pinned empty in
``tests/unit/migration/test_target_profile_evidence.py``), but the grade
is still part of the schema and still drives the rename modal's amber
"port names NOT verified" notice, so every tier needs one such profile
to prove the path: copy the file into the test's definitions directory
before the app loads it.
"""

from __future__ import annotations

from pathlib import Path

#: The synthetic ``evidence: inferred`` profile.
UNVERIFIED_PROFILE_YAML = Path(__file__).with_name("unverified_profile.yaml")

#: Its ``vendor/model`` key, as the registry and the API spell it.
UNVERIFIED_PROFILE_KEY = "opnsense/Fixture-Unverified"

#: Its operator-visible caveat, verbatim (no characters HTML would escape).
UNVERIFIED_PROFILE_CAVEAT = (
    "Synthetic test profile. These port names describe no real device."
)
