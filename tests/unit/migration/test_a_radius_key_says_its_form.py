"""A RADIUS key a platform stored in a form of its own is not another's secret.

Three parsers read a stored form as the secret itself, and the RADIUS
policy (:mod:`netcanon.migration._radius_secrets`) classifies a value
that carries no envelope, from a known source, as ``plaintext`` -- so
each target wrote the stored form into its literal-secret slot, a config
that commits and authenticates nobody, in a job that said ``completed``.
Measured on ``dae33113``, every case on every one of the six targets:

* IOS-XE ``key 7 <blob>`` and ``key 6 <blob>`` were the value
  ``7 <blob>``: the secret ``7 <blob>`` on AOS-S, FortiOS, OPNsense and
  RouterOS (the value IN it held the type; nothing read it).  ``key 0
  <secret>`` was the secret ``0 <secret>`` on those four.
* The legacy one-line ``radius-server host ... key 7 <blob>`` dropped the
  type, so an IOS-XE output wrote ``key <blob>``: the blob as plaintext,
  on the device's own platform.
* EOS ``key 7 <blob>`` -- the form EOS prints -- was the secret ``7`` on
  every target, EOS included; ``key 0 <secret>`` was the secret ``0``.
* AOS-S ``encrypted-key "<blob>"`` was the plaintext ``<blob>`` (the
  ``key`` pattern matched inside ``encrypted-key``) on every target,
  AOS-S included.
* And the other way: the FortiGate parser put every ``set secret`` behind
  ``fortios:``, a secret typed without ``ENC`` included, so the policy
  refused a portable secret on every other target.

The parser of each platform now carries a stored form behind its own
envelope (``iosxe:``, ``eos:``, ``aoss:``), which only that platform's
renderer writes, as the device wrote it; any other target keeps the
server and says why it has no key.

The output is read two ways: as TEXT, by patterns typed here from each
target's grammar, and with the target's own parser.  What each source
line means is typed beside it by hand, not read from the parser under
test.  Each check is handed the trees the parsers made before the
change, and fails.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration._radius_secrets import (
    AOSS_ENVELOPE,
    EOS_ENVELOPE,
    IOSXE_ENVELOPE,
    classify_radius_secret,
    stored_form,
)
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalRADIUSServer,
)
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan

pytestmark = pytest.mark.unit

TARGETS = (
    "cisco_iosxe_cli",
    "arista_eos",
    "aruba_aoss",
    "fortigate_cli",
    "opnsense",
    "mikrotik_routeros",
)

HOST = "192.0.2.10"
#: Not real secrets: distinctive markers, so that a leak is unambiguous.
PLAIN = "plainSharedSecretMarker"
BLOB7 = "0822455D0A16"
BLOB6 = "FakeAesBlobMarkerForTests"
BLOB64 = "RmFrZUVuY3J5cHRlZEtleU1hcmtlcg=="

_IOS = "hostname r1\n!\n{}\n!\nend\n"
_EOS = "hostname s1\n!\n{}\n!\nend\n"
_AOSS = 'hostname "s1"\n{}\n'
_IOS_STANZA = (
    "radius server A\n address ipv4 " + HOST
    + " auth-port 1812 acct-port 1813\n key {}"
)
_IOS_LEGACY = "radius-server host " + HOST + " auth-port 1812 acct-port 1813 key {}"
_EOS_LINE = "radius-server host " + HOST + " key {}"
_FGT = (
    'config user radius\n    edit "radius-1"\n        set server "' + HOST
    + '"\n        set secret {}\n    next\nend\n'
)

#: (case, source codec, config text, what the key line means).  The
#: meaning is ``("secret", <the secret>)`` or ``("stored", <type token>,
#: <blob>)``: a form only the source platform reads.
CASES = [
    ("ios-stanza-bare", "cisco_iosxe_cli", _IOS.format(_IOS_STANZA.format(PLAIN)), ("secret", PLAIN)),
    ("ios-stanza-0", "cisco_iosxe_cli", _IOS.format(_IOS_STANZA.format("0 " + PLAIN)), ("secret", PLAIN)),
    ("ios-stanza-7", "cisco_iosxe_cli", _IOS.format(_IOS_STANZA.format("7 " + BLOB7)), ("stored", "7", BLOB7)),
    ("ios-stanza-6", "cisco_iosxe_cli", _IOS.format(_IOS_STANZA.format("6 " + BLOB6)), ("stored", "6", BLOB6)),
    ("ios-legacy-bare", "cisco_iosxe_cli", _IOS.format(_IOS_LEGACY.format(PLAIN)), ("secret", PLAIN)),
    ("ios-legacy-0", "cisco_iosxe_cli", _IOS.format(_IOS_LEGACY.format("0 " + PLAIN)), ("secret", PLAIN)),
    ("ios-legacy-7", "cisco_iosxe_cli", _IOS.format(_IOS_LEGACY.format("7 " + BLOB7)), ("stored", "7", BLOB7)),
    ("eos-bare", "arista_eos", _EOS.format(_EOS_LINE.format(PLAIN)), ("secret", PLAIN)),
    ("eos-0", "arista_eos", _EOS.format(_EOS_LINE.format("0 " + PLAIN)), ("secret", PLAIN)),
    ("eos-7", "arista_eos", _EOS.format(_EOS_LINE.format("7 " + BLOB7)), ("stored", "7", BLOB7)),
    ("aoss-key", "aruba_aoss", _AOSS.format(f'radius-server host {HOST} key "{PLAIN}"'), ("secret", PLAIN)),
    (
        "aoss-encrypted-key", "aruba_aoss",
        _AOSS.format(f'radius-server host {HOST} encrypted-key "{BLOB64}"'),
        ("stored", "encrypted-key", BLOB64),
    ),
    (
        "aoss-global-key", "aruba_aoss",
        _AOSS.format(f'radius-server host {HOST}\nradius-server key "{PLAIN}"'),
        ("secret", PLAIN),
    ),
    (
        "aoss-global-encrypted-key", "aruba_aoss",
        _AOSS.format(f'radius-server host {HOST}\nradius-server encrypted-key "{BLOB64}"'),
        ("stored", "encrypted-key", BLOB64),
    ),
    ("fgt-typed", "fortigate_cli", _FGT.format(PLAIN), ("secret", PLAIN)),
    ("fgt-enc", "fortigate_cli", _FGT.format("ENC " + BLOB64), ("stored", "ENC", BLOB64)),
]

#: Where each target writes the secret as typed, typed from its grammar.
_SECRET_SLOT = {
    "cisco_iosxe_cli": "^ key {s}$",
    "arista_eos": "^radius-server host {h} key {s}$",
    "aruba_aoss": '^radius-server host {h} key "{s}"$',
    "fortigate_cli": "^ *set secret {s}$",
    "opnsense": "<radius_secret>{s}</radius_secret>",
    "mikrotik_routeros": "^add address={h} secret={s} ",
}

#: Where a platform writes its own stored form back, typed from its grammar.
_STORED_SLOT = {
    "cisco_iosxe_cli": "^ key {t} {b}$",
    "arista_eos": "^radius-server host {h} key {t} {b}$",
    "aruba_aoss": '^radius-server host {h} encrypted-key "{b}"$',
    "fortigate_cli": "^ *set secret {t} {b}$",
}

#: How a review line names each source platform's stored form.
_FORM_NAME = {
    ("cisco_iosxe_cli", "7"): "Cisco IOS-XE type 7",
    ("cisco_iosxe_cli", "6"): "Cisco IOS-XE type 6",
    ("arista_eos", "7"): "Arista EOS type 7",
    ("aruba_aoss", "encrypted-key"): "AOS-S encrypted-key",
    # The sentence the policy had before: encrypted under the device's key.
    ("fortigate_cli", "ENC"): None,
}


def _reread(target: str, output: str) -> list[str]:
    """The keys the target's own parser reads for HOST."""
    tree = get_codec(target).parse(output)
    return [server.key for server in tree.radius_servers if server.host == HOST]


def _check(source: str, meaning: tuple, target: str, output: str) -> None:
    """Hold *output* to what the source line meant (raises AssertionError)."""
    text = re.MULTILINE
    if meaning[0] == "secret":
        secret = meaning[1]
        slot = _SECRET_SLOT[target].format(h=re.escape(HOST), s=re.escape(secret))
        assert re.search(slot, output, text), (target, "the secret is not in its slot")
        assert _reread(target, output) == [secret], (target, "read back otherwise")
        return
    _, token, blob = meaning
    if target == source:
        slot = _STORED_SLOT[target].format(
            h=re.escape(HOST), t=re.escape(token), b=re.escape(blob),
        )
        assert re.search(slot, output, text), (target, "its own form is not written back")
        # Read back, the stored form is still not a secret anywhere else.
        keys = _reread(target, output)
        assert len(keys) == 1 and keys[0] != blob, (target, keys)
        assert classify_radius_secret(keys[0], source) == "encrypted", (target, keys)
        return
    assert blob not in output, (target, "a stored form was written for another platform")
    assert HOST in output, (target, "the server went with its key")
    reviews = [line for line in output.splitlines() if "review:" in line and HOST in line]
    assert len(reviews) == 1, (target, reviews)
    name = _FORM_NAME[(source, token)]
    said = f"({name})" if name else "encrypted under its own device key"
    assert said in reviews[0], (target, reviews[0])
    assert _reread(target, output) == [""], (target, "read back otherwise")


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize(
    ("source", "text", "meaning"),
    [pytest.param(src, txt, mean, id=case) for case, src, txt, mean in CASES],
)
def test_each_form_reaches_each_target_as_what_it_is(
    source: str, text: str, meaning: tuple, target: str,
) -> None:
    job = run_plan(get_codec(source), get_codec(target), text)
    assert job.rendered, job.error
    _check(source, meaning, target, job.rendered)


def test_a_secret_that_begins_with_a_type_is_written_as_a_secret() -> None:
    """A secret as typed that begins with digits and a space is written
    after ``key 0``: the device, and the parser, read ``key 7 abc`` as a
    type-7 ``abc``."""
    text = _AOSS.format(f'radius-server host {HOST} key "7 abc def"')
    output = run_plan(get_codec("aruba_aoss"), get_codec("cisco_iosxe_cli"), text).rendered
    assert re.search(r"^ key 0 7 abc def$", output, re.MULTILINE), output
    assert _reread("cisco_iosxe_cli", output) == ["7 abc def"]


def test_the_envelopes_are_encrypted_and_named() -> None:
    for value, form in (
        (f"{IOSXE_ENVELOPE}7 {BLOB7}", "Cisco IOS-XE type 7"),
        (f"{IOSXE_ENVELOPE}6 {BLOB6}", "Cisco IOS-XE type 6"),
        (f"{EOS_ENVELOPE}7 {BLOB7}", "Arista EOS type 7"),
        (f"{EOS_ENVELOPE}8a {BLOB6}", "Arista EOS type 8a"),
        (f"{AOSS_ENVELOPE}{BLOB64}", "AOS-S encrypted-key"),
        # The label holds the type the config wrote only where it is one.
        (f"{IOSXE_ENVELOPE}{'9' * 40} {BLOB7}", "Cisco IOS-XE type unknown"),
    ):
        assert classify_radius_secret(value, "anything") == "encrypted", value
        assert stored_form(value) == form, value
    assert stored_form(PLAIN) == ""
    assert stored_form("fortios:ENC x") == ""


# ---------------------------------------------------------------------------
# The checks fail on what the parsers made before
# ---------------------------------------------------------------------------


def _render_tree(source_vendor: str, key: str, target: str) -> str:
    tree = CanonicalIntent(
        source_vendor=source_vendor,
        radius_servers=[CanonicalRADIUSServer(host=HOST, key=key)],
    )
    return get_codec(target).render(tree)


#: (what the source line meant, the source codec, the tree's
#: ``source_vendor``, the value the parser gave on ``dae33113``, a target).
_BEFORE = [
    (("stored", "7", BLOB7), "cisco_iosxe_cli", "cisco_iosxe", f"7 {BLOB7}", "aruba_aoss"),
    (("stored", "7", BLOB7), "cisco_iosxe_cli", "cisco_iosxe", f"7 {BLOB7}", "mikrotik_routeros"),
    (("stored", "6", BLOB6), "cisco_iosxe_cli", "cisco_iosxe", f"6 {BLOB6}", "opnsense"),
    (("secret", PLAIN), "cisco_iosxe_cli", "cisco_iosxe", f"0 {PLAIN}", "fortigate_cli"),
    # The legacy form, which lost its type, back onto IOS-XE.
    (("stored", "7", BLOB7), "cisco_iosxe_cli", "cisco_iosxe", BLOB7, "cisco_iosxe_cli"),
    (("stored", "7", BLOB7), "arista_eos", "arista_eos", "7", "arista_eos"),
    (("stored", "7", BLOB7), "arista_eos", "arista_eos", "7", "aruba_aoss"),
    (("secret", PLAIN), "arista_eos", "arista_eos", "0", "cisco_iosxe_cli"),
    (("stored", "encrypted-key", BLOB64), "aruba_aoss", "aruba_aoss", BLOB64, "aruba_aoss"),
    (("stored", "encrypted-key", BLOB64), "aruba_aoss", "aruba_aoss", BLOB64, "cisco_iosxe_cli"),
    (("secret", PLAIN), "fortigate_cli", "fortigate", f"fortios:{PLAIN}", "aruba_aoss"),
]


@pytest.mark.parametrize(("meaning", "source", "vendor", "old", "target"), _BEFORE)
def test_each_check_fails_on_the_value_the_parser_gave_before(
    meaning: tuple, source: str, vendor: str, old: str, target: str,
) -> None:
    output = _render_tree(vendor, old, target)
    with pytest.raises(AssertionError):
        _check(source, meaning, target, output)


def test_the_parsers_no_longer_give_those_values() -> None:
    """The other half of the test above: each case's tree, now."""
    expected = {
        "ios-stanza-0": PLAIN,
        "ios-stanza-7": f"{IOSXE_ENVELOPE}7 {BLOB7}",
        "ios-stanza-6": f"{IOSXE_ENVELOPE}6 {BLOB6}",
        "ios-legacy-7": f"{IOSXE_ENVELOPE}7 {BLOB7}",
        "eos-0": PLAIN,
        "eos-7": f"{EOS_ENVELOPE}7 {BLOB7}",
        "aoss-encrypted-key": f"{AOSS_ENVELOPE}{BLOB64}",
        "aoss-global-encrypted-key": f"{AOSS_ENVELOPE}{BLOB64}",
        "fgt-typed": PLAIN,
        "fgt-enc": f"fortios:ENC {BLOB64}",
    }
    for case, source, text, _meaning in CASES:
        if case in expected:
            keys = [s.key for s in get_codec(source).parse(text).radius_servers]
            assert keys == [expected[case]], (case, keys)
