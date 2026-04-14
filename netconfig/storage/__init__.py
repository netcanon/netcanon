"""
Pluggable configuration storage layer.

The ``BaseConfigStore`` abstract class defines the interface.  The
``FileConfigStore`` implementation writes files to a local directory and
is the default for v1.  Future implementations (database, object storage)
only need to satisfy the same interface.
"""

from .base import BaseConfigStore
from .file_store import FileConfigStore

__all__ = ["BaseConfigStore", "FileConfigStore"]
