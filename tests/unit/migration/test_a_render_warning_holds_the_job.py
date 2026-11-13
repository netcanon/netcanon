"""A record the target leaves out, or writes otherwise than the source
states it, holds the job ``partial``.

A target says what it leaves out for a reason of its own in
``render_warnings``: a local user that holds no password, an account past
the one AOS-S has for its role, a DHCP pool it can be given no range for.
The validation report is made from the tree before the renderer decides,
so it does not list such a record, and the status was the report's
alone: a job that left an account out said ``completed`` whenever
nothing else held it.  Over the committed inputs, onto every public codec
with no port map, two dozen jobs did, half of them between two configs
of one codec, each for an account the target left out.  A warning is not
a status (AGENTS.md).

A credential the target cannot carry is the same: a password it does
not take, an SNMPv3 user whose key belongs to the source device, a
RADIUS secret it cannot re-use.  Each was a ``review:`` line in the
output and nothing in the job -- 92 jobs over the committed inputs,
onto every public codec with no port map, said ``completed`` with
such a line in them.  The renderer asks a
question of each credential and the codec asks the same one for the
warning (``takes_password``, ``refuses_snmpv3_user``,
``refuses_radius_secret`` on ``CodecBase``); the guard below holds the
two to each other by what they name, on every public codec.

Not held yet: a ``review:`` line of another kind with no warning beside
it (a VLAN FortiOS can give no parent, a value a target does not read
as one).
"""
from __future__ import annotations

from typing import Any

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalSNMPv3User,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan, run_plan_with_checked_names

pytestmark = pytest.mark.unit

_LEFT_OUT = "The target left out"

# An account the source gives no password: written without one it could
# log in with none, so no target writes it.
_NO_PASSWORD = {
    "arista_eos": "hostname s1\nusername ops nopassword\n",
    "cisco_iosxe_cli": "hostname s1\nusername ops privilege 15 nopassword\n",
}


def _plan(source: str, target: Any, text: str) -> MigrationJob:
    return run_plan_with_checked_names(get_codec(source), target, text, port_rename_map={})


class _Said:
    """A target that says *said* for every tree, and is otherwise the
    codec it stands in front of."""

    def __init__(self, codec: Any, said: list[str]) -> None:
        self._codec = codec
        self._said = said

    def __getattr__(self, name: str) -> Any:
        return getattr(self._codec, name)

    def render_warnings(self, tree: Any) -> list[str]:
        return list(self._said)


@pytest.mark.parametrize(("source", "target"), [
    ("arista_eos", "arista_eos"),
    ("arista_eos", "cisco_iosxe_cli"),
    ("cisco_iosxe_cli", "cisco_iosxe_cli"),
    ("cisco_iosxe_cli", "juniper_junos"),
])
def test_an_account_with_no_password_holds_it(source: str, target: str) -> None:
    job = _plan(source, get_codec(target), _NO_PASSWORD[source])
    said = [w for w in job.warnings if w.startswith('Local user "ops" is not written for ')]
    assert len(said) == 1, job.warnings
    # Nothing else holds it: the report is clean.
    assert job.validation is not None and job.validation.severity == "ok"
    assert job.status is MigrationJobStatus.partial
    assert job.error is not None and job.error.startswith(f"{_LEFT_OUT} 1 record(s)")


def test_a_job_with_nothing_left_out_is_completed() -> None:
    job = _plan("arista_eos", get_codec("arista_eos"), "hostname s1\n")
    assert job.warnings == []
    assert job.status is MigrationJobStatus.completed
    assert job.error is None


class TestTheStatusIsTheTargets:
    """The status follows what the target says, and nothing else: the
    same text is ``completed`` when the target says nothing, and
    ``partial`` when it says something."""

    def test_said_nothing(self) -> None:
        target = _Said(get_codec("arista_eos"), [])
        job = run_plan(get_codec("arista_eos"), target, "hostname s1\n")
        assert job.status is MigrationJobStatus.completed

    def test_said_two(self) -> None:
        target = _Said(get_codec("arista_eos"), ["one thing", "another"])
        job = run_plan(get_codec("arista_eos"), target, "hostname s1\n")
        assert job.status is MigrationJobStatus.partial
        assert job.error is not None and job.error.startswith(f"{_LEFT_OUT} 2 record(s)")
        assert job.warnings[-2:] == ["one thing", "another"]

    def test_the_account_is_completed_without_its_warning(self) -> None:
        """The account case is ``partial`` for its warning: taken away,
        the job that left the account out says ``completed`` again, as it
        did before."""
        target = _Said(get_codec("arista_eos"), [])
        job = run_plan(get_codec("arista_eos"), target, _NO_PASSWORD["arista_eos"])
        assert job.status is MigrationJobStatus.completed


def test_a_job_partial_for_another_reason_keeps_its_words_first() -> None:
    """Text nothing recognises is ``partial`` for that; what the target
    says is added after it."""
    target = _Said(get_codec("arista_eos"), ["one thing"])
    job = run_plan(get_codec("arista_eos"), target, "not a config at all\nnor this\n")
    assert job.status is MigrationJobStatus.partial
    assert job.error is not None
    assert job.error.startswith("No source constructs were recognized")
    assert f"{_LEFT_OUT} 1 record(s)" in job.error


def test_a_radius_secret_the_target_cannot_carry_holds_it() -> None:
    """The server is written and its secret is not: the job says which
    server, and is ``partial`` for it."""
    text = (
        "hostname s1\n"
        "radius server r1\n"
        " address ipv4 192.0.2.9 auth-port 1812 acct-port 1813\n"
        " key 7 0000FAKE\n"
    )
    job = _plan("cisco_iosxe_cli", get_codec("aruba_aoss"), text)
    lines = (job.rendered or "").splitlines()
    assert "radius-server host 192.0.2.9" in lines
    assert any("review:" in line and "192.0.2.9" in line for line in lines)
    said = [w for w in job.warnings if w.startswith("RADIUS server 192.0.2.9 ")]
    assert len(said) == 1, job.warnings
    assert "0000FAKE" not in said[0]
    assert job.status is MigrationJobStatus.partial


def test_a_review_line_with_no_warning_does_not_hold_it_yet() -> None:
    """A known limitation, pinned so that closing it fails here until
    this is taken out (CHANGELOG, Known limitations): a VLAN FortiOS can
    give no parent is a ``review:`` line and no warning, and the job
    says ``completed``."""
    job = _plan("arista_eos", get_codec("fortigate_cli"), "hostname s1\nvlan 10\n   name ten\n")
    assert any(
        "review:" in line and "VLAN 10 has no parent" in line
        for line in (job.rendered or "").splitlines()
    )
    assert job.warnings == []
    assert job.status is MigrationJobStatus.completed


def test_a_failed_job_is_not_made_partial() -> None:
    target = _Said(get_codec("arista_eos"), ["one thing"])
    job = run_plan(get_codec("arista_eos"), target, "hostname s1\n", transforms=[_raises])
    assert job.status is MigrationJobStatus.failed


def _raises(tree: Any) -> Any:
    raise ValueError("a transform that fails")


# ---------------------------------------------------------------------
# A credential the target cannot carry
# ---------------------------------------------------------------------
#
# Each record below carries a token of its own (a user's name, a
# server's address), so that a line of the output and a warning of the
# job can be told to be about it without reading either sentence.  The
# check is the relation both ways: a ``review:`` line that names the
# record has a warning that names it and the job is ``partial``; and a
# warning that names it stands beside a ``review:`` line -- a warning
# over an output that wrote the record as the source states it is a
# status raised over a right output.  (Beside one, not one naming the
# record: AOS-S writes a hashed password live and says once, naming the
# accounts, that the switch needs a setting first; its review line names
# the forms.)
#
# The trees are given to the target as built (``_Gives``): no parser has
# a hand in which forms reach a renderer.  None is a real secret.

#: Password forms as parsers store them.
_PASSWORDS = (
    "9 $9$fakeSalt$fakeScryptHashBody",
    "5 $1$fake$fakeMd5cryptBody",
    "$6$fakeSalt$fakeSha512cryptBody",
    "junos:$6$fakeSalt$fakeSha512cryptBody",
    "bcrypt:$2y$10$fakeBcryptBodyFakeBcryptBodyFakeB",
    "fortios:ENC fakeEncodedHash==",
    "sha1:0000fakehex",
    "sha256:0000fakehex",
    "6 fakeType6Body",
    "arista:sha512:$6$fakeSalt$fakeSha512cryptBody",
    "typedPasswordFake",
)

#: (source, auth protocol, auth key, auth kind, priv protocol, priv key).
_V3_USERS = (
    ("arista_eos", "sha", "fakePassphraseOne", "", "aes", "fakePassphraseTwo"),
    ("cisco_nxos", "sha", "0xfakeLocalisedKey", "", "aes", "0xfakeLocalisedKey2"),
    ("aruba_aoscx", "sha", "AQBfakeCiphertext", "", "aes", "AQBfakeCiphertext2"),
    ("fortigate_cli", "sha", "ENC fakeEncodedKey==", "", "aes", "ENC fakeEncodedKey2=="),
    ("dell_os10", "sha", "0xfakeLocalisedKey", "localised", "", ""),
    ("juniper_junos", "sha", "", "", "", ""),
    ("cisco_nxos", "", "", "", "aes", "0xfakeLocalisedKey3"),
    ("vyos", "sha", "0xfakeLocalisedKey", "", "", ""),
)

#: (source, key) of RADIUS servers.
_RADIUS_KEYS = (
    ("fortigate_cli", "fortios:ENC fakeEncodedBlob=="),
    ("cisco_iosxe_cli", "iosxe:7 0000FAKE"),
    ("arista_eos", "eos:7 0000FAKE"),
    ("aruba_aoss", "aoss:fakeBlob"),
    ("aruba_aoss", "plainSharedSecretFake"),
    ("opnsense", "plainSharedSecretFake"),
    ("arista_eos", "weird:fakeEnvelope"),
    # FortiOS's envelope on a value another platform's config gave: not
    # FortiOS's own, whatever it begins with.
    ("aruba_aoss", "fortios:ENC fakeForeignBlob=="),
)


class _Gives:
    """A source that gives *tree* for any text, and is otherwise the
    codec it stands in front of."""

    def __init__(self, codec: Any, tree: CanonicalIntent) -> None:
        self._codec = codec
        self._tree = tree

    def __getattr__(self, name: str) -> Any:
        return getattr(self._codec, name)

    def parse(self, text: str) -> CanonicalIntent:
        return self._tree.model_copy(deep=True)


def _credential_cases() -> list[tuple[str, str, CanonicalIntent]]:
    """(token, source codec, tree) for each credential record."""
    cases = []
    for i, hashed in enumerate(_PASSWORDS):
        token = f"zedu{i}"
        cases.append((token, "cisco_iosxe_cli", CanonicalIntent(
            hostname="s1", source_vendor="cisco_iosxe_cli",
            local_users=[CanonicalLocalUser(
                name=token, privilege_level=15, hashed_password=hashed,
            )],
        )))
    for i, (source, auth, akey, akind, priv, pkey) in enumerate(_V3_USERS):
        token = f"zedv{i}"
        cases.append((token, source, CanonicalIntent(
            hostname="s1", source_vendor=source,
            snmp=CanonicalSNMP(v3_users=[CanonicalSNMPv3User(
                name=token, group="grpz", auth_protocol=auth,
                auth_passphrase=akey, auth_kind=akind,
                priv_protocol=priv, priv_passphrase=pkey,
            )]),
        )))
    for i, (source, key) in enumerate(_RADIUS_KEYS):
        token = f"192.0.2.{70 + i}"
        cases.append((token, source, CanonicalIntent(
            hostname="s1", source_vendor=source,
            radius_servers=[CanonicalRADIUSServer(host=token, key=key)],
        )))
    return cases


def _named(token: str, text: str) -> bool:
    """Whether *text* names *token* as a word of its own, so that
    ``zedu1`` is not found in ``zedu10``."""
    return any(
        part.strip('"\'.,;:()[]{}<>=') == token for part in text.split()
    )


def _disagreements(job: Any, token: str) -> list[str]:
    """What is wrong between the output and the job about *token*."""
    lines = (job.rendered or "").splitlines()
    review = [line for line in lines if "review:" in line and _named(token, line)]
    said = [w for w in job.warnings if _named(token, w)]
    wrong = []
    if review and not said:
        wrong.append(f"{token}: a review line and no warning")
    if review and job.status is not MigrationJobStatus.partial:
        wrong.append(f"{token}: a review line and the job is {job.status.value}")
    if said and not any("review:" in line for line in lines):
        wrong.append(f"{token}: a warning and no review line")
    return wrong


def _run(target: Any, source: str, tree: CanonicalIntent) -> MigrationJob:
    return run_plan(_Gives(get_codec(source), tree), target, "x\n")


#: How many of the records each target writes a ``review:`` line for,
#: compared for equality: a check that is never given a review line
#: passes, and a change of policy is seen here.
_REVIEWED = {
    "arista_eos": 17,
    "aruba_aoscx": 15,
    "aruba_aoss": 18,
    "cisco_iosxe": 0,
    "cisco_iosxe_cli": 19,
    "cisco_iosxr": 5,
    "cisco_nxos": 14,
    "dell_os10": 12,
    "fortigate_cli": 19,
    "juniper_junos": 13,
    "mikrotik_routeros": 22,
    "opnsense": 12,
    "vyos": 12,
}


def test_every_public_codec_is_counted() -> None:
    assert set(_REVIEWED) == set(list_public_codecs())


@pytest.mark.parametrize("target", sorted(_REVIEWED))
def test_a_credential_review_line_has_its_warning(target: str) -> None:
    wrong: list[str] = []
    reviewed = 0
    for token, source, tree in _credential_cases():
        job = _run(get_codec(target), source, tree)
        reviewed += any(
            "review:" in line and _named(token, line)
            for line in (job.rendered or "").splitlines()
        )
        wrong += _disagreements(job, token)
    assert wrong == []
    assert reviewed == _REVIEWED[target]


class _Silent(_Said):
    """A target that says nothing of credentials, and the rest of what
    the codec says."""

    def render_warnings(self, tree: Any) -> list[str]:
        codec = self._codec
        return [
            w for w in codec.render_warnings(tree)
            if not w.startswith(("Local user ", "SNMPv3 user ", "RADIUS server "))
        ]


class TestTheGuardCanFail:
    """Each check of :func:`_disagreements` is handed the defect it is
    for, and has to see it."""

    def test_a_review_line_with_no_warning(self) -> None:
        token, source, tree = _credential_cases()[0]
        job = _run(_Silent(get_codec("arista_eos"), []), source, tree)
        assert f"{token}: a review line and no warning" in _disagreements(job, token)

    def test_a_review_line_in_a_completed_job(self) -> None:
        token, source, tree = _credential_cases()[0]
        job = _run(_Silent(get_codec("arista_eos"), []), source, tree)
        assert job.status is MigrationJobStatus.completed
        assert f"{token}: a review line and the job is completed" in _disagreements(job, token)

    def test_a_warning_with_no_review_line(self) -> None:
        job = _run(
            _Said(get_codec("arista_eos"), ['Local user "zedq" is not written']),
            "arista_eos", CanonicalIntent(hostname="s1", source_vendor="arista_eos"),
        )
        assert "zedq: a warning and no review line" in _disagreements(job, "zedq")

    def test_a_token_is_a_word(self) -> None:
        assert _named("zedu1", 'user "zedu1" -- review: x')
        assert not _named("zedu1", 'user "zedu10" -- review: x')
        assert _named("192.0.2.70", "radius-server host 192.0.2.70")
        assert not _named("192.0.2.7", "radius-server host 192.0.2.70")


def test_a_held_aoss_account_with_no_name_is_said() -> None:
    """A tree can hold an account with no name; AOS-S writes a review
    line for it, and the job says so without a name to give."""
    tree = CanonicalIntent(
        hostname="s1", source_vendor="cisco_iosxe_cli",
        local_users=[CanonicalLocalUser(
            name="", privilege_level=15, hashed_password="typedPasswordFake",
        )],
    )
    job = _run(get_codec("aruba_aoss"), "cisco_iosxe_cli", tree)
    said = [w for w in job.warnings if w.startswith("A local user with no name ")]
    assert len(said) == 1, job.warnings
    assert "typedPasswordFake" not in said[0]
    assert job.status is MigrationJobStatus.partial


@pytest.mark.parametrize("target", sorted(_REVIEWED))
def test_no_warning_holds_a_secret(target: str) -> None:
    """A warning names a record and the form of its secret, never the
    secret: every fake value above has a word no sentence holds."""
    for _token, source, tree in _credential_cases():
        job = _run(get_codec(target), source, tree)
        for warning in job.warnings:
            assert "fake" not in warning.lower(), warning
            assert "0000FAKE" not in warning
