"""Tests for the shared cross-codec user-secret policy module.

The functions under test are imported by the fortigate_cli,
juniper_junos, and opnsense renderers (Wave 2) to avoid leaking
foreign hashes (Cisco type-9, Arista sha512, etc.) as plaintext-
equivalent text on the target wire.

See also: netconfig/migration/_user_secrets.py
"""

from __future__ import annotations

import pytest

from netconfig.migration._user_secrets import (
    _TARGET_ACCEPTS,
    _UNIVERSALLY_UNMIGRATABLE,
    classify_hash,
    format_review_comment,
    is_migratable,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# classify_hash — input shapes
# ---------------------------------------------------------------------------


def test_classify_hash_cisco_type_9() -> None:
    """Cisco IOS-XE shape: ``9 $9$<scrypt>`` (digit, space, payload)."""
    alg, payload = classify_hash("9 $9$abc")
    assert alg == "9"
    assert payload == "$9$abc"


def test_classify_hash_cisco_type_5() -> None:
    """Cisco IOS shape: ``5 $1$<md5crypt>``."""
    alg, payload = classify_hash("5 $1$saltsalt$hash")
    assert alg == "5"
    assert payload == "$1$saltsalt$hash"


def test_classify_hash_arista_sha512() -> None:
    """Vendor-tagged two-colon form: ``arista:sha512:$6$..``."""
    alg, payload = classify_hash("arista:sha512:$6$salt$hash")
    assert alg == "sha512"
    assert payload == "$6$salt$hash"


def test_classify_hash_bcrypt() -> None:
    """Single-colon form: ``bcrypt:$2y$10$..``."""
    alg, payload = classify_hash("bcrypt:$2y$10$saltbcryptpayload")
    assert alg == "bcrypt"
    assert payload == "$2y$10$saltbcryptpayload"


def test_classify_hash_native_sha1() -> None:
    """Native AOS-S form: ``sha1:<40-hex>`` should classify as sha1."""
    alg, payload = classify_hash("sha1:abc123")
    assert alg == "sha1"
    assert payload == "abc123"


def test_classify_hash_plaintext() -> None:
    """Bare string with no separator is treated as a plaintext password."""
    alg, payload = classify_hash("hello")
    assert alg == "plaintext"
    assert payload == "hello"


def test_classify_hash_empty() -> None:
    """Empty input returns the plaintext sentinel with empty payload."""
    alg, payload = classify_hash("")
    assert alg == "plaintext"
    assert payload == ""


def test_classify_hash_algorithm_lowercased() -> None:
    """Algorithm tokens are normalised to lowercase regardless of input case."""
    alg, _payload = classify_hash("Arista:SHA512:$6$x$y")
    assert alg == "sha512"


# ---------------------------------------------------------------------------
# is_migratable — per-target policy
# ---------------------------------------------------------------------------


def test_is_migratable_cisco_type_9_to_fortigate() -> None:
    """Type-9 scrypt is FortiGate-incompatible — must be unmigratable."""
    assert is_migratable("9 $9$abc", "fortigate_cli") is False


def test_is_migratable_cisco_type_9_to_junos() -> None:
    """Junos accepts $1$/$6$ but NOT type-9 scrypt — unmigratable."""
    assert is_migratable("9 $9$abc", "juniper_junos") is False


def test_is_migratable_cisco_type_9_to_opnsense() -> None:
    """OPNsense is bcrypt-only — type-9 cannot be re-hashed there."""
    assert is_migratable("9 $9$abc", "opnsense") is False


def test_is_migratable_cisco_type_9_to_mikrotik() -> None:
    """RouterOS only takes plaintext — even Cisco type-9 is rejected."""
    assert is_migratable("9 $9$abc", "mikrotik_routeros") is False


def test_is_migratable_arista_sha512_to_junos() -> None:
    """Arista's $6$ sha512 IS migratable to Junos — Junos accepts $6$."""
    assert is_migratable("arista:sha512:$6$salt$hash", "juniper_junos") is True


def test_is_migratable_arista_sha512_to_opnsense() -> None:
    """OPNsense is bcrypt-only — sha512 is foreign and unmigratable."""
    assert is_migratable("arista:sha512:$6$salt$hash", "opnsense") is False


def test_is_migratable_bcrypt_to_opnsense() -> None:
    """Bcrypt $2y$ is OPNsense-native and migrates cleanly."""
    assert is_migratable("bcrypt:$2y$10$salt$hash", "opnsense") is True


def test_is_migratable_plaintext_universal() -> None:
    """Plaintext passwords are universally migratable across all targets."""
    for target in (
        "aruba_aoss",
        "fortigate_cli",
        "juniper_junos",
        "opnsense",
        "mikrotik_routeros",
    ):
        assert is_migratable("hello", target) is True, target


def test_is_migratable_unknown_target_only_plaintext() -> None:
    """Unknown target vendors are conservatively treated as plaintext-only."""
    assert is_migratable("hello", "made_up_vendor") is True
    assert is_migratable("9 $9$abc", "made_up_vendor") is False


def test_arista_eos_in_target_accepts() -> None:
    """``arista_eos`` accepts plaintext + the three algorithms whose
    payloads EOS's ``secret`` command can consume natively (md5crypt-
    aliases ``"5"``/``"md5crypt"`` and ``"sha512"``).  Mirrors
    ``_ARISTA_SECRET_TYPE`` in ``codecs/arista_eos/render.py`` —
    keep these in sync (the codec uses ``is_migratable`` as the
    gate, then the local table for emit-form dispatch).
    """
    assert "arista_eos" in _TARGET_ACCEPTS
    assert _TARGET_ACCEPTS["arista_eos"] == frozenset(
        {"plaintext", "5", "md5crypt", "sha512"}
    )


def test_is_migratable_arista_eos_known_algorithms() -> None:
    """Each algorithm Arista's ``secret`` command can consume
    natively must report as migratable through the shared helper."""
    assert is_migratable("hunter2", "arista_eos") is True
    assert is_migratable("5 $1$salt$md5crypthash", "arista_eos") is True
    assert is_migratable(
        "arista:5:$1$salt$md5crypthash", "arista_eos"
    ) is True
    assert is_migratable(
        "md5crypt:$1$salt$md5crypthash", "arista_eos"
    ) is True
    assert is_migratable(
        "arista:sha512:$6$salt$sha512hash", "arista_eos"
    ) is True
    assert is_migratable(
        "sha512:$6$salt$sha512hash", "arista_eos"
    ) is True


def test_is_migratable_arista_eos_rejects_bcrypt() -> None:
    """Bcrypt ``$2y$`` cannot be consumed by EOS's ``secret``
    command — the previous opaque ``secret 5 bcrypt:$2y$..``
    fallback was issue #1 in ``user_smoke_findings.md`` (CRITICAL
    security disclosure).  Gate must report unmigratable so the
    Arista codec falls through to the review-comment line."""
    assert is_migratable(
        "bcrypt:$2y$11$saltbcryptpayload", "arista_eos"
    ) is False


def test_universally_unmigratable_membership() -> None:
    """Sanity-check the constant Wave 2 may import for cross-checks."""
    assert "9" in _UNIVERSALLY_UNMIGRATABLE
    assert "5" in _UNIVERSALLY_UNMIGRATABLE
    assert "bcrypt" in _UNIVERSALLY_UNMIGRATABLE
    assert "plaintext" not in _UNIVERSALLY_UNMIGRATABLE


# ---------------------------------------------------------------------------
# format_review_comment — comment-syntax dispatch
# ---------------------------------------------------------------------------


def test_format_review_comment_hash_syntax() -> None:
    line = format_review_comment("netadmin", "9", "hash")
    assert line.startswith("# password manager")
    assert '"netadmin"' in line
    assert "9 hash" in line
    assert "reset" in line


def test_format_review_comment_semicolon_syntax() -> None:
    line = format_review_comment("netadmin", "sha512", "semicolon")
    assert line.startswith("; password manager")
    assert "sha512 hash" in line


def test_format_review_comment_slash_syntax() -> None:
    line = format_review_comment("netadmin", "bcrypt", "slash")
    assert line.startswith("/* password manager")
    assert line.endswith(" */")


def test_format_review_comment_xml_syntax() -> None:
    line = format_review_comment("admin", "fortios", "xml")
    assert line.startswith("<!-- password manager")
    assert line.endswith(" -->")


def test_format_review_comment_xml_no_double_hyphen() -> None:
    """XML 1.0 forbids ``--`` inside comment bodies (the parser treats
    it as premature termination of the comment).  The helper must
    produce output that is embeddable directly into XML without any
    local post-processing.

    Asserts zero ``--`` substrings appear between the leading ``<!--``
    and trailing ``-->`` delimiters.  Also verifies well-formedness
    by reparsing the output through ``xml.etree.ElementTree``.
    """
    import xml.etree.ElementTree as ET

    line = format_review_comment("netadmin", "9", "xml")
    # Strip the comment delimiters before scanning the body.
    body = line.removeprefix("<!-- ").removesuffix(" -->")
    assert "--" not in body, (
        f"XML comment body must not contain '--': {body!r}"
    )
    # Wording invariant — the separator is a single ``-``.
    assert "- review:" in body
    # Reparse to confirm the output is well-formed XML when wrapped
    # in a root element (ElementTree.fromstring rejects ``--`` inside
    # comments at parse time).
    ET.fromstring(f"<root>{line}</root>")


def test_format_review_comment_non_xml_keeps_double_hyphen() -> None:
    """Non-XML comment syntaxes preserve the original ``-- review:``
    separator byte-for-byte — Aruba AOS-S, FortiGate, and Junos all
    emit lines with this exact phrasing.  Changing it would break
    cross-vendor diff stability."""
    for syntax in ("hash", "semicolon", "slash"):
        line = format_review_comment("netadmin", "9", syntax)
        assert "-- review:" in line, syntax


def test_format_review_comment_default_is_hash() -> None:
    line = format_review_comment("admin", "9")
    assert line.startswith("# password manager")


def test_format_review_comment_unknown_syntax_falls_back_to_hash() -> None:
    """Unknown comment_syntax values silently fall back to hash form."""
    line = format_review_comment("admin", "9", "klingon")
    assert line.startswith("# password manager")


def test_format_review_comment_target_label_default_is_this_target() -> None:
    """When target_label is omitted the body keeps the generic
    "this target" wording — preserves byte-identity for callers
    that haven't been updated to pass a vendor-specific label."""
    line = format_review_comment("netadmin", "9")
    assert "cannot be re-used on this target" in line


def test_format_review_comment_target_label_overrides_default() -> None:
    """A vendor-specific target_label replaces the generic
    "this target" wording without changing surrounding structure."""
    line = format_review_comment(
        "netadmin", "bcrypt", target_label="Cisco IOS-XE",
    )
    assert "cannot be re-used on Cisco IOS-XE" in line
    assert "this target" not in line


def test_format_review_comment_target_label_works_with_xml_syntax() -> None:
    """target_label composes with comment_syntax — XML body stays
    XML-comment-safe (no ``--`` substrings) regardless of label."""
    line = format_review_comment(
        "admin", "9", comment_syntax="xml", target_label="OPNsense",
    )
    assert line.startswith("<!-- ")
    assert line.endswith(" -->")
    assert "cannot be re-used on OPNsense" in line
    body = line.removeprefix("<!-- ").removesuffix(" -->")
    assert "--" not in body
