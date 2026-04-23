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
      cisco_more_paging: true
      opnsense_shell_menu: false
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
      opnsense_shell_menu: true
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


# ---------------------------------------------------------------------------
# Longest-match resolver (layered definitions, Project 1 commit 1)
# ---------------------------------------------------------------------------

BASE_CISCO = textwrap.dedent("""\
    vendor: Cisco
    os: IOS-XE
    type_key: Cisco
    priority: 10
    file_extension: cfg
    connection:
      needs_enable: true
      cisco_more_paging: true
    commands:
      config: "show running-config"
    collector:
      strategy: netmiko
      netmiko_device_type: cisco_xe
    notes: family base
""")

OVERLAY_1712 = textwrap.dedent("""\
    vendor: Cisco
    os: IOS-XE
    type_key: Cisco
    priority: 20
    os_version: "17.12"
    file_extension: cfg
    connection:
      needs_enable: true
      cisco_more_paging: true
    commands:
      config: "show running-config"
    collector:
      strategy: netmiko
      netmiko_device_type: cisco_xe
    notes: overlay 17.12
""")

OVERLAY_1712_C9300 = textwrap.dedent("""\
    vendor: Cisco
    os: IOS-XE
    type_key: Cisco
    priority: 30
    os_version: "17.12"
    model: "C9300-48P"
    file_extension: cfg
    connection:
      needs_enable: true
      cisco_more_paging: true
    commands:
      config: "show running-config"
    collector:
      strategy: netmiko
      netmiko_device_type: cisco_xe
    notes: overlay 17.12 + C9300-48P
""")

OVERLAY_MODEL_ONLY = textwrap.dedent("""\
    vendor: Cisco
    os: IOS-XE
    type_key: Cisco
    priority: 25
    model: "C9300-48P"
    file_extension: cfg
    connection:
      needs_enable: true
      cisco_more_paging: true
    commands:
      config: "show running-config"
    collector:
      strategy: netmiko
      netmiko_device_type: cisco_xe
    notes: overlay C9300-48P any version
""")


class TestOverlayIsolation:
    """Overlays (entries with os_version or model set) must not pollute
    the family-base map returned by load_all().  Back-compat: callers
    that iterate load_all() see exactly one entry per type_key."""

    def test_overlay_excluded_from_legacy_map(self, tmp_path: Path):
        (tmp_path / "base.yaml").write_text(BASE_CISCO, encoding="utf-8")
        (tmp_path / "overlay.yaml").write_text(OVERLAY_1712, encoding="utf-8")
        loader = DefinitionLoader(tmp_path)
        profiles = loader.load_all()
        # Only family-base entry present; overlay invisible here.
        assert list(profiles.keys()) == ["Cisco"]
        assert profiles["Cisco"].notes == "family base"
        assert profiles["Cisco"].os_version is None

    def test_two_overlays_dont_collide_in_legacy_map(self, tmp_path: Path):
        (tmp_path / "base.yaml").write_text(BASE_CISCO, encoding="utf-8")
        (tmp_path / "1712.yaml").write_text(OVERLAY_1712, encoding="utf-8")
        (tmp_path / "1712_9300.yaml").write_text(
            OVERLAY_1712_C9300, encoding="utf-8"
        )
        profiles = DefinitionLoader(tmp_path).load_all()
        assert len(profiles) == 1


class TestResolveLongestMatch:
    """``DefinitionLoader.resolve`` picks the most-specific matching
    definition using the fallback ladder documented in the module
    docstring.  Each test covers one rung of the ladder."""

    def test_resolve_exact_triple_match(self, tmp_path: Path):
        """Pin both os_version + model → exact-triple overlay wins."""
        (tmp_path / "base.yaml").write_text(BASE_CISCO, encoding="utf-8")
        (tmp_path / "v.yaml").write_text(OVERLAY_1712, encoding="utf-8")
        (tmp_path / "vm.yaml").write_text(OVERLAY_1712_C9300, encoding="utf-8")
        loader = DefinitionLoader(tmp_path)
        loader.load_all()
        hit = loader.resolve("Cisco", os_version="17.12", model="C9300-48P")
        assert hit is not None
        assert hit.notes == "overlay 17.12 + C9300-48P"

    def test_resolve_version_pin_model_wildcard(self, tmp_path: Path):
        """Pin os_version only → version-overlay wins even when a
        triple-overlay exists for a different model."""
        (tmp_path / "base.yaml").write_text(BASE_CISCO, encoding="utf-8")
        (tmp_path / "v.yaml").write_text(OVERLAY_1712, encoding="utf-8")
        (tmp_path / "vm.yaml").write_text(OVERLAY_1712_C9300, encoding="utf-8")
        loader = DefinitionLoader(tmp_path)
        loader.load_all()
        hit = loader.resolve("Cisco", os_version="17.12")
        assert hit is not None
        assert hit.notes == "overlay 17.12"

    def test_resolve_version_pin_falls_through_to_base(self, tmp_path: Path):
        """Pin an os_version with no matching overlay → family base."""
        (tmp_path / "base.yaml").write_text(BASE_CISCO, encoding="utf-8")
        (tmp_path / "v.yaml").write_text(OVERLAY_1712, encoding="utf-8")
        loader = DefinitionLoader(tmp_path)
        loader.load_all()
        # 17.9 has no overlay — falls back to base.
        hit = loader.resolve("Cisco", os_version="17.9")
        assert hit is not None
        assert hit.notes == "family base"

    def test_resolve_model_pin_only(self, tmp_path: Path):
        """Pin model only, overlay exists for that model → overlay wins."""
        (tmp_path / "base.yaml").write_text(BASE_CISCO, encoding="utf-8")
        (tmp_path / "m.yaml").write_text(OVERLAY_MODEL_ONLY, encoding="utf-8")
        loader = DefinitionLoader(tmp_path)
        loader.load_all()
        hit = loader.resolve("Cisco", model="C9300-48P")
        assert hit is not None
        assert hit.notes == "overlay C9300-48P any version"

    def test_resolve_no_pin_returns_family_base(self, tmp_path: Path):
        """No pins → family-base wins even when overlays exist."""
        (tmp_path / "base.yaml").write_text(BASE_CISCO, encoding="utf-8")
        (tmp_path / "v.yaml").write_text(OVERLAY_1712, encoding="utf-8")
        loader = DefinitionLoader(tmp_path)
        loader.load_all()
        hit = loader.resolve("Cisco")
        assert hit is not None
        assert hit.notes == "family base"

    def test_resolve_unknown_type_key_returns_none(self, tmp_path: Path):
        (tmp_path / "base.yaml").write_text(BASE_CISCO, encoding="utf-8")
        loader = DefinitionLoader(tmp_path)
        loader.load_all()
        assert loader.resolve("Juniper") is None

    def test_resolve_before_load_all_returns_none(self, tmp_path: Path):
        """Defensive: resolve() called before load_all() has no data
        to consult.  Returning None (rather than raising) matches how
        a missing definition is handled downstream."""
        (tmp_path / "base.yaml").write_text(BASE_CISCO, encoding="utf-8")
        loader = DefinitionLoader(tmp_path)
        # NOTE: intentionally not calling load_all()
        assert loader.resolve("Cisco") is None

    def test_resolve_version_pin_prefers_version_over_model(self, tmp_path: Path):
        """When both an os_version overlay and a model overlay could
        apply (neither has the full triple), version wins — matches
        the tier ordering in the resolver docstring."""
        (tmp_path / "base.yaml").write_text(BASE_CISCO, encoding="utf-8")
        (tmp_path / "v.yaml").write_text(OVERLAY_1712, encoding="utf-8")
        (tmp_path / "m.yaml").write_text(OVERLAY_MODEL_ONLY, encoding="utf-8")
        loader = DefinitionLoader(tmp_path)
        loader.load_all()
        # Both overlays match if we relaxed tiers, but tier-2 (version
        # pin) wins over tier-3 (model pin).
        hit = loader.resolve("Cisco", os_version="17.12", model="C9300-48P")
        # With both a v-only and m-only overlay but no triple, the
        # tier-2 match (os_version=17.12, model=None) is preferred.
        assert hit is not None
        assert hit.notes == "overlay 17.12"
