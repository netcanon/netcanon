"""Determinism: the cross-mesh runner's per-cell LAG drill-down must be
stable run-to-run.

Before the fix, ``compute_field_disposition`` stored the UNSORTED source/
target lists in a non-preserved cell's ``source``/``target`` drill-down,
so the serialised order tracked the source parse's hash-randomised
set-iteration order — producing a different ``CROSS_MESH_RESULTS.md`` MD5
on every process invocation.  It now summarises the identity-normalised
lists, so the output is byte-stable regardless of input list order.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalLAG

pytestmark = pytest.mark.unit

# Load the standalone runner the same way test_run_full_mesh.py does.
_RUNNER_PATH = Path(__file__).resolve().parents[3] / "tools" / "run_full_mesh.py"
_spec = importlib.util.spec_from_file_location("run_full_mesh", _RUNNER_PATH)
assert _spec is not None and _spec.loader is not None
run_full_mesh = importlib.util.module_from_spec(_spec)
sys.modules["run_full_mesh"] = run_full_mesh
_spec.loader.exec_module(run_full_mesh)
compute_field_disposition = run_full_mesh.compute_field_disposition


def _src(order: list[str]) -> CanonicalIntent:
    return CanonicalIntent(lags=[CanonicalLAG(name=n) for n in order])


def test_lag_drilldown_display_is_order_independent() -> None:
    # Target drops one LAG → the `lags` field is not preserved → the
    # source/target drill-down arrays are stored.
    tgt = CanonicalIntent(lags=[CanonicalLAG(name="port-channel5")])
    a = compute_field_disposition(
        _src(["port-channel3", "port-channel5"]), tgt
    )["lags"]
    b = compute_field_disposition(
        _src(["port-channel5", "port-channel3"]), tgt
    )["lags"]
    assert not a["preserved"] and not b["preserved"]
    # Identity-normalised → byte-identical drill-down regardless of the
    # source list's (set-iteration) order.
    assert a["source"] == b["source"]
    assert a["target"] == b["target"]


def test_dict_drift_keys_are_sorted() -> None:
    """``_dict_drift_summary`` must sort ``value_drift_keys`` / ``only_in_*``
    so a dict-field drill-down (e.g. ``snmp``) serialises deterministically
    regardless of the key-set intersection's hash-randomised order — this was
    the residual cross-mesh non-determinism after the LAG fix."""
    src = {"b": 1, "a": 2, "c": 3, "z": 9}
    tgt = {"b": 10, "a": 20, "c": 30, "y": 8}
    out = run_full_mesh._dict_drift_summary(src, tgt)
    assert out["value_drift_keys"] == ["a", "b", "c"]
    assert out["only_in_source"] == ["z"]
    assert out["only_in_target"] == ["y"]


def test_relativize_tb_strips_repo_root() -> None:
    """The traceback path-relativizer removes the absolute repo root so the
    committed matrix never embeds an operator's local filesystem layout."""
    root = str(run_full_mesh._REPO_ROOT)
    sample = f'  File "{root}\\netcanon\\x.py", line 1\n  File "{root}/y.py"\n'
    out = run_full_mesh._relativize_tb(sample)
    assert root not in out
    assert "netcanon\\x.py" in out or "netcanon/x.py" in out
