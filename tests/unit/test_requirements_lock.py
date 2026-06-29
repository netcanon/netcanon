"""Consistency guard for ``requirements.lock`` (audit e5b77d7 finding #5).

``requirements.lock`` is the hash-pinned dependency manifest the Docker image
installs with ``pip --require-hashes`` (see Dockerfile + tools/
gen_requirements_lock.sh) so the shipped container's dependency input set is
constrained and integrity-verified rather than re-resolved from pyproject's
ranges at build time.

This guard does NOT re-resolve (that would flake every time an upstream release
lands).  It asserts the committed lock stays *consistent* with the declared
dependencies: every direct dependency in ``pyproject.toml`` is present in the
lock at a version its specifier allows, and every pinned line carries a hash.
So a dep added / removed / range-tightened in pyproject without regenerating the
lock (e.g. a Dependabot bump that would otherwise silently ship a stale pin)
turns CI red, pointing at ``tools/gen_requirements_lock.sh``.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _ROOT / "pyproject.toml"
_LOCK = _ROOT / "requirements.lock"

#: A pinned line: ``name==version \`` (extras stripped by --strip-extras).
_PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+?)\s*\\?\s*$")


def _direct_deps() -> list[Requirement]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return [Requirement(d) for d in data["project"]["dependencies"]]


def _locked_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _LOCK.read_text(encoding="utf-8").splitlines():
        m = _PIN_RE.match(line)
        if m:
            out[canonicalize_name(m.group(1))] = m.group(2)
    return out


def test_lock_exists_and_is_hash_pinned() -> None:
    assert _LOCK.is_file(), "requirements.lock missing -- run tools/gen_requirements_lock.sh"
    text = _LOCK.read_text(encoding="utf-8")
    pinned = len(_locked_versions())
    hashes = text.count("--hash=sha256:")
    assert pinned >= len(_direct_deps()), f"lock pins only {pinned} packages -- looks truncated"
    assert hashes >= pinned, (
        f"lock has {hashes} hashes for {pinned} pinned packages -- every pin must carry a "
        "--hash (regenerate with --generate-hashes via tools/gen_requirements_lock.sh)"
    )


def test_every_direct_dependency_is_locked_and_satisfied() -> None:
    locked = _locked_versions()
    problems: list[str] = []
    for req in _direct_deps():
        name = canonicalize_name(req.name)
        if name not in locked:
            problems.append(f"{req.name}: declared in pyproject but absent from requirements.lock")
            continue
        ver = locked[name]
        if not req.specifier.contains(ver, prereleases=True):
            problems.append(f"{req.name}: locked {ver} does not satisfy pyproject specifier '{req.specifier}'")
    assert not problems, (
        "requirements.lock is out of sync with pyproject.toml dependencies "
        "(regenerate with tools/gen_requirements_lock.sh):\n  " + "\n  ".join(problems)
    )


def test_lock_targets_the_runtime_python() -> None:
    """The lock must be resolved for the deploy interpreter (CPython 3.14, the
    Dockerfile base) -- a lock resolved on another Python carries wrong markers
    / wheels and would break ``pip --require-hashes`` in the image build."""
    header = _LOCK.read_text(encoding="utf-8")[:400]
    assert "with Python 3.14" in header, (
        "requirements.lock header does not show 'with Python 3.14' -- it must be regenerated "
        "inside the digest-pinned 3.14 base image (tools/gen_requirements_lock.sh), not on another Python"
    )
