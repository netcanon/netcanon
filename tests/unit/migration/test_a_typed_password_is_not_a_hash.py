"""A password a human typed is written where the target takes one, or nowhere.

A canonical secret the policy calls ``plaintext`` is a password as it was
typed (IOS-XE ``password 0``, AOS-CX ``password plaintext``, VyOS
``plaintext-password``, ...).  Every target but two has a line that takes
such a password and hashes it itself.  Junos and OPNsense have none: the
Junos renderer wrote it as ``authentication encrypted-password "<typed>"``
and the OPNsense renderer into ``<password>``, the two places each keeps a
HASH -- so the typed string became the hash of an account no password
opens, in a job that reported nothing.  The shared gate let it through
because ``plaintext`` was "implicitly accepted by every target".

The guard reads the OUTPUT as text with a table typed here by hand, from
each vendor's own grammar for a typed password, never from the renderers:
every line that holds the typed value must be that target's form for one,
and where the target has no form the value is in no line and the account
is in no line but a comment.  Then, where the target's parser reads a
password back, it must read the typed one as typed.

See also ``test_secret_fail_open.py`` (a digest must never be written as a
typed password -- the same rule, the other way round).
"""

from __future__ import annotations

import pathlib
import re

import pytest

import netcanon.migration.codecs  # noqa: F401  (registers the codecs)
from netcanon.migration._user_secrets import classify_hash, is_migratable
from netcanon.migration.canonical.intent import CanonicalLocalUser
from netcanon.migration.codecs.registry import get_codec, list_public_codecs

pytestmark = pytest.mark.unit

_REPO = pathlib.Path(__file__).resolve().parents[3]

_TYPED = "zqTyped9"
_NAME = "zqtyped"

#: Each target's line for a password as typed, from the vendor's grammar.
#: ``None``: the target's config holds a password only as a hash.
#:
#: * EOS ``username <name> secret 0 <password>`` (0: "the password is
#:   entered as clear text").
#: * AOS-CX ``user <name> group <group> password plaintext <password>``.
#: * AOS-S ``password manager user-name <name> plaintext <password>``.
#: * IOS-XE ``username <name> secret 0 <password>`` (0: unencrypted).
#: * IOS XR ``secret 0 <password>`` under ``username <name>``.
#: * NX-OS ``username <name> password 0 <password>`` (0: clear text).
#: * OS10 ``username <name> password <password> role <role>``: the
#:   switch takes the password in clear text and stores a hash.
#: * FortiOS ``set password <password>`` under ``edit "<name>"``.
#: * RouterOS ``/user add name=<name> password=<password>``.
#: * VyOS ``authentication plaintext-password <password>``.
#: * Junos: ``encrypted-password`` takes a hash; ``plain-text-password``
#:   takes no value and asks at a prompt.  (``plain-text-password-value``
#:   is a hidden command no Juniper page documents.)
#: * OPNsense: ``<password>`` is the hash PHP's ``password_verify()``
#:   checks a password against.
_TYPED_FORM: dict[str, re.Pattern[str] | None] = {
    "arista_eos": re.compile(rf"^username {_NAME}\b.* secret 0 {_TYPED}$"),
    "aruba_aoscx": re.compile(
        rf"^user {_NAME} group \S+ password plaintext {_TYPED}$"
    ),
    "aruba_aoss": re.compile(
        rf'^password manager user-name "?{_NAME}"? plaintext "?{_TYPED}"?$'
    ),
    "cisco_iosxe_cli": re.compile(rf"^username {_NAME}\b.* secret 0 {_TYPED}$"),
    "cisco_iosxr": re.compile(rf"^ secret 0 {_TYPED}$"),
    "cisco_nxos": re.compile(rf"^username {_NAME} password 0 {_TYPED}( |$)"),
    "dell_os10": re.compile(rf"^username {_NAME} password {_TYPED} role "),
    "fortigate_cli": re.compile(rf"^ *set password {_TYPED}$"),
    "mikrotik_routeros": re.compile(rf"^add .*\bpassword={_TYPED}( |$)"),
    "vyos": re.compile(rf"^ *plaintext-password {_TYPED}$"),
    "juniper_junos": None,
    "opnsense": None,
}

#: Cells known to fail, each mended by another change.  Compared for
#: equality with what is measured, so the change that mends one fails
#: here until its pin is taken out.
_MENDED_ELSEWHERE: dict[str, str] = {
    # ``set password ENC <typed>``: ENC says the value is FortiOS's own
    # ciphertext.  #533 writes ``set password <typed>``; whichever of it
    # and this change merges second takes this pin out.
    "fortigate_cli": "#533",
}

#: Targets whose parser does not read an account's password back.
_NOT_READ_BACK: dict[str, str] = {
    "mikrotik_routeros": "the RouterOS parser reads no `password=`",
    "fortigate_cli": "read as `fortios:ENC ...` until #533",
}

#: The comment markers of every target's grammar, XML's included.
_COMMENT_MARKERS = ("!", "#", ";", "/*", "//", "<!--")


def _intent_with_a_typed_password():
    """A real parsed intent whose one local user has a typed password."""
    fx = _REPO / "tests" / "fixtures" / "synthetic" / "vyos" / "kitchen_sink.conf"
    intent = get_codec("vyos").parse(fx.read_text(encoding="utf-8"))
    intent.local_users = [
        CanonicalLocalUser(
            name=_NAME, privilege_level=15, hashed_password=_TYPED, role="admin",
        )
    ]
    return intent


_CALLS = {"n": 0}


def _findings(target: str, out: str) -> list[str]:
    """What is wrong with how *out* writes the typed password, as text."""
    _CALLS["n"] += 1
    form = _TYPED_FORM[target]
    lines = out.splitlines()
    holding = [ln for ln in lines if _TYPED in ln]
    named = [
        ln for ln in lines
        if _NAME in ln and not ln.lstrip().startswith(_COMMENT_MARKERS)
    ]
    if form is None:
        found = [f"the typed password is in a line: {ln.strip()!r}" for ln in holding]
        found += [f"the account is written: {ln.strip()!r}" for ln in named]
        if not any("review" in ln and _NAME in ln for ln in lines):
            found.append("no review line names the account")
        return found
    found = [
        f"the typed password is outside the target's form for one: {ln.strip()!r}"
        for ln in holding if not form.search(ln)
    ]
    if not holding:
        found.append("the typed password is in no line")
    if not named:
        found.append("the account is in no line")
    return found


def test_the_table_is_every_target_that_writes_users() -> None:
    """A target that renders local users is in the table, and only those."""
    writes_users = set()
    for name in list_public_codecs():
        out = get_codec(name).render(_intent_with_a_typed_password())
        if _NAME in out:
            writes_users.add(name)
    assert writes_users == set(_TYPED_FORM)


@pytest.mark.parametrize("target", sorted(_TYPED_FORM))
def test_a_typed_password_is_written_as_typed_or_not_at_all(target) -> None:
    out = get_codec(target).render(_intent_with_a_typed_password())
    found = _findings(target, out)
    if target in _MENDED_ELSEWHERE:
        assert found, f"{target} is mended: take out its pin ({_MENDED_ELSEWHERE[target]})"
        return
    assert found == []


@pytest.mark.parametrize("target", sorted(_TYPED_FORM))
def test_the_parser_reads_its_own_typed_password_back(target) -> None:
    """A target that takes a typed password reads it back as typed.

    The EOS parser read ``secret 0 <typed>`` as the algorithm ``0``, which
    no target takes: an EOS account with a typed password was refused on
    every target, EOS included.
    """
    if _TYPED_FORM[target] is None:
        pytest.skip("the target takes no typed password")
    if target in _NOT_READ_BACK:
        pytest.skip(_NOT_READ_BACK[target])
    codec = get_codec(target)
    back = [
        u for u in codec.parse(codec.render(_intent_with_a_typed_password())).local_users
        if u.name == _NAME
    ]
    assert len(back) == 1
    assert classify_hash(back[0].hashed_password) == ("plaintext", _TYPED)
    assert is_migratable(back[0].hashed_password, target)


def test_the_pins_are_what_is_measured() -> None:
    failing = {
        t for t in _TYPED_FORM
        if _findings(t, get_codec(t).render(_intent_with_a_typed_password()))
    }
    assert failing == set(_MENDED_ELSEWHERE)


@pytest.mark.parametrize(
    ("target", "out"),
    [
        # What the two renderers wrote before this change.
        ("juniper_junos",
         f"set system login user {_NAME} class super-user\n"
         f'set system login user {_NAME} authentication encrypted-password "{_TYPED}"\n'),
        ("opnsense",
         f"<user>\n  <name>{_NAME}</name>\n  <password>{_TYPED}</password>\n</user>\n"),
        # A review line that quotes the value.
        ("juniper_junos",
         f'# password manager user-name "{_NAME}" -- review: {_TYPED}\n'),
        # The value behind a hash marker of a target that has a typed form.
        ("cisco_iosxe_cli", f"username {_NAME} privilege 15 secret 5 {_TYPED}\n"),
        ("fortigate_cli", f'edit "{_NAME}"\n    set password ENC {_TYPED}\nnext\n'),
        # The account left out on a target that takes a typed password.
        ("vyos", "# review: nothing\n"),
    ],
)
def test_the_check_sees_each_defect(target, out) -> None:
    assert _findings(target, out)


def test_the_check_was_asked() -> None:
    before = _CALLS["n"]
    _findings("vyos", "")
    assert _CALLS["n"] == before + 1


# ---------------------------------------------------------------------------
# A parser that knows what a value is says so
# ---------------------------------------------------------------------------
#
# The AOS-CX parser read ``password ciphertext <value>`` and ``password
# plaintext <value>`` alike and kept the value bare, for the policy to read
# by its shape.  A committed capture whose publisher put a word in place of
# the ciphertext was then a password as typed, written onto every other
# target as one (``secret 0 <word>`` on IOS-XE).  The keyword decides.

_AQB = "AQB" + "b" * 60


@pytest.mark.parametrize(
    ("line", "algorithm", "payload"),
    [
        ("password ciphertext wordy", "aoscx_encrypted", "wordy"),
        (f"password ciphertext {_AQB}", "aoscx_encrypted", _AQB),
        ("password plaintext h0rse", "plaintext", "h0rse"),
        ("password plaintext AQBlooksEncrypted", "plaintext", "AQBlooksEncrypted"),
        ("password plaintext $a$b", "plaintext", "$a$b"),
    ],
)
def test_aoscx_reads_a_password_by_its_keyword(line, algorithm, payload) -> None:
    codec = get_codec("aruba_aoscx")
    tree = codec.parse(f"hostname sw1\nuser zq group administrators {line}\n")
    (user,) = tree.local_users
    assert classify_hash(user.hashed_password) == (algorithm, payload)
    # The form every AOS-CX tree held is kept where the shape agrees.
    if classify_hash(payload)[0] == algorithm:
        assert user.hashed_password == payload
    # Written back as it was read.
    assert f"user zq group administrators {line}" in codec.render(tree)
    # A ciphertext reaches no other target.
    if algorithm == "aoscx_encrypted":
        for target in sorted(_TYPED_FORM):
            if target != "aruba_aoscx":
                assert payload not in get_codec(target).render(tree), target


def test_the_capture_whose_ciphertext_is_a_word() -> None:
    """The GL CX 10.09 capture's ``admin`` reaches no other target."""
    text = (
        _REPO / "tests" / "fixtures" / "real" / "aruba_aoscx"
        / "netutils_aoscx_snmpv3_glcx1009.cfg"
    ).read_text(encoding="utf-8")
    word = re.search(r"^user admin group \S+ password ciphertext (\S+)", text, re.M).group(1)
    assert not word.startswith("AQB")
    tree = get_codec("aruba_aoscx").parse(text)
    (admin,) = [u for u in tree.local_users if u.name == "admin"]
    assert classify_hash(admin.hashed_password)[0] == "aoscx_encrypted"
    for target in sorted(_TYPED_FORM):
        if target == "aruba_aoscx":
            continue
        out = get_codec(target).render(tree)
        written = [ln for ln in out.splitlines() if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", ln)]
        assert written == [], target
