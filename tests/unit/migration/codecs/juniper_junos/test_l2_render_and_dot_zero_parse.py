"""Phase 4 rank-4 / rank-5 regression tests for the Junos codec.

Two related fixes land together because both touch the same
codec:

* **rank 4 — L2 / LAG / SVI render path** (~22 cells): the codec
  previously emitted no ``family ethernet-switching``, no
  ``aggregated-ether-options``, and no ``irb.<vid>`` SVI L3 lines,
  so any cross-vendor render INTO Junos lost L2 + LAG + SVI
  semantics entirely.
* **rank 5 — ``.0`` suffix routing-instance parse** (~18 cells):
  reparse of Junos render output where a routing-instance
  references a parent-only canonical interface (e.g. ``Loopback0``)
  was creating a duplicate stub interface named ``Loopback0.0``
  instead of resolving back to ``Loopback0``.

See ``tests/fixtures/real/PHASE4_RECONCILIATION.md`` for the
reconciliation matrix and the per-vendor ``phase4_findings_*.md``
files for the source-of-bug detail.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalLAG,
    CanonicalVlan,
)
from netconfig.migration.codecs.juniper_junos.parse import parse_intent
from netconfig.migration.codecs.juniper_junos.render import render_intent

pytestmark = pytest.mark.unit


def test_routing_instance_dot_zero_iface_resolves() -> None:
    cfg = (
        "set interfaces Loopback0 unit 0 family inet address 1.1.1.1/32\n"
        "set routing-instances TENANT_A interface Loopback0.0\n"
        "set routing-instances TENANT_A instance-type vrf\n"
    )
    intent = parse_intent(cfg)
    # Single interface, not a duplicate.
    assert len(intent.interfaces) == 1
    assert intent.interfaces[0].name == "Loopback0"
    assert intent.interfaces[0].vrf == "TENANT_A"


def test_l2_switchports_round_trip_to_junos() -> None:
    intent = CanonicalIntent(
        vlans=[
            CanonicalVlan(
                id=10,
                name="USERS",
                ipv4_addresses=[
                    CanonicalIPv4Address(ip="10.10.10.1", prefix_length=24),
                ],
            ),
        ],
        interfaces=[
            CanonicalInterface(
                name="ge-0/0/1",
                switchport_mode="access",
                access_vlan=10,
            ),
        ],
    )
    out = render_intent(intent)
    assert "family ethernet-switching" in out
    assert "interface-mode access" in out
    assert "vlan members USERS" in out
    # SVI L3 emission:
    assert "interfaces irb unit 10 family inet address" in out
    assert "vlans USERS l3-interface irb.10" in out


def test_lag_round_trip_to_junos() -> None:
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(name="ge-0/0/1", lag_member_of="Port-Channel10"),
            CanonicalInterface(name="ge-0/0/2", lag_member_of="Port-Channel10"),
        ],
        lags=[
            CanonicalLAG(
                name="Port-Channel10",
                members=["ge-0/0/1", "ge-0/0/2"],
                mode="active",
            ),
        ],
    )
    out = render_intent(intent)
    assert "set interfaces ae10 aggregated-ether-options lacp active" in out
    assert "set interfaces ge-0/0/1 ether-options 802.3ad ae10" in out
    # Round-trip preserves the LAG record.
    roundtrip = parse_intent(out)
    assert len(roundtrip.lags) == 1
    # On the Junos side the LAG name is canonicalised to the ae form.
    assert roundtrip.lags[0].name == "ae10"
    assert sorted(roundtrip.lags[0].members) == ["ge-0/0/1", "ge-0/0/2"]
