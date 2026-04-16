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

logger = logging.getLogger(__name__)

# Netmiko's send_command timeout — matches the PS script's 120s limit
_READ_TIMEOUT = 120


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
