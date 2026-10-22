"""The runtime image carries no pip.

pip vendors its own copies of third-party libraries, pinned by the pip
release the base image ships rather than by ``requirements.lock``.  The
certifi CA bundle that pip 26.2.1 vendors is a CRITICAL advisory
(GHSA-6q48-6c7w-9gw2), and the gating Trivy scan in ``ci.yml`` failed
every pull request on it while the image's own dependencies were clean.
Nothing in the server uses pip, so the runtime stage uninstalls it once
netcanon is installed.  This module reads the Dockerfile for that: the
runtime stage removes pip, and nothing after the removal runs pip or
brings it back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"

#: ``pip uninstall`` of pip itself, as ``python -m pip`` or ``pip``.
_REMOVES_PIP = re.compile(
    r"(?:python3?\s+-m\s+)?pip\s+uninstall\s+(?:--yes|-y)\s+pip\b",
)
#: Anything that runs pip, or puts one back.
_USES_PIP = re.compile(r"\bpip3?\b|\bensurepip\b")


def _instructions(text: str) -> list[str]:
    """The Dockerfile's instructions, each continued line joined, comments
    left out."""
    out: list[str] = []
    pending = ""
    for line in text.splitlines():
        if not pending and line.lstrip().startswith("#"):
            continue
        if line.rstrip().endswith("\\"):
            pending += line.rstrip()[:-1] + " "
            continue
        out.append(pending + line)
        pending = ""
    if pending:
        out.append(pending)
    return [step.strip() for step in out if step.strip()]


def _runtime_stage(text: str) -> list[str]:
    steps = _instructions(text)
    starts = [i for i, step in enumerate(steps) if re.match(r"FROM\s.*\bAS\s+runtime\b", step, re.I)]
    assert len(starts) == 1, "no single `FROM ... AS runtime` stage in the Dockerfile"
    return steps[starts[0] + 1:]


def _removals(steps: list[str]) -> list[int]:
    return [i for i, step in enumerate(steps) if step.startswith("RUN ") and _REMOVES_PIP.search(step)]


def test_the_runtime_stage_removes_pip() -> None:
    assert _removals(_runtime_stage(_DOCKERFILE.read_text(encoding="utf-8")))


def test_nothing_after_the_removal_runs_pip_or_brings_it_back() -> None:
    steps = _runtime_stage(_DOCKERFILE.read_text(encoding="utf-8"))
    last = _removals(steps)[-1]
    # The step that removes pip may use it before the removal, not after.
    after_in_step = _REMOVES_PIP.split(steps[last])[-1]
    assert not _USES_PIP.search(after_in_step), steps[last]
    for step in steps[last + 1:]:
        assert not _USES_PIP.search(step), step


@pytest.mark.parametrize(
    ("dockerfile", "removes"),
    [
        (
            "FROM python AS builder\nRUN pip wheel .\n"
            "FROM python AS runtime\nRUN pip install x \\\n    && python -m pip uninstall --yes pip\n",
            True,
        ),
        ("FROM python AS builder\nRUN pip uninstall -y pip\nFROM python AS runtime\nRUN pip install x\n", False),
        ("FROM python AS runtime\n# RUN pip uninstall --yes pip\nRUN pip install x\n", False),
    ],
)
def test_the_reading_tells_a_stage_that_removes_pip(dockerfile: str, removes: bool) -> None:
    """The reader is handed Dockerfiles that do and do not: a removal in
    the builder stage, or in a comment, is no removal in the runtime."""
    assert bool(_removals(_runtime_stage(dockerfile))) is removes


def test_the_reading_sees_pip_brought_back() -> None:
    steps = _runtime_stage(
        "FROM python AS runtime\nRUN pip install x && pip uninstall --yes pip\n"
        "RUN python -m ensurepip\n",
    )
    last = _removals(steps)[-1]
    assert any(_USES_PIP.search(step) for step in steps[last + 1:])
