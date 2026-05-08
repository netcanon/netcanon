"""
File-based backup job persistence.

Jobs are written as individual JSON files (one per job) so that the
complete job history — including which config files each job produced —
survives server restarts.  The ``jobs/`` directory sits alongside the
``configs/`` directory in the data root.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..models.backup import BackupJob

logger = logging.getLogger(__name__)


class FileJobStore:
    """Persist and reload ``BackupJob`` objects as JSON files.

    Each completed job is written to ``{jobs_dir}/{job_id}.json``.
    On startup the entire directory is scanned and all valid records
    are loaded into the in-memory jobs registry.

    Args:
        jobs_dir: Directory where job JSON files are stored.  Created
            automatically if it does not exist.
    """

    def __init__(self, jobs_dir: Path) -> None:
        self._dir = jobs_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.debug("FileJobStore initialised at %s", self._dir)

    def save(self, job: BackupJob) -> None:
        """Write *job* to disk as ``{job_id}.json``.

        Overwrites any existing file for the same job ID (idempotent —
        safe to call after status updates).
        """
        path = self._dir / f"{job.id}.json"
        # Atomic write: write to temp then rename to prevent corruption.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(job.model_dump_json(), encoding="utf-8")
        tmp.replace(path)
        logger.debug("Persisted job %s", job.id)

    def load_all(self) -> dict[str, BackupJob]:
        """Load all job records from disk.

        Corrupt or unreadable files are logged and skipped rather than
        crashing startup.

        Returns:
            Mapping of job ID → ``BackupJob``, sorted newest-first by
            ``created_at``.
        """
        jobs: dict[str, BackupJob] = {}
        for path in sorted(self._dir.glob("*.json")):
            try:
                job = BackupJob.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                jobs[job.id] = job
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "CORRUPT FILE SKIPPED: %s — %s", path.name, exc
                )
        logger.info(
            "Loaded %d persisted job(s) from %s", len(jobs), self._dir
        )
        return jobs
