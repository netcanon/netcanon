"""
Pre-built ``DeviceDefinition`` objects for unit tests.

These are constructed directly via Pydantic models — not via the YAML
loader — so unit tests that only need a valid definition object remain
independent of the file I/O and YAML parsing layers.

Usage::

    from tests.fixtures.definitions import make_cisco_definition

    def test_something():
        defn = make_cisco_definition()
        ...
"""
from __future__ import annotations

from netcanon.definitions.schema import (
    CollectorConfig,
    CommandConfig,
    ConnectionConfig,
    DeviceDefinition,
    PromptConfig,
)


def make_cisco_definition(**overrides) -> DeviceDefinition:
    """Return a minimal valid Cisco IOS-XE ``DeviceDefinition``.

    Pass keyword arguments to override individual top-level fields::

        defn = make_cisco_definition(priority=99)
    """
    kwargs: dict = dict(
        vendor="Cisco",
        os="IOS-XE",
        type_key="Cisco",
        priority=10,
        file_extension="cfg",
        connection=ConnectionConfig(needs_enable=True, cisco_more_paging=True),
        commands=CommandConfig(
            pre=[],
            config="show running-config",
            post=[],
        ),
        prompts=PromptConfig(trailing=[r"^\S+[#>]\s*$"]),
        collector=CollectorConfig(
            strategy="netmiko",
            netmiko_device_type="cisco_xe",
        ),
        notes="Cisco IOS-XE test definition.",
    )
    kwargs.update(overrides)
    return DeviceDefinition(**kwargs)


def make_fortigate_definition(**overrides) -> DeviceDefinition:
    """Return a minimal valid Fortigate FortiOS ``DeviceDefinition``."""
    kwargs: dict = dict(
        vendor="Fortigate",
        os="FortiOS",
        type_key="Fortigate",
        priority=10,
        file_extension="cfg",
        connection=ConnectionConfig(),
        commands=CommandConfig(
            pre=["config system console", "set output standard", "end"],
            config="show full-configuration",
            post=["config system console", "set output more", "end"],
        ),
        prompts=PromptConfig(trailing=[r"^\S+\s+[#]\s*$"]),
        collector=CollectorConfig(
            strategy="netmiko",
            netmiko_device_type="fortinet",
        ),
        notes="Fortigate FortiOS test definition.",
    )
    kwargs.update(overrides)
    return DeviceDefinition(**kwargs)


def make_opnsense_definition(**overrides) -> DeviceDefinition:
    """Return a minimal valid OPNsense ``DeviceDefinition``."""
    kwargs: dict = dict(
        vendor="OPNsense",
        os="OPNsense",
        type_key="OPNsense",
        priority=10,
        file_extension="xml",
        connection=ConnectionConfig(opnsense_shell_menu=True),
        commands=CommandConfig(
            config="cat /conf/config.xml",
            post=["exit"],
        ),
        prompts=PromptConfig(trailing=[r"^root@\S+:.*[#$]\s*$"]),
        collector=CollectorConfig(strategy="paramiko_shell"),
        notes="OPNsense test definition.",
    )
    kwargs.update(overrides)
    return DeviceDefinition(**kwargs)


def make_mikrotik_definition(**overrides) -> DeviceDefinition:
    """Return a minimal valid MikroTik RouterOS ``DeviceDefinition``."""
    kwargs: dict = dict(
        vendor="MikroTik",
        os="RouterOS",
        type_key="MikroTik",
        priority=10,
        file_extension="rsc",
        connection=ConnectionConfig(),
        commands=CommandConfig(config="/export verbose"),
        prompts=PromptConfig(trailing=[r"^\[.+\]\s*>\s*$"]),
        collector=CollectorConfig(
            strategy="netmiko",
            netmiko_device_type="mikrotik_routeros",
        ),
        notes="MikroTik RouterOS test definition.",
    )
    kwargs.update(overrides)
    return DeviceDefinition(**kwargs)
