"""Wave 9 α — pin the fix that makes dict-typed canonical fields
(``snmp``) carry their full source/target dict in the Phase 1 cell
record, so the Phase 4 reconciler's :func:`_subfield_drift_in_dict`
can resolve per-attribute drift instead of conservatively flagging
every attribute as drifted.

Pre-fix bug: ``compute_field_disposition`` recorded ``record["source"] =
list(src_val.keys())``, a key-list summary.  When the reconciler tried
to compare ``snmp.community`` between source/target, it got two key-lists
instead of two dicts and bailed out — returning ``None`` from
``_subfield_drift_in_dict``, which the caller treats as drifted.  The
result was ~11 spurious CODEC_BUG cells (snmp.community / .location /
.contact / .trap_hosts on cross-vendor pairs that actually preserved
those scalars).

Post-fix: dict-typed parents store the full source/target dicts.  The
reconciler's existing per-attribute comparison resolves cleanly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalSNMP,
    CanonicalSNMPv3User,
)


pytestmark = pytest.mark.unit


_RUNNER_PATH = (
    Path(__file__).resolve().parents[3] / "tools" / "run_full_mesh.py"
)
_spec = importlib.util.spec_from_file_location(
    "run_full_mesh_a", _RUNNER_PATH,
)
assert _spec is not None and _spec.loader is not None
run_full_mesh = importlib.util.module_from_spec(_spec)
sys.modules["run_full_mesh_a"] = run_full_mesh
_spec.loader.exec_module(run_full_mesh)


_RECON_PATH = (
    Path(__file__).resolve().parents[3]
    / "tools"
    / "run_phase4_reconciliation.py"
)
_spec_recon = importlib.util.spec_from_file_location(
    "run_phase4_reconciliation_a", _RECON_PATH,
)
assert _spec_recon is not None and _spec_recon.loader is not None
recon = importlib.util.module_from_spec(_spec_recon)
sys.modules["run_phase4_reconciliation_a"] = recon
_spec_recon.loader.exec_module(recon)


compute_field_disposition = run_full_mesh.compute_field_disposition


def _intent_with_snmp(
    *,
    community: str,
    location: str,
    contact: str,
    v3_users: list[CanonicalSNMPv3User] | None = None,
) -> CanonicalIntent:
    return CanonicalIntent(
        hostname="r1",
        snmp=CanonicalSNMP(
            community=community,
            location=location,
            contact=contact,
            v3_users=v3_users or [],
        ),
    )


def test_snmp_drift_record_carries_full_dicts_not_key_lists() -> None:
    """The cell record for the ``snmp`` field must carry the full
    source/target dicts so a downstream consumer can compare individual
    attributes.  Pre-fix the record carried ``list(snmp.keys())``.
    """
    src_user = CanonicalSNMPv3User(name="opA", auth_protocol="sha")
    tgt_user = CanonicalSNMPv3User(name="opA", auth_protocol="sha256")
    src = _intent_with_snmp(
        community="public",
        location="rack-7",
        contact="noc@example.com",
        v3_users=[src_user],
    )
    # Identical scalars; only v3_users differs.
    tgt = _intent_with_snmp(
        community="public",
        location="rack-7",
        contact="noc@example.com",
        v3_users=[tgt_user],
    )
    out = compute_field_disposition(src, tgt)
    snmp_record = out["snmp"]
    assert snmp_record["preserved"] is False
    # The fix: source/target are full dicts, not key-lists.
    assert isinstance(snmp_record["source"], dict), (
        f"expected source to be a dict, got "
        f"{type(snmp_record['source']).__name__}: {snmp_record['source']!r}"
    )
    assert isinstance(snmp_record["target"], dict)
    assert snmp_record["source"]["community"] == "public"
    assert snmp_record["target"]["community"] == "public"
    assert snmp_record["source"]["location"] == "rack-7"


def test_subfield_drift_in_dict_resolves_to_preserved_for_unchanged_scalars() -> None:
    """End-to-end check: when only ``v3_users`` differs but
    community/location/contact match, the reconciler's
    ``_subfield_drift_in_dict`` must report those scalars as preserved
    (not drifted)."""
    src = _intent_with_snmp(
        community="public",
        location="rack-7",
        contact="noc@example.com",
        v3_users=[CanonicalSNMPv3User(name="a", auth_protocol="sha")],
    )
    tgt = _intent_with_snmp(
        community="public",
        location="rack-7",
        contact="noc@example.com",
        v3_users=[CanonicalSNMPv3User(name="a", auth_protocol="sha256")],
    )
    field_disposition = compute_field_disposition(src, tgt)

    # community / location / contact unchanged → reconciler must treat
    # them as preserved.
    for attr in ("community", "location", "contact"):
        actual, _ = recon.actual_disposition(
            field_disposition, f"snmp.{attr}",
        )
        assert actual == "preserved", (
            f"snmp.{attr} should be preserved (source value matches "
            f"target value); got {actual}"
        )

    # v3_users actually changed → drifted.
    actual, _ = recon.actual_disposition(field_disposition, "snmp.v3_users")
    assert actual == "drifted"


def test_subfield_drift_in_dict_resolves_to_drifted_for_changed_scalars() -> None:
    """Sanity check the OTHER side of the contract: when a scalar
    actually drifts, the reconciler reports it as drifted."""
    src = _intent_with_snmp(
        community="public", location="rack-7", contact="noc@example.com",
    )
    tgt = _intent_with_snmp(
        community="private",  # drifted!
        location="rack-7",
        contact="noc@example.com",
    )
    field_disposition = compute_field_disposition(src, tgt)
    actual, _ = recon.actual_disposition(
        field_disposition, "snmp.community",
    )
    assert actual == "drifted"
    # Other attributes still preserved.
    for attr in ("location", "contact"):
        actual, _ = recon.actual_disposition(
            field_disposition, f"snmp.{attr}",
        )
        assert actual == "preserved"
