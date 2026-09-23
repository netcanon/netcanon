"""The sanitiser must not redact a derivation keyword.

`auto` in an RD / route-target slot is not an identity — it is an instruction
to the device to derive the value itself. Redacting it protected nobody and
did two kinds of damage:

* **Fabrication.** The keyword was replaced with a synthetic RFC-5398 value the
  operator never wrote, contradicting `docs/CAPABILITIES.md`'s shipped promise
  that netcanon preserves the keyword "rather than inventing a value".
* **Collision.** `_SubstitutionTable._route_targets` is keyed on the value
  string, which is safe while every string is an identity — two different real
  values can never share a placeholder. `auto` breaks that, because ONE string
  stands for N different real values. Two tenants whose RDs genuinely differ on
  the device both became `64496:1`, and so did their export RTs, while the two
  *explicit* RTs in the same file correctly mapped to distinct placeholders. A
  reviewer of that submission saw a merged-VPN topology that does not exist.

It also defeated the #482 derivation-keyword gate: on a sanitised tree the
value is no longer `auto`, so the renderers' check passes and a fabricated RD
ships cross-vendor with no review comment. Since `BUG_REPORTING.md` tells
operators to sanitise before submitting, this hid the class from every future
contributor.

⚠️ The non-vacuous half
----------------------
"Stop redacting" is trivially satisfiable by redacting nothing, so every test
below that asserts `auto` survives is paired with one asserting a **real**
ASN-bearing route-target is still redacted, to distinct placeholders. Without
that pairing this module would pass on a sanitiser that had been switched off.

These are the first corpus-level assertions on RD/RT *content*. (Committed
captures do already flow through the sanitiser elsewhere —
`test_sanitize_api.py:164-166` — and `test_sanitize_completeness.py` is
value-blind by design, triggering on a leaf's existence rather than its value,
so neither could express "redacted *correctly*".)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.registry import get_codec
from netcanon.tools.sanitize import sanitize_intent

pytestmark = pytest.mark.unit


_CORPUS = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "real"
    / "cisco_nxos"
)

#: Two tenants, both with `rd auto`, plus two DIFFERENT explicit leak RTs.
#: The one committed capture that exercises both halves at once.
_TWO_TENANT = _CORPUS / "akarneliuk_evpn_vxlan_mcast_leaf_c1l1_nxos939.txt"


def _sanitised(path: Path):
    intent = get_codec("cisco_nxos").parse(
        path.read_text(encoding="utf-8", errors="replace")
    )
    result = sanitize_intent(intent)
    return result[0] if isinstance(result, tuple) else result


def _instances_with_rd(tree):
    return [ri for ri in tree.routing_instances if ri.route_distinguisher]


def test_the_fixture_still_has_the_shape_this_module_depends_on() -> None:
    """Guard the guard.

    Needs TWO instances whose RD is `auto` (for the collision half) and at
    least one explicit RT (for the non-vacuous half). If the capture or the
    NX-OS parser changes, fail loudly rather than pass vacuously.
    """
    intent = get_codec("cisco_nxos").parse(
        _TWO_TENANT.read_text(encoding="utf-8", errors="replace")
    )
    auto_rds = [
        ri for ri in intent.routing_instances
        if ri.route_distinguisher == "auto"
    ]
    assert len(auto_rds) >= 2, (
        "fixture no longer carries two `rd auto` VRFs — the collision half "
        "of this module cannot fire"
    )
    explicit = [
        rt
        for ri in intent.routing_instances
        for rt in ri.rt_imports
        if rt != "auto"
    ]
    assert explicit, (
        "fixture no longer carries an explicit route-target — the "
        "non-vacuous half of this module cannot fire"
    )


def test_auto_survives_sanitisation() -> None:
    tree = _sanitised(_TWO_TENANT)
    rds = [ri.route_distinguisher for ri in _instances_with_rd(tree)]
    assert rds, "no routing instance carried an RD through sanitisation"
    assert all(rd == "auto" for rd in rds), (
        f"the derivation keyword was rewritten: {rds}"
    )


def test_real_route_targets_are_still_redacted() -> None:
    """The non-vacuous half — the sanitiser must still be doing its job."""
    tree = _sanitised(_TWO_TENANT)
    all_rts = [
        rt for ri in tree.routing_instances for rt in ri.rt_imports
    ]
    real = [rt for rt in all_rts if rt != "auto"]

    assert real, "expected at least one non-keyword RT to survive as a value"
    assert all(rt.startswith("64496:") for rt in real), (
        f"an operator's real ASN-bearing route-target was not redacted: {real}"
    )


def test_two_auto_vrfs_do_not_collide_onto_one_fabricated_rd() -> None:
    """The defect, stated directly.

    Before the fix both tenants' RDs became `64496:1` — one placeholder for
    two values that differ on the device.
    """
    tree = _sanitised(_TWO_TENANT)
    rds = [ri.route_distinguisher for ri in _instances_with_rd(tree)]
    assert len(rds) >= 2
    assert not any(rd.startswith("64496:") for rd in rds), (
        f"a derivation keyword was replaced by a fabricated RD: {rds}"
    )


def test_distinct_real_route_targets_stay_distinct() -> None:
    """Redaction must remain injective on genuine values.

    The two tenants' explicit leak RTs differ on the device; they must differ
    after sanitisation too. This is the property `auto` violated.
    """
    tree = _sanitised(_TWO_TENANT)
    real = [
        rt
        for ri in tree.routing_instances
        for rt in ri.rt_imports
        if rt != "auto"
    ]
    assert len(real) == len(set(real)), (
        f"two distinct real route-targets collapsed onto one placeholder: "
        f"{real}"
    )


def test_the_audit_log_does_not_claim_a_redaction_that_did_not_happen() -> None:
    """The RD walk lacked the `!=` guard its sibling list helper has.

    Once `auto` passes through unchanged, an unguarded walk still appends a
    `route-distinguisher` Substitution — an audit trail that over-reports is
    as untrustworthy as one that under-reports.
    """
    intent = get_codec("cisco_nxos").parse(
        _TWO_TENANT.read_text(encoding="utf-8", errors="replace")
    )
    result = sanitize_intent(intent)
    if not isinstance(result, tuple) or len(result) < 2:
        pytest.skip("sanitize_intent does not return an audit trail here")

    subs = result[1]
    rd_subs = [
        s for s in subs
        if getattr(s, "category", "") == "route-distinguisher"
    ]
    for s in rd_subs:
        assert s.original != s.redacted, (
            f"audit log records a no-op substitution: {s.field}"
        )


def test_the_derivation_gate_is_not_defeated_by_sanitisation() -> None:
    """End to end: a sanitised tree must still trip the #482 renderer gate.

    This is the coupling that made the defect invisible — operators are told
    to sanitise before submitting, so every reported fixture had already had
    its `auto` sentinels replaced.
    """
    tree = _sanitised(_TWO_TENANT)
    rendered = get_codec("juniper_junos").render(tree)

    assert "review:" in rendered, (
        "the sanitised tree rendered without the derivation-keyword review "
        "comment — the gate was bypassed"
    )
    assert "route-distinguisher 64496:" not in rendered, (
        "a fabricated RD was emitted into Junos output"
    )
