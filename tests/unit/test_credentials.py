"""
Unit tests for ``netcanon.security.credentials``.

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
    from netcanon.security.credentials import reset_fernet

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
            from netcanon.security import credentials

            credentials._fernet = None
            # Trigger initialisation by encrypting something
            credentials.encrypt("test")
            mock_set.assert_called_once()
            svc, acc, stored_key = mock_set.call_args.args
            assert svc == "Netcanon"
            assert acc == "master_key"
            assert len(stored_key) > 0

    def test_loads_existing_key_from_keyring(self):
        """Subsequent runs: key already in keyring → reused, no new key generated."""
        key = _make_fernet_key()
        with (
            patch("keyring.get_password", return_value=key),
            patch("keyring.set_password") as mock_set,
        ):
            from netcanon.security import credentials

            credentials._fernet = None
            credentials.encrypt("hello")
            mock_set.assert_not_called()

    def test_fernet_instance_is_cached(self):
        """Second call must not hit the keyring again."""
        key = _make_fernet_key()
        with patch("keyring.get_password", return_value=key) as mock_get:
            from netcanon.security import credentials

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
        from netcanon.security.credentials import encrypt

        result = encrypt("my_password")
        assert isinstance(result, str)

    def test_encrypt_differs_from_plaintext(self):
        from netcanon.security.credentials import encrypt

        assert encrypt("my_password") != "my_password"

    def test_decrypt_recovers_plaintext(self):
        from netcanon.security.credentials import decrypt, encrypt

        plaintext = "super_secret_pass!"
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_round_trip_empty_string(self):
        from netcanon.security.credentials import decrypt, encrypt

        assert decrypt(encrypt("")) == ""

    def test_round_trip_unicode(self):
        from netcanon.security.credentials import decrypt, encrypt

        value = "p\u00e4\u00df\u0077\u00f6rd"  # "pässwörd"
        assert decrypt(encrypt(value)) == value

    def test_two_encryptions_of_same_value_differ(self):
        """Fernet uses a random IV, so each encryption produces a unique token."""
        from netcanon.security.credentials import encrypt

        t1 = encrypt("same")
        t2 = encrypt("same")
        assert t1 != t2

    def test_decrypt_invalid_token_raises(self):
        from cryptography.fernet import InvalidToken

        from netcanon.security.credentials import decrypt

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
        from netcanon.security.credentials import decrypt_field, encrypt

        token = encrypt("secret123")
        plaintext, was_enc = decrypt_field(token)
        assert plaintext == "secret123"
        assert was_enc is True

    def test_legacy_plaintext_returns_value_and_false(self):
        """Plaintext that isn't a Fernet token → treated as legacy, not encrypted."""
        from netcanon.security.credentials import decrypt_field

        plaintext, was_enc = decrypt_field("hunter2")
        assert plaintext == "hunter2"
        assert was_enc is False

    def test_empty_string_returns_false(self):
        from netcanon.security.credentials import decrypt_field

        val, was_enc = decrypt_field("")
        assert val == ""
        assert was_enc is False


# ---------------------------------------------------------------------------
# Tier 1: NETCANON_FERNET_KEY env var (operator-explicit override)
# ---------------------------------------------------------------------------


class TestEnvVarKey:
    """Verify the env-var tier takes priority and bypasses the keyring entirely."""

    def test_env_var_takes_priority_over_keyring(self, monkeypatch):
        """When NETCANON_FERNET_KEY is set, keyring is never consulted."""
        env_key = _make_fernet_key()
        keyring_key = _make_fernet_key()  # different key — proves env wins
        monkeypatch.setenv("NETCANON_FERNET_KEY", env_key)
        with (
            patch("keyring.get_password", return_value=keyring_key) as mock_get,
            patch("keyring.set_password") as mock_set,
        ):
            from netcanon.security import credentials

            credentials._fernet = None
            token = credentials.encrypt("ping")
            # The token must be decryptable with the *env-var* key, proving
            # that's what was used.
            from cryptography.fernet import Fernet

            assert Fernet(env_key.encode()).decrypt(token.encode()).decode() == "ping"
            mock_get.assert_not_called()
            mock_set.assert_not_called()

    def test_env_var_is_stripped(self, monkeypatch):
        """Trailing whitespace / newlines in the env var are tolerated."""
        env_key = _make_fernet_key()
        monkeypatch.setenv("NETCANON_FERNET_KEY", env_key + "\n")
        from netcanon.security import credentials

        credentials._fernet = None
        # Should not raise — Fernet rejects keys with trailing whitespace.
        assert credentials.decrypt(credentials.encrypt("x")) == "x"

    def test_empty_env_var_is_ignored(self, monkeypatch):
        """An empty NETCANON_FERNET_KEY falls through to the next tier."""
        monkeypatch.setenv("NETCANON_FERNET_KEY", "")
        key = _make_fernet_key()
        with (
            patch("keyring.get_password", return_value=key) as mock_get,
            patch("keyring.set_password"),
        ):
            from netcanon.security import credentials

            credentials._fernet = None
            credentials.encrypt("x")
            # Empty env var means we should reach keyring.
            mock_get.assert_called()


# ---------------------------------------------------------------------------
# Tier 3: file fallback at $NETCANON_DATA_DIR/.fernet_key
# ---------------------------------------------------------------------------


class TestFileFallback:
    """Verify the file-fallback tier kicks in when the keyring is unavailable.

    Models the container / headless deployment shape:
    ``keyring.get_password`` raises ``NoKeyringError``, and the application
    should auto-bootstrap a key file inside ``$NETCANON_DATA_DIR``.
    """

    def test_writes_new_key_file_when_keyring_unavailable(self, tmp_path, monkeypatch):
        """No env var, no keyring backend, no existing key file → bootstrap a new key file."""
        from keyring.errors import NoKeyringError

        monkeypatch.delenv("NETCANON_FERNET_KEY", raising=False)
        monkeypatch.setenv("NETCANON_DATA_DIR", str(tmp_path))

        def _raise_no_keyring(*_a, **_kw):
            raise NoKeyringError("no backend in test")

        with (
            patch("keyring.get_password", side_effect=_raise_no_keyring),
            patch("keyring.set_password", side_effect=_raise_no_keyring),
        ):
            from netcanon.security import credentials

            credentials._fernet = None
            token = credentials.encrypt("from_container")

            key_file = tmp_path / ".fernet_key"
            assert key_file.is_file(), "file-fallback key was not written"
            on_disk_key = key_file.read_text().strip()

            # The encrypted token must decrypt with the file's key.
            from cryptography.fernet import Fernet

            assert (
                Fernet(on_disk_key.encode()).decrypt(token.encode()).decode()
                == "from_container"
            )

    def test_loads_existing_key_file_when_keyring_unavailable(
        self, tmp_path, monkeypatch
    ):
        """Pre-existing .fernet_key file is reused, not regenerated."""
        from keyring.errors import NoKeyringError

        monkeypatch.delenv("NETCANON_FERNET_KEY", raising=False)
        monkeypatch.setenv("NETCANON_DATA_DIR", str(tmp_path))
        existing_key = _make_fernet_key()
        (tmp_path / ".fernet_key").write_text(existing_key)

        with (
            patch(
                "keyring.get_password",
                side_effect=NoKeyringError("no backend"),
            ),
            patch("keyring.set_password", side_effect=NoKeyringError("no backend")),
        ):
            from netcanon.security import credentials

            credentials._fernet = None
            # Round-trip through the loaded key.
            assert credentials.decrypt(credentials.encrypt("hi")) == "hi"
            # The token must decrypt with the pre-seeded key (proving load,
            # not regenerate).
            from cryptography.fernet import Fernet

            token = credentials.encrypt("verify")
            assert (
                Fernet(existing_key.encode()).decrypt(token.encode()).decode()
                == "verify"
            )

    def test_round_trip_with_file_fallback(self, tmp_path, monkeypatch):
        """End-to-end encrypt/decrypt with file fallback as the key source."""
        from keyring.errors import NoKeyringError

        monkeypatch.delenv("NETCANON_FERNET_KEY", raising=False)
        monkeypatch.setenv("NETCANON_DATA_DIR", str(tmp_path))

        with (
            patch(
                "keyring.get_password",
                side_effect=NoKeyringError("no backend"),
            ),
            patch("keyring.set_password", side_effect=NoKeyringError("no backend")),
        ):
            from netcanon.security import credentials

            credentials._fernet = None
            plaintext = "container-deployment-password"
            assert credentials.decrypt(credentials.encrypt(plaintext)) == plaintext
