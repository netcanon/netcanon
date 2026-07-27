"""Execute `desktop-msi-publish.yml`'s pre-publish gate, rather than reading it.

The MSI workflow only ever runs on a `v*.*.*` tag push, so PR CI never
exercises a single line of it. Every defect this repo has shipped in a publish
path shared one shape: a check scoped to a source file instead of the artefact
that actually ships. Asserting "the gate step exists" would repeat that mistake
at one remove — it proves the YAML has a step, not that the step works.

So these tests pull the gate's `run:` block straight out of the parsed workflow
and run it under bash against a stubbed `gh`. The script takes all of its input
from `env:` and contains no `${{ }}` expansion (there is a test below pinning
that), which is what makes running it verbatim possible: what executes here is
byte-identical to what executes on the runner.

Under immutable releases the publish step freezes the asset permanently, so the
failure this gate has to catch — GitHub storing something other than what was
built — is not recoverable after the fact. It has to be caught in the draft
window or not at all.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/desktop-msi-publish.yml"

GATE_STEP = "Gate — re-verify the asset GitHub stored, before freezing it"
MSI_NAME = "netcanon-9.9.9-win64.msi"
BUILT = b"pretend this is 250 MB of cx_Freeze output"

# The stub stands in for `gh`, dispatching on the argument shapes the gate uses.
# `release download` writes into the `roundtrip/` dir the gate itself created.
GH_STUB = """#!/usr/bin/env bash
args="$*"
case "$args" in
  *"release download"*)   printf '%s' "$STUB_BODY" > "roundtrip/$STUB_STORED_NAME" ;;
  *".assets[].name"*)     printf '%s\\n' "$STUB_NAMES" ;;
  *".assets | length"*)   printf '%s\\n' "$STUB_COUNT" ;;
  *)                      printf 'isDraft=true assets=%s\\n' "$STUB_COUNT" ;;
esac
"""


def find_bash() -> str | None:
    """A bash that can actually run the gate.

    `shutil.which("bash")` on Windows finds `System32\\bash.exe` — the WSL shim,
    which fails with `execvpe(/bin/bash)` when no distro is installed. Probing
    for the coreutils the gate uses is the only reliable test, and it doubles as
    a check that `sha256sum`/`stat` exist (the runner's git-bash has them; the
    workflow already relies on that).
    """
    candidates = [shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe"]
    for cand in candidates:
        if not cand or not Path(cand).exists():
            continue
        try:
            probe = subprocess.run(
                [cand, "-c", "command -v sha256sum >/dev/null && printf ok"],
                capture_output=True, text=True, timeout=30,
            )
        except OSError:
            continue
        if probe.stdout.strip() == "ok":
            return cand
    return None


BASH = find_bash()


def gate_script() -> str:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = data["jobs"]["build-msi"]["steps"]
    matching = [s for s in steps if s.get("name") == GATE_STEP]
    assert matching, (
        f"no step named {GATE_STEP!r} in desktop-msi-publish.yml — if it was "
        "renamed, update GATE_STEP so these tests keep exercising the real gate"
    )
    return matching[0]["run"]


def run_gate(tmp_path: Path, **stub) -> subprocess.CompletedProcess:
    """Run the real gate script with a stubbed `gh` on PATH."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(GH_STUB, encoding="utf-8", newline="\n")
    gh.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "stub",
        "TAG": "v9.9.9",
        "EXPECTED_ASSETS": "1",
        # What the build step recorded into $GITHUB_ENV.
        "MSI_NAME": MSI_NAME,
        "MSI_SIZE": str(len(BUILT)),
        "MSI_SHA256": hashlib.sha256(BUILT).hexdigest(),
        # Stub knobs — what GitHub is pretending to hold.
        "STUB_NAMES": stub.get("names", MSI_NAME),
        "STUB_STORED_NAME": stub.get("stored_name", MSI_NAME),
        "STUB_COUNT": stub.get("count", "1"),
        "STUB_BODY": stub.get("body", BUILT).decode("latin-1"),
    }
    return subprocess.run(
        [BASH, "-c", gate_script()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )


pytestmark = [
    pytestmark,
    pytest.mark.skipif(BASH is None, reason="needs a bash with coreutils"),
]


def test_gate_passes_when_github_stored_what_was_built(tmp_path):
    r = run_gate(tmp_path)
    assert r.returncode == 0, f"gate rejected a good release:\n{r.stdout}\n{r.stderr}"
    assert "byte-identical" in r.stdout


def test_gate_refuses_a_corrupted_upload(tmp_path):
    """The failure the gate exists for: the upload truncated or mangled, so what
    users would download is not what was built and tested."""
    r = run_gate(tmp_path, body=BUILT + b"tail garbage")
    assert r.returncode != 0
    assert "does not match what was built" in r.stdout


def test_gate_refuses_an_extra_asset(tmp_path):
    """A backfill re-run against a draft that already carries a stale MSI would
    otherwise publish both, and under immutability that pairing is permanent."""
    r = run_gate(tmp_path, count="2")
    assert r.returncode != 0
    assert "expected 1" in r.stdout


def test_gate_refuses_an_asset_under_the_wrong_name(tmp_path):
    r = run_gate(tmp_path, names="netcanon-0.0.1-win64.msi")
    assert r.returncode != 0
    assert "attached asset is" in r.stdout


def test_gate_script_is_self_contained(tmp_path):
    """The gate takes every input from `env:`. A `${{ }}` expression in the
    `run:` block would be substituted by the runner before bash ever sees it,
    which would make the tests above exercise a different script than ships."""
    assert not re.search(r"\$\{\{.*?\}\}", gate_script()), (
        "the gate's run: block gained a ${{ }} expression — move it into env: "
        "so what these tests execute stays identical to what the runner executes"
    )
