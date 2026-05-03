"""
Phase 4b regression: aruba_aoss parse() invokes
``project_switchport_to_vlan`` for symmetry with the other codecs.

AOS-S source config is natively VLAN-centric (``vlan N`` stanza
with ``tagged`` / ``untagged`` member lists), so the projection is
typically a no-op against AOS-S native input — there is no per-iface
switchport_mode populated by the parser to project FROM.  The call
nevertheless lands at the end of parse_intent() so that:

  * cross-vendor pipelines that hand a partially-populated intent
    through the AOS-S codec see consistent post-conditions, and
  * a future per-iface AOS-S grammar (e.g. ``no untagged-vlan``
    variants) that DOES write per-iface state Just Works without
    revisiting the call site.

The test pins the wiring and the no-op idempotence on native input.
"""

from __future__ import annotations

import pytest

from netconfig.migration.codecs.aruba_aoss.parse import parse_intent

pytestmark = pytest.mark.unit


def test_parse_preserves_native_vlan_centric_membership() -> None:
    """AOS-S native ``vlan / untagged / tagged`` survives the
    projection unchanged — the call is additive, not destructive."""
    cfg = (
        "hostname sw1\n"
        "vlan 10\n"
        '   name "USERS"\n'
        "   untagged 1,2\n"
        "   tagged 25\n"
        "   exit\n"
        "vlan 20\n"
        '   name "LAB"\n'
        "   tagged 25\n"
        "   exit\n"
    )
    intent = parse_intent(cfg)
    by_id = {v.id: v for v in intent.vlans}
    # Native AOS-S membership preserved exactly:
    assert sorted(by_id[10].untagged_ports) == ["1", "2"]
    assert by_id[10].tagged_ports == ["25"]
    assert by_id[20].tagged_ports == ["25"]
    assert by_id[20].untagged_ports == []


def test_parse_projection_is_idempotent_when_called_twice() -> None:
    """``project_switchport_to_vlan`` is documented as idempotent.
    Importing + invoking it again on a parsed intent must produce the
    same canonical tree — the helper guards against double-add."""
    from netconfig.migration.canonical.transforms import (
        project_switchport_to_vlan,
    )

    cfg = (
        "hostname sw1\n"
        "vlan 10\n"
        '   name "USERS"\n'
        "   untagged 1,2\n"
        "   exit\n"
    )
    intent = parse_intent(cfg)
    snapshot_untagged = list(intent.vlans[0].untagged_ports)
    project_switchport_to_vlan(intent)  # second call
    assert intent.vlans[0].untagged_ports == snapshot_untagged
