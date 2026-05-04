"""
Unit tests for :mod:`netconfig.migration.canonical.transforms` — the
shared post-parse bridging transforms between port-centric and VLAN-
centric VLAN membership representations.  Covers Bug 3 from
translator-plans.txt (KNOWN DATA-LOSS BUGS).
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalVlan,
)
from netconfig.migration.canonical.transforms import (
    project_switchport_to_vlan,
    project_vlan_to_switchport,
)

pytestmark = pytest.mark.unit


def _mk_intent(interfaces=None, vlans=None):
    return CanonicalIntent(
        source_vendor="test",
        source_format="test",
        interfaces=list(interfaces or []),
        vlans=list(vlans or []),
    )


# ---------------------------------------------------------------------------
# project_switchport_to_vlan
# ---------------------------------------------------------------------------


class TestSwitchportToVlan:
    """Port-centric -> VLAN-centric mirroring."""

    def test_access_port_populates_untagged(self):
        intent = _mk_intent(
            interfaces=[
                CanonicalInterface(
                    name="Gi1/0/1", switchport_mode="access", access_vlan=10
                )
            ],
            vlans=[CanonicalVlan(id=10, name="DATA")],
        )
        project_switchport_to_vlan(intent)
        assert intent.vlans[0].untagged_ports == ["Gi1/0/1"]
        assert intent.vlans[0].tagged_ports == []

    def test_trunk_port_populates_tagged_for_each_allowed(self):
        intent = _mk_intent(
            interfaces=[
                CanonicalInterface(
                    name="Gi1/0/24",
                    switchport_mode="trunk",
                    trunk_allowed_vlans=[10, 20, 30],
                )
            ],
            vlans=[
                CanonicalVlan(id=10),
                CanonicalVlan(id=20),
                CanonicalVlan(id=30),
            ],
        )
        project_switchport_to_vlan(intent)
        for vlan in intent.vlans:
            assert vlan.tagged_ports == ["Gi1/0/24"]
            assert vlan.untagged_ports == []

    def test_trunk_native_vlan_is_untagged_not_tagged(self):
        """Native VLAN rides the trunk untagged; it must appear in
        untagged_ports even if also listed in allowed."""
        intent = _mk_intent(
            interfaces=[
                CanonicalInterface(
                    name="Gi1/0/24",
                    switchport_mode="trunk",
                    trunk_allowed_vlans=[10, 99],
                    trunk_native_vlan=99,
                )
            ],
            vlans=[CanonicalVlan(id=10), CanonicalVlan(id=99)],
        )
        project_switchport_to_vlan(intent)
        v10 = next(v for v in intent.vlans if v.id == 10)
        v99 = next(v for v in intent.vlans if v.id == 99)
        assert v10.tagged_ports == ["Gi1/0/24"]
        assert v99.untagged_ports == ["Gi1/0/24"]
        # Native VLAN must NOT also be in tagged_ports.
        assert v99.tagged_ports == []

    def test_missing_vlan_gets_synthesized(self):
        """A port references VLAN 20 but no top-level `vlan 20` stanza
        exists — the transform must create a bare VLAN record so the
        membership isn't lost."""
        intent = _mk_intent(
            interfaces=[
                CanonicalInterface(
                    name="Gi1/0/1", switchport_mode="access", access_vlan=20
                )
            ],
            vlans=[],
        )
        project_switchport_to_vlan(intent)
        assert len(intent.vlans) == 1
        assert intent.vlans[0].id == 20
        assert intent.vlans[0].untagged_ports == ["Gi1/0/1"]

    def test_idempotent(self):
        intent = _mk_intent(
            interfaces=[
                CanonicalInterface(
                    name="Gi1/0/1", switchport_mode="access", access_vlan=10
                )
            ],
            vlans=[CanonicalVlan(id=10)],
        )
        project_switchport_to_vlan(intent)
        project_switchport_to_vlan(intent)
        project_switchport_to_vlan(intent)
        assert intent.vlans[0].untagged_ports == ["Gi1/0/1"]

    def test_routed_ports_ignored(self):
        """switchport_mode=None means routed port — no VLAN membership."""
        intent = _mk_intent(
            interfaces=[
                CanonicalInterface(name="Gi1/0/1", switchport_mode=None)
            ],
            vlans=[CanonicalVlan(id=10)],
        )
        project_switchport_to_vlan(intent)
        assert intent.vlans[0].untagged_ports == []
        assert intent.vlans[0].tagged_ports == []

    def test_preserves_existing_membership(self):
        """If a VLAN already has ports from another source (e.g. an
        Aruba-style `untagged 1-24` parse), new additions append
        without clobbering."""
        intent = _mk_intent(
            interfaces=[
                CanonicalInterface(
                    name="Gi1/0/5", switchport_mode="access", access_vlan=10
                )
            ],
            vlans=[CanonicalVlan(id=10, untagged_ports=["existing-port-A"])],
        )
        project_switchport_to_vlan(intent)
        # Phase 4b Wave 7c: project_switchport_to_vlan now applies a
        # natural-port sort to the resulting membership lists so cross-
        # vendor round-trips produce stable port-list order.  Both
        # entries are present; their order reflects natural sort
        # (alpha-prefix tokens like ``existing-port-A`` follow
        # numeric-trailing tokens like ``Gi1/0/5``).
        assert set(intent.vlans[0].untagged_ports) == {
            "existing-port-A", "Gi1/0/5",
        }

    def test_mixed_access_and_trunk(self):
        """Real-world 9300: most ports access + a couple of trunks."""
        intent = _mk_intent(
            interfaces=[
                CanonicalInterface(
                    name="Gi1/0/1", switchport_mode="access", access_vlan=10
                ),
                CanonicalInterface(
                    name="Gi1/0/2", switchport_mode="access", access_vlan=10
                ),
                CanonicalInterface(
                    name="Gi1/0/3", switchport_mode="access", access_vlan=20
                ),
                CanonicalInterface(
                    name="Te1/1/1",
                    switchport_mode="trunk",
                    trunk_allowed_vlans=[10, 20, 99],
                    trunk_native_vlan=99,
                ),
            ],
            vlans=[
                CanonicalVlan(id=10, name="DATA"),
                CanonicalVlan(id=20, name="VOICE"),
                CanonicalVlan(id=99, name="MGMT"),
            ],
        )
        project_switchport_to_vlan(intent)
        by_id = {v.id: v for v in intent.vlans}
        assert by_id[10].untagged_ports == ["Gi1/0/1", "Gi1/0/2"]
        assert by_id[10].tagged_ports == ["Te1/1/1"]
        assert by_id[20].untagged_ports == ["Gi1/0/3"]
        assert by_id[20].tagged_ports == ["Te1/1/1"]
        assert by_id[99].untagged_ports == ["Te1/1/1"]
        assert by_id[99].tagged_ports == []


# ---------------------------------------------------------------------------
# End-to-end: Cisco CLI parse -> Aruba render
# ---------------------------------------------------------------------------


class TestCiscoToArubaSwitchport:
    """Bug 3 end-to-end: per-port switchport lines on Cisco must
    survive into Aruba's VLAN-centric output."""

    def test_access_ports_appear_in_aruba_vlan_untagged(self):
        from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
        from netconfig.migration.codecs.aruba_aoss import ArubaAOSSCodec

        raw = """\
hostname sw1
!
vlan 10
 name DATA
!
vlan 20
 name VOICE
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 10
!
interface GigabitEthernet1/0/2
 switchport mode access
 switchport access vlan 10
!
interface GigabitEthernet1/0/3
 switchport mode access
 switchport access vlan 20
!
end
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        # Verify canonical state first.
        by_id = {v.id: v for v in intent.vlans}
        assert "GigabitEthernet1/0/1" in by_id[10].untagged_ports
        assert "GigabitEthernet1/0/2" in by_id[10].untagged_ports
        assert "GigabitEthernet1/0/3" in by_id[20].untagged_ports

        aruba_out = ArubaAOSSCodec().render(intent)
        # Aruba emits `vlan N / untagged <list>` — both port names must
        # be in the rendering (opaque strings through to the target).
        assert "vlan 10" in aruba_out
        assert "vlan 20" in aruba_out
        # Port names ride through as opaque strings.
        assert "GigabitEthernet1/0/1" in aruba_out
        assert "GigabitEthernet1/0/2" in aruba_out
        assert "GigabitEthernet1/0/3" in aruba_out

    def test_trunk_port_appears_in_aruba_vlan_tagged(self):
        from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
        from netconfig.migration.codecs.aruba_aoss import ArubaAOSSCodec

        raw = """\
hostname sw1
!
vlan 10
 name DATA
!
vlan 99
 name MGMT
!
interface TenGigabitEthernet1/1/1
 description TRUNK-TO-CORE
 switchport mode trunk
 switchport trunk allowed vlan 10,99
 switchport trunk native vlan 99
!
end
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        by_id = {v.id: v for v in intent.vlans}
        assert "TenGigabitEthernet1/1/1" in by_id[10].tagged_ports
        # Native VLAN is untagged on the trunk.
        assert "TenGigabitEthernet1/1/1" in by_id[99].untagged_ports
        assert "TenGigabitEthernet1/1/1" not in by_id[99].tagged_ports

        aruba_out = ArubaAOSSCodec().render(intent)
        assert "TenGigabitEthernet1/1/1" in aruba_out


# ---------------------------------------------------------------------------
# project_vlan_to_switchport (inverse transform)
# ---------------------------------------------------------------------------


class TestVlanToSwitchport:
    """VLAN-centric -> port-centric mirroring.  Not wired into any
    current codec — exists for future port-centric renderers."""

    def test_single_untagged_becomes_access(self):
        intent = _mk_intent(
            interfaces=[CanonicalInterface(name="ether2")],
            vlans=[CanonicalVlan(id=10, untagged_ports=["ether2"])],
        )
        project_vlan_to_switchport(intent)
        assert intent.interfaces[0].switchport_mode == "access"
        assert intent.interfaces[0].access_vlan == 10

    def test_tagged_becomes_trunk(self):
        intent = _mk_intent(
            interfaces=[CanonicalInterface(name="ether24")],
            vlans=[
                CanonicalVlan(id=10, tagged_ports=["ether24"]),
                CanonicalVlan(id=20, tagged_ports=["ether24"]),
            ],
        )
        project_vlan_to_switchport(intent)
        i = intent.interfaces[0]
        assert i.switchport_mode == "trunk"
        assert set(i.trunk_allowed_vlans) == {10, 20}

    def test_tagged_plus_untagged_picks_native(self):
        intent = _mk_intent(
            interfaces=[CanonicalInterface(name="ether24")],
            vlans=[
                CanonicalVlan(id=10, tagged_ports=["ether24"]),
                CanonicalVlan(id=99, untagged_ports=["ether24"]),
            ],
        )
        project_vlan_to_switchport(intent)
        i = intent.interfaces[0]
        assert i.switchport_mode == "trunk"
        assert i.trunk_native_vlan == 99
        assert 10 in i.trunk_allowed_vlans

    def test_existing_switchport_state_not_clobbered(self):
        intent = _mk_intent(
            interfaces=[
                CanonicalInterface(
                    name="ether2", switchport_mode="access", access_vlan=5
                )
            ],
            vlans=[CanonicalVlan(id=10, untagged_ports=["ether2"])],
        )
        project_vlan_to_switchport(intent)
        # Pre-existing state must win.
        assert intent.interfaces[0].switchport_mode == "access"
        assert intent.interfaces[0].access_vlan == 5

    def test_unknown_interface_skipped(self):
        """A VLAN referencing a port we never saw declared shouldn't
        crash — the membership lives on in the VLAN list regardless."""
        intent = _mk_intent(
            interfaces=[],
            vlans=[CanonicalVlan(id=10, untagged_ports=["ghost-port"])],
        )
        project_vlan_to_switchport(intent)  # must not raise
        assert intent.vlans[0].untagged_ports == ["ghost-port"]

    def test_idempotent(self):
        intent = _mk_intent(
            interfaces=[CanonicalInterface(name="ether2")],
            vlans=[CanonicalVlan(id=10, untagged_ports=["ether2"])],
        )
        project_vlan_to_switchport(intent)
        project_vlan_to_switchport(intent)
        assert intent.interfaces[0].switchport_mode == "access"
        assert intent.interfaces[0].access_vlan == 10
