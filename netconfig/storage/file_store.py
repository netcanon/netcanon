"""
File-based configuration storage.

Configurations are saved as plain text files under a configurable
directory.  Filenames encode all metadata using the convention::

    {DeviceType}_{Host}_{YYYYMMDD_HHmmss}.{ext}

e.g. ``Cisco_192-168-1-1_20260414_120000.cfg``

Dots and colons in host addresses are replaced with hyphens so filenames
are safe on all platforms.  The metadata fields (device type, host,
timestamp) are recovered by parsing the filename, making the directory
self-describing without a sidecar database.
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from ..models.backup import ConfigRecord
from .base import BaseConfigStore

logger = logging.getLogger(__name__)

# Regex to parse filenames produced by this store.
# Groups: device_type, safe_host, timestamp_str, extension
_FILENAME_RE = re.compile(
    r"^(?P<device_type>.+?)_(?P<safe_host>[^_]+(?:_[^_]+)*)_"
    r"(?P<ts>\d{8}_\d{6})\.(?P<ext>[^.]+)$"
)
_TS_FORMAT = "%Y%m%d_%H%M%S"


class FileConfigStore(BaseConfigStore):
    """Stores configuration files in a local directory.

    Args:
        storage_dir: Directory to read and write configuration files.
            Created automatically if it does not exist.

    Raises:
        OSError: If the directory cannot be created.
    """

    def __init__(self, storage_dir: Path) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # BaseConfigStore interface
    # ------------------------------------------------------------------

    def save(
        self,
        device_type: str,
        host: str,
        timestamp: datetime,
        extension: str,
        content: str,
    ) -> ConfigRecord:
        """Write *content* to disk and return its ``ConfigRecord``.

        Dots and colons in *host* are replaced with hyphens to keep the
        filename safe across platforms (IPv6 addresses contain colons).
        """
        safe_host = re.sub(r"[.:]", "-", host)
        ts_str = timestamp.strftime(_TS_FORMAT)
        filename = f"{device_type}_{safe_host}_{ts_str}.{extension}"
        path = self._dir / filename
        path.write_text(content, encoding="utf-8")
        size = path.stat().st_size
        logger.info("Saved config %r (%d bytes) → %s", filename, size, self._dir)
        return ConfigRecord(
            device_type=device_type,
            host=host,
            timestamp=timestamp,
            filename=filename,
            file_extension=extension,
            size_bytes=size,
        )

    def list_configs(self) -> list[ConfigRecord]:
        """Return metadata for all config files, sorted newest-first.

        Files whose names do not match the expected pattern are silently
        skipped (e.g. log files, temp files).
        """
        records: list[ConfigRecord] = []
        for path in self._dir.iterdir():
            record = self._parse_filename(path)
            if record is not None:
                records.append(record)
        records.sort(key=lambda r: r.timestamp, reverse=True)
        logger.debug("Listed %d config(s) from %s", len(records), self._dir)
        return records

    def get_content(self, filename: str) -> str:
        """Return the text of a stored config file.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        path = self._dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {filename!r}")
        return path.read_text(encoding="utf-8")

    def delete(self, filename: str) -> None:
        """Delete a stored config file.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        path = self._dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {filename!r}")
        path.unlink()
        logger.info("Deleted config %r from %s", filename, self._dir)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_filename(self, path: Path) -> ConfigRecord | None:
        """Attempt to reconstruct a ``ConfigRecord`` from a filename.

        Returns ``None`` for files that do not match the expected pattern.
        """
        m = _FILENAME_RE.match(path.name)
        if not m:
            return None
        try:
            timestamp = datetime.strptime(m.group("ts"), _TS_FORMAT).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return None
        safe_host = m.group("safe_host")
        host = safe_host.replace("-", ".")  # best-effort reconstruction
        return ConfigRecord(
            device_type=m.group("device_type"),
            host=host,
            timestamp=timestamp,
            filename=path.name,
            file_extension=m.group("ext"),
            size_bytes=path.stat().st_size,
        )
