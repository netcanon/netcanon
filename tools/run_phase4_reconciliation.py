#!/usr/bin/env python
"""
Phase 4a — cross-mesh fidelity reconciliation.

Joins Phase 1's mechanical drift JSON
(``tests/fixtures/real/_cross_mesh_runs/<timestamp>.json``) with the
Phase 3 vendor-doc-grounded expectation YAMLs
(``tests/fixtures/cross_vendor_expectations/<src>__<tgt>.yaml``) to
produce a per-cell variance classification: did each canonical field's
ACTUAL disposition (preserved vs drifted) match the EXPECTED disposition
(good / lossy / unsupported / not_applicable)?

What this is
------------
A *reconciliation* layer — it does NOT re-run translations.  It reads
the latest mechanical JSON in
``tests/fixtures/real/_cross_mesh_runs/`` and joins each cell to its
matching ``<source_codec>__<target_codec>.yaml``, then per-field
classifies the (actual, expected) tuple into one of:

* ``ALIGNED``                — preserved, expected good (the boring case)
* ``CODEC_BUG``              — drifted, expected good (high severity)
* ``EXPECTED_LOSSY``         — drifted, expected lossy (matches docs)
* ``EXPECTED_UNSUPPORTED``   — drifted, expected unsupported (matches docs)
* ``METHODOLOGY_ISSUE_under``— preserved against {lossy/unsupported/N-A}
                              expectation (codec doing more than docs claim,
                              OR Phase 1 false-positive: source had no
                              instance of the field so trivially preserved)
* ``METHODOLOGY_ISSUE_over`` — drifted against ``not_applicable``
                              (Phase 3 said "shouldn't apply"; Phase 1 saw
                              drift anyway — usually because the field is
                              absent on both sides and a sentinel mismatch
                              triggered)

The variance class drives downstream Phase 4b investigation: agents
only need to look at the CODEC_BUG buckets per source vendor; the
expected-* buckets ARE the ground truth.

Operator usage
--------------

    python tools/run_phase4_reconciliation.py [--mesh-json PATH]

* By default reads the most recent file in
  ``tests/fixtures/real/_cross_mesh_runs/``.  Pass ``--mesh-json`` to
  pin a specific run (useful when reconciling against a known-good
  baseline).
* Always writes a timestamped JSON to
  ``tests/fixtures/real/_phase4_runs/<timestamp>.json``.
* Always re-emits ``tests/fixtures/real/PHASE4_RECONCILIATION.md``
  (the skeleton report) with aggregate counts and per-cell severity
  matrix.  The "Top codec bugs" section is a placeholder — Phase 4b
  investigation agents fill it in per source vendor.

Constraints honoured
--------------------
* Standalone executable — no pytest dependency at runtime.
* Self-contained — no internet, no external API calls.
* Honest about misses — cells whose pair YAML doesn't exist (shouldn't
  happen since Phase 3 ships 56/56 pairs validated) are reported in
  the JSON's ``cells_without_expectation_yaml`` field rather than
  silently dropped.
* Idempotent — re-running produces a new timestamped JSON; the
  skeleton .md gets overwritten on every invocation.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


REAL_FIXTURES_ROOT = _REPO_ROOT / "tests" / "fixtures" / "real"
CROSS_MESH_RUNS_DIR = REAL_FIXTURES_ROOT / "_cross_mesh_runs"
PHASE4_RUNS_DIR = REAL_FIXTURES_ROOT / "_phase4_runs"
PHASE4_REPORT_PATH = REAL_FIXTURES_ROOT / "PHASE4_RECONCILIATION.md"
EXPECTATIONS_DIR = (
    _REPO_ROOT / "tests" / "fixtures" / "cross_vendor_expectations"
)


# Variance class labels — kept as module-level constants so unit tests
# and downstream consumers (Phase 4b investigation agents) can refer to
# them without reaching into magic strings.
VAR_ALIGNED = "ALIGNED"
VAR_CODEC_BUG = "CODEC_BUG"
VAR_EXPECTED_LOSSY = "EXPECTED_LOSSY"
VAR_EXPECTED_UNSUPPORTED = "EXPECTED_UNSUPPORTED"
VAR_METHODOLOGY_UNDER = "METHODOLOGY_ISSUE_under"
VAR_METHODOLOGY_OVER = "METHODOLOGY_ISSUE_over"

ALL_VARIANCES = (
    VAR_ALIGNED,
    VAR_CODEC_BUG,
    VAR_EXPECTED_LOSSY,
    VAR_EXPECTED_UNSUPPORTED,
    VAR_METHODOLOGY_UNDER,
    VAR_METHODOLOGY_OVER,
)


# ---------------------------------------------------------------------------
# Variance derivation (the single load-bearing decision in this module)
# ---------------------------------------------------------------------------


def derive_variance(
    actual: str, expected: str,
) -> tuple[str, str]:
    """Map an (actual, expected) field-disposition pair to its variance
    class + severity.

    Args:
        actual: One of ``"preserved"`` / ``"drifted"``.  Sourced from
            the per-field ``preserved`` boolean in the Phase 1 mechanical
            drift JSON.
        expected: One of ``"good"`` / ``"lossy"`` / ``"unsupported"`` /
            ``"not_applicable"``.  Sourced from the Phase 3 YAML's
            ``per_field_expectation[<field>].disposition``.

    Returns:
        ``(variance_class, severity)`` where variance_class is one of
        the ``VAR_*`` module constants and severity is one of
        ``"ok"`` / ``"low"`` / ``"medium"`` / ``"high"``.

    Raises:
        ValueError: If ``actual`` or ``expected`` is not a recognised
            literal — this is a bug in the caller, not a data
            classification issue.
    """
    if actual not in ("preserved", "drifted"):
        raise ValueError(
            f"actual must be 'preserved' or 'drifted'; got {actual!r}"
        )
    if expected not in ("good", "lossy", "unsupported", "not_applicable"):
        raise ValueError(
            f"expected must be one of "
            f"good/lossy/unsupported/not_applicable; got {expected!r}"
        )

    if actual == "preserved":
        if expected == "good":
            return VAR_ALIGNED, "ok"
        if expected == "lossy":
            return VAR_METHODOLOGY_UNDER, "low"
        if expected == "unsupported":
            return VAR_METHODOLOGY_UNDER, "medium"
        # not_applicable
        return VAR_METHODOLOGY_UNDER, "low"

    # actual == "drifted"
    if expected == "good":
        return VAR_CODEC_BUG, "high"
    if expected == "lossy":
        return VAR_EXPECTED_LOSSY, "ok"
    if expected == "unsupported":
        return VAR_EXPECTED_UNSUPPORTED, "ok"
    # not_applicable
    return VAR_METHODOLOGY_OVER, "low"


# ---------------------------------------------------------------------------
# Sub-field actual-disposition extraction
# ---------------------------------------------------------------------------


def _subfield_drift_in_list(
    parent_record: dict[str, Any], subfield: str,
) -> bool | None:
    """For a list-of-records canonical field (e.g. ``interfaces``,
    ``vlans``), determine whether a specific sub-field (e.g. ``name``,
    ``mtu``) drifted.

    Returns ``True`` if the sub-field drifted in any record, ``False``
    if every record's sub-field was preserved, or ``None`` if no
    determination is possible (parent missing the drift drill-down).

    The Phase 1 ``compute_field_disposition`` already drills per-record
    via :func:`_LIST_ID_KEYS`, so the sub-field signal is encoded in the
    keys of the ``drift`` dict.  Format:

        "interfaces[15] {'name': 'Loopback123'}": {
            "interface_type": {"source": "...", "target": "..."}
        }

    A sub-field has drifted iff its name appears as a key in any of the
    inner per-record diff dicts.
    """
    if parent_record.get("preserved"):
        return False
    drift = parent_record.get("drift")
    if not isinstance(drift, dict):
        # Drift summary is a string ("all N dropped", count drift, etc.)
        # — the entire list lost coherence.  Treat every sub-field as
        # drifted: we can't claim any individual sub-field was
        # preserved when records are missing wholesale.
        return True
    for record_key, record_diffs in drift.items():
        if record_key == "..." or not isinstance(record_diffs, dict):
            continue
        if subfield in record_diffs:
            return True
    # Drift dict exists but doesn't mention this sub-field — it was
    # preserved across every record that drifted on OTHER fields.
    return False


def _subfield_drift_in_dict(
    parent_record: dict[str, Any], subfield: str,
) -> bool | None:
    """For a singleton-dict canonical field (e.g. ``snmp``), determine
    whether a specific attribute drifted.

    The Phase 1 record stores ``source`` and ``target`` snapshots when
    the parent didn't preserve.  We compare the requested attribute on
    both sides directly.  Returns ``None`` only if neither snapshot is
    available.
    """
    if parent_record.get("preserved"):
        return False
    src = parent_record.get("source")
    tgt = parent_record.get("target")
    # ``target`` can legitimately be None (Phase 1 records that as
    # "snmp dropped entirely").  In that case every sub-field on the
    # source side has drifted to absence.
    if tgt is None:
        if isinstance(src, dict):
            return src.get(subfield) not in (None, "", [], {})
        return True
    if not isinstance(src, dict) or not isinstance(tgt, dict):
        return None
    return src.get(subfield) != tgt.get(subfield)


def actual_disposition(
    field_disposition: dict[str, Any], yaml_field_key: str,
) -> tuple[str, dict[str, Any] | None]:
    """Extract ``"preserved"`` or ``"drifted"`` for a YAML field key
    against the Phase 1 ``field_disposition`` block.

    YAML field keys come in three shapes:

    * ``hostname``, ``static_routes``, ``lags`` — top-level field name;
      look up directly.
    * ``interfaces[].name``, ``vlans[].id`` — list sub-field; look up
      the parent then drill into per-record drift drill-down.
    * ``snmp.community`` — dict sub-field; look up the parent then
      compare the attribute on the source/target snapshots.

    Returns ``(disposition, drift_detail)`` where drift_detail is the
    raw Phase 1 record (or a sub-field slice of it) when drifted, or
    ``None`` when preserved.  ``disposition`` is ``"missing"`` when the
    parent canonical field isn't in the Phase 1 dispositions at all
    (shouldn't happen — every audited field is unconditionally present
    — but we fail open rather than crash).
    """
    # Form: "interfaces[].name" — list sub-field.  Checked BEFORE the
    # "snmp.community" dot-split because list-subfield keys also contain
    # a dot ("[].").
    if yaml_field_key.endswith("[]") or "[]." in yaml_field_key:
        if "[]." in yaml_field_key:
            parent_name, subfield = yaml_field_key.split("[].", 1)
        else:
            # Bare "<list>[]" (no sub-field) — equivalent to the parent.
            parent_name = yaml_field_key.removesuffix("[]")
            subfield = None
        parent = field_disposition.get(parent_name)
        if parent is None:
            return "missing", None
        if subfield is None:
            return _disposition_from_record(parent)
        sub_drifted = _subfield_drift_in_list(parent, subfield)
        if sub_drifted:
            return "drifted", _slice_list_subfield(parent, subfield)
        return "preserved", None

    # Form: "snmp.community" — dict sub-field.
    if "." in yaml_field_key:
        parent_name, subfield = yaml_field_key.split(".", 1)
        parent = field_disposition.get(parent_name)
        if parent is None:
            return "missing", None
        sub_drifted = _subfield_drift_in_dict(parent, subfield)
        if sub_drifted is None:
            # Parent drifted but we can't tell about this attribute —
            # treat as drifted (conservative; the caller will see it
            # bucket per the parent's disposition).
            return "drifted", _slice_dict_subfield(parent, subfield)
        if sub_drifted:
            return "drifted", _slice_dict_subfield(parent, subfield)
        return "preserved", None

    # Form: bare top-level field name.
    parent = field_disposition.get(yaml_field_key)
    if parent is None:
        return "missing", None
    return _disposition_from_record(parent)


def _disposition_from_record(
    record: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Map a top-level Phase 1 record's ``preserved`` flag to the
    actual-disposition string + drift detail.
    """
    if record.get("preserved"):
        return "preserved", None
    detail = {
        k: record.get(k)
        for k in ("source", "target", "drift", "source_count", "target_count")
        if k in record
    }
    return "drifted", detail or None


def _slice_dict_subfield(
    parent: dict[str, Any], subfield: str,
) -> dict[str, Any]:
    """Build a compact drift-detail snippet for a dict sub-field."""
    src = parent.get("source")
    tgt = parent.get("target")
    snippet: dict[str, Any] = {"subfield": subfield}
    if isinstance(src, dict):
        snippet["source"] = src.get(subfield)
    if isinstance(tgt, dict):
        snippet["target"] = tgt.get(subfield)
    elif tgt is None and isinstance(src, dict):
        snippet["target"] = None
    return snippet


def _slice_list_subfield(
    parent: dict[str, Any], subfield: str,
) -> dict[str, Any]:
    """Build a compact drift-detail snippet for a list sub-field — the
    per-record diffs filtered down to just the requested attribute.
    """
    drift = parent.get("drift")
    snippet: dict[str, Any] = {"subfield": subfield}
    if not isinstance(drift, dict):
        # Wholesale list drift (count differs / all-dropped) — no
        # per-record detail to slice.  Preserve the summary string.
        snippet["drift_summary"] = drift
        return snippet
    per_record: dict[str, Any] = {}
    for record_key, record_diffs in drift.items():
        if not isinstance(record_diffs, dict):
            continue
        if subfield in record_diffs:
            per_record[record_key] = record_diffs[subfield]
    if per_record:
        snippet["per_record"] = per_record
    return snippet


# ---------------------------------------------------------------------------
# Expectation YAML loading
# ---------------------------------------------------------------------------


def load_expectation_yamls() -> dict[tuple[str, str], dict[str, Any]]:
    """Read every ``<src>__<tgt>.yaml`` and return a dict keyed by
    ``(source_codec, target_codec)`` with the raw parsed YAML body.

    Files that don't match the ``<src>__<tgt>.yaml`` shape (e.g. a
    stray README) are skipped silently — schema validation lives in
    ``tools/load_cross_vendor_expectations.py``.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if not EXPECTATIONS_DIR.is_dir():
        return out
    for path in sorted(EXPECTATIONS_DIR.glob("*.yaml")):
        stem = path.stem
        if "__" not in stem:
            continue
        src, tgt = stem.split("__", 1)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        out[(src, tgt)] = data
    return out


# ---------------------------------------------------------------------------
# Per-cell reconciliation
# ---------------------------------------------------------------------------


def reconcile_cell(
    cell: dict[str, Any],
    expectation: dict[str, Any] | None,
) -> dict[str, Any]:
    """Reconcile one Phase 1 cell against its Phase 3 expectation YAML.

    Returns a record carrying:
    * ``fixture`` / ``source_codec`` / ``target_codec`` /
      ``fixture_kind`` — pass-through identifiers
    * ``expectation_yaml`` — the YAML path used (or ``None`` if missing)
    * ``field_variances`` — per-YAML-field variance classification
    * ``summary`` — count of each variance class + total fields
    * ``cell_status`` — pass-through from Phase 1's WARN / OK / RENDER /
      PARSE / SOURCE classification, so downstream filters can skip
      cells that didn't even render
    """
    src = cell["source_codec"]
    tgt = cell["target_codec"]
    out: dict[str, Any] = {
        "fixture": cell["fixture"],
        "source_codec": src,
        "target_codec": tgt,
        "fixture_kind": cell.get("fixture_kind", "real"),
        "render_status": cell.get("render_status"),
        "roundtrip_parse_status": cell.get("roundtrip_parse_status"),
    }
    pair_yaml_path = (
        f"tests/fixtures/cross_vendor_expectations/{src}__{tgt}.yaml"
    )
    out["expectation_yaml"] = pair_yaml_path if expectation else None

    if expectation is None:
        out["expectation_missing"] = True
        out["field_variances"] = {}
        out["summary"] = {v: 0 for v in ALL_VARIANCES} | {
            "fields_total": 0,
        }
        return out

    field_disposition = cell.get("field_disposition") or {}
    if cell.get("render_status") != "ok" or cell.get(
        "roundtrip_parse_status",
    ) != "ok":
        # Render or parse failed — there's no field_disposition to
        # reconcile against.  Mark the cell explicitly and emit empty
        # field_variances so downstream consumers can filter.
        out["non_ok_status"] = True
        out["field_variances"] = {}
        out["summary"] = {v: 0 for v in ALL_VARIANCES} | {
            "fields_total": 0,
        }
        return out

    per_field = expectation.get("per_field_expectation") or {}
    field_variances: dict[str, Any] = {}
    counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    missing_in_phase1 = 0

    for yaml_field_key, entry in per_field.items():
        if not isinstance(entry, dict):
            continue
        expected = entry.get("disposition")
        if expected not in (
            "good", "lossy", "unsupported", "not_applicable",
        ):
            continue
        actual, drift_detail = actual_disposition(
            field_disposition, yaml_field_key,
        )
        if actual == "missing":
            # The audited canonical field doesn't appear in this
            # cell's Phase 1 dispositions at all.  This shouldn't
            # happen (every audited top-level field is always present
            # in field_disposition) — flag it but don't crash.
            missing_in_phase1 += 1
            field_variances[yaml_field_key] = {
                "actual": "missing",
                "expected": expected,
                "variance": "MISSING_PHASE1",
                "severity": "low",
            }
            continue
        variance, severity = derive_variance(actual, expected)
        record: dict[str, Any] = {
            "actual": actual,
            "expected": expected,
            "variance": variance,
            "severity": severity,
        }
        if drift_detail:
            record["drift_detail"] = drift_detail
        field_variances[yaml_field_key] = record
        counts[variance] += 1
        severity_counts[severity] += 1

    summary = {v: counts.get(v, 0) for v in ALL_VARIANCES}
    summary["fields_total"] = sum(counts.values())
    summary["missing_in_phase1"] = missing_in_phase1
    summary["severity_high"] = severity_counts.get("high", 0)
    summary["severity_medium"] = severity_counts.get("medium", 0)
    summary["severity_low"] = severity_counts.get("low", 0)
    summary["severity_ok"] = severity_counts.get("ok", 0)

    out["field_variances"] = field_variances
    out["summary"] = summary
    return out


# ---------------------------------------------------------------------------
# Run orchestration
# ---------------------------------------------------------------------------


def latest_mesh_run() -> Path:
    """Return the most recently modified ``*.json`` in
    ``_cross_mesh_runs/``.  Raises ``FileNotFoundError`` if none exist.
    """
    if not CROSS_MESH_RUNS_DIR.is_dir():
        raise FileNotFoundError(
            f"Cross-mesh runs dir does not exist: {CROSS_MESH_RUNS_DIR}.  "
            f"Run `python tools/run_full_mesh.py` first to generate one."
        )
    candidates = sorted(
        CROSS_MESH_RUNS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"No JSON runs in {CROSS_MESH_RUNS_DIR}.  "
            f"Run `python tools/run_full_mesh.py` first."
        )
    return candidates[0]


def run_reconciliation(mesh_json_path: Path) -> dict[str, Any]:
    """Read the Phase 1 mesh JSON + every Phase 3 YAML, reconcile, and
    return the structured result.
    """
    mesh = json.loads(mesh_json_path.read_text(encoding="utf-8"))
    expectations = load_expectation_yamls()

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cells_out: list[dict[str, Any]] = []
    intra_vendor_cells: list[dict[str, str]] = []
    cells_without_yaml: list[dict[str, str]] = []

    for cell in mesh.get("cells", []):
        src = cell["source_codec"]
        tgt = cell["target_codec"]
        key = (src, tgt)
        expectation = expectations.get(key)
        if expectation is None:
            # Intra-vendor self-pairs (e.g. arista_eos -> arista_eos)
            # are expected to have no Phase 3 YAML — Phase 3 is
            # cross-vendor only.  Bucket those separately so a
            # genuinely missing cross-vendor YAML stays loud.
            if src == tgt:
                intra_vendor_cells.append({
                    "fixture": cell["fixture"],
                    "source_codec": src,
                    "target_codec": tgt,
                })
            else:
                cells_without_yaml.append({
                    "fixture": cell["fixture"],
                    "source_codec": src,
                    "target_codec": tgt,
                })
        cells_out.append(reconcile_cell(cell, expectation))

    aggregate = aggregate_counts(cells_out)
    severity_matrix = build_severity_matrix(cells_out)
    pair_codec_bug_counts = build_pair_codec_bug_counts(cells_out)

    return {
        "started_utc": started,
        "mesh_json": mesh_json_path.relative_to(_REPO_ROOT).as_posix(),
        "mesh_run_started_utc": mesh.get("started_utc"),
        "cells_total": len(cells_out),
        "expectation_yamls_loaded": len(expectations),
        "intra_vendor_cells_skipped": intra_vendor_cells,
        "cells_without_expectation_yaml": cells_without_yaml,
        "aggregate": aggregate,
        "severity_matrix": severity_matrix,
        "pair_codec_bug_counts": pair_codec_bug_counts,
        "cells": cells_out,
    }


def aggregate_counts(cells: list[dict[str, Any]]) -> dict[str, int]:
    """Sum every variance bucket across every cell."""
    agg: Counter[str] = Counter()
    fields_total = 0
    severity: Counter[str] = Counter()
    for cell in cells:
        s = cell.get("summary") or {}
        for v in ALL_VARIANCES:
            agg[v] += s.get(v, 0)
        fields_total += s.get("fields_total", 0)
        for sev in ("high", "medium", "low", "ok"):
            severity[sev] += s.get(f"severity_{sev}", 0)
    out = {v: agg.get(v, 0) for v in ALL_VARIANCES}
    out["fields_total"] = fields_total
    out["severity_high"] = severity["high"]
    out["severity_medium"] = severity["medium"]
    out["severity_low"] = severity["low"]
    out["severity_ok"] = severity["ok"]
    return out


def build_severity_matrix(
    cells: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Per (source_codec, target_codec) cell — count of CODEC_BUG
    findings.  Returns nested dict: ``{src: {tgt: count, ...}, ...}``.
    Only counts the high-severity ``CODEC_BUG`` class — the matrix is
    designed to highlight the cells worth investigating in Phase 4b.
    """
    pair_counts: dict[tuple[str, str], int] = {}
    for cell in cells:
        s = cell.get("summary") or {}
        n = s.get(VAR_CODEC_BUG, 0)
        if n == 0:
            continue
        key = (cell["source_codec"], cell["target_codec"])
        pair_counts[key] = pair_counts.get(key, 0) + n
    out: dict[str, dict[str, int]] = {}
    for (src, tgt), n in pair_counts.items():
        out.setdefault(src, {})[tgt] = n
    return out


def build_pair_codec_bug_counts(
    cells: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flat sorted list of (source, target, codec_bug_count) for the
    top-N renderer in the markdown report.
    """
    pair_counts: dict[tuple[str, str], int] = {}
    for cell in cells:
        s = cell.get("summary") or {}
        n = s.get(VAR_CODEC_BUG, 0)
        if n == 0:
            continue
        key = (cell["source_codec"], cell["target_codec"])
        pair_counts[key] = pair_counts.get(key, 0) + n
    out = [
        {"source_codec": src, "target_codec": tgt, "codec_bug_count": n}
        for (src, tgt), n in pair_counts.items()
    ]
    out.sort(key=lambda r: (-r["codec_bug_count"], r["source_codec"], r["target_codec"]))
    return out


# ---------------------------------------------------------------------------
# Markdown skeleton
# ---------------------------------------------------------------------------


def render_skeleton_md(result: dict[str, Any]) -> str:
    """Render the top-level ``PHASE4_RECONCILIATION.md`` skeleton.

    Carries:
    * Generation timestamp + which mesh JSON was reconciled
    * Aggregate variance counts (one row per VAR_* class)
    * Per-(source × target) severity matrix (CODEC_BUG count per cell)
    * Top codec-bug pairs (placeholder for Phase 4b investigation)
    * Cross-references back to the per-run JSON + Phase 1 + Phase 3
    """
    lines: list[str] = []
    lines.append("# Phase 4 — Cross-mesh fidelity reconciliation\n")
    lines.append(
        f"Generated by `tools/run_phase4_reconciliation.py` on "
        f"{result['started_utc']}.  Reconciles Phase 1 mechanical drift "
        f"(`{result['mesh_json']}`, run "
        f"{result.get('mesh_run_started_utc', 'unknown')}) against the "
        f"{result['expectation_yamls_loaded']} per-pair Phase 3 "
        f"expectation YAMLs.\n"
    )
    lines.append(
        f"Total cells reconciled: **{result['cells_total']}**.  Each "
        f"cell carries one ``field_variances`` entry per audited "
        f"canonical field present in its pair YAML.\n"
    )
    intra_n = len(result.get("intra_vendor_cells_skipped", []))
    if intra_n:
        lines.append(
            f"Intra-vendor self-pairs skipped (no Phase 3 YAML — by "
            f"design, Phase 3 is cross-vendor only): **{intra_n}** "
            f"cell(s).  Their fields show up in the per-run JSON with "
            f"empty ``field_variances``.\n"
        )
    if result.get("cells_without_expectation_yaml"):
        n = len(result["cells_without_expectation_yaml"])
        lines.append(
            f"**Warning:** {n} cross-vendor cell(s) had no matching "
            f"pair YAML.  Phase 3 ships 56/56 cross-vendor pairs "
            f"validated; if this number is non-zero, check "
            f"``tests/fixtures/cross_vendor_expectations/`` for "
            f"missing files.  Detail in the per-run JSON.\n"
        )

    lines.append("## Aggregate variance counts\n")
    agg = result["aggregate"]
    lines.append("| Variance class | Count | Severity |")
    lines.append("|---|---:|---|")
    severity_for: dict[str, str] = {
        VAR_ALIGNED: "ok",
        VAR_EXPECTED_LOSSY: "ok",
        VAR_EXPECTED_UNSUPPORTED: "ok",
        VAR_METHODOLOGY_UNDER: "low/medium",
        VAR_METHODOLOGY_OVER: "low",
        VAR_CODEC_BUG: "**high**",
    }
    for v in ALL_VARIANCES:
        lines.append(f"| {v} | {agg.get(v, 0)} | {severity_for[v]} |")
    lines.append(f"| **Total field-cells classified** | **{agg.get('fields_total', 0)}** | |")
    lines.append("")
    lines.append(
        "Severity roll-up: "
        f"{agg.get('severity_high', 0)} high, "
        f"{agg.get('severity_medium', 0)} medium, "
        f"{agg.get('severity_low', 0)} low, "
        f"{agg.get('severity_ok', 0)} ok.\n"
    )

    lines.append("## Per-cell matrix — CODEC_BUG counts\n")
    lines.append(
        "Each cell shows the number of CODEC_BUG (drifted-where-docs-"
        "say-good) findings summed across every fixture in that "
        "(source codec, target codec) pair.  Empty cells = zero "
        "high-severity findings (could still have lower-severity "
        "variance — see per-cell JSON).  Diagonal cells are intra-"
        "vendor round-trips and should normally be zero.\n"
    )
    matrix = result["severity_matrix"]
    targets = sorted({
        tgt
        for tgt_map in matrix.values()
        for tgt in tgt_map
    } | _all_target_codecs(result))
    sources = sorted(set(matrix.keys()) | _all_source_codecs(result))
    if not sources or not targets:
        lines.append("(no CODEC_BUG findings across any cell)\n")
    else:
        header = ["src ↓ / tgt →"] + targets
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["---"] * len(header)) + "|")
        for src in sources:
            row = [src]
            for tgt in targets:
                n = matrix.get(src, {}).get(tgt, 0)
                row.append(str(n) if n else "")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    lines.append("## Top codec-bug pairs (severity=high)\n")
    lines.append(
        "Ordered by total CODEC_BUG findings across every fixture in "
        "the (source → target) pair.  Phase 4b investigation agents "
        "will fill in per-vendor findings reports under "
        "``tests/fixtures/real/phase4_findings_<source_vendor>.md`` — "
        "this skeleton just lists the pairs that need investigation.\n"
    )
    pairs = result["pair_codec_bug_counts"]
    if not pairs:
        lines.append("No pairs with CODEC_BUG findings — every drifted "
                     "field aligned with a documented expectation.\n")
    else:
        lines.append("| Rank | Source codec | Target codec | Σ CODEC_BUG |")
        lines.append("|---:|---|---|---:|")
        for rank, rec in enumerate(pairs[:20], start=1):
            lines.append(
                f"| {rank} | {rec['source_codec']} | "
                f"{rec['target_codec']} | {rec['codec_bug_count']} |"
            )
        lines.append("")
        lines.append(
            "(Top 20 shown.  Full list in the per-run JSON's "
            "``pair_codec_bug_counts`` array.)\n"
        )

    lines.append("## Per-vendor findings reports — Phase 4b placeholder\n")
    lines.append(
        "This section is populated by Phase 4b investigation agents.  "
        "Each agent reads the per-run JSON in "
        "``tests/fixtures/real/_phase4_runs/`` for its assigned source "
        "vendor and produces a "
        "``tests/fixtures/real/phase4_findings_<source_vendor>.md`` "
        "with per-CODEC_BUG triage notes (fixture path, target codec, "
        "field, drift detail, suspected root cause, suggested fix or "
        "expectation-YAML correction).\n"
    )

    lines.append("## See also\n")
    lines.append(
        "- ``tools/run_phase4_reconciliation.py`` — generation script\n"
        "- ``tests/fixtures/real/_phase4_runs/`` — per-run JSON outputs "
        "(gitignored except the latest, which is committed for Phase 4b "
        "agents to read)\n"
        "- ``tests/fixtures/cross_vendor_expectations/`` — Phase 3 "
        "vendor-doc-grounded expectations (56 pair YAMLs)\n"
        "- ``tests/fixtures/real/CROSS_MESH_RESULTS.md`` — Phase 1 "
        "mechanical drift matrix (the input this report joins against)\n"
        "- ``tools/run_full_mesh.py`` — Phase 1 generator\n"
    )
    return "\n".join(lines) + "\n"


def _all_source_codecs(result: dict[str, Any]) -> set[str]:
    return {c["source_codec"] for c in result["cells"]}


def _all_target_codecs(result: dict[str, Any]) -> set[str]:
    return {c["target_codec"] for c in result["cells"]}


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


def write_json(result: dict[str, Any]) -> Path:
    """Write the reconciliation result twice:

    * ``<timestamp>.json`` — the per-run archive (gitignored)
    * ``latest.json``      — a stable filename overwritten on every
                             invocation, committed alongside the
                             skeleton .md so Phase 4b investigation
                             agents always have an up-to-date input
                             without the operator having to ``git add``
                             the timestamped name each time.

    Returns the timestamped path (the canonical "this run" identifier);
    ``latest.json`` is a side-effect mirror.
    """
    PHASE4_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    body = json.dumps(result, indent=2, default=str)
    out_path = PHASE4_RUNS_DIR / f"{timestamp}.json"
    out_path.write_text(body, encoding="utf-8")
    latest_path = PHASE4_RUNS_DIR / "latest.json"
    latest_path.write_text(body, encoding="utf-8")
    return out_path


def write_skeleton(body: str) -> Path:
    PHASE4_REPORT_PATH.write_text(body, encoding="utf-8")
    return PHASE4_REPORT_PATH


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile the latest Phase 1 mechanical drift JSON against "
            "the Phase 3 per-pair expectation YAMLs."
        ),
    )
    parser.add_argument(
        "--mesh-json",
        type=Path,
        default=None,
        help=(
            "Path to a specific Phase 1 cross-mesh JSON.  If omitted, "
            "the most recent file under "
            "tests/fixtures/real/_cross_mesh_runs/ is used."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress prints; only emit the final JSON path.",
    )
    args = parser.parse_args(argv)

    if args.mesh_json is None:
        mesh_json_path = latest_mesh_run()
    else:
        mesh_json_path = args.mesh_json
        if not mesh_json_path.is_file():
            print(
                f"ERROR: --mesh-json {mesh_json_path} does not exist",
                file=sys.stderr,
            )
            return 2

    if not args.quiet:
        print(
            f"Reconciling against {mesh_json_path.name}...",
            file=sys.stderr,
        )

    result = run_reconciliation(mesh_json_path)
    json_path = write_json(result)
    body = render_skeleton_md(result)
    md_path = write_skeleton(body)

    if not args.quiet:
        agg = result["aggregate"]
        print(
            f"Reconciled {result['cells_total']} cells "
            f"({agg.get('fields_total', 0)} field-cells classified):",
            file=sys.stderr,
        )
        for v in ALL_VARIANCES:
            print(f"  {v:30s} {agg.get(v, 0)}", file=sys.stderr)
        print(f"Wrote JSON to {json_path}", file=sys.stderr)
        print(f"Wrote skeleton to {md_path}", file=sys.stderr)

    print(json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
