"""FileConfigStore.get_content must not 500 on a non-UTF-8 file (#28).

``get_content`` was the lone strict UTF-8 decoder in the stack; a config with
invalid bytes (an out-of-band drop / foreign backup tool) was still listable +
selectable, but any read/diff/detect/plan action on it escaped a
UnicodeDecodeError as a bare 500.  The fix decodes with ``errors="replace"``,
matching the collector / CLI / sanitizer convention.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from netcanon.storage.file_store import FileConfigStore

pytestmark = pytest.mark.unit


def test_get_content_replaces_invalid_utf8_bytes(tmp_path: Path):
    store = FileConfigStore(tmp_path)
    record = store.save(
        "Cisco", "10.0.0.1", datetime(2026, 4, 14, tzinfo=UTC), "cfg",
        "hostname R1\n",
    )
    # Simulate an out-of-band non-UTF-8 file (e.g. a latin-1 config): 0xe9 is
    # an invalid standalone UTF-8 byte.  The file stays listable/selectable.
    store.resolve_path(record.filename).write_bytes(
        b"hostname R1\ndescription caf\xe9\n"
    )
    # #28: must decode with U+FFFD replacement, NOT raise UnicodeDecodeError.
    content = store.get_content(record.filename)
    assert "hostname R1" in content
    assert "�" in content  # the invalid byte became the replacement char
