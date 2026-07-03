"""
Shared credential migration helper for storage loaders.

Both ``FileDeviceProfileStore`` and ``FileScheduleStore`` need to detect
legacy plaintext credentials and re-encrypt them on first load.  This
module centralises that logic so it only exists once.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from .credentials import CredentialDecryptError, decrypt_field

logger = logging.getLogger(__name__)


def scrub_exc_for_log(exc: BaseException) -> str:
    """Render *exc* for a log line without echoing decrypted secrets.

    The storage loaders call :func:`migrate_credential_fields` — which
    decrypts ``password`` / ``enable_password`` into the in-memory dict —
    BEFORE ``model_validate``.  If validation then fails, the resulting
    pydantic :class:`ValidationError` carries the offending input in
    ``.errors()[*]["input"]``; for a model-level error (e.g. a missing
    required field) that input is the whole decrypted dict, credentials
    included.  Whether the secret reaches the log is purely a function of how
    the error is stringified: ``str(exc)`` on pydantic 2.13 happens NOT to
    render the input, but ``exc.errors()`` does, and the supported range
    (``pydantic>=2.0.0,<3``) includes older 2.x versions whose ``str`` did.
    Rather than depend on that, format a ``ValidationError`` from
    ``errors(include_input=False)`` — field locations + error types only,
    never the input value.  Any other exception (JSON / OS errors) carries no
    plaintext — the on-disk credential is still ciphertext at that point — so
    it passes through ``str`` unchanged.
    """
    if isinstance(exc, ValidationError):
        errs = exc.errors(include_input=False, include_url=False)
        summary = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['type']}"
            for e in errs
        )
        return f"{len(errs)} validation error(s) [{summary}]"
    return str(exc)


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
