"""The linter version must never reach CI without a reviewed PR.

``pyproject.toml`` used to carry ``ruff>=0.15,<0.16`` under a comment claiming
the range existed so "a ruff release that adds/changes a rule can't silently
turn the CI ``ruff check`` gate red on an unrelated PR".  A range cannot do
that.  CI installs fresh on every run and pip resolves to the newest match, so
the constraint silently adopted 0.15.18 through 0.15.22 as they shipped — five
releases, no PR, no review.  Measured, not assumed: ``pip install --dry-run
"ruff>=0.15,<0.16"`` resolved to ``ruff-0.15.22`` while the pin was in force.

Two properties make the stated rule true rather than aspirational, and this
module holds both:

1. **The pin is exact.**  Only ``ruff==X.Y.Z`` prevents a new release from
   reaching the gate on its own.  Dependabot watches ``pyproject.toml`` — that
   is where its ruff PRs are raised — so every bump then arrives as a
   reviewable, CI-tested PR after the cooldown in ``.github/dependabot.yml``.

2. **``ci.yml`` does not repeat the version.**  The lint job derives the pin
   from ``pyproject.toml``.  The old instruction was a comment saying "keep
   this constraint in sync", which nothing enforced — so the gate and the
   declared dev dependency could drift apart silently.  That divergence is
   precisely why a Dependabot bump to the pyproject constraint would have been
   *inert*: contributors would move to the new ruff while the gate kept
   installing the old one.  Deriving makes divergence structurally impossible;
   this test keeps a literal from creeping back in.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _ROOT / "pyproject.toml"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"

#: ``ruff==1.2.3`` and nothing looser.  Anchored so ``ruff==1.2.3,!=1.2.4`` or a
#: trailing wildcard (``ruff==1.2.*``) does not slip through as "exact".
_EXACT_PIN_RE = re.compile(r"^ruff\s*==\s*\d+\.\d+\.\d+$")

#: Any ruff version constraint at all, for the ci.yml literal check.
_ANY_CONSTRAINT_RE = re.compile(r"ruff\s*(==|>=|<=|~=|!=|<|>)\s*\d")


def _dev_extra() -> list[str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]["dev"]


def _ruff_specs() -> list[str]:
    return [s for s in _dev_extra() if s.replace(" ", "").lower().startswith("ruff")]


def test_pyproject_pins_ruff_exactly() -> None:
    """One ruff spec in the dev extra, and it is an exact ``==`` pin."""
    specs = _ruff_specs()
    assert len(specs) == 1, (
        f"expected exactly one ruff spec in the dev extra, found {specs} — the "
        f"lint job derives the pin by matching 'ruff==', so more than one is "
        f"ambiguous"
    )
    spec = specs[0].replace(" ", "")
    assert _EXACT_PIN_RE.match(spec), (
        f"ruff is pinned as {specs[0]!r}, which is not an exact ==X.Y.Z pin.  A "
        f"range does not keep new releases out of CI: pip resolves to the "
        f"newest match on every fresh install, which is how 0.15.18-0.15.22 "
        f"were adopted without a single PR.  Pin exactly and let Dependabot "
        f"propose each bump."
    )


def test_ci_derives_the_pin_instead_of_repeating_it() -> None:
    """The lint job must read the version, not restate it.

    A second copy of the version can disagree with the first, and nothing
    would notice until someone wondered why a dependency bump changed nothing.
    """
    doc = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    steps = doc["jobs"]["lint"]["steps"]
    # The INSTALL step specifically — the sibling "Run ruff" step invokes
    # the linter and rightly mentions neither a version nor pyproject.
    install = [
        s for s in steps
        if "ruff" in str(s.get("name", "")).lower()
        and "pip install" in str(s.get("run", ""))
    ]
    assert install, (
        "no ruff-install step found in the lint job (a step named for ruff "
        "whose run: block pip-installs it)"
    )

    for step in install:
        run = str(step.get("run", ""))
        literal = _ANY_CONSTRAINT_RE.search(run)
        assert literal is None, (
            f"the lint job hardcodes a ruff version ({literal.group()!r}).  It "
            f"must derive the pin from pyproject.toml instead — a duplicated "
            f"constraint is what let the gate and the declared dev dependency "
            f"drift apart, and it is what made a Dependabot bump to pyproject "
            f"inert."
        )
        assert "pyproject.toml" in run, (
            "the lint job's ruff install neither hardcodes a version nor reads "
            "pyproject.toml — it must read the pin from pyproject so the two "
            "cannot disagree"
        )


def test_the_pinned_ruff_is_the_one_documented_in_ci_scope() -> None:
    """The derivation the workflow performs is the one this test assumes.

    Runs the same selection logic the lint job runs, so a change to the dev
    extra's shape (e.g. ruff moving to another extra) fails here rather than
    at release time in a workflow PR CI does exercise but nobody reads.
    """
    specs = _dev_extra()
    picked = next(
        (s for s in specs if s.replace(" ", "").startswith("ruff==")), None
    )
    assert picked is not None, (
        "the lint job selects the ruff pin with startswith('ruff==') against "
        "the dev extra; nothing in that list matches, so the install step "
        "would fail on the runner"
    )
    assert _EXACT_PIN_RE.match(picked.replace(" ", "")), picked
