"""
Unit tests for ``tools/run_phase4_reconciliation.py``'s variance
derivation + per-cell reconciliation logic.

The runner script itself runs end-to-end against the committed Phase 1
JSON and the Phase 3 YAMLs; these tests pin the *building blocks* —
the (actual, expected) → variance class mapping, the sub-field actual-
disposition extraction, and the per-cell reconciliation result shape —
so a regression in :func:`derive_variance` or
:func:`actual_disposition` fails loud rather than silently
mis-classifying every cell in the next reconciliation pass.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


# Load the runner module without making ``tools/`` a package — same
# pattern as ``test_run_full_mesh.py``.
_RUNNER_PATH = (
    Path(__file__).resolve().parents[3]
    / "tools"
    / "run_phase4_reconciliation.py"
)
_spec = importlib.util.spec_from_file_location(
    "run_phase4_reconciliation", _RUNNER_PATH,
)
assert _spec is not None and _spec.loader is not None
recon = importlib.util.module_from_spec(_spec)
sys.modules["run_phase4_reconciliation"] = recon
_spec.loader.exec_module(recon)


derive_variance = recon.derive_variance
actual_disposition = recon.actual_disposition
reconcile_cell = recon.reconcile_cell


# ---------------------------------------------------------------------------
# derive_variance — one test per row of the variance table
# ---------------------------------------------------------------------------


def test_preserved_good_is_aligned() -> None:
    variance, severity = derive_variance("preserved", "good")
    assert variance == recon.VAR_ALIGNED
    assert severity == "ok"


def test_preserved_lossy_is_methodology_under_low() -> None:
    variance, severity = derive_variance("preserved", "lossy")
    assert variance == recon.VAR_METHODOLOGY_UNDER
    assert severity == "low"


def test_preserved_unsupported_is_methodology_under_medium() -> None:
    """Codec did something the docs say is impossible — medium severity
    because either the codec is over-reaching OR the YAML is wrong, but
    either way the docs/code disagree more sharply than for lossy."""
    variance, severity = derive_variance("preserved", "unsupported")
    assert variance == recon.VAR_METHODOLOGY_UNDER
    assert severity == "medium"


def test_preserved_not_applicable_is_methodology_under_low() -> None:
    variance, severity = derive_variance("preserved", "not_applicable")
    assert variance == recon.VAR_METHODOLOGY_UNDER
    assert severity == "low"


def test_drifted_good_is_codec_bug_high() -> None:
    """The headline finding — Phase 3 said this should preserve and
    Phase 1 says it didn't.  Phase 4b investigation agents look at
    these first."""
    variance, severity = derive_variance("drifted", "good")
    assert variance == recon.VAR_CODEC_BUG
    assert severity == "high"


def test_drifted_lossy_is_expected_lossy_ok() -> None:
    variance, severity = derive_variance("drifted", "lossy")
    assert variance == recon.VAR_EXPECTED_LOSSY
    assert severity == "ok"


def test_drifted_unsupported_is_expected_unsupported_ok() -> None:
    variance, severity = derive_variance("drifted", "unsupported")
    assert variance == recon.VAR_EXPECTED_UNSUPPORTED
    assert severity == "ok"


def test_drifted_not_applicable_is_methodology_over_low() -> None:
    variance, severity = derive_variance("drifted", "not_applicable")
    assert variance == recon.VAR_METHODOLOGY_OVER
    assert severity == "low"


def test_unrecognised_actual_raises() -> None:
    with pytest.raises(ValueError):
        derive_variance("preserved-ish", "good")


def test_unrecognised_expected_raises() -> None:
    with pytest.raises(ValueError):
        derive_variance("preserved", "maybe")


# ---------------------------------------------------------------------------
# actual_disposition — top-level, list sub-field, dict sub-field
# ---------------------------------------------------------------------------


def test_top_level_preserved() -> None:
    fd = {"hostname": {"preserved": True}}
    actual, detail = actual_disposition(fd, "hostname")
    assert actual == "preserved"
    assert detail is None


def test_top_level_drifted_carries_drift_detail() -> None:
    fd = {
        "hostname": {
            "preserved": False,
            "source": "r1",
            "target": "r2",
            "drift": "hostname: 'r1' → 'r2'",
        }
    }
    actual, detail = actual_disposition(fd, "hostname")
    assert actual == "drifted"
    assert detail is not None
    assert detail["source"] == "r1"
    assert detail["target"] == "r2"


def test_list_subfield_drifted() -> None:
    """``interfaces[].interface_type`` drifted — the parent ``interfaces``
    record's drift dict mentions ``interface_type`` under one of the
    per-record keys."""
    fd = {
        "interfaces": {
            "preserved": False,
            "source_count": 17,
            "target_count": 17,
            "drift": {
                "interfaces[15] {'name': 'Loopback123'}": {
                    "interface_type": {
                        "source": "ianaift:softwareLoopback",
                        "target": "ianaift:ethernetCsmacd",
                    },
                },
            },
        },
    }
    actual, detail = actual_disposition(fd, "interfaces[].interface_type")
    assert actual == "drifted"
    assert detail is not None
    assert "per_record" in detail
    assert any(
        "interfaces[15]" in k for k in detail["per_record"]
    )


def test_list_subfield_preserved_when_other_subfield_drifts() -> None:
    """If the parent drifted but only on a different sub-field, this
    sub-field counts as preserved.  Example: ``interfaces[].mtu``
    when only ``interface_type`` drifted."""
    fd = {
        "interfaces": {
            "preserved": False,
            "drift": {
                "interfaces[0] {'name': 'eth0'}": {
                    "interface_type": {"source": "x", "target": "y"},
                },
            },
        },
    }
    actual, detail = actual_disposition(fd, "interfaces[].mtu")
    assert actual == "preserved"
    assert detail is None


def test_list_subfield_drifted_when_parent_wholesale_drift() -> None:
    """If the parent's drift summary is a string (count drift,
    all-dropped) we can't pinpoint a single sub-field — every
    sub-field counts as drifted because records went missing."""
    fd = {
        "interfaces": {
            "preserved": False,
            "source_count": 5,
            "target_count": 0,
            "drift": "all 5 interfaces dropped",
        },
    }
    actual, detail = actual_disposition(fd, "interfaces[].name")
    assert actual == "drifted"
    assert detail is not None


def test_dict_subfield_preserved_when_parent_preserved() -> None:
    fd = {"snmp": {"preserved": True}}
    actual, detail = actual_disposition(fd, "snmp.community")
    assert actual == "preserved"
    assert detail is None


def test_dict_subfield_drifted_when_target_is_none() -> None:
    """Phase 1 records ``snmp`` dropped entirely as
    ``source: {...}, target: None``.  Every populated source attribute
    has drifted to absence."""
    fd = {
        "snmp": {
            "preserved": False,
            "source": {
                "community": "private",
                "location": "",
                "contact": "",
                "trap_hosts": [],
                "v3_users": [],
            },
            "target": None,
        },
    }
    actual_comm, _ = actual_disposition(fd, "snmp.community")
    assert actual_comm == "drifted"
    # Empty string source attribute → drift to None still drifted
    # (target had no SNMP at all), but it normalises to None which
    # the helper treats as "not populated" — preserved.
    actual_loc, _ = actual_disposition(fd, "snmp.location")
    assert actual_loc == "preserved"


def test_dict_subfield_drifted_when_attributes_differ() -> None:
    fd = {
        "snmp": {
            "preserved": False,
            "source": {"community": "public", "location": "rackA"},
            "target": {"community": "public", "location": "rackB"},
        },
    }
    actual_comm, _ = actual_disposition(fd, "snmp.community")
    assert actual_comm == "preserved"
    actual_loc, _ = actual_disposition(fd, "snmp.location")
    assert actual_loc == "drifted"


def test_missing_parent_field_returns_missing() -> None:
    """If the YAML keys a field the Phase 1 dispositions don't carry,
    the disposition is ``missing`` rather than crashing."""
    fd = {}
    actual, detail = actual_disposition(fd, "hostname")
    assert actual == "missing"
    assert detail is None


# ---------------------------------------------------------------------------
# reconcile_cell — end-to-end shape
# ---------------------------------------------------------------------------


def test_reconcile_cell_emits_summary_with_all_variance_buckets() -> None:
    cell = {
        "fixture": "tests/fixtures/real/arista_eos/example.txt",
        "fixture_kind": "real",
        "source_codec": "arista_eos",
        "target_codec": "juniper_junos",
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "field_disposition": {
            "hostname": {"preserved": True},
            "vlans": {
                "preserved": False,
                "drift": {
                    "vlans[0] {'id': 10, 'name': 'USERS'}": {
                        "name": {"source": "USERS", "target": "users"},
                    },
                },
            },
        },
    }
    expectation = {
        "per_field_expectation": {
            "hostname": {"disposition": "good"},
            "vlans[].name": {"disposition": "lossy", "reason": "..."},
        },
    }
    result = reconcile_cell(cell, expectation)
    assert result["source_codec"] == "arista_eos"
    assert result["target_codec"] == "juniper_junos"
    assert result["expectation_yaml"] == (
        "tests/fixtures/cross_vendor_expectations/"
        "arista_eos__juniper_junos.yaml"
    )
    fv = result["field_variances"]
    assert fv["hostname"]["variance"] == recon.VAR_ALIGNED
    assert fv["vlans[].name"]["variance"] == recon.VAR_EXPECTED_LOSSY
    summary = result["summary"]
    assert summary[recon.VAR_ALIGNED] == 1
    assert summary[recon.VAR_EXPECTED_LOSSY] == 1
    assert summary[recon.VAR_CODEC_BUG] == 0
    assert summary["fields_total"] == 2


def test_reconcile_cell_codec_bug_when_drift_against_good() -> None:
    cell = {
        "fixture": "f.txt",
        "fixture_kind": "real",
        "source_codec": "arista_eos",
        "target_codec": "juniper_junos",
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "field_disposition": {
            "hostname": {
                "preserved": False,
                "source": "r1",
                "target": "",
                "drift": "hostname: 'r1' → ''",
            },
        },
    }
    expectation = {
        "per_field_expectation": {
            "hostname": {"disposition": "good"},
        },
    }
    result = reconcile_cell(cell, expectation)
    assert result["field_variances"]["hostname"]["variance"] == (
        recon.VAR_CODEC_BUG
    )
    assert result["field_variances"]["hostname"]["severity"] == "high"
    assert result["summary"][recon.VAR_CODEC_BUG] == 1
    assert result["summary"]["severity_high"] == 1


def test_reconcile_cell_handles_missing_expectation_yaml() -> None:
    cell = {
        "fixture": "f.txt",
        "fixture_kind": "real",
        "source_codec": "arista_eos",
        "target_codec": "juniper_junos",
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "field_disposition": {"hostname": {"preserved": True}},
    }
    result = reconcile_cell(cell, expectation=None)
    assert result["expectation_missing"] is True
    assert result["expectation_yaml"] is None
    assert result["field_variances"] == {}
    assert result["summary"]["fields_total"] == 0


def test_reconcile_cell_handles_render_error() -> None:
    """Cells where Phase 1 couldn't even render get an empty
    ``field_variances`` — there's nothing to reconcile."""
    cell = {
        "fixture": "f.txt",
        "fixture_kind": "real",
        "source_codec": "arista_eos",
        "target_codec": "juniper_junos",
        "render_status": "render_error",
        "roundtrip_parse_status": "skipped",
    }
    expectation = {"per_field_expectation": {"hostname": {"disposition": "good"}}}
    result = reconcile_cell(cell, expectation)
    assert result["non_ok_status"] is True
    assert result["field_variances"] == {}
    assert result["summary"]["fields_total"] == 0
