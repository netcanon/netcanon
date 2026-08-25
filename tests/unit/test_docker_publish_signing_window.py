"""Nothing failable may sit between publishing an artifact and signing it.

``docker-publish.yml`` pushes every tag — ``:latest`` included — in its
``Build and push`` step.  From that instant until ``cosign sign`` runs, GHCR is
serving an image nobody has signed.  A step in that window that can fail turns
a transient outage into a *permanently* published unsigned ``:latest``: the job
aborts, and the tag stays moved.

The window used to hold three such steps — the Trivy scan, the SARIF upload
(``if: always()`` but no ``continue-on-error``, so its own failure killed the
job), and the cosign install itself.  A GitHub Code Scanning outage was
therefore sufficient to ship an unsigned release.

**This guard covers ``demo-publish.yml`` too, since #446's review found the
same shape there.**  The rule in AGENTS.md is stated generally, but the guard
that enforced it named exactly one workflow, so ``demo-publish.yml`` was never
checked and had drifted into all three violations: the cosign install sat
*after* both image pushes, the SARIF upload was ``if: always()`` with no
``continue-on-error``, and signature verification sat *behind* the scanning
steps that could abort the job.  That workflow signs the demo warden and
authz-shim — Trusted Computing Base components — so it is the more sensitive
of the two, not the less.

Known residual, deliberately not asserted away: ``demo-publish``'s
``warden-image`` job pushes two images before signing either, so a failure of
the *second* push leaves the *first* published unsigned.  That window contains
only essential work (the other push), not incidental steps, and unlike
``:latest`` a demo tag is re-pushable, so the exposure is transient rather than
permanent.  ``test_signing_immediately_follows_the_push`` therefore measures
from the LAST push — the invariant is "nothing incidental in the window", not
"exactly one push per job".

Why this asserts on YAML shape, when ``tests/demo/test_msi_publish_gate.py``
argues that asserting "the gate step exists" proves only that the YAML has a
step and not that it works: that objection is about using structure as a
*proxy* for behaviour.  Here the structure IS the behaviour under test.  The
hazard is defined entirely by step ordering and failure propagation, both of
which are properties of the workflow file — there is no runtime artefact to
inspect instead, and these workflows only ever run on a version tag, so nothing
in PR CI can execute them.  Ordering is therefore checked directly, and checked
against the parsed document rather than the raw text so that reformatting,
re-indentation or comment edits cannot make it pass vacuously.

Deliberately in ``tests/unit`` and not ``tests/demo``: CI runs ``tests/unit``,
``tests/integration``, ``tests/e2e`` and ``tests/desktop``.  ``tests/demo`` runs
only inside ``demo-publish.yml``, so a guard placed there would not gate a
single pull request — and would not have caught this drift either, since it
would only have run at the moment it was already too late.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SIGN_MARKER = "cosign sign"
_SCAN_MARKERS = ("trivy", "sarif")
_INSTALL_MARKER = "cosign-installer"


@dataclass(frozen=True)
class _Case:
    workflow: str
    job: str
    push_steps: tuple[str, ...]
    verify_marker: str


_CASES = {
    "docker-publish": _Case(
        workflow="docker-publish.yml",
        job="build-and-publish",
        push_steps=("Build and push",),
        verify_marker="verify signature",
    ),
    "demo-publish": _Case(
        workflow="demo-publish.yml",
        job="warden-image",
        push_steps=("Build + push warden", "Build + push authz-shim"),
        verify_marker="verify both signatures",
    ),
}

_IDS = sorted(_CASES)


def _steps(case: _Case) -> list[dict]:
    path = _ROOT / ".github" / "workflows" / case.workflow
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc["jobs"][case.job]["steps"]


def _index_of_name(steps: list[dict], name: str, case: _Case) -> int:
    for i, step in enumerate(steps):
        if step.get("name") == name:
            return i
    raise AssertionError(
        f"no step named {name!r} in {case.workflow}:{case.job} — if it was "
        f"renamed, update this guard rather than deleting it"
    )


def _index_of_sign(steps: list[dict], case: _Case) -> int:
    for i, step in enumerate(steps):
        if _SIGN_MARKER in str(step.get("run", "")):
            return i
    raise AssertionError(
        f"no step in {case.workflow}:{case.job} runs {_SIGN_MARKER!r} — the "
        f"publish path no longer signs the artifact it pushes"
    )


@pytest.mark.parametrize("case_id", _IDS)
def test_signing_tooling_is_installed_before_the_push(case_id: str) -> None:
    """cosign is on the runner BEFORE anything is published.

    Installing it afterwards puts a network-dependent download inside the
    unsigned window: if the install fails, the artifact is already public and
    can never be signed by that run.  This is the assertion `demo-publish.yml`
    failed — its cosign install sat after both image pushes.
    """
    case = _CASES[case_id]
    steps = _steps(case)
    install = next(
        (i for i, s in enumerate(steps) if _INSTALL_MARKER in str(s.get("uses", ""))),
        None,
    )
    assert install is not None, (
        f"{case.workflow}:{case.job} never installs cosign, yet signs — the "
        f"signing step must be relying on a preinstalled binary that is not "
        f"guaranteed"
    )
    first_push = min(_index_of_name(steps, n, case) for n in case.push_steps)
    assert install < first_push, (
        f"cosign is installed at step {install} but the first push is at step "
        f"{first_push} in {case.workflow}:{case.job} — a failed install then "
        f"leaves a published, permanently unsigned artifact.  Hoist the "
        f"install above the push."
    )


@pytest.mark.parametrize("case_id", _IDS)
def test_signing_immediately_follows_the_push(case_id: str) -> None:
    """Zero incidental steps between publishing and signing.

    Measured from the LAST push, so a job that batches several pushes is
    allowed — see the module docstring on that residual.  Every other step in
    between is one more way to end up with a published, unsigned artifact.
    """
    case = _CASES[case_id]
    steps = _steps(case)
    last_push = max(_index_of_name(steps, n, case) for n in case.push_steps)
    sign = _index_of_sign(steps, case)
    assert sign > last_push, (
        f"{_SIGN_MARKER!r} runs at step {sign} but the last push is at step "
        f"{last_push} in {case.workflow}:{case.job} — signing must follow the "
        f"push, not precede it"
    )
    between = [str(s.get("name")) for s in steps[last_push + 1:sign]]
    assert not between, (
        f"{len(between)} step(s) sit between the push and the signature in "
        f"{case.workflow}:{case.job}, so a failure in any of them leaves the "
        f"registry serving an unsigned artifact with the tag already moved: "
        f"{between}.  Move them after the signing chain (prerequisite tooling "
        f"like the cosign install belongs BEFORE the push)."
    )


@pytest.mark.parametrize("case_id", _IDS)
def test_image_scanning_runs_after_the_image_is_signed(case_id: str) -> None:
    """Trivy and its SARIF upload are reporting, not gating.

    They scan an artifact that is already published, so running them before
    the signature buys nothing and costs the release its signature when Code
    Scanning has a bad day.
    """
    case = _CASES[case_id]
    steps = _steps(case)
    sign = _index_of_sign(steps, case)
    offenders = [
        (i, str(s.get("name")))
        for i, s in enumerate(steps[:sign])
        if any(m in str(s.get("name", "")).lower() for m in _SCAN_MARKERS)
    ]
    assert not offenders, (
        f"image-scanning step(s) run before the signature at step {sign} in "
        f"{case.workflow}:{case.job}: {offenders}.  Scanning is informational "
        f"(the Trivy step sets `exit-code: 0`); it must not be able to abort "
        f"the job while the pushed tags are unsigned."
    )


@pytest.mark.parametrize("case_id", _IDS)
def test_sarif_upload_cannot_fail_the_publish(case_id: str) -> None:
    """The SARIF upload is explicitly non-fatal.

    ``if: always()`` only guarantees the step RUNS after an earlier failure —
    it does nothing about the step failing on its own, which is exactly what a
    Code Scanning outage looks like.  ``continue-on-error`` is the property
    that keeps a reporting hiccup from failing a release.
    """
    case = _CASES[case_id]
    for step in _steps(case):
        if "sarif" in str(step.get("name", "")).lower():
            assert step.get("continue-on-error") is True, (
                f"step {step.get('name')!r} in {case.workflow}:{case.job} "
                f"uploads scan results but is not `continue-on-error: true` — "
                f"a Code Scanning outage would fail the publish job.  "
                f"`if: always()` does NOT cover this; it governs whether the "
                f"step runs, not whether its own failure propagates."
            )
            return
    raise AssertionError(
        f"no SARIF upload step found to check in {case.workflow}:{case.job}"
    )


@pytest.mark.parametrize("case_id", _IDS)
def test_the_signature_is_verified_before_scanning_reports(case_id: str) -> None:
    """The post-publish signature smoke test stays inside the trusted chain.

    It is the step that proves the signature is real; ordering it after the
    scanning steps would let a scan failure skip verification entirely.
    """
    case = _CASES[case_id]
    steps = _steps(case)
    verify = next(
        (i for i, s in enumerate(steps)
         if case.verify_marker in str(s.get("name", "")).lower()),
        None,
    )
    assert verify is not None, (
        f"the post-publish signature smoke test is gone from "
        f"{case.workflow}:{case.job} (looked for {case.verify_marker!r})"
    )
    scans = [
        i for i, s in enumerate(steps)
        if any(m in str(s.get("name", "")).lower() for m in _SCAN_MARKERS)
    ]
    assert all(verify < i for i in scans), (
        f"signature verification is at step {verify} but scanning runs at "
        f"{scans} in {case.workflow}:{case.job} — verification must not sit "
        f"behind a step that can abort."
    )
