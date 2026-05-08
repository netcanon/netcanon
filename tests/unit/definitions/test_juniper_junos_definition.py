"""
Unit tests for the shipped Juniper Junos 22.x device definition.

These tests load ``definitions/juniper/junos/22.x.yaml`` from the real
repository tree (not a tmp fixture) and assert the schema-validated
shape plus the probe regex behaviour against canned ``show version``
output captured from real Junos SRX / EX / QFX / MX devices.

The codec pairing lives at ``netcanon/migration/codecs/juniper_junos``;
this definition is what the backup pipeline uses to *fetch* the
``set``-form running configuration whose translation that codec
performs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from netcanon.collectors.probe import parse_probe_output
from netcanon.definitions.schema import DeviceDefinition

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parents[3]
JUNOS_DEF_PATH = REPO_ROOT / "definitions" / "juniper" / "junos" / "22.x.yaml"


# ---------------------------------------------------------------------------
# Canonical Junos `show version` outputs
# ---------------------------------------------------------------------------
#
# Three chassis families have slightly different headers but the
# ``Hostname: / Model: / Junos:`` triple is consistent across them.
# These are the lines our probe regexes anchor on — reproduce a
# representative sample of each chassis to lock the regex behaviour.

_SHOW_VERSION_SRX = """\
Hostname: srx-edge-01
Model: srx340
Junos: 22.4R3-S2.5
JUNOS Software Release [22.4R3-S2.5]
"""

_SHOW_VERSION_EX = """\
Hostname: ex-access-12
Model: ex4300-48t
Junos: 22.2R1.9
JUNOS EX  Software Suite [22.2R1.9]
JUNOS Online Documentation [22.2R1.9]
JUNOS Crypto Software Suite [22.2R1.9]
"""

_SHOW_VERSION_MX = """\
Hostname: mx-pe-01
Model: mx204
Junos: 22.4R2.6
JUNOS OS Kernel 64-bit  [20221012.36ee5e7_builder_stable_12]
JUNOS Routing Software Suite [22.4R2.6]
JUNOS Crypto Software Suite [22.4R2.6]
"""

_SHOW_VERSION_QFX = """\
Hostname: qfx-leaf-01
Model: qfx5100-48s-6q
Junos: 22.1R1.11
JUNOS Software Release [22.1R1.11]
"""


# ---------------------------------------------------------------------------
# Schema shape
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def junos_definition() -> DeviceDefinition:
    """Load and schema-validate the shipped 22.x.yaml."""
    raw = yaml.safe_load(JUNOS_DEF_PATH.read_text(encoding="utf-8"))
    return DeviceDefinition.model_validate(raw)


class TestJunosDefinitionShape:
    def test_file_exists(self):
        assert JUNOS_DEF_PATH.is_file(), (
            f"Juniper Junos definition missing at {JUNOS_DEF_PATH}"
        )

    def test_validates_against_schema(self, junos_definition):
        # Module fixture already validates; this is the explicit lock.
        assert isinstance(junos_definition, DeviceDefinition)

    def test_vendor(self, junos_definition):
        assert junos_definition.vendor.lower() == "juniper"

    def test_os(self, junos_definition):
        assert junos_definition.os.lower() == "junos"

    def test_type_key(self, junos_definition):
        # The route lookup is case-sensitive; lock the exact key so
        # downstream device-list templates and tests can rely on it.
        assert junos_definition.type_key == "Juniper"

    def test_priority_set(self, junos_definition):
        # Family base priority — match the other shipped definitions.
        assert junos_definition.priority == 10

    def test_file_extension_cfg(self, junos_definition):
        assert junos_definition.file_extension == "cfg"

    def test_collector_is_netmiko(self, junos_definition):
        assert junos_definition.collector.strategy == "netmiko"

    def test_netmiko_device_type_is_juniper_junos(self, junos_definition):
        # ``juniper_junos`` is Netmiko's canonical device-type for Junos
        # devices — handles operational-mode landing + ``| no-more``
        # paging suppression.  Must match what the codec round-trips.
        assert junos_definition.collector.netmiko_device_type == "juniper_junos"

    def test_config_command_uses_display_set(self, junos_definition):
        # ``| display set`` is the load-bearing modifier — it converts
        # Junos' hierarchical config to flat ``set`` statements, which
        # is the canonical paste form the juniper_junos codec parses.
        # ``| no-more`` disables the operational-mode pager so the
        # whole config streams without space-injection.
        assert (
            junos_definition.commands.config
            == "show configuration | display set | no-more"
        )

    def test_no_pre_or_post_commands(self, junos_definition):
        # ``| no-more`` on the config command itself handles paging —
        # no separate pre/post sequence is required.
        assert junos_definition.commands.pre == []
        assert junos_definition.commands.post == []

    def test_paging_does_not_use_cisco_more_paging(self, junos_definition):
        # CLAUDE.md hard rule: never ``terminal length 0``.  Junos uses
        # ``| no-more`` instead — neither space-injection nor the Cisco
        # paging dance applies.
        assert junos_definition.connection.cisco_more_paging is False

    def test_does_not_need_enable(self, junos_definition):
        # Junos has no privileged-exec equivalent — operational-mode
        # is the default landing prompt and is sufficient for backup.
        assert junos_definition.connection.needs_enable is False

    def test_probe_command_set(self, junos_definition):
        assert junos_definition.probe.command == "show version"

    def test_probe_has_patterns(self, junos_definition):
        assert junos_definition.probe.patterns
        assert "detected_os_version" in junos_definition.probe.patterns
        assert "detected_model" in junos_definition.probe.patterns


# ---------------------------------------------------------------------------
# Probe regex behaviour against canned `show version` outputs
# ---------------------------------------------------------------------------


class TestJunosProbeAgainstCannedOutput:
    def test_extracts_os_version_srx(self, junos_definition):
        facts = parse_probe_output(_SHOW_VERSION_SRX, junos_definition.probe)
        # major.minor only — overlay pins are "22.4", not "22.4R3-S2.5"
        assert facts["detected_os_version"] == "22.4"

    def test_extracts_model_srx(self, junos_definition):
        facts = parse_probe_output(_SHOW_VERSION_SRX, junos_definition.probe)
        assert facts["detected_model"] == "srx340"

    def test_extracts_hostname_srx(self, junos_definition):
        facts = parse_probe_output(_SHOW_VERSION_SRX, junos_definition.probe)
        assert facts["detected_hostname"] == "srx-edge-01"

    def test_extracts_os_version_ex(self, junos_definition):
        facts = parse_probe_output(_SHOW_VERSION_EX, junos_definition.probe)
        assert facts["detected_os_version"] == "22.2"

    def test_extracts_model_ex(self, junos_definition):
        facts = parse_probe_output(_SHOW_VERSION_EX, junos_definition.probe)
        assert facts["detected_model"] == "ex4300-48t"

    def test_extracts_os_version_mx(self, junos_definition):
        facts = parse_probe_output(_SHOW_VERSION_MX, junos_definition.probe)
        assert facts["detected_os_version"] == "22.4"

    def test_extracts_model_mx(self, junos_definition):
        facts = parse_probe_output(_SHOW_VERSION_MX, junos_definition.probe)
        assert facts["detected_model"] == "mx204"

    def test_extracts_os_version_qfx(self, junos_definition):
        facts = parse_probe_output(_SHOW_VERSION_QFX, junos_definition.probe)
        assert facts["detected_os_version"] == "22.1"

    def test_extracts_model_qfx(self, junos_definition):
        facts = parse_probe_output(_SHOW_VERSION_QFX, junos_definition.probe)
        assert facts["detected_model"] == "qfx5100-48s-6q"

    def test_no_trailing_whitespace_in_values(self, junos_definition):
        # Probe parser strips, but anchor the regex behaviour explicitly.
        padded = _SHOW_VERSION_SRX.replace("Junos: 22.4R3-S2.5", "Junos: 22.4R3-S2.5   ")
        facts = parse_probe_output(padded, junos_definition.probe)
        assert facts["detected_os_version"] == "22.4"

    def test_kernel_version_does_not_false_match_os_version(
        self, junos_definition
    ):
        # The MX output contains a "Kernel 64-bit  [20221012...]" line.
        # The detected_os_version regex anchors on ``^Junos:`` so we
        # must capture 22.4 (from "Junos: 22.4R2.6") not 64.0 etc.
        facts = parse_probe_output(_SHOW_VERSION_MX, junos_definition.probe)
        assert facts["detected_os_version"] == "22.4"


# ---------------------------------------------------------------------------
# Codec pairing — captured set-form output round-trips through parse_intent
# ---------------------------------------------------------------------------


class TestJunosDefinitionCodecPairing:
    """The backup pipeline writes raw bytes; the migration codec then parses.

    These tests assert the contract: a representative ``show configuration |
    display set | no-more`` capture (the exact command the definition runs)
    parses cleanly through the juniper_junos codec's ``parse_intent`` —
    proving the definition's command choice produces the wire form the
    codec actually consumes.
    """

    @pytest.fixture
    def display_set_output(self) -> str:
        # Minimal but representative ``| display set`` capture — covers
        # system, interfaces, vlans, routing-options, and protocols
        # families that the codec dispatches on.
        return (
            "set version 22.4R3-S2.5\n"
            "set system host-name junos-test-01\n"
            "set system domain-name example.com\n"
            "set system name-server 8.8.8.8\n"
            "set interfaces ge-0/0/0 description \"uplink to core\"\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24\n"
            "set interfaces lo0 unit 0 family inet address 10.255.0.1/32\n"
            "set vlans v100 vlan-id 100\n"
            "set routing-options static route 0.0.0.0/0 next-hop 10.0.0.254\n"
            "set snmp community public authorization read-only\n"
            "set snmp location \"rack-7\"\n"
        )

    def test_set_form_capture_parses(self, display_set_output):
        from netcanon.migration.codecs.juniper_junos import JunosCodec

        codec = JunosCodec()
        intent = codec.parse(display_set_output)
        # Sanity-check the intent has at least the host-name + interface
        # so we know dispatch ran end-to-end.
        assert intent.hostname == "junos-test-01"
        # ge-0/0/0 should land in the interface table.
        assert any(iface.name == "ge-0/0/0" for iface in intent.interfaces)


# ---------------------------------------------------------------------------
# Loader integration — definition loads cleanly via DefinitionLoader
# ---------------------------------------------------------------------------


class TestJunosDefinitionLoaderIntegration:
    def test_loader_picks_up_juniper_family_base(self, tmp_path):
        """When pointed at a tree containing the Junos YAML, the loader
        returns it under its declared type_key."""
        from netcanon.definitions.loader import DefinitionLoader

        defs = tmp_path / "definitions"
        (defs / "juniper" / "junos").mkdir(parents=True)
        (defs / "juniper" / "junos" / "22.x.yaml").write_text(
            JUNOS_DEF_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )

        loader = DefinitionLoader(defs)
        loaded = loader.load_all()

        assert "Juniper" in loaded
        d = loaded["Juniper"]
        assert d.vendor.lower() == "juniper"
        assert d.collector.netmiko_device_type == "juniper_junos"
        # And the load-bearing config-command shape — without
        # ``| display set`` the codec parser sees block-form and has
        # to do extra conversion work.
        assert "| display set" in d.commands.config
        assert "| no-more" in d.commands.config
