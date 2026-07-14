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
  baseline (the confusion-matrix fidelity ratchet),
* no NEW codec-bug ``(source, target)`` pair appears, and
* no YAML-less pair's raw mechanical drift exceeds the baseline — the
  coverage ratchet that catches regressions on the ~723/1224 cells the
  CODEC_BUG ratchet is structurally blind to (#14).

This turns the manual ``python tools/run_full_mesh.py`` +
``run_phase4_reconciliation.py`` dogfood loop into a permanent CI
invariant.  When a codec bug is legitimately fixed (``CODEC_BUG`` drops)
or the fixture corpus changes, regenerate ``latest.json`` to ratchet the
baseline: ``python tools/run_phase4_reconciliation.py --write-baseline``
overwrites the committed ``latest.json`` (a bare run leaves it untouched
so inspecting drift never silently moves the baseline — Tests-T1).  The
absolute ceiling in :data:`_ABSOLUTE_CODEC_BUG_CEILING` below is the
non-self-referential backstop: raising the committed baseline still
cannot lift ``CODEC_BUG`` past that hard literal without editing it here.

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

# Render failures EXPECTED on the committed corpus, keyed by
# (source_codec, target_codec, fixture_basename) — NOT pair-only (#36): a
# pair-scoped allowlist let a regression that crashed on any of the 12
# committed REAL vyos captures hide inside an allowlisted (vyos, target) pair.
# Every committed cell renders OK on current main, so this is empty; scope any
# genuinely render-incapable cell here BY BASENAME (e.g. the vyos synthetic
# kitchen-sink on a target lacking a render path) rather than a whole pair.
_ALLOWED_RENDER_FAILURES: set[tuple[str, str, str]] = set()


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
        (c["source_codec"], c["target_codec"], _fixture_name(c))
        for c in mesh["cells"]
        if c["render_status"] != "ok"
    }
    new = failing - _ALLOWED_RENDER_FAILURES
    assert not new, (
        f"new render failure(s) beyond the allowlist: {sorted(new)}. "
        "If intentional, add the (source, target, fixture) triple to "
        "_ALLOWED_RENDER_FAILURES with a reason; otherwise it's a codec "
        "render regression."
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


# The absolute, human-audited ceiling on cross-vendor CODEC_BUG cells.
# UNLIKE test_codec_bug_count_within_baseline (which compares against the
# committed latest.json — a file run_phase4_reconciliation.py rewrites when
# passed --write-baseline), this is a hard literal the reconciliation tool
# cannot move.  Together they close the self-referential loop: regenerating
# the baseline can never lift CODEC_BUG past this line without a human
# editing it here.  Lower it (never raise) as the residual tail is triaged
# down; it stands at 5 as of HEAD-review Fid-F2.
_ABSOLUTE_CODEC_BUG_CEILING = 5


def test_codec_bug_count_within_absolute_ceiling(mesh_and_recon):
    """(Tests-T1) A CONSTANT-pinned ceiling, independent of the committed
    latest.json baseline, so regenerating the baseline can never silently
    ratchet CODEC_BUG upward — only a human edit to the literal can."""
    _, result = mesh_and_recon
    live = result["aggregate"]["CODEC_BUG"]
    assert live <= _ABSOLUTE_CODEC_BUG_CEILING, (
        f"cross-vendor CODEC_BUG count {live} exceeds the absolute ceiling "
        f"{_ABSOLUTE_CODEC_BUG_CEILING}.  Either a real regression, or the "
        f"residual tail genuinely grew — raise the literal here ONLY after "
        f"triaging each pair.\nlive pairs: {result['pair_codec_bug_counts']}"
    )


def test_cross_mesh_results_md_reproduces(mesh_and_recon):
    """(Fid-F1) The committed ``CROSS_MESH_RESULTS.md`` must byte-reproduce
    from the current tree.  The file's own header promises this ("a
    non-empty ``git diff`` here means real drift, not a new run time"), yet
    it silently went stale for the entire #224..#356 promotion wave because
    render-side codec changes skipped the ``--matrix`` regen (the review's
    Fid-F1).  This pins the contract: ``render_matrix_md`` over the same
    in-process mesh the other guards use must equal the committed file.
    Regenerate + commit with ``python tools/run_full_mesh.py --matrix``."""
    rfm = _load_tool("run_full_mesh_ciguard", "tools/run_full_mesh.py")
    mesh, _ = mesh_and_recon
    rendered = rfm.render_matrix_md(mesh)
    committed = (
        _REPO_ROOT / "tests" / "fixtures" / "real" / "CROSS_MESH_RESULTS.md"
    ).read_text(encoding="utf-8")
    # ``splitlines()`` normalises the committed file's CRLF against the
    # renderer's ``\n`` joins, so the assert catches content drift, not the
    # git-checkout line-ending policy.
    assert rendered.splitlines() == committed.splitlines(), (
        "CROSS_MESH_RESULTS.md is stale vs the current mesh render — "
        "regenerate with `python tools/run_full_mesh.py --matrix` and commit "
        "(doc-only).  A non-empty diff here means real render drift the "
        "committed matrix no longer reflects."
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


def test_no_yaml_less_pair_drift_regressed(mesh_and_recon, baseline):
    """No YAML-less (source, target) pair may drift MORE than the committed
    baseline (#14).

    The 56 expectation YAMLs cover only the original 8-codec cross-mesh; the
    4 newest codecs' pairs (cisco_nxos / cisco_iosxr / aruba_aoscx / vyos)
    plus every same-vendor pair — ~723/1224 cells — have no YAML, so their
    ``field_variances`` is empty and NO field can classify as ``CODEC_BUG``.
    The four CODEC_BUG guards above are therefore structurally blind to them:
    a regression that drops every static route on ``arista_eos -> cisco_nxos``
    keeps all of them green.  This pins each YAML-less pair's raw mechanical
    ``fields_drifted`` total (from the Phase-1 mesh, expectation-independent)
    with ``<=`` — a genuine improvement (less drift) still passes, a
    regression (more drift) turns red.  Long-term fix: author expectation
    YAMLs for these pairs so they get the richer CODEC_BUG classification.
    """
    _, result = mesh_and_recon

    def _by_pair(rows):
        return {
            (r["source_codec"], r["target_codec"]): r["drifted_total"]
            for r in rows
        }

    live = _by_pair(result["pair_drift_yaml_less"])
    base = _by_pair(baseline["pair_drift_yaml_less"])
    # The ``<=`` ratchet below iterates the BASELINE pairs, so a pair that is
    # YAML-less in LIVE but ABSENT from the baseline would never be checked
    # (HEAD-review Fid-F5).  Reaching that state needs an expectation-YAML
    # rename/swap that keeps the coverage counts equal (so
    # test_expectation_yaml_coverage_not_reduced stays green) yet moves a pair
    # into the unpinned yaml-less bucket.  Pin the pair SET so any such shuffle
    # turns red and forces a conscious re-baseline.  (88 == 88 at HEAD.)
    assert set(live) == set(base), (
        "YAML-less cross-mesh pair SET changed vs the baseline "
        f"(added: {sorted(set(live) - set(base))}; "
        f"removed: {sorted(set(base) - set(live))}).\nAn expectation-YAML "
        "rename/swap moved a (source, target) pair into (or out of) the "
        "unpinned yaml-less bucket without tripping the coverage guard — the "
        "moved pair's drift is no longer ratcheted.  Re-author the expectation "
        "coverage or regenerate the baseline consciously "
        "(tools/run_phase4_reconciliation.py --write-baseline)."
    )
    regressed = {
        pair: (base[pair], live.get(pair, 0))
        for pair in base
        if live.get(pair, 0) > base[pair]
    }
    assert not regressed, (
        "YAML-less cross-mesh pair(s) drifted MORE than the baseline "
        f"(baseline->live): {regressed}.\nA field that used to round-trip on "
        "an uncovered pair now drops, and the CODEC_BUG ratchet can't see it. "
        "Investigate the regression before re-baselining "
        "(regenerate tests/fixtures/real/_phase4_runs/latest.json's "
        "pair_drift_yaml_less via tools/run_phase4_reconciliation.py)."
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


def test_expectation_yaml_coverage_not_reduced(mesh_and_recon, baseline):
    """No pair-expectation YAML silently drops out of coverage (#35).

    The four CODEC_BUG guards classify only the cells that HAVE a pair
    expectation YAML.  A codec rename orphans a YAML silently (the loader keys
    by filename stem), removing its CODEC_BUG classification while cells_total,
    the aggregate count and the vanished-pair checks all stay green.  Pin the
    coverage denominator: fewer loaded YAMLs, MORE uncovered cells, or fewer
    classified field-cells all turn this red.  live==baseline today
    (56>=56, 723<=723) so no re-baseline is needed."""
    _, result = mesh_and_recon
    assert (
        result["expectation_yamls_loaded"]
        >= baseline["expectation_yamls_loaded"]
    ), (
        "expectation-YAML coverage regressed: "
        f"{result['expectation_yamls_loaded']} < baseline "
        f"{baseline['expectation_yamls_loaded']} — a pair YAML was "
        "deleted/orphaned (codec rename?) and its CODEC_BUG coverage vanished."
    )
    assert len(result["cells_without_expectation_yaml"]) <= len(
        baseline["cells_without_expectation_yaml"]
    ), (
        "cross-vendor cells without a pair YAML rose vs baseline — a pair lost "
        "its expectation YAML; the CODEC_BUG ratchet is now blind to it. "
        "Investigate before re-baselining latest.json."
    )
    assert (
        result["aggregate"]["fields_total"]
        >= baseline["aggregate"]["fields_total"]
    ), (
        "reconciled field-cells dropped vs baseline — fewer fields are being "
        "classified than the committed coverage floor."
    )
