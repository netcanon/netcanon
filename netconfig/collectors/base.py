"""
Abstract collector base and strategy factory.

The ``get_collector`` factory is the single call site responsible for
mapping a definition's ``collector.strategy`` to a concrete implementation.
Import and call it from the backup route rather than instantiating
collectors directly — this keeps test mocking to a single patch target.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ..definitions.schema import DeviceDefinition
from ..models.device import DeviceTarget

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Abstract base class for SSH configuration collectors.

    All concrete collectors must implement ``collect``.  Implementations
    should raise informative exceptions on failure rather than returning
    empty strings — the backup runner catches ``Exception`` broadly and
    records the message in ``BackupResult.error``.

    Optional: subclasses MAY override :meth:`probe` to extract
    ``detected_facts`` (OS version, model) from a pre-backup "show
    version" style command.  The default implementation returns an
    empty dict — subclasses that don't support probing keep working
    unchanged, and the pipeline gracefully falls back to the
    family-base definition.
    """

    @abstractmethod
    def collect(self, device: DeviceTarget, definition: DeviceDefinition) -> str:
        """Connect to *device*, run the config command, and return raw output.

        The returned string is the *raw* captured output before any cleaning
        or normalisation.  The caller is responsible for post-processing if
        needed.

        Args:
            device: Connection target (host, port, credentials).
            definition: Loaded device definition carrying commands,
                connection flags, and collector config.

        Returns:
            Raw configuration text as a single string.

        Raises:
            Exception: Any exception from the underlying SSH library
                propagates up and is caught by the backup runner.
        """

    def probe(
        self, device: DeviceTarget, definition: DeviceDefinition
    ) -> dict[str, str]:
        """Run the definition's probe command against *device* and extract
        :attr:`DeviceProfile.detected_facts`.

        Default implementation returns an empty dict — subclasses that
        haven't wired probing support keep working unchanged (the
        pipeline treats an empty probe result as "no detected_facts
        available" and falls back to the family-base definition).

        Concrete subclasses that override this method should:

        * Return an empty dict when ``definition.probe.command`` is
          empty — no probe configured means no work to do.
        * Catch exceptions and return an empty dict rather than
          raising.  Probe failure is non-fatal; backup should
          proceed.  Errors should be logged at WARNING, not re-raised.
        * Parse the command's stdout via
          :func:`netconfig.collectors.probe.parse_probe_output` for
          regex handling + timestamp attachment.

        Cost note: this typically opens a second SSH session (first
        for probe, second for the main collect).  Acceptable for
        P1C3 — probe output is tiny, session setup is bounded by
        ``conn_timeout=30``, and the double-auth cost only affects
        definitions that opt in by declaring ``probe.command``.
        Single-session optimisation (probe inside the main session)
        is a future refinement.

        Args:
            device: Connection target.
            definition: Device definition supplying the probe
                command + regex map.  Only ``definition.probe`` is
                consulted; other fields are passed through in case
                future overrides need connection parameters.

        Returns:
            Dict of ``{fact_name: value}``.  Empty when probe isn't
            configured, the probe failed, or no regex matched.
        """
        return {}


def get_collector(definition: DeviceDefinition) -> BaseCollector:
    """Return the appropriate collector for *definition*'s strategy.

    This is the single factory for collector instantiation.  Mock
    *this function* in tests to avoid real SSH connections::

        monkeypatch.setattr("netconfig.api.routes.backups.get_collector",
                            lambda _: FakeCollector())

    Args:
        definition: Device definition whose ``collector.strategy`` field
            selects the implementation.

    Returns:
        A ready-to-use ``BaseCollector`` instance.

    Raises:
        ValueError: If ``collector.strategy`` is not a known value.
    """
    from .netmiko_collector import NetmikoCollector
    from .paramiko_collector import ParamikoShellCollector

    strategy = definition.collector.strategy
    if strategy == "netmiko":
        return NetmikoCollector()
    if strategy == "paramiko_shell":
        return ParamikoShellCollector()
    raise ValueError(
        f"Unknown collector strategy {strategy!r} in definition "
        f"'{definition.type_key}' ({definition.source_file})"
    )
