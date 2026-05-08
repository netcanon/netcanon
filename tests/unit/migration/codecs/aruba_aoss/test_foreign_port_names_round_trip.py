"""Regression guards — Junos-style port names survive Aruba round-trip.

Phase 4 mesh agent (juniper_junos source) flagged eight CODEC_BUG cells
for the ``aruba_aoss`` target.  Triage traced them to three connected
parser/renderer issues:

1.  ``_parse_port_list`` shredded foreign-vendor port names containing
    ``-`` (Junos ``xe-0/0/0``, ``et-0/0/48``) into pieces because the
    range-detection logic was unconditional on any ``-`` in the token.
    AOS-S ranges always have a digit immediately before ``-``; the
    fix gates range-expansion on both lo/hi halves matching the
    AOS-S native port-shape grammar.

2.  ``_format_port_list`` collapsed any tokens with a shared alpha
    prefix into ``prefix<lo>-prefix<hi>`` form, even for foreign-
    vendor names like Junos ``ae0`` / ``ae1``.  The result was
    ``ae0-ae1`` — invalid AOS-S syntax that the parse path then
    shredded back into ``["ae", "0", "1"]``.  Fix: range-collapse
    only fires for AOS-S native prefix shapes (empty / single-letter
    / ``<digit>/`` / ``<digit>/<letter>`` / ``trk``).

3.  Aruba parse populated VLAN-centric ``tagged_ports`` /
    ``untagged_ports`` from interface stanzas via
    ``project_switchport_to_vlan`` but did NOT run the inverse
    ``project_vlan_to_switchport``, so the per-iface
    ``switchport_mode`` / ``trunk_allowed_vlans`` view that
    Phase 4's comparator audits never appeared on round-trip.

4.  Aruba SVI-absorption over-attributed VRF-bound IRB IPs onto the
    matching ``vlan N`` block.  Aruba's vlan stanza has no VRF
    concept, so absorbing IPs from a VRF-bound IRB silently strips
    the routing-instance binding.  The Junos parser already
    preserves these IRBs as standalone interfaces (per its step-3
    "load-bearing-iface" guard); the Aruba renderer must respect
    that decision.

5.  Trunk-all sentinel (``vlan members all``) lost ``switchport_mode``
    on round-trip.  ``project_switchport_to_vlan`` deliberately
    skips synthesising 4094 phantom VLANs, but it can still stamp
    the trunk-all iface onto every operator-DECLARED vlan's
    ``tagged_ports`` so the symmetric ``project_vlan_to_switchport``
    on the target side recovers trunk-mode.

These tests pin the corrected behaviour at the unit-tier so the
parse/render pair stays self-consistent regardless of which Phase 4
fixture surfaces a regression.
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
from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec
from netcanon.migration.codecs.aruba_aoss.parse import _parse_port_list
from netcanon.migration.codecs.aruba_aoss.render import _format_port_list

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 1. Foreign-vendor port-name round-trip (parse-side range gating)
# ---------------------------------------------------------------------------


class TestParseDoesNotShredForeignPortNames:
    """``_parse_port_list`` must keep hyphenated foreign-vendor port
    names intact.  AOS-S ranges always have a digit before ``-`` —
    when either endpoint isn't a valid AOS-S port shape, the token
    falls through to the single-name branch.
    """

    def test_junos_xe_port_name_survives(self):
        # Single-token Junos port name with embedded hyphens.
        assert _parse_port_list("xe-0/0/0") == ["xe-0/0/0"]

    def test_junos_xe_comma_list_preserves_each(self):
        assert _parse_port_list("xe-0/0/0,xe-0/0/2") == [
            "xe-0/0/0", "xe-0/0/2",
        ]

    def test_junos_et_comma_list_preserves_each(self):
        assert _parse_port_list("et-0/0/48,et-0/0/49") == [
            "et-0/0/48", "et-0/0/49",
        ]

    def test_native_aos_range_still_expands(self):
        # Regression: must keep working for native AOS-S ranges.
        assert _parse_port_list("1-5") == ["1", "2", "3", "4", "5"]
        assert _parse_port_list("A1-A3") == ["A1", "A2", "A3"]
        assert _parse_port_list("1/1-1/4") == ["1/1", "1/2", "1/3", "1/4"]

    def test_mixed_native_and_foreign(self):
        # Real wire form from cross-vendor ksator_qfx5100 round-trip.
        assert _parse_port_list("xe-0/0/2,1/1") == ["xe-0/0/2", "1/1"]


# ---------------------------------------------------------------------------
# 2. Foreign-vendor port-name format-side
# ---------------------------------------------------------------------------


class TestFormatDoesNotMisCollapseForeignPortNames:
    """``_format_port_list`` must NOT collapse Junos ``ae0``/``ae1``
    into ``ae0-ae1``.  AOS-S syntax accepts only specific prefix
    shapes for range collapse.
    """

    def test_junos_ae_pair_stays_comma_joined(self):
        assert _format_port_list(["ae0", "ae1"]) == "ae0,ae1"

    def test_junos_xe_pair_stays_comma_joined(self):
        assert _format_port_list(["xe-0/0/0", "xe-0/0/2"]) == (
            "xe-0/0/0,xe-0/0/2"
        )

    def test_mikrotik_bond_pair_stays_comma_joined(self):
        assert _format_port_list(["bond1", "bond2"]) == "bond1,bond2"

    def test_native_numeric_still_collapses(self):
        # Regression: native AOS-S ports MUST still collapse.
        assert _format_port_list(["1", "2", "3", "4"]) == "1-4"
        assert _format_port_list(["A1", "A2", "A3"]) == "A1-A3"
        assert _format_port_list(["Trk1", "Trk2"]) == "Trk1-Trk2"

    def test_round_trip_preserves_foreign_list(self):
        for ports in [
            ["ae0", "ae1"],
            ["xe-0/0/0", "xe-0/0/2"],
            ["xe-0/0/2", "ae0", "ae1"],
            ["bond1", "lagg0"],
        ]:
            formatted = _format_port_list(ports)
            assert _parse_port_list(formatted) == ports, (
                f"round-trip diverged for {ports}: "
                f"formatted={formatted!r} reparsed={_parse_port_list(formatted)}"
            )


# ---------------------------------------------------------------------------
# 3. Aruba parse derives switchport_mode from VLAN tagged_ports
# ---------------------------------------------------------------------------


class TestArubaParseProjectsVlanToSwitchport:
    """A foreign-vendor source carrying VLAN-centric tagged_ports must
    end up with per-iface ``switchport_mode='trunk'`` after Aruba's
    parse pass.  Otherwise Phase 4's comparator sees source
    ``switchport_mode='trunk'`` vs. target ``None`` as drift.
    """

    def test_iface_tagged_in_vlan_becomes_trunk_on_reparse(self):
        # Build a minimal VLAN-centric AOS-S config and verify the
        # interface picks up trunk mode + allowed VLANs after parse.
        cfg = (
            "hostname test\n"
            "vlan 10\n"
            '   name "USERS"\n'
            "   tagged 1/1\n"
            "   exit\n"
            "vlan 20\n"
            '   name "VOICE"\n'
            "   tagged 1/1\n"
            "   exit\n"
            "interface 1/1\n"
            "   enable\n"
            "   exit\n"
        )
        intent = ArubaAOSSCodec().parse(cfg)
        iface = next(i for i in intent.interfaces if i.name == "1/1")
        assert iface.switchport_mode == "trunk"
        assert sorted(iface.trunk_allowed_vlans) == [10, 20]

    def test_iface_untagged_in_vlan_becomes_access_on_reparse(self):
        cfg = (
            "hostname test\n"
            "vlan 10\n"
            '   name "USERS"\n'
            "   untagged 1/1\n"
            "   exit\n"
            "interface 1/1\n"
            "   enable\n"
            "   exit\n"
        )
        intent = ArubaAOSSCodec().parse(cfg)
        iface = next(i for i in intent.interfaces if i.name == "1/1")
        assert iface.switchport_mode == "access"
        assert iface.access_vlan == 10


# ---------------------------------------------------------------------------
# 4. Aruba SVI-absorption skips VRF-bound IRBs
# ---------------------------------------------------------------------------


class TestArubaSviAbsorptionRespectsVrf:
    """A VRF-bound IRB / SVI must NOT have its IP absorbed into the
    matching ``vlan N`` block — Aruba's vlan stanza has no VRF
    concept and the binding would silently disappear.
    """

    def test_vrf_bound_irb_not_absorbed(self):
        intent = CanonicalIntent(
            vlans=[CanonicalVlan(id=100, name="TENANT_A_DATA")],
            interfaces=[CanonicalInterface(
                name="irb.100",
                vrf="TENANT_A",
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="172.16.100.3", prefix_length=24,
                )],
            )],
        )
        out = ArubaAOSSCodec().render(intent)
        # The VRF-bound IRB IP must NOT appear inside vlan 100's block.
        # Slice the vlan 100 stanza.
        start = out.index("vlan 100\n")
        block = out[start:out.index("   exit", start)]
        assert "ip address 172.16.100.3/24" not in block
        # The IRB iface stanza retains the IP (the operator can still
        # see it; it's just not folded into the vlan block).
        assert "172.16.100.3" in out

    def test_unbound_irb_still_absorbs(self):
        # Regression: a default-VRF IRB MUST still absorb (Junos
        # default-routing-instance case from same-vendor round-trip).
        intent = CanonicalIntent(
            vlans=[CanonicalVlan(id=100, name="USERS")],
            interfaces=[CanonicalInterface(
                name="irb.100",
                # No vrf — default routing instance.
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.10.100.1", prefix_length=24,
                )],
            )],
        )
        out = ArubaAOSSCodec().render(intent)
        start = out.index("vlan 100\n")
        block = out[start:out.index("   exit", start)]
        assert "ip address 10.10.100.1/24" in block


# ---------------------------------------------------------------------------
# 5. Trunk-all sentinel preserves switchport state via canonical layer
# ---------------------------------------------------------------------------


class TestTrunkAllSentinelStampsTaggedPorts:
    """Source iface with ``trunk_allowed_vlans=[1..4094]`` must land
    in every operator-declared vlan's ``tagged_ports`` after the
    canonical projection runs (closing the previous round-trip gap
    where Aruba's render + reparse lost trunk mode).
    """

    def test_trunk_all_iface_lands_in_declared_vlans(self):
        from netcanon.migration.canonical.transforms import (
            project_switchport_to_vlan,
        )
        intent = CanonicalIntent(
            vlans=[
                CanonicalVlan(id=10, name="V10"),
                CanonicalVlan(id=20, name="V20"),
            ],
            interfaces=[CanonicalInterface(
                name="ae0",
                switchport_mode="trunk",
                trunk_allowed_vlans=list(range(1, 4095)),  # trunk-all
            )],
        )
        project_switchport_to_vlan(intent)
        v10 = next(v for v in intent.vlans if v.id == 10)
        v20 = next(v for v in intent.vlans if v.id == 20)
        assert "ae0" in v10.tagged_ports
        assert "ae0" in v20.tagged_ports
        # Crucially: NO synthesis of phantom 4094 VLANs.
        assert {v.id for v in intent.vlans} == {10, 20}


# ---------------------------------------------------------------------------
# 6. Junos LAG-name normalisation on Arista render
# ---------------------------------------------------------------------------


class TestJunosLagNameToArista:
    """Junos canonical LAG names (``ae<N>``) get translated to
    Arista's ``Port-Channel<N>`` form on render so the channel-group
    binding survives parse-back.
    """

    def test_junos_ae_translates_to_port_channel(self):
        from netcanon.migration.codecs.arista_eos.codec import AristaEOSCodec
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="Ethernet48",
                    lag_member_of="ae1",
                ),
                CanonicalInterface(
                    name="Ethernet49",
                    lag_member_of="ae1",
                ),
            ],
            lags=[CanonicalLAG(
                name="ae1",
                members=["Ethernet48", "Ethernet49"],
                mode="active",
            )],
        )
        out = AristaEOSCodec().render(intent)
        # Member iface gets a channel-group binding.
        assert "channel-group 1 mode active" in out
        # LAG stub is emitted under the Arista-native name.
        assert "interface Port-Channel1" in out
        # The Junos-shape stub is NOT leaked.
        assert "\ninterface ae1\n" not in out

    def test_junos_ae_round_trips_through_arista(self):
        from netcanon.migration.codecs.arista_eos.codec import AristaEOSCodec
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="Ethernet48",
                    lag_member_of="ae1",
                ),
            ],
            lags=[CanonicalLAG(
                name="ae1",
                members=["Ethernet48"],
                mode="active",
            )],
        )
        rendered = AristaEOSCodec().render(intent)
        reparsed = AristaEOSCodec().parse(rendered)
        # After round-trip the LAG should be Port-Channel1.
        assert any(l.name == "Port-Channel1" for l in reparsed.lags)
        eth = next(i for i in reparsed.interfaces if i.name == "Ethernet48")
        assert eth.lag_member_of == "Port-Channel1"
