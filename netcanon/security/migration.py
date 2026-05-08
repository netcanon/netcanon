"""
Shared credential migration helper for storage loaders.

Both ``FileDeviceProfileStore`` and ``FileScheduleStore`` need to detect
legacy plaintext credentials and re-encrypt them on first load.  This
module centralises that logic so it only exists once.
"""

from __future__ import annotations

import logging

from .credentials import decrypt_field

logger = logging.getLogger(__name__)


def migrate_credential_fields(
    data: dict,
    fields: list[str],
) -> bool:
    """Decrypt credential *fields* in *data* in-place.

    Returns ``True`` if any field was plaintext (needs re-save with
    encryption), ``False`` if all were already encrypted.
    """
    needs_resave = False
    for field in fields:
        value = data.get(field)
        if value:
            plaintext, was_encrypted = decrypt_field(value)
            data[field] = plaintext
            if not was_encrypted:
                needs_resave = True
    return needs_resave
