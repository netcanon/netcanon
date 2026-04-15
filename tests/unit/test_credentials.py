"""
Unit tests for ``netconfig.security.credentials``.

The OS keyring is mocked throughout — no real credential store is touched.
``reset_fernet()`` is called between tests so each test gets a fresh key.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_KEY = None  # filled lazily after first test generates one


def _make_fernet_key() -> str:
    """Generate a real Fernet key string for use in mocks."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_module():
    """Reset the cached Fernet instance before every test."""
    from netconfig.security.credentials import reset_fernet

    reset_fernet()
    yield
    reset_fernet()


# ---------------------------------------------------------------------------
# Key initialisation
# ---------------------------------------------------------------------------


class TestKeyInitialisation:
    def test_generates_key_when_none_exists(self):
        """First run: no key in keyring → new key generated and stored."""
        key = _make_fernet_key()
        with (
            patch("keyring.get_password", return_value=None),
            patch("keyring.set_password") as mock_set,
        ):
            from netconfig.security import credentials

            credentials._fernet = None
            # Trigger initialisation by encrypting something
            credentials.encrypt("test")
            mock_set.assert_called_once()
            svc, acc, stored_key = mock_set.call_args.args
            assert svc == "NetConfig"
            assert acc == "master_key"
            assert len(stored_key) > 0

    def test_loads_existing_key_from_keyring(self):
        """Subsequent runs: key already in keyring → reused, no new key generated."""
        key = _make_fernet_key()
        with (
            patch("keyring.get_password", return_value=key),
            patch("keyring.set_password") as mock_set,
        ):
            from netconfig.security import credentials

            credentials._fernet = None
            credentials.encrypt("hello")
            mock_set.assert_not_called()

    def test_fernet_instance_is_cached(self):
        """Second call must not hit the keyring again."""
        key = _make_fernet_key()
        with patch("keyring.get_password", return_value=key) as mock_get:
            from netconfig.security import credentials

            credentials._fernet = None
            credentials.encrypt("first")
            credentials.encrypt("second")
            assert mock_get.call_count == 1  # only called once


# ---------------------------------------------------------------------------
# encrypt / decrypt round-trip
# ---------------------------------------------------------------------------


class TestEncryptDecrypt:
    @pytest.fixture(autouse=True)
    def _patch_keyring(self):
        key = _make_fernet_key()
        with (
            patch("keyring.get_password", return_value=key),
            patch("keyring.set_password"),
        ):
            yield

    def test_encrypt_returns_string(self):
        from netconfig.security.credentials import encrypt

        result = encrypt("my_password")
        assert isinstance(result, str)

    def test_encrypt_differs_from_plaintext(self):
        from netconfig.security.credentials import encrypt

        assert encrypt("my_password") != "my_password"

    def test_decrypt_recovers_plaintext(self):
        from netconfig.security.credentials import decrypt, encrypt

        plaintext = "super_secret_pass!"
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_round_trip_empty_string(self):
        from netconfig.security.credentials import decrypt, encrypt

        assert decrypt(encrypt("")) == ""

    def test_round_trip_unicode(self):
        from netconfig.security.credentials import decrypt, encrypt

        value = "p\u00e4\u00df\u0077\u00f6rd"  # "pässwörd"
        assert decrypt(encrypt(value)) == value

    def test_two_encryptions_of_same_value_differ(self):
        """Fernet uses a random IV, so each encryption produces a unique token."""
        from netconfig.security.credentials import encrypt

        t1 = encrypt("same")
        t2 = encrypt("same")
        assert t1 != t2

    def test_decrypt_invalid_token_raises(self):
        from cryptography.fernet import InvalidToken

        from netconfig.security.credentials import decrypt

        with pytest.raises(InvalidToken):
            decrypt("not-a-fernet-token")


# ---------------------------------------------------------------------------
# decrypt_field — migration helper
# ---------------------------------------------------------------------------


class TestDecryptField:
    @pytest.fixture(autouse=True)
    def _patch_keyring(self):
        key = _make_fernet_key()
        with (
            patch("keyring.get_password", return_value=key),
            patch("keyring.set_password"),
        ):
            yield

    def test_encrypted_value_returns_plaintext_and_true(self):
        from netconfig.security.credentials import decrypt_field, encrypt

        token = encrypt("secret123")
        plaintext, was_enc = decrypt_field(token)
        assert plaintext == "secret123"
        assert was_enc is True

    def test_legacy_plaintext_returns_value_and_false(self):
        """Plaintext that isn't a Fernet token → treated as legacy, not encrypted."""
        from netconfig.security.credentials import decrypt_field

        plaintext, was_enc = decrypt_field("hunter2")
        assert plaintext == "hunter2"
        assert was_enc is False

    def test_empty_string_returns_false(self):
        from netconfig.security.credentials import decrypt_field

        val, was_enc = decrypt_field("")
        assert val == ""
        assert was_enc is False
