"""
File-based backup schedule persistence.

Schedules are written as individual JSON files (one per schedule) under
the ``schedules/`` directory.  On startup the entire directory is scanned
and enabled schedules are re-registered with APScheduler.

Credentials inside legacy inline ``devices`` lists (``ScheduleDevice.password``
and ``enable_password``) are **encrypted at rest** using Fernet symmetric
encryption via :mod:`netconfig.security.credentials`.  New-style schedules
reference device profile IDs and carry no credentials of their own.

On first load after upgrading from an unencrypted version, plaintext
credentials in existing schedule files are transparently migrated.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..models.schedule import BackupSchedule
from ..security.credentials import decrypt_field, encrypt

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
        """Write *schedule* to ``{schedule_id}.json``.

        Credentials in the legacy inline ``devices`` list are encrypted
        before writing.
        """
        data = json.loads(schedule.model_dump_json())
        for dev in data.get("devices", []):
            if dev.get("password"):
                dev["password"] = encrypt(dev["password"])
            if dev.get("enable_password"):
                dev["enable_password"] = encrypt(dev["enable_password"])
        path = self._dir / f"{schedule.id}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        logger.debug("Persisted schedule '%s'", schedule.name)

    def delete(self, schedule_id: str) -> None:
        """Remove the JSON file for *schedule_id* if it exists."""
        path = self._dir / f"{schedule_id}.json"
        if path.exists():
            path.unlink()
            logger.debug("Deleted schedule file %s.json", schedule_id[:8])

    def load_all(self) -> dict[str, BackupSchedule]:
        """Load all schedule records from disk.

        Credentials in legacy inline device lists are decrypted on load.
        Plaintext values (pre-encryption migration) are detected and the
        file is immediately re-saved with encryption applied.

        Corrupt or unreadable files are logged and skipped.

        Returns:
            Mapping of schedule ID → ``BackupSchedule``.
        """
        schedules: dict[str, BackupSchedule] = {}
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))

                needs_resave = False
                for dev in data.get("devices", []):
                    if dev.get("password"):
                        plain, was_enc = decrypt_field(dev["password"])
                        dev["password"] = plain
                        if not was_enc:
                            needs_resave = True
                    if dev.get("enable_password"):
                        plain, was_enc = decrypt_field(dev["enable_password"])
                        dev["enable_password"] = plain
                        if not was_enc:
                            needs_resave = True

                s = BackupSchedule.model_validate(data)

                if needs_resave:
                    self.save(s)
                    logger.info(
                        "Migrated plaintext credentials in schedule '%s' to encrypted storage",
                        s.name,
                    )

                schedules[s.id] = s
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping corrupt schedule file %s: %s", path.name, exc
                )
        logger.info("Loaded %d schedule(s)", len(schedules))
        return schedules
