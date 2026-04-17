"""
Unit tests for the ``CiscoIOSXECLICodec`` — R4 first CLI codec.

This is the codec that makes the translator work against real backup
data.  It parses ``show running-config`` text — the format the existing
Netmiko collectors already capture — into the same tree shape as the
NETCONF ``CiscoIOSXECodec``.

Direction: ``parse_only`` — render() raises RenderError.
Certainty: ``experimental`` — tested against synthetic samples here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netconfig.migration.codecs.base import ParseError, RenderError
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.cisco_iosxe import CiscoIOSXECodec
from netconfig.migration.codecs._mock import MockCodec
from netconfig.models.migration import DeviceClass, MigrationJobStatus
from netconfig.services.migration_pipeline import run_plan

pytestmark = pytest.mark.unit


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "iosxe"


_MINIMAL_CLI = """\
!
interface GigabitEthernet0/0/0
 description test link
 ip address 10.0.0.1 255.255.255.0
 no shutdown
!
end
"""


# ---------------------------------------------------------------------------
# R3 field declarations
# ---------------------------------------------------------------------------


class TestR3Fields:
    def test_direction_is_parse_only(self):
        assert CiscoIOSXECLICodec.direction == "parse_only"

    def test_certainty_is_experimental(self):
        assert CiscoIOSXECLICodec.certainty == "experimental"

    def test_canonical_model(self):
        assert CiscoIOSXECLICodec.canonical_model == "openconfig-lite"

    def test_input_format(self):
        assert CiscoIOSXECLICodec.input_format == "cli-ios"

    def test_vendor_id_matches_netconf_codec(self):
        """CLI and NETCONF codecs share the same vendor."""
        cli = CiscoIOSXECLICodec().capabilities.vendor_id
        net = CiscoIOSXECodec().capabilities.vendor_id
        assert cli == net == "cisco_iosxe"

    def test_device_classes_match_netconf_codec(self):
        cli = CiscoIOSXECLICodec().capabilities.device_classes
        net = CiscoIOSXECodec().capabilities.device_classes
        assert set(cli) == set(net)


# ---------------------------------------------------------------------------
# Parse — basic
# ---------------------------------------------------------------------------


class TestParseCLI:
    def test_minimal_cli(self):
        tree = CiscoIOSXECLICodec().parse(_MINIMAL_CLI)
        ifaces = tree.interfaces
        assert len(ifaces) == 1
        assert ifaces[0].name == "GigabitEthernet0/0/0"
        assert ifaces[0].description == "test link"
        assert ifaces[0].enabled is True

    def test_ip_address_parsed(self):
        tree = CiscoIOSXECLICodec().parse(_MINIMAL_CLI)
        addrs = tree.interfaces[0].ipv4_addresses
        assert addrs[0].ip == "10.0.0.1"
        assert addrs[0].prefix_length == 24

    def test_fixture_parses_four_interfaces(self):
        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        tree = CiscoIOSXECLICodec().parse(raw)
        ifaces = tree.interfaces
        assert len(ifaces) == 4
        names = [i.name for i in ifaces]
        assert names == [
            "GigabitEthernet0/0/0",
            "GigabitEthernet0/0/1",
            "Loopback0",
            "GigabitEthernet0/0/2",
        ]

    def test_shutdown_interface_has_enabled_false(self):
        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        tree = CiscoIOSXECLICodec().parse(raw)
        # GigabitEthernet0/0/2 has "shutdown"
        gi2 = tree.interfaces[3]
        assert gi2.name == "GigabitEthernet0/0/2"
        assert gi2.enabled is False

    def test_loopback_has_host_mask(self):
        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        tree = CiscoIOSXECLICodec().parse(raw)
        lo = tree.interfaces[2]
        assert lo.ipv4_addresses[0].prefix_length == 32

    def test_interface_type_inferred(self):
        tree = CiscoIOSXECLICodec().parse(_MINIMAL_CLI)
        assert tree.interfaces[0].interface_type == "ianaift:ethernetCsmacd"

    def test_loopback_type_inferred(self):
        raw = "interface Loopback99\n!\nend\n"
        tree = CiscoIOSXECLICodec().parse(raw)
        assert tree.interfaces[0].interface_type == "ianaift:softwareLoopback"


# ---------------------------------------------------------------------------
# SVI → VLAN synthesis (fix for Bug 1: silently-dropped SVI IPs)
# ---------------------------------------------------------------------------


class TestSVIVlanSynthesis:
    """`interface Vlan<N>` stanzas must produce both a
    :class:`CanonicalInterface` AND a :class:`CanonicalVlan` so VLAN-
    centric downstream codecs (Aruba AOS-S, OPNsense) don't silently
    drop the SVI's IP address.

    Regression fixture exercised: a real Cisco 9300 user config that
    rendered to Aruba with NO ``vlan`` stanzas when the bug was open.
    """

    def test_svi_with_ip_synthesises_vlan(self):
        raw = (
            "interface Vlan11\n"
            " ip address 192.168.11.252 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        assert len(tree.vlans) == 1
        vlan = tree.vlans[0]
        assert vlan.id == 11
        assert len(vlan.ipv4_addresses) == 1
        assert vlan.ipv4_addresses[0].ip == "192.168.11.252"
        assert vlan.ipv4_addresses[0].prefix_length == 24

    def test_svi_also_appears_as_interface(self):
        """The SVI interface record must also survive — it carries
        L3 interface metadata (MTU, description) the bare VLAN record
        doesn't model."""
        raw = (
            "interface Vlan11\n"
            " description Corp users\n"
            " ip address 192.168.11.252 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        names = [i.name for i in tree.interfaces]
        assert "Vlan11" in names

    def test_svi_no_ip_still_produces_vlan_record(self):
        """`interface Vlan1 / no ip address` asserts the VLAN exists
        even without L3 data.  The VLAN record must be preserved."""
        raw = (
            "interface Vlan1\n"
            " no ip address\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        ids = [v.id for v in tree.vlans]
        assert 1 in ids
        # No IPs attached.
        vlan = next(v for v in tree.vlans if v.id == 1)
        assert vlan.ipv4_addresses == []

    def test_svi_merges_with_top_level_vlan_stanza(self):
        """If both `vlan 11 / name Users` AND `interface Vlan11 /
        ip address ...` exist, the resulting VLAN record MUST keep
        the explicit name (it's the authoritative L2 tag) and gain
        the SVI's IP."""
        raw = (
            "vlan 11\n"
            " name Users\n"
            "!\n"
            "interface Vlan11\n"
            " ip address 192.168.11.252 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        vlan11 = next(v for v in tree.vlans if v.id == 11)
        assert vlan11.name == "Users"
        assert len(vlan11.ipv4_addresses) == 1
        assert vlan11.ipv4_addresses[0].ip == "192.168.11.252"

    def test_multiple_svis_all_synthesised(self):
        """User's reported regression: `interface Vlan1` + `interface
        Vlan11` both present.  Both must produce VLAN records."""
        raw = (
            "interface Vlan1\n"
            " no ip address\n"
            "!\n"
            "interface Vlan11\n"
            " ip address 192.168.11.252 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        ids = sorted(v.id for v in tree.vlans)
        assert ids == [1, 11]

    def test_svi_description_fills_name_when_no_stanza(self):
        """When no top-level `vlan N / name X` exists, the SVI's
        description is a reasonable fallback for the VLAN's name."""
        raw = (
            "interface Vlan11\n"
            " description Corporate users\n"
            " ip address 192.168.11.252 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        vlan = next(v for v in tree.vlans if v.id == 11)
        assert vlan.name == "Corporate users"

    def test_non_svi_interface_does_not_create_vlan(self):
        """Only interfaces whose name matches `Vlan<digits>` exactly
        should trigger synthesis.  GigabitEthernet0/0 must NOT create
        a phantom VLAN."""
        raw = (
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        assert tree.vlans == []

    def test_svi_ip_reaches_aruba_render(self):
        """End-to-end regression: the exact case from the user's
        real config."""
        from netconfig.migration.codecs.aruba_aoss import ArubaAOSSCodec
        raw = (
            'hostname "Switch"\n'
            "!\n"
            "interface Vlan1\n"
            " no ip address\n"
            "!\n"
            "interface Vlan11\n"
            " ip address 192.168.11.252 255.255.255.0\n"
            "!\n"
        )
        tree = CiscoIOSXECLICodec().parse(raw)
        rendered = ArubaAOSSCodec().render(tree)
        assert "vlan 11" in rendered
        assert "ip address 192.168.11.252/24" in rendered


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------


class TestParseCLIErrors:
    def test_empty_input_raises(self):
        with pytest.raises(ParseError, match="empty input"):
            CiscoIOSXECLICodec().parse("")

    def test_xml_input_rejected(self):
        with pytest.raises(ParseError, match="looks like XML"):
            CiscoIOSXECLICodec().parse('<?xml version="1.0"?><data/>')

    def test_json_input_rejected(self):
        with pytest.raises(ParseError, match="looks like XML or JSON"):
            CiscoIOSXECLICodec().parse('{"key": "value"}')

    def test_non_contiguous_mask_rejected(self):
        raw = "interface Gi0/0\n ip address 1.1.1.1 255.0.255.0\n!\n"
        with pytest.raises(ParseError, match="non-contiguous"):
            CiscoIOSXECLICodec().parse(raw)


# ---------------------------------------------------------------------------
# Render — must raise (parse_only)
# ---------------------------------------------------------------------------


class TestRenderRaises:
    def test_render_raises_render_error(self):
        with pytest.raises(RenderError, match="parse-only"):
            CiscoIOSXECLICodec().render({})


# ---------------------------------------------------------------------------
# Tree shape compatibility with the NETCONF codec
# ---------------------------------------------------------------------------


class TestTreeShapeCompatibility:
    """The CLI codec's tree must be identical in shape to the NETCONF
    codec's tree — that's what makes them interchangeable as sources."""

    def test_cli_tree_validates_against_netconf_caps(self):
        """Parse CLI → validate against the NETCONF codec's capability
        matrix.  Every supported xpath should be recognized."""
        from netconfig.services.migration_validate import validate_against

        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        cli_codec = CiscoIOSXECLICodec()
        net_codec = CiscoIOSXECodec()
        tree = cli_codec.parse(raw)
        report = validate_against(tree, net_codec, source=cli_codec)
        assert report.severity in ("ok", "warn")
        # Every parsed path should be in the supported bucket
        # (except the lossy 'type' field which is inferred, not from NETCONF).
        assert len(report.supported_paths) >= 4


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


class TestPipelineWithCLICodec:
    def test_cli_to_netconf_plan_succeeds(self):
        """CLI (source, parse_only) → NETCONF (target, bidirectional):
        the translate pipeline should complete because source.parse works
        and target.render works (they share the same tree shape)."""
        raw = FIXTURES.joinpath("show_run_simple.txt").read_text()
        cli = CiscoIOSXECLICodec()
        net = CiscoIOSXECodec()
        job = run_plan(cli, net, raw)
        assert job.status is MigrationJobStatus.completed
        assert job.rendered is not None
        # Rendered output is OpenConfig XML (from the NETCONF renderer).
        assert "<interfaces" in job.rendered
        assert "GigabitEthernet0/0/0" in job.rendered

    def test_cli_as_target_fails_with_render_error(self):
        """Using a parse_only codec as TARGET must produce a failed job
        with a clear render error."""
        raw = '{"key": "val"}'  # mock codec format
        job = run_plan(MockCodec(), CiscoIOSXECLICodec(), raw)
        assert job.status is MigrationJobStatus.failed
        assert "parse-only" in (job.error or "").lower()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_cli_codec_in_registry(self):
        from netconfig.migration.codecs.registry import list_codecs
        import netconfig.migration  # side-effect
        assert "cisco_iosxe_cli" in list_codecs()

    def test_two_codecs_for_same_vendor(self):
        """cisco_iosxe and cisco_iosxe_cli both registered — first
        multi-codec-per-vendor case."""
        from netconfig.migration.codecs.registry import list_codecs
        codecs = list_codecs()
        assert "cisco_iosxe" in codecs
        assert "cisco_iosxe_cli" in codecs
