"""
Netmiko-based SSH collector.

Uses Netmiko's ``ConnectHandler`` for vendors with native support:
Cisco IOS-XE, Fortigate FortiOS, and MikroTik RouterOS.  Netmiko
handles SSH quirks (prompt detection, enable mode, ``--More--`` paging)
internally for these platforms, so definition pre/post commands are
the main extension point rather than custom stream logic.

Supported netmiko_device_type values
-------------------------------------
``cisco_xe``           Cisco IOS-XE
``fortinet``           Fortigate FortiOS
``mikrotik_routeros``  MikroTik RouterOS
"""

from __future__ import annotations

import logging

from netmiko import ConnectHandler

from ..definitions.schema import DeviceDefinition
from ..models.device import DeviceTarget
from .base import BaseCollector
from .probe import parse_probe_output

logger = logging.getLogger(__name__)

# Netmiko's send_command timeout — matches the PS script's 120s limit
_READ_TIMEOUT = 120
# Probe is a lightweight "show version" — bound its session time
# tighter than the main config collect so a flaky device doesn't
# take the backup down.  If probe exceeds this, we log + return
# empty and let the main collect try.
_PROBE_READ_TIMEOUT = 30


class NetmikoCollector(BaseCollector):
    """Collects device configurations via Netmiko.

    Netmiko transparently manages:

    * SSH key acceptance
    * Enable-mode escalation (when ``secret`` is supplied)
    * ``--More--`` paging dismissal
    * Prompt detection and output stripping

    Pre- and post-commands from the definition are sent via
    ``send_command_timing`` (fire-and-forget with a short drain) while
    the main config command uses ``send_command`` for reliable
    prompt-based termination.
    """

    def collect(self, device: DeviceTarget, definition: DeviceDefinition) -> str:
        """Connect to *device* via Netmiko and return the raw config output.

        Args:
            device: Connection target.
            definition: Device definition supplying commands and collector
                config.

        Returns:
            Raw configuration text as returned by Netmiko (prompts and
            echo already stripped by Netmiko internally).

        Raises:
            ValueError: If ``netmiko_device_type`` is not set in the
                definition's collector config.
            netmiko.NetmikoAuthenticationException: On auth failure.
            netmiko.NetmikoTimeoutException: On connection or read timeout.
        """
        device_type = definition.collector.netmiko_device_type
        if not device_type:
            raise ValueError(
                f"netmiko_device_type is not set for definition "
                f"'{definition.type_key}'"
            )

        params: dict = {
            "device_type": device_type,
            "host": device.host,
            "port": device.port,
            "username": device.credentials.username,
            "password": device.credentials.password.get_secret_value(),
            "conn_timeout": 30,
        }
        if device.credentials.enable_password:
            params["secret"] = (
                device.credentials.enable_password.get_secret_value()
            )

        logger.info("Connecting to %s:%d (%s)", device.host, device.port, device_type)
        logger.debug(
            "SSH user for %s:%d: %s",
            device.host,
            device.port,
            device.credentials.username,
        )

        with ConnectHandler(**params) as conn:
            if definition.connection.needs_enable:
                logger.debug("Entering enable mode on %s", device.host)
                conn.enable()

            for cmd in definition.commands.pre:
                logger.debug("Pre-command on %s: %s", device.host, cmd)
                conn.send_command_timing(cmd, strip_prompt=False, strip_command=False)

            logger.debug(
                "Running config command on %s: %s",
                device.host,
                definition.commands.config,
            )
            output = conn.send_command(
                definition.commands.config,
                read_timeout=_READ_TIMEOUT,
                strip_command=True,
                strip_prompt=True,
            )

            for cmd in definition.commands.post:
                logger.debug("Post-command on %s: %s", device.host, cmd)
                conn.send_command_timing(cmd, strip_prompt=False, strip_command=False)

        logger.info(
            "Collected %d bytes from %s", len(output or ""), device.host
        )
        return output or ""

    def probe(
        self, device: DeviceTarget, definition: DeviceDefinition
    ) -> dict[str, str]:
        """Run the probe command via a short-lived Netmiko session.

        Opens a separate SSH session from :meth:`collect` — see
        :meth:`BaseCollector.probe` for the rationale + cost notes.
        Probe failures are logged at WARNING and swallowed; the
        caller gets an empty dict and falls back to the family-base
        definition.

        Returns an empty dict when:

        * ``definition.probe.command`` is empty (no probe configured).
        * The SSH connection fails.
        * The command runs but no regex pattern matches.
        """
        if not definition.probe.command:
            return {}

        device_type = definition.collector.netmiko_device_type
        if not device_type:
            # Defence in depth — Netmiko won't open without this, so
            # abort early rather than letting the connection layer
            # raise + fall through to the broad exception handler.
            logger.warning(
                "probe skipped for %s: netmiko_device_type missing in "
                "definition %r",
                device.host,
                definition.type_key,
            )
            return {}

        params: dict = {
            "device_type": device_type,
            "host": device.host,
            "port": device.port,
            "username": device.credentials.username,
            "password": device.credentials.password.get_secret_value(),
            "conn_timeout": 30,
        }
        if device.credentials.enable_password:
            params["secret"] = (
                device.credentials.enable_password.get_secret_value()
            )

        logger.info(
            "Probing %s:%d (%s) with command %r",
            device.host,
            device.port,
            device_type,
            definition.probe.command,
        )
        try:
            with ConnectHandler(**params) as conn:
                if definition.connection.needs_enable:
                    conn.enable()
                output = conn.send_command(
                    definition.probe.command,
                    read_timeout=_PROBE_READ_TIMEOUT,
                    strip_command=True,
                    strip_prompt=True,
                )
        except Exception as exc:  # noqa: BLE001 — probe failures non-fatal
            logger.warning(
                "Probe of %s failed: %s — continuing with family-base "
                "definition",
                device.host,
                exc,
            )
            return {}

        facts = parse_probe_output(output or "", definition.probe)
        logger.info(
            "Probe of %s returned %d fact(s): %s",
            device.host,
            len(facts),
            ", ".join(sorted(facts)) if facts else "(none)",
        )
        return facts
