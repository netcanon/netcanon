"""
Credential encryption using OS keyring + Fernet symmetric encryption.

On first use a random Fernet key is generated and stored in the OS
secure credential store (Windows Credential Manager on Windows, Keychain
on macOS, SecretService on Linux via the ``keyring`` library).  Subsequent
runs retrieve the same key so ciphertext persists correctly across restarts.

All credential fields (passwords, enable passwords) in device profiles and
legacy schedule device lists are encrypted before being written to disk and
decrypted immediately after being read back.  The in-memory model objects
always hold **plaintext** values — encryption is a storage-layer concern only.

Migration
---------
On first load after upgrading from an unencrypted version, any field that
fails to decrypt (``InvalidToken``) is assumed to be a legacy plaintext value.
``decrypt_field()`` returns the plaintext and signals that the file should be
re-saved with encryption applied.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SERVICE = "NetConfig"
_ACCOUNT = "master_key"
_fernet = None  # Fernet instance, initialised lazily on first use


def _get_fernet():
    """Return a Fernet instance, initialising the key on first call."""
    global _fernet
    if _fernet is not None:
        return _fernet

    import keyring
    from cryptography.fernet import Fernet

    raw = keyring.get_password(_SERVICE, _ACCOUNT)
    if raw is None:
        key = Fernet.generate_key()
        keyring.set_password(_SERVICE, _ACCOUNT, key.decode())
        logger.info(
            "Generated new credential encryption key in OS keyring (%s / %s)",
            _SERVICE,
            _ACCOUNT,
        )
        raw = key.decode()
    else:
        logger.debug("Loaded credential encryption key from OS keyring")

    _fernet = Fernet(raw.encode())
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* and return a Fernet token string.

    The returned value is a base64url-encoded byte string (safe to store in
    JSON and other text formats).
    """
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a Fernet *token* and return the original plaintext.

    Raises:
        cryptography.fernet.InvalidToken: If *token* is not a valid Fernet
            token — e.g. if it is a legacy plaintext credential.
    """
    return _get_fernet().decrypt(token.encode()).decode()


def decrypt_field(value: str) -> tuple[str, bool]:
    """Decrypt *value* if it is a Fernet token; return as-is if plaintext.

    Used during startup to handle files written before encryption was
    introduced.  The boolean flag indicates whether the value was already
    encrypted so callers can decide whether to re-save the file.

    Returns:
        ``(plaintext, was_encrypted)`` — ``was_encrypted`` is ``False`` when
        the stored value is a legacy plaintext credential that needs migrating.
    """
    from cryptography.fernet import InvalidToken

    try:
        return _get_fernet().decrypt(value.encode()).decode(), True
    except InvalidToken:
        # Value is not a valid Fernet token — treat as legacy plaintext.
        return value, False


def reset_fernet() -> None:  # noqa: D401
    """Reset the cached Fernet instance (test helper only)."""
    global _fernet
    _fernet = None
