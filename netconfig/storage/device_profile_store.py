"""
File-based device profile persistence.

Profiles are written as individual JSON files (one per profile) under
the ``devices/`` directory.  On startup the entire directory is scanned
and all valid records are loaded into the in-memory profile registry.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..models.device_profile import DeviceProfile

logger = logging.getLogger(__name__)


class FileDeviceProfileStore:
    """Persist and reload ``DeviceProfile`` objects as JSON files.

    Args:
        store_dir: Directory where device profile JSON files are stored.
            Created automatically if it does not exist.
    """

    def __init__(self, store_dir: Path) -> None:
        self._dir = store_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.debug("FileDeviceProfileStore initialised at %s", self._dir)

    def save(self, profile: DeviceProfile) -> None:
        """Write *profile* to ``{profile_id}.json`` (idempotent)."""
        path = self._dir / f"{profile.id}.json"
        path.write_text(profile.model_dump_json(), encoding="utf-8")
        logger.debug("Persisted device profile '%s'", profile.name)

    def delete(self, profile_id: str) -> None:
        """Remove the JSON file for *profile_id* if it exists (silent no-op if absent)."""
        path = self._dir / f"{profile_id}.json"
        if path.exists():
            path.unlink()
            logger.debug("Deleted device profile file %s.json", profile_id[:8])

    def load_all(self) -> dict[str, DeviceProfile]:
        """Load all device profile records from disk.

        Corrupt or unreadable files are logged and skipped.

        Returns:
            Mapping of profile ID → ``DeviceProfile``.
        """
        profiles: dict[str, DeviceProfile] = {}
        for path in self._dir.glob("*.json"):
            try:
                p = DeviceProfile.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                profiles[p.id] = p
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping corrupt device profile file %s: %s", path.name, exc
                )
        logger.info("Loaded %d device profile(s)", len(profiles))
        return profiles
