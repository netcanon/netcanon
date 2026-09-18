"""Three USM grammars a parser silently threw away.

Each vendor has a second spelling for the same v3 user, and in each case the
parser matched only the first -- so a real config lost the user (or its key)
with no warning at all.  A refusal is visible; a silent drop is not.

* **VyOS** ``service snmp v3 user <n> auth plaintext-password <v>``.  The leaf
  set accepted ``type`` / ``encrypted-password`` / ``encrypted-key`` only, so
  the user record was built with an EMPTY key.  Per the VyOS reference the
  valid leaves are ``plaintext-password`` and ``encrypted-password`` -- under
  both ``auth`` and ``privacy``; ``encrypted-key`` / ``plaintext-key`` are not
  VyOS spellings at all.
* **Cisco IOS-XE** ``snmp-server user <n> <g> v3 encrypted auth sha <v>``.  Per
  the Cisco command reference ``encrypted`` is an optional keyword straight
  after ``v3``; the regex ended ``\\s*$`` after the optional auth/priv clauses,
  so the whole LINE failed to match and the user vanished.  (The parser comment
  claimed the trailer "lands in the passphrase bucket and round-trips back out
  on render" -- it did not; both that spelling and the real one dropped.)
* **Arista EOS** ``snmp-server user <n> <g> v3 localized <engineID> auth …``.
  Per the EOS command reference the form is
  ``user_name group_name [AGENT] VERSION [ENGINE][SECURITY]`` with ENGINE =
  ``localized <engineID>`` -- i.e. BETWEEN ``v3`` and ``auth``.  Same failure:
  the line did not match and the user disappeared.

⚠️ Each recovered key is the agent's ALREADY-PROCESSED form, so it is stamped
``localised`` (VyOS ``encrypted-password`` likewise) and a target that cannot
re-derive it refuses it -- visibly, which is the whole point.  VyOS
``plaintext-password`` is the one portable spelling of the four.

⚠️ No key material appears in this file; every value is a synthetic shape.
"""
from __future__ import annotations

import pytest

import netcanon.migration.codecs as _c  # noqa: F401  (registry population)
from netcanon.migration._usm_keys import LOCALISED, PLAINTEXT
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit

_KEY = "0x" + "ab" * 16
_PRIVKEY = "0x" + "cd" * 16
_PASS = "Passphrase0"
_PRIVPASS = "PrivPhrase0"
_ENGINE = "0x80000009"


def _users(codec: str, text: str):
    intent = get_codec(codec).parse(text)
    snmp = getattr(intent, "snmp", None)
    return intent, list(getattr(snmp, "v3_users", []) or []) if snmp else (intent, [])


# --- VyOS: plaintext-password is a real leaf and was dropped on the floor ----

def _vyos(leaf: str, value: str, priv_leaf: str, priv_value: str) -> str:
    return (
        "service {\n"
        "    snmp {\n"
        "        v3 {\n"
        "            user monitor {\n"
        "                group default\n"
        "                auth {\n"
        f"                    {leaf} {value}\n"
        "                    type md5\n"
        "                }\n"
        "                privacy {\n"
        f"                    {priv_leaf} {priv_value}\n"
        "                    type aes\n"
        "                }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def test_vyos_plaintext_password_is_not_dropped() -> None:
    """The key must survive parse -- the user record used to be created with
    an empty passphrase, losing the credential with no warning."""
    _, users = _users("vyos", _vyos("plaintext-password", _PASS,
                                    "plaintext-password", _PRIVPASS))
    assert users, "the v3 user must parse"
    assert users[0].auth_passphrase == _PASS
    assert users[0].priv_passphrase == _PRIVPASS


def test_vyos_plaintext_password_is_stamped_portable() -> None:
    _, users = _users("vyos", _vyos("plaintext-password", _PASS,
                                    "plaintext-password", _PRIVPASS))
    assert users[0].auth_kind == PLAINTEXT
    assert users[0].priv_kind == PLAINTEXT


def test_vyos_encrypted_password_is_stamped_localised() -> None:
    """The other spelling still reads as the agent's own processed key."""
    _, users = _users("vyos", _vyos("encrypted-password", _KEY,
                                    "encrypted-password", _PRIVKEY))
    assert users[0].auth_kind == LOCALISED
    assert users[0].priv_kind == LOCALISED


def test_vyos_does_not_relabel_a_passphrase_as_its_own_ciphertext() -> None:
    """``encrypted-password`` asserts VyOS localised the value against its own
    engine ID.  Writing a passphrase there is the same false claim NX-OS made
    with ``localizedkey`` -- so a plaintext source must go back out through
    ``plaintext-password`` on a same-vendor re-render."""
    raw = _vyos("plaintext-password", _PASS, "plaintext-password", _PRIVPASS)
    out = get_codec("vyos").render(get_codec("vyos").parse(raw))
    assert "plaintext-password" in out, "the portable spelling was not used"
    assert f"encrypted-password {_PASS}" not in out, (
        "a passphrase was re-emitted as VyOS's own localised key"
    )


def test_vyos_own_encrypted_key_still_round_trips() -> None:
    raw = _vyos("encrypted-password", _KEY, "encrypted-password", _PRIVKEY)
    out = get_codec("vyos").render(get_codec("vyos").parse(raw))
    assert f"encrypted-password {_KEY}" in out


# --- IOS-XE: the `encrypted` keyword sits right after v3 --------------------

_IOSXE_ENC = (
    f"snmp-server user monitor grp v3 encrypted auth sha {_KEY} "
    f"priv aes 128 {_PRIVKEY}"
)


def test_iosxe_encrypted_user_is_not_dropped() -> None:
    """The whole user used to vanish: the line failed to match, so nothing at
    all reached canonical."""
    _, users = _users("cisco_iosxe_cli", _IOSXE_ENC)
    assert users, "the v3 user must parse"
    assert users[0].name == "monitor"
    assert users[0].auth_passphrase == _KEY


def test_iosxe_encrypted_key_is_stamped_localised() -> None:
    _, users = _users("cisco_iosxe_cli", _IOSXE_ENC)
    assert users[0].auth_kind == LOCALISED


def test_iosxe_plain_passphrase_is_unchanged() -> None:
    """The common form must keep carrying no marker (codec default applies)."""
    _, users = _users(
        "cisco_iosxe_cli",
        f"snmp-server user monitor grp v3 auth sha {_PASS}",
    )
    assert users[0].auth_passphrase == _PASS
    assert users[0].auth_kind == ""


# --- Arista: `localized <engineID>` sits between v3 and auth ----------------

_EOS_LOCALIZED = (
    f"snmp-server user monitor grp v3 localized {_ENGINE} auth sha {_KEY} "
    f"priv aes {_PRIVKEY}"
)


def test_arista_localized_user_is_not_dropped() -> None:
    _, users = _users("arista_eos", _EOS_LOCALIZED)
    assert users, "the v3 user must parse"
    assert users[0].auth_passphrase == _KEY
    assert users[0].priv_passphrase == _PRIVKEY


def test_arista_localized_key_is_stamped_localised() -> None:
    _, users = _users("arista_eos", _EOS_LOCALIZED)
    assert users[0].auth_kind == LOCALISED
    assert users[0].priv_kind == LOCALISED


def test_arista_localized_engine_id_is_captured() -> None:
    """The engineID the key is localised AGAINST is the reason it cannot
    travel; dropping it would discard the evidence."""
    _, users = _users("arista_eos", _EOS_LOCALIZED)
    assert users[0].engine_id == _ENGINE


def test_arista_plain_passphrase_is_unchanged() -> None:
    _, users = _users(
        "arista_eos",
        f"snmp-server user monitor grp v3 auth sha {_PASS} priv aes {_PRIVPASS}",
    )
    assert users[0].auth_passphrase == _PASS
    assert users[0].auth_kind == ""


# --- the recovered keys must be refused, not silently carried ---------------

@pytest.mark.parametrize(
    "source, text",
    [("cisco_iosxe_cli", _IOSXE_ENC), ("arista_eos", _EOS_LOCALIZED)],
)
def test_a_recovered_localised_key_is_refused_cross_vendor(source, text) -> None:
    """Recovering these users must not smuggle a device-bound key into a
    target.  Before, they vanished silently; now they are refused VISIBLY."""
    intent = get_codec(source).parse(text)
    out = get_codec("cisco_nxos").render(intent)
    assert any("review:" in ln and "monitor" in ln for ln in out.splitlines()), (
        "a key localised to the source agent was not refused"
    )
    assert _KEY not in out, "the source agent's key reached the target config"


# --- recovering a key is only half the job: it must go back out MARKED ------

def test_arista_localised_key_is_re_emitted_behind_its_engine_clause() -> None:
    """EOS's bare slot takes a passphrase and DERIVES the key, so re-emitting a
    localised digest there makes the switch derive a key from a key -- the
    NX-OS same-vendor corruption in a different grammar."""
    out = get_codec("arista_eos").render(
        get_codec("arista_eos").parse(_EOS_LOCALIZED)
    )
    lines = [ln for ln in out.splitlines() if ln.startswith("snmp-server user")]
    assert lines, "the user must survive a same-vendor re-render"
    assert f"localized {_ENGINE}" in lines[0], (
        "a localised key was re-emitted into the passphrase slot"
    )


def test_iosxe_encrypted_key_is_re_emitted_behind_its_keyword() -> None:
    """Same shape on IOS-XE: without ``encrypted`` the value is taken as a
    passphrase and re-derived."""
    out = get_codec("cisco_iosxe_cli").render(
        get_codec("cisco_iosxe_cli").parse(_IOSXE_ENC)
    )
    lines = [ln for ln in out.splitlines() if ln.startswith("snmp-server user")]
    assert lines, "the user must survive a same-vendor re-render"
    assert "v3 encrypted" in lines[0], (
        "a stored key was re-emitted as though it were a passphrase"
    )


def test_a_passphrase_source_gains_no_marker() -> None:
    """The control in both grammars: an unmarked source must stay unmarked, or
    every ordinary v3 user acquires a false claim."""
    eos = get_codec("arista_eos")
    out = eos.render(eos.parse(
        f"snmp-server user monitor grp v3 auth sha {_PASS} priv aes {_PRIVPASS}"
    ))
    assert "localized" not in out
    xe = get_codec("cisco_iosxe_cli")
    out = xe.render(xe.parse(
        f"snmp-server user monitor grp v3 auth sha {_PASS}"
    ))
    assert "encrypted" not in out
