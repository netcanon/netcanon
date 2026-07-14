"""Guard tests for ``CHANGELOG.md`` integrity.

Motivated by the v0.2.0 → v0.3.0 cut, where a CHANGELOG edit silently deleted
the ``## [0.2.0]`` section header (restored in #111).  Nothing caught it
because there was no changelog test — the lesson was "eyeball the version
headers when cutting", which is exactly the kind of manual check a test should
replace.  These guards assert:

* an ``## [Unreleased]`` section exists (a home for new entries + the anchor
  the release cut renames),
* released-version headers are unique and strictly descending (newest first),
  and each carries a ``- YYYY-MM-DD`` date — except the single oldest
  (genesis) entry, which may use the ``— initial release`` form, and
* **every stable ``vX.Y.Z`` release tag has a matching ``## [X.Y.Z]``
  section** — the direct guard against a dropped header.  The CI test job
  checks out full history + tags, so this runs in CI; it skips gracefully
  where git/tags are unavailable (e.g. a source tarball).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHANGELOG = _REPO_ROOT / "CHANGELOG.md"

# Any released-version header: `## [X.Y.Z]` (ignores `## [Unreleased]`).
_ANY_VERSION = re.compile(r"^## \[(\d+)\.(\d+)\.(\d+)\]", re.MULTILINE)
# A dated released header: `## [X.Y.Z] - YYYY-MM-DD`.
_DATED_VERSION = re.compile(
    r"^## \[(\d+)\.(\d+)\.(\d+)\] - \d{4}-\d{2}-\d{2}\s*$", re.MULTILINE
)
_STABLE_TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")


def _changelog_text() -> str:
    # read_text uses universal newlines, so a CRLF file is normalised to \n
    # and the ^/$ MULTILINE anchors behave regardless of the on-disk endings.
    return _CHANGELOG.read_text(encoding="utf-8")


def _versions(pattern: re.Pattern[str]) -> list[tuple[int, int, int]]:
    return [(int(a), int(b), int(c)) for a, b, c in pattern.findall(_changelog_text())]


def test_changelog_exists() -> None:
    assert _CHANGELOG.is_file()


def test_unreleased_section_present() -> None:
    """`## [Unreleased]` must exist — new entries land there and the release
    cut renames it to the new version."""
    assert re.search(r"^## \[Unreleased\]\s*$", _changelog_text(), re.MULTILINE), (
        "CHANGELOG.md is missing its `## [Unreleased]` section header"
    )


def test_released_headers_unique_and_descending() -> None:
    """Released-version headers are unique and strictly descending (newest
    first) — catches duplicate or out-of-order sections."""
    versions = _versions(_ANY_VERSION)
    assert versions, "no `## [X.Y.Z]` release headers found in CHANGELOG"
    assert len(versions) == len(set(versions)), (
        f"duplicate version header(s) in CHANGELOG: {versions}"
    )
    assert versions == sorted(versions, reverse=True), (
        f"CHANGELOG version headers must be strictly descending (newest first); got {versions}"
    )


def test_released_headers_are_dated_except_genesis() -> None:
    """Every released header carries a `- YYYY-MM-DD` date, except the single
    oldest (genesis) entry, which may use the `— initial release` form."""
    all_versions = _versions(_ANY_VERSION)
    dated = set(_versions(_DATED_VERSION))
    undated = [v for v in all_versions if v not in dated]
    assert len(undated) <= 1, (
        f"release header(s) missing a `- YYYY-MM-DD` date: "
        f"{['.'.join(map(str, v)) for v in undated]}"
    )
    if undated:
        assert undated[0] == min(all_versions), (
            "only the oldest (genesis) release header may omit a date; "
            f"undated header {'.'.join(map(str, undated[0]))} is not the oldest"
        )


def _git_stable_tags() -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "tag", "--list", "v*"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    tags = [m.group(1) for line in result.stdout.splitlines() if (m := _STABLE_TAG.match(line.strip()))]
    return tags


def test_every_release_tag_has_changelog_entry() -> None:
    """The regression guard: each stable `vX.Y.Z` release tag must have a
    matching `## [X.Y.Z]` CHANGELOG section.  This is exactly what the dropped
    `[0.2.0]` header (restored in #111) violated.  Skips where git/tags are
    unavailable; the CI test job fetches full history + tags."""
    tags = _git_stable_tags()
    if not tags:
        # In CI the test job checks out with fetch-depth: 0 (full history +
        # tags), so a tag-less checkout THERE means that fetch regressed and
        # the release guard is silently disarmed — setuptools_scm would then
        # guess a `.devN` version and nothing else goes red.  Fail loudly in CI
        # rather than skip (P7); the skip stays for legitimate tarball / shallow
        # local checkouts.
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail(
                "no git tags visible in CI — the test checkout lost its "
                "full-history+tags fetch (fetch-depth: 0). The tag↔CHANGELOG "
                "release guard is silently disarmed; restore the deep fetch."
            )
        pytest.skip("no git tags available (shallow / tarball checkout) — tag↔changelog check skipped")
    headers = {".".join(map(str, v)) for v in _versions(_ANY_VERSION)}
    missing = sorted(t for t in tags if t not in headers)
    assert not missing, (
        f"release tag(s) with no `## [X.Y.Z]` CHANGELOG section: {missing}. "
        "A header was likely dropped — restore it (see the #111 [0.2.0] restore)."
    )
