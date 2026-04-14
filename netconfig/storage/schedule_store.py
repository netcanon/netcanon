"""
File-based backup schedule persistence.

Schedules are written as individual JSON files (one per schedule) under
the ``schedules/`` directory.  On startup the entire directory is scanned
and enabled schedules are re-registered with APScheduler.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..models.schedule import BackupSchedule

logger = logging.getLogger(__name__)


class FileScheduleStore:
    """Persist and reload ``BackupSchedule`` objects as JSON files.

    Args:
        schedules_dir: Directory where schedule JSON files are stored.
            Created automatically if it does not exist.
    """

    def __init__(self, schedules_dir: Path) -> None:
        self._dir = schedules_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.debug("FileScheduleStore initialised at %s", self._dir)

    def save(self, schedule: BackupSchedule) -> None:
        """Write *schedule* to ``{schedule_id}.json`` (idempotent)."""
        path = self._dir / f"{schedule.id}.json"
        path.write_text(schedule.model_dump_json(), encoding="utf-8")
        logger.debug("Persisted schedule '%s'", schedule.name)

    def delete(self, schedule_id: str) -> None:
        """Remove the JSON file for *schedule_id* if it exists."""
        path = self._dir / f"{schedule_id}.json"
        if path.exists():
            path.unlink()
            logger.debug("Deleted schedule file %s.json", schedule_id[:8])

    def load_all(self) -> dict[str, BackupSchedule]:
        """Load all schedule records from disk.

        Corrupt or unreadable files are logged and skipped.

        Returns:
            Mapping of schedule ID → ``BackupSchedule``.
        """
        schedules: dict[str, BackupSchedule] = {}
        for path in self._dir.glob("*.json"):
            try:
                s = BackupSchedule.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                schedules[s.id] = s
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping corrupt schedule file %s: %s", path.name, exc
                )
        logger.info("Loaded %d schedule(s)", len(schedules))
        return schedules
