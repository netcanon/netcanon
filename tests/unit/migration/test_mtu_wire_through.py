"""
Unit tests for per-interface MTU wire-through.

Fidelity polish item: `CanonicalInterface.mtu` already existed on the
model but no codec populated or rendered it.  Real configs routinely
carry jumbo MTUs (9000, 9096, 1546) especially on carrier and
data-centre fixtures; without the wire-through, they were silently
dropped.

Vendors covered:
    * cisco_iosxe_cli  (parse)
    * opnsense          (parse + render)
    * mikrotik          (parse + render, /interface ethernet mtu=)
    * fortigate         (parse + render, emits `set mtu-override
                         enable` + `set mtu N`)
    * aruba_aoss        — NOT modelled; AOS-S has no per-port MTU
                         concept (only global jumbo), so silently
                         lossy on Aruba render (documented)
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalInterface,
    CanonicalIntent,
    CanonicalIPv4Address,
)
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec
from netconfig.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netconfig.migration.codecs.opnsense import OPNsenseCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Cisco IOS-XE CLI
# ---------------------------------------------------------------------------


class TestCiscoMTUParse:
    def test_simple_mtu(self):
        raw = "interface GigabitEthernet1/0/1\n mtu 9000\n!\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        assert intent.interfaces[0].mtu == 9000

    def test_mtu_absent_stays_none(self):
        raw = "interface GigabitEthernet1/0/1\n description X\n!\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        assert intent.interfaces[0].mtu is None

    def test_carrier_jumbo(self):
        """NTC's carrier-interfaces fixture has `mtu 9096` —
        regression guard that large values parse."""
        raw = "interface GigabitEthernet1/0/1\n mtu 9096\n!\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        assert intent.interfaces[0].mtu == 9096


# ---------------------------------------------------------------------------
# OPNsense
# ---------------------------------------------------------------------------


class TestOPNsenseMTUParseRender:
    def test_parse_mtu(self):
        raw = "<opnsense><interfaces><lan><enable/><mtu>1492</mtu></lan></interfaces></opnsense>"
        intent = OPNsenseCodec().parse(raw)
        assert intent.interfaces[0].mtu == 1492

    def test_render_emits_mtu(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[CanonicalInterface(
                name="lan",
                mtu=1492,
                ipv4_addresses=[CanonicalIPv4Address(
                    ip="10.0.0.1", prefix_length=24,
                )],
            )],
        )
        out = OPNsenseCodec().render(intent)
        assert "<mtu>1492</mtu>" in out

    def test_render_omits_when_none(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[CanonicalInterface(name="lan")],
        )
        out = OPNsenseCodec().render(intent)
        assert "<mtu>" not in out

    def test_round_trip(self):
        c = OPNsenseCodec()
        raw = "<opnsense><interfaces><lan><enable/><mtu>1492</mtu></lan></interfaces></opnsense>"
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.interfaces[0].mtu == second.interfaces[0].mtu == 1492


# ---------------------------------------------------------------------------
# MikroTik
# ---------------------------------------------------------------------------


class TestMikroTikMTUParseRender:
    def test_parse_ethernet_mtu(self):
        raw = "/interface ethernet\nset [ find default-name=ether1 ] mtu=9000\n"
        intent = MikroTikRouterOSCodec().parse(raw)
        assert intent.interfaces[0].mtu == 9000

    def test_render_emits_mtu(self):
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[CanonicalInterface(
                name="ether1",
                mtu=9000,
                interface_type="ianaift:ethernetCsmacd",
            )],
        )
        out = MikroTikRouterOSCodec().render(intent)
        assert "mtu=9000" in out

    def test_round_trip(self):
        c = MikroTikRouterOSCodec()
        raw = "/interface ethernet\nset [ find default-name=ether1 ] mtu=9000\n"
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.interfaces[0].mtu == second.interfaces[0].mtu == 9000


# ---------------------------------------------------------------------------
# FortiGate
# ---------------------------------------------------------------------------


class TestFortiGateMTUParseRender:
    def test_parse_mtu(self):
        raw = """\
config system interface
    edit "port1"
        set mtu 1500
    next
end
"""
        intent = FortiGateCLICodec().parse(raw)
        assert intent.interfaces[0].mtu == 1500

    def test_render_emits_mtu_override_and_mtu(self):
        """FortiOS requires ``set mtu-override enable`` before
        ``set mtu N`` takes effect on physical ports; render must
        emit both."""
        intent = CanonicalIntent(
            source_vendor="test", source_format="test",
            interfaces=[CanonicalInterface(name="port1", mtu=1500)],
        )
        out = FortiGateCLICodec().render(intent)
        assert "set mtu-override enable" in out
        assert "set mtu 1500" in out

    def test_round_trip(self):
        c = FortiGateCLICodec()
        raw = """\
config system interface
    edit "port1"
        set mtu 1500
    next
end
"""
        first = c.parse(raw)
        second = c.parse(c.render(first))
        assert first.interfaces[0].mtu == second.interfaces[0].mtu == 1500


# ---------------------------------------------------------------------------
# Cross-codec: MTU survives Cisco -> OPNsense
# ---------------------------------------------------------------------------


class TestCiscoToOPNsenseMTU:
    def test_cisco_mtu_reaches_opnsense_output(self):
        raw = "interface GigabitEthernet1/0/1\n mtu 9000\n!\n"
        intent = CiscoIOSXECLICodec().parse(raw)
        out = OPNsenseCodec().render(intent)
        assert "<mtu>9000</mtu>" in out
