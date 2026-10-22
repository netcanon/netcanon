"""A sanitised secret is the same kind of secret as the one it replaces.

The sanitiser replaces each local user's stored secret with a fake "of the
same format", so that the sanitised config is the config with its values
changed, and a translation of it is the translation.  It recognised a few
bare shapes (``$6$...``, ``ENC ...``) and faked everything else as
``fake-hash-NNNN`` -- which the shared policy reads as a password AS TYPED.
But a parser puts a tag in front of most stored secrets (EOS
``arista:sha512:``, NX-OS and IOS-XE ``5 `` / ``9 ``, AOS-S ``sha1:``,
Junos ``junos:``), and an AOS-CX ciphertext begins ``AQB``, which no rule
knew: every one of them came out of the sanitiser as a typed password,
written behind the device's cleartext marker (``secret 0 fake-hash-0001``,
``password plaintext fake-hash-0001``), and was left out of the output
where the device takes no typed password (Junos, OPNsense).

The guard reads every committed input whose parser reads a stored secret,
sanitises it, parses the output with the same codec, and holds each
secret's kind -- as ``classify_hash`` reads it -- to the original's.

See also ``tests/unit/tools/test_sanitize.py`` (the sanitiser's own
tests) and ``tests/unit/migration/test_a_typed_password_is_not_a_hash.py``
(what a password as typed is).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import netcanon.migration.codecs  # noqa: F401  (registers the codecs)
from netcanon.migration._user_secrets import classify_hash
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.tools import sanitize
from netcanon.tools.sanitize import sanitize_text

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
_SUFFIXES = {".txt", ".cfg", ".xml", ".conf", ".rsc", ".set"}


def _inputs() -> list[tuple[str, Path]]:
    """Every committed input whose parser reads a stored secret."""
    found = []
    for kind in ("real", "synthetic"):
        for directory in sorted((FIXTURES / kind).iterdir()):
            codec = DIR_TO_CODEC_NAME.get(directory.name)
            if codec is None or not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if not path.is_file() or path.suffix.lower() not in _SUFFIXES:
                    continue
                raw = path.read_text(encoding="utf-8", errors="replace")
                try:
                    users = get_codec(codec).parse(raw).local_users
                except Exception:  # a refused input holds no secret here
                    continue
                if any(u.hashed_password for u in users):
                    found.append((codec, path))
    return found


INPUTS = _inputs()

#: The codecs whose parser reads a stored secret, typed by hand.  RouterOS
#: is not one: an export never prints a user's password.
_READS_A_SECRET = {
    "arista_eos", "aruba_aoscx", "aruba_aoss", "cisco_iosxe_cli",
    "cisco_iosxr", "cisco_nxos", "dell_os10", "fortigate_cli",
    "juniper_junos", "opnsense", "vyos",
}


def _kinds(codec: str, text: str) -> list[str]:
    return sorted(classify_hash(u.hashed_password)[0] for u in get_codec(codec).parse(text).local_users)


def _findings(codec: str, raw: str) -> list[str]:
    """How the sanitised *raw* changes the kind of a stored secret."""
    before = _kinds(codec, raw)
    after = _kinds(codec, sanitize_text(raw, codec).sanitized_text)
    if before == after:
        return []
    return [f"secrets read as {before} before sanitising and {after} after"]


def test_the_inputs_are_every_codec_that_reads_a_secret() -> None:
    assert {codec for codec, _ in INPUTS} == _READS_A_SECRET


@pytest.mark.parametrize(
    ("codec", "path"), INPUTS, ids=[f"{c}:{p.name}" for c, p in INPUTS],
)
def test_a_sanitised_secret_is_the_same_kind(codec, path) -> None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    assert _findings(codec, raw) == []


#: Each shape a parser stores, typed by hand, with the kind the shared
#: policy reads it as.
_SHAPES = [
    ("$6$saltsalt$" + "h" * 86, "sha512"),
    ("$5$saltsalt$" + "h" * 43, "sha256crypt"),
    ("$1$saltsalt$" + "h" * 22, "md5crypt"),
    ("$9$jUnOsReVeRsIbLe", "junos_type9"),
    ("$2y$11$" + "b" * 53, "bcrypt"),
    ("$y$j9T$" + "y" * 43, "yescrypt"),
    ("$8$notmodelled$" + "x" * 20, "unknown"),
    ("AQB" + "c" * 60, "aoscx_encrypted"),
    ("arista:sha512:$6$saltsalt$" + "h" * 86, "sha512"),
    ("arista:plaintext:h0rse", "plaintext"),
    ("aoscx:aoscx_encrypted:wordy", "aoscx_encrypted"),
    ("aoscx:plaintext:AQBlooksEncrypted", "plaintext"),
    ("junos:$6$saltsalt$" + "h" * 86, "sha512"),
    ("junos:$9$jUnOsReVeRsIbLe", "junos_type9"),
    ("fortios:ENC " + "e" * 40, "fortios"),
    ("bcrypt:$2y$11$" + "b" * 53, "bcrypt"),
    ("bcrypt:$6$saltsalt$" + "h" * 86, "sha512"),
    ("sha1:" + "0123456789abcdef" * 2 + "01234567", "sha1"),
    ("plaintext:h0rse", "plaintext"),
    ("5 $1$saltsalt$" + "h" * 22, "5"),
    ("5 $5$saltsalt$" + "h" * 43, "sha256crypt"),
    ("7 0822455D0A16", "7"),
    ("9 $9$" + "s" * 14 + "$" + "h" * 43, "9"),
    ("10 $6$saltsalt$" + "h" * 86, "10"),
    ("h0rse", "plaintext"),
]


@pytest.mark.parametrize(("original", "kind"), _SHAPES)
def test_each_shape_is_faked_as_its_kind(original, kind) -> None:
    assert classify_hash(original)[0] == kind
    fake = sanitize._SubstitutionTable().redact_hash(original)
    assert classify_hash(fake)[0] == kind
    payload = classify_hash(original)[1]
    assert len(payload) < 6 or payload not in fake


def test_text_before_a_colon_that_no_parser_writes_is_redacted() -> None:
    """A tag is kept only where a parser writes it: any other text before a
    colon may be part of a password."""
    fake = sanitize._SubstitutionTable().redact_hash("Summer2024:Corp")
    assert "Summer2024" not in fake and "Corp" not in fake


def test_the_check_sees_the_old_redaction(monkeypatch) -> None:
    """With the tag faked along with the payload, as before, the check
    fails on an input of each tag it was written for."""
    monkeypatch.setattr(sanitize, "_secret_envelope", lambda value: ("", value))
    for codec, name in (
        ("arista_eos", "kitchen_sink.txt"),
        ("cisco_nxos", "kitchen_sink.cfg"),
        ("aruba_aoss", "kitchen_sink.cfg"),
        ("cisco_iosxr", "kitchen_sink.cfg"),
    ):
        (path,) = [p for c, p in INPUTS if c == codec and p.name == name]
        assert _findings(codec, path.read_text(encoding="utf-8")), codec


def test_the_check_sees_a_ciphertext_faked_as_a_word(monkeypatch) -> None:
    real = sanitize._fake_secret_payload

    def as_a_word(original: str, n: int) -> str:
        return f"fake-hash-{n:04d}" if original.startswith("AQB") else real(original, n)

    monkeypatch.setattr(sanitize, "_fake_secret_payload", as_a_word)
    (path,) = [p for c, p in INPUTS if c == "aruba_aoscx" and p.name == "kitchen_sink.cfg"]
    assert _findings("aruba_aoscx", path.read_text(encoding="utf-8"))
