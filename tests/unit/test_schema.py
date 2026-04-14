"""
Unit tests for ``netconfig.definitions.schema``.

These tests exercise Pydantic model construction and validation directly —
no file I/O, no YAML parsing, no HTTP.  Each test should be milliseconds.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from netconfig.definitions.schema import (
    CollectorConfig,
    CommandConfig,
    ConnectionConfig,
    DeviceDefinition,
    PromptConfig,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# CollectorConfig
# ---------------------------------------------------------------------------


class TestCollectorConfig:
    def test_valid_netmiko(self):
        cfg = CollectorConfig(strategy="netmiko", netmiko_device_type="cisco_xe")
        assert cfg.strategy == "netmiko"
        assert cfg.netmiko_device_type == "cisco_xe"

    def test_valid_paramiko_shell(self):
        cfg = CollectorConfig(strategy="paramiko_shell")
        assert cfg.strategy == "paramiko_shell"
        assert cfg.netmiko_device_type is None

    def test_paramiko_shell_ignores_netmiko_device_type(self):
        """netmiko_device_type is silently accepted (and ignored) for paramiko_shell."""
        cfg = CollectorConfig(
            strategy="paramiko_shell",
            netmiko_device_type="cisco_xe",
        )
        assert cfg.strategy == "paramiko_shell"

    def test_netmiko_with_explicit_null_raises(self):
        """Explicitly setting netmiko_device_type=None with netmiko strategy is rejected."""
        with pytest.raises(ValidationError, match="netmiko_device_type"):
            CollectorConfig(strategy="netmiko", netmiko_device_type=None)

    def test_invalid_strategy_raises(self):
        with pytest.raises(ValidationError):
            CollectorConfig(strategy="telnet")  # type: ignore[arg-type]

    def test_known_netmiko_device_types(self):
        """Spot-check that real Netmiko device-type strings are accepted."""
        for dt in ("cisco_xe", "fortinet", "mikrotik_routeros"):
            cfg = CollectorConfig(strategy="netmiko", netmiko_device_type=dt)
            assert cfg.netmiko_device_type == dt


# ---------------------------------------------------------------------------
# ConnectionConfig
# ---------------------------------------------------------------------------


class TestConnectionConfig:
    def test_all_defaults_false(self):
        cfg = ConnectionConfig()
        assert cfg.needs_enable is False
        assert cfg.handle_paging is False
        assert cfg.needs_shell_menu is False

    def test_cisco_flags(self):
        cfg = ConnectionConfig(needs_enable=True, handle_paging=True)
        assert cfg.needs_enable is True
        assert cfg.handle_paging is True
        assert cfg.needs_shell_menu is False

    def test_opnsense_flags(self):
        cfg = ConnectionConfig(needs_shell_menu=True)
        assert cfg.needs_shell_menu is True


# ---------------------------------------------------------------------------
# CommandConfig
# ---------------------------------------------------------------------------


class TestCommandConfig:
    def test_config_required(self):
        with pytest.raises(ValidationError):
            CommandConfig()  # type: ignore[call-arg]

    def test_pre_post_default_empty(self):
        cfg = CommandConfig(config="show running-config")
        assert cfg.pre == []
        assert cfg.post == []

    def test_pre_post_with_commands(self):
        cfg = CommandConfig(
            pre=["config system console", "set output standard", "end"],
            config="show full-configuration",
            post=["config system console", "set output more", "end"],
        )
        assert len(cfg.pre) == 3
        assert len(cfg.post) == 3


# ---------------------------------------------------------------------------
# PromptConfig
# ---------------------------------------------------------------------------


class TestPromptConfig:
    def test_default_trailing_empty(self):
        cfg = PromptConfig()
        assert cfg.trailing == []

    def test_trailing_patterns(self):
        cfg = PromptConfig(trailing=[r"^\S+[#>]\s*$", r"^\[.+\]\s*>\s*$"])
        assert len(cfg.trailing) == 2


# ---------------------------------------------------------------------------
# DeviceDefinition
# ---------------------------------------------------------------------------


def _valid_definition_kwargs() -> dict:
    """Return keyword arguments for a valid Cisco DeviceDefinition."""
    return dict(
        vendor="Cisco",
        os="IOS-XE",
        type_key="Cisco",
        connection=ConnectionConfig(needs_enable=True),
        commands=CommandConfig(config="show running-config"),
        collector=CollectorConfig(
            strategy="netmiko",
            netmiko_device_type="cisco_xe",
        ),
    )


class TestDeviceDefinition:
    def test_valid_definition_constructs(self):
        d = DeviceDefinition(**_valid_definition_kwargs())
        assert d.vendor == "Cisco"
        assert d.type_key == "Cisco"

    def test_default_priority_zero(self):
        d = DeviceDefinition(**_valid_definition_kwargs())
        assert d.priority == 0

    def test_default_file_extension_cfg(self):
        d = DeviceDefinition(**_valid_definition_kwargs())
        assert d.file_extension == "cfg"

    def test_default_version_match_wildcard(self):
        d = DeviceDefinition(**_valid_definition_kwargs())
        assert d.version_match == ".*"

    def test_missing_vendor_raises(self):
        kwargs = _valid_definition_kwargs()
        del kwargs["vendor"]
        with pytest.raises(ValidationError):
            DeviceDefinition(**kwargs)

    def test_missing_os_raises(self):
        kwargs = _valid_definition_kwargs()
        del kwargs["os"]
        with pytest.raises(ValidationError):
            DeviceDefinition(**kwargs)

    def test_missing_type_key_raises(self):
        kwargs = _valid_definition_kwargs()
        del kwargs["type_key"]
        with pytest.raises(ValidationError):
            DeviceDefinition(**kwargs)

    def test_missing_connection_raises(self):
        kwargs = _valid_definition_kwargs()
        del kwargs["connection"]
        with pytest.raises(ValidationError):
            DeviceDefinition(**kwargs)

    def test_missing_commands_raises(self):
        kwargs = _valid_definition_kwargs()
        del kwargs["commands"]
        with pytest.raises(ValidationError):
            DeviceDefinition(**kwargs)

    def test_source_file_excluded_from_model_dump(self):
        from pathlib import Path

        d = DeviceDefinition(**_valid_definition_kwargs())
        d.source_file = Path("/tmp/test.yaml")
        data = d.model_dump()
        assert "source_file" not in data

    def test_source_file_default_none(self):
        d = DeviceDefinition(**_valid_definition_kwargs())
        assert d.source_file is None

    def test_paramiko_shell_definition_valid(self):
        d = DeviceDefinition(
            vendor="OPNsense",
            os="OPNsense",
            type_key="OPNsense",
            connection=ConnectionConfig(needs_shell_menu=True),
            commands=CommandConfig(config="cat /conf/config.xml"),
            collector=CollectorConfig(strategy="paramiko_shell"),
        )
        assert d.collector.strategy == "paramiko_shell"
        assert d.collector.netmiko_device_type is None

    def test_notes_default_empty_string(self):
        d = DeviceDefinition(**_valid_definition_kwargs())
        assert d.notes == ""

    def test_custom_priority(self):
        d = DeviceDefinition(**_valid_definition_kwargs(), priority=50)
        assert d.priority == 50

    def test_xml_extension(self):
        kwargs = _valid_definition_kwargs()
        kwargs["file_extension"] = "xml"
        d = DeviceDefinition(**kwargs)
        assert d.file_extension == "xml"
