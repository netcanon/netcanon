"""
Tier 2 — SNMP parse/render across every real codec.

SNMP is the first Tier 2 feature wired end-to-end through every real
codec.  Serves as the template for subsequent Tier 2 additions
(local_users, LAGs, RADIUS, DHCP server).

Each codec's SNMP surface is slightly different but the canonical
model is universal (community + location + contact + trap_hosts), so
the tests live here as a single suite rather than scattered across
the per-codec files.
"""

from __future__ import annotations

import pytest

import netconfig.migration  # noqa: F401

from netconfig.migration.codecs.aruba_aoss import ArubaAOSSCodec
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec
from netconfig.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netconfig.migration.codecs.opnsense import OPNsenseCodec
from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalSNMP,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Parse — per codec
# ---------------------------------------------------------------------------


class TestCiscoIOSXECLISNMP:
    def test_parse_community(self):
        raw = (
            "hostname r1\n"
            "!\n"
            "snmp-server community mysecret RO\n"
            "!\nend\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        assert tree.snmp is not None
        assert tree.snmp.community == "mysecret"

    def test_parse_location_and_contact(self):
        raw = (
            'snmp-server location "Data Center A"\n'
            'snmp-server contact admin@example.com\n'
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        assert tree.snmp is not None
        assert tree.snmp.location == "Data Center A"
        assert tree.snmp.contact == "admin@example.com"

    def test_parse_trap_hosts(self):
        raw = (
            "snmp-server host 10.0.0.1 version 2c public\n"
            "snmp-server host 10.0.0.2 version 2c public\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        assert tree.snmp is not None
        assert tree.snmp.trap_hosts == ["10.0.0.1", "10.0.0.2"]

    def test_parse_no_snmp_leaves_none(self):
        tree = CiscoIOSXECLICodec().parse("hostname r1\n!\nend\n")
        assert tree.snmp is None


class TestOPNsenseSNMP:
    def test_parse_snmpd_block(self):
        xml = (
            '<?xml version="1.0"?>\n'
            '<opnsense>\n'
            '  <system><hostname>fw01</hostname></system>\n'
            '  <snmpd>\n'
            '    <rocommunity>public</rocommunity>\n'
            '    <syslocation>DC A</syslocation>\n'
            '    <syscontact>admin</syscontact>\n'
            '    <traphost>10.0.0.1</traphost>\n'
            '  </snmpd>\n'
            '</opnsense>\n'
        )
        tree = OPNsenseCodec().parse(xml)
        assert tree.snmp is not None
        assert tree.snmp.community == "public"
        assert tree.snmp.location == "DC A"
        assert tree.snmp.contact == "admin"
        assert tree.snmp.trap_hosts == ["10.0.0.1"]

    def test_render_produces_snmpd_element(self):
        intent = CanonicalIntent(
            hostname="fw01",
            snmp=CanonicalSNMP(
                community="public",
                location="DC A",
                contact="admin",
                trap_hosts=["10.0.0.1"],
            ),
        )
        out = OPNsenseCodec().render(intent)
        assert "<snmpd>" in out
        assert "<rocommunity>public</rocommunity>" in out
        assert "<syslocation>DC A</syslocation>" in out
        assert "<syscontact>admin</syscontact>" in out
        assert "<traphost>10.0.0.1</traphost>" in out

    def test_opnsense_snmp_roundtrip(self):
        intent = CanonicalIntent(
            hostname="fw01",
            snmp=CanonicalSNMP(
                community="pub", location="DC A", contact="admin",
                trap_hosts=["10.0.0.1"],
            ),
        )
        codec = OPNsenseCodec()
        rendered = codec.render(intent)
        back = codec.parse(rendered)
        assert back.snmp is not None
        assert back.snmp.community == "pub"
        assert back.snmp.location == "DC A"
        assert back.snmp.contact == "admin"
        assert back.snmp.trap_hosts == ["10.0.0.1"]


class TestMikroTikSNMP:
    def test_parse_snmp_root(self):
        raw = (
            '/snmp\nset enabled=yes contact="admin" location="DC A" '
            'trap-target=10.0.0.1,10.0.0.2\n'
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.snmp is not None
        assert tree.snmp.contact == "admin"
        assert tree.snmp.location == "DC A"
        assert tree.snmp.trap_hosts == ["10.0.0.1", "10.0.0.2"]

    def test_parse_community(self):
        raw = (
            '/snmp community\nset [ find default=yes ] name=mycomm\n'
        )
        tree = MikroTikRouterOSCodec().parse(raw)
        assert tree.snmp is not None
        assert tree.snmp.community == "mycomm"

    def test_roundtrip(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(
                community="pub", location="DC A", contact="admin",
                trap_hosts=["10.0.0.1"],
            ),
        )
        codec = MikroTikRouterOSCodec()
        back = codec.parse(codec.render(intent))
        assert back.snmp is not None
        assert back.snmp.community == "pub"
        assert back.snmp.location == "DC A"
        assert back.snmp.contact == "admin"
        assert back.snmp.trap_hosts == ["10.0.0.1"]


class TestArubaAOSSSNMP:
    def test_parse_community_location_contact_host(self):
        raw = (
            'snmp-server community "public" Operator\n'
            'snmp-server location "DC A"\n'
            'snmp-server contact "admin"\n'
            'snmp-server host 10.0.0.1 community "public"\n'
        )
        tree = ArubaAOSSCodec().parse(raw)
        assert tree.snmp is not None
        assert tree.snmp.community == "public"
        assert tree.snmp.location == "DC A"
        assert tree.snmp.contact == "admin"
        assert "10.0.0.1" in tree.snmp.trap_hosts

    def test_render_emits_aos_s_syntax(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(
                community="pub", location="DC A", contact="admin",
                trap_hosts=["10.0.0.1"],
            ),
        )
        out = ArubaAOSSCodec().render(intent)
        assert 'snmp-server community "pub"' in out
        assert 'snmp-server location "DC A"' in out
        assert 'snmp-server contact "admin"' in out
        assert 'snmp-server host 10.0.0.1 community "pub"' in out

    def test_roundtrip(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(
                community="pub", location="DC A", contact="admin",
                trap_hosts=["10.0.0.1"],
            ),
        )
        codec = ArubaAOSSCodec()
        back = codec.parse(codec.render(intent))
        assert back.snmp is not None
        assert back.snmp.community == "pub"
        assert back.snmp.location == "DC A"
        assert back.snmp.contact == "admin"


class TestFortiGateSNMP:
    def test_parse_sysinfo_and_community(self):
        raw = (
            'config system snmp sysinfo\n'
            '    set status enable\n'
            '    set location "DC A"\n'
            '    set contact-info "admin"\n'
            'end\n'
            'config system snmp community\n'
            '    edit 1\n'
            '        set name "public"\n'
            '        config hosts\n'
            '            edit 1\n'
            '                set ip "10.0.0.1 255.255.255.255"\n'
            '            next\n'
            '        end\n'
            '    next\n'
            'end\n'
        )
        tree = FortiGateCLICodec().parse(raw)
        assert tree.snmp is not None
        assert tree.snmp.community == "public"
        assert tree.snmp.location == "DC A"
        assert tree.snmp.contact == "admin"
        assert "10.0.0.1" in tree.snmp.trap_hosts

    def test_render_emits_fortios_blocks(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(
                community="pub", location="DC A", contact="admin",
                trap_hosts=["10.0.0.1"],
            ),
        )
        out = FortiGateCLICodec().render(intent)
        assert "config system snmp sysinfo" in out
        assert '    set location "DC A"' in out
        assert '    set contact-info "admin"' in out
        assert "config system snmp community" in out
        assert '        set name "pub"' in out
        assert "        config hosts" in out

    def test_roundtrip(self):
        intent = CanonicalIntent(
            snmp=CanonicalSNMP(
                community="pub", location="DC A", contact="admin",
                trap_hosts=["10.0.0.1"],
            ),
        )
        codec = FortiGateCLICodec()
        back = codec.parse(codec.render(intent))
        assert back.snmp is not None
        assert back.snmp.community == "pub"
        assert back.snmp.location == "DC A"
        assert back.snmp.contact == "admin"
        assert back.snmp.trap_hosts == ["10.0.0.1"]


# ---------------------------------------------------------------------------
# Cross-vendor SNMP translation
# ---------------------------------------------------------------------------


_CANONICAL_SNMP_TREE = CanonicalIntent(
    hostname="snmp-test",
    snmp=CanonicalSNMP(
        community="sharedsecret",
        location="Rack 42",
        contact="netops@example.com",
        trap_hosts=["10.0.0.1", "10.0.0.2"],
    ),
)


@pytest.mark.parametrize("codec_cls", [
    OPNsenseCodec,
    MikroTikRouterOSCodec,
    ArubaAOSSCodec,
    FortiGateCLICodec,
])
def test_snmp_universal_render_does_not_crash(codec_cls):
    """Every real render()-capable codec must handle an SNMP-populated
    CanonicalIntent without raising or producing empty output."""
    out = codec_cls().render(_CANONICAL_SNMP_TREE)
    assert out
    # Each codec's rendered output must carry the community string
    # (the most distinctive SNMP token).
    assert "sharedsecret" in out


@pytest.mark.parametrize("codec_cls", [
    OPNsenseCodec,
    MikroTikRouterOSCodec,
    ArubaAOSSCodec,
    FortiGateCLICodec,
])
def test_snmp_lossless_roundtrip_per_codec(codec_cls):
    """Each bidirectional codec round-trips SNMP through its own render→parse."""
    codec = codec_cls()
    rendered = codec.render(_CANONICAL_SNMP_TREE)
    back = codec.parse(rendered)
    assert back.snmp is not None, f"{codec_cls.__name__} lost SNMP block"
    assert back.snmp.community == "sharedsecret"
    assert back.snmp.location == "Rack 42"
    assert back.snmp.contact == "netops@example.com"
