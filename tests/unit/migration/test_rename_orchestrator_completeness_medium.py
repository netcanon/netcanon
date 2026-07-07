"""Rename-orchestrator completeness — 2026-07-06 review theme 2 (#17-#20).

The rename/transform orchestrators walked an incomplete canonical-reference
set and misreported.  These are the four MEDIUM completeness gaps:

* #17 port-rename target collision: two sources -> one name, no detection.
* #18 VLAN rename with an existing SVI: two overlapping ``Vlan<N>`` stanzas.
* #19 empty-string port-rename drop key deletes gateway-only routes / pools.
* #20 ``project_switchport_to_vlan`` trunk-all stamp is order-dependent +
  non-idempotent.

All four are on the /plan-with-overrides (or codec-parse transform) path, not
the bare cross-mesh, so they are mesh-flat.  Each assertion below fails against
the pre-fix code (verified by stashing the fix).
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from netcanon.migration.canonical.port_names import translate_port_names
from netcanon.migration.canonical.transforms import project_switchport_to_vlan
from netcanon.migration.canonical.vlan_names import translate_vlan_ids
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec

pytestmark = pytest.mark.unit


# ── #17 port-rename target collision ───────────────────────────────────


class TestPortRenameTargetCollision:
    def test_two_sources_to_one_target_warns(self) -> None:
        # Two ports renamed onto one target name previously collided silently
        # (warnings=[]).  The orchestrator now surfaces it (warn-only: it does
        # not drop config, so render-side dedup on targets that have it — e.g.
        # FortiGate — still runs).
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="GigabitEthernet1/0/1", description="LINK-A"),
                CanonicalInterface(name="GigabitEthernet1/0/2", description="LINK-B"),
            ],
        )
        result = translate_port_names(
            intent,
            CiscoIOSXECLICodec(),
            CiscoIOSXECLICodec(),
            rename_map={
                "GigabitEthernet1/0/1": "GigabitEthernet1/0/9",
                "GigabitEthernet1/0/2": "GigabitEthernet1/0/9",
            },
        )
        assert any(
            "map to 'GigabitEthernet1/0/9'" in w and "GigabitEthernet1/0/1" in w
            for w in result.warnings
        )


# ── #18 VLAN rename with an existing SVI ───────────────────────────────


class TestSviRenameTracking:
    def _svi_intent(self) -> CanonicalIntent:
        return CanonicalIntent(
            vlans=[CanonicalVlan(id=10, name="DATA")],
            interfaces=[
                CanonicalInterface(
                    name="Vlan10",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.1.1.1", prefix_length=24)
                    ],
                ),
            ],
        )

    def test_rename_renames_the_svi_interface(self) -> None:
        intent = self._svi_intent()
        translate_vlan_ids(intent, {10: 20})
        names = [i.name for i in intent.interfaces]
        assert names == ["Vlan20"]  # not both Vlan10 and Vlan20

    def test_drop_removes_the_svi_interface(self) -> None:
        intent = self._svi_intent()
        result = translate_vlan_ids(intent, {10: None})
        assert [i.name for i in intent.interfaces] == []
        assert any("Vlan10" in w and "dropped" in w for w in result.warnings)

    def test_rename_onto_existing_svi_merges(self) -> None:
        intent = CanonicalIntent(
            vlans=[CanonicalVlan(id=10), CanonicalVlan(id=20)],
            interfaces=[
                CanonicalInterface(
                    name="Vlan10",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.1.1.1", prefix_length=24)
                    ],
                ),
                CanonicalInterface(
                    name="Vlan20",
                    ipv4_addresses=[
                        CanonicalIPv4Address(ip="10.2.2.1", prefix_length=24)
                    ],
                ),
            ],
        )
        translate_vlan_ids(intent, {10: 20})
        svis = [i for i in intent.interfaces if i.name == "Vlan20"]
        assert len(svis) == 1  # merged, not duplicated
        ips = {a.ip for a in svis[0].ipv4_addresses}
        assert ips == {"10.1.1.1", "10.2.2.1"}


# ── #19 empty-string drop key ──────────────────────────────────────────


class TestEmptyKeyDropGuard:
    def test_empty_key_does_not_delete_gateway_only_route(self) -> None:
        intent = CanonicalIntent(
            static_routes=[
                CanonicalStaticRoute(destination="0.0.0.0/0", gateway="1.2.3.4"),
            ],
        )
        result = translate_port_names(
            intent,
            CiscoIOSXECLICodec(),
            CiscoIOSXECLICodec(),
            rename_map={"": None},
        )
        # The default route (interface == '') must survive the empty drop key.
        assert len(intent.static_routes) == 1
        assert intent.static_routes[0].destination == "0.0.0.0/0"
        assert any("empty or blank" in w for w in result.warnings)


# ── #20 trunk-all projection order-independence + idempotency ──────────


class TestProjectSwitchportTrunkAllOrder:
    def _uplink_before_access(self) -> CanonicalIntent:
        # Trunk-all uplink DECLARED BEFORE an access port whose VLAN has no
        # top-level stanza (realistic: stacked switch, uplink on member 1).
        return CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="Ethernet1",
                    switchport_mode="trunk",
                    trunk_allowed_vlans=list(range(1, 4095)),  # trunk-all sentinel
                ),
                CanonicalInterface(
                    name="Ethernet2",
                    switchport_mode="access",
                    access_vlan=99,  # no CanonicalVlan(99) declared
                ),
            ],
        )

    def test_trunk_all_stamps_regardless_of_interface_order(self) -> None:
        intent = self._uplink_before_access()
        project_switchport_to_vlan(intent)
        vlan99 = next(v for v in intent.vlans if v.id == 99)
        # The trunk-all uplink must be tagged on the later-synthesised VLAN.
        assert "Ethernet1" in vlan99.tagged_ports
        assert "Ethernet2" in vlan99.untagged_ports

    def test_projection_is_idempotent(self) -> None:
        intent = self._uplink_before_access()
        project_switchport_to_vlan(intent)
        first = {
            v.id: (sorted(v.tagged_ports), sorted(v.untagged_ports))
            for v in intent.vlans
        }
        project_switchport_to_vlan(intent)
        second = {
            v.id: (sorted(v.tagged_ports), sorted(v.untagged_ports))
            for v in intent.vlans
        }
        assert first == second
