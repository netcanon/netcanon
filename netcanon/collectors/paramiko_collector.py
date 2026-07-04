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

Security model
--------------
Netcanon is operator-trust-anchor by design: the operator who registers
a backup target in the UI is asserting that the target's IP + port pair
is the device they intend to reach.  Host-key verification is governed by
``Settings.ssh_host_key_checking`` (see :mod:`netcanon.collectors.hostkey`):
``tofu`` (default since v0.4.5) persists the first key seen under
``{data_dir}/known_hosts`` and rejects a later changed key; ``auto_add``
(legacy opt-out) keeps the historical trust-on-first-use-*without*-
persistence behaviour for a trusted management VLAN and warns at startup;
``reject`` only connects to already-known hosts.  Both
:meth:`ParamikoShellCollector.collect` and ``.probe`` apply the configured
policy + persist (TOFU) after a successful connect.

The opt-in TOFU store closes the AutoAddPolicy gap scoped during the
2026-05-21 security-triage cycle and re-raised by the 2026-06-14 review
(finding #11); ``docs/security-triage/2026-05-21/`` retains the original
trade-off discussion.
"""

from __future__ import annotations

import logging
import re
import time

import paramiko

from ..definitions.schema import DeviceDefinition
from ..models.device import DeviceTarget
from .base import BaseCollector
from .hostkey import apply_paramiko_policy, persist_paramiko_host_keys
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


_SHELL_PROMPT_RE = re.compile(
    # Conservative shell prompt match anchored at end-of-buffer:
    # `username@hostname:cwd [$#>]` with optional trailing space.
    # The leading `^` binds it to the start of a line (via re.M
    # when used); the preceding \r?\n in the search avoids false
    # matches on config content that happens to end with `#`.
    r"(?m)^[A-Za-z0-9_.\-]+@[A-Za-z0-9_.\-]+:[^\n]*[#$>]\s*$",
)


def _strip_command_echo(buf: str, command: str) -> str:
    """Remove the echoed command line from the head of *buf* and
    any residual shell prompt from the tail.

    Paramiko's raw PTY shell leaks BOTH ends of the interaction
    into the accumulated buffer:

    * The **head** holds the echo of every byte the caller sent —
      ``shell.send("cat /conf/config.xml\\n")`` makes the device's
      terminal echo ``cat /conf/config.xml`` back at us BEFORE the
      actual command output arrives.  Usually followed by
      ``\\r\\r\\n`` noise (FreeBSD/OPNsense PTY style).
    * The **tail** holds the shell prompt that returns after the
      command completes — ``root@supergate:~ # `` appended after
      the closing bytes of the real output.

    Downstream parsers (OPNsense's ``ET.fromstring`` especially)
    reject anything not well-formed XML, so both ends must be
    trimmed.  Netmiko handles the same issues via
    ``strip_command=True`` + ``strip_prompt=True``; the raw
    paramiko-shell strategy has to do them explicitly.

    The strip is conservative on both ends:

    * **Head**: locate the first occurrence of *command* in the
      first 512 bytes.  Not present → return unchanged.  Match →
      slice to just past the command + trailing whitespace run.
    * **Tail**: locate the last line matching a shell-prompt
      shape (``user@host:cwd #|$|>``) within the last 512 bytes.
      Match → slice before it (keeping trailing content that
      isn't a prompt, like a trailing newline from the real
      output).
    """
    if not buf:
        return buf
    # --- Head: strip echoed command ---
    if command:
        head = buf[:512]
        idx = head.find(command)
        if idx >= 0:
            cut = idx + len(command)
            n = len(buf)
            while cut < n and buf[cut] in ("\r", "\n", "\t", " "):
                cut += 1
            buf = buf[cut:]
    # --- Tail: strip shell prompt residue ---
    # Look at the last 512 bytes only so we don't accidentally
    # match a prompt-shaped config line buried in the middle of
    # the real output.
    tail_window = buf[-512:] if len(buf) > 512 else buf
    m = None
    for candidate in _SHELL_PROMPT_RE.finditer(tail_window):
        m = candidate  # last match wins
    if m is not None:
        # Map the match position back into the full buffer.
        window_start = len(buf) - len(tail_window)
        prompt_start = window_start + m.start()
        buf = buf[:prompt_start]
        # Drop any trailing whitespace left over by the prompt's
        # preceding newline run.
        buf = buf.rstrip("\r\n\t ") + "\n" if buf.rstrip("\r\n\t ") else ""
    return buf


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
        # Host-key verification policy (see module "Security model" +
        # netcanon.collectors.hostkey): tofu (default since v0.4.5) /
        # auto_add (legacy opt-out) / reject, driven by
        # Settings.ssh_host_key_checking.
        settings = self._effective_settings()
        apply_paramiko_policy(client, settings)

        logger.info("Connecting (Paramiko shell) to %s:%d", device.host, device.port)
        logger.debug(
            "SSH user for %s:%d: %s",
            device.host,
            device.port,
            device.credentials.username,
        )
        # CONC-8: connect + host-key persist live INSIDE the try so the
        # finally's client.close() also covers a connect/auth failure —
        # otherwise a failed connect propagated without closing the client,
        # leaking it (and its socket/Transport) on a repeatedly-unreachable
        # device.
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
            # TOFU: persist the (possibly newly-learned) host key for next time.
            persist_paramiko_host_keys(client, settings)

            shell = client.invoke_shell(width=220, height=50)
            time.sleep(2)
            initial = self._drain(shell)

            # OPNsense console menu — send "8" to enter shell
            if definition.connection.opnsense_shell_menu and (
                "8) Shell" in initial or "Enter an option:" in initial
            ):
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
            output = self._collect_output(
                shell, device.host,
                command=definition.commands.config,
            )

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
        # Same host-key policy as collect() — see module "Security model"
        # and netcanon.collectors.hostkey.
        settings = self._effective_settings()
        apply_paramiko_policy(client, settings)

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
            persist_paramiko_host_keys(client, settings)
        except Exception as exc:
            logger.warning(
                "Probe connect to %s failed: %s — continuing with "
                "family-base definition",
                device.host,
                exc,
            )
            client.close()  # CONC-8: don't leak the client on connect failure
            return {}

        try:
            shell = client.invoke_shell(width=220, height=50)
            time.sleep(2)
            initial = self._drain(shell)

            if definition.connection.opnsense_shell_menu and (
                "8) Shell" in initial or "Enter an option:" in initial
            ):
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
        except Exception as exc:
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

    def _collect_output(
        self,
        shell: paramiko.Channel,
        host: str,
        command: str | None = None,
    ) -> str:
        """Read config command output until idle for ``_IDLE_THRESHOLD`` polls.

        Uses the same two-phase strategy as the PowerShell script:

        1. Wait for output to *start* (first meaningful data).
        2. Once started, stop after ``_IDLE_THRESHOLD`` consecutive empty
           polls (approximately 3 seconds of silence).

        An absolute ``_MAX_SECONDS`` cap prevents hanging forever if a
        device produces a never-ending stream.  Hitting that cap while
        output is still arriving raises ``TimeoutError`` (fail closed)
        rather than returning the truncated buffer — a partial config
        must never be persisted as a successful backup (audit 276eaeb
        T0-3; the NetmikoCollector sibling fails closed the same way via
        its read timeout).

        If *command* is supplied, the accumulated buffer is post-
        processed to strip the echoed command from the head — PTY
        shells echo the keystrokes the caller sent (``cat
        /conf/config.xml\\n`` on OPNsense, for example) before the
        actual output starts.  Without this strip, downstream parsers
        see a literal command token as the first bytes of the file
        and reject it as malformed (the reported OPNsense parse
        regression).  NetmikoCollector gets this behaviour for free
        via Netmiko's ``strip_command=True``; the paramiko-shell
        strategy has to do it explicitly.

        Args:
            shell: Active Paramiko channel.
            host: Used only for log messages.
            command: The config command whose echo should be trimmed
                off the head of the buffer.  Pass ``None`` (or omit)
                to skip stripping.

        Returns:
            Accumulated raw output string, with any echoed command
            line removed from the head.

        Raises:
            TimeoutError: If no output at all arrives within
                ``_MAX_SECONDS``, or if output is still arriving when the
                ``_MAX_SECONDS`` cap is hit (the idle window was never
                reached, so the buffer would be truncated — fail closed
                rather than save a partial config).
        """
        buf = ""
        idle_count = 0
        started = False
        settled = False
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
                    settled = True
                    break

        if not buf:
            raise TimeoutError(
                f"No output received from {host} within {_MAX_SECONDS}s"
            )

        if not settled:
            # Fell through the absolute _MAX_SECONDS cap while the device
            # was still streaming — the idle window was never reached, so
            # the buffer is almost certainly truncated mid-config.  Fail
            # closed: a partial capture must surface as a failed backup,
            # never be saved as "success" (audit 276eaeb T0-3 — restores
            # parity with the read-timeout fail-closed NetmikoCollector).
            raise TimeoutError(
                f"Output from {host} never settled within {_MAX_SECONDS}s "
                f"({len(buf.splitlines())} lines captured, stream still "
                "active) — refusing to save a truncated backup"
            )

        if command:
            buf = _strip_command_echo(buf, command)

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
