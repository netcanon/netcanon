"""
Credential encryption using Fernet symmetric encryption.

Fernet key resolution
---------------------

The key used to encrypt device credentials at rest is resolved in this
order, first hit wins:

1. **``NETCANON_FERNET_KEY`` environment variable** — operator-explicit.
   Recommended for container / headless / production deployments.
   Generate once with::

       python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

   and inject via ``-e NETCANON_FERNET_KEY=...`` or your orchestrator's
   secret-injection mechanism.  The key never touches disk inside the
   application's data directory.

2. **OS keyring** — Windows Credential Manager (DPAPI) / macOS Keychain
   / Linux SecretService (via dbus + libsecret).  Best fit for desktop
   installs.  Not available in container / headless / CI environments
   that lack a SecretService daemon.

3. **File fallback** at ``$NETCANON_DATA_DIR/.fernet_key`` —
   zero-config bootstrap for container / headless deployments where no
   keyring backend exists and the operator hasn't set the env var.
   Auto-generated on first use and persisted in the operator's bind-
   mounted data volume so subsequent restarts decrypt existing
   profiles.  The key is plaintext on disk, but the disk in question is
   ``NETCANON_DATA_DIR`` — the same volume the operator already chose
   to trust for jobs / schedules / device profile JSON.  This is the
   weakest tier; tier 1 (env var) is the recommended production
   pattern.

On first use, if no key is found anywhere, a new random Fernet key is
generated and persisted via the highest-tier mechanism that's writable:
keyring if available, file otherwise.  Subsequent runs retrieve the
same key so ciphertext persists correctly across restarts.

All credential fields (passwords, enable passwords) in device profiles
and legacy schedule device lists are encrypted before being written to
disk and decrypted immediately after being read back.  The in-memory
model objects always hold **plaintext** values — encryption is a
storage-layer concern only.

Migration
---------
On first load after upgrading from an unencrypted version, any field
that fails to decrypt (``InvalidToken``) is assumed to be a legacy
plaintext value.  ``decrypt_field()`` returns the plaintext and signals
that the file should be re-saved with encryption applied.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_SERVICE = "Netcanon"
_ACCOUNT = "master_key"
_ENV_VAR = "NETCANON_FERNET_KEY"
_KEY_FILENAME = ".fernet_key"
_fernet = None  # Fernet instance, initialised lazily on first use


def _data_dir() -> Path:
    """Return the directory where the file-fallback key lives.

    Matches the storage layer's convention: uses ``NETCANON_DATA_DIR``
    if set, else falls back to ``./data`` relative to the current
    working directory.  This keeps the file-fallback key alongside the
    job / schedule / device-profile state in the same bind-mounted
    volume.
    """
    return Path(os.environ.get("NETCANON_DATA_DIR", "data"))


def _read_keyring() -> str | None:
    """Read the Fernet key from the OS keyring.

    Returns the key string if present, ``None`` if the keyring backend
    is alive but no key is stored, and raises whatever the keyring
    library raises (typically ``NoKeyringError``) if no backend is
    available.  Callers are expected to catch and fall through to the
    next tier.
    """
    import keyring

    return keyring.get_password(_SERVICE, _ACCOUNT)


def _write_keyring(key: str) -> bool:
    """Try to write *key* to the OS keyring.

    Returns ``True`` if the write succeeded; ``False`` if the keyring
    backend rejected the call.  Never raises — keyring write failures
    are a signal to fall through to the file-fallback tier, not an
    error condition.
    """
    import keyring

    try:
        keyring.set_password(_SERVICE, _ACCOUNT, key)
        return True
    except Exception as e:  # noqa: BLE001 — backend variety; any failure → fall through
        logger.debug(
            "Keyring write failed (%s); falling through to file fallback",
            type(e).__name__,
        )
        return False


def _read_key_file() -> str | None:
    """Read the file-fallback Fernet key from ``$NETCANON_DATA_DIR/.fernet_key``."""
    key_file = _data_dir() / _KEY_FILENAME
    if key_file.is_file():
        return key_file.read_text(encoding="utf-8").strip()
    return None


def _write_key_file(key: str) -> Path:
    """Write *key* to ``$NETCANON_DATA_DIR/.fernet_key``.

    Creates the parent directory if needed and attempts restrictive
    permissions (0o600); chmod failures on platforms that don't honour
    POSIX perms (notably Windows) are non-fatal — the directory is
    operator-managed and presumed-protected.
    """
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    key_file = data_dir / _KEY_FILENAME
    key_file.write_text(key, encoding="utf-8")
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        # Windows doesn't enforce POSIX perms; that's fine.
        pass
    return key_file


def _resolve_key() -> str:
    """Resolve the Fernet key string via the 3-tier lookup.

    See module docstring for the precedence rationale.
    """
    from cryptography.fernet import Fernet

    # ----- Tier 1: environment variable wins outright. -----
    env_key = os.environ.get(_ENV_VAR)
    if env_key:
        logger.info("Loaded credential encryption key from %s env var", _ENV_VAR)
        return env_key.strip()

    # ----- Tier 2: OS keyring (when a backend is actually usable). -----
    try:
        existing = _read_keyring()
        if existing is not None:
            logger.debug("Loaded credential encryption key from OS keyring")
            return existing
        # Keyring backend works but no key stored yet — generate one and
        # try to persist it back through the same channel.
        candidate = Fernet.generate_key().decode()
        if _write_keyring(candidate):
            logger.info(
                "Generated new credential encryption key in OS keyring (%s / %s)",
                _SERVICE,
                _ACCOUNT,
            )
            return candidate
        # Read succeeded but write failed — unusual; fall through.
    except Exception as e:  # noqa: BLE001 — backend variety; NoKeyringError + friends
        logger.debug(
            "OS keyring unavailable (%s); falling back to file storage",
            type(e).__name__,
        )

    # ----- Tier 3: file fallback at NETCANON_DATA_DIR/.fernet_key. -----
    on_disk = _read_key_file()
    if on_disk is not None:
        logger.debug(
            "Loaded credential encryption key from %s",
            _data_dir() / _KEY_FILENAME,
        )
        return on_disk

    # Nothing anywhere — generate and write to disk.
    candidate = Fernet.generate_key().decode()
    path = _write_key_file(candidate)
    logger.warning(
        "Generated new credential encryption key at %s.  For production "
        "deployments, set %s instead so the key never touches the "
        "application's data directory.",
        path,
        _ENV_VAR,
    )
    return candidate


def _get_fernet():
    """Return a Fernet instance, initialising the key on first call."""
    global _fernet
    if _fernet is not None:
        return _fernet

    from cryptography.fernet import Fernet

    raw = _resolve_key()
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
