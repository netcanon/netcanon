"""An AOS-S output gives one manager and one operator account, or fewer.

An ArubaOS-Switch holds ONE manager credential and ONE operator
credential; ``user-name`` names the slot, and a second ``password
manager user-name ...`` line re-points it (HPE Access Security Guide,
AOS-S 16.x: "only one set of operator/manager passwords").  An operator
password with no manager password gives manager access (the same
guide).  The renderer wrote a live line for every local user, so:

* of several accounts of one role, all but the last were lost, with
  nothing said;
* a config whose privilege-15 accounts all had secrets AOS-S cannot
  take came out with a live operator line and no manager line -- an
  operator password that is a manager password;
* an account with no password came out as ``plaintext ""``;
* the review comment for an account that could not be written said
  "reset this user password manually", which on a switch whose role
  was written replaces that account.

The output is read as TEXT here, by a reader this module owns
(:func:`live_accounts`), over hand-made trees, through the pipeline,
and over every committed capture; each check is handed the defect it is
for and has to fail.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalLocalUser,
)
from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import (
    run_plan,
    run_plan_with_checked_names,
    run_plan_with_overrides,
)

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
PUBLIC = list_public_codecs()

#: A live account line, as AOS-S prints one: the name and the value
#: between quotes.
_LIVE = re.compile(
    r'^password (manager|operator) user-name "([^"]*)" '
    r'(plaintext|sha1|sha256) "([^"]*)"[ \t]*$'
)


def live_accounts(text: str) -> list[tuple[str, str, str]]:
    """(role, name, value) of every live account line of *text*.  A
    line that sets a role in any other shape is returned with the name
    ``?`` -- it is live all the same."""
    found: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        if not re.match(r"^password[ \t]+(manager|operator)\b", line):
            continue
        hit = _LIVE.match(line)
        if hit is None:
            role = line.split()[1]
            found.append((role, "?", "?"))
        else:
            found.append((hit.group(1), hit.group(2), hit.group(4)))
    return found


def _commented(text: str, name: str) -> bool:
    return any(
        line.startswith("; password ")
        and (f'user-name "{name}"' in line or f"user-name {name} " in line)
        and "-- review:" in line
        for line in text.splitlines()
    )


def wrong_accounts(
    text: str, names: list[str], warnings: list[str],
) -> list[str]:
    """What is wrong with the accounts of an AOS-S output *text* made
    from a config whose users are *names*."""
    wrong: list[str] = []
    live = live_accounts(text)
    roles = [role for role, _n, _v in live]
    for role in ("manager", "operator"):
        if roles.count(role) > 1:
            wrong.append(f"{roles.count(role)} live {role} lines")
    if "operator" in roles and "manager" not in roles:
        wrong.append("a live operator line and no manager line")
    wrong += [
        f'an empty value for "{name}"'
        for _role, name, value in live if value == ""
    ]
    wrong += [f"a {role} line in another shape" for role, name, _v in live if name == "?"]
    given = {name for _role, name, _v in live}
    for name in names:
        if name in given or _commented(text, name):
            continue
        if any(f'"{name}"' in warning for warning in warnings):
            continue
        wrong.append(f'"{name}" is in no line of the output')
    return wrong


def _user(name: str, level: int, secret: str) -> CanonicalLocalUser:
    return CanonicalLocalUser(
        name=name, privilege_level=level, hashed_password=secret,
    )


def _render(*users: CanonicalLocalUser) -> tuple[str, list[str]]:
    tree = CanonicalIntent(local_users=list(users))
    codec = ArubaAOSSCodec()
    return codec.render(tree), codec.render_warnings(tree)


# ---------------------------------------------------------------------------
# The reader and the check, handed each defect
# ---------------------------------------------------------------------------


class TestTheCheckFails:
    @pytest.mark.parametrize(("text", "said"), [
        ('password manager user-name "a" sha1 "x"\n'
         'password manager user-name "b" sha1 "y"\n', "2 live manager lines"),
        ('password operator user-name "a" plaintext "x"\n',
         "a live operator line and no manager line"),
        ('password manager user-name "a" plaintext ""\n', 'an empty value for "a"'),
        ('password manager user-name a sha1 x\n', "a manager line in another shape"),
        ('password manager user-name "a" sha1 "x"\n', '"b" is in no line of the output'),
    ])
    def test_handed_the_defect(self, text: str, said: str) -> None:
        assert said in wrong_accounts(text, ["a", "b"] if "b" in said else ["a"], [])

    def test_a_comment_is_not_live(self) -> None:
        text = '; password manager user-name "a" -- review: x\n'
        assert live_accounts(text) == []
        assert wrong_accounts(text, ["a"], []) == []


# ---------------------------------------------------------------------------
# Hand-made trees
# ---------------------------------------------------------------------------


class TestOneAccountPerRole:
    def test_the_first_manager_has_the_account(self) -> None:
        out, warnings = _render(
            _user("admin", 15, "sha1:aa11"),
            _user("bob", 15, "plaintext:bobpw"),
        )
        assert live_accounts(out) == [("manager", "admin", "aa11")]
        assert wrong_accounts(out, ["admin", "bob"], warnings) == []
        line = next(x for x in out.splitlines() if 'user-name "bob"' in x)
        assert line.startswith("; ")
        assert '"admin" above' in line
        # No advice that, followed, replaces the account written above.
        assert "asks for the password" not in line
        assert "reset" not in line
        assert len(warnings) == 1
        assert '"bob"' in warnings[0] and '"admin"' in warnings[0]
        # The secret of the account not written is in no line.
        assert "bobpw" not in out

    def test_the_operator_too(self) -> None:
        out, warnings = _render(
            _user("viewer", 1, "sha1:bb22"),
            _user("admin", 15, "sha1:aa11"),
            _user("guest", 5, "sha1:cc33"),
        )
        # The manager first, as the switch prints them.
        assert live_accounts(out) == [
            ("manager", "admin", "aa11"), ("operator", "viewer", "bb22"),
        ]
        assert wrong_accounts(out, ["viewer", "admin", "guest"], warnings) == []
        assert len(warnings) == 1 and '"guest"' in warnings[0]


class TestNoOperatorWithoutAManager:
    def test_a_manager_secret_aos_s_cannot_take(self) -> None:
        out, warnings = _render(
            _user("root", 15, "9 $9$fake$hash"),
            _user("viewer", 1, "plaintext:viewerpw"),
        )
        assert live_accounts(out) == []
        assert wrong_accounts(out, ["root", "viewer"], warnings) == []
        assert "viewerpw" not in out
        assert "$9$" not in out
        line = next(x for x in out.splitlines() if 'user-name "viewer"' in x)
        assert "manager access" in line
        assert len(warnings) == 1 and '"viewer"' in warnings[0]

    def test_no_manager_at_all(self) -> None:
        out, warnings = _render(_user("viewer", 1, "sha1:bb22"))
        assert live_accounts(out) == []
        assert len(warnings) == 1

    def test_a_manager_with_no_password(self) -> None:
        out, warnings = _render(
            _user("frank", 15, ""),
            _user("viewer", 1, "sha1:bb22"),
        )
        assert live_accounts(out) == []
        assert wrong_accounts(out, ["frank", "viewer"], warnings) == []
        assert len(warnings) == 2


class TestNoEmptyValue:
    @pytest.mark.parametrize("secret", ["", "sha1:", "plaintext:"])
    def test_no_password(self, secret: str) -> None:
        out, warnings = _render(_user("frank", 15, secret))
        assert live_accounts(out) == []
        assert 'plaintext ""' not in out and 'sha1 ""' not in out
        assert _commented(out, "frank")
        assert len(warnings) == 1 and '"frank"' in warnings[0]

    def test_the_next_manager_has_the_account(self) -> None:
        out, warnings = _render(
            _user("frank", 15, ""),
            _user("admin", 15, "sha1:aa11"),
        )
        assert live_accounts(out) == [("manager", "admin", "aa11")]
        line = next(x for x in out.splitlines() if 'user-name "frank"' in x)
        assert '"admin" above' in line


class TestASecretAosSCannotTake:
    def test_with_no_account_of_the_role_it_says_how_to_set_one(self) -> None:
        out, warnings = _render(_user("root", 15, "bcrypt:$2y$10$fakehash"))
        line = next(x for x in out.splitlines() if 'user-name "root"' in x)
        assert line.startswith("; ")
        assert "bcrypt" in line
        assert 'password manager user-name "root", which asks for the password' in line
        # Said in the output, as on every other target.
        assert warnings == []

    def test_beside_an_account_of_the_role_it_does_not(self) -> None:
        out, _warnings = _render(
            _user("admin", 15, "sha1:aa11"),
            _user("root", 15, "bcrypt:$2y$10$fakehash"),
        )
        line = next(x for x in out.splitlines() if 'user-name "root"' in x)
        assert '"admin" above' in line
        assert "asks for the password" not in line


class TestTheParserReadsItBack:
    def test_one_of_each(self) -> None:
        out, _ = _render(
            _user("admin", 15, "sha1:aa11"),
            _user("bob", 15, "sha1:dd44"),
            _user("viewer", 1, "sha1:bb22"),
            _user("guest", 1, "sha1:cc33"),
        )
        users = ArubaAOSSCodec().parse(out).local_users
        assert [(u.name, u.role) for u in users] == [
            ("admin", "manager"), ("viewer", "operator"),
        ]


# ---------------------------------------------------------------------------
# Through the pipeline
# ---------------------------------------------------------------------------

_IOSXE = (
    "hostname sw1\n"
    "username root privilege 15 secret 9 $9$fake$hash\n"
    "username viewer privilege 1 password 0 viewerpw\n"
    "username admin2 privilege 15 password 0 adminpw\n"
    "username bob privilege 15 password 0 bobpw\n"
)


class TestThroughThePipeline:
    def test_the_job_says_which_account_has_the_role(self) -> None:
        job = run_plan(get_codec("cisco_iosxe_cli"), ArubaAOSSCodec(), _IOSXE)
        assert job.status == MigrationJobStatus.completed
        assert live_accounts(job.rendered) == [
            ("manager", "admin2", "adminpw"), ("operator", "viewer", "viewerpw"),
        ]
        said = [w for w in job.warnings if w.startswith("Local user ")]
        assert len(said) == 1 and '"bob"' in said[0] and '"admin2"' in said[0]
        assert job.validation.severity == "warn"
        assert any(
            lp.path == "/local-users/user/privilege-level"
            for lp in job.validation.lossy_paths
        )

    def test_the_rename_map_chooses_another(self) -> None:
        job = run_plan_with_overrides(
            get_codec("cisco_iosxe_cli"), ArubaAOSSCodec(), _IOSXE,
            local_user_rename_map={"admin2": None},
        )
        assert live_accounts(job.rendered) == [
            ("manager", "bob", "bobpw"), ("operator", "viewer", "viewerpw"),
        ]
        assert not [w for w in job.warnings if w.startswith("Local user ")]

    def test_no_manager_no_operator(self) -> None:
        raw = (
            "hostname sw1\n"
            "username root privilege 15 secret 9 $9$fake$hash\n"
            "username viewer privilege 1 password 0 viewerpw\n"
        )
        job = run_plan(get_codec("cisco_iosxe_cli"), ArubaAOSSCodec(), raw)
        assert live_accounts(job.rendered) == []
        assert "viewerpw" not in job.rendered
        assert any(
            '"viewer"' in w and "manager access" in w for w in job.warnings
        )

    def test_another_target_is_not_told(self) -> None:
        job = run_plan(get_codec("cisco_iosxe_cli"), get_codec("arista_eos"), _IOSXE)
        assert not [w for w in job.warnings if w.startswith("Local user ")]


# ---------------------------------------------------------------------------
# Every committed capture
# ---------------------------------------------------------------------------

_NOT_A_CAPTURE = {".md", ".json", ".yaml", ".yml", ".py"}


def _captures() -> list[tuple[str, str, Path]]:
    found: list[tuple[str, str, Path]] = []
    for root in ("real", "synthetic", "iosxe", "opnsense"):
        for path in sorted(p for p in (FIXTURES / root).rglob("*") if p.is_file()):
            if path.suffix.lower() in _NOT_A_CAPTURE:
                continue
            parts = path.relative_to(FIXTURES).parts
            label = parts[1] if root in ("real", "synthetic") else {"iosxe": "cisco_iosxe"}.get(root, root)
            codec = DIR_TO_CODEC_NAME.get(label, label)
            if label == "cisco_iosxe" and path.suffix.lower() == ".xml":
                codec = "cisco_iosxe"
            if codec in PUBLIC:
                found.append((codec, "/".join(parts), path))
    return found


def test_every_capture_onto_aos_s() -> None:
    wrong: list[str] = []
    asked = {"jobs": 0, "with users": 0, "two of a role": 0}
    for codec, label, path in _captures():
        raw = path.read_text(encoding="utf-8")
        try:
            users = get_codec(codec).parse(raw).local_users
        except Exception:  # a capture the parser refuses
            continue
        job = run_plan_with_checked_names(
            get_codec(codec), ArubaAOSSCodec(), raw, devices_known=False,
        )
        if job.rendered is None:
            continue
        asked["jobs"] += 1
        if users:
            asked["with users"] += 1
        levels = [15 if u.privilege_level == 15 else 1 for u in users]
        if levels.count(15) > 1 or levels.count(1) > 1:
            asked["two of a role"] += 1
        for said in wrong_accounts(
            job.rendered, [u.name for u in users], list(job.warnings),
        ):
            wrong.append(f"{label}: {said}")
    assert wrong == [], "\n".join(wrong[:20])
    # It read something: jobs with users, and with two of a role.
    assert asked["with users"] > 10, asked
    assert asked["two of a role"] > 3, asked
