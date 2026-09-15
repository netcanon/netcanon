"""An unrecognised secret must never be re-emitted as a cleartext password.

``classify_hash`` used to end with "anything I don't recognise is a literal
plaintext password".  That is a fail-open default on credential material, and
it was not theoretical: a **bare Unix crypt string** — the form VyOS stores
natively — matched none of its three tagged shapes, so ``$6$...`` classified as
``plaintext``, ``is_migratable`` returned True, and the Arista render mapped
plaintext to ``secret 0``, EOS's CLEARTEXT marker.  The digest became the
password.

Measured before the fix, on the committed corpus:

====================  ========  ==================================
source form           records   classified as
====================  ========  ==================================
vyos bare ``$6$``           14   plaintext
aruba_aoscx ``AQB…``         4   plaintext
cisco_iosxr ``10 $6$…``      1   plaintext
====================  ========  ==================================

All three were re-emitted under a cleartext marker while both capability
matrices declared ``/local-users/user/hashed-password`` SUPPORTED — so the
migration reported no loss at all.  An operator got a config that looked
complete and carried a working credential in the clear.

The two halves of the fix are tested separately below because they are
independently load-bearing:

1. **Prefix-classify the crypt forms.**  Shrinks the unknown set so the
   common real-world hashes are recognised and routed to the correct
   target-side tag (or correctly refused).
2. **Refuse the unknown.**  Closes the door behind (1): the *next* secret
   format nobody has seen yet must fail closed, not open.

Order matters and is asserted by
:func:`test_genuine_plaintext_is_still_migratable`: flipping (2) without (1)
would refuse all 19 records above, which is a false-positive blast rather than
a fix.

⚠️ No digest body appears in this file.  Every fixture value is a synthetic
shape (salt ``S``\\ s, digest ``B``\\ s) of the right form and length class.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

from netcanon.migration._user_secrets import classify_hash, is_migratable

pytestmark = pytest.mark.unit

_REPO = pathlib.Path(__file__).resolve().parents[3]

# Synthetic stand-ins — correct shape, no real secret material.
_MD5CRYPT = "$1$" + "S" * 8 + "$" + "B" * 22
_SHA256CRYPT = "$5$" + "S" * 8 + "$" + "B" * 43
_SHA512CRYPT = "$6$" + "S" * 8 + "$" + "B" * 86
_BCRYPT = "$2y$10$" + "B" * 53
_YESCRYPT = "$y$j9T$" + "S" * 8 + "$" + "B" * 38
_IOSXR_T10 = "10 " + _SHA512CRYPT
_AOSCX_ENC = "AQB" + "b" * 181
_UNKNOWN_CRYPT = "$zz$" + "S" * 8 + "$" + "B" * 40


# ---------------------------------------------------------------------------
# Part 1 — the crypt forms are recognised, not mistaken for plaintext
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("hashed", "label"),
    [
        (_MD5CRYPT, "bare $1$ md5crypt"),
        (_SHA256CRYPT, "bare $5$ sha256crypt"),
        (_SHA512CRYPT, "bare $6$ sha512crypt (VyOS native)"),
        (_BCRYPT, "bare $2y$ bcrypt"),
        (_YESCRYPT, "bare $y$ yescrypt"),
        (_IOSXR_T10, "IOS-XR type-10"),
        (_AOSCX_ENC, "AOS-CX AQB ciphertext"),
        (_UNKNOWN_CRYPT, "unknown $zz$ crypt variant"),
    ],
)
def test_structured_secret_is_never_classified_plaintext(hashed, label) -> None:
    """None of these is a password a human typed.

    Classifying any of them ``plaintext`` licenses every downstream codec to
    emit it under a cleartext marker, because ``is_migratable`` short-circuits
    to True for plaintext on every target.
    """
    algorithm, _payload = classify_hash(hashed)
    assert algorithm != "plaintext", (
        f"{label} classified as plaintext — this is the fail-open default that "
        f"let a digest be re-emitted as the password itself"
    )


def test_sha256crypt_is_not_confused_with_aruba_hex_sha256() -> None:
    """``$5$`` must NOT classify as the token AOS-S accepts.

    ``aruba_aoss`` accepts ``sha256`` — meaning a raw hex digest its
    ``password manager`` command ingests verbatim, NOT a crypt(3) ``$5$``
    string.  Reusing the ``sha256`` token for sha256crypt would hand AOS-S a
    value it cannot consume while passing the migratability gate: a new
    fail-open in the shape of a fix.
    """
    algorithm, _ = classify_hash(_SHA256CRYPT)
    assert algorithm != "sha256", (
        "sha256crypt must use a token distinct from AOS-S's hex `sha256`"
    )
    assert not is_migratable(_SHA256CRYPT, "aruba_aoss")


@pytest.mark.parametrize(
    ("hashed", "target", "label"),
    [
        (_SHA512CRYPT, "arista_eos", "EOS consumes $6$ as `secret sha512`"),
        (_SHA512CRYPT, "juniper_junos", "Junos commit-hasher accepts $6$"),
        (_MD5CRYPT, "arista_eos", "EOS consumes $1$ as `secret 5`"),
        (_MD5CRYPT, "cisco_iosxe_cli", "IOS-XE consumes $1$ as `secret 5`"),
        (_BCRYPT, "opnsense", "OPNsense is FreeBSD/PHP-style bcrypt"),
    ],
)
def test_recognised_crypt_forms_stay_migratable_where_the_target_can_take_them(
    hashed, target, label
) -> None:
    """Recognising a form must not make it *less* usable.

    Part 1 exists to route these correctly, not to refuse everything.  If this
    goes red the fix has over-corrected into a denial-of-migration.
    """
    assert is_migratable(hashed, target), label


@pytest.mark.parametrize(
    ("hashed", "target"),
    [
        (_SHA512CRYPT, "aruba_aoss"),
        (_SHA512CRYPT, "mikrotik_routeros"),
        (_SHA512CRYPT, "fortigate_cli"),
        (_SHA256CRYPT, "arista_eos"),
        (_YESCRYPT, "arista_eos"),
        (_IOSXR_T10, "arista_eos"),
        (_AOSCX_ENC, "aruba_aoss"),
        (_AOSCX_ENC, "arista_eos"),
        (_UNKNOWN_CRYPT, "arista_eos"),
    ],
)
def test_unconsumable_secret_is_refused(hashed, target) -> None:
    """A target that cannot consume the form must refuse it.

    Refusal is what makes the codec emit a review comment telling the operator
    to reset the password, instead of silently writing a broken or cleartext
    credential.
    """
    assert not is_migratable(hashed, target)


# ---------------------------------------------------------------------------
# Part 2 — the door stays shut behind Part 1
# ---------------------------------------------------------------------------

def test_unknown_is_refused_by_every_known_target() -> None:
    """The *next* unseen format must fail closed.

    Part 1 shrinks the unknown set; it cannot empty it.  This is the assertion
    that survives the next vendor introducing a hash nobody has modelled.
    """
    from netcanon.migration._user_secrets import _TARGET_ACCEPTS

    algorithm, _ = classify_hash(_UNKNOWN_CRYPT)
    for target in _TARGET_ACCEPTS:
        assert not is_migratable(_UNKNOWN_CRYPT, target), (
            f"unknown secret form (classified {algorithm!r}) is migratable to "
            f"{target} — the fail-open default is back"
        )


def test_no_target_accept_set_contains_the_unknown_sentinel() -> None:
    """Belt and braces: the sentinel must never be added to an accept set.

    ``is_migratable`` is a membership test, so adding the sentinel to any
    target's set would silently reopen the hole this module exists to close.
    """
    from netcanon.migration._user_secrets import _TARGET_ACCEPTS, _UNKNOWN

    for target, accepted in _TARGET_ACCEPTS.items():
        assert _UNKNOWN not in accepted, (
            f"{target} accepts the unknown-secret sentinel {_UNKNOWN!r}"
        )


def test_genuine_plaintext_is_still_migratable() -> None:
    """A password a human actually typed is still a password.

    The corpus has one: a 5-character alphanumeric secret on an AOS-CX
    ``admin`` account.  Refusing *everything* unrecognised would have caught it
    too — which is why the rule keys on structured-secret shape (a ``$``-form
    or a known vendor ciphertext prefix) rather than on "did I recognise it".
    """
    for target in ("arista_eos", "aruba_aoss", "mikrotik_routeros"):
        assert is_migratable("h0rse", target)
        assert is_migratable("plaintext", target)
    assert classify_hash("h0rse") == ("plaintext", "h0rse")


def test_empty_secret_is_still_plaintext() -> None:
    """Empty stays empty — no accidental refusal of an absent password."""
    assert classify_hash("") == ("plaintext", "")


# ---------------------------------------------------------------------------
# The behavioural regression, end to end
# ---------------------------------------------------------------------------

def _render_users(source_codec: str, target_codec: str, fixture_dir: str):
    """Yield rendered ``username`` lines for every fixture in a directory."""
    import netcanon.migration.codecs as _c  # noqa: F401  (registry population)
    from netcanon.migration.codecs.registry import get_codec

    src, tgt = get_codec(source_codec), get_codec(target_codec)
    root = _REPO / "tests" / "fixtures" / "real" / fixture_dir
    for fx in sorted(root.glob("*")):
        if not fx.is_file():
            continue
        try:
            intent = src.parse(fx.read_text(encoding="utf-8", errors="replace"))
            out = tgt.render(intent)
        except Exception:  # pragma: no cover - a parse break is another test's job
            continue
        for line in out.splitlines():
            if line.strip().startswith("username"):
                yield fx.name, line.strip()


@pytest.mark.skipif(sys.platform == "emscripten", reason="filesystem fixtures")
def test_vyos_secrets_never_render_under_the_eos_cleartext_marker() -> None:
    """The defect, stated as the operator sees it.

    ``secret 0`` is EOS's CLEARTEXT marker.  Before the fix this fired on 14 of
    14 password-bearing vyos records — 100%, no exception.
    """
    offenders = [
        (name, re.sub(r"(secret\s+\S+\s+)\S+", r"\1<REDACTED>", line))
        for name, line in _render_users("vyos", "arista_eos", "vyos")
        if re.search(r"\bsecret\s+0\b", line)
    ]
    assert not offenders, (
        "VyOS secrets rendered under EOS's cleartext `secret 0` marker — the "
        f"digest becomes the password: {offenders[:3]}"
    )


@pytest.mark.skipif(sys.platform == "emscripten", reason="filesystem fixtures")
def test_iosxr_type10_never_renders_the_type_number_as_the_password() -> None:
    """``secret 0 10 <hash>`` makes the literal string ``10`` the password.

    EOS reads the token after the cleartext marker as the password, so the
    leftover IOS-XR type number became the credential and the SHA-512 body
    trailed as garbage.
    """
    offenders = [
        (name, re.sub(r"(secret\s+\S+\s+)\S+", r"\1<REDACTED>", line))
        for name, line in _render_users("cisco_iosxr", "arista_eos", "cisco_iosxr")
        if re.search(r"\bsecret\s+0\s+10\b", line)
    ]
    assert not offenders, f"IOS-XR type-10 rendered as cleartext: {offenders[:3]}"


@pytest.mark.skipif(sys.platform == "emscripten", reason="filesystem fixtures")
def test_aoscx_ciphertext_is_not_retyped_as_an_aos_s_plaintext_password() -> None:
    """AOS-S's ``plaintext "<value>"`` form is a cleartext marker too.

    The AOS-CX ``AQB…`` blob is encrypted vendor ciphertext; re-emitting it
    behind ``plaintext`` both breaks the account and writes secret-bearing
    material onto a line that claims to be cleartext.
    """
    import netcanon.migration.codecs as _c  # noqa: F401
    from netcanon.migration.codecs.registry import get_codec

    src, tgt = get_codec("aruba_aoscx"), get_codec("aruba_aoss")
    root = _REPO / "tests" / "fixtures" / "real" / "aruba_aoscx"
    offenders = []
    for fx in sorted(root.glob("*")):
        if not fx.is_file():
            continue
        try:
            out = tgt.render(src.parse(fx.read_text(encoding="utf-8", errors="replace")))
        except Exception:  # pragma: no cover
            continue
        for line in out.splitlines():
            if "plaintext" in line and "AQB" in line:
                offenders.append((fx.name, re.sub(r"AQB\S+", "AQB<REDACTED>", line.strip())))
    assert not offenders, (
        f"AOS-CX ciphertext re-typed as an AOS-S plaintext password: {offenders[:3]}"
    )


# ---------------------------------------------------------------------------
# Every render path gates — the second route to the same leak
# ---------------------------------------------------------------------------
#
# Classification alone does not close the leak: a codec that renders users
# WITHOUT calling ``is_migratable`` accepts whatever it is handed.
# ``aruba_aoscx``, ``cisco_iosxr``, ``cisco_nxos`` and ``vyos`` did exactly
# that.  Rendering the committed corpus put 61 source secrets behind NX-OS's
# ``password 0`` and 61 behind IOS-XR's ``secret 0`` — both cleartext markers —
# and wrote 116 (VyOS) / 93 (AOS-CX) values into hash slots that could not
# authenticate.  The tests below are shaped so the NEXT codec to skip the gate
# goes red too, not just these four.

#: Every codec that renders local users.  ``cisco_iosxe`` (the NETCONF stub)
#: models no AAA subtree and is deliberately absent.
_USER_RENDERING_TARGETS = (
    "arista_eos", "aruba_aoss", "aruba_aoscx", "cisco_iosxe_cli", "cisco_iosxr",
    "cisco_nxos", "fortigate_cli", "juniper_junos", "mikrotik_routeros",
    "opnsense", "vyos",
)


def _intent_with_users(*secrets: str):
    """A real parsed intent whose local users carry exactly ``secrets``."""
    import netcanon.migration.codecs as _c  # noqa: F401
    from netcanon.migration.canonical.intent import CanonicalLocalUser
    from netcanon.migration.codecs.registry import get_codec

    fx = _REPO / "tests" / "fixtures" / "synthetic" / "vyos"
    intent = get_codec("vyos").parse(next(p for p in sorted(fx.glob("kitchen_sink*"))).read_text(
        encoding="utf-8"))
    intent.local_users = [
        CanonicalLocalUser(name=f"u{i}", privilege_level=15, hashed_password=s, role="admin")
        for i, s in enumerate(secrets)
    ]
    return intent


@pytest.mark.parametrize("target", _USER_RENDERING_TARGETS)
def test_every_user_rendering_codec_refuses_an_unmodelled_secret(target) -> None:
    """No target accepts an unmodelled ``$id$`` form, so no render may emit it.

    The digest body must not appear ANYWHERE in the output — not behind a
    cleartext marker, not in a hash slot, not in a comment.  A codec that
    renders users without consulting the gate fails this on the first run.
    """
    from netcanon.migration.codecs.registry import get_codec

    out = get_codec(target).render(_intent_with_users(_UNKNOWN_CRYPT))
    assert "B" * 40 not in out, (
        f"{target} rendered an unmodelled secret it cannot consume — its user "
        f"render path does not call is_migratable()"
    )


def test_nxos_type5_is_classified_by_its_payload_not_as_md5crypt() -> None:
    """NX-OS writes EVERY crypt form under ``password 5``, and defaults to $5$.

    Tagging ``5 $5$…`` as Cisco type-5 MD5 crypt told EOS and IOS-XE it was a
    ``secret 5`` they could consume, so it passed the gate and produced an
    account nobody could log in to.  All 10 NX-OS corpus secrets have this
    shape.
    """
    assert classify_hash("5 " + _SHA256CRYPT) == ("sha256crypt", _SHA256CRYPT)
    assert classify_hash("5 " + _SHA512CRYPT) == ("sha512", _SHA512CRYPT)
    assert classify_hash("5 " + _MD5CRYPT) == ("5", _MD5CRYPT)  # IOS type 5 unchanged
    for target in ("arista_eos", "cisco_iosxe_cli"):
        assert not is_migratable("5 " + _SHA256CRYPT, target), target
    for target in ("cisco_nxos", "vyos"):
        assert is_migratable("5 " + _SHA256CRYPT, target), target


@pytest.mark.parametrize(
    ("module", "table", "target"),
    [
        ("netcanon.migration.codecs.cisco_nxos.render", "_NXOS_PASSWORD_TYPE", "cisco_nxos"),
        ("netcanon.migration.codecs.cisco_iosxr.render", "_IOSXR_SECRET_FORM", "cisco_iosxr"),
    ],
)
def test_emit_table_mirrors_the_accept_set_exactly(module, table, target) -> None:
    """An accepted token with no emit form would crash the render (KeyError);
    an emit form with no accepted token is dead code that hides a policy gap."""
    import importlib

    from netcanon.migration._user_secrets import _TARGET_ACCEPTS

    assert set(getattr(importlib.import_module(module), table)) == set(_TARGET_ACCEPTS[target])


@pytest.mark.parametrize(
    ("target", "secret", "must_contain", "must_not_contain"),
    [
        # A consumable crypt string is re-tagged into the target's native form.
        ("cisco_iosxr", _SHA512CRYPT, "secret 10 $6$", "secret 0"),
        ("cisco_nxos", "5 " + _SHA256CRYPT, "password 5 $5$", "password 0"),
        ("vyos", "5 " + _MD5CRYPT, "encrypted-password $1$", "encrypted-password 5"),
        # Genuine plaintext goes to the leaf that means plaintext.
        ("vyos", "h0rse", "plaintext-password h0rse", "encrypted-password h0rse"),
        ("aruba_aoscx", "h0rse", "password plaintext h0rse", "password ciphertext h0rse"),
        # An unconsumable secret is refused — review comment, no account line.
        ("cisco_nxos", _BCRYPT, "review:", "B" * 40),
        ("cisco_iosxr", _BCRYPT, "review:", "B" * 40),
        ("vyos", _AOSCX_ENC, "review:", "b" * 40),
        ("aruba_aoscx", _SHA512CRYPT, "review:", "B" * 40),
    ],
)
def test_newly_gated_codecs_emit_the_right_form(
    target, secret, must_contain, must_not_contain
) -> None:
    from netcanon.migration.codecs.registry import get_codec

    out = get_codec(target).render(_intent_with_users(secret))
    assert must_contain in out
    assert must_not_contain not in out


@pytest.mark.parametrize(
    ("target", "secret"),
    [("vyos", "h0rse"), ("aruba_aoscx", "h0rse"), ("cisco_iosxr", "7 0822455D0A16")],
)
def test_new_emit_forms_round_trip_through_their_own_parser(target, secret) -> None:
    """A form the render now writes must be one its own parser reads back."""
    from netcanon.migration.codecs.registry import get_codec

    codec = get_codec(target)
    back = codec.parse(codec.render(_intent_with_users(secret)))
    assert [u.hashed_password for u in back.local_users] == [secret]
