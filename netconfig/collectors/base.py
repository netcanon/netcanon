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
