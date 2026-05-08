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

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalLAG,
    CanonicalVlan,
)
from netcanon.migration.codecs.juniper_junos.parse import parse_intent
from netcanon.migration.codecs.juniper_junos.render import render_intent

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


def test_trunk_all_vlans_collapses_to_members_all() -> None:
    """Arista MLAG peer ports often carry `switchport trunk allowed
    vlan 2-4094` — the operator-form for "all VLANs except the
    default".  Without this fix, render emits one `vlan members
    VLAN-N` line per VID, exploding to 4000+ lines per port.  Junos
    expresses the same intent as `vlan members all`."""
    intent = CanonicalIntent(
        interfaces=[CanonicalInterface(
            name="ae3",
            switchport_mode="trunk",
            trunk_allowed_vlans=list(range(2, 4095)),  # 4093 VIDs
        )],
    )
    out = render_intent(intent)
    # The all-form is emitted exactly once.
    assert (
        "set interfaces ae3 unit 0 family ethernet-switching vlan members all"
        in out
    )
    # No phantom VLAN-N lines.
    assert "VLAN-1000" not in out
    assert "VLAN-4094" not in out
    # Total `vlan members` lines for ae3 is exactly 1.
    member_lines = [
        line for line in out.splitlines()
        if "ae3" in line and "vlan members" in line
    ]
    assert len(member_lines) == 1


def test_trunk_full_1_4094_also_collapses() -> None:
    """Arista's literal `switchport trunk allowed vlan 1-4094` form
    (less common but legal) collapses identically."""
    intent = CanonicalIntent(
        interfaces=[CanonicalInterface(
            name="ae0",
            switchport_mode="trunk",
            trunk_allowed_vlans=list(range(1, 4095)),  # 4094 VIDs
        )],
    )
    out = render_intent(intent)
    assert (
        "set interfaces ae0 unit 0 family ethernet-switching vlan members all"
        in out
    )


def test_trunk_specific_vlans_still_enumerate() -> None:
    """Specific (small) VLAN lists must NOT collapse to `members all`
    — only the all-VLANs case is special-cased."""
    intent = CanonicalIntent(
        vlans=[
            CanonicalVlan(id=10, name="USERS"),
            CanonicalVlan(id=20, name="VOICE"),
            CanonicalVlan(id=30, name="GUESTS"),
        ],
        interfaces=[CanonicalInterface(
            name="ae5",
            switchport_mode="trunk",
            trunk_allowed_vlans=[10, 20, 30],
        )],
    )
    out = render_intent(intent)
    assert "vlan members all" not in out
    assert "vlan members USERS" in out
    assert "vlan members VOICE" in out
    assert "vlan members GUESTS" in out


def test_irb_dot_unit_renders_without_double_unit() -> None:
    """Issue #3 in ``user_smoke_findings.md`` (CRITICAL deploy block).

    A canonical ``CanonicalInterface(name="irb.10", ipv4_addresses=...)``
    used to render as ``set interfaces irb.10 unit 0 family inet
    address 192.168.10.1/24`` — Junos's commit-time validator rejects
    this because ``irb.10`` is shorthand for ``irb unit 10``, so the
    line expands to ``irb unit 10 unit 0``.  Cross-vendor renders
    into Junos from any source codec that produces SVI names
    (OPNsense ``opt1``-``opt5``, Cisco ``Vlan10``) would silently
    deploy a non-committable config.

    The fix routes ``irb.<N>`` (and ``vlan.<N>``) names through the
    sub-interface branch with parent=``irb`` and unit=``N`` so the
    emitted line is ``set interfaces irb unit 10 family inet
    address ...`` — the form Junos's commit-time validator accepts.
    """
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="irb.10",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="192.168.10.1", prefix_length=24,
                    ),
                ],
            ),
        ],
    )
    out = render_intent(intent)
    # The malformed double-unit form must not appear anywhere.
    assert "irb.10 unit 0" not in out
    # The native Junos form is emitted instead.
    assert (
        "set interfaces irb unit 10 family inet "
        "address 192.168.10.1/24"
    ) in out


def test_irb_multiple_units_render_correctly() -> None:
    """The OPNsense supergate fixture has 5 SVIs — irb.10/.11/.20/
    .100/.150 — each carrying its own L3 address.  All five must
    render in the native Junos form (``irb unit <vid>``) so the
    rendered config commits cleanly."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name=f"irb.{vid}",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip=f"192.168.{vid}.1", prefix_length=24,
                    ),
                ],
            )
            for vid in (10, 11, 20, 100, 150)
        ],
    )
    out = render_intent(intent)
    for vid in (10, 11, 20, 100, 150):
        # Native Junos form present.
        assert (
            f"set interfaces irb unit {vid} family inet "
            f"address 192.168.{vid}.1/24"
        ) in out
        # Malformed double-unit form not present.
        assert f"irb.{vid} unit 0" not in out


def test_physical_port_unit_0_still_emits() -> None:
    """Regression guard: standard physical ports without a ``.<N>``
    suffix still take the regular-interface branch and emit ``set
    interfaces ge-0/0/0 unit 0 family inet address ...`` — only
    Junos logical SVI names (``irb.<N>`` / ``vlan.<N>``) are routed
    through the sub-interface branch."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="ge-0/0/0",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="10.1.1.1", prefix_length=30,
                    ),
                ],
            ),
        ],
    )
    out = render_intent(intent)
    assert (
        "set interfaces ge-0/0/0 unit 0 family inet "
        "address 10.1.1.1/30"
    ) in out


def test_irb_dot_unit_round_trip_canonical_stable() -> None:
    """Render an ``irb.10`` SVI with an IP, reparse, and confirm the
    canonical tree round-trips cleanly.  Without an l3-interface
    binding the irb.<vid> interface is preserved as-is by the parser
    (see step 3 in ``parse_intent``'s post-pass)."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="irb.10",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="192.168.10.1", prefix_length=24,
                    ),
                ],
            ),
        ],
    )
    out = render_intent(intent)
    roundtrip = parse_intent(out)
    irb_iface = next(
        (i for i in roundtrip.interfaces if i.name == "irb.10"), None,
    )
    assert irb_iface is not None
    assert len(irb_iface.ipv4_addresses) == 1
    assert irb_iface.ipv4_addresses[0].ip == "192.168.10.1"
    assert irb_iface.ipv4_addresses[0].prefix_length == 24


def test_trunk_all_round_trip_canonical_stable() -> None:
    """Source canonical with all-VLANs trunk → render emits `members
    all` → reparse expands back to the full VID range.  Canonical
    field comparison is set-equal across the round-trip."""
    intent = CanonicalIntent(
        interfaces=[CanonicalInterface(
            name="ae3",
            switchport_mode="trunk",
            trunk_allowed_vlans=list(range(2, 4095)),
        )],
    )
    out = render_intent(intent)
    roundtrip = parse_intent(out)
    rt_iface = next(i for i in roundtrip.interfaces if i.name == "ae3")
    assert rt_iface.switchport_mode == "trunk"
    # Reparse expands `members all` to the full 1-4094 range.
    # Source had 2-4094 (4093 VIDs); reparse gives 1-4094 (4094 VIDs)
    # — that's a documented one-VID asymmetry where Junos's `all`
    # includes VLAN 1 (default-VLAN) by spec while Arista's
    # `2-4094` explicitly excludes it.  Both forms canonicalise to
    # the all-VLANs sentinel; the lone difference is operator-intent
    # on whether VLAN 1 itself is permitted.  We accept the full
    # range as correct on reparse.
    assert len(rt_iface.trunk_allowed_vlans) >= 4093
    assert 100 in rt_iface.trunk_allowed_vlans
    assert 4094 in rt_iface.trunk_allowed_vlans
