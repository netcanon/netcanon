"""
Unit tests for ``tools/run_full_mesh.py``'s drift computation.

The runner script itself is verified end-to-end by running it once and
eyeballing the matrix.  These tests pin the *building blocks* — the
field-by-field drift comparison — so a regression in
:func:`compute_field_disposition` fails loud rather than silently
mis-classifying every cell in the next audit pass.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalLAG,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVxlan,
)


pytestmark = pytest.mark.unit


# Load the runner module without making ``tools/`` a package.  The
# audit script is intentionally standalone — importing it through the
# spec mechanism keeps the production import surface clean while still
# letting unit tests reach into its internals.
_RUNNER_PATH = (
    Path(__file__).resolve().parents[3] / "tools" / "run_full_mesh.py"
)
_spec = importlib.util.spec_from_file_location(
    "run_full_mesh", _RUNNER_PATH,
)
assert _spec is not None and _spec.loader is not None
run_full_mesh = importlib.util.module_from_spec(_spec)
sys.modules["run_full_mesh"] = run_full_mesh
_spec.loader.exec_module(run_full_mesh)

compute_field_disposition = run_full_mesh.compute_field_disposition
cell_status = run_full_mesh.cell_status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ip(addr: str, prefix: int = 24) -> CanonicalIPv4Address:
    return CanonicalIPv4Address(ip=addr, prefix_length=prefix)


# ---------------------------------------------------------------------------
# Identical intents → all preserved
# ---------------------------------------------------------------------------


def test_identical_intents_preserve_every_field() -> None:
    intent = CanonicalIntent(
        hostname="router-1",
        dns_servers=["1.1.1.1", "8.8.8.8"],
        interfaces=[
            CanonicalInterface(
                name="GigabitEthernet0/0",
                ipv4_addresses=[_ip("10.0.0.1", 24)],
                mtu=1500,
            )
        ],
        vlans=[
            CanonicalVlan(id=10, name="USERS"),
            CanonicalVlan(id=20, name="VOICE"),
        ],
    )
    out = compute_field_disposition(intent, intent)
    for field, rec in out.items():
        assert rec["preserved"], (
            f"identical intents must preserve {field}; got {rec}"
        )


def test_identical_intents_yield_zero_drift_summary() -> None:
    intent = CanonicalIntent(hostname="r1")
    out = compute_field_disposition(intent, intent)
    drifted = [k for k, v in out.items() if not v["preserved"]]
    assert drifted == []


# ---------------------------------------------------------------------------
# Scalar drift
# ---------------------------------------------------------------------------


def test_hostname_drift_is_detected() -> None:
    src = CanonicalIntent(hostname="r1")
    tgt = CanonicalIntent(hostname="r2")
    out = compute_field_disposition(src, tgt)
    assert out["hostname"]["preserved"] is False
    assert "r1" in out["hostname"]["drift"]
    assert "r2" in out["hostname"]["drift"]


def test_empty_to_empty_scalar_is_preserved() -> None:
    """The canonical model uses '' as the zero state for many string
    fields.  Empty-to-empty must NOT register as drift even though
    technically equal-via-equality — guards against False being
    confused with 'never set'."""
    src = CanonicalIntent()
    tgt = CanonicalIntent()
    out = compute_field_disposition(src, tgt)
    for field in ("hostname", "domain", "timezone"):
        assert out[field]["preserved"], (
            f"{field}='' on both sides must be preserved"
        )


# ---------------------------------------------------------------------------
# List-of-records drift
# ---------------------------------------------------------------------------


def test_dropped_list_records_are_drift() -> None:
    src = CanonicalIntent(
        vxlan_vnis=[
            CanonicalVxlan(vlan_id=100, vni=10100),
            CanonicalVxlan(vlan_id=200, vni=10200),
        ]
    )
    tgt = CanonicalIntent()
    out = compute_field_disposition(src, tgt)
    rec = out["vxlan_vnis"]
    assert rec["preserved"] is False
    assert rec["source_count"] == 2
    assert rec["target_count"] == 0
    assert "dropped" in str(rec["drift"]).lower()


def test_partial_record_drift_drills_into_field() -> None:
    src = CanonicalIntent(
        vlans=[CanonicalVlan(id=10, name="USERS", description="primary")]
    )
    tgt = CanonicalIntent(
        # Same VLAN id + name but description dropped.
        vlans=[CanonicalVlan(id=10, name="USERS", description="")]
    )
    out = compute_field_disposition(src, tgt)
    rec = out["vlans"]
    assert rec["preserved"] is False
    assert rec["source_count"] == 1
    assert rec["target_count"] == 1
    drift = rec["drift"]
    # The drill-down is dict-shaped — find the per-record diff.
    assert isinstance(drift, dict)
    flat = " ".join(repr(v) for v in drift.values())
    assert "description" in flat
    assert "primary" in flat


def test_list_order_change_does_not_register_as_drift() -> None:
    """Order is cosmetic for list-fields with a natural identity key.
    Mirrors the round-trip test's _compare semantics."""
    src = CanonicalIntent(
        interfaces=[
            CanonicalInterface(name="ge-0/0/0"),
            CanonicalInterface(name="ge-0/0/1"),
        ]
    )
    tgt = CanonicalIntent(
        interfaces=[
            CanonicalInterface(name="ge-0/0/1"),
            CanonicalInterface(name="ge-0/0/0"),
        ]
    )
    out = compute_field_disposition(src, tgt)
    assert out["interfaces"]["preserved"], (
        "list-order-only difference must not register as drift"
    )


# ---------------------------------------------------------------------------
# Unsupported-in-target classification
# ---------------------------------------------------------------------------


def test_unsupported_xpath_marks_field_as_unsupported_in_target() -> None:
    src = CanonicalIntent(
        vxlan_vnis=[CanonicalVxlan(vlan_id=100, vni=10100)],
    )
    tgt = CanonicalIntent()  # target dropped the VNI
    # Simulate aruba_aoss-style declarations: "/vxlan-vnis/vni" etc.
    out = compute_field_disposition(
        src, tgt,
        target_unsupported_xpaths=[
            "/vxlan-vnis/vni",
            "/vxlan-vnis/source-interface",
            "/vxlan-vnis/udp-port",
        ],
    )
    rec = out["vxlan_vnis"]
    assert rec["preserved"] is False
    assert rec["unsupported_in_target"] is True


def test_unsupported_xpath_does_not_apply_to_other_fields() -> None:
    src = CanonicalIntent(hostname="r1")
    tgt = CanonicalIntent(hostname="r2")
    out = compute_field_disposition(
        src, tgt,
        target_unsupported_xpaths=["/vxlan-vnis/vni"],
    )
    assert out["hostname"]["unsupported_in_target"] is False


# ---------------------------------------------------------------------------
# Dict-field drift (raw_sections, group_content)
# ---------------------------------------------------------------------------


def test_raw_sections_drift_summary() -> None:
    src = CanonicalIntent(
        raw_sections={"banner": "MOTD", "ntp": "ntp 1.1.1.1"},
    )
    tgt = CanonicalIntent(raw_sections={"banner": "MOTD"})
    out = compute_field_disposition(src, tgt)
    rec = out["raw_sections"]
    assert rec["preserved"] is False
    drift = rec["drift"]
    assert isinstance(drift, dict)
    assert "ntp" in drift["only_in_source"]


# ---------------------------------------------------------------------------
# Cell-status helper
# ---------------------------------------------------------------------------


def test_cell_status_render_error() -> None:
    cell = {
        "render_status": "render_error",
        "roundtrip_parse_status": "skipped",
    }
    assert cell_status(cell) == "RENDER"


def test_cell_status_parse_error() -> None:
    cell = {
        "render_status": "ok",
        "roundtrip_parse_status": "parse_error",
    }
    assert cell_status(cell) == "PARSE"


def test_cell_status_clean() -> None:
    cell = {
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "summary": {
            "fields_total": 10,
            "fields_preserved": 8,
            "fields_drifted": 0,
            "fields_unsupported_in_target": 2,
        },
    }
    assert cell_status(cell) == "OK"


def test_cell_status_warn_when_drift_present() -> None:
    cell = {
        "render_status": "ok",
        "roundtrip_parse_status": "ok",
        "summary": {
            "fields_total": 10,
            "fields_preserved": 7,
            "fields_drifted": 2,
            "fields_unsupported_in_target": 1,
        },
    }
    assert cell_status(cell) == "WARN"


# ---------------------------------------------------------------------------
# Coverage of all audited fields
# ---------------------------------------------------------------------------


def test_audited_fields_cover_every_canonical_top_level() -> None:
    """If a new top-level field lands on CanonicalIntent and the runner
    forgets to add it to ``_AUDITED_FIELDS``, it'll silently be excluded
    from every cell.  This guard fails loud."""
    canonical_fields = set(CanonicalIntent.model_fields.keys())
    metadata_fields = {
        "source_vendor", "source_format", "source_version",
    }
    expected = canonical_fields - metadata_fields
    audited = set(run_full_mesh._AUDITED_FIELDS)
    missing = expected - audited
    assert not missing, (
        f"new CanonicalIntent fields not in _AUDITED_FIELDS: {missing}.  "
        f"Add them to tools/run_full_mesh.py::_AUDITED_FIELDS so the "
        f"audit doesn't silently skip them."
    )


# ---------------------------------------------------------------------------
# Mixed example: realistic small intent with one OK + one DRIFT field
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# trivially_preserved — both sides empty, no data to validate against
# ---------------------------------------------------------------------------
#
# Wave 10α.  The post-Wave-7c matrix had 7382 METHODOLOGY_ISSUE_under
# cells; an audit found that 4169 (56%) were noise — the source fixture
# had ZERO data for the field, so the target trivially "preserved" zero
# and the YAML's lossy/unsupported claim could neither be confirmed nor
# violated.  These cells are now tagged ``trivially_preserved=True`` at
# Phase 1 so Phase 4 can route them to a new TRIVIAL_EMPTY variance
# class instead of polluting METHODOLOGY_ISSUE_under.


def test_trivially_preserved_fires_when_both_lists_empty() -> None:
    """Empty list on both sides → preserved AND trivially_preserved.
    The cell is benignly aligned by absence of data — the YAML's
    disposition (lossy / unsupported / good) couldn't be tested."""
    src = CanonicalIntent()  # vxlan_vnis defaults to []
    tgt = CanonicalIntent()
    out = compute_field_disposition(src, tgt)
    rec = out["vxlan_vnis"]
    assert rec["preserved"] is True
    assert rec.get("trivially_preserved") is True
    rec_evpn = out["evpn_type5_routes"]
    assert rec_evpn["preserved"] is True
    assert rec_evpn.get("trivially_preserved") is True


def test_trivially_preserved_does_not_fire_when_lists_have_content() -> None:
    """Equal non-empty content is real preservation, NOT trivial.  The
    flag must be absent / falsy so the Phase 4 reconciler doesn't
    misclassify a populated round-trip as TRIVIAL_EMPTY."""
    src = CanonicalIntent(
        vxlan_vnis=[CanonicalVxlan(vlan_id=100, vni=10100)],
    )
    tgt = CanonicalIntent(
        vxlan_vnis=[CanonicalVxlan(vlan_id=100, vni=10100)],
    )
    out = compute_field_disposition(src, tgt)
    rec = out["vxlan_vnis"]
    assert rec["preserved"] is True
    assert not rec.get("trivially_preserved")


def test_trivially_preserved_does_not_fire_when_only_one_side_empty() -> None:
    """Empty → populated (or vice versa) is drift, not preservation; the
    trivial-empty flag is irrelevant when ``preserved`` is False."""
    src = CanonicalIntent(
        vxlan_vnis=[CanonicalVxlan(vlan_id=100, vni=10100)],
    )
    tgt = CanonicalIntent()  # empty
    out = compute_field_disposition(src, tgt)
    rec = out["vxlan_vnis"]
    assert rec["preserved"] is False
    assert not rec.get("trivially_preserved")


def test_trivially_preserved_fires_for_empty_scalar_strings() -> None:
    """Both sides have empty-state scalar (e.g. ``timezone=""``).  This
    is the dominant noise source for the timezone / domain fields."""
    src = CanonicalIntent()  # timezone defaults to ""
    tgt = CanonicalIntent()
    out = compute_field_disposition(src, tgt)
    for field in ("hostname", "domain", "timezone"):
        rec = out[field]
        assert rec["preserved"] is True
        assert rec.get("trivially_preserved") is True, (
            f"{field} with both sides at empty-state must flag trivially_preserved"
        )


def test_trivially_preserved_does_not_fire_for_populated_scalar_match() -> None:
    """Real preservation of a populated scalar (``hostname='r1'``
    on both sides) must NOT trip the flag — that's an ALIGNED cell."""
    src = CanonicalIntent(hostname="r1")
    tgt = CanonicalIntent(hostname="r1")
    out = compute_field_disposition(src, tgt)
    rec = out["hostname"]
    assert rec["preserved"] is True
    assert not rec.get("trivially_preserved")


def test_trivially_preserved_fires_for_empty_dicts() -> None:
    """Empty raw_sections / group_content dicts on both sides → trivial.
    Both fields default to ``{}`` in the canonical model."""
    src = CanonicalIntent()
    tgt = CanonicalIntent()
    out = compute_field_disposition(src, tgt)
    rec = out["raw_sections"]
    assert rec["preserved"] is True
    assert rec.get("trivially_preserved") is True


def test_trivially_preserved_does_not_fire_for_populated_equal_dicts() -> None:
    src = CanonicalIntent(raw_sections={"banner": "MOTD"})
    tgt = CanonicalIntent(raw_sections={"banner": "MOTD"})
    out = compute_field_disposition(src, tgt)
    rec = out["raw_sections"]
    assert rec["preserved"] is True
    assert not rec.get("trivially_preserved")


def test_mixed_drift_example() -> None:
    src = CanonicalIntent(
        hostname="r1",
        ntp_servers=["10.0.0.1"],
        static_routes=[
            CanonicalStaticRoute(
                destination="0.0.0.0/0", gateway="10.0.0.254",
            ),
        ],
        snmp=CanonicalSNMP(community="public"),
        lags=[CanonicalLAG(name="bond0", members=["eth0", "eth1"])],
        dhcp_servers=[
            CanonicalDHCPPool(network="10.0.0.0/24", start_ip="10.0.0.10"),
        ],
    )
    tgt = CanonicalIntent(
        hostname="r1",
        ntp_servers=["10.0.0.1"],
        static_routes=[
            # Same destination but gateway dropped — drift on a record
            # field (gateway), not the whole list.
            CanonicalStaticRoute(destination="0.0.0.0/0", gateway=""),
        ],
        snmp=CanonicalSNMP(community="public"),
        lags=[CanonicalLAG(name="bond0", members=["eth0", "eth1"])],
        # dhcp_servers dropped entirely.
    )
    out = compute_field_disposition(src, tgt)
    assert out["hostname"]["preserved"]
    assert out["ntp_servers"]["preserved"]
    assert out["snmp"]["preserved"]
    assert out["lags"]["preserved"]
    assert out["static_routes"]["preserved"] is False
    assert out["dhcp_servers"]["preserved"] is False
    assert out["dhcp_servers"]["target_count"] == 0
