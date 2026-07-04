"""CI guard: the cross-vendor mesh fidelity + honesty baseline.

Runs the full committed-fixture mesh (``tools/run_full_mesh``) and the
Phase-4 reconciliation (``tools/run_phase4_reconciliation``) IN-PROCESS
and asserts the fidelity/honesty properties don't regress against the
committed baseline (``tests/fixtures/real/_phase4_runs/latest.json``):

* reparse of a codec's OWN render never crashes (an absolute invariant —
  the exact class of regression #229 was, but locked in across every
  committed fixture × target pair rather than one endpoint),
* render failures stay within a documented allowlist (a new render crash
  on the committed corpus is a codec regression),
* the reconciled high-severity ``CODEC_BUG`` count doesn't exceed the
  baseline (the confusion-matrix fidelity ratchet), and
* no NEW codec-bug ``(source, target)`` pair appears.

This turns the manual ``python tools/run_full_mesh.py`` +
``run_phase4_reconciliation.py`` dogfood loop into a permanent CI
invariant.  When a codec bug is legitimately fixed (``CODEC_BUG`` drops)
or the fixture corpus changes, regenerate ``latest.json`` to ratchet the
baseline (``python tools/run_phase4_reconciliation.py`` writes a fresh
run; copy its aggregate into ``latest.json``).

Runtime: the mesh is ~1200 cells / ~7s in-process — heavier than a unit
test, hence ``integration``.  It writes NO timestamped JSON (calls the
in-memory ``run_full_mesh()`` directly, not the CLI ``main``).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASELINE_PATH = (
    _REPO_ROOT / "tests" / "fixtures" / "real" / "_phase4_runs" / "latest.json"
)

# Render failures EXPECTED on the committed corpus: the vyos synthetic
# kitchen-sink carries constructs cisco_iosxe_cli / fortigate_cli have no
# render path for.  Any render failure OUTSIDE this set is a regression.
# (source_codec, target_codec)
_ALLOWED_RENDER_FAILURES = {
    ("vyos", "cisco_iosxe_cli"),
    ("vyos", "fortigate_cli"),
}


def _load_tool(mod_name: str, rel_path: str):
    """Import a ``tools/*.py`` runner without making ``tools/`` a package
    (mirrors the pattern in tests/unit/audit)."""
    path = _REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mesh_and_recon(tmp_path_factory):
    """Run the mesh + reconciliation ONCE for the whole module."""
    rfm = _load_tool("run_full_mesh_ciguard", "tools/run_full_mesh.py")
    recon = _load_tool(
        "run_phase4_reconciliation_ciguard", "tools/run_phase4_reconciliation.py"
    )
    mesh = rfm.run_full_mesh()
    # run_reconciliation reads a mesh JSON off disk; hand it an in-repo-free
    # tmp path (the robust relative_to fallback handles the display path).
    mesh_json = tmp_path_factory.mktemp("ciguard") / "mesh.json"
    mesh_json.write_text(json.dumps(mesh), encoding="utf-8")
    result = recon.run_reconciliation(mesh_json)
    return mesh, result


@pytest.fixture(scope="module")
def baseline():
    return json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))


def _fixture_name(cell: dict) -> str:
    return Path(cell["fixture"]).name


def test_reparse_of_own_render_never_crashes(mesh_and_recon):
    """Every cell whose render succeeded must reparse without crashing —
    ``roundtrip_parse_status`` is only ever ``ok`` or ``skipped`` (skipped
    tracks the render failures).  A codec that emits config its own parser
    can't read (e.g. an out-of-range value, the #229 class) turns this red."""
    mesh, _ = mesh_and_recon
    crashed = [
        c for c in mesh["cells"]
        if c["roundtrip_parse_status"] not in ("ok", "skipped")
    ]
    assert not crashed, (
        "reparse of the codec's own render crashed for:\n"
        + "\n".join(
            f"  {c['source_codec']} -> {c['target_codec']} "
            f"[{_fixture_name(c)}]: {c['roundtrip_parse_status']}"
            for c in crashed[:15]
        )
    )


def test_render_failures_within_allowlist(mesh_and_recon):
    """Render failures on the committed corpus stay within the documented
    allowlist; a new (source, target) render crash is a codec regression."""
    mesh, _ = mesh_and_recon
    failing = {
        (c["source_codec"], c["target_codec"])
        for c in mesh["cells"]
        if c["render_status"] != "ok"
    }
    new = failing - _ALLOWED_RENDER_FAILURES
    assert not new, (
        f"new render failure(s) beyond the allowlist: {sorted(new)}. "
        "If intentional, add to _ALLOWED_RENDER_FAILURES with a reason; "
        "otherwise it's a codec render regression."
    )


def test_codec_bug_count_within_baseline(mesh_and_recon, baseline):
    """The reconciled high-severity CODEC_BUG count must not exceed the
    committed baseline.  Uses ``<=`` so a legitimate FIX (fewer bugs)
    passes — ratchet latest.json down when that happens."""
    _, result = mesh_and_recon
    live = result["aggregate"]["CODEC_BUG"]
    base = baseline["aggregate"]["CODEC_BUG"]
    assert live <= base, (
        f"cross-vendor CODEC_BUG count regressed: live={live} > baseline={base}.\n"
        f"live pairs: {result['pair_codec_bug_counts']}\n"
        "A previously-good field now drifts on the committed corpus — "
        "investigate the new pair before re-baselining."
    )


def test_no_new_codec_bug_pairs(mesh_and_recon, baseline):
    """No NEW codec-bug (source, target) pair appears vs the baseline —
    catches a regression even if the total count is coincidentally equal."""
    _, result = mesh_and_recon
    live_pairs = {
        (p["source_codec"], p["target_codec"])
        for p in result["pair_codec_bug_counts"]
    }
    base_pairs = {
        (p["source_codec"], p["target_codec"])
        for p in baseline["pair_codec_bug_counts"]
    }
    new = live_pairs - base_pairs
    assert not new, (
        f"new codec-bug pair(s) not in the baseline: {sorted(new)}. "
        "A previously-clean codec pair now produces a high-severity "
        "fidelity drift on the committed corpus."
    )


def test_no_pair_codec_bug_count_regressed(mesh_and_recon, baseline):
    """No EXISTING pair's codec-bug count may exceed its baseline (TEST-2).

    The aggregate-total and pair-membership guards above both miss an
    intra-corpus shuffle where one pair drops (e.g. 1→0, leaving the set)
    while another rises (2→3): the total stays equal and no NEW pair
    appears, so both pass green while a real per-pair regression hides.
    This pins each pair's count with ``<=`` so a genuine fix (lower count)
    still passes but a rise is caught."""
    _, result = mesh_and_recon

    def _by_pair(rows):
        return {
            (r["source_codec"], r["target_codec"]): r["codec_bug_count"]
            for r in rows
        }

    live = _by_pair(result["pair_codec_bug_counts"])
    base = _by_pair(baseline["pair_codec_bug_counts"])
    regressed = {
        pair: (base[pair], live[pair])
        for pair in base
        if live.get(pair, 0) > base[pair]
    }
    assert not regressed, (
        "existing codec-bug pair(s) regressed (baseline→live): "
        f"{regressed}. A previously-tolerated pair now drifts MORE on the "
        "committed corpus even though the aggregate total / pair set held."
    )


def test_mesh_cell_count_matches_baseline(mesh_and_recon, baseline):
    """The baseline was computed on a fixed corpus size; if fixtures are
    added/removed the count shifts and the CODEC_BUG baseline must be
    regenerated alongside — this makes that coupling explicit rather than
    letting a silently-shrunk corpus weaken the ratchet."""
    mesh, _ = mesh_and_recon
    assert mesh["cells_total"] == baseline["cells_total"], (
        f"mesh cell count {mesh['cells_total']} != baseline "
        f"{baseline['cells_total']}. Adding/removing a fixture (or a codec) "
        "changes this — regenerate tests/fixtures/real/_phase4_runs/latest.json "
        "(python tools/run_phase4_reconciliation.py) and commit it."
    )
