"""
Definition file loader.

Scans a directory tree for ``*.yaml`` files, validates each against
``DeviceDefinition``, and returns a ``dict[type_key, DeviceDefinition]``.

Override resolution
-------------------
When multiple files share the same ``type_key``, the file with the
highest ``priority`` value wins.  Files with equal priority are processed
in lexicographic path order, so deeper (more specific) paths win ties by
convention — but explicitly setting ``priority`` is more reliable and
self-documenting.

Example tree::

    definitions/
      cisco/ios-xe/base.yaml          # priority: 0  → loaded first, wins for most
      cisco/ios-xe/17.x.yaml          # priority: 10 → overrides base for IOS-XE 17
      cisco/ios-xe/models/ASR1K.yaml  # priority: 20 → overrides both for ASR1000

Usage::

    loader = DefinitionLoader(Path("definitions"))
    profiles = loader.load_all()   # dict[str, DeviceDefinition]
"""

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import DeviceDefinition

logger = logging.getLogger(__name__)


class DefinitionLoader:
    """Loads and validates device definitions from a YAML file tree.

    Args:
        definitions_dir: Root of the definition tree.  All ``*.yaml``
            files found recursively are candidates for loading.

    Raises:
        FileNotFoundError: If ``definitions_dir`` does not exist.
        RuntimeError: If no valid definitions are found after scanning.
    """

    def __init__(self, definitions_dir: Path) -> None:
        self._dir = Path(definitions_dir)

    def load_all(self) -> dict[str, DeviceDefinition]:
        """Scan the definition tree and return all valid definitions.

        Files are parsed in two passes:

        1. All files are read and validated against ``DeviceDefinition``.
           Failures emit a ``WARNING`` log and are skipped.
        2. Valid definitions are sorted by ``priority`` (ascending) and
           applied in order.  Later entries overwrite earlier ones on the
           same ``type_key``, so higher-priority files always win.

        Returns:
            Mapping of ``type_key`` → ``DeviceDefinition`` for every
            successfully loaded definition.

        Raises:
            FileNotFoundError: If the definitions directory does not exist.
            RuntimeError: If the directory exists but contains no valid
                ``*.yaml`` files.
        """
        if not self._dir.exists():
            raise FileNotFoundError(
                f"Definitions directory not found: {self._dir.resolve()}"
            )

        yaml_files = sorted(self._dir.rglob("*.yaml"))
        if not yaml_files:
            raise RuntimeError(
                f"No *.yaml definition files found under: {self._dir.resolve()}"
            )

        # Pass 1 — parse and validate, collecting (priority, definition) pairs
        candidates: list[tuple[int, DeviceDefinition]] = []
        for path in yaml_files:
            definition = self._load_file(path)
            if definition is not None:
                candidates.append((definition.priority, definition))

        if not candidates:
            raise RuntimeError(
                f"No valid definitions loaded from: {self._dir.resolve()}"
            )

        # Pass 2 — apply in ascending priority order (higher wins by being last)
        profiles: dict[str, DeviceDefinition] = {}
        for _, definition in sorted(candidates, key=lambda t: t[0]):
            if definition.type_key in profiles:
                logger.debug(
                    "Definition '%s' overridden by priority-%d file: %s",
                    definition.type_key,
                    definition.priority,
                    definition.source_file,
                )
            profiles[definition.type_key] = definition
            logger.debug(
                "Loaded definition '%s' (priority %d) from %s",
                definition.type_key,
                definition.priority,
                definition.source_file,
            )

        logger.info(
            "Loaded %d device definition(s) from %s",
            len(profiles),
            self._dir,
        )
        return profiles

    def _load_file(self, path: Path) -> DeviceDefinition | None:
        """Parse and validate a single YAML file.

        Args:
            path: Absolute path to the YAML file.

        Returns:
            A validated ``DeviceDefinition`` with ``source_file`` set, or
            ``None`` if parsing or validation fails.
        """
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            logger.warning("YAML parse error in %s: %s", path, exc)
            return None

        if not isinstance(raw, dict):
            logger.warning("Skipping %s: expected a YAML mapping at top level", path)
            return None

        try:
            definition = DeviceDefinition.model_validate(raw)
        except ValidationError as exc:
            logger.warning("Validation error in %s:\n%s", path, exc)
            return None

        definition.source_file = path
        return definition
