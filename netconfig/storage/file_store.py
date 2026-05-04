"""
File-based configuration storage.

Configurations are saved as plain text files under a configurable directory,
organised into ``{DeviceType}/{safe_host}/`` subdirectories::

    configs/
      Cisco/
        192-168-1-1/
          Cisco_192-168-1-1_20260414_120000.cfg
      OPNsense/
        192-168-1-254/
          OPNsense_192-168-1-254_20260414_120001.xml

Filenames encode all metadata using the convention::

    {DeviceType}_{safe_host}_{YYYYMMDD_HHmmss}.{ext}

e.g. ``Cisco_192-168-1-1_20260414_120000.cfg``

Dots and colons in host addresses are replaced with hyphens so filenames are
safe on all platforms.  The metadata fields (device type, host, timestamp) are
recovered by parsing the filename, making the directory self-describing without
a sidecar database.

**Startup migration**: any files found directly in ``storage_dir`` (flat layout
from older versions) are automatically moved into the appropriate subdirectory
on first instantiation.

**Collision safety**: if two backups of the same device complete within the same
second a numeric suffix is appended (``…_1.cfg``, ``…_2.cfg``, …) so no file
is ever silently overwritten.
"""

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..models.backup import ConfigRecord
from .base import BaseConfigStore

logger = logging.getLogger(__name__)

# Regex to parse filenames produced by this store.
# Groups: device_type, safe_host, ts, optional collision counter n, extension.
#
# **Invariant:** ``device_type`` MUST NOT contain ``_`` and MUST NOT
# contain ``.``.  The filename grammar uses ``_`` as the separator
# between ``device_type``, ``safe_host``, and the timestamp segments,
# so an underscore inside ``device_type`` makes the boundary
# mathematically ambiguous (the lazy ``.+?`` would absorb only the
# leading token, mis-locating the file).  A dot inside ``device_type``
# would collide with the extension separator.  Both classes are
# rejected by ``DeviceDefinition.type_key_filename_safe`` at definition
# load time, so by the time a value reaches this regex it is
# guaranteed safe.  Established convention: a single-token CamelCase
# vendor key (``Cisco``, ``Fortigate``, ``MikroTik``, ``OPNsense``,
# ``Aruba``, ``Juniper``, ``Arista``).
_FILENAME_RE = re.compile(
    r"^(?P<device_type>[^_.]+)_(?P<safe_host>[^_]+(?:_[^_]+)*)_"
    r"(?P<ts>\d{8}_\d{6})(?:_(?P<n>\d+))?\.(?P<ext>[^.]+)$"
)
_TS_FORMAT = "%Y%m%d_%H%M%S"


class FileConfigStore(BaseConfigStore):
    """Stores configuration files in a local directory tree.

    Args:
        storage_dir: Root directory for all configuration files.
            Created automatically if it does not exist.  On first use any
            flat files left by older versions are migrated to subdirectories.

    Raises:
        OSError: If the directory cannot be created.
    """

    def __init__(self, storage_dir: Path) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._migrate_flat_files()

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
        device_profile_id: str | None = None,
    ) -> ConfigRecord:
        """Write *content* to ``{device_type}/{safe_host}/`` and return its record.

        Dots and colons in *host* are replaced with hyphens to keep the
        filename safe across platforms (IPv6 addresses contain colons).

        If a file with the same name already exists (two backups within the
        same second), a numeric suffix is appended so no file is overwritten.

        If *device_profile_id* is not ``None``, a sidecar
        ``{filename}.meta.json`` is written alongside the config file
        containing ``{"device_profile_id": "..."}``.
        """
        # Encode dots as single hyphens, colons (IPv6) as double hyphens
        # so the reconstruction in _parse_filename is lossless.
        MAX_CONFIG_SIZE = 50 * 1024 * 1024  # 50 MB
        if len(content) > MAX_CONFIG_SIZE:
            raise ValueError(
                f"Config content exceeds max size "
                f"({len(content):,} bytes > {MAX_CONFIG_SIZE:,} bytes)"
            )
        safe_host = host.replace(":", "--").replace(".", "-")
        ts_str = timestamp.strftime(_TS_FORMAT)
        stem = f"{device_type}_{safe_host}_{ts_str}"
        filename = f"{stem}.{extension}"

        subdir = self._dir / device_type / safe_host
        subdir.mkdir(parents=True, exist_ok=True)
        path = subdir / filename

        # Collision safety — append _1, _2, … if the same-second file exists.
        counter = 0
        while path.exists():
            counter += 1
            filename = f"{stem}_{counter}.{extension}"
            path = subdir / filename
            logger.warning(
                "Filename collision: renamed to %r (counter=%d)", filename, counter
            )

        # Atomic write: write to temp then rename to prevent corruption.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
        size = path.stat().st_size
        logger.info("Saved config %r (%d bytes) → %s", filename, size, subdir)

        if device_profile_id is not None:
            meta_path = subdir / f"{filename}.meta.json"
            meta_tmp = meta_path.with_suffix(".tmp")
            meta_tmp.write_text(
                json.dumps({"device_profile_id": device_profile_id}),
                encoding="utf-8",
            )
            meta_tmp.replace(meta_path)
            logger.debug("Wrote sidecar metadata %s", meta_path.name)

        return ConfigRecord(
            device_type=device_type,
            host=host,
            timestamp=timestamp,
            filename=filename,
            file_extension=extension,
            size_bytes=size,
            device_profile_id=device_profile_id,
        )

    def list_configs(self) -> list[ConfigRecord]:
        """Return metadata for all config files, sorted newest-first.

        Walks the full directory tree so both subdirectory-organised files and
        any remaining flat files are returned.  Non-matching files (log files,
        temp files, sidecar ``.meta.json`` files, etc.) are silently skipped.

        For each config file, if a sidecar ``{filename}.meta.json`` exists
        alongside it, the ``device_profile_id`` is read from it and set on
        the returned record.
        """
        records: list[ConfigRecord] = []
        for path in self._dir.rglob("*"):
            if path.is_file():
                record = self._parse_filename(path)
                if record is not None:
                    meta_path = path.parent / f"{path.name}.meta.json"
                    if meta_path.exists():
                        try:
                            meta = json.loads(meta_path.read_text(encoding="utf-8"))
                            record.device_profile_id = meta.get("device_profile_id")
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                "Could not read sidecar metadata %s", meta_path.name,
                                exc_info=True,
                            )
                    records.append(record)
        records.sort(key=lambda r: r.timestamp, reverse=True)
        logger.debug("Listed %d config(s) from %s", len(records), self._dir)
        return records

    def get_content(self, filename: str) -> str:
        """Return the text of a stored config file.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        return self.resolve_path(filename).read_text(encoding="utf-8")

    def delete(self, filename: str) -> None:
        """Delete a stored config file.

        Also removes the sidecar ``{filename}.meta.json`` if it exists
        (no error if the sidecar is absent).

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        path = self.resolve_path(filename)
        # Delete sidecar first so it isn't orphaned if main file delete fails.
        meta_path = path.parent / f"{path.name}.meta.json"
        if meta_path.exists():
            meta_path.unlink()
            logger.debug("Deleted sidecar metadata %s", meta_path.name)
        path.unlink()
        logger.info("Deleted config %r from %s", filename, path.parent)

    def resolve_path(self, filename: str) -> Path:
        """Return the absolute filesystem path for *filename*.

        Only accepts filenames that match the expected naming convention
        (path-traversal protection: any name containing ``..`` or path
        separators will not match the regex and is rejected).

        Checks the canonical ``{device_type}/{safe_host}/{filename}`` location
        first, then falls back to a flat file at the storage root for files
        that pre-date the subdirectory migration.  Both resolved paths are
        verified to lie inside the storage root (defence-in-depth against
        symlink attacks).

        Raises:
            FileNotFoundError: If the filename does not match the expected
                pattern, or if the file is not found in either location.
        """
        m = _FILENAME_RE.match(filename)
        if not m:
            raise FileNotFoundError(f"Config not found: {filename!r}")

        storage_root = self._dir.resolve()

        candidate = (
            self._dir / m.group("device_type") / m.group("safe_host") / filename
        )
        if candidate.resolve().is_relative_to(storage_root) and candidate.exists():
            return candidate

        # Flat fallback for pre-migration files (same regex guard applies).
        flat = self._dir / filename
        if flat.resolve().is_relative_to(storage_root) and flat.exists():
            return flat

        raise FileNotFoundError(f"Config not found: {filename!r}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _migrate_flat_files(self) -> None:
        """Move flat files in the storage root into subdirectories.

        Called once at construction time.  Files that cannot be parsed (e.g.
        log files, README) are left in place.  Errors on individual files are
        logged and skipped so a single bad file cannot block startup.
        """
        moved = 0
        for path in list(self._dir.iterdir()):
            if not path.is_file():
                continue
            m = _FILENAME_RE.match(path.name)
            if not m:
                continue  # not a config file — leave untouched
            dest_dir = self._dir / m.group("device_type") / m.group("safe_host")
            dest = dest_dir / path.name
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(dest))
                moved += 1
                logger.debug("Migrated %r → %s", path.name, dest_dir)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Could not migrate %r to subdirectory", path.name, exc_info=True
                )
        if moved:
            logger.info(
                "Migrated %d flat config file(s) to subdirectory layout", moved
            )

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
            # Best-effort host reconstruction: dots were encoded as single
        # hyphens and colons (IPv6) as double hyphens.
        host = safe_host.replace("--", ":").replace("-", ".")
        return ConfigRecord(
            device_type=m.group("device_type"),
            host=host,
            timestamp=timestamp,
            filename=path.name,
            file_extension=m.group("ext"),
            size_bytes=path.stat().st_size,
        )
