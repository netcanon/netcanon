"""
Unit tests for the shipped Aruba AOS-S 16.x device definition.

These tests load ``definitions/aruba/aos-s/16.x.yaml`` from the real
repository tree (not a tmp fixture) and assert the schema-validated
shape plus the probe regex behaviour against canned ``show system``
output captured from real Aruba 2530/2930F switches.

The codec pairing lives at ``netcanon/migration/codecs/aruba_aoss``;
this definition is what the backup pipeline uses to *fetch* the
``running-config`` whose translation that codec performs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from netcanon.collectors.probe import parse_probe_output
from netcanon.definitions.schema import DeviceDefinition

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parents[2]
ARUBA_DEF_PATH = REPO_ROOT / "definitions" / "aruba" / "aos-s" / "16.x.yaml"


# Canonical AOS-S "show system" output.  The colon-aligned key/value
# layout is identical across the 2530 / 2930F / 5400R families — only
# the Hardware string differs by chassis.
_SHOW_SYSTEM_2930F = """\
 Status and Counters - General System Information

  System Name        : SwitchA
  System Contact     :
  System Location    :

  MAC Age Time (sec) : 300

  Time Zone          : 0
  Daylight Time Rule : None

  Software revision  : WC.16.10.0023
  Base MAC Addr      : 1c98ec-aabbcc
  Serial Number      : SG90BLR1KT
  Hardware           : J9776A 2530-24G-PoEP
"""

_SHOW_SYSTEM_2530 = """\
 Status and Counters - General System Information

  System Name        : LabSwitch
  System Contact     :
  System Location    :

  Software revision  : YA.16.11.0007
  Base MAC Addr      : 9457a5-112233
  Serial Number      : CN12ABCD34
  Hardware           : J9772A 2530-48G-PoEP
"""


# ---------------------------------------------------------------------------
# Schema shape
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def aruba_definition() -> DeviceDefinition:
    """Load and schema-validate the shipped 16.x.yaml."""
    raw = yaml.safe_load(ARUBA_DEF_PATH.read_text(encoding="utf-8"))
    return DeviceDefinition.model_validate(raw)


class TestArubaDefinitionShape:
    def test_file_exists(self):
        assert ARUBA_DEF_PATH.is_file(), (
            f"Aruba AOS-S definition missing at {ARUBA_DEF_PATH}"
        )

    def test_validates_against_schema(self, aruba_definition):
        # Module fixture already validates; this is the explicit lock.
        assert isinstance(aruba_definition, DeviceDefinition)

    def test_vendor(self, aruba_definition):
        assert aruba_definition.vendor.lower() == "aruba"

    def test_os(self, aruba_definition):
        assert aruba_definition.os.lower() == "aos-s"

    def test_type_key(self, aruba_definition):
        # The route lookup is case-sensitive; lock the exact key so
        # downstream device-list templates and tests can rely on it.
        assert aruba_definition.type_key == "Aruba"

    def test_priority_set(self, aruba_definition):
        # Family base priority — match the other shipped definitions.
        assert aruba_definition.priority == 10

    def test_file_extension_cfg(self, aruba_definition):
        assert aruba_definition.file_extension == "cfg"

    def test_collector_is_netmiko(self, aruba_definition):
        assert aruba_definition.collector.strategy == "netmiko"

    def test_netmiko_device_type_is_aruba_osswitch(self, aruba_definition):
        # aruba_osswitch is the modern AOS-S 16.x driver; hp_procurve
        # exists for legacy firmware but aruba_osswitch handles 16.x
        # paging + manager-mode escalation cleanly.
        assert aruba_definition.collector.netmiko_device_type == "aruba_osswitch"

    def test_config_command(self, aruba_definition):
        assert aruba_definition.commands.config == "show running-config"

    def test_no_pre_or_post_commands(self, aruba_definition):
        # Netmiko's aruba_osswitch driver handles paging internally
        # via space-injection — no pre/post needed.
        assert aruba_definition.commands.pre == []
        assert aruba_definition.commands.post == []

    def test_paging_uses_space_injection(self, aruba_definition):
        # CLAUDE.md hard rule: never `terminal length 0`.  AOS-S also
        # responds to space-injection; the driver does it for us when
        # this flag is set.
        assert aruba_definition.connection.cisco_more_paging is True

    def test_probe_command_set(self, aruba_definition):
        assert aruba_definition.probe.command == "show system"

    def test_probe_has_patterns(self, aruba_definition):
        assert aruba_definition.probe.patterns
        assert "detected_os_version" in aruba_definition.probe.patterns
        assert "detected_model" in aruba_definition.probe.patterns


# ---------------------------------------------------------------------------
# Probe regex behaviour against canned `show system` outputs
# ---------------------------------------------------------------------------


class TestArubaProbeAgainstCannedOutput:
    def test_extracts_software_revision_2930f(self, aruba_definition):
        facts = parse_probe_output(_SHOW_SYSTEM_2930F, aruba_definition.probe)
        assert facts["detected_os_version"] == "WC.16.10.0023"

    def test_extracts_hardware_2930f(self, aruba_definition):
        facts = parse_probe_output(_SHOW_SYSTEM_2930F, aruba_definition.probe)
        # Capture group should give us the chassis SKU + name; whitespace
        # trimmed by the parser.
        assert "2530-24G-PoEP" in facts["detected_model"]

    def test_extracts_serial_2930f(self, aruba_definition):
        facts = parse_probe_output(_SHOW_SYSTEM_2930F, aruba_definition.probe)
        assert facts.get("detected_serial") == "SG90BLR1KT"

    def test_extracts_software_revision_2530(self, aruba_definition):
        facts = parse_probe_output(_SHOW_SYSTEM_2530, aruba_definition.probe)
        assert facts["detected_os_version"] == "YA.16.11.0007"

    def test_extracts_serial_2530(self, aruba_definition):
        facts = parse_probe_output(_SHOW_SYSTEM_2530, aruba_definition.probe)
        assert facts.get("detected_serial") == "CN12ABCD34"

    def test_no_trailing_whitespace_in_values(self, aruba_definition):
        # show system rows often have trailing whitespace before \n —
        # parser must strip.
        padded = _SHOW_SYSTEM_2930F.replace(
            "WC.16.10.0023", "WC.16.10.0023   "
        )
        facts = parse_probe_output(padded, aruba_definition.probe)
        assert facts["detected_os_version"] == "WC.16.10.0023"


# ---------------------------------------------------------------------------
# Loader integration — definition loads cleanly via DefinitionLoader
# ---------------------------------------------------------------------------


class TestArubaDefinitionLoaderIntegration:
    def test_loader_picks_up_aruba_family_base(self, tmp_path):
        """When pointed at a tree containing the Aruba YAML, the loader
        returns it under its declared type_key."""
        from netcanon.definitions.loader import DefinitionLoader

        defs = tmp_path / "definitions"
        (defs / "aruba" / "aos-s").mkdir(parents=True)
        (defs / "aruba" / "aos-s" / "16.x.yaml").write_text(
            ARUBA_DEF_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )

        loader = DefinitionLoader(defs)
        loaded = loader.load_all()

        assert "Aruba" in loaded
        d = loaded["Aruba"]
        assert d.vendor.lower() == "aruba"
        assert d.collector.netmiko_device_type == "aruba_osswitch"
