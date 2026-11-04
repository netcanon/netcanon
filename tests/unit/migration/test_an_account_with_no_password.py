"""No target writes an account the source gives no password.

An account written without a password is one that can log in with none.
EOS and IOS-XE wrote ``username <name> privilege 15 nopassword`` -- on
IOS-XE "No password is required for this user to log in", on EOS a login
from the console -- and every other target but AOS-S wrote the account
with no password line (a blank password on RouterOS and FortiOS), in
jobs that said ``completed``.  Committed inputs of several
source codecs hold such accounts, and a RouterOS export holds a password
for none.

Every renderer of local users asks
:func:`netcanon.migration._user_secrets.holds_no_secret` first and writes
a review line in place of the account, and the job warns for each
(``CodecBase.render_warnings``).  The tree does not say whether the
source MEANT an account with no password (EOS's own ``nopassword``) or
only printed none (a RouterOS export, a FortiOS admin for remote login),
so the rule holds between two configs of one platform as well.

The output is read three ways: as text (no line outside a comment names
the account, and one review line does), with the target's own parser (no
such account), and in the job's warnings (one for each).  The check is
handed each defect it is for (:class:`TestTheCheckFails`).

See also ``test_secret_fail_open.py`` (a secret the target cannot take
drops the account the same way) and
``codecs/aruba_aoss/test_one_account_per_role.py``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter

import pytest

import netcanon.migration.codecs  # noqa: F401  (registers the codecs)
from netcanon.migration._user_secrets import (
    format_no_secret_comment,
    format_review_comment,
    holds_no_secret,
    is_migratable,
)
from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalLocalUser
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan
from tests.unit.migration.codecs.aruba_aoss.test_one_account_per_role import _captures
from tests.unit.migration.test_secret_fail_open import (
    _COMMENT_MARKERS,
    _UNKNOWN_CRYPT,
    _USER_RENDERING_TARGETS,
    _outside_comments,
)

#: Values that hold no password: nothing, a tag with nothing after it,
#: a vendor tag and an algorithm with nothing after them, a type digit
#: alone.
_NO_SECRET = ("", "sha1:", "arista:sha512:", "5 ")

_NAMES = ("zqadmin", "zqoper")


#: What every review line for an account with no password says.
NO_SECRET_SAID = "no password for this account was read from the source"


def without_the_reviews_of(text: str, tree: CanonicalIntent) -> str:
    """*text* without the review line written in place of each account
    of *tree* that holds no password; each is there once.

    For a round trip on one codec: the first render writes such a line,
    and the re-parse has no account to write one for.
    """
    lines = text.splitlines(keepends=True)
    for user in tree.local_users:
        if not holds_no_secret(user.hashed_password):
            continue
        at = [
            i for i, line in enumerate(lines)
            if f'"{user.name}"' in line and NO_SECRET_SAID in line
        ]
        assert len(at) == 1, (user.name, len(at))
        del lines[at[0]]
    return "".join(lines)


def _tree(secret: str) -> CanonicalIntent:
    return CanonicalIntent(
        hostname="sw1",
        local_users=[
            CanonicalLocalUser(name="zqadmin", privilege_level=15, hashed_password=secret),
            CanonicalLocalUser(name="zqoper", privilege_level=1, hashed_password=secret),
        ],
    )


def _comments(text: str) -> list[str]:
    return [
        line for line in text.splitlines()
        if line.lstrip().startswith(_COMMENT_MARKERS)
    ]


def _names(name: str, line: str) -> bool:
    """Whether *line* holds *name* as a word of its own."""
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", line) is not None


_USERNAME = r"^username[ \t]+{n}(?![\w-])"

#: How each target writes an account, typed by hand from its grammar
#: rather than asked of its codec; ``{n}`` is the account's name.  A
#: capture's account is often named as something else is (``admin`` in
#: ``config system admin``, a group, a description), so a line counts
#: only where the target writes an account: the FortiOS pattern within
#: ``config system admin``, the RouterOS one under ``/user``, the VyOS
#: one in ``login`` (:func:`_in_scope`).  OPNsense is read as XML
#: (:func:`_accounts`).
_ACCOUNT_LINE: dict[str, str] = {
    "arista_eos": _USERNAME,
    "cisco_iosxe_cli": _USERNAME,
    "cisco_iosxr": _USERNAME,
    "cisco_nxos": _USERNAME,
    "dell_os10": _USERNAME,
    "aruba_aoscx": r"^user[ \t]+{n}(?![\w-])",
    "aruba_aoss": (
        r'^password[ \t]+(?:manager|operator)[ \t]+user-name[ \t]+"?{n}"?(?![\w-])'
    ),
    "juniper_junos": r'^set system login user "?{n}"?(?![\w-])',
    "fortigate_cli": r'^[ \t]*edit[ \t]+"?{n}"?[ \t]*$',
    "mikrotik_routeros": r'^add\b.*[ \t]name="?{n}"?(?:[ \t]|$)',
    "vyos": r'^[ \t]*user[ \t]+"?{n}"?[ \t]*\{',
}


def _in_scope(target: str, text: str) -> list[str]:
    """The lines of *text*, outside comments, where *target* writes its
    accounts."""
    lines = _outside_comments(text)
    if target == "fortigate_cli":
        kept: list[str] = []
        indent: str | None = None
        for line in lines:
            stripped = line.strip()
            lead = line[: len(line) - len(line.lstrip())]
            if indent is None:
                if stripped == "config system admin":
                    indent = lead
            elif stripped == "end" and lead == indent:
                indent = None
            else:
                kept.append(line)
        return kept
    if target == "mikrotik_routeros":
        kept, section = [], ""
        for line in lines:
            if line.startswith("/"):
                head, _, rest = line.partition(" add ")
                section = head.strip()
                if rest and section == "/user":
                    kept.append("add " + rest)
            elif section == "/user":
                kept.append(line)
        return kept
    if target == "vyos":
        kept, stack = [], []
        for line in lines:
            stripped = line.strip()
            if stripped.endswith("{"):
                if stack and stack[-1] == "login":
                    kept.append(line)
                stack.append(stripped[:-1].strip())
            elif stripped == "}" and stack:
                stack.pop()
        return kept
    return lines


def _accounts(target: str, text: str, name: str) -> list[str]:
    """Where *text*, written for *target*, writes an account *name*."""
    if target == "opnsense":
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []
        return [
            f"<user><name>{name}</name>"
            for system in root.iter("system")
            for user in system.findall("user")
            if (user.findtext("name") or "").strip() == name
        ]
    pattern = re.compile(_ACCOUNT_LINE[target].replace("{n}", re.escape(name)))
    return [line for line in _in_scope(target, text) if pattern.search(line)]


def wrong(target: str, text: str, warnings: list[str], names) -> list[str]:
    """What is wrong with *text* and *warnings* for accounts *names*,
    each of which the source gave no password.

    A synthetic name (``zq...``) is not otherwise in the output, so for
    one of those any line outside a comment that names it is wrong too.
    """
    said: list[str] = []
    try:
        read_back = {u.name for u in get_codec(target).parse(text).local_users}
    except Exception as exc:  # said, not raised
        said.append(f"the output does not parse: {type(exc).__name__}")
        read_back = set()
    for name in names:
        written = _accounts(target, text, name)
        if name.startswith("zq"):
            written += [
                line for line in _outside_comments(text)
                if _names(name, line) and line not in written
            ]
        if written:
            said.append(f"{name}: written as {written[:2]}")
        if name in read_back:
            said.append(f"{name}: the target's parser reads the account back")
        reviews = [
            line for line in _comments(text)
            if f'"{name}"' in line and "review:" in line and "no password" in line
        ]
        if len(reviews) != 1:
            said.append(f"{name}: {len(reviews)} review lines, not 1")
        told = [w for w in warnings if f'"{name}"' in w and "no password" in w]
        if len(told) != 1:
            said.append(f"{name}: {len(told)} warnings, not 1")
    return said


@pytest.mark.parametrize(
    ("value", "none"),
    [
        *((v, True) for v in _NO_SECRET),
        ("Typed-pw1", False),
        ("sha1:abc", False),
        ("arista:sha512:$6$s$h", False),
        ("$6$s$h", False),
        ("fortios:ENC abc", False),
        (_UNKNOWN_CRYPT, False),
    ],
)
def test_what_holds_no_password(value, none) -> None:
    assert holds_no_secret(value) is none


def test_the_targets_that_render_accounts_are_the_listed_ones() -> None:
    """A codec that writes local users is in ``_USER_RENDERING_TARGETS``,
    which every guard of a user's secret walks; one missing from it is
    asked nothing (OS10 was, until this list was checked)."""
    tree = CanonicalIntent(
        hostname="sw1",
        local_users=[
            CanonicalLocalUser(name="zqlisted", privilege_level=15, hashed_password="Typed-pw1"),
        ],
    )
    renders = {
        name for name in list_public_codecs()
        if "zqlisted" in get_codec(name).render(tree)
    }
    assert renders == set(_USER_RENDERING_TARGETS)


#: Secrets of three kinds, one of which each target takes.
_TAKEN = ("Typed-pw1", "$6$s$h", "$2y$10$" + "a" * 53)


def test_the_reader_has_a_form_for_each_target() -> None:
    assert set(_ACCOUNT_LINE) | {"opnsense"} == set(_USER_RENDERING_TARGETS)


@pytest.mark.parametrize("target", _USER_RENDERING_TARGETS)
def test_the_reader_sees_an_account_the_target_writes(target) -> None:
    """The reader is typed by hand: each form sees the account its
    target writes for a secret the target takes, or the check reads
    nothing.  ``admin`` is also the name of a FortiOS block."""
    secret = next(s for s in _TAKEN if is_migratable(s, target))
    for name in ("zqprobe", "admin"):
        tree = CanonicalIntent(
            hostname="sw1",
            local_users=[
                CanonicalLocalUser(name=name, privilege_level=15, hashed_password=secret),
            ],
        )
        out = get_codec(target).render(tree)
        assert _accounts(target, out, name), (target, name)


@pytest.mark.parametrize(
    ("target", "text", "others"),
    [
        (
            "fortigate_cli",
            'config system accprofile\n    edit "zqprobe"\n    next\nend\n'
            'config system admin\n    edit "other"\n    next\nend\n',
            1,
        ),
        (
            "mikrotik_routeros",
            "/user group\nadd name=zqprobe policy=read\n"
            "/user\nadd group=zqprobe name=other\n",
            1,
        ),
        (
            "vyos",
            "service {\n    snmp {\n        v3 {\n            user zqprobe {\n"
            "            }\n        }\n    }\n}\n"
            "system {\n    login {\n        user other {\n        }\n    }\n}\n",
            1,
        ),
        (
            "opnsense",
            "<opnsense><system><group><name>zqprobe</name></group>"
            "<user><name>other</name></user></system></opnsense>",
            1,
        ),
        (
            "juniper_junos",
            "set system login class zqprobe permissions all\n"
            "set snmp v3 usm local-engine user zqprobe\n",
            0,
        ),
    ],
)
def test_the_reader_reads_accounts_only(target, text, others) -> None:
    """A name that is something else's -- a profile, a group, an SNMP
    user -- is no account; the account beside it is."""
    assert _accounts(target, text, "zqprobe") == []
    assert len(_accounts(target, text, "other")) == others


@pytest.mark.parametrize("secret", _NO_SECRET)
@pytest.mark.parametrize("target", _USER_RENDERING_TARGETS)
def test_no_target_writes_an_account_with_no_password(target, secret) -> None:
    codec = get_codec(target)
    tree = _tree(secret)
    warnings = codec.render_warnings(tree)
    assert wrong(target, codec.render(tree), warnings, _NAMES) == []


def test_a_codec_that_writes_no_accounts_warns_of_none() -> None:
    """The default warning is for a codec that renders local users."""
    for name in set(list_public_codecs()) - set(_USER_RENDERING_TARGETS):
        assert get_codec(name).render_warnings(_tree("")) == [], name


@pytest.mark.parametrize("target", sorted(set(_USER_RENDERING_TARGETS) - {"aruba_aoss"}))
def test_a_review_line_is_in_no_targets_syntax(target) -> None:
    """The shared review line began with AOS-S's ``password manager
    user-name`` on every target, whatever the account's role; AOS-S
    writes its own lines (``aruba_aoss/accounts.py``)."""
    tree = CanonicalIntent(
        hostname="sw1",
        local_users=[
            CanonicalLocalUser(name="zqnone", privilege_level=1, hashed_password=""),
            CanonicalLocalUser(name="zqref", privilege_level=1, hashed_password=_UNKNOWN_CRYPT),
        ],
    )
    out = get_codec(target).render(tree)
    assert "password manager" not in out
    assert "password operator" not in out
    assert sum(1 for line in _comments(out) if 'user "zqnone"' in line) == 1
    assert sum(1 for line in _comments(out) if 'user "zqref"' in line) == 1


@pytest.mark.parametrize("syntax", ["hash", "exclamation", "semicolon", "slash", "xml"])
def test_the_two_review_lines_share_their_subject(syntax) -> None:
    for line in (
        format_no_secret_comment("zq", syntax, "T"),
        format_review_comment("zq", "bcrypt", syntax, "T"),
    ):
        assert 'user "zq"' in line, line
        assert "\n" not in line


class TestTheCheckFails:
    """The check above is handed each defect it is for, and fails."""

    def _good(self) -> tuple[str, list[str]]:
        codec = get_codec("arista_eos")
        tree = _tree("")
        return codec.render(tree), codec.render_warnings(tree)

    def test_it_passes_the_good_output(self) -> None:
        text, warnings = self._good()
        assert wrong("arista_eos", text, warnings, _NAMES) == []

    def test_an_account_with_nopassword(self) -> None:
        text, warnings = self._good()
        text += "username zqadmin privilege 15 nopassword\n"
        said = wrong("arista_eos", text, warnings, _NAMES)
        assert any("written as" in s for s in said)
        assert any("reads the account back" in s for s in said)

    def test_an_account_the_parser_reads_back(self) -> None:
        text, warnings = self._good()
        text += "username zqoper nopassword\n"
        assert any(
            "reads the account back" in s
            for s in wrong("arista_eos", text, warnings, _NAMES)
        )

    def test_an_account_of_a_name_a_capture_gives(self) -> None:
        """A name that is not synthetic is read where the target writes
        accounts, and is found there."""
        text = 'config system admin\n    edit "admin"\n    next\nend\n'
        said = wrong("fortigate_cli", text, [], ["admin"])
        assert any("written as" in s for s in said), said

    def test_no_review_line(self) -> None:
        text, warnings = self._good()
        text = "\n".join(line for line in text.splitlines() if "zqadmin" not in line)
        assert any(
            "0 review lines" in s for s in wrong("arista_eos", text, warnings, _NAMES)
        )

    def test_two_review_lines(self) -> None:
        text, warnings = self._good()
        text += format_no_secret_comment("zqadmin", "exclamation", "Arista EOS") + "\n"
        assert any(
            "2 review lines" in s for s in wrong("arista_eos", text, warnings, _NAMES)
        )

    def test_no_warning(self) -> None:
        text, _warnings = self._good()
        assert any("0 warnings" in s for s in wrong("arista_eos", text, [], _NAMES))

    def test_a_warning_twice(self) -> None:
        text, warnings = self._good()
        assert any(
            "2 warnings" in s
            for s in wrong("arista_eos", text, warnings + warnings[:1], _NAMES)
        )


def test_every_committed_input_onto_every_target() -> None:
    """Every committed input that holds an account with no password,
    onto every public codec, through the pipeline: the job's output and
    its warnings are read as above."""
    found: list[str] = []
    asked: Counter[str] = Counter()
    sources: set[str] = set()
    for source, label, path in _captures():
        raw = path.read_text(encoding="utf-8")
        try:
            users = get_codec(source).parse(raw).local_users
        except Exception:  # a capture the parser refuses
            continue
        names = {u.name for u in users if holds_no_secret(u.hashed_password)}
        # A name another account of the input holds with a password is
        # not one this can read for.
        names -= {u.name for u in users if not holds_no_secret(u.hashed_password)}
        if not names:
            continue
        sources.add(source)
        for target in list_public_codecs():
            job = run_plan(get_codec(source), get_codec(target), raw)
            if job.rendered is None:
                asked["not rendered"] += 1
                continue
            asked["jobs"] += 1
            if target not in _USER_RENDERING_TARGETS:
                continue
            asked["read"] += 1
            for said in wrong(target, job.rendered, job.warnings, sorted(names)):
                found.append(f"{label} -> {target}: {said}")
    assert found == []
    # The inputs that hold such accounts, by source codec: one that no
    # longer reaches here leaves a guard that reads nothing.
    assert sources >= {
        "arista_eos", "fortigate_cli", "juniper_junos",
        "mikrotik_routeros", "opnsense", "vyos",
    }, sources
    assert asked["read"] > 0 and asked["not rendered"] == 0, asked
