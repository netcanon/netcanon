"""
Unit tests for :mod:`netcanon.migration.canonical.transforms` — the
shared post-parse bridging transforms between port-centric and VLAN-
centric VLAN membership representations.  Covers Bug 3 from
translator-plans.txt (KNOWN DATA-LOSS BUGS).
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalVlan,
)
from netcanon.migration.canonical.transforms import (
    project_switchport_to_vlan,
    project_vlan_to_switchport,
    synthesize_svis_from_vlan_l3,
    trunk_untagged_vlan,
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

    @pytest.mark.parametrize("allowed", [[10], [], list(range(2, 4095))])
    def test_native_outside_the_list_no_member(self, allowed):
        """The list is what the trunk carries.  A native VLAN it does
        not hold is stated and not carried: the port is made no member
        of that VLAN, tagged or untagged.  (It was made an untagged
        member whatever the list said, and a target that is told VLAN
        by VLAN then carried a VLAN the source trunk did not.)"""
        native = 1 if len(allowed) > 1 else 99
        intent = _mk_intent(
            interfaces=[
                CanonicalInterface(
                    name="Gi1/0/24",
                    switchport_mode="trunk",
                    trunk_allowed_vlans=list(allowed),
                    trunk_native_vlan=native,
                )
            ],
            vlans=[CanonicalVlan(id=10)],
        )
        project_switchport_to_vlan(intent)
        by_id = {v.id: v for v in intent.vlans}
        # The record of a stated native VLAN is made all the same.
        assert native in by_id
        assert by_id[native].untagged_ports == [] and by_id[native].tagged_ports == []
        assert by_id[10].tagged_ports == (["Gi1/0/24"] if 10 in allowed else [])

    def test_a_native_vlan_in_every_vlan(self):
        intent = _mk_intent(
            interfaces=[
                CanonicalInterface(
                    name="Gi1/0/24",
                    switchport_mode="trunk",
                    trunk_allowed_vlans=list(range(1, 4095)),
                    trunk_native_vlan=99,
                )
            ],
            vlans=[CanonicalVlan(id=10)],
        )
        project_switchport_to_vlan(intent)
        by_id = {v.id: v for v in intent.vlans}
        assert by_id[99].untagged_ports == ["Gi1/0/24"] and by_id[99].tagged_ports == []
        assert by_id[10].tagged_ports == ["Gi1/0/24"]

    def test_what_a_list_held_already_is_left(self):
        """Outside the list nothing is added and nothing is taken out."""
        intent = _mk_intent(
            interfaces=[
                CanonicalInterface(
                    name="Gi1", switchport_mode="trunk", trunk_allowed_vlans=[10], trunk_native_vlan=99,
                )
            ],
            vlans=[CanonicalVlan(id=10), CanonicalVlan(id=99, tagged_ports=["Gi1"])],
        )
        project_switchport_to_vlan(intent)
        v99 = next(v for v in intent.vlans if v.id == 99)
        assert (v99.tagged_ports, v99.untagged_ports) == (["Gi1"], [])


class TestTheUntaggedVlanOfATrunk:
    @pytest.mark.parametrize("allowed,native,carried", [
        ([10, 20, 30], 10, 10),
        ([20, 30], 10, None),
        ([], 10, None),
        ([20, 30], None, None),
        (list(range(1, 4095)), 999, 999),
        (list(range(2, 4095)), 1, None),
        ((10, 20), 20, 20),
    ])
    def test_native_where_the_list_holds_it(self, allowed, native, carried):
        assert trunk_untagged_vlan(allowed, native) == carried

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
        from netcanon.migration.codecs.aruba_aoss import ArubaAOSSCodec
        from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec

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
        from netcanon.migration.codecs.aruba_aoss import ArubaAOSSCodec
        from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec

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
        # The list is what the trunk carries: the VLAN it is tagged in
        # and the one it is untagged in.
        assert i.trunk_allowed_vlans == [10, 99]

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


# ---------------------------------------------------------------------------
# synthesize_svis_from_vlan_l3 — inverse of project_svi_to_vlan
# ---------------------------------------------------------------------------


class TestSynthesizeSvisFromVlanL3:
    """A VLAN carrying L3 (``ipv4_addresses``) with no sibling
    ``Vlan<N>`` interface — the shape a Junos ``irb`` + ``l3-interface``
    source produces — gets a synthetic ``Vlan<N>`` SVI so SVI-model
    renderers (Arista, IOS-XE) can emit the L3 instead of dropping it."""

    def test_synthesises_svi_when_absent(self):
        intent = _mk_intent(
            vlans=[
                CanonicalVlan(
                    id=698,
                    name="VLAN698",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.200.1.1", prefix_length=22)
                    ],
                )
            ],
        )
        svis = synthesize_svis_from_vlan_l3(intent)
        assert len(svis) == 1
        assert svis[0].name == "Vlan698"
        assert [(a.ip, a.prefix_length) for a in svis[0].ipv4_addresses] == [
            ("10.200.1.1", 22)
        ]

    def test_skips_when_svi_interface_already_present(self):
        """Same-vendor parse keeps the ``Vlan<N>`` interface — no
        double-emit (case-insensitive match on the SVI name)."""
        intent = _mk_intent(
            interfaces=[
                CanonicalInterface(
                    name="Vlan698",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.200.1.1", prefix_length=22)
                    ],
                )
            ],
            vlans=[
                CanonicalVlan(
                    id=698,
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.200.1.1", prefix_length=22)
                    ],
                )
            ],
        )
        assert synthesize_svis_from_vlan_l3(intent) == []

    def test_skips_l3_empty_vlan(self):
        intent = _mk_intent(vlans=[CanonicalVlan(id=10, name="DATA")])
        assert synthesize_svis_from_vlan_l3(intent) == []

    def test_dedupes_addresses(self):
        intent = _mk_intent(
            vlans=[
                CanonicalVlan(
                    id=5,
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.0.5.1", prefix_length=24),
                        CanonicalIPv4Address(ip="10.0.5.1", prefix_length=24),
                    ],
                )
            ],
        )
        svis = synthesize_svis_from_vlan_l3(intent)
        assert len(svis[0].ipv4_addresses) == 1

    def test_non_mutating(self):
        """Contract: the cross-mesh runner reuses one parsed intent
        across target renders, so this must not touch intent.interfaces."""
        intent = _mk_intent(
            vlans=[
                CanonicalVlan(
                    id=7,
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.0.7.1", prefix_length=24)
                    ],
                )
            ],
        )
        before = len(intent.interfaces)
        synthesize_svis_from_vlan_l3(intent)
        assert len(intent.interfaces) == before


class TestJunosVlanL3ToSviRender:
    """End-to-end: a Junos ``irb`` + ``l3-interface`` VLAN L3 survives
    translation to the SVI-model targets (Arista, IOS-XE).  Regression
    for the cross-mesh CODEC_BUG surfaced by the ``saidvandeklundert``
    real fixture (PR #68): the VLAN SVI address dropped on render."""

    JUNOS_SRC = (
        "set interfaces irb unit 698 family inet address 10.200.1.1/22\n"
        "set vlans VLAN698 vlan-id 698\n"
        "set vlans VLAN698 l3-interface irb.698\n"
    )

    def _intent(self):
        from netcanon.migration.codecs.juniper_junos.codec import JunosCodec

        return JunosCodec().parse(self.JUNOS_SRC)

    def test_junos_to_arista_emits_svi_and_round_trips(self):
        from netcanon.migration.codecs.arista_eos.codec import AristaEOSCodec

        codec = AristaEOSCodec()
        out = codec.render(self._intent())
        assert "interface Vlan698" in out
        assert "10.200.1.1/22" in out
        reparsed = codec.parse(out)
        v = next(x for x in reparsed.vlans if x.id == 698)
        assert [(a.ip, a.prefix_length) for a in v.ipv4_addresses] == [
            ("10.200.1.1", 22)
        ]

    def test_junos_to_iosxe_cli_emits_svi_and_round_trips(self):
        from netcanon.migration.codecs.cisco_iosxe_cli.codec import (
            CiscoIOSXECLICodec,
        )

        codec = CiscoIOSXECLICodec()
        out = codec.render(self._intent())
        assert "interface Vlan698" in out
        assert "10.200.1.1" in out
        reparsed = codec.parse(out)
        v = next(x for x in reparsed.vlans if x.id == 698)
        assert [(a.ip, a.prefix_length) for a in v.ipv4_addresses] == [
            ("10.200.1.1", 22)
        ]

    def test_arista_same_vendor_no_double_svi(self):
        from netcanon.migration.codecs.arista_eos.codec import AristaEOSCodec

        own = (
            "vlan 698\n   name VLAN698\n!\n"
            "interface Vlan698\n   ip address 10.200.1.1/22\n!\n"
        )
        codec = AristaEOSCodec()
        out = codec.render(codec.parse(own))
        assert out.count("interface Vlan698") == 1


# ---------------------------------------------------------------------------
# "All" is the VLANs the list holds
# ---------------------------------------------------------------------------


def _one_trunk(allowed: list[int]) -> CanonicalIntent:
    return CanonicalIntent(
        vlans=[CanonicalVlan(id=1, name="default"), CanonicalVlan(id=10, name="users")],
        interfaces=[CanonicalInterface(
            name="Ethernet1", switchport_mode="trunk", trunk_allowed_vlans=allowed,
        )],
    )


def test_a_trunk_of_all_but_vlan_1_is_not_stamped_onto_vlan_1() -> None:
    """`2-4094` is read as "all" so that 4,093 VLANs are not made for
    it, and the trunk is stamped onto the VLANs the config declares.
    It was stamped onto a declared VLAN 1 too -- the one VLAN the list
    leaves out -- and a VLAN-centric target then tagged the port in it."""
    intent = _one_trunk(list(range(2, 4095)))
    project_switchport_to_vlan(intent)
    by_id = {vlan.id: vlan for vlan in intent.vlans}
    assert by_id[10].tagged_ports == ["Ethernet1"]
    assert by_id[1].tagged_ports == []
    assert sorted(by_id) == [1, 10]


def test_a_trunk_of_every_vlan_is_stamped_onto_each() -> None:
    intent = _one_trunk(list(range(1, 4095)))
    project_switchport_to_vlan(intent)
    assert {vlan.id: vlan.tagged_ports for vlan in intent.vlans} == {
        1: ["Ethernet1"], 10: ["Ethernet1"],
    }
