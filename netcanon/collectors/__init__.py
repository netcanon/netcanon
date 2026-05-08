"""
SSH collection strategies.

``get_collector`` is the primary entry point — it reads ``definition.collector.strategy``
and returns the appropriate ``BaseCollector`` subclass.

Adding a new strategy
---------------------
1. Create ``netcanon/collectors/my_strategy.py`` with a class that
   subclasses ``BaseCollector`` and implements ``collect()``.
2. Register it in ``get_collector`` (``base.py``).
3. Add ``strategy: "my_strategy"`` to any definition YAML that needs it.
4. Document the strategy in ``collectors/README.md``.
"""

from .base import BaseCollector, get_collector
from .netmiko_collector import NetmikoCollector
from .paramiko_collector import ParamikoShellCollector

__all__ = [
    "BaseCollector",
    "get_collector",
    "NetmikoCollector",
    "ParamikoShellCollector",
]
