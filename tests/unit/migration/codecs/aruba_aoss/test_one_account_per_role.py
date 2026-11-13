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

A hashed account line (``sha1``, ``sha256``) needs ``include-credentials``
on the switch, and ``sha256`` needs ``password non-plaintext-sha256`` as
well, in which mode the switch does not take ``sha1``.  The output
writes neither setting; it has one ``review:`` line above the accounts
that names what the switch needs, and the job one warning
(:func:`wrong_setting`).

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


#: The forms a switch takes only with a setting the output leaves out.
_HASHED = {"sha1", "sha256"}

#: A setting the output must not write: it changes how the switch keeps
#: every credential, and is the operator's to decide.
_SETTING = re.compile(
    r"^[ \t]*(include-credentials|password[ \t]+non-plaintext-sha256)\b"
)


def _users_said(warnings: list[str]) -> list[str]:
    """The warnings for a user left out, one a user."""
    return [w for w in warnings if w.startswith("Local user ")]


def wrong_setting(text: str, warnings: list[str]) -> list[str]:
    """What is wrong with what an AOS-S output *text* and its job's
    *warnings* say of the settings a hashed account line needs."""
    lines = text.splitlines()
    live = [
        (index, hit) for index, line in enumerate(lines)
        if (hit := _LIVE.match(line)) is not None
    ]
    hashed = [(index, hit) for index, hit in live if hit.group(3) in _HASHED]
    forms = {hit.group(3) for _i, hit in hashed}
    reviews = [
        index for index, line in enumerate(lines)
        if line.startswith("; review:") and "include-credentials" in line
    ]
    said = [w for w in warnings if "include-credentials" in w]
    wrong = [
        f"a setting is written: {line.strip()}"
        for line in lines if _SETTING.match(line)
    ]
    if not hashed:
        if reviews:
            wrong.append("a review line for the settings and no hashed line")
        if said:
            wrong.append("a warning for the settings and no hashed line")
        return wrong
    if len(reviews) != 1:
        wrong.append(f"{len(reviews)} review lines for the settings")
    if len(said) != 1:
        wrong.append(f"{len(said)} warnings for the settings")
    if reviews and live and reviews[0] > live[0][0]:
        wrong.append("the review line is below an account line")
    for words in [lines[index] for index in reviews] + said:
        named = re.search(r"\(((?:sha1|sha256)(?:, (?:sha1|sha256))*)\)", words)
        if named is None or set(named.group(1).split(", ")) != forms:
            wrong.append(f"the forms named are not {sorted(forms)}")
        if "sha256" in forms and "password non-plaintext-sha256" not in words:
            wrong.append("sha256 and no password non-plaintext-sha256")
        if forms == _HASHED:
            sha1 = next(h.group(2) for _i, h in hashed if h.group(3) == "sha1")
            if "does not take sha1" not in words or f'"{sha1}"' not in words:
                wrong.append(f'sha1 and sha256, and "{sha1}" is not named')
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


_SHA1 = 'password manager user-name "a" sha1 "x"\n'
_SHA256 = 'password manager user-name "a" sha256 "x"\n'
_SAYS_SHA1 = "; review: a hashed password line (sha1) needs include-credentials\n"
_WARNS_SHA1 = ["... (sha1) ... include-credentials"]


class TestTheSettingCheckFails:
    @pytest.mark.parametrize(("text", "warnings", "said"), [
        (_SHA1, [], "0 review lines for the settings"),
        (_SAYS_SHA1 + _SHA1, [], "0 warnings for the settings"),
        (_SHA1 + _SAYS_SHA1, _WARNS_SHA1, "the review line is below"),
        (_SAYS_SHA1 + _SAYS_SHA1 + _SHA1, _WARNS_SHA1, "2 review lines"),
        (_SAYS_SHA1 + 'password manager user-name "a" plaintext "x"\n',
         [], "a review line for the settings and no hashed line"),
        (_SAYS_SHA1 + _SHA256, ["... (sha256) ... include-credentials"],
         "the forms named are not"),
        ("; review: a hashed password line (sha256) needs include-credentials\n"
         + _SHA256, ["... (sha256) ... include-credentials"],
         "sha256 and no password non-plaintext-sha256"),
        ("include-credentials\n" + _SAYS_SHA1 + _SHA1, _WARNS_SHA1,
         "a setting is written"),
        ("password non-plaintext-sha256\n", [], "a setting is written"),
        ("; review: a hashed password line (sha1, sha256) needs "
         "include-credentials, password non-plaintext-sha256\n"
         + _SHA256 + 'password operator user-name "b" sha1 "y"\n',
         ["(sha1, sha256) include-credentials password non-plaintext-sha256"],
         '"b" is not named'),
    ])
    def test_handed_the_defect(
        self, text: str, warnings: list[str], said: str,
    ) -> None:
        assert any(said in w for w in wrong_setting(text, warnings)), (
            wrong_setting(text, warnings)
        )


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
        said = _users_said(warnings)
        assert len(said) == 1
        assert '"bob"' in said[0] and '"admin"' in said[0]
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
        said = _users_said(warnings)
        assert len(said) == 1 and '"guest"' in said[0]


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
        # One a user: the manager for its secret, the operator for want
        # of the manager.
        assert len(warnings) == 2
        assert '"root"' in warnings[0] and "hash (9)" in warnings[0]
        assert '"viewer"' in warnings[1] and "manager access" in warnings[1]

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
        # And in the job, as on every other target: an account left out.
        assert len(warnings) == 1
        assert warnings[0].startswith('Local user "root" (manager) is not written for AOS-S: ')
        assert "hash (bcrypt)" in warnings[0] and "$2y$" not in warnings[0]

    @pytest.mark.parametrize(("name", "secret", "said"), [
        ('my "root"', "plaintext:rootpw", "white space or a quote"),
        ("root", 'plaintext:a "b"', "white space or a quote"),
        ("", "plaintext:rootpw", "A local user with no name (manager)"),
    ])
    def test_an_account_held_for_its_value_is_said(
        self, name: str, secret: str, said: str,
    ) -> None:
        out, warnings = _render(_user(name, 15, secret))
        assert live_accounts(out) == []
        assert len(warnings) == 1 and said in warnings[0]
        assert "rootpw" not in warnings[0] and '"b"' not in warnings[0]

    def test_beside_an_account_of_the_role_it_does_not(self) -> None:
        out, _warnings = _render(
            _user("admin", 15, "sha1:aa11"),
            _user("root", 15, "bcrypt:$2y$10$fakehash"),
        )
        line = next(x for x in out.splitlines() if 'user-name "root"' in x)
        assert '"admin" above' in line
        assert "asks for the password" not in line


class TestAHashedLineSaysWhatItNeeds:
    @pytest.mark.parametrize(("users", "forms"), [
        ((("admin", 15, "sha1:aa11"), ("viewer", 1, "sha1:bb22")), ["sha1"]),
        ((("admin", 15, "sha256:aa11"),), ["sha256"]),
        ((("admin", 15, "sha256:aa11"), ("viewer", 1, "sha1:bb22")),
         ["sha1", "sha256"]),
        ((("admin", 15, "plaintext:pw"), ("viewer", 1, "sha1:bb22")), ["sha1"]),
    ])
    def test_one_review_line_above_the_accounts(
        self, users: tuple[tuple[str, int, str], ...], forms: list[str],
    ) -> None:
        out, warnings = _render(*(_user(*u) for u in users))
        assert wrong_setting(out, warnings) == []
        review = next(x for x in out.splitlines() if "include-credentials" in x)
        assert f"({', '.join(forms)})" in review
        # Neither holds a secret.
        assert "aa11" not in review and "bb22" not in review
        assert not any("aa11" in w or "bb22" in w for w in warnings)

    @pytest.mark.parametrize("users", [
        (("admin", 15, "plaintext:pw"),),
        # A hashed account that is a comment needs no setting.
        (("viewer", 1, "sha1:bb22"),),
        (("root", 15, "9 $9$fake$hash"), ("viewer", 1, "sha1:bb22")),
        (),
    ])
    def test_none_without_a_live_hashed_line(
        self, users: tuple[tuple[str, int, str], ...],
    ) -> None:
        out, warnings = _render(*(_user(*u) for u in users))
        assert "include-credentials" not in out
        assert not any("include-credentials" in w for w in warnings)

    def test_the_parser_reads_the_accounts_back_past_it(self) -> None:
        out, _ = _render(
            _user("admin", 15, "sha256:aa11"),
            _user("viewer", 1, "sha1:bb22"),
        )
        users = ArubaAOSSCodec().parse(out).local_users
        assert [(u.name, u.role) for u in users] == [
            ("admin", "manager"), ("viewer", "operator"),
        ]


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
        # An account left out holds the job: the report cannot see it.
        assert job.status == MigrationJobStatus.partial
        assert job.error.startswith("The target left out ")
        assert live_accounts(job.rendered) == [
            ("manager", "admin2", "adminpw"), ("operator", "viewer", "viewerpw"),
        ]
        said = [w for w in job.warnings if w.startswith("Local user ")]
        # "root" for its secret, "bob" for the role "admin2" has.
        assert len(said) == 2
        assert '"root"' in said[0] and "hash (9)" in said[0]
        assert '"bob"' in said[1] and '"admin2"' in said[1]
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
        # Only "root", whose secret no map can make AOS-S take.
        said = [w for w in job.warnings if w.startswith("Local user ")]
        assert len(said) == 1 and '"root"' in said[0]

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
        """Of AOS-S's one account a role: EOS is told only of the
        secret it cannot take."""
        job = run_plan(get_codec("cisco_iosxe_cli"), get_codec("arista_eos"), _IOSXE)
        said = [w for w in job.warnings if w.startswith("Local user ")]
        assert len(said) == 1 and '"root"' in said[0] and "hash (9)" in said[0]

    def test_a_hashed_manager_from_a_switch(self) -> None:
        raw = (
            FIXTURES / "real" / "aruba_aoss" / "user_contrib_2930m_wc1611.cfg"
        ).read_text(encoding="utf-8")
        # The source sets include-credentials; the output names it in
        # a review line and does not set it.
        assert any(_SETTING.match(line) for line in raw.splitlines())
        job = run_plan(ArubaAOSSCodec(), ArubaAOSSCodec(), raw)
        assert [r for r, _n, _v in live_accounts(job.rendered)] == ["manager"]
        assert wrong_setting(job.rendered, list(job.warnings)) == []
        assert "include-credentials" in job.rendered
        onto_eos = run_plan(ArubaAOSSCodec(), get_codec("arista_eos"), raw)
        assert not any("include-credentials" in w for w in onto_eos.warnings)


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
    asked = {"jobs": 0, "with users": 0, "two of a role": 0, "hashed": 0}
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
        for said in wrong_setting(job.rendered, list(job.warnings)):
            wrong.append(f"{label}: {said}")
        if any((hit := _LIVE.match(line)) and hit.group(3) in _HASHED
               for line in job.rendered.splitlines()):
            asked["hashed"] += 1
    assert wrong == [], "\n".join(wrong[:20])
    # It read something: jobs with users, and with two of a role.
    assert asked["with users"] > 10, asked
    assert asked["two of a role"] > 3, asked
    assert asked["hashed"] > 0, asked
