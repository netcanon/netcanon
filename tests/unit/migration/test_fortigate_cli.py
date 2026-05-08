"""
Unit tests for ``FortiGateCLICodec`` — 5th real codec, Session D.

Covers the canonical contract (parse / render / round-trip / xpath /
capabilities / registry) plus FortiOS-specific quirks:

    * Recursive ``config/edit/set/next/end`` grammar
    * Nested ``config`` inside ``config`` (NTP ntpserver sub-table)
    * Quoted values with spaces (``set alias "WAN uplink"``)
    * Multi-token set values (``set allowaccess ping https ssh``)
    * ``set ip A.B.C.D M.M.M.M`` dotted-decimal form
    * VLAN interfaces via ``set type vlan`` + ``set vlanid``
    * Integer edit IDs (static routes) + quoted edit IDs (ifaces)
"""

from __future__ import annotations

from pathlib import Path

import pytest

import netcanon.migration  # noqa: F401

from netcanon.migration.codecs._mock import MockCodec
from netcanon.migration.codecs.base import ParseError, RenderError
from netcanon.migration.codecs.cisco_iosxe import CiscoIOSXECodec
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.fortigate_cli import FortiGateCLICodec
from netcanon.migration.codecs.fortigate_cli.codec import (
    _mask_to_prefix,
    _parse_blocks,
    _prefix_to_mask,
)
from netcanon.migration.codecs.opnsense import OPNsenseCodec
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalIPv4Address,
    CanonicalInterface,
    CanonicalStaticRoute,
)
from netcanon.models.migration import DeviceClass, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan

pytestmark = pytest.mark.unit


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "fortigate_cli"


_MIN = """\
#config-version=FGT60E-7.4
config system global
    set hostname "test-fgt"
end
config system interface
    edit "port1"
        set alias "WAN"
        set ip 10.0.0.2 255.255.255.252
        set status up
    next
end
"""


# ---------------------------------------------------------------------------
# R3 field declarations
# ---------------------------------------------------------------------------


class TestR3Fields:
    def test_direction(self):
        assert FortiGateCLICodec.direction == "bidirectional"

    def test_certainty(self):
        # Promoted from best_effort after a sanitised real capture from
        # a physical FortiGate 100E on FortiOS 7.2.13 (user-contributed)
        # landed the corpus at 3 fixtures across 2 major.minor OS
        # versions (7.2.13 + 7.6.6) and 2 device classes (FG100E
        # physical + FGT-70G + FGT-VM).  Real capture surfaced a real
        # round-trip bug (radius-port 0 parsed literally but renderer
        # omitted when 1812, causing drift); fix + regression test
        # (TestRoundTrip::test_radius_port_zero_canonicalised_to_default)
        # landed in the same commit.  See tests/fixtures/real/RESULTS.md.
        assert FortiGateCLICodec.certainty == "certified"

    def test_input_format(self):
        assert FortiGateCLICodec.input_format == "cli-fortigate"

    def test_vendor_id(self):
        assert FortiGateCLICodec().capabilities.vendor_id == "fortigate"

    def test_device_classes(self):
        classes = FortiGateCLICodec().capabilities.device_classes
        assert DeviceClass.firewall in classes
        assert DeviceClass.router in classes


# ---------------------------------------------------------------------------
# Grammar primitives
# ---------------------------------------------------------------------------


class TestBlockParser:
    def test_simple_config_end(self):
        raw = 'config system global\n    set hostname "fw"\nend\n'
        blocks = _parse_blocks(raw)
        assert len(blocks) == 1
        assert blocks[0].config_path == "system global"
        assert blocks[0].settings["hostname"] == ["fw"]

    def test_edit_next_inside_config(self):
        raw = (
            'config system interface\n'
            '    edit "port1"\n'
            '        set ip 10.0.0.1 255.255.255.0\n'
            '    next\n'
            'end\n'
        )
        blocks = _parse_blocks(raw)
        assert len(blocks[0].edits) == 1
        assert blocks[0].edits[0].edit_id == "port1"
        assert blocks[0].edits[0].settings["ip"] == ["10.0.0.1", "255.255.255.0"]

    def test_nested_config_inside_config(self):
        """config ntpserver inside config system ntp — parser must
        attach the inner block to the outer config's sub_blocks."""
        raw = (
            'config system ntp\n'
            '    set ntpsync enable\n'
            '    config ntpserver\n'
            '        edit 1\n'
            '            set server "pool.ntp.org"\n'
            '        next\n'
            '    end\n'
            'end\n'
        )
        blocks = _parse_blocks(raw)
        assert len(blocks) == 1
        outer = blocks[0]
        assert outer.config_path == "system ntp"
        assert len(outer.sub_blocks) == 1
        assert outer.sub_blocks[0].config_path == "ntpserver"
        assert outer.sub_blocks[0].edits[0].edit_id == "1"

    def test_quoted_value_with_spaces(self):
        raw = (
            'config system interface\n'
            '    edit "port1"\n'
            '        set alias "WAN uplink"\n'
            '    next\n'
            'end\n'
        )
        blocks = _parse_blocks(raw)
        assert blocks[0].edits[0].settings["alias"] == ["WAN uplink"]

    def test_multi_token_set(self):
        raw = (
            'config system interface\n'
            '    edit "port1"\n'
            '        set allowaccess ping https ssh\n'
            '    next\n'
            'end\n'
        )
        blocks = _parse_blocks(raw)
        assert blocks[0].edits[0].settings["allowaccess"] == ["ping", "https", "ssh"]

    def test_comment_lines_ignored(self):
        raw = '#config-version=something\n# banner\nconfig system global\nend\n'
        blocks = _parse_blocks(raw)
        assert len(blocks) == 1


class TestMaskHelpers:
    def test_mask_to_prefix_roundtrip(self):
        for prefix in (0, 8, 16, 24, 30, 32):
            mask = _prefix_to_mask(prefix)
            assert _mask_to_prefix(mask) == prefix

    def test_non_contiguous_mask_rejected(self):
        with pytest.raises(ParseError, match="non-contiguous"):
            _mask_to_prefix("255.0.255.0")

    def test_invalid_cidr_rejected(self):
        from netcanon.migration.codecs.base import RenderError
        with pytest.raises(RenderError):
            _prefix_to_mask(33)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


class TestParse:
    def test_hostname(self):
        tree = FortiGateCLICodec().parse(_MIN)
        assert tree.hostname == "test-fgt"

    def test_interface_with_ip(self):
        tree = FortiGateCLICodec().parse(_MIN)
        port1 = tree.interfaces[0]
        assert port1.name == "port1"
        assert port1.description == "WAN"
        assert port1.enabled is True
        assert port1.ipv4_addresses[0].ip == "10.0.0.2"
        assert port1.ipv4_addresses[0].prefix_length == 30

    def test_fixture_full_tree(self):
        raw = FIXTURES.joinpath("fortios_simple.conf").read_text()
        tree = FortiGateCLICodec().parse(raw)
        assert tree.hostname == "fgt-edge-01"
        assert tree.dns_servers == ["1.1.1.1", "8.8.8.8"]
        assert tree.ntp_servers == ["pool.ntp.org", "time.google.com"]

        # 4 interfaces (port1, port2, port3, port2.10)
        names = [i.name for i in tree.interfaces]
        assert names == ["port1", "port2", "port3", "port2.10"]

        # port3 is disabled (status down)
        port3 = next(i for i in tree.interfaces if i.name == "port3")
        assert port3.enabled is False

        # VLAN subinterface registered as both an interface AND a VLAN
        vlan_iface = next(i for i in tree.interfaces if i.name == "port2.10")
        assert vlan_iface.interface_type == "ianaift:l3ipvlan"
        assert vlan_iface.ipv4_addresses[0].ip == "192.168.11.1"
        assert len(tree.vlans) == 1
        assert tree.vlans[0].id == 10

        # Static routes with device field preserved
        default = next(r for r in tree.static_routes if r.destination == "0.0.0.0/0")
        assert default.gateway == "198.51.100.1"
        assert default.interface == "port1"

    def test_disabled_status_maps_to_enabled_false(self):
        raw = (
            'config system interface\n'
            '    edit "port1"\n'
            '        set status down\n'
            '    next\nend\n'
        )
        tree = FortiGateCLICodec().parse(raw)
        assert tree.interfaces[0].enabled is False


class TestParseErrors:
    def test_empty_input(self):
        with pytest.raises(ParseError, match="empty input"):
            FortiGateCLICodec().parse("")

    def test_xml_rejected(self):
        with pytest.raises(ParseError, match="looks like XML"):
            FortiGateCLICodec().parse("<?xml version='1.0'?>")

    def test_json_rejected(self):
        with pytest.raises(ParseError, match="looks like JSON"):
            FortiGateCLICodec().parse('{"key": "value"}')

    def test_bad_mask_raises(self):
        raw = (
            'config system interface\n'
            '    edit "p1"\n'
            '        set ip 10.0.0.1 255.0.255.0\n'
            '    next\nend\n'
        )
        with pytest.raises(ParseError, match="non-contiguous"):
            FortiGateCLICodec().parse(raw)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


class TestRender:
    def test_render_deterministic(self):
        tree = FortiGateCLICodec().parse(_MIN)
        a = FortiGateCLICodec().render(tree)
        b = FortiGateCLICodec().render(tree)
        assert a == b

    def test_render_rejects_non_canonical(self):
        with pytest.raises(RenderError, match="CanonicalIntent"):
            FortiGateCLICodec().render({"foo": "bar"})  # type: ignore[arg-type]

    def test_render_hostname(self):
        tree = CanonicalIntent(hostname="test")
        out = FortiGateCLICodec().render(tree)
        assert "config system global" in out
        assert 'set hostname "test"' in out
        assert "end" in out

    def test_render_ntp_subtable(self):
        tree = CanonicalIntent(ntp_servers=["a.ntp", "b.ntp"])
        out = FortiGateCLICodec().render(tree)
        assert "config system ntp" in out
        assert "    config ntpserver" in out
        assert 'set server "a.ntp"' in out
        assert 'set server "b.ntp"' in out

    def test_render_alias_truncated_to_25_chars(self):
        tree = CanonicalIntent(interfaces=[
            CanonicalInterface(
                name="port1",
                description="A very very very very long description",
            ),
        ])
        out = FortiGateCLICodec().render(tree)
        # alias length should be <= 25 chars.
        import re as _re
        m = _re.search(r'set alias "([^"]*)"', out)
        assert m
        assert len(m.group(1)) <= 25

    def test_render_static_route_uses_mask_form(self):
        tree = CanonicalIntent(static_routes=[
            CanonicalStaticRoute(
                destination="192.168.0.0/16",
                gateway="10.0.0.1",
                interface="port1",
            ),
        ])
        out = FortiGateCLICodec().render(tree)
        assert "set dst 192.168.0.0 255.255.0.0" in out
        assert "set gateway 10.0.0.1" in out
        assert 'set device "port1"' in out


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRealConfigVlanInference:
    """Real FortiOS configs often omit ``set type vlan`` on subinterfaces,
    relying on ``set vlanid`` + ``set interface <parent>`` to imply VLAN
    semantics.  Surfaced by KevinGuenay/fortinet-resources FGT-70G-BRANCH
    during real-capture validation."""

    def test_vlanid_plus_parent_without_type_recognised_as_vlan(self):
        raw = """\
config system interface
    edit "LAG_INTERNAL"
        set type aggregate
        set member "port1" "port2"
    next
    edit "VL_100"
        set alias "TEST100"
        set ip 192.168.100.1 255.255.255.0
        set interface "LAG_INTERNAL"
        set vlanid 100
    next
end
"""
        intent = FortiGateCLICodec().parse(raw)
        vl100 = next(i for i in intent.interfaces if i.name == "VL_100")
        assert vl100.interface_type == "ianaift:l3ipvlan"
        assert any(v.id == 100 for v in intent.vlans), (
            f"expected a CanonicalVlan with id=100, got {[v.id for v in intent.vlans]}"
        )

    def test_canonical_vlan_name_matches_iface_name(self):
        """For the render path to map iface -> vlan id without help,
        the CanonicalVlan.name must equal the iface name (not the
        alias).  Otherwise round-trip drops VLANs."""
        raw = """\
config system interface
    edit "VL_100"
        set alias "TEST100"
        set interface "port1"
        set vlanid 100
    next
end
"""
        intent = FortiGateCLICodec().parse(raw)
        vlan = next(v for v in intent.vlans if v.id == 100)
        assert vlan.name == "VL_100"

    def test_round_trip_stable_with_implicit_vlan(self):
        raw = """\
config system interface
    edit "port1"
        set status up
    next
    edit "VL_100"
        set alias "TEST100"
        set ip 192.168.100.1 255.255.255.0
        set interface "port1"
        set vlanid 100
    next
end
"""
        c = FortiGateCLICodec()
        first = c.parse(raw)
        second = c.parse(c.render(first))
        def norm(i):
            d = i.model_dump()
            for k in ('source_vendor','source_format','source_version'): d.pop(k,None)
            return d
        assert norm(first) == norm(second)


class TestRoundTrip:
    def test_roundtrip_minimal(self):
        codec = FortiGateCLICodec()
        tree = codec.parse(_MIN)
        tree2 = codec.parse(codec.render(tree))
        assert tree.hostname == tree2.hostname

    def test_roundtrip_fixture(self):
        codec = FortiGateCLICodec()
        raw = FIXTURES.joinpath("fortios_simple.conf").read_text()
        tree = codec.parse(raw)
        tree2 = codec.parse(codec.render(tree))
        assert tree.hostname == tree2.hostname
        assert tree.dns_servers == tree2.dns_servers
        assert tree.ntp_servers == tree2.ntp_servers
        # Interface names preserved.
        assert [i.name for i in tree.interfaces] == [
            i.name for i in tree2.interfaces
        ]
        # Static route dst + gateway preserved.
        for r1, r2 in zip(tree.static_routes, tree2.static_routes):
            assert r1.destination == r2.destination
            assert r1.gateway == r2.gateway

    def test_radius_port_zero_canonicalised_to_default(self):
        # Regression: real FortiOS captures (e.g. FG100E 7.2.13 export)
        # emit `set radius-port 0` under `config user radius` to mean
        # "use the default port 1812".  Our parser used to store 0
        # literally, then the renderer (which omits radius-port when
        # auth_port == 1812 to mirror FortiOS's default-omission idiom)
        # would not emit anything — so a parse → render → parse cycle
        # drifted from auth_port=0 to auth_port=1812.  Fix canonicalises
        # `radius-port 0` to 1812 at parse time; both passes now see
        # auth_port=1812, round-trip stable.
        raw = """config user radius
    edit "TestRadius"
        set server "10.1.1.1"
        set secret ENC fakePayloadAbcXyz==
        set radius-port 0
    next
end
"""
        codec = FortiGateCLICodec()
        tree = codec.parse(raw)
        assert len(tree.radius_servers) == 1
        assert tree.radius_servers[0].host == "10.1.1.1"
        assert tree.radius_servers[0].auth_port == 1812, (
            "radius-port 0 means 'use default 1812' in FortiOS; canonical "
            "should reflect the effective value, not the literal 0"
        )
        # Round-trip stable.
        tree2 = codec.parse(codec.render(tree))
        assert tree2.radius_servers[0].auth_port == 1812


# ---------------------------------------------------------------------------
# Capabilities + iter_xpaths
# ---------------------------------------------------------------------------


class TestCapabilities:
    def test_firewall_policy_unsupported(self):
        paths = [u.path for u in FortiGateCLICodec().capabilities.unsupported]
        assert "/filter/rule" in paths

    def test_alias_truncation_lossy(self):
        reasons = [l.reason for l in FortiGateCLICodec().capabilities.lossy]
        assert any("25 character" in r for r in reasons)


class TestIterXpaths:
    def test_xpaths_match_matrix(self):
        caps = FortiGateCLICodec().capabilities
        declared = (
            set(caps.supported)
            | {l.path for l in caps.lossy}
            | {u.path for u in caps.unsupported}
        )
        raw = FIXTURES.joinpath("fortios_simple.conf").read_text()
        tree = FortiGateCLICodec().parse(raw)
        for x in FortiGateCLICodec().iter_xpaths(tree):
            assert x in declared, f"undeclared: {x}"


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


class TestProbe:
    def test_config_version_banner(self):
        raw = '#config-version=FGT60E-7.4\nconfig system global\nend\n'
        hit = FortiGateCLICodec.probe(raw)
        assert hit is not None
        assert hit[0] >= 95

    def test_grammar_markers(self):
        raw = (
            'config system global\n'
            'end\n'
            'config system interface\n'
            '    edit "port1"\n'
            '    next\n'
            'end\n'
        )
        hit = FortiGateCLICodec.probe(raw)
        assert hit is not None
        assert hit[0] >= 75

    def test_ignores_xml(self):
        assert FortiGateCLICodec.probe("<data/>") is None

    def test_ignores_ios_cli(self):
        raw = "!\ninterface GigabitEthernet0/0/0\n ip address 10.0.0.1 255.255.255.0\n!\n"
        assert FortiGateCLICodec.probe(raw) is None


# ---------------------------------------------------------------------------
# Cross-adapter
# ---------------------------------------------------------------------------


class TestCrossAdapter:
    def test_fortigate_to_opnsense(self):
        raw = FIXTURES.joinpath("fortios_simple.conf").read_text()
        job = run_plan(FortiGateCLICodec(), OPNsenseCodec(), raw)
        assert job.status is MigrationJobStatus.completed
        assert "<hostname>fgt-edge-01</hostname>" in (job.rendered or "")

    def test_fortigate_to_iosxe_netconf(self):
        """FortiGate -> Cisco IOS-XE NETCONF.  The cisco_iosxe NETCONF
        codec is a Phase 0.5 stub whose render emits ONLY the
        openconfig-interfaces subtree; FortiGate sources carry
        hostname / VLANs / etc. that the target render drops.  Wave
        10γ-2 lifted those un-rendered surfaces from ``supported`` to
        ``unsupported`` in the matrix, so this run terminates as
        ``partial`` with a ``block`` validation severity.  The
        ``<interfaces>`` subtree is still emitted."""
        raw = FIXTURES.joinpath("fortios_simple.conf").read_text()
        job = run_plan(FortiGateCLICodec(), CiscoIOSXECodec(), raw)
        assert job.status is MigrationJobStatus.partial
        assert job.validation is not None
        assert job.validation.severity == "block"
        assert "<interfaces" in (job.rendered or "")

    def test_ios_cli_to_fortigate(self):
        ios_cli = (
            "hostname ios-to-fgt\n"
            "!\ninterface GigabitEthernet0/0/0\n"
            " description WAN\n"
            " ip address 10.0.0.2 255.255.255.252\n"
            " no shutdown\n!\n"
            "ip route 0.0.0.0 0.0.0.0 10.0.0.1\n"
            "!\nend\n"
        )
        job = run_plan(CiscoIOSXECLICodec(), FortiGateCLICodec(), ios_cli)
        assert job.status is MigrationJobStatus.completed
        assert 'set hostname "ios-to-fgt"' in (job.rendered or "")
        assert "config router static" in (job.rendered or "")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registered(self):
        from netcanon.migration.codecs.registry import list_codecs
        assert "fortigate_cli" in list_codecs()
