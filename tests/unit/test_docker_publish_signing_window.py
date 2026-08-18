"""Nothing failable may sit between publishing an image and signing it.

``docker-publish.yml`` pushes every tag — ``:latest`` included — in its
``Build and push`` step.  From that instant until ``cosign sign`` runs, GHCR is
serving an image nobody has signed.  A step in that window that can fail turns
a transient outage into a *permanently* published unsigned ``:latest``: the job
aborts, and the tag stays moved.

The window used to hold three such steps — the Trivy scan, the SARIF upload
(``if: always()`` but no ``continue-on-error``, so its own failure killed the
job), and the cosign install itself.  A GitHub Code Scanning outage was
therefore sufficient to ship an unsigned release.

Why this asserts on YAML shape, when ``tests/demo/test_msi_publish_gate.py``
argues that asserting "the gate step exists" proves only that the YAML has a
step and not that it works: that objection is about using structure as a
*proxy* for behaviour.  Here the structure IS the behaviour under test.  The
hazard is defined entirely by step ordering and failure propagation, both of
which are properties of the workflow file — there is no runtime artefact to
inspect instead, and this workflow only ever runs on a version tag, so nothing
in PR CI can execute it.  Ordering is therefore checked directly, and checked
against the parsed document rather than the raw text so that reformatting,
re-indentation or comment edits cannot make it pass vacuously.

Deliberately in ``tests/unit`` and not ``tests/demo``: CI runs ``tests/unit``,
``tests/integration``, ``tests/e2e`` and ``tests/desktop``.  ``tests/demo`` runs
only inside ``demo-publish.yml``, so a guard placed there would not gate a
single pull request.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _ROOT / ".github" / "workflows" / "docker-publish.yml"

_PUBLISH_JOB = "build-and-publish"
_PUSH_STEP = "Build and push"
_SIGN_MARKER = "cosign sign"
_SCAN_MARKERS = ("trivy", "sarif")


def _steps() -> list[dict]:
    doc = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    return doc["jobs"][_PUBLISH_JOB]["steps"]


def _index_of_name(steps: list[dict], name: str) -> int:
    for i, step in enumerate(steps):
        if step.get("name") == name:
            return i
    raise AssertionError(
        f"no step named {name!r} in {_PUBLISH_JOB} — if it was renamed, update "
        f"this guard rather than deleting it"
    )


def _index_of_sign(steps: list[dict]) -> int:
    for i, step in enumerate(steps):
        if _SIGN_MARKER in str(step.get("run", "")):
            return i
    raise AssertionError(
        f"no step runs {_SIGN_MARKER!r} — the publish path no longer signs the "
        f"image it pushes"
    )


def test_signing_immediately_follows_the_push() -> None:
    """Zero steps between publishing and signing.

    Not "signing happens eventually" — every step in between is one more way
    to end up with a published, unsigned ``:latest``.
    """
    steps = _steps()
    push = _index_of_name(steps, _PUSH_STEP)
    sign = _index_of_sign(steps)
    assert sign > push, (
        f"{_SIGN_MARKER!r} runs at step {sign} but the push is at step {push} — "
        f"signing must follow the push, not precede it"
    )
    between = [str(s.get("name")) for s in steps[push + 1:sign]]
    assert not between, (
        f"{len(between)} step(s) sit between the push and the signature, so a "
        f"failure in any of them leaves GHCR serving an unsigned :latest with "
        f"the tag already moved: {between}.  Move them after the signing chain "
        f"(prerequisite tooling like the cosign install belongs BEFORE the "
        f"push)."
    )


def test_image_scanning_runs_after_the_image_is_signed() -> None:
    """Trivy and its SARIF upload are reporting, not gating.

    They scan an image that is already published, so running them before the
    signature buys nothing and costs the release its signature when Code
    Scanning has a bad day.
    """
    steps = _steps()
    sign = _index_of_sign(steps)
    offenders = [
        (i, str(s.get("name")))
        for i, s in enumerate(steps[:sign])
        if any(m in str(s.get("name", "")).lower() for m in _SCAN_MARKERS)
    ]
    assert not offenders, (
        f"image-scanning step(s) run before the signature at step {sign}: "
        f"{offenders}.  Scanning is informational (the Trivy step sets "
        f"`exit-code: 0`); it must not be able to abort the job while the "
        f"pushed tags are unsigned."
    )


def test_sarif_upload_cannot_fail_the_publish() -> None:
    """The SARIF upload is explicitly non-fatal.

    ``if: always()`` only guarantees the step RUNS after an earlier failure —
    it does nothing about the step failing on its own, which is exactly what a
    Code Scanning outage looks like.  ``continue-on-error`` is the property
    that keeps a reporting hiccup from failing a release.
    """
    steps = _steps()
    for step in steps:
        if "sarif" in str(step.get("name", "")).lower():
            assert step.get("continue-on-error") is True, (
                f"step {step.get('name')!r} uploads scan results but is not "
                f"`continue-on-error: true` — a Code Scanning outage would "
                f"fail the publish job.  `if: always()` does NOT cover this; "
                f"it governs whether the step runs, not whether its own "
                f"failure propagates."
            )
            return
    raise AssertionError("no SARIF upload step found to check")


def test_the_signature_is_verified_before_scanning_reports() -> None:
    """The post-publish signature smoke test stays inside the trusted chain.

    It is the step that proves the signature is real; ordering it after the
    scanning steps would let a scan failure skip verification entirely.
    """
    steps = _steps()
    verify = next(
        (i for i, s in enumerate(steps)
         if "verify signature" in str(s.get("name", "")).lower()),
        None,
    )
    assert verify is not None, "the post-publish signature smoke test is gone"
    scans = [
        i for i, s in enumerate(steps)
        if any(m in str(s.get("name", "")).lower() for m in _SCAN_MARKERS)
    ]
    assert all(verify < i for i in scans), (
        f"signature verification is at step {verify} but scanning runs at "
        f"{scans} — verification must not sit behind a step that can abort."
    )
