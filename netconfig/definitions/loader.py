"""
Definition file loader.

Scans a directory tree for ``*.yaml`` files, validates each against
``DeviceDefinition``, and exposes two lookup surfaces:

* :meth:`DefinitionLoader.load_all` — returns ``dict[type_key,
  DeviceDefinition]`` containing only **family-base** definitions
  (``os_version is None`` AND ``model is None``).  This is the legacy
  surface; existing callers (backup collectors, etc.) use this as they
  always have.

* :meth:`DefinitionLoader.resolve` — longest-match lookup that can
  return either a family base or a version/model-specific overlay.
  Callers aware of the ``(type_key, os_version, model)`` triple call
  this instead of the legacy map.

Override resolution (within the family-base set)
------------------------------------------------
When multiple family-base files share the same ``type_key``, the file
with the highest ``priority`` value wins.  Overlays — files with
``os_version`` or ``model`` set — do NOT participate in this override
mechanism; they live in a parallel variant registry.

Longest-match resolution (overlays)
-----------------------------------
:meth:`resolve` picks the most-specific matching definition:

1. ``(type_key == T, os_version == V, model == M)`` — exact triple.
2. ``(type_key == T, os_version == V, model is None)`` — version pin
   with model wildcard.
3. ``(type_key == T, os_version is None, model == M)`` — model pin
   with version wildcard (rare).
4. ``(type_key == T, os_version is None, model is None)`` — family
   base.

Example tree::

    definitions/
      cisco/ios-xe/17.x.yaml    # family base (os_version=None)
      cisco/ios-xe/17.12.yaml   # overlay (os_version="17.12")

    loader.resolve("Cisco")                  → 17.x.yaml (family base)
    loader.resolve("Cisco", os_version="17.9")  → 17.x.yaml (no exact match)
    loader.resolve("Cisco", os_version="17.12") → 17.12.yaml (overlay)

Usage::

    loader = DefinitionLoader(Path("definitions"))
    base_map = loader.load_all()                          # legacy map
    definition = loader.resolve("Cisco", os_version="17.12")  # overlay-aware
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
        self._variants: list[DeviceDefinition] = []

    def load_all(self) -> dict[str, DeviceDefinition]:
        """Scan the definition tree and return all family-base definitions.

        **Overlays** (definitions with ``os_version`` or ``model``
        set) are NOT included in the returned map — they live in the
        variant registry and are accessible via :meth:`resolve`.
        This keeps backwards compatibility with callers that treat
        ``load_all()`` as "one entry per type_key".

        Files are parsed in two passes:

        1. All files are read and validated against ``DeviceDefinition``.
           Failures emit a ``WARNING`` log and are skipped.
        2. Valid family-base definitions are sorted by ``priority``
           (ascending) and applied in order.  Later entries overwrite
           earlier ones on the same ``type_key``, so higher-priority
           files always win.  Overlays are appended to the variant
           registry without priority-based overriding.

        Returns:
            Mapping of ``type_key`` → family-base ``DeviceDefinition``
            for every successfully loaded base definition.

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

        # Pass 1 — parse and validate, collecting all valid definitions
        # into the variant registry (overlays + family-base alike).
        self._variants = []
        for path in yaml_files:
            definition = self._load_file(path)
            if definition is not None:
                self._variants.append(definition)

        if not self._variants:
            raise RuntimeError(
                f"No valid definitions loaded from: {self._dir.resolve()}"
            )

        # Pass 2 — build the legacy family-base-only map with priority
        # override semantics.  Overlays are excluded so they don't
        # collide with their family base on the same type_key.
        base_candidates: list[tuple[int, DeviceDefinition]] = [
            (d.priority, d)
            for d in self._variants
            if d.os_version is None and d.model is None
        ]

        profiles: dict[str, DeviceDefinition] = {}
        for _, definition in sorted(base_candidates, key=lambda t: t[0]):
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

        overlay_count = sum(
            1 for d in self._variants
            if d.os_version is not None or d.model is not None
        )
        logger.info(
            "Loaded %d device definition(s) from %s (%d base + %d overlay)",
            len(self._variants),
            self._dir,
            len(profiles),
            overlay_count,
        )
        return profiles

    def resolve(
        self,
        type_key: str,
        os_version: str | None = None,
        model: str | None = None,
    ) -> DeviceDefinition | None:
        """Longest-match lookup over the full variant registry.

        Returns the most-specific matching definition for the given
        ``(type_key, os_version, model)`` triple.  Specificity order:

        1. Exact triple match.
        2. Version pin with model wildcard (``os_version == V,
           model is None``).
        3. Model pin with version wildcard (``os_version is None,
           model == M``) — rare.
        4. Family base (``os_version is None, model is None``).

        At most one definition per specificity tier can match after
        priority-based overriding, so the result is deterministic.

        Args:
            type_key: The ``type_key`` declared in the definition YAML.
            os_version: Operator-pinned OS version, or ``None``.
            model: Operator-pinned hardware model, or ``None``.

        Returns:
            The most-specific matching ``DeviceDefinition``, or
            ``None`` when no family-base nor overlay matches the
            ``type_key``.  Callers should treat ``None`` as an
            unknown-device error.
        """
        if not self._variants:
            # load_all hasn't run yet — nothing to resolve.
            return None

        candidates = [d for d in self._variants if d.type_key == type_key]
        if not candidates:
            return None

        # Tier 1 — exact triple match.
        if os_version is not None and model is not None:
            hit = _highest_priority(
                c for c in candidates
                if c.os_version == os_version and c.model == model
            )
            if hit is not None:
                return hit

        # Tier 2 — os_version pin, model wildcard.
        if os_version is not None:
            hit = _highest_priority(
                c for c in candidates
                if c.os_version == os_version and c.model is None
            )
            if hit is not None:
                return hit

        # Tier 3 — model pin, os_version wildcard.
        if model is not None:
            hit = _highest_priority(
                c for c in candidates
                if c.os_version is None and c.model == model
            )
            if hit is not None:
                return hit

        # Tier 4 — family base.
        return _highest_priority(
            c for c in candidates
            if c.os_version is None and c.model is None
        )

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


def _highest_priority(
    defs,
) -> DeviceDefinition | None:
    """Return the highest-priority definition from an iterable, or None."""
    materialised = list(defs)
    if not materialised:
        return None
    return max(materialised, key=lambda d: d.priority)
