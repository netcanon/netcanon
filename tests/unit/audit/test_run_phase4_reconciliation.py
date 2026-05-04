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


# ---------------------------------------------------------------------------
# STRUCTURAL_ONLY collapse — one structural drift signal per (cell,
# parent-list), not amplified across every per-field key on that list.
#
# The bug being fixed: when ``interfaces`` had a wholesale list-length
# drift (``count drift: 17 → 2 (interfaces)`` or ``all 5 interfaces
# dropped``), Phase 1 emitted that as a single string under
# ``drift``.  The pre-fix comparator's ``_subfield_drift_in_list``
# returned True for every sub-field on a string-drift parent — so each
# of ``interfaces[].description``, ``interfaces[].mtu``,
# ``interfaces[].enabled``, ... got an independent CODEC_BUG entry,
# multiplying one structural signal across N per-field keys.
#
# Fix: the FIRST sub-field of each list-parent in each cell keeps its
# original variance class (typically CODEC_BUG when expected="good"),
# carrying the ``drift_summary`` string in drift_detail.  Subsequent
# sub-fields of the SAME parent list in the SAME cell are reclassified
# STRUCTURAL_ONLY (low severity), with a ``structural_owner`` pointer
# back to the YAML key that owns the canonical signal.  Real per-field
# drift on surviving rows (which Phase 1 represents via a per-record
# dict, surfaced as ``per_record`` in drift_detail) is NEVER collapsed.
# ---------------------------------------------------------------------------


def test_count_drift_emits_single_signal_per_cell() -> None:
    """Wholesale ``count drift`` on ``interfaces`` should fire ONE
    CODEC_BUG (on the first per-field key encountered) and reclassify
    every other per-field key on the same list to STRUCTURAL_ONLY."""
    cell = {
        "fixture": "f.txt",
        "fixture_kind": "real",
        "source_codec": "arista_eos",
        "target_codec": "juniper_junos",
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "field_disposition": {
            "interfaces": {
                "preserved": False,
                "source_count": 17,
                "target_count": 2,
                "drift": "count drift: 17 → 2 (interfaces)",
            },
        },
    }
    expectation = {
        "per_field_expectation": {
            "interfaces[].name": {"disposition": "good"},
            "interfaces[].description": {"disposition": "good"},
            "interfaces[].enabled": {"disposition": "good"},
            "interfaces[].mtu": {"disposition": "good"},
            "interfaces[].ipv4_addresses": {"disposition": "good"},
            "interfaces[].ipv6_addresses": {"disposition": "good"},
            "interfaces[].lag_member_of": {"disposition": "good"},
        },
    }
    result = reconcile_cell(cell, expectation)
    fv = result["field_variances"]
    # First sub-field encountered (insertion order: ``name``) owns the
    # canonical CODEC_BUG signal.
    assert fv["interfaces[].name"]["variance"] == recon.VAR_CODEC_BUG
    assert fv["interfaces[].name"]["severity"] == "high"
    name_dd = fv["interfaces[].name"]["drift_detail"]
    assert isinstance(name_dd.get("drift_summary"), str)
    assert "count drift" in name_dd["drift_summary"]
    # Every subsequent sub-field of ``interfaces`` collapses to
    # STRUCTURAL_ONLY with a back-pointer to the canonical owner.
    for key in (
        "interfaces[].description",
        "interfaces[].enabled",
        "interfaces[].mtu",
        "interfaces[].ipv4_addresses",
        "interfaces[].ipv6_addresses",
        "interfaces[].lag_member_of",
    ):
        assert fv[key]["variance"] == recon.VAR_STRUCTURAL_ONLY, (
            f"{key} should be STRUCTURAL_ONLY, got {fv[key]['variance']}"
        )
        assert fv[key]["severity"] == "low"
        assert fv[key]["drift_detail"]["structural_owner"] == (
            "interfaces[].name"
        )
    # Aggregate: exactly one CODEC_BUG, six STRUCTURAL_ONLY, no other
    # high-severity finding.
    assert result["summary"][recon.VAR_CODEC_BUG] == 1
    assert result["summary"][recon.VAR_STRUCTURAL_ONLY] == 6
    assert result["summary"]["severity_high"] == 1
    assert result["summary"]["severity_low"] == 6


def test_count_drift_with_real_per_field_drift_preserves_both() -> None:
    """If Phase 1 surfaces per-record drift (``per_record`` populated
    in drift_detail) — i.e. the surviving rows actually differ on a
    sub-field — that per-field signal MUST keep its CODEC_BUG, even
    when another sub-field on the same list has a structural-only
    drift.  This guards against masking real per-field drift behind
    the structural-collapse rule."""
    cell = {
        "fixture": "f.txt",
        "fixture_kind": "real",
        "source_codec": "arista_eos",
        "target_codec": "juniper_junos",
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "field_disposition": {
            # One field with per-record drift on the surviving rows
            # (counts match) — should fire CODEC_BUG with per_record
            # detail, NOT collapse.
            "interfaces": {
                "preserved": False,
                "source_count": 4,
                "target_count": 4,
                "drift": {
                    "interfaces[0] {'name': 'eth0'}": {
                        "description": {
                            "source": "uplink-A",
                            "target": "uplink-B",
                        },
                    },
                },
            },
        },
    }
    expectation = {
        "per_field_expectation": {
            "interfaces[].name": {"disposition": "good"},
            "interfaces[].description": {"disposition": "good"},
            "interfaces[].mtu": {"disposition": "good"},
        },
    }
    result = reconcile_cell(cell, expectation)
    fv = result["field_variances"]
    # ``description`` actually drifted per-record — keeps CODEC_BUG.
    assert fv["interfaces[].description"]["variance"] == recon.VAR_CODEC_BUG
    assert "per_record" in fv["interfaces[].description"]["drift_detail"]
    # ``name`` and ``mtu`` did NOT drift on any surviving row — they
    # come back as ``preserved`` (the parent's drift dict doesn't
    # mention them) and so don't become STRUCTURAL_ONLY either.
    assert fv["interfaces[].name"]["variance"] == recon.VAR_ALIGNED
    assert fv["interfaces[].mtu"]["variance"] == recon.VAR_ALIGNED
    # Nothing collapses to STRUCTURAL_ONLY here — there's no wholesale
    # list-length signal in play.
    assert result["summary"][recon.VAR_STRUCTURAL_ONLY] == 0
    assert result["summary"][recon.VAR_CODEC_BUG] == 1


def test_count_drift_plus_real_per_field_drift_on_same_list_both_emit() -> None:
    """Edge case combining both signals on the SAME list parent: a
    wholesale ``count drift`` PLUS per-record drift on a surviving
    row's sub-field.  The per-record-driven sub-field MUST keep its
    CODEC_BUG signal; only the structural-only sub-fields collapse.

    In practice Phase 1 emits either a string OR a per-record dict, not
    both — so this scenario cannot reach the comparator from the real
    pipeline.  But the comparator must be defensive against that
    invariant being relaxed in the future, so we still test the case
    by handing it both signals manually.

    Implementation note: ``actual_disposition`` reads the parent's
    ``drift`` value once.  When the upstream emits a dict with
    per-record drill-down, ``_slice_list_subfield`` produces a
    ``per_record`` slice and the structural-collapse condition (which
    requires a string ``drift_summary``) doesn't fire — so even on the
    same list parent, the per-record entry goes through unmolested."""
    cell = {
        "fixture": "f.txt",
        "fixture_kind": "real",
        "source_codec": "arista_eos",
        "target_codec": "juniper_junos",
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "field_disposition": {
            "interfaces": {
                "preserved": False,
                "source_count": 4,
                "target_count": 4,
                "drift": {
                    "interfaces[2] {'name': 'eth2'}": {
                        "description": {
                            "source": "old", "target": "new",
                        },
                    },
                },
            },
        },
    }
    expectation = {
        "per_field_expectation": {
            "interfaces[].description": {"disposition": "good"},
            "interfaces[].mtu": {"disposition": "good"},
        },
    }
    result = reconcile_cell(cell, expectation)
    fv = result["field_variances"]
    # Real per-record drift survives as a CODEC_BUG with per_record
    # detail.
    assert fv["interfaces[].description"]["variance"] == recon.VAR_CODEC_BUG
    assert "per_record" in fv["interfaces[].description"]["drift_detail"]
    # ``mtu`` wasn't in any per-record diff — disposition is preserved,
    # so it shows up as ALIGNED rather than STRUCTURAL_ONLY (no
    # structural signal to collapse onto).
    assert fv["interfaces[].mtu"]["variance"] == recon.VAR_ALIGNED


def test_no_count_drift_no_change_in_behavior() -> None:
    """When the parent list preserves entirely, every per-field key
    classifies as ALIGNED (good) — no STRUCTURAL_ONLY artefact, no
    CODEC_BUG."""
    cell = {
        "fixture": "f.txt",
        "fixture_kind": "real",
        "source_codec": "arista_eos",
        "target_codec": "juniper_junos",
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "field_disposition": {
            "interfaces": {"preserved": True, "source_count": 4, "target_count": 4},
        },
    }
    expectation = {
        "per_field_expectation": {
            "interfaces[].name": {"disposition": "good"},
            "interfaces[].description": {"disposition": "good"},
            "interfaces[].mtu": {"disposition": "good"},
        },
    }
    result = reconcile_cell(cell, expectation)
    fv = result["field_variances"]
    for key in (
        "interfaces[].name",
        "interfaces[].description",
        "interfaces[].mtu",
    ):
        assert fv[key]["variance"] == recon.VAR_ALIGNED
    assert result["summary"][recon.VAR_STRUCTURAL_ONLY] == 0
    assert result["summary"][recon.VAR_CODEC_BUG] == 0
    assert result["summary"][recon.VAR_ALIGNED] == 3


def test_count_drift_on_vlans_also_collapses() -> None:
    """The collapse rule applies to any list parent, not just
    ``interfaces``.  A wholesale ``all N vlans dropped`` parent should
    behave the same way."""
    cell = {
        "fixture": "f.txt",
        "fixture_kind": "real",
        "source_codec": "arista_eos",
        "target_codec": "mikrotik_routeros",
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "field_disposition": {
            "vlans": {
                "preserved": False,
                "source_count": 5,
                "target_count": 0,
                "drift": "all 5 vlans dropped",
            },
        },
    }
    expectation = {
        "per_field_expectation": {
            "vlans[].id": {"disposition": "good"},
            "vlans[].name": {"disposition": "good"},
            "vlans[].interface_members": {"disposition": "good"},
        },
    }
    result = reconcile_cell(cell, expectation)
    fv = result["field_variances"]
    # First key claims the canonical structural CODEC_BUG.
    assert fv["vlans[].id"]["variance"] == recon.VAR_CODEC_BUG
    assert "all 5 vlans dropped" in (
        fv["vlans[].id"]["drift_detail"]["drift_summary"]
    )
    # Subsequent keys collapse.
    assert fv["vlans[].name"]["variance"] == recon.VAR_STRUCTURAL_ONLY
    assert fv["vlans[].interface_members"]["variance"] == (
        recon.VAR_STRUCTURAL_ONLY
    )
    assert result["summary"][recon.VAR_CODEC_BUG] == 1
    assert result["summary"][recon.VAR_STRUCTURAL_ONLY] == 2


# ---------------------------------------------------------------------------
# TRIVIAL_EMPTY — both sides empty/zero, no data to validate against
#
# Wave 10α.  See the Phase 1 unit tests in test_run_full_mesh.py for the
# disposition-flag mechanics.  These tests pin the Phase 4 mapping:
# trivially_preserved (the third actual-disposition literal alongside
# preserved/drifted) becomes TRIVIAL_EMPTY regardless of expectation.
# ---------------------------------------------------------------------------


def test_derive_variance_trivially_preserved_lossy_is_trivial_empty_ok() -> None:
    """A trivially-empty cell against a lossy expectation is no longer
    METHODOLOGY_ISSUE_under — the YAML claim couldn't be tested."""
    variance, severity = derive_variance("trivially_preserved", "lossy")
    assert variance == recon.VAR_TRIVIAL_EMPTY
    assert severity == "ok"


def test_derive_variance_trivially_preserved_unsupported_is_trivial_empty_ok() -> None:
    variance, severity = derive_variance("trivially_preserved", "unsupported")
    assert variance == recon.VAR_TRIVIAL_EMPTY
    assert severity == "ok"


def test_derive_variance_trivially_preserved_good_is_trivial_empty_ok() -> None:
    """Even when expectation is ``good``, a trivial-empty cell shouldn't
    count as ALIGNED — there was no data to actually validate."""
    variance, severity = derive_variance("trivially_preserved", "good")
    assert variance == recon.VAR_TRIVIAL_EMPTY
    assert severity == "ok"


def test_derive_variance_trivially_preserved_not_applicable_is_trivial_empty() -> None:
    variance, severity = derive_variance(
        "trivially_preserved", "not_applicable",
    )
    assert variance == recon.VAR_TRIVIAL_EMPTY
    assert severity == "ok"


def test_preserved_lossy_remains_methodology_under_regression_guard() -> None:
    """Regression guard: introducing TRIVIAL_EMPTY must NOT swallow
    real preservation-where-YAML-says-lossy.  Real over-claim signal
    (populated data preserved on both sides where YAML says lossy)
    keeps firing METHODOLOGY_ISSUE_under as before."""
    variance, severity = derive_variance("preserved", "lossy")
    assert variance == recon.VAR_METHODOLOGY_UNDER
    assert severity == "low"


def test_trivial_empty_class_listed_in_all_variances() -> None:
    """``ALL_VARIANCES`` is the canonical roster — TRIVIAL_EMPTY must
    be in it so aggregate / matrix renderers tally it."""
    assert recon.VAR_TRIVIAL_EMPTY in recon.ALL_VARIANCES


def test_actual_disposition_top_level_trivially_preserved() -> None:
    """Phase 1 record carrying ``preserved=True, trivially_preserved=True``
    surfaces as actual='trivially_preserved' in the reconciler."""
    fd = {"vxlan_vnis": {"preserved": True, "trivially_preserved": True}}
    actual, detail = actual_disposition(fd, "vxlan_vnis")
    assert actual == "trivially_preserved"
    assert detail is None


def test_actual_disposition_top_level_preserved_without_trivial_flag() -> None:
    """Without the trivial flag, preserved still maps to plain
    ``preserved`` (the existing behaviour)."""
    fd = {"hostname": {"preserved": True}}
    actual, detail = actual_disposition(fd, "hostname")
    assert actual == "preserved"
    assert detail is None


def test_reconcile_cell_classifies_trivially_preserved_as_trivial_empty() -> None:
    """End-to-end: an empty-vs-empty list field against a ``lossy``
    YAML disposition lands in TRIVIAL_EMPTY, not METHODOLOGY_ISSUE_under.
    Severity rolls up under ``ok``."""
    cell = {
        "fixture": "f.txt",
        "fixture_kind": "real",
        "source_codec": "cisco_iosxe_cli",
        "target_codec": "arista_eos",
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "field_disposition": {
            "evpn_type5_routes": {
                "preserved": True,
                "trivially_preserved": True,
                "source_count": 0,
                "target_count": 0,
            },
        },
    }
    expectation = {
        "per_field_expectation": {
            "evpn_type5_routes": {"disposition": "lossy"},
        },
    }
    result = reconcile_cell(cell, expectation)
    fv = result["field_variances"]
    assert fv["evpn_type5_routes"]["variance"] == recon.VAR_TRIVIAL_EMPTY
    assert fv["evpn_type5_routes"]["severity"] == "ok"
    assert fv["evpn_type5_routes"]["actual"] == "trivially_preserved"
    assert result["summary"][recon.VAR_TRIVIAL_EMPTY] == 1
    assert result["summary"][recon.VAR_METHODOLOGY_UNDER] == 0
    assert result["summary"]["severity_ok"] == 1


def test_reconcile_cell_real_methodology_under_still_fires() -> None:
    """Companion regression guard at the cell level: when the source
    actually has data and both sides preserved it, the YAML's ``lossy``
    claim IS being violated → METHODOLOGY_ISSUE_under, not TRIVIAL_EMPTY."""
    cell = {
        "fixture": "f.txt",
        "fixture_kind": "real",
        "source_codec": "cisco_iosxe_cli",
        "target_codec": "arista_eos",
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "field_disposition": {
            "vlans": {
                "preserved": True,
                "source_count": 5,
                "target_count": 5,
            },
        },
    }
    expectation = {
        "per_field_expectation": {
            "vlans": {"disposition": "lossy"},
        },
    }
    result = reconcile_cell(cell, expectation)
    fv = result["field_variances"]
    assert fv["vlans"]["variance"] == recon.VAR_METHODOLOGY_UNDER
    assert result["summary"][recon.VAR_TRIVIAL_EMPTY] == 0
    assert result["summary"][recon.VAR_METHODOLOGY_UNDER] == 1


def test_structural_only_class_listed_in_all_variances() -> None:
    """``ALL_VARIANCES`` is the canonical roster — STRUCTURAL_ONLY must
    be in it so aggregate / matrix renderers tally it."""
    assert recon.VAR_STRUCTURAL_ONLY in recon.ALL_VARIANCES


def test_structural_only_does_not_count_as_high_severity() -> None:
    """Severity totals must keep CODEC_BUG and STRUCTURAL_ONLY apart —
    the whole point of the new class is to stop a structural signal
    from inflating the high-severity bucket."""
    cell = {
        "fixture": "f.txt",
        "fixture_kind": "real",
        "source_codec": "arista_eos",
        "target_codec": "juniper_junos",
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "field_disposition": {
            "interfaces": {
                "preserved": False,
                "source_count": 10,
                "target_count": 3,
                "drift": "count drift: 10 → 3 (interfaces)",
            },
        },
    }
    expectation = {
        "per_field_expectation": {
            "interfaces[].name": {"disposition": "good"},
            "interfaces[].description": {"disposition": "good"},
            "interfaces[].mtu": {"disposition": "good"},
            "interfaces[].enabled": {"disposition": "good"},
        },
    }
    result = reconcile_cell(cell, expectation)
    # Pre-fix this cell would have contributed 4 to severity_high.
    # Post-fix: 1 high, 3 low.
    assert result["summary"]["severity_high"] == 1
    assert result["summary"]["severity_low"] == 3
