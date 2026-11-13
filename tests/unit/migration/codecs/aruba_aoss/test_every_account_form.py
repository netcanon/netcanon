"""The AOS-S parser reads every account the switch prints.

An ArubaOS-Switch has ONE manager account and ONE operator account,
set by ``password manager`` / ``password operator``; a second line of a
role re-points the account, so the switch keeps the last (HPE Access
Security Guide, AOS-S 16.x).  Beside them it holds local users, each in
an authorization group (``aaa authentication local-user``).  The parser
read the ``password <role> user-name "<name>" <alg> "<value>"`` line
only, and each line as an account of its own:

* two lines of a role were two accounts, the one the switch replaced
  among them;
* the bare ``password manager`` a switch prints without
  ``include-credentials`` -- no name, no value -- was no account at all,
  nor a line that left out ``user-name``, as a switch whose names were
  never changed prints it;
* no ``aaa authentication local-user`` account was read.

Each form is read here as the switch prints or takes it, and every
committed input is held to a reader of its own (:func:`accounts_of`),
which is handed the old reading and has to fail.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration._user_secrets import holds_no_secret
from netcanon.migration.codecs.aruba_aoss import parse as aoss_parse
from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
INPUTS = sorted(
    list((FIXTURES / "real" / "aruba_aoss").glob("*.cfg"))
    + list((FIXTURES / "synthetic" / "aruba_aoss").glob("*.cfg"))
    + list((FIXTURES / "aruba_aoss").glob("*.txt"))
)

_REPLACED = 'password manager (a later "password manager" line sets the same account'
_REPLACED_USER = "aaa authentication local-user (a later line names the same user"
_OTHER_GROUP = "aaa authentication local-user ... group (a group other than"
_NO_ACCOUNT = "aaa authentication local-user (a line that sets no account"


def _parse(*lines: str):
    return ArubaAOSSCodec().parse('hostname "sw"\n' + "\n".join(lines) + "\n")


def _users(tree) -> list[tuple[str, int, str, str]]:
    return [(u.name, u.privilege_level, u.hashed_password, u.role) for u in tree.local_users]


def _rows(tree, start: str) -> list[str]:
    return [row for row in tree.dropped_tier3_sections if row.startswith(start)]


# ---------------------------------------------------------------------------
# The two accounts
# ---------------------------------------------------------------------------


def test_a_bare_marker_is_an_account_with_no_secret() -> None:
    """``include-credentials`` off: the switch says a role has a password,
    and neither its name nor the password."""
    tree = _parse("password manager", "password operator")
    assert _users(tree) == [("manager", 15, "", "manager"), ("operator", 1, "", "operator")]
    assert all(holds_no_secret(u.hashed_password) for u in tree.local_users)
    assert tree.dropped_tier3_sections == []


@pytest.mark.parametrize(
    ("line", "user"),
    [
        ('password manager user-name "admin" sha1 "ab12"', ("admin", 15, "sha1:ab12", "manager")),
        ('password operator user-name "noc" plaintext "Typed-pw1"', ("noc", 1, "plaintext:Typed-pw1", "operator")),
        # A switch whose name was never changed prints no user-name.
        ('password manager sha1 "ab12"', ("manager", 15, "sha1:ab12", "manager")),
        ("password operator sha256 cd34", ("operator", 1, "sha256:cd34", "operator")),
        # Typed: the name unquoted; ``plaintext`` with no value asks for it.
        ("password manager user-name admin plaintext", ("admin", 15, "plaintext:", "manager")),
        ('password manager user-name "admin"', ("admin", 15, "", "manager")),
        ('Password Manager user-name "admin" SHA1 "ab12"', ("admin", 15, "sha1:ab12", "manager")),
    ],
)
def test_each_form_of_the_line(line: str, user: tuple[str, int, str, str]) -> None:
    assert _users(_parse(line)) == [user]


@pytest.mark.parametrize(
    "line",
    ["password manager user-name", 'password manager user-name "a" sha1 "ab" more', "password minimum-length 8"],
)
def test_a_line_of_another_shape_is_no_account(line: str) -> None:
    assert _users(_parse(line)) == []


def test_the_last_line_of_a_role_is_its_account() -> None:
    tree = _parse(
        'password manager user-name "first" sha1 "11"',
        'password operator user-name "op" sha1 "22"',
        'password manager user-name "second" sha1 "33"',
        'password manager user-name "third" sha1 "44"',
    )
    assert _users(tree) == [("third", 15, "sha1:44", "manager"), ("op", 1, "sha1:22", "operator")]
    # One row for the two lines the switch replaced, naming no user and
    # no value.
    assert _rows(tree, "password manager") == [
        f'{_REPLACED}, as on the switch; not translated; 2 lines)'
    ]
    assert not any("first" in row or "11" in row for row in tree.dropped_tier3_sections)


def test_a_bare_marker_after_a_line_is_the_last() -> None:
    tree = _parse('password manager user-name "first" sha1 "11"', "password manager")
    assert _users(tree) == [("manager", 15, "", "manager")]
    assert len(_rows(tree, _REPLACED)) == 1


def test_a_wrapped_value_is_read_for_every_form() -> None:
    tree = _parse(
        'password manager user-name "admin" sha1',
        '   "ab12"',
        'aaa authentication local-user "u2" group "Level-15" password sha1',
        "",
        '   "cd34"',
    )
    assert _users(tree) == [("admin", 15, "sha1:ab12", "manager"), ("u2", 15, "sha1:cd34", "")]


# ---------------------------------------------------------------------------
# The local users
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "user"),
    [
        # include-credentials on (a 2530 prints the hash wrapped, or not).
        ('aaa authentication local-user "admin2" group "Level-15" password sha1 "ab12"',
         ("admin2", 15, "sha1:ab12", "")),
        # include-credentials off.
        ('aaa authentication local-user "admin2" group "Level-15"', ("admin2", 15, "", "")),
        # Typed: unquoted, and ``plaintext`` asks for the password.
        ("aaa authentication local-user admin2 group Level-1 password plaintext", ("admin2", 1, "plaintext:", "")),
        ("aaa authentication local-user admin2 group Level-9 password sha1 ab12", ("admin2", 9, "sha1:ab12", "")),
        ('aaa authentication local-user "admin2" group "Level-0" password sha256 "ef56"',
         ("admin2", 0, "sha256:ef56", "")),
    ],
)
def test_each_form_of_a_local_user(line: str, user: tuple[str, int, str, str]) -> None:
    tree = _parse(line)
    assert _users(tree) == [user]
    assert tree.dropped_tier3_sections == []


@pytest.mark.parametrize("level", range(16))
def test_a_level_group_is_its_privilege_level(level: int) -> None:
    tree = _parse(f'aaa authentication local-user "u" group "Level-{level}"')
    assert _users(tree) == [("u", level, "", "")]


@pytest.mark.parametrize("group", ["ADMINS", "manager", "operator", "level-15", "Level-16", "Level-07", "Level-1x"])
def test_any_other_group_is_level_one_and_said(group: str) -> None:
    """What another group allows is in rules that are not translated:
    the user is read with the fewer rights, and a row says so.  The
    group is no role of another platform's."""
    tree = _parse(f'aaa authentication local-user "u" group "{group}" password sha1 "ab"')
    assert _users(tree) == [("u", 1, "sha1:ab", "")]
    assert len(_rows(tree, _OTHER_GROUP)) == 1
    assert not any(group in row for row in tree.dropped_tier3_sections)


def test_the_last_line_of_a_user_is_its_account() -> None:
    tree = _parse(
        'aaa authentication local-user "a" group "Level-1"',
        'aaa authentication local-user "b" group "Level-15"',
        'aaa authentication local-user "a" group "Level-15" password sha1 "ab"',
        'aaa authentication local-user "A" group "Level-1"',
    )
    # Names are case-sensitive on the switch.
    assert _users(tree) == [("b", 15, "", ""), ("a", 15, "sha1:ab", ""), ("A", 1, "", "")]
    assert len(_rows(tree, _REPLACED_USER)) == 1


@pytest.mark.parametrize(
    "line",
    [
        'aaa authentication local-user "u" aging-period 30',
        'aaa authentication local-user "u" min-pwd-length 8',
        'aaa authentication local-user "u" clear-password-history',
        'aaa authentication local-user "u" group "Level-15" password sha 256 "ab"',
        "aaa authentication local-user",
    ],
)
def test_a_line_that_sets_no_account_is_said(line: str) -> None:
    tree = _parse(line)
    assert _users(tree) == []
    assert _rows(tree, _NO_ACCOUNT) == [f"{_NO_ACCOUNT}: a password policy, or a form not read; not translated)"]


def test_other_aaa_lines_are_not_accounts() -> None:
    """Other ``aaa`` lines are no account, and no row of an account's:
    each is said in the row of its command words, which shows no value
    of the line."""
    tree = _parse(
        "aaa authentication login privilege-mode",
        "aaa authentication local-users-only",
        'aaa authorization group "ADMINS" 100 match-command "configure" permit',
    )
    assert _users(tree) == []
    assert tree.dropped_tier3_sections == ["aaa authentication", "aaa authorization"]


# ---------------------------------------------------------------------------
# The order of the tree, and what AOS-S makes of it
# ---------------------------------------------------------------------------


def test_the_two_accounts_come_first() -> None:
    """A switch prints its local users above the two accounts; the
    renderer gives the manager slot to the first user of privilege 15,
    which has to be the manager's line."""
    raw = (
        'hostname "sw"\n'
        'aaa authentication local-user "localadmin" group "Level-15" password sha1 "11"\n'
        'password manager user-name "boss" sha1 "22"\n'
        'password operator user-name "op" sha1 "33"\n'
    )
    codec = ArubaAOSSCodec()
    tree = codec.parse(raw)
    assert [u.name for u in tree.local_users] == ["boss", "op", "localadmin"]
    out = codec.render(tree)
    live = [line for line in out.splitlines() if line.startswith("password ")]
    assert live == [
        'password manager user-name "boss" sha1 "22"',
        'password operator user-name "op" sha1 "33"',
    ]
    assert any(line.startswith('; password manager user-name "localadmin" -- review:') for line in out.splitlines())
    assert any('"localadmin"' in w for w in codec.render_warnings(tree))


def test_a_column_0_account_line_ends_a_stanza() -> None:
    """A line the top reads ends a stanza whose indentation was lost."""
    for line in ("password manager", 'aaa authentication local-user "u" group "Level-1"',
                 'aaa authentication local-user "u" min-pwd-length 8'):
        tree = _parse("vlan 2", 'name "two"', line, "untagged 1")
        vlan = next(v for v in tree.vlans if v.id == 2)
        assert vlan.untagged_ports == [], line


# ---------------------------------------------------------------------------
# Every committed input, held to a reader of the test's own
# ---------------------------------------------------------------------------

_ROLE_LINE = re.compile(r"^password[ \t]+(manager|operator)([ \t].*)?$", re.IGNORECASE)
_LOCAL_LINE = re.compile(r'^aaa[ \t]+authentication[ \t]+local-user[ \t]+("[^"]+"|\S+)[ \t]+group[ \t]', re.IGNORECASE)


def accounts_of(text: str) -> list[tuple[str, bool]]:
    """``(what, bare)`` for each account *text* sets, as the switch keeps
    them: the role of the last line of each role, ``manager`` first, and
    then each local user's name, the last line of a name counting.
    *bare*: the account's line names no algorithm (for a local user:
    no ``password``)."""
    roles: dict[str, bool] = {}
    users: dict[str, bool] = {}
    for line in text.splitlines():
        if not line or line[0].isspace():
            continue
        role = _ROLE_LINE.match(line.rstrip())
        if role:
            words = line.split()
            if "user-name" in [w.lower() for w in words]:
                at = [w.lower() for w in words].index("user-name")
                del words[at:at + 2]
            roles[role.group(1).lower()] = len(words) == 2
            continue
        local = _LOCAL_LINE.match(line)
        if local:
            name = local.group(1).strip('"')
            users.pop(name, None)
            users[name] = " password " not in f" {line.lower()} "
    return [(r, roles[r]) for r in ("manager", "operator") if r in roles] + list(users.items())


def _held(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    tree = ArubaAOSSCodec().parse(text)
    expected = accounts_of(text)
    got = []
    for user in tree.local_users:
        what = user.role or user.name
        got.append((what, user.hashed_password == ""))
    return [] if got == expected else [f"{path.name}: read {got}, the text sets {expected}"]


def test_every_committed_input_is_read_as_the_switch_keeps_it() -> None:
    wrong: list[str] = []
    asked = {"inputs": 0, "with accounts": 0, "bare": 0}
    for path in INPUTS:
        asked["inputs"] += 1
        expected = accounts_of(path.read_text(encoding="utf-8"))
        asked["with accounts"] += bool(expected)
        asked["bare"] += any(bare for _w, bare in expected)
        wrong += _held(path)
    assert wrong == [], "\n".join(wrong)
    # It read something: inputs with accounts, and bare markers among them.
    assert asked["with accounts"] >= 4 and asked["bare"] >= 2, asked


def test_the_input_check_fails_on_the_old_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    """The line the parser used to require: a bare marker is no account."""
    monkeypatch.setattr(
        aoss_parse, "_PASSWORD_LINE_RE",
        re.compile(r'^password\s+(manager|operator)\s+user-name\s+("[^"]+")\s+(\S+)\s+("[^"]+")\s*$', re.IGNORECASE),
    )
    failed = [path for path in INPUTS if _held(path)]
    assert len(failed) >= 2, failed


def test_the_reader_reads_each_form() -> None:
    assert accounts_of(
        'aaa authentication local-user "u" group "Level-15"\n'
        "password manager\n"
        'password operator user-name "o" sha1\n'
        '   "ab"\n'
        'aaa authentication local-user u2 group G password sha1 ab\n'
        'aaa authentication local-user "u" group "Level-1" password plaintext\n'
    ) == [("manager", True), ("operator", False), ("u2", False), ("u", False)]
