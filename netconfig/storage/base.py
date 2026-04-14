"""
Abstract storage interface.

Any storage backend must implement all four methods.  The interface is
intentionally narrow to keep implementations simple and swappable.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from ..models.backup import ConfigRecord


class BaseConfigStore(ABC):
    """Abstract base class for configuration file storage backends.

    All methods are synchronous.  If a backend requires async I/O, wrap
    calls in ``asyncio.to_thread`` at the call site.
    """

    @abstractmethod
    def save(
        self,
        device_type: str,
        host: str,
        timestamp: datetime,
        extension: str,
        content: str,
    ) -> ConfigRecord:
        """Persist a configuration string and return its metadata record.

        Args:
            device_type: The ``type_key`` of the source device definition.
            host: IP address or hostname of the source device.
            timestamp: UTC time of collection.
            extension: File extension without the leading dot (e.g. ``cfg``).
            content: Raw configuration text to store.

        Returns:
            A ``ConfigRecord`` describing the stored file.
        """

    @abstractmethod
    def list_configs(self) -> list[ConfigRecord]:
        """Return metadata for all stored configuration files.

        Returns:
            List of ``ConfigRecord`` objects, newest first.
        """

    @abstractmethod
    def get_content(self, filename: str) -> str:
        """Return the full text of a stored configuration file.

        Args:
            filename: Bare filename (no directory component).

        Returns:
            UTF-8 decoded file content.

        Raises:
            FileNotFoundError: If no file with that name exists.
        """

    @abstractmethod
    def delete(self, filename: str) -> None:
        """Delete a stored configuration file.

        Args:
            filename: Bare filename (no directory component).

        Raises:
            FileNotFoundError: If no file with that name exists.
        """

    @abstractmethod
    def resolve_path(self, filename: str) -> Path:
        """Return the absolute filesystem path for a stored config file.

        Implementations must resolve the correct subdirectory (or legacy flat
        location) from the filename alone.

        Args:
            filename: Bare filename as returned by ``list_configs()``.

        Returns:
            Absolute ``Path`` to the file on disk.

        Raises:
            FileNotFoundError: If no file with that name exists.
        """
