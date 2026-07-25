"""The `demo-v*` tag namespace must stay disjoint from the product release train.

The whole demo release design rests on one property: a `demo-v<N>` tag fires
`demo-publish.yml` and **nothing else**. If a demo tag ever matched a product
publish glob it would push a PyPI release / move a Docker `:latest`; if it
matched the changelog regex it would demand a CHANGELOG section that will never
exist. Both were verified by hand during design ("`demo-` does not begin with
`v`"), which makes them exactly the kind of incidental property that rots.

The `tag_name_pattern` ruleset rule that would enforce the tag *shape* at push
time is unavailable on this repo's plan, so the workflow's own ref guard is the
enforcement point — and these tests are what keep that guard consistent with the
cosign identity it has to match.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github/workflows"

# Representative demo tags, including the ones a slip of the finger produces.
DEMO_TAGS = ["demo-v1", "demo-v2", "demo-v10", "demo-v99"]
# Shapes the ref guard must REFUSE even though they match the trigger glob.
MALFORMED_DEMO_TAGS = ["demo-v1-rc1", "demo-vfoo", "demo-v", "demo-v1.0", "demo-v01a"]


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def tag_globs(name: str) -> list[str]:
    """The `on.push.tags` globs of a workflow. (PyYAML parses bare `on:` as the
    boolean True, hence the fallback.)"""
    data = workflow(name)
    on = data.get("on") or data.get(True) or {}
    return list((on.get("push") or {}).get("tags") or [])


# ── Disjointness from the product publish workflows ──────────────────────────
PRODUCT_PUBLISH_WORKFLOWS = [
    "docker-publish.yml",
    "pypi-publish.yml",
    "desktop-msi-publish.yml",
]


@pytest.mark.parametrize("wf", PRODUCT_PUBLISH_WORKFLOWS)
@pytest.mark.parametrize("tag", DEMO_TAGS + MALFORMED_DEMO_TAGS)
def test_demo_tags_never_trigger_a_product_publish(wf, tag):
    """A demo tag must not push a wheel, an image, or an MSI."""
    for glob in tag_globs(wf):
        assert not fnmatch.fnmatch(tag, glob), (
            f"demo tag {tag!r} matches {wf} trigger glob {glob!r} — "
            "pushing it would fire a product publish"
        )


@pytest.mark.parametrize("tag", DEMO_TAGS)
def test_demo_tags_do_trigger_the_demo_publish(tag):
    globs = tag_globs("demo-publish.yml")
    assert globs, "demo-publish.yml has no push-tag trigger"
    assert any(fnmatch.fnmatch(tag, g) for g in globs), f"{tag!r} would not fire the demo build"


def test_demo_namespace_does_not_begin_with_v():
    """The design criterion, asserted directly: the product globs all start with
    `v`, so any namespace that cannot start with `v` is disjoint by construction.
    """
    for glob in tag_globs("demo-publish.yml"):
        assert not glob.startswith("v"), (
            f"demo trigger glob {glob!r} starts with 'v' and could collide with "
            "the product publish globs"
        )


# ── Disjointness from the changelog obligation ───────────────────────────────
def test_demo_tags_are_exempt_from_the_changelog_release_regex():
    """`tests/unit/test_changelog.py` asserts every stable tag has a CHANGELOG
    section. Demo tags have no changelog entry by design, so they must not match
    its `_STABLE_TAG` regex — nor the `git tag --list v*` filter that feeds it.
    """
    from tests.unit import test_changelog

    for tag in DEMO_TAGS + MALFORMED_DEMO_TAGS:
        assert not test_changelog._STABLE_TAG.match(tag), (
            f"demo tag {tag!r} matches the changelog stable-tag regex and would "
            "demand a CHANGELOG section that will never exist"
        )
        assert not fnmatch.fnmatch(tag, "v*"), f"{tag!r} would be listed by `git tag --list v*`"


# ── The workflow ref guard is the tag_name_pattern substitute ────────────────
def demo_publish_source() -> str:
    return (WORKFLOWS / "demo-publish.yml").read_text(encoding="utf-8")


def ref_guard_regex() -> str:
    """Extract the `^refs/tags/…$` regex the guards job enforces."""
    match = re.search(r"\[\[\s*!\s*\"\$REF\"\s*=~\s*(\^refs/tags/\S+\$)\s*\]\]", demo_publish_source())
    assert match, "could not find the ref-guard regex in demo-publish.yml"
    return match.group(1)


@pytest.mark.parametrize("tag", DEMO_TAGS)
def test_ref_guard_accepts_well_formed_demo_tags(tag):
    assert re.match(ref_guard_regex(), f"refs/tags/{tag}")


@pytest.mark.parametrize("tag", MALFORMED_DEMO_TAGS)
def test_ref_guard_refuses_malformed_demo_tags(tag):
    """These match the trigger glob but would produce a signature whose identity
    no documented `cosign verify` command can match — so the guard must stop the
    build before anything is pushed or signed."""
    assert not re.match(ref_guard_regex(), f"refs/tags/{tag}"), (
        f"{tag!r} would pass the ref guard but is not a demo-v<N> tag"
    )


def test_ref_guard_refuses_branch_and_product_tag_refs():
    guard = ref_guard_regex()
    for ref in ("refs/heads/main", "refs/tags/v0.6.1", "refs/heads/demo-v1", "refs/pull/1/merge"):
        assert not re.match(guard, ref), f"ref guard would accept {ref!r}"


def test_ref_guard_matches_the_cosign_identity_shape():
    """The guard exists to keep every signed demo tag inside the identity the
    verify commands are anchored to (`demo-v[0-9]+`). If the two drift, builds
    succeed but their signatures are unverifiable."""
    assert "demo-v[0-9]+$" in ref_guard_regex()


# ── Signer-identity hygiene ──────────────────────────────────────────────────
def test_cosign_identity_is_exact_not_a_tail_unanchored_regexp():
    """A `--certificate-identity-regexp` ending in `@refs/tags/demo-v` would
    accept a signature minted by ANY demo tag's run — the cross-version
    substitution hole the product workflow already closed."""
    runs = [step.get("run") or "" for step in all_steps()]
    for run in runs:
        assert "--certificate-identity-regexp" not in run, (
            "demo-publish.yml verifies with a regexp identity; pin it exactly"
        )
    assert any("--certificate-identity " in run for run in runs), (
        "expected at least one exact pinned signer identity"
    )


def all_steps() -> list[dict]:
    """Every step of every job. Structural checks read the PARSED workflow, not
    the raw text — a comment explaining a rule must not be mistaken for a
    violation of it (and a trailing comment must not hide a real one)."""
    steps: list[dict] = []
    for job in workflow("demo-publish.yml")["jobs"].values():
        steps.extend(job.get("steps") or [])
    return steps


def test_demo_publish_never_pushes_a_mutable_latest_tag():
    """Both demo images are TCB components consumed by digest; a floating
    `:latest` on them is exactly what the digest pin exists to avoid."""
    for step in all_steps():
        tags = str((step.get("with") or {}).get("tags", ""))
        assert ":latest" not in tags, f"step {step.get('name')!r} pushes a :latest tag"


def test_demo_publish_uses_no_shared_build_cache():
    """A writable cross-run cache could launder a poisoned layer into an image
    this workflow then signs and attests. zizmor does not model cache poisoning,
    so this is the enforcement point."""
    for step in all_steps():
        with_ = step.get("with") or {}
        for key in ("cache-from", "cache-to"):
            assert key not in with_, f"step {step.get('name')!r} declares {key}"
        assert "type=gha" not in str(with_)


def test_demo_publish_declares_least_privilege_at_workflow_level():
    data = workflow("demo-publish.yml")
    assert data["permissions"] == {"contents": "read"}


def test_publish_jobs_depend_on_the_test_and_guard_jobs():
    """Nothing may push before the test re-run and the guards have passed."""
    jobs = workflow("demo-publish.yml")["jobs"]
    assert set(jobs["warden-image"]["needs"]) == {"test", "guards"}
    assert jobs["bundle"]["needs"] == ["warden-image"]


def test_demo_publish_serialises_globally():
    """Per-ref concurrency would let a re-pushed tag race its own bundle attach."""
    concurrency = workflow("demo-publish.yml")["concurrency"]
    assert concurrency["group"] == "demo-publish", "group must not be ref-scoped"
    assert concurrency["cancel-in-progress"] is False, (
        "a half-signed bundle is worse than a queued second run"
    )
