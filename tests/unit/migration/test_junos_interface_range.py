"""
Unit tests for Junos interface-range parse + render (structural
apply-groups collapse).

Parse side:
- `set interfaces interface-range <name> member <iface>` collects
  members; per-range shared attrs (mtu, description, disable) apply
  to each member at materialisation time.
- Canonical tree looks identical whether the operator wrote
  interface-range blocks or flat per-interface lines — full round-
  trip fidelity.

Render side:
- Auto-detects ≥3 interfaces sharing identical (mtu, description,
  enabled) tuples and emits `set interfaces interface-range
  AUTO-RANGE-<N>` blocks.  Per-interface emission suppresses the
  shared attrs.
- Collapses skip VRF-bound, switchport, trunk, and sub-interfaces
  (richer semantics warrant per-interface emission).

Structural collapse is COMPLEMENTARY to GAP 9b's apply-groups
preservation — the operator's explicit group structure is preserved
verbatim; auto-synthesis kicks in only when no explicit group covers
the shared config.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
)
from netcanon.migration.codecs.juniper_junos import JunosCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Interface-range parse
# ---------------------------------------------------------------------------


class TestInterfaceRangeParse:
    def test_mtu_shared_across_members(self):
        raw = (
            "set interfaces interface-range UPLINKS member ge-0/0/0\n"
            "set interfaces interface-range UPLINKS member ge-0/0/1\n"
            "set interfaces interface-range UPLINKS member ge-0/0/2\n"
            "set interfaces interface-range UPLINKS mtu 9000\n"
        )
        intent = JunosCodec().parse(raw)
        names = {i.name for i in intent.interfaces}
        assert names == {"ge-0/0/0", "ge-0/0/1", "ge-0/0/2"}
        for iface in intent.interfaces:
            assert iface.mtu == 9000

    def test_description_shared_across_members(self):
        raw = (
            "set interfaces interface-range UPLINKS member ge-0/0/0\n"
            "set interfaces interface-range UPLINKS member ge-0/0/1\n"
            'set interfaces interface-range UPLINKS description "uplink"\n'
        )
        intent = JunosCodec().parse(raw)
        for iface in intent.interfaces:
            assert iface.description == "uplink"

    def test_disable_shared_across_members(self):
        raw = (
            "set interfaces interface-range UNUSED member ge-0/0/10\n"
            "set interfaces interface-range UNUSED member ge-0/0/11\n"
            "set interfaces interface-range UNUSED disable\n"
        )
        intent = JunosCodec().parse(raw)
        for iface in intent.interfaces:
            assert iface.enabled is False

    def test_per_interface_overrides_range(self):
        """When a member has its own ``set interfaces X description
        specific``, that wins over the range-level shared value."""
        raw = (
            "set interfaces interface-range UPLINKS member ge-0/0/0\n"
            "set interfaces interface-range UPLINKS member ge-0/0/1\n"
            'set interfaces interface-range UPLINKS description "default"\n'
            'set interfaces ge-0/0/0 description "specific"\n'
        )
        intent = JunosCodec().parse(raw)
        ge0 = next(i for i in intent.interfaces if i.name == "ge-0/0/0")
        ge1 = next(i for i in intent.interfaces if i.name == "ge-0/0/1")
        assert ge0.description == "specific"
        assert ge1.description == "default"

    def test_unknown_range_attr_silently_dropped(self):
        """Unknown sub-paths under interface-range (e.g. family-
        filter references we don't model) parse-and-ignore without
        affecting known attrs."""
        raw = (
            "set interfaces interface-range X member ge-0/0/0\n"
            "set interfaces interface-range X member ge-0/0/1\n"
            "set interfaces interface-range X mtu 9000\n"
            "set interfaces interface-range X unit 0 family inet "
            "filter input MY-FILTER\n"
        )
        intent = JunosCodec().parse(raw)
        for iface in intent.interfaces:
            assert iface.mtu == 9000


# ---------------------------------------------------------------------------
# Interface-range render (auto-collapse)
# ---------------------------------------------------------------------------


class TestInterfaceRangeRender:
    def test_three_interfaces_shared_mtu_collapse(self):
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="ge-0/0/0", mtu=9000),
                CanonicalInterface(name="ge-0/0/1", mtu=9000),
                CanonicalInterface(name="ge-0/0/2", mtu=9000),
            ],
        )
        out = JunosCodec().render(intent)
        # Expect an auto-range block.
        assert "set interfaces interface-range AUTO-RANGE-1 member ge-0/0/0" in out
        assert "set interfaces interface-range AUTO-RANGE-1 member ge-0/0/1" in out
        assert "set interfaces interface-range AUTO-RANGE-1 member ge-0/0/2" in out
        assert "set interfaces interface-range AUTO-RANGE-1 mtu 9000" in out
        # Per-interface MTU emission suppressed.
        assert "set interfaces ge-0/0/0 mtu 9000" not in out

    def test_two_interfaces_no_collapse(self):
        """Collapse threshold is ≥3 members; 2 members stays flat."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="ge-0/0/0", mtu=9000),
                CanonicalInterface(name="ge-0/0/1", mtu=9000),
            ],
        )
        out = JunosCodec().render(intent)
        assert "interface-range" not in out
        assert "set interfaces ge-0/0/0 mtu 9000" in out
        assert "set interfaces ge-0/0/1 mtu 9000" in out

    def test_multiple_collapse_groups(self):
        """Different shared-attr tuples get separate AUTO-RANGE-N names."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="ge-0/0/0", mtu=9000),
                CanonicalInterface(name="ge-0/0/1", mtu=9000),
                CanonicalInterface(name="ge-0/0/2", mtu=9000),
                CanonicalInterface(name="xe-0/0/0", mtu=1500),
                CanonicalInterface(name="xe-0/0/1", mtu=1500),
                CanonicalInterface(name="xe-0/0/2", mtu=1500),
            ],
        )
        out = JunosCodec().render(intent)
        # Two auto-ranges should emit.
        assert "AUTO-RANGE-1" in out
        assert "AUTO-RANGE-2" in out

    def test_per_interface_specifics_still_emit(self):
        """IP addresses are per-interface even when the interface is
        a range member — must still emit."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ge-0/0/0", mtu=9000,
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.0.0.1", prefix_length=31),
                    ],
                ),
                CanonicalInterface(name="ge-0/0/1", mtu=9000),
                CanonicalInterface(name="ge-0/0/2", mtu=9000),
            ],
        )
        out = JunosCodec().render(intent)
        assert "AUTO-RANGE-1 member ge-0/0/0" in out
        assert (
            "set interfaces ge-0/0/0 unit 0 family inet "
            "address 10.0.0.1/31" in out
        )

    def test_vrf_bound_iface_not_collapsed(self):
        """VRF-bound interfaces skip auto-collapse — per-interface
        VRF semantics warrant explicit emission."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="ge-0/0/0", mtu=9000, vrf="A"),
                CanonicalInterface(name="ge-0/0/1", mtu=9000, vrf="A"),
                CanonicalInterface(name="ge-0/0/2", mtu=9000, vrf="A"),
            ],
            routing_instances=[
                # Needs to exist so render doesn't complain.
                __import__(
                    "netcanon.migration.canonical.intent",
                    fromlist=["CanonicalRoutingInstance"],
                ).CanonicalRoutingInstance(name="A"),
            ],
        )
        out = JunosCodec().render(intent)
        assert "interface-range" not in out

    def test_all_defaults_not_collapsed(self):
        """Interfaces with no shared non-default attrs don't collapse
        (would be pointless — nothing to hoist to the range)."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="ge-0/0/0"),
                CanonicalInterface(name="ge-0/0/1"),
                CanonicalInterface(name="ge-0/0/2"),
            ],
        )
        out = JunosCodec().render(intent)
        assert "interface-range" not in out

    def test_subiface_not_collapsed(self):
        """Sub-interfaces (`ge-0/0/0.100`) don't participate in
        interface-range collapse — their per-unit semantics are
        distinct from the parent."""
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="ge-0/0/0.100", mtu=9000, access_vlan=100,
                ),
                CanonicalInterface(
                    name="ge-0/0/0.200", mtu=9000, access_vlan=200,
                ),
                CanonicalInterface(
                    name="ge-0/0/0.300", mtu=9000, access_vlan=300,
                ),
            ],
        )
        out = JunosCodec().render(intent)
        # Sub-interfaces render under their parent/unit grammar,
        # not interface-range.
        assert "interface-range" not in out


# ---------------------------------------------------------------------------
# Round-trip — parse → render (auto-collapse) → parse stability
# ---------------------------------------------------------------------------


class TestInterfaceRangeRoundTrip:
    def test_flat_input_collapses_then_reparses_stable(self):
        """Input is flat per-interface; render auto-collapses; re-
        parse gets the same canonical tree back."""
        raw = (
            "set interfaces ge-0/0/0 mtu 9000\n"
            "set interfaces ge-0/0/1 mtu 9000\n"
            "set interfaces ge-0/0/2 mtu 9000\n"
            "set interfaces ge-0/0/3 mtu 9000\n"
        )
        codec = JunosCodec()
        first = codec.parse(raw)
        rendered = codec.render(first)
        # Rendered form uses interface-range.
        assert "interface-range AUTO-RANGE-1" in rendered
        second = codec.parse(rendered)
        # Canonical trees match.
        assert len(second.interfaces) == 4
        for iface in second.interfaces:
            assert iface.mtu == 9000

    def test_range_input_roundtrips_via_flat_or_range_rendering(self):
        """Input uses interface-range; render collapses if members
        ≥3, else emits flat.  Either way, re-parse produces the
        same canonical tree."""
        raw = (
            "set interfaces interface-range UPLINKS member ge-0/0/0\n"
            "set interfaces interface-range UPLINKS member ge-0/0/1\n"
            "set interfaces interface-range UPLINKS member ge-0/0/2\n"
            'set interfaces interface-range UPLINKS description "uplink"\n'
            "set interfaces interface-range UPLINKS mtu 9000\n"
        )
        codec = JunosCodec()
        first = codec.parse(raw)
        rendered = codec.render(first)
        second = codec.parse(rendered)
        for iface in second.interfaces:
            assert iface.mtu == 9000
            assert iface.description == "uplink"
        assert len(second.interfaces) == 3

    def test_mtu_on_parse_survives(self):
        """``set interfaces X mtu N`` at top level populates
        CanonicalInterface.mtu (previously unparsed)."""
        raw = "set interfaces ge-0/0/0 mtu 9000\n"
        intent = JunosCodec().parse(raw)
        iface = intent.interfaces[0]
        assert iface.name == "ge-0/0/0"
        assert iface.mtu == 9000
