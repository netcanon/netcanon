"""
Unit tests for :mod:`netconfig.migration.canonical.vlan_names`.

Layer A of the cross-mesh test pyramid (per the P2 strategy
document): transform-level correctness on synthetic
:class:`CanonicalIntent` trees, no I/O, no codec-specific
behaviour — VLAN IDs are universal integers.

The cross-codec mesh smoke tests (Layer B) live separately in
``test_cross_mesh_overrides.py`` under the ``@pytest.mark.cross_mesh``
marker with a documented aggregate-runtime budget.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalVlan,
)
from netconfig.migration.canonical.vlan_names import (
    VlanRenameResult,
    build_vlan_rename_transform,
    translate_vlan_ids,
)

pytestmark = pytest.mark.unit


def _tree_with_vlans(*ids: int) -> CanonicalIntent:
    """Minimal canonical tree containing the given VLAN IDs."""
    return CanonicalIntent(
        vlans=[CanonicalVlan(id=vid, name=f"V{vid}") for vid in ids],
    )


class TestIdentityAndNoOps:
    def test_empty_map_is_noop(self):
        intent = _tree_with_vlans(10, 20)
        result = translate_vlan_ids(intent, rename_map={})
        assert result.applied == {}
        assert result.dropped == []
        assert [v.id for v in intent.vlans] == [10, 20]

    def test_none_map_is_noop(self):
        intent = _tree_with_vlans(10, 20)
        result = translate_vlan_ids(intent, rename_map=None)
        assert result.applied == {}
        assert [v.id for v in intent.vlans] == [10, 20]

    def test_non_canonical_tree_returns_empty_result(self):
        """Mock codecs that parse into plain dicts must not crash
        the orchestrator.  Mirrors the defensive guard in
        port_names.translate_port_names."""
        result = translate_vlan_ids({"vlans": [{"id": 10}]}, rename_map={10: 20})
        assert result.applied == {}
        assert result.dropped == []


class TestBasicRename:
    def test_single_rename(self):
        intent = _tree_with_vlans(10, 20)
        result = translate_vlan_ids(intent, rename_map={10: 100})
        assert result.applied == {10: 100}
        assert result.dropped == []
        # VLAN IDs updated in place.
        assert sorted(v.id for v in intent.vlans) == [20, 100]

    def test_rename_preserves_name_and_description(self):
        intent = CanonicalIntent(vlans=[
            CanonicalVlan(id=10, name="USERS", description="user LAN"),
        ])
        translate_vlan_ids(intent, rename_map={10: 100})
        v = intent.vlans[0]
        assert v.id == 100
        assert v.name == "USERS"
        assert v.description == "user LAN"


class TestDropSemantics:
    def test_drop_removes_vlan(self):
        intent = _tree_with_vlans(10, 20, 30)
        result = translate_vlan_ids(intent, rename_map={20: None})
        assert result.dropped == [20]
        assert sorted(v.id for v in intent.vlans) == [10, 30]

    def test_drop_detaches_access_vlan_on_interfaces(self):
        intent = _tree_with_vlans(10, 20)
        intent.interfaces = [
            CanonicalInterface(
                name="Gi1/0/1",
                switchport_mode="access",
                access_vlan=20,
            ),
        ]
        result = translate_vlan_ids(intent, rename_map={20: None})
        iface = intent.interfaces[0]
        assert iface.access_vlan is None
        assert any("Gi1/0/1" in w for w in result.warnings)

    def test_drop_strips_trunk_allowed_vlan_entry(self):
        intent = _tree_with_vlans(10, 20, 30)
        intent.interfaces = [
            CanonicalInterface(
                name="Gi1/0/24",
                switchport_mode="trunk",
                trunk_allowed_vlans=[10, 20, 30],
                trunk_native_vlan=10,
            ),
        ]
        result = translate_vlan_ids(intent, rename_map={20: None})
        iface = intent.interfaces[0]
        assert iface.trunk_allowed_vlans == [10, 30]
        # Native VLAN wasn't dropped → unchanged.
        assert iface.trunk_native_vlan == 10
        assert 20 in result.dropped

    def test_drop_clears_trunk_native_vlan(self):
        intent = _tree_with_vlans(10, 20)
        intent.interfaces = [
            CanonicalInterface(
                name="Gi1/0/24",
                switchport_mode="trunk",
                trunk_native_vlan=20,
            ),
        ]
        result = translate_vlan_ids(intent, rename_map={20: None})
        iface = intent.interfaces[0]
        assert iface.trunk_native_vlan is None
        assert any("native" in w.lower() for w in result.warnings)

    def test_drop_clears_voice_vlan(self):
        intent = _tree_with_vlans(50, 200)
        intent.interfaces = [
            CanonicalInterface(
                name="Gi1/0/1",
                switchport_mode="access",
                access_vlan=50,
                voice_vlan=200,
            ),
        ]
        result = translate_vlan_ids(intent, rename_map={200: None})
        iface = intent.interfaces[0]
        assert iface.voice_vlan is None
        assert iface.access_vlan == 50  # untouched


class TestRenameCascadesThroughInterfaces:
    def test_access_vlan_follows_rename(self):
        intent = _tree_with_vlans(10)
        intent.interfaces = [
            CanonicalInterface(
                name="Gi1/0/1",
                switchport_mode="access",
                access_vlan=10,
            ),
        ]
        translate_vlan_ids(intent, rename_map={10: 100})
        assert intent.interfaces[0].access_vlan == 100

    def test_trunk_allowed_list_follows_rename(self):
        intent = _tree_with_vlans(10, 20, 30)
        intent.interfaces = [
            CanonicalInterface(
                name="Gi1/0/24",
                switchport_mode="trunk",
                trunk_allowed_vlans=[10, 20, 30],
            ),
        ]
        translate_vlan_ids(intent, rename_map={10: 100, 30: 300})
        assert intent.interfaces[0].trunk_allowed_vlans == [100, 20, 300]

    def test_native_and_voice_follow_rename(self):
        intent = _tree_with_vlans(10, 200)
        intent.interfaces = [
            CanonicalInterface(
                name="Gi1/0/1",
                switchport_mode="access",
                trunk_native_vlan=10,
                voice_vlan=200,
            ),
        ]
        translate_vlan_ids(intent, rename_map={10: 100, 200: 2000})
        iface = intent.interfaces[0]
        assert iface.trunk_native_vlan == 100
        assert iface.voice_vlan == 2000


class TestCollisionMerge:
    """When two source VLANs map to the same target ID (or to an ID
    already present in the tree), the orchestrator merges by union —
    it's the only sane thing to do when an operator squashes VLANs."""

    def test_multiple_sources_to_same_target_merge_port_lists(self):
        intent = CanonicalIntent(vlans=[
            CanonicalVlan(id=10, name="A", untagged_ports=["1/1", "1/2"]),
            CanonicalVlan(id=20, name="B", untagged_ports=["1/3", "1/4"]),
        ])
        result = translate_vlan_ids(intent, rename_map={10: 30, 20: 30})
        # Only one VLAN remains (the merged 30).
        assert len(intent.vlans) == 1
        merged = intent.vlans[0]
        assert merged.id == 30
        assert merged.untagged_ports == ["1/1", "1/2", "1/3", "1/4"]
        # Collision warning emitted.
        assert any("multiple source VLANs" in w for w in result.warnings)

    def test_rename_to_existing_id_merges(self):
        """Mapping 10 → 20 when 20 already exists → merge into 20's
        membership rather than silently clobbering."""
        intent = CanonicalIntent(vlans=[
            CanonicalVlan(id=10, tagged_ports=["1/1"]),
            CanonicalVlan(id=20, tagged_ports=["1/2"]),
        ])
        result = translate_vlan_ids(intent, rename_map={10: 20})
        assert len(intent.vlans) == 1
        merged = intent.vlans[0]
        assert merged.id == 20
        assert sorted(merged.tagged_ports) == ["1/1", "1/2"]
        # Warning about the target-already-exists case.
        assert any("already exists" in w for w in result.warnings)

    def test_merged_vlan_concatenates_svi_addresses(self):
        intent = CanonicalIntent(vlans=[
            CanonicalVlan(id=10, ipv4_addresses=[
                CanonicalIPv4Address(ip="10.0.1.1", prefix_length=24),
            ]),
            CanonicalVlan(id=20, ipv4_addresses=[
                CanonicalIPv4Address(ip="10.0.2.1", prefix_length=24),
            ]),
        ])
        translate_vlan_ids(intent, rename_map={10: 30, 20: 30})
        assert len(intent.vlans) == 1
        merged = intent.vlans[0]
        assert len(merged.ipv4_addresses) == 2


class TestValidation:
    """Bad input → warnings + skip, not crash."""

    def test_source_id_out_of_range_rejected(self):
        intent = _tree_with_vlans(10)
        result = translate_vlan_ids(intent, rename_map={5000: 20})
        assert result.applied == {}
        assert any("out of range" in w for w in result.warnings)

    def test_target_id_out_of_range_rejected(self):
        intent = _tree_with_vlans(10)
        result = translate_vlan_ids(intent, rename_map={10: 5000})
        assert result.applied == {}
        assert any("out of range" in w for w in result.warnings)
        # Original VLAN unchanged.
        assert intent.vlans[0].id == 10

    def test_zero_vlan_id_rejected(self):
        intent = _tree_with_vlans(10)
        result = translate_vlan_ids(intent, rename_map={0: 10})
        assert result.applied == {}
        assert any("out of range" in w for w in result.warnings)


class TestBuildTransform:
    """``build_vlan_rename_transform`` returns a pipeline-compatible
    callable + a result accumulator; outcomes populate as the
    transform runs."""

    def test_transform_is_callable_and_returns_intent(self):
        intent = _tree_with_vlans(10)
        transform, result = build_vlan_rename_transform({10: 100})
        returned = transform(intent)
        assert returned is intent
        assert intent.vlans[0].id == 100
        assert result.applied == {10: 100}

    def test_transform_accumulates_result_across_runs(self):
        """Transform can be called multiple times on different trees
        if the caller wants — the result captures all runs.  Not
        currently used by the pipeline (one tree per job) but leaves
        the option open."""
        transform, result = build_vlan_rename_transform({10: 100})
        t1 = _tree_with_vlans(10)
        t2 = _tree_with_vlans(10, 20)
        transform(t1)
        transform(t2)
        # Same rewrite applied twice → same applied entry, just once
        # in the result (dict semantics).
        assert result.applied == {10: 100}
