"""
Shared credential migration helper for storage loaders.

Both ``FileDeviceProfileStore`` and ``FileScheduleStore`` need to detect
legacy plaintext credentials and re-encrypt them on first load.  This
module centralises that logic so it only exists once.
"""

from __future__ import annotations

import logging

from .credentials import CredentialDecryptError, decrypt_field

logger = logging.getLogger(__name__)


def migrate_credential_fields(
    data: dict,
    fields: list[str],
) -> bool:
    """Decrypt credential *fields* in *data* in-place.

    Returns ``True`` if any field was plaintext (needs re-save with
    encryption), ``False`` if all were already encrypted **or** any field
    could not be decrypted under the active key.

    A token-shaped field that fails to decrypt (wrong / rotated / lost
    key) is left untouched, logged loudly, and forces the return to
    ``False`` so the store does NOT re-save the profile — re-saving would
    double-encrypt the surviving ciphertext and corrupt it.
    """
    needs_resave = False
    decrypt_failed = False
    for field in fields:
        value = data.get(field)
        if not value:
            continue
        try:
            plaintext, was_encrypted = decrypt_field(value)
        except CredentialDecryptError as exc:
            logger.warning(
                "CREDENTIAL DECRYPT FAILED for field %r: %s.  Leaving the "
                "stored value untouched and skipping re-save (avoids double-"
                "encryption).  Restore the original encryption key or "
                "re-enter the credential.",
                field,
                exc,
            )
            decrypt_failed = True
            continue
        data[field] = plaintext
        if not was_encrypted:
            needs_resave = True
    # Never re-save a profile we could not fully decrypt — a re-save would
    # re-encrypt the still-ciphertext field and corrupt it.
    return needs_resave and not decrypt_failed
