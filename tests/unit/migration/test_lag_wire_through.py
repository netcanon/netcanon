"""
Unit tests for :class:`CanonicalLAG` wire-through across all 5 codecs.
Covers Bug 2 from translator-plans.txt (KNOWN DATA-LOSS BUGS).

Structure:
    * One class per codec, covering parse, render (if applicable), and
      round-trip stability.
    * One cross-codec class covering the end-to-end Cisco -> Aruba
      translation that the real 9300 dogfooding hit.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
)
from netconfig.migration.codecs.aruba_aoss import ArubaAOSSCodec
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec
from netconfig.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netconfig.migration.codecs.opnsense import OPNsenseCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Cisco IOS-XE CLI — LAG producer
# ---------------------------------------------------------------------------


class TestCiscoLAGParse:
    def test_port_channel_with_members_and_mode_active(self):
        raw = """\
interface Port-channel1
 description UPLINK
!
interface GigabitEthernet1/0/1
 channel-group 1 mode active
!
interface GigabitEthernet1/0/2
 channel-group 1 mode active
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        assert len(intent.lags) == 1
        lag = intent.lags[0]
        assert lag.name == "Port-channel1"
        assert lag.members == ["GigabitEthernet1/0/1", "GigabitEthernet1/0/2"]
        assert lag.mode == "active"

    def test_members_are_lag_member_of_stamped(self):
        raw = """\
interface GigabitEthernet1/0/1
 channel-group 2 mode passive
!
interface GigabitEthernet1/0/2
 channel-group 2 mode passive
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        members_by_name = {i.name: i for i in intent.interfaces}
        assert members_by_name["GigabitEthernet1/0/1"].lag_member_of == "Port-channel2"
        assert members_by_name["GigabitEthernet1/0/2"].lag_member_of == "Port-channel2"

    def test_channel_group_mode_on_is_static(self):
        raw = """\
interface GigabitEthernet1/0/1
 channel-group 3 mode on
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        assert intent.lags[0].mode == "static"

    def test_channel_group_mode_passive_preserved(self):
        raw = """\
interface GigabitEthernet1/0/1
 channel-group 4 mode passive
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        assert intent.lags[0].mode == "passive"

    def test_lag_without_member_still_emitted(self):
        """Empty Port-channel stanza still produces a LAG record so the
        downstream capability matrix can report it."""
        raw = """\
interface Port-channel1
 description PREPARED-FOR-MEMBERS
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        assert len(intent.lags) == 1
        assert intent.lags[0].name == "Port-channel1"
        assert intent.lags[0].members == []

    def test_multiple_lags_sort_stable(self):
        raw = """\
interface GigabitEthernet1/0/1
 channel-group 3 mode active
!
interface GigabitEthernet1/0/2
 channel-group 1 mode active
!
interface GigabitEthernet1/0/3
 channel-group 2 mode active
!
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        assert [lag.name for lag in intent.lags] == [
            "Port-channel1", "Port-channel2", "Port-channel3",
        ]


# ---------------------------------------------------------------------------
# Aruba AOS-S
# ---------------------------------------------------------------------------


class TestArubaLAGRenderParse:
    def test_render_single_lag_as_trunk_line(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[
                CanonicalInterface(name="1"),
                CanonicalInterface(name="2"),
            ],
            lags=[CanonicalLAG(name="trk1", members=["1", "2"], mode="active")],
        )
        out = ArubaAOSSCodec().render(intent)
        assert "trunk 1-2 trk1 lacp" in out

    def test_non_native_lag_name_is_translated_to_trk(self):
        """Cisco-style Port-channel1 must become trk1 in Aruba output."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            lags=[CanonicalLAG(
                name="Port-channel3", members=["A1", "A2"], mode="active",
            )],
        )
        out = ArubaAOSSCodec().render(intent)
        assert "trk3" in out
        # The Cisco name must not leak through; it's not valid AOS-S.
        assert "Port-channel3" not in out.split("trunk", 1)[1].split("\n", 1)[0]

    def test_static_mode_emits_trunk_type(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            lags=[CanonicalLAG(name="trk1", members=["1", "2"], mode="static")],
        )
        out = ArubaAOSSCodec().render(intent)
        assert "trunk 1-2 trk1 trunk" in out

    def test_empty_lag_emits_comment_not_broken_trunk_line(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            lags=[CanonicalLAG(name="trk9", members=[], mode="active")],
        )
        out = ArubaAOSSCodec().render(intent)
        # No trunk line with empty port list.
        for line in out.splitlines():
            if line.strip().startswith("trunk "):
                parts = line.split()
                assert len(parts) >= 4, f"malformed trunk line: {line!r}"
        # But the info must not silently vanish.
        assert "trk9" in out

    def test_parse_trunk_line(self):
        raw = """\
; minimal
hostname "sw1"
trunk 1-4 trk1 lacp
"""
        intent = ArubaAOSSCodec().parse(raw)
        assert len(intent.lags) == 1
        lag = intent.lags[0]
        assert lag.name == "trk1"
        assert lag.members == ["1", "2", "3", "4"]
        assert lag.mode == "active"

    def test_round_trip_preserves_members_and_mode(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[
                CanonicalInterface(name="A1"),
                CanonicalInterface(name="A2"),
                CanonicalInterface(name="A3"),
            ],
            lags=[CanonicalLAG(name="trk2", members=["A1", "A2", "A3"], mode="active")],
        )
        out = ArubaAOSSCodec().render(intent)
        reparse = ArubaAOSSCodec().parse(out)
        assert len(reparse.lags) == 1
        assert reparse.lags[0].name == "trk2"
        assert reparse.lags[0].members == ["A1", "A2", "A3"]


# ---------------------------------------------------------------------------
# FortiGate
# ---------------------------------------------------------------------------


class TestFortiGateLAGParseRender:
    def test_aggregate_interface_becomes_lag(self):
        raw = """\
config system interface
    edit "port1"
        set status up
    next
    edit "port2"
        set status up
    next
    edit "lag1"
        set type aggregate
        set member "port1" "port2"
        set lacp-mode active
        set status up
    next
end
"""
        intent = FortiGateCLICodec().parse(raw)
        assert len(intent.lags) == 1
        lag = intent.lags[0]
        assert lag.name == "lag1"
        assert lag.members == ["port1", "port2"]
        assert lag.mode == "active"

    def test_members_stamped_with_lag_member_of(self):
        raw = """\
config system interface
    edit "port1"
        set status up
    next
    edit "lag1"
        set type aggregate
        set member "port1"
    next
end
"""
        intent = FortiGateCLICodec().parse(raw)
        port1 = next(i for i in intent.interfaces if i.name == "port1")
        assert port1.lag_member_of == "lag1"

    def test_render_emits_type_aggregate_and_member(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            lags=[CanonicalLAG(
                name="lag1", members=["port1", "port2"], mode="active"
            )],
        )
        out = FortiGateCLICodec().render(intent)
        assert "set type aggregate" in out
        assert 'set member "port1" "port2"' in out
        assert "set lacp-mode active" in out

    def test_round_trip(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[CanonicalInterface(name="port1"), CanonicalInterface(name="port2")],
            lags=[CanonicalLAG(name="lag1", members=["port1", "port2"], mode="active")],
        )
        out = FortiGateCLICodec().render(intent)
        reparse = FortiGateCLICodec().parse(out)
        assert len(reparse.lags) == 1
        assert reparse.lags[0].name == "lag1"
        assert reparse.lags[0].members == ["port1", "port2"]
        assert reparse.lags[0].mode == "active"


# ---------------------------------------------------------------------------
# MikroTik RouterOS
# ---------------------------------------------------------------------------


class TestMikroTikLAGParseRender:
    def test_bonding_section_becomes_lag(self):
        raw = """\
/interface bonding
add slaves=ether1,ether2 mode=802.3ad name=bond1
"""
        intent = MikroTikRouterOSCodec().parse(raw)
        assert len(intent.lags) == 1
        lag = intent.lags[0]
        assert lag.name == "bond1"
        assert lag.members == ["ether1", "ether2"]
        assert lag.mode == "active"

    def test_active_backup_is_static(self):
        raw = """\
/interface bonding
add slaves=ether1,ether2 mode=active-backup name=bond1
"""
        intent = MikroTikRouterOSCodec().parse(raw)
        assert intent.lags[0].mode == "static"

    def test_render_emits_bonding_section(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            lags=[CanonicalLAG(name="bond1", members=["ether1", "ether2"], mode="active")],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "/interface bonding" in out
        assert "mode=802.3ad" in out
        assert "slaves=ether1,ether2" in out
        assert "name=bond1" in out

    def test_round_trip(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[CanonicalInterface(name="ether1"), CanonicalInterface(name="ether2")],
            lags=[CanonicalLAG(name="bond1", members=["ether1", "ether2"], mode="active")],
        )
        out = MikroTikRouterOSCodec().render(intent)
        reparse = MikroTikRouterOSCodec().parse(out)
        assert len(reparse.lags) == 1
        assert reparse.lags[0].name == "bond1"
        assert reparse.lags[0].members == ["ether1", "ether2"]


# ---------------------------------------------------------------------------
# OPNsense
# ---------------------------------------------------------------------------


class TestOPNsenseLAGParseRender:
    def test_laggs_element_becomes_lag(self):
        raw = """\
<opnsense>
<system><hostname>fw1</hostname></system>
<laggs>
<lagg>
<laggif>lagg0</laggif>
<members>em0,em1</members>
<proto>lacp</proto>
</lagg>
</laggs>
</opnsense>
"""
        intent = OPNsenseCodec().parse(raw)
        assert len(intent.lags) == 1
        lag = intent.lags[0]
        assert lag.name == "lagg0"
        assert lag.members == ["em0", "em1"]
        assert lag.mode == "active"

    def test_proto_failover_is_static(self):
        raw = """\
<opnsense>
<laggs>
<lagg>
<laggif>lagg0</laggif>
<members>em0,em1</members>
<proto>failover</proto>
</lagg>
</laggs>
</opnsense>
"""
        intent = OPNsenseCodec().parse(raw)
        assert intent.lags[0].mode == "static"

    def test_render_emits_laggs_element(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            lags=[CanonicalLAG(name="lagg0", members=["em0", "em1"], mode="active")],
        )
        out = OPNsenseCodec().render(intent)
        assert "<laggs>" in out
        assert "<laggif>lagg0</laggif>" in out
        assert "<members>em0,em1</members>" in out
        assert "<proto>lacp</proto>" in out

    def test_round_trip(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            lags=[CanonicalLAG(name="lagg0", members=["em0", "em1"], mode="active")],
        )
        out = OPNsenseCodec().render(intent)
        reparse = OPNsenseCodec().parse(out)
        assert len(reparse.lags) == 1
        assert reparse.lags[0].name == "lagg0"
        assert reparse.lags[0].members == ["em0", "em1"]


# ---------------------------------------------------------------------------
# Cross-codec: Cisco -> Aruba (the real 9300 scenario)
# ---------------------------------------------------------------------------


class TestCiscoToArubaLAGFlow:
    """The end-to-end scenario that surfaced Bug 2 during dogfooding."""

    def test_cisco_lag_members_reach_aruba_trunk_line(self):
        raw = """\
hostname sw1
!
interface Port-channel1
 description UPLINK
 switchport mode trunk
!
interface GigabitEthernet1/0/1
 channel-group 1 mode active
!
interface GigabitEthernet1/0/2
 channel-group 1 mode active
!
end
"""
        intent = CiscoIOSXECLICodec().parse(raw)
        out = ArubaAOSSCodec().render(intent)

        # A trunk line must be emitted with both member names.
        trunk_lines = [
            line for line in out.splitlines()
            if line.lstrip().startswith("trunk ")
        ]
        assert len(trunk_lines) >= 1
        tl = trunk_lines[0]
        assert "GigabitEthernet1/0/1" in tl
        assert "GigabitEthernet1/0/2" in tl
        # AOS-S-style trunk name: trk<N>, translated from Port-channel1.
        assert "trk1" in tl
        # LACP default on active mode.
        assert "lacp" in tl.lower()
