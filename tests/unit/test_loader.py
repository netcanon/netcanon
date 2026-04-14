"""
Unit tests for ``netconfig.definitions.loader.DefinitionLoader``.

These tests write minimal YAML files to tmp directories and verify the
two-pass loader: parse → sort by priority → apply in order.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from netconfig.definitions.loader import DefinitionLoader

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Canned YAML content
# ---------------------------------------------------------------------------

VALID_CISCO = textwrap.dedent("""\
    vendor: Cisco
    os: IOS-XE
    type_key: Cisco
    priority: 10
    file_extension: cfg
    connection:
      needs_enable: true
      handle_paging: true
      needs_shell_menu: false
    commands:
      config: "show running-config"
    collector:
      strategy: netmiko
      netmiko_device_type: cisco_xe
    notes: Cisco IOS-XE test definition.
""")

VALID_OPNSENSE = textwrap.dedent("""\
    vendor: OPNsense
    os: OPNsense
    type_key: OPNsense
    priority: 10
    file_extension: xml
    connection:
      needs_enable: false
      needs_shell_menu: true
    commands:
      config: "cat /conf/config.xml"
    collector:
      strategy: paramiko_shell
    notes: OPNsense test definition.
""")

LOW_PRIORITY_CISCO = textwrap.dedent("""\
    vendor: Cisco
    os: IOS-XE
    type_key: Cisco
    priority: 0
    file_extension: cfg
    connection:
      needs_enable: false
    commands:
      config: "show run"
    collector:
      strategy: netmiko
      netmiko_device_type: cisco_xe
    notes: Low priority base definition.
""")

HIGH_PRIORITY_CISCO = textwrap.dedent("""\
    vendor: Cisco
    os: IOS-XE 17.x
    type_key: Cisco
    priority: 50
    file_extension: cfg
    connection:
      needs_enable: true
    commands:
      config: "show running-config"
    collector:
      strategy: netmiko
      netmiko_device_type: cisco_xe
    notes: High priority override definition.
""")

MISSING_COMMANDS = textwrap.dedent("""\
    vendor: Bad
    os: BadOS
    type_key: Bad
    connection:
      needs_enable: false
    collector:
      strategy: netmiko
      netmiko_device_type: bad_device
""")


# ---------------------------------------------------------------------------
# Directory / file not found
# ---------------------------------------------------------------------------


class TestLoaderMissingDirectory:
    def test_missing_dir_raises_file_not_found(self, tmp_path: Path):
        loader = DefinitionLoader(tmp_path / "does_not_exist")
        with pytest.raises(FileNotFoundError, match="not found"):
            loader.load_all()

    def test_empty_dir_raises_runtime_error(self, tmp_path: Path):
        loader = DefinitionLoader(tmp_path)
        with pytest.raises(RuntimeError, match=r"No \*.yaml"):
            loader.load_all()

    def test_dir_with_only_non_yaml_files_raises(self, tmp_path: Path):
        (tmp_path / "README.txt").write_text("not yaml", encoding="utf-8")
        loader = DefinitionLoader(tmp_path)
        with pytest.raises(RuntimeError, match=r"No \*.yaml"):
            loader.load_all()


# ---------------------------------------------------------------------------
# Valid file loading
# ---------------------------------------------------------------------------


class TestLoaderValidFiles:
    def test_loads_single_valid_file(self, tmp_path: Path):
        (tmp_path / "cisco.yaml").write_text(VALID_CISCO, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        assert "Cisco" in profiles

    def test_loaded_definition_fields(self, tmp_path: Path):
        (tmp_path / "cisco.yaml").write_text(VALID_CISCO, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        d = profiles["Cisco"]
        assert d.vendor == "Cisco"
        assert d.os == "IOS-XE"
        assert d.file_extension == "cfg"
        assert d.collector.strategy == "netmiko"
        assert d.collector.netmiko_device_type == "cisco_xe"

    def test_loads_multiple_files(self, tmp_path: Path):
        (tmp_path / "cisco.yaml").write_text(VALID_CISCO, encoding="utf-8")
        (tmp_path / "opnsense.yaml").write_text(VALID_OPNSENSE, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        assert set(profiles.keys()) == {"Cisco", "OPNsense"}

    def test_source_file_is_set(self, tmp_path: Path):
        path = tmp_path / "cisco.yaml"
        path.write_text(VALID_CISCO, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        assert profiles["Cisco"].source_file == path

    def test_loads_yaml_recursively(self, tmp_path: Path):
        sub = tmp_path / "cisco" / "ios-xe"
        sub.mkdir(parents=True)
        (sub / "17.x.yaml").write_text(VALID_CISCO, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        assert "Cisco" in profiles

    def test_returns_dict_type(self, tmp_path: Path):
        (tmp_path / "cisco.yaml").write_text(VALID_CISCO, encoding="utf-8")
        result = DefinitionLoader(tmp_path).load_all()
        assert isinstance(result, dict)

    def test_paramiko_shell_definition_loads(self, tmp_path: Path):
        (tmp_path / "opnsense.yaml").write_text(VALID_OPNSENSE, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        assert profiles["OPNsense"].collector.strategy == "paramiko_shell"


# ---------------------------------------------------------------------------
# Error handling — bad files are skipped, good files still load
# ---------------------------------------------------------------------------


class TestLoaderErrorHandling:
    def test_malformed_yaml_is_skipped(self, tmp_path: Path):
        (tmp_path / "bad.yaml").write_text(":\t:\t{ invalid yaml !!", encoding="utf-8")
        (tmp_path / "good.yaml").write_text(VALID_CISCO, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        assert "Cisco" in profiles

    def test_non_dict_yaml_is_skipped(self, tmp_path: Path):
        (tmp_path / "list.yaml").write_text("- item1\n- item2\n", encoding="utf-8")
        (tmp_path / "good.yaml").write_text(VALID_CISCO, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        assert "Cisco" in profiles

    def test_invalid_schema_is_skipped(self, tmp_path: Path):
        (tmp_path / "bad.yaml").write_text(MISSING_COMMANDS, encoding="utf-8")
        (tmp_path / "good.yaml").write_text(VALID_CISCO, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        assert "Bad" not in profiles
        assert "Cisco" in profiles

    def test_all_invalid_raises_runtime_error(self, tmp_path: Path):
        (tmp_path / "bad.yaml").write_text(MISSING_COMMANDS, encoding="utf-8")
        with pytest.raises(RuntimeError, match="No valid definitions"):
            DefinitionLoader(tmp_path).load_all()

    def test_bad_file_does_not_prevent_other_files(self, tmp_path: Path):
        for i in range(3):
            (tmp_path / f"bad{i}.yaml").write_text(
                MISSING_COMMANDS, encoding="utf-8"
            )
        (tmp_path / "good.yaml").write_text(VALID_CISCO, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        assert "Cisco" in profiles


# ---------------------------------------------------------------------------
# Priority-based override resolution
# ---------------------------------------------------------------------------


class TestLoaderPriority:
    def test_higher_priority_wins(self, tmp_path: Path):
        (tmp_path / "base.yaml").write_text(LOW_PRIORITY_CISCO, encoding="utf-8")
        (tmp_path / "override.yaml").write_text(HIGH_PRIORITY_CISCO, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        # HIGH_PRIORITY_CISCO has os="IOS-XE 17.x"
        assert profiles["Cisco"].os == "IOS-XE 17.x"

    def test_higher_priority_overrides_connection_flags(self, tmp_path: Path):
        # LOW: needs_enable=false  HIGH: needs_enable=true
        (tmp_path / "base.yaml").write_text(LOW_PRIORITY_CISCO, encoding="utf-8")
        (tmp_path / "override.yaml").write_text(HIGH_PRIORITY_CISCO, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        assert profiles["Cisco"].connection.needs_enable is True

    def test_priority_field_is_preserved(self, tmp_path: Path):
        (tmp_path / "base.yaml").write_text(LOW_PRIORITY_CISCO, encoding="utf-8")
        (tmp_path / "override.yaml").write_text(HIGH_PRIORITY_CISCO, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        assert profiles["Cisco"].priority == 50

    def test_only_one_entry_per_type_key(self, tmp_path: Path):
        (tmp_path / "base.yaml").write_text(LOW_PRIORITY_CISCO, encoding="utf-8")
        (tmp_path / "override.yaml").write_text(HIGH_PRIORITY_CISCO, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        assert len(profiles) == 1

    def test_equal_priority_last_path_wins(self, tmp_path: Path):
        """When priorities are equal, lexicographic file order determines winner."""
        # "z_override.yaml" sorts after "a_base.yaml" alphabetically
        a_def = LOW_PRIORITY_CISCO.replace("priority: 0", "priority: 10").replace(
            "os: IOS-XE", "os: A"
        )
        z_def = LOW_PRIORITY_CISCO.replace("priority: 0", "priority: 10").replace(
            "os: IOS-XE", "os: Z"
        )
        (tmp_path / "a_base.yaml").write_text(a_def, encoding="utf-8")
        (tmp_path / "z_override.yaml").write_text(z_def, encoding="utf-8")
        profiles = DefinitionLoader(tmp_path).load_all()
        assert profiles["Cisco"].os == "Z"
