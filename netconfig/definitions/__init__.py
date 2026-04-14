"""
Device definition loading and schema validation.

A *device definition* is a YAML file that describes everything needed to
connect to a particular vendor/OS/version combination and retrieve its
running configuration.  The loader assembles these files into a
``dict[type_key, DeviceDefinition]`` that drives both the collection engine
and the web UI.

See ``definitions/README.md`` for the file format and extension guide.
"""

from .loader import DefinitionLoader
from .schema import (
    CollectorConfig,
    CommandConfig,
    ConnectionConfig,
    DeviceDefinition,
    PromptConfig,
)

__all__ = [
    "CollectorConfig",
    "CommandConfig",
    "ConnectionConfig",
    "DefinitionLoader",
    "DeviceDefinition",
    "PromptConfig",
]
