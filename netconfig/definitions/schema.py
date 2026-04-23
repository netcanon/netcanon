"""
Pydantic schema for device definition YAML files.

Every ``*.yaml`` file under ``definitions/`` is validated against
``DeviceDefinition`` when the application starts.  Malformed or
incomplete files emit a warning and are skipped rather than crashing
the server.

Field-level documentation here also serves as the authoritative reference
for definition authors — keep it in sync with ``definitions/README.md``.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ConnectionConfig(BaseModel):
    """SSH session behaviour flags.

    Attributes:
        needs_enable: Send ``enable`` if the initial banner shows a
            user-exec prompt (``>``).  Applies to any device that requires
            privileged-mode escalation (Cisco IOS/IOS-XE, HP ProCurve,
            Aruba OS-CX, and others supported by Netmiko).
        cisco_more_paging: Suppress Cisco ``--More--`` prompts by injecting
            a SPACE character mid-stream.  Cisco IOS/IOS-XE only —
            ``terminal length 0`` is deliberately avoided on this platform.
        opnsense_shell_menu: Detect and dismiss the OPNsense numbered
            console menu by sending ``8`` before issuing any commands.
            OPNsense only — SSH on this device lands at a menu rather than
            a shell prompt.
    """

    needs_enable: bool = False
    cisco_more_paging: bool = False
    opnsense_shell_menu: bool = False


class CommandConfig(BaseModel):
    """Command sequence for configuration retrieval.

    Attributes:
        pre: Commands sent (and drained) before the main config command.
            Typically used to disable paging or adjust output formatting.
        config: The command whose output *is* the device configuration.
        post: Commands sent after collection, e.g. to restore settings
            changed by ``pre`` commands.
    """

    pre: list[str] = Field(default_factory=list)
    config: str
    post: list[str] = Field(default_factory=list)


class PromptConfig(BaseModel):
    """Prompt patterns used for SSH output post-processing.

    Attributes:
        trailing: List of regular expressions that match shell-prompt
            lines at the end of captured output.  The output cleaner
            strips any trailing lines matching any of these patterns.
            Vendor-specific patterns yield tighter stripping than the
            broad fallback used when patterns are absent.
    """

    trailing: list[str] = Field(default_factory=list)


class CollectorConfig(BaseModel):
    """Specifies which collection strategy to use for this definition.

    Attributes:
        strategy: ``"netmiko"`` uses Netmiko's high-level
            ``ConnectHandler`` for vendors it supports natively.
            ``"paramiko_shell"`` opens a raw interactive shell via
            Paramiko for devices requiring custom session orchestration
            (e.g. OPNsense's console menu).
        netmiko_device_type: Netmiko device-type string passed to
            ``ConnectHandler``.  Required when ``strategy`` is
            ``"netmiko"``; ignored otherwise.
            Common values: ``cisco_xe``, ``fortinet``,
            ``mikrotik_routeros``.
    """

    strategy: Literal["netmiko", "paramiko_shell"] = "netmiko"
    netmiko_device_type: str | None = None

    @field_validator("netmiko_device_type")
    @classmethod
    def device_type_required_for_netmiko(
        cls, v: str | None, info: object
    ) -> str | None:
        """Validate that netmiko_device_type is present when strategy is netmiko."""
        # info.data is populated with already-validated fields
        strategy = getattr(info, "data", {}).get("strategy", "netmiko")
        if strategy == "netmiko" and not v:
            raise ValueError(
                "netmiko_device_type is required when collector.strategy is 'netmiko'"
            )
        return v


class DeviceDefinition(BaseModel):
    """A fully-validated device definition loaded from a YAML file.

    This is the central object that every other component depends on.
    The loader populates ``source_file`` after validation so callers can
    report which file a definition came from.

    Attributes:
        vendor: Human-readable vendor name (e.g. ``"Cisco"``).
        os: Operating system name (e.g. ``"IOS-XE"``).
        version_match: Regex matched against the detected version string
            post-connection for future automatic selection.  Defaults to
            ``".*"`` (matches any version).
        type_key: Primary lookup key.  Must be unique across all loaded
            definitions (higher-priority files win on collision within
            the family-base set).  This is the value users pass as
            ``type_key`` in device lists.
        priority: Load order for conflict resolution among family-base
            entries (those with ``os_version`` and ``model`` both unset).
            Higher numbers are loaded later and override lower-priority
            definitions sharing the same ``type_key``.  Overlays —
            entries with ``os_version`` or ``model`` set — do NOT
            participate in priority-based overriding; they live in a
            parallel variant registry accessible via
            :meth:`DefinitionLoader.resolve`.
        os_version: Specific OS version this definition targets
            (e.g. ``"17.12"``).  ``None`` = family-base, applies to any
            version.  Used by :meth:`DefinitionLoader.resolve` for
            longest-match lookup: a pinned target with
            ``os_version="17.12"`` picks the ``17.12`` overlay when it
            exists; falls back to the family base when it doesn't.
        model: Specific hardware model this definition targets (e.g.
            ``"C9300-48P"``).  ``None`` = any model.  Same longest-match
            semantics as ``os_version`` — rarely needed since CLI
            backup behaviour almost never varies by model, but
            available for the edge case.
        file_extension: Output file extension without the leading dot.
        connection: SSH session flags.
        commands: Pre/config/post command sequence.
        prompts: Trailing-prompt patterns for output cleaning.
        collector: Collector strategy selection.
        notes: Free-text notes visible in the web UI and ``--verbose``
            loader output.  Document known quirks here.
        source_file: Set by the loader; not present in YAML files.
    """

    vendor: str
    os: str
    version_match: str = ".*"
    type_key: str
    priority: int = 0
    os_version: str | None = None
    model: str | None = None
    file_extension: str = "cfg"
    connection: ConnectionConfig
    commands: CommandConfig
    prompts: PromptConfig = Field(default_factory=PromptConfig)
    collector: CollectorConfig = Field(default_factory=CollectorConfig)
    notes: str = ""
    source_file: Path | None = Field(None, exclude=True)
