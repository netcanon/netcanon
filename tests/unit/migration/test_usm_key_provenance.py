"""Three grammars mark a USM key's KIND on the line; canonical must carry it.

NX-OS ``localizedkey``, AOS-CX ``auth-pass ciphertext|plaintext`` and Junos
``authentication-key`` vs ``authentication-password`` each say, on the line
itself, whether the value is a passphrase the agent will process or a key the
agent has ALREADY processed for itself.  Every one of those parsers used to
discard the marker, so the kind fell back to a per-CODEC default and the two
shapes became indistinguishable in the canonical tree.  That cost both
directions:

* **Same-vendor corruption.**  An NX-OS passphrase line (no keyword) re-rendered
  WITH ``localizedkey`` appended — the Nexus is then told a passphrase is
  already localised against its own engine ID, and the user authenticates
  nobody.  Same-vendor re-render is the path that is supposed to be lossless,
  and the round-trip guard could not see it: parse -> render -> parse is
  STABLE, it is the rendered TEXT that is wrong.
* **Cross-vendor over-refusal.**  A genuine passphrase from any of the three was
  classified as the unsafe kind and refused, rather than migrated.

The kind still comes from the SOURCE CODEC'S GRAMMAR, never from the value's
shape — now at per-LINE resolution rather than per-CODEC.  That distinction is
load-bearing: three committed NX-OS captures carry ``localizedkey`` but hold a
word-like (sanitised) value, so shape-inference would call them plaintext and
re-emit another agent's key.  The marker survives sanitisation; the value does
not.

⚠️ No key material appears in this file; every value is a synthetic shape.
"""
from __future__ import annotations

import pytest

import netcanon.migration.codecs as _c  # noqa: F401  (registry population)
from netcanon.migration._usm_keys import (
    CIPHERTEXT,
    LOCALISED,
    PLAINTEXT,
    classify_usm_key,
    usm_is_migratable,
)
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalSNMP,
    CanonicalSNMPv3User,
)
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit

_PASS = "Passphrase0"
_PRIVPASS = "PrivPhrase0"
_KEY = "0x" + "ab" * 16
_PRIVKEY = "0x" + "cd" * 16

# Targets whose USM slot takes a PASSPHRASE, so a portable key must reach them.
_PASSPHRASE_TARGETS = ["arista_eos", "aruba_aoss", "cisco_iosxe_cli",
                       "mikrotik_routeros"]


def _render(source: str, text: str, target: str) -> str:
    """Parse *text* with the *source* codec, render it for *target*."""
    intent = get_codec(source).parse(text)
    return get_codec(target).render(intent)


def _refused(out: str, user: str = "monitor") -> bool:
    return any(user in ln and "review:" in ln for ln in out.splitlines())


def _emitted(out: str, user: str = "monitor") -> bool:
    return any(
        user in ln and "review:" not in ln and ln.strip()
        and not ln.strip().startswith(("!", "#", ";", "/*"))
        for ln in out.splitlines()
    )


# --- NX-OS: the keyword is a CLAIM, and it must be re-derived, not assumed ---

_NXOS_MARKED = (
    f"snmp-server user monitor network-operator auth md5 {_KEY} "
    f"priv aes-128 {_PRIVKEY} localizedkey"
)
_NXOS_UNMARKED = (
    f"snmp-server user monitor network-operator auth md5 {_PASS} "
    f"priv aes-128 {_PRIVPASS}"
)


def test_nxos_records_the_marker_it_read() -> None:
    """The parser must keep WHICH form it saw."""
    marked = get_codec("cisco_nxos").parse(_NXOS_MARKED).snmp.v3_users[0]
    unmarked = get_codec("cisco_nxos").parse(_NXOS_UNMARKED).snmp.v3_users[0]
    assert marked.auth_kind == LOCALISED
    assert marked.priv_kind == LOCALISED
    assert unmarked.auth_kind == PLAINTEXT
    assert unmarked.priv_kind == PLAINTEXT


def test_nxos_passphrase_does_not_gain_the_localizedkey_claim() -> None:
    """THE SAME-VENDOR CORRUPTION.  A passphrase line re-renders as a
    passphrase line — appending ``localizedkey`` tells the Nexus the value is
    already localised against its own engine ID, so it stores passphrase bytes
    as a digest and the user authenticates nobody."""
    out = _render("cisco_nxos", _NXOS_UNMARKED, "cisco_nxos")
    user_lines = [ln for ln in out.splitlines() if ln.startswith("snmp-server user")]
    assert user_lines, "the user must survive a same-vendor re-render"
    assert "localizedkey" not in user_lines[0], (
        "a passphrase was re-emitted as a pre-localised digest"
    )


def test_nxos_localised_key_keeps_its_keyword() -> None:
    """The other half: a genuine localised digest MUST keep the claim, or the
    Nexus re-localises an already-localised key."""
    out = _render("cisco_nxos", _NXOS_MARKED, "cisco_nxos")
    user_lines = [ln for ln in out.splitlines() if ln.startswith("snmp-server user")]
    assert user_lines and "localizedkey" in user_lines[0]


@pytest.mark.parametrize("target", _PASSPHRASE_TARGETS)
def test_nxos_passphrase_migrates_cross_vendor(target: str) -> None:
    """A passphrase ports: every one of these targets derives the key itself."""
    out = _render("cisco_nxos", _NXOS_UNMARKED, target)
    assert _emitted(out), f"{target} refused a genuine passphrase"
    assert not _refused(out)


@pytest.mark.parametrize("target", _PASSPHRASE_TARGETS)
def test_nxos_localised_key_is_still_refused(target: str) -> None:
    """A digest localised to the source engine ID ports nowhere."""
    out = _render("cisco_nxos", _NXOS_MARKED, target)
    assert _refused(out), f"{target} accepted another agent's localised key"
    assert not _emitted(out)


# --- AOS-CX: the keyword is a claim about the device key ---

_AOSCX_CIPHER = (
    f"snmpv3 user monitor auth md5 auth-pass ciphertext {_KEY} "
    f"priv aes priv-pass ciphertext {_PRIVKEY}"
)
_AOSCX_PLAIN = (
    f"snmpv3 user monitor auth md5 auth-pass plaintext {_PASS} "
    f"priv aes priv-pass plaintext {_PRIVPASS}"
)


def test_aoscx_records_the_marker_it_read() -> None:
    cipher = get_codec("aruba_aoscx").parse(_AOSCX_CIPHER).snmp.v3_users[0]
    plain = get_codec("aruba_aoscx").parse(_AOSCX_PLAIN).snmp.v3_users[0]
    assert cipher.auth_kind == CIPHERTEXT
    assert cipher.priv_kind == CIPHERTEXT
    assert plain.auth_kind == PLAINTEXT
    assert plain.priv_kind == PLAINTEXT


@pytest.mark.parametrize("target", _PASSPHRASE_TARGETS)
def test_aoscx_plaintext_migrates_cross_vendor(target: str) -> None:
    out = _render("aruba_aoscx", _AOSCX_PLAIN, target)
    assert _emitted(out), f"{target} refused a genuine AOS-CX passphrase"


@pytest.mark.parametrize("target", _PASSPHRASE_TARGETS)
def test_aoscx_ciphertext_is_still_refused(target: str) -> None:
    out = _render("aruba_aoscx", _AOSCX_CIPHER, target)
    assert _refused(out), f"{target} accepted an AOS-CX device-key blob"


# --- Junos: the kind is a different LEAF, not a keyword ---

_JUNOS_KEY = (
    f'set snmp v3 usm local-engine user monitor authentication-md5 '
    f'authentication-key "{_KEY}"'
)
_JUNOS_PASS = (
    f'set snmp v3 usm local-engine user monitor authentication-md5 '
    f'authentication-password "{_PASS}"'
)


def test_junos_records_which_leaf_it_read() -> None:
    keyed = get_codec("juniper_junos").parse(_JUNOS_KEY).snmp.v3_users[0]
    passed = get_codec("juniper_junos").parse(_JUNOS_PASS).snmp.v3_users[0]
    assert keyed.auth_kind == LOCALISED
    assert passed.auth_kind == PLAINTEXT


@pytest.mark.parametrize("target", _PASSPHRASE_TARGETS)
def test_junos_password_leaf_migrates_cross_vendor(target: str) -> None:
    out = _render("juniper_junos", _JUNOS_PASS, target)
    assert _emitted(out), f"{target} refused a genuine Junos passphrase"


@pytest.mark.parametrize("target", _PASSPHRASE_TARGETS)
def test_junos_key_leaf_is_still_refused(target: str) -> None:
    out = _render("juniper_junos", _JUNOS_KEY, target)
    assert _refused(out), f"{target} accepted a Junos-processed key"


# --- the policy layer itself ---


def test_an_explicit_kind_overrides_the_codec_default() -> None:
    """The per-CODEC default is a fallback for grammars that carry no marker;
    a recorded kind must win."""
    assert classify_usm_key(_PASS, "cisco_nxos", PLAINTEXT) == PLAINTEXT
    assert classify_usm_key(_KEY, "arista_eos", LOCALISED) == LOCALISED


def test_an_unrecognised_kind_fails_closed() -> None:
    """A kind this policy does not model must never read as portable — the
    same rule the unknown-SOURCE case follows."""
    assert classify_usm_key(_KEY, "cisco_nxos", "sometimes-safe") == LOCALISED
    assert not usm_is_migratable(_KEY, "cisco_nxos", "arista_eos",
                                 "sometimes-safe")


def test_no_kind_preserves_the_per_codec_default() -> None:
    """Every marker-free codec keeps today's behaviour: an unset kind is
    'ask the source codec', not 'assume portable'."""
    assert classify_usm_key(_PASS, "arista_eos") == PLAINTEXT
    assert classify_usm_key(_KEY, "cisco_nxos") == LOCALISED
    assert classify_usm_key(_KEY, "vyos") == LOCALISED
    assert classify_usm_key(_KEY, "totally-unknown-codec") == LOCALISED


def test_a_mixed_user_is_refused_on_its_least_portable_key() -> None:
    """auth and priv are separate leaves and CAN disagree (Junos writes them on
    separate lines; AOS-CX marks each token).  Gating on the auth key alone
    would leak a device-bound privacy key."""
    intent = CanonicalIntent(
        hostname="leaf1",
        source_vendor="juniper_junos",
        snmp=CanonicalSNMP(v3_users=[CanonicalSNMPv3User(
            name="monitor", group="operators",
            auth_protocol="md5", auth_passphrase=_PASS, auth_kind=PLAINTEXT,
            priv_protocol="aes", priv_passphrase=_PRIVKEY,
            priv_kind=LOCALISED,
        )]),
    )
    for target in _PASSPHRASE_TARGETS:
        out = get_codec(target).render(intent)
        assert _refused(out), (
            f"{target} emitted a user whose PRIVACY key belongs to the "
            f"source agent"
        )
