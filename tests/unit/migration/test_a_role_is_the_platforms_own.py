"""A local user's role crosses only between two configs of one platform.

A role is a name the device looks up among the roles it has (EOS, NX-OS
and OS10 ``role``, AOS-CX and IOS XR ``group``, Junos ``class``, FortiOS
``accprofile``).  Seven renderers wrote the source's role as it stood,
whatever platform it came from: a Junos ``super-user`` became an NX-OS
role NX-OS does not have, an NX-OS ``network-admin`` a Junos class Junos
does not have, an IOS-XE account at privilege 1 a Junos ``operator`` that
may clear, reset and trace.  And VyOS, whose every login user has full
access, wrote every account as one: an account the source kept at
privilege 1 became an administrator.

The rule (:mod:`netcanon.migration._roles`): the role is written as it
stands only where the tree was read by a codec of the target's platform
(``source_vendor`` is the target's ``vendor_id``); everywhere else the
target chooses one of its own built-in roles from the privilege level,
and a target that has none below an administrator (VyOS, FortiOS) writes
a review line and a job warning in place of an account below one.

The output is read as TEXT, by a reader typed here for each target's
grammar (:func:`roles_written`), never by the target's parser, and what
each target writes is typed here too (:data:`BUILT_IN`), not asked of
the codec.  Sources: a tree of each platform and of none, and every
committed input onto every public target.  The check is handed each
defect it is for (:class:`TestTheCheckFails`), and with the gate taken
out the foreign role comes back on the targets pinned there.

See also ``test_an_account_with_no_password.py`` (whose account readers
this module uses) and ``test_secret_fail_open.py``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter

import pytest

import netcanon.migration._roles as roles
import netcanon.migration.codecs  # noqa: F401  (registers the codecs)
from netcanon.migration._user_secrets import holds_no_secret, is_migratable
from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalLocalUser
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan
from tests.unit.migration.codecs.aruba_aoss.test_one_account_per_role import _captures
from tests.unit.migration.test_an_account_with_no_password import (
    _TAKEN,
    _accounts,
    _comments,
    _in_scope,
)
from tests.unit.migration.test_secret_fail_open import (
    _USER_RENDERING_TARGETS,
    _outside_comments,
)

#: In place of an account: a review line and a warning.
LEFT_OUT = object()


def _by_level(admin: str, below) -> object:
    return lambda level: admin if level >= 15 else below


#: What each target writes for an account from another platform, by its
#: privilege level, typed from the target's grammar: ``""`` is no role
#: at all, :data:`LEFT_OUT` a review line in place of the account.
BUILT_IN = {
    "arista_eos": _by_level("network-admin", "network-operator"),
    "aruba_aoscx": _by_level("administrators", "operators"),
    "aruba_aoss": _by_level("manager", "operator"),
    "cisco_iosxe_cli": _by_level("", ""),
    "cisco_iosxr": _by_level("root-lr", "operator"),
    "cisco_nxos": _by_level("network-admin", "network-operator"),
    "dell_os10": _by_level("sysadmin", "netoperator"),
    "fortigate_cli": _by_level("super_admin", LEFT_OUT),
    "juniper_junos": lambda level: (
        "super-user" if level >= 15 else "operator" if level >= 5 else "read-only"
    ),
    "mikrotik_routeros": lambda level: (
        "full" if level >= 15 else "write" if level >= 10 else "read"
    ),
    "opnsense": _by_level("admins", "users"),
    "vyos": _by_level("", LEFT_OUT),
}

#: The targets that write a role of their own platform's config as it
#: stands.  The others choose from the privilege level whatever the
#: source (IOS-XE, VyOS and AOS-S have no named role to keep; RouterOS
#: and OPNsense write their built-in groups only).
KEEPS_ITS_OWN = frozenset({
    "arista_eos", "aruba_aoscx", "cisco_iosxr", "cisco_nxos", "dell_os10",
    "fortigate_cli", "juniper_junos",
})

#: What the review line and the warning say of an account left out.
BELOW = "below an administrator"


def expected(target: str, same: bool, user: CanonicalLocalUser) -> object:
    """The role *target* writes for *user*, from a config of its own
    platform (*same*) or not."""
    if same and target in KEEPS_ITS_OWN:
        if target == "fortigate_cli" and user.privilege_level >= 15:
            return "super_admin"
        if user.role:
            return user.role
        if target == "arista_eos":
            return ""  # EOS prints an account with no role as it is
    return BUILT_IN[target](user.privilege_level)


def _word(pattern: str, line: str) -> str:
    found = re.search(pattern, line)
    return found.group(1) if found else ""


def _block(text: str, header: re.Pattern) -> list[list[str]]:
    """Each block of *text* (outside comments) whose first line matches
    *header*: the line and the indented lines after it."""
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in _outside_comments(text):
        if current is not None and line[:1] in (" ", "\t"):
            current.append(line)
            continue
        current = None
        if header.search(line):
            current = [line]
            blocks.append(current)
    return blocks


def roles_written(target: str, text: str, name: str) -> list[str]:
    """The role of each account *name* that *text*, written for
    *target*, holds; ``""`` for an account written with none.  One entry
    an account; none where no account of the name is written."""
    if target == "opnsense":
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []
        return [
            (user.findtext("groupname") or "").strip()
            for system in root.iter("system")
            for user in system.findall("user")
            if (user.findtext("name") or "").strip() == name
        ]
    if target == "cisco_iosxr":
        header = re.compile(rf"^username[ \t]+{re.escape(name)}(?![\w-])")
        return [
            ",".join(
                _word(r"^[ \t]+group[ \t]+(\S+)", line)
                for line in block[1:]
                if re.match(r"^[ \t]+group[ \t]", line)
            )
            for block in _block(text, header)
        ]
    if target == "fortigate_cli":
        written: list[str] = []
        inside: str | None = None
        for line in _in_scope(target, text):
            stripped = line.strip()
            if inside is None:
                if re.fullmatch(rf'edit[ \t]+"?{re.escape(name)}"?', stripped):
                    inside = ""
                    written.append("")
            elif stripped == "next":
                inside = None
            elif stripped.startswith("set accprofile "):
                written[-1] = stripped[len("set accprofile "):].strip('"')
        return written
    lines = _accounts(target, text, name)
    if target == "juniper_junos":
        if not lines:
            return []
        return [",".join(
            _word(r"[ \t]class[ \t]+\"?([^\"\s]+)", line)
            for line in lines if re.search(r"[ \t]class[ \t]", line)
        )]
    if target == "aruba_aoss":
        return [_word(r"^password[ \t]+(manager|operator)[ \t]", line) for line in lines]
    if target == "aruba_aoscx":
        return [_word(r"[ \t]group[ \t]+(\S+)", line) for line in lines]
    if target == "mikrotik_routeros":
        return [_word(r'(?:^|[ \t])group="?([^"\s]+)"?', line) for line in lines]
    if target == "vyos":
        return ["" for _line in lines]
    # EOS, IOS-XE, NX-OS, OS10: ``username <name> ... role <role> ...``.
    return [_word(r"[ \t]role[ \t]+(\S+)", line) for line in lines]


def wrong(
    target: str, text: str, warnings: list[str], users, source_vendor: str,
    *, all_written: bool,
) -> list[str]:
    """What is wrong with *text* and *warnings*, written for *target*
    from *users* of a tree stamped *source_vendor*.

    Each user holds a secret the target takes, and its name is the
    name of no other account of the source.  With *all_written* every
    account the target has a role for must be written; otherwise one
    that is not (left out for another reason: a name the line cannot
    hold, a second AOS-S account of a role) is not read for.
    """
    same = roles.same_platform(source_vendor, target)
    said: list[str] = []
    for user in users:
        want = expected(target, same, user)
        got = roles_written(target, text, user.name)
        reviews = [
            line for line in _comments(text)
            if f'"{user.name}"' in line and BELOW in line
        ]
        told = [w for w in warnings if f'"{user.name}"' in w and BELOW in w]
        if want is LEFT_OUT:
            if got:
                said.append(f"{user.name}: written as {got}, not left out")
            if len(reviews) != 1:
                said.append(f"{user.name}: {len(reviews)} review lines, not 1")
            if len(told) != 1:
                said.append(f"{user.name}: {len(told)} warnings, not 1")
            continue
        if reviews or told:
            said.append(f"{user.name}: said to be left out, and is not")
        if not got and not all_written:
            continue
        if got != [want]:
            said.append(f"{user.name}: role {got}, not [{want!r}]")
    return said


def _a_hash_it_takes(target: str) -> str:
    return next(s for s in _TAKEN if is_migratable(s, target))


def _tree(target: str, source_vendor: str) -> CanonicalIntent:
    """Three accounts that each name a role (two for AOS-S, which
    writes one account of each of its two roles)."""
    taken_hash = _a_hash_it_takes(target)
    users = [
        CanonicalLocalUser(name="zqadm", privilege_level=15, role="zqrole-a", hashed_password=taken_hash),
        CanonicalLocalUser(name="zqop", privilege_level=1, role="zqrole-b", hashed_password=taken_hash),
        CanonicalLocalUser(name="zqmid", privilege_level=10, role="zqrole-c", hashed_password=taken_hash),
    ]
    if target == "aruba_aoss":
        users = users[:2]
    return CanonicalIntent(hostname="sw1", source_vendor=source_vendor, local_users=users)


#: Every platform a public codec reads, and none.
PLATFORMS = sorted(
    {get_codec(name).capabilities.vendor_id for name in list_public_codecs()} | {""}
)


def test_the_tables_cover_every_target_that_writes_accounts() -> None:
    assert set(BUILT_IN) == set(_USER_RENDERING_TARGETS)
    assert set(BUILT_IN) >= KEEPS_ITS_OWN
    assert set(roles.BELOW_ADMIN_WHY) == {
        target for target, pick in BUILT_IN.items() if pick(1) is LEFT_OUT
    }


@pytest.mark.parametrize("target", _USER_RENDERING_TARGETS)
def test_the_reader_reads_the_role_each_target_writes(target) -> None:
    """The reader is typed by hand: for a tree of the target's own
    platform it finds each account, with a role where the target writes
    one, or the check reads nothing."""
    vendor = get_codec(target).capabilities.vendor_id
    tree = _tree(target, vendor)
    out = get_codec(target).render(tree)
    for user in tree.local_users:
        want = expected(target, True, user)
        if want is LEFT_OUT:
            continue
        assert roles_written(target, out, user.name) == [want], (target, user.name)


@pytest.mark.parametrize("source_vendor", PLATFORMS)
@pytest.mark.parametrize("target", _USER_RENDERING_TARGETS)
def test_a_role_crosses_only_within_a_platform(target, source_vendor) -> None:
    codec = get_codec(target)
    tree = _tree(target, source_vendor)
    said = wrong(
        target, codec.render(tree), codec.render_warnings(tree),
        tree.local_users, source_vendor, all_written=True,
    )
    assert said == []


@pytest.mark.parametrize("target", _USER_RENDERING_TARGETS)
def test_no_account_below_an_administrator_is_written_as_one(target) -> None:
    """From any platform but the target's own, an account below
    privilege 15 is never given the role the target gives at 15."""
    admin = BUILT_IN[target](15)
    for source_vendor in PLATFORMS:
        if roles.same_platform(source_vendor, target):
            continue
        tree = _tree(target, source_vendor)
        out = get_codec(target).render(tree)
        for user in tree.local_users:
            if user.privilege_level < 15 and admin:
                assert admin not in roles_written(target, out, user.name), (
                    target, source_vendor, user.name,
                )


def test_vyos_writes_no_account_below_an_administrator_from_its_own_platform() -> None:
    """VyOS has no role at all, so no tree, its own included, makes an
    account below privilege 15 an administrator there."""
    tree = _tree("vyos", "vyos")
    out = get_codec("vyos").render(tree)
    assert roles_written("vyos", out, "zqop") == []
    assert roles_written("vyos", out, "zqadm") == [""]


@pytest.mark.parametrize("name", sorted(list_public_codecs()))
def test_each_parser_stamps_its_codecs_platform(name) -> None:
    """``source_vendor`` is what the rule reads; a parser that stamped
    another word would lose its own roles on its own platform."""
    codec = get_codec(name)
    for source, _label, path in _captures():
        if source != name:
            continue
        try:
            tree = codec.parse(path.read_text(encoding="utf-8"))
        except Exception:  # a capture the parser refuses
            continue
        assert tree.source_vendor == codec.capabilities.vendor_id, path
        return
    pytest.fail(f"no capture of {name}")


#: The parsers that record no role: IOS-XE and VyOS state none for a
#: local account, and OPNsense states a user's groups by the ``<group>``
#: elements that list it, which its parser does not read.
STATES_NO_ROLE = frozenset({"cisco_iosxe_cli", "opnsense", "vyos"})


def test_a_parser_records_the_role_its_config_names() -> None:
    """A role in the tree is a word of the config, and the parsers whose
    grammar has none record none.  IOS-XE, RouterOS, OPNsense and VyOS
    made one up from the privilege level, which the targets then wrote
    as a name of theirs."""
    asked: Counter[str] = Counter()
    found: list[str] = []
    for source, label, path in _captures():
        raw = path.read_text(encoding="utf-8")
        try:
            users = get_codec(source).parse(raw).local_users
        except Exception:  # a capture the parser refuses
            continue
        for user in users:
            asked[source] += 1
            if source in STATES_NO_ROLE and user.role:
                found.append(f"{label}: a role where the config states none")
            elif user.role and not re.search(
                rf"(?<![\w-]){re.escape(user.role)}(?![\w-])", raw
            ):
                found.append(f"{label}: a role that is no word of the config")
    assert found == []
    assert set(asked) >= STATES_NO_ROLE | {"mikrotik_routeros", "fortigate_cli"}, asked


def test_fortios_keeps_a_profiles_case() -> None:
    text = (
        "config system admin\n"
        '    edit "zqprof"\n'
        '        set accprofile "Zq_Profile"\n'
        "        set password ENC fakeEncodedHash==\n"
        "    next\n"
        "end\n"
    )
    user = get_codec("fortigate_cli").parse(text).local_users[0]
    assert (user.role, user.privilege_level) == ("Zq_Profile", 1)
    out = get_codec("fortigate_cli").render(get_codec("fortigate_cli").parse(text))
    assert roles_written("fortigate_cli", out, "zqprof") == ["Zq_Profile"]


class TestTheCheckFails:
    """The check above is handed each defect it is for, and fails."""

    def _out(self, target: str, source_vendor: str = "juniper_junos"):
        codec = get_codec(target)
        tree = _tree(target, source_vendor)
        return codec.render(tree), codec.render_warnings(tree), tree

    def test_it_passes_the_good_output(self) -> None:
        text, warnings, tree = self._out("cisco_nxos")
        assert wrong(
            "cisco_nxos", text, warnings, tree.local_users, "juniper_junos",
            all_written=True,
        ) == []

    def test_a_foreign_role(self) -> None:
        text, warnings, tree = self._out("cisco_nxos")
        text = text.replace("role network-operator", "role zqrole-b", 1)
        said = wrong("cisco_nxos", text, warnings, tree.local_users, "juniper_junos", all_written=True)
        assert any("zqop: role" in s for s in said), said

    def test_an_account_below_an_administrator_written_as_one(self) -> None:
        text, warnings, tree = self._out("arista_eos")
        text = text.replace(
            "username zqop privilege 1 role network-operator",
            "username zqop privilege 1 role network-admin",
        ).replace(
            "username zqop role network-operator", "username zqop role network-admin",
        )
        said = wrong("arista_eos", text, warnings, tree.local_users, "juniper_junos", all_written=True)
        assert any("zqop: role ['network-admin']" in s for s in said), (said, text)

    def test_an_account_not_written(self) -> None:
        text, warnings, tree = self._out("dell_os10")
        text = "\n".join(line for line in text.splitlines() if "zqmid" not in line)
        said = wrong("dell_os10", text, warnings, tree.local_users, "juniper_junos", all_written=True)
        assert any("zqmid: role []" in s for s in said), said

    def test_an_account_left_out_and_written(self) -> None:
        text, warnings, tree = self._out("vyos")
        text += "system {\n    login {\n        user zqop {\n        }\n    }\n}\n"
        said = wrong("vyos", text, warnings, tree.local_users, "juniper_junos", all_written=True)
        assert any("zqop: written as" in s for s in said), said

    def test_no_review_line(self) -> None:
        text, warnings, tree = self._out("fortigate_cli")
        text = "\n".join(line for line in text.splitlines() if BELOW not in line)
        said = wrong("fortigate_cli", text, warnings, tree.local_users, "juniper_junos", all_written=True)
        assert any("0 review lines" in s for s in said), said

    def test_no_warning_and_two(self) -> None:
        text, warnings, tree = self._out("vyos")
        for given, count in (([], "0 warnings"), (warnings + warnings, "2 warnings")):
            said = wrong("vyos", text, given, tree.local_users, "juniper_junos", all_written=True)
            assert any(count in s for s in said), (count, said)

    def test_the_gate_taken_out(self, monkeypatch) -> None:
        """With every source taken for the target's own platform, the
        source's role is written as it stands: a foreign role on each
        target that writes one (and on FortiOS a foreign profile in
        place of a review line).  VyOS asks no platform: it has no
        role to keep."""
        failed = set()
        for target in _USER_RENDERING_TARGETS:
            codec = get_codec(target)
            tree = _tree(target, "juniper_junos" if target != "juniper_junos" else "cisco_nxos")
            with monkeypatch.context() as patched:
                patched.setattr(roles, "_vendor_id", lambda _t, v=tree.source_vendor: v)
                text, warnings = codec.render(tree), codec.render_warnings(tree)
            if wrong(target, text, warnings, tree.local_users, tree.source_vendor, all_written=True):
                failed.add(target)
        assert failed == KEEPS_ITS_OWN

    def test_no_target_left_out(self, monkeypatch) -> None:
        """With no target in the table, VyOS and FortiOS write an account
        below an administrator, and the check says so."""
        monkeypatch.setattr(roles, "BELOW_ADMIN_WHY", {})
        failed = set()
        for target in _USER_RENDERING_TARGETS:
            text, warnings, tree = self._out(target)
            if wrong(target, text, warnings, tree.local_users, "juniper_junos", all_written=True):
                failed.add(target)
        assert failed == {"vyos", "fortigate_cli"}


def test_every_committed_input_onto_every_target() -> None:
    """Every committed input that holds an account, onto every public
    codec, through the pipeline: the role each target writes is read as
    above."""
    found: list[str] = []
    asked: Counter[str] = Counter()
    for source, label, path in _captures():
        raw = path.read_text(encoding="utf-8")
        try:
            tree = get_codec(source).parse(raw)
        except Exception:  # a capture the parser refuses
            continue
        names = Counter(u.name for u in tree.local_users)
        for target in _USER_RENDERING_TARGETS:
            users = [
                u for u in tree.local_users
                if names[u.name] == 1
                and not holds_no_secret(u.hashed_password)
                and is_migratable(u.hashed_password, target)
            ]
            if not users:
                continue
            job = run_plan(get_codec(source), get_codec(target), raw)
            if job.rendered is None:
                asked["not rendered"] += 1
                continue
            asked["jobs"] += 1
            asked["same" if roles.same_platform(tree.source_vendor, target) else "cross"] += 1
            for user in users:
                if roles_written(target, job.rendered, user.name):
                    asked["accounts read"] += 1
            for said in wrong(
                target, job.rendered, job.warnings, users, tree.source_vendor,
                all_written=False,
            ):
                found.append(f"{label} -> {target}: {said}")
    assert found == []
    assert asked["not rendered"] == 0, asked
    assert asked["same"] > 0 and asked["cross"] > 0 and asked["accounts read"] > 0, asked
