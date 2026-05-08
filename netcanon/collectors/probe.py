"""
Pure-function probe-output parser.

The probe phase runs BEFORE the main backup-config command and
extracts ``detected_facts`` (OS version, hardware model, firmware
build, etc.) from a vendor-specific "show version" style command's
stdout.  The parser lives here as a pure function so it can be
unit-tested against canned fixtures without any SSH / Netmiko /
Paramiko dependency.

The I/O side of the probe (opening a session, actually running the
command) lives on the collectors — see
:meth:`netcanon.collectors.base.BaseCollector.probe`.  That method
calls :func:`parse_probe_output` internally; callers that want to
exercise the regex logic in isolation (tests, offline tools) can
import this module directly.

Design:

* Regex patterns come from the definition's ``probe.patterns`` map.
* First capture group of each regex becomes the fact value.
* Patterns that don't match are silently skipped — probe is best-
  effort, not a hard dependency.
* Always returns a plain ``dict[str, str]`` so callers can serialise
  it directly onto :attr:`DeviceProfile.detected_facts`.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from ..definitions.schema import ProbeConfig

logger = logging.getLogger(__name__)


#: Timestamp field added to every successful probe so the UI can show
#: operators how stale the detected_facts are.  Key name is stable —
#: documented on ``DeviceProfile.detected_facts`` attribute.
PROBE_TIMESTAMP_KEY = "probe_timestamp"


def parse_probe_output(
    output: str,
    probe_config: ProbeConfig,
) -> dict[str, str]:
    """Extract detected facts from *output* using *probe_config*'s regex map.

    For each ``(fact_name, pattern)`` in ``probe_config.patterns``:

    * Compile the pattern with :data:`re.MULTILINE` so ``^`` / ``$``
      anchor per-line (show-version output is invariably multi-line).
    * Search for the first match.
    * If matched, the first capture group becomes the fact value;
      leading/trailing whitespace is stripped.
    * Pattern compile errors are logged and the pattern is skipped —
      a malformed regex in one fact should not block the others.

    A ``probe_timestamp`` field is always added on non-empty results
    so the UI can age-out stale facts.  Skipped when the parsed dict
    is empty (no regexes matched) — an empty fact dict shouldn't look
    like a successful probe.

    Args:
        output: Raw stdout from the probe command.
        probe_config: Definition's probe configuration.

    Returns:
        Dict of ``{fact_name: value}``.  Empty dict when probe
        wasn't configured (no command / no patterns) or when no
        patterns matched.
    """
    if not probe_config.patterns:
        return {}

    results: dict[str, str] = {}
    for fact_name, pattern in probe_config.patterns.items():
        try:
            compiled = re.compile(pattern, re.MULTILINE)
        except re.error as exc:
            logger.warning(
                "probe: pattern for fact %r failed to compile: %s",
                fact_name,
                exc,
            )
            continue
        match = compiled.search(output)
        if match is None:
            continue
        if match.groups():
            value = match.group(1).strip()
        else:
            # Regex without a capture group — take the whole match.
            value = match.group(0).strip()
        if value:
            results[fact_name] = value

    # Attach a timestamp only on successful extractions so an empty
    # result doesn't masquerade as "probe ran and found nothing".
    if results:
        results[PROBE_TIMESTAMP_KEY] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )

    return results
