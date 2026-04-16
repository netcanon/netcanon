"""
File-based device profile persistence.

Profiles are written as individual JSON files (one per profile) under
the ``devices/`` directory.  On startup the entire directory is scanned
and all valid records are loaded into the in-memory profile registry.

Credentials (``password`` and ``enable_password``) are **encrypted at rest**
using Fernet symmetric encryption via :mod:`netconfig.security.credentials`.
The in-memory ``DeviceProfile`` objects always contain plaintext values —
encryption/decryption is handled entirely in this module.

On first load after upgrading from an unencrypted version, any field that
fails Fernet decryption is assumed to be a legacy plaintext value and is
transparently migrated: the file is re-saved with encrypted credentials.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..models.device_profile import DeviceProfile
from ..security.credentials import encrypt
from ..security.migration import migrate_credential_fields

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
        """Write *profile* to ``{profile_id}.json`` with credentials encrypted."""
        # model_dump_json handles datetime/UUID serialisation correctly.
        data = json.loads(profile.model_dump_json())
        data["password"] = encrypt(profile.password)
        if profile.enable_password is not None:
            data["enable_password"] = encrypt(profile.enable_password)
        path = self._dir / f"{profile.id}.json"
        # Atomic write: write to temp then rename to prevent corruption.
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            logger.error("Failed to persist device profile '%s': %s", profile.name, exc)
            raise
        logger.debug("Persisted device profile '%s' (credentials encrypted)", profile.name)

    def delete(self, profile_id: str) -> None:
        """Remove the JSON file for *profile_id* if it exists (silent no-op if absent)."""
        path = self._dir / f"{profile_id}.json"
        if path.exists():
            path.unlink()
            logger.debug("Deleted device profile file %s.json", profile_id[:8])

    def load_all(self) -> dict[str, DeviceProfile]:
        """Load all device profile records from disk.

        Credentials are decrypted on load.  Legacy plaintext credentials
        (from files written before encryption was introduced) are detected
        via ``decrypt_field()`` and the file is immediately re-saved with
        encryption applied.

        Corrupt or unreadable files are logged and skipped.

        Returns:
            Mapping of profile ID → ``DeviceProfile``.
        """
        profiles: dict[str, DeviceProfile] = {}
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))

                # Decrypt credentials; detect & migrate legacy plaintext.
                needs_resave = migrate_credential_fields(
                    data, ["password", "enable_password"]
                )

                p = DeviceProfile.model_validate(data)

                if needs_resave:
                    self.save(p)
                    logger.info(
                        "Migrated plaintext credentials for profile '%s' (id=%s) to encrypted storage",
                        p.name,
                        p.id[:8],
                    )

                profiles[p.id] = p
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "CORRUPT FILE SKIPPED: %s — %s", path.name, exc
                )
        logger.info("Loaded %d device profile(s)", len(profiles))
        return profiles
