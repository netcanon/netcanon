"""
Paramiko shell-based SSH collector.

Used for devices that require interactive shell-level orchestration not
supported by Netmiko's standard device handlers — primarily OPNsense,
which presents a numbered console menu on SSH login before a shell is
available.

The implementation replicates the proven PowerShell script logic:
* Open a raw interactive shell channel.
* Detect and dismiss the OPNsense console menu (sends ``8``).
* Drain pre-commands.
* Stream output from the config command, stopping after a configurable
  idle window.
* Send post-commands (e.g. ``exit`` to return to the menu).
"""

from __future__ import annotations

import logging
import time

import paramiko

from ..definitions.schema import DeviceDefinition
from ..models.device import DeviceTarget
from .base import BaseCollector
from .probe import parse_probe_output

logger = logging.getLogger(__name__)

_READ_INTERVAL = 0.2   # seconds between recv polls
_IDLE_THRESHOLD = 15   # consecutive idle polls before stopping (= 3 s)
_MAX_SECONDS = 120     # absolute read timeout
_CONNECT_TIMEOUT = 30
# Probe-specific tighter bounds — "show version" style output is
# tiny (< 1KB typically), so a shorter idle threshold keeps probe
# latency low and the separate-session cost acceptable.
_PROBE_IDLE_THRESHOLD = 8   # consecutive idle polls (~1.6s)
_PROBE_MAX_SECONDS = 30


class ParamikoShellCollector(BaseCollector):
    """Collects device configurations via a raw Paramiko interactive shell.

    This collector opens a PTY shell, handles OPNsense-style console menus,
    and streams output using the same idle-detection heuristic as the
    original PowerShell script.

    All timing constants (``_READ_INTERVAL``, ``_IDLE_THRESHOLD``,
    ``_MAX_SECONDS``) are module-level and may be overridden in tests.
    """

    def collect(self, device: DeviceTarget, definition: DeviceDefinition) -> str:
        """Open a Paramiko shell and return the raw config command output.

        Args:
            device: Connection target.
            definition: Device definition supplying commands and
                connection flags.

        Returns:
            Raw output from the config command (un-cleaned).

        Raises:
            paramiko.AuthenticationException: On authentication failure.
            paramiko.SSHException: On general SSH errors.
            TimeoutError: If the config command produces no output within
                ``_MAX_SECONDS``.
        """
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        logger.info("Connecting (Paramiko shell) to %s:%d", device.host, device.port)
        logger.debug(
            "SSH user for %s:%d: %s",
            device.host,
            device.port,
            device.credentials.username,
        )
        client.connect(
            hostname=device.host,
            port=device.port,
            username=device.credentials.username,
            password=device.credentials.password.get_secret_value(),
            timeout=_CONNECT_TIMEOUT,
            look_for_keys=False,
            allow_agent=False,
        )

        try:
            shell = client.invoke_shell(width=220, height=50)
            time.sleep(2)
            initial = self._drain(shell)

            # OPNsense console menu — send "8" to enter shell
            if definition.connection.opnsense_shell_menu:
                if "8) Shell" in initial or "Enter an option:" in initial:
                    logger.debug(
                        "OPNsense menu detected on %s — sending '8'", device.host
                    )
                    shell.send("8\n")
                    time.sleep(3)
                    self._drain(shell)

            for cmd in definition.commands.pre:
                logger.debug("Pre-command: %s", cmd)
                shell.send(f"{cmd}\n")
                time.sleep(2)
                self._drain(shell)

            # Final drain to clear anything lingering before config command
            time.sleep(1)
            self._drain(shell)

            logger.debug("Config command: %s", definition.commands.config)
            shell.send(f"{definition.commands.config}\n")
            output = self._collect_output(shell, device.host)

            for cmd in definition.commands.post:
                logger.debug("Post-command: %s", cmd)
                shell.send(f"{cmd}\n")
                time.sleep(1)
                self._drain(shell)

        finally:
            client.close()
            logger.info("SSH session closed for %s", device.host)

        logger.info("Collected %d bytes from %s", len(output), device.host)
        return output

    def probe(
        self, device: DeviceTarget, definition: DeviceDefinition
    ) -> dict[str, str]:
        """Run the probe command via a short-lived Paramiko shell session.

        Mirrors :meth:`NetmikoCollector.probe` for paramiko_shell
        strategy devices — opens a separate SSH session, handles the
        OPNsense console menu if the definition opts in, runs the
        probe command with a tighter idle threshold (~1.6s vs 3s
        main), parses output via :func:`parse_probe_output`.

        Failure modes all return ``{}`` and WARN:
          * ``definition.probe.command`` empty (nothing to do).
          * Connection / auth failure.
          * Menu handling produces no usable shell.
          * Probe command returns no output within
            ``_PROBE_MAX_SECONDS``.
          * Regex patterns don't match the output.

        Probe failure is NEVER fatal to the main backup — the caller
        (backup pipeline) falls back to the family-base definition.
        """
        if not definition.probe.command:
            return {}

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        logger.info(
            "Probing (Paramiko shell) %s:%d with command %r",
            device.host,
            device.port,
            definition.probe.command,
        )
        try:
            client.connect(
                hostname=device.host,
                port=device.port,
                username=device.credentials.username,
                password=device.credentials.password.get_secret_value(),
                timeout=_CONNECT_TIMEOUT,
                look_for_keys=False,
                allow_agent=False,
            )
        except Exception as exc:  # noqa: BLE001 — probe non-fatal
            logger.warning(
                "Probe connect to %s failed: %s — continuing with "
                "family-base definition",
                device.host,
                exc,
            )
            return {}

        try:
            shell = client.invoke_shell(width=220, height=50)
            time.sleep(2)
            initial = self._drain(shell)

            if definition.connection.opnsense_shell_menu:
                if "8) Shell" in initial or "Enter an option:" in initial:
                    logger.debug(
                        "OPNsense menu detected on %s during probe — "
                        "sending '8'",
                        device.host,
                    )
                    shell.send("8\n")
                    time.sleep(3)
                    self._drain(shell)

            time.sleep(1)
            self._drain(shell)

            shell.send(f"{definition.probe.command}\n")
            output = self._collect_probe_output(shell, device.host)
        except Exception as exc:  # noqa: BLE001 — probe non-fatal
            logger.warning(
                "Probe session on %s failed: %s — continuing with "
                "family-base definition",
                device.host,
                exc,
            )
            return {}
        finally:
            client.close()

        facts = parse_probe_output(output or "", definition.probe)
        logger.info(
            "Probe of %s returned %d fact(s): %s",
            device.host,
            len(facts),
            ", ".join(sorted(facts)) if facts else "(none)",
        )
        return facts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _drain(self, shell: paramiko.Channel, timeout: float = 0.5) -> str:
        """Read and return all immediately available output, then stop.

        Args:
            shell: Active Paramiko channel.
            timeout: Maximum seconds to wait for data before returning.

        Returns:
            All data received within *timeout* seconds, decoded as UTF-8.
        """
        buf = ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if shell.recv_ready():
                chunk = shell.recv(65536).decode("utf-8", errors="replace")
                buf += chunk
                deadline = time.monotonic() + timeout  # reset on new data
            else:
                time.sleep(0.05)
        return buf

    def _collect_output(self, shell: paramiko.Channel, host: str) -> str:
        """Read config command output until idle for ``_IDLE_THRESHOLD`` polls.

        Uses the same two-phase strategy as the PowerShell script:

        1. Wait for output to *start* (first meaningful data).
        2. Once started, stop after ``_IDLE_THRESHOLD`` consecutive empty
           polls (approximately 3 seconds of silence).

        An absolute ``_MAX_SECONDS`` cap prevents hanging forever if a
        device produces a never-ending stream.

        Args:
            shell: Active Paramiko channel.
            host: Used only for log messages.

        Returns:
            Accumulated raw output string.

        Raises:
            TimeoutError: If no output at all arrives within ``_MAX_SECONDS``.
        """
        buf = ""
        idle_count = 0
        started = False
        deadline = time.monotonic() + _MAX_SECONDS

        while time.monotonic() < deadline:
            time.sleep(_READ_INTERVAL)
            if shell.recv_ready():
                chunk = shell.recv(65536).decode("utf-8", errors="replace")
                buf += chunk
                idle_count = 0
                if len(buf.splitlines()) > 0:
                    started = True
                if len(buf) % (100 * 80) < 160:
                    logger.debug(
                        "%s: ~%d lines received so far", host, len(buf.splitlines())
                    )
            else:
                idle_count += 1
                if started and idle_count >= _IDLE_THRESHOLD:
                    logger.debug(
                        "%s: idle threshold reached after %d lines",
                        host,
                        len(buf.splitlines()),
                    )
                    break

        if not buf:
            raise TimeoutError(
                f"No output received from {host} within {_MAX_SECONDS}s"
            )
        return buf

    def _collect_probe_output(
        self, shell: paramiko.Channel, host: str
    ) -> str:
        """Probe-tuned variant of :meth:`_collect_output`.

        Uses ``_PROBE_IDLE_THRESHOLD`` + ``_PROBE_MAX_SECONDS`` in
        place of the main-collect constants.  "Show version" output
        is tiny, so the tighter idle window keeps probe latency to
        a couple of seconds even on slow devices.  Returns the
        accumulated buffer — empty string is a valid result (the
        caller treats missing-match as a no-op, not an error).
        """
        buf = ""
        idle_count = 0
        started = False
        deadline = time.monotonic() + _PROBE_MAX_SECONDS

        while time.monotonic() < deadline:
            time.sleep(_READ_INTERVAL)
            if shell.recv_ready():
                chunk = shell.recv(65536).decode("utf-8", errors="replace")
                buf += chunk
                idle_count = 0
                if len(buf.splitlines()) > 0:
                    started = True
            else:
                idle_count += 1
                if started and idle_count >= _PROBE_IDLE_THRESHOLD:
                    break
        return buf
