"""
Schema guard for the Phase 3 cross-vendor expectation YAMLs.

``tools/load_cross_vendor_expectations.py`` has always validated these 56
files against the schema documented in
``tests/fixtures/cross_vendor_expectations/README.md`` — but it was a
standalone script wired into nothing, so nothing ran it.  It rotted: by
2026-08 three files failed their own documented schema and had done since
``ba86562`` ("Wave 7c close-out: flip 3 cisco_iosxe-source vendor-wire-correct
cells to lossy"), which flipped ``interfaces[].name`` from ``good`` to
``lossy`` in each without renaming the accompanying ``note:`` to ``reason:``.
The requirement is *disposition-dependent* — ``note`` is the right key for
``good`` / ``not_applicable`` and ``reason`` is REQUIRED for ``lossy`` /
``unsupported`` — so flipping a disposition silently invalidates the entry.
That is precisely the class of drift a human re-reading the diff does not
catch and a validator does, which is why this module now exists: the tool's
own docstring named this file as its intended home.

This module deliberately calls the tool's ``validate_one`` rather than
re-implementing the rules, so the schema has ONE definition.  A rule added to
the tool is enforced here automatically.

The two checks below it are additions the tool does not make, each verified
against the current corpus before being adopted:

* the filename must equal ``<source_vendor>__<target_vendor>`` from ``meta``.
  The reconciler resolves a cell's YAML *by filename*
  (``run_phase4_reconciliation`` builds its index from the stem), so a file
  whose meta disagrees with its name would be silently reconciled against the
  wrong pair's expectations.
* every ``meta.references[].path`` must resolve on disk.  The tool checks that
  cited ids are declared, but never that a declared reference points at a real
  research note — so a moved or deleted note leaves a citation that looks
  grounded and is not.  (The same wave found ``1b1b865`` cited in three files'
  prose, a revision that exists nowhere in this repo.)
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "cross_vendor_expectations"

# Load the validator without making ``tools/`` a package — same pattern as
# ``tests/unit/audit/test_run_phase4_reconciliation.py``.
_LOADER_PATH = _REPO_ROOT / "tools" / "load_cross_vendor_expectations.py"
_spec = importlib.util.spec_from_file_location(
    "load_cross_vendor_expectations", _LOADER_PATH,
)
assert _spec is not None and _spec.loader is not None
loader = importlib.util.module_from_spec(_spec)
sys.modules["load_cross_vendor_expectations"] = loader
_spec.loader.exec_module(loader)

validate_one = loader.validate_one

#: Sorted so parametrisation ids are stable across platforms.
_YAML_PATHS = sorted(_FIXTURE_DIR.glob("*.yaml"))
_YAML_IDS = [p.stem for p in _YAML_PATHS]


def test_the_corpus_is_not_empty() -> None:
    """A glob that silently matches nothing would make every parametrised
    test below vacuous — the failure mode where a green suite proves
    nothing.  Pin a floor rather than an exact count so adding a pair
    (A6's 16 vyos YAMLs, say) doesn't fail here for the wrong reason."""
    assert len(_YAML_PATHS) >= 56, (
        f"expected at least 56 expectation YAMLs under {_FIXTURE_DIR}, "
        f"found {len(_YAML_PATHS)} — the glob is matching nothing, or pair "
        f"files were deleted without updating this floor"
    )


@pytest.mark.parametrize("path", _YAML_PATHS, ids=_YAML_IDS)
def test_yaml_matches_the_documented_schema(path: Path) -> None:
    """Every pair YAML satisfies the schema in the fixture-dir README.

    Delegates to ``tools/load_cross_vendor_expectations.validate_one`` so
    there is one definition of the rules.  The most-missed rule is the
    disposition-dependent one: ``lossy`` and ``unsupported`` REQUIRE
    ``reason``; ``good`` and ``not_applicable`` take an optional ``note``.
    Flipping a disposition means re-checking the key.
    """
    try:
        validate_one(path)
    except (yaml.YAMLError, ValueError) as exc:
        pytest.fail(
            f"{path.name} fails the schema documented in "
            f"{_FIXTURE_DIR.name}/README.md: {exc}"
        )


@pytest.mark.parametrize("path", _YAML_PATHS, ids=_YAML_IDS)
def test_filename_matches_the_declared_pair(path: Path) -> None:
    """``<source>__<target>.yaml`` must agree with ``meta``.

    The reconciler keys its expectation index off the FILENAME, so a
    disagreement here reconciles a cell against another pair's expectations
    and every resulting variance class is quietly wrong.
    """
    meta = yaml.safe_load(path.read_text(encoding="utf-8"))["meta"]
    expected = f"{meta['source_vendor']}__{meta['target_vendor']}"
    assert path.stem == expected, (
        f"{path.name} declares source_vendor={meta['source_vendor']!r} / "
        f"target_vendor={meta['target_vendor']!r}, so it must be named "
        f"{expected}.yaml — the Phase 4 reconciler matches cells to YAMLs by "
        f"filename, not by meta, so this file is being applied to the wrong "
        f"pair"
    )


@pytest.mark.parametrize("path", _YAML_PATHS, ids=_YAML_IDS)
def test_every_declared_reference_path_resolves(path: Path) -> None:
    """A citation is only as good as the note it points at.

    ``validate_one`` proves cited ids are declared; it cannot prove a
    declared reference's ``path`` still exists.  A research note that is
    moved or deleted leaves behind a citation that reads as vendor-grounded
    while grounding nothing.
    """
    meta = yaml.safe_load(path.read_text(encoding="utf-8"))["meta"]
    dangling = [
        (ref["id"], ref["path"])
        for ref in meta.get("references", [])
        if not (_REPO_ROOT / ref["path"]).is_file()
    ]
    assert not dangling, (
        f"{path.name} declares reference(s) whose path does not exist: "
        f"{dangling}.  Either restore the research note, repoint the "
        f"reference at the note that actually grounds the claim, or drop "
        f"the reference — a citation to a missing file is worse than none."
    )
