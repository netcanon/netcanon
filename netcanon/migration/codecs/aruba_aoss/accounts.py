"""The two accounts of an AOS-S switch, and which local users get them.

An ArubaOS-Switch holds ONE manager credential and ONE operator
credential.  ``password manager user-name "<name>" <alg> "<value>"``
sets the manager slot and names it; a second such line is taken
without complaint and re-points the same slot, so of several lines of
one role only the last is the switch's (HPE Access Security Guide,
16.x: "only one set of operator/manager passwords").  And an operator
password with no manager password gives manager access: "if you
configure only an operator password, entering the operator password
enables full manager privileges" (the same guide).

So of a config's local users, AOS-S can be given at most two, and the
renderer writes:

* the manager account: the first user of privilege 15, in the order
  of the source, whose secret AOS-S can take (:func:`_split_aos_hash`)
  and which is not empty;
* the operator account: the first such user of any other privilege --
  and only beside a manager account, since alone it is a manager
  account under another name;
* every other user as a ``review:`` comment that says why, and what to
  do on the switch.  The advice never says "set its password" where
  that would replace the account written above it.

Which user gets a role is the order of the source; an operator who
wants another drops the first in the local-user rename map.  The
renderer writes the lines (:func:`account_lines`) and the job carries a
warning for each user who is not given an account for a reason of
AOS-S's own -- a second account of a role, an operator held back for
want of a manager, an account with no password (:func:`account_warnings`).
A secret AOS-S cannot take is a comment on every target, and is said
in the output only, as on the others.

A live line in a hashed form (``sha1``, ``sha256``) needs settings this
output does not write.  A 5412R refused ``password manager user-name
... sha256 ...`` with "Invalid input: sha256" until
``include-credentials`` had been run, and Aruba Central's template help
says a template that sets a password must carry ``include-credentials``;
for ``sha1`` the need is inferred.  ``sha256`` needs ``password
non-plaintext-sha256`` as well, which the 16.11 guides document and a
2530 on 16.10 refuses, and in that mode the switch does not take a
password in SHA-1 form (HPE Access Security Guide, AOS-S 16.11).
``include-credentials`` keeps the switch's credentials in its config
file, and a startup config that holds it replaces the credentials the
switch kept apart, so neither setting is written: one ``review:`` line
above the accounts names what the switch needs
(:func:`setting_review`), and the job says it once
(:func:`setting_warning`).

No line here holds a secret outside a live ``password`` line: a comment
names the account and never its value.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..._one_value import breaks_its_quotes
from ..._user_secrets import classify_hash, is_migratable
from ...canonical.intent import CanonicalLocalUser

#: Hash algorithms AOS-S accepts in the ``password manager user-name
#: <name> <alg> <hash>`` form.  Verified against Aruba's published
#: docs (Aruba 3810M/5400R Access Security Guide for AOS-S 16.11,
#: "Setting passwords and usernames" + the password command-options
#: reference).  AOS-S accepts ``plaintext``, ``sha1`` (40-char hex),
#: ``sha256`` (64-char hex).  ``sha512`` is NOT accepted (this is
#: the cross-vendor migration hazard from Cisco / Arista — operator
#: must reset the password rather than re-use the hash).  Cisco
#: type-5 (md5crypt) and type-9 (scrypt) are also unmigratable.
#:
#: This set expresses Aruba-NATIVE emit forms.  The cross-vendor
#: migratability gate (which algorithms AOS-S literally cannot
#: consume) lives in :mod:`netcanon.migration._user_secrets` and
#: is shared with fortigate_cli, juniper_junos, and opnsense codecs.
_AOS_KNOWN_ALGORITHMS = {"sha1", "sha256", "plaintext"}

#: The two roles, in the order the switch prints them.
ROLES = ("manager", "operator")

#: The hashed forms AOS-S takes, in the order a review line names them.
HASHED_FORMS = ("sha1", "sha256")


def _split_aos_hash(hashed: str) -> tuple[str, str]:
    """Split a canonical ``hashed_password`` into (aos-algorithm, hash).

    Thin wrapper over the shared :func:`classify_hash` /
    :func:`is_migratable` policy in
    :mod:`netcanon.migration._user_secrets`.  Maps the shared
    helper's output to the historical Aruba return shape:

        ``sha1:<hex>``        -> ("sha1", "<hex>")        [native]
        ``sha256:<hex>``      -> ("sha256", "<hex>")      [native]
        ``arista:sha512:...`` -> ("__unmigratable__", "sha512")
        ``5 <md5crypt>``      -> ("__unmigratable__", "5")
        ``9 <scrypt>``        -> ("__unmigratable__", "9")
        ``bcrypt:...``        -> ("__unmigratable__", "bcrypt")
        ``fortios:ENC ...``   -> ("__unmigratable__", "fortios")

    The sentinel ``"__unmigratable__"`` makes the account a comment
    rather than a syntactically-correct but operationally-broken
    ``plaintext "..."`` line.  An empty secret comes back as
    ``("plaintext", "")``; :func:`aoss_accounts` gives it no account.
    """
    alg, payload = classify_hash(hashed)
    # Aruba-native algorithm — emit verbatim using the AOS-S
    # ``password manager <alg> <hash>`` form.  ``_AOS_KNOWN_ALGORITHMS``
    # is the Aruba-local emit-form vocabulary; the shared helper's
    # accepted-set covers exactly the same three for ``aruba_aoss``,
    # but keeping this check local documents the AOS-S CLI grammar
    # that consumes the ``alg`` token verbatim.
    if alg in _AOS_KNOWN_ALGORITHMS:
        return alg, payload
    # Cross-vendor unmigratable hash — surface via comment-form
    # review line.  The shared policy decides; Aruba just adapts.
    if not is_migratable(hashed, "aruba_aoss"):
        return "__unmigratable__", alg
    # Unreachable in practice: every algorithm outside
    # ``_AOS_KNOWN_ALGORITHMS`` should fail the shared helper's
    # migratability gate.  Defensive plaintext wrap of the original
    # preserves Aruba's historical "verbatim under plaintext"
    # fallback for any unforeseen algorithm token.
    return "plaintext", hashed


@dataclass(frozen=True)
class Account:
    """One local user, as the AOS-S output has it.

    Attributes:
        name: The user's name.
        role: ``manager`` (privilege 15) or ``operator`` (any other).
        line: The line written: a live ``password`` line, or a comment.
        live: Whether :attr:`line` is a live line.
        warning: The job's warning for a user left out for a reason of
            AOS-S's own (see the module docstring); empty otherwise.
        form: The form of a live line (``plaintext``, ``sha1``,
            ``sha256``); empty for a comment.
    """

    name: str
    role: str
    line: str
    live: bool
    warning: str = ""
    form: str = ""


def role_of(user: CanonicalLocalUser) -> str:
    """The AOS-S role of *user*: privilege 15 is ``manager``, any other
    level ``operator``."""
    return "manager" if user.privilege_level == 15 else "operator"


def _advice(
    role: str, name: str, kept: dict[str, str | None], *, typed: bool,
) -> str:
    """What the operator can do on the switch for an account of *role*
    that is not written, given the names of the accounts that are
    (*kept*).  *typed*: whether the name can be typed on AOS-S."""
    if kept[role] is not None:
        return (
            f'AOS-S keeps one {role} account, "{kept[role]}" above; a '
            f'second "password {role}" line would replace it'
        )
    if role == "operator" and kept["manager"] is None:
        return (
            "set the manager password on the switch first (an operator "
            "password alone gives manager access on AOS-S), then this one"
            + (f' with password operator user-name "{name}"' if typed else "")
        )
    if not typed:
        return "re-create it on the switch under a name AOS-S reads"
    return (
        f'set it on the switch with password {role} user-name "{name}", '
        "which asks for the password"
    )


def aoss_accounts(users: Sequence[CanonicalLocalUser]) -> list[Account]:
    """The account each of *users* is given on an AOS-S switch.

    Returns:
        One :class:`Account` a user, the manager role's first and then
        the operator role's; within a role, the live line (if any)
        first and then the others in the order of *users*.
    """
    # Why each user's secret cannot be written on AOS-S ("" if it can).
    read: list[tuple[CanonicalLocalUser, str, str, str]] = []
    for user in users:
        alg, value = _split_aos_hash(user.hashed_password)
        if alg == "__unmigratable__":
            why = f"{value} hash from source vendor cannot be re-used on AOS-S"
        elif breaks_its_quotes(user.name) or breaks_its_quotes(value):
            why = (
                "a value of it holds white space or a quote, which AOS-S "
                "does not read as one value"
            )
        elif not user.name:
            why = "it has no name"
        elif not value:
            why = "no password for this account was read from the source"
        else:
            why = ""
        read.append((user, alg, value, why))

    # The user each role is given: the first that can be written, and
    # for the operator role only beside a manager.
    given: dict[str, int | None] = dict.fromkeys(ROLES)
    for role in ROLES:
        if role == "operator" and given["manager"] is None:
            break
        given[role] = next(
            (index for index, (user, _a, _v, why) in enumerate(read)
             if role_of(user) == role and not why),
            None,
        )
    kept = {
        role: (read[index][0].name if index is not None else None)
        for role, index in given.items()
    }

    accounts: list[Account] = []
    for role in ROLES:
        live: list[Account] = []
        held: list[Account] = []
        for index, (user, alg, value, why) in enumerate(read):
            if role_of(user) != role:
                continue
            name = user.name
            if index == given[role]:
                live.append(Account(
                    name, role,
                    f'password {role} user-name "{name}" {alg} "{value}"',
                    live=True,
                    form=alg,
                ))
                continue
            warning = ""
            if not why and kept[role] is None:
                # An operator that could be written, held back for want
                # of a manager.
                why = "no manager account is written"
                warning = (
                    f'Local user "{name}" (operator) is not written for '
                    f"AOS-S: no manager account is, and on AOS-S an "
                    f"operator password alone gives manager access.  It is "
                    f"a review comment; set the manager password on the "
                    f"switch first."
                )
            elif not why:
                warning = (
                    f'Local user "{name}" ({role}) is not written for '
                    f'AOS-S: AOS-S keeps one {role} account, and '
                    f'"{kept[role]}" has it.  It is a review comment; to '
                    f'keep "{name}" instead, drop "{kept[role]}" in the '
                    f"local-user rename map."
                )
            elif why.startswith("no password"):
                warning = (
                    f'Local user "{name}" ({role}) is not written for '
                    f"AOS-S: no password for it was read from the source, "
                    f"and AOS-S has no account without one.  It is a "
                    f"review comment."
                )
            typed = bool(name) and not breaks_its_quotes(name)
            said = "; ".join(
                part for part in (why, _advice(role, name, kept, typed=typed))
                if part
            )
            shown = f'"{name}"' if typed else name
            held.append(Account(
                name, role,
                f"; password {role} user-name {shown} -- review: {said}",
                live=False,
                warning=warning,
            ))
        accounts.extend(live + held)
    return accounts


def _hashed(accounts: Sequence[Account]) -> tuple[list[Account], list[str]]:
    """The live accounts of *accounts* whose line is hashed, and the
    hashed forms among them in :data:`HASHED_FORMS` order."""
    hashed = [a for a in accounts if a.live and a.form in HASHED_FORMS]
    forms = [f for f in HASHED_FORMS if any(a.form == f for a in hashed)]
    return hashed, forms


def _needs(forms: Sequence[str]) -> str:
    """What a switch needs for lines of *forms*, after "needs"."""
    said = (
        "include-credentials on the switch, which keeps its credentials "
        "in its config file"
    )
    if "sha256" in forms:
        said += (
            ", and a sha256 one password non-plaintext-sha256 as well, "
            "which not every switch has"
        )
        if "sha1" in forms:
            said += " and in which the switch does not take sha1"
    return said


def _setting_advice(hashed: Sequence[Account], forms: Sequence[str]) -> str:
    """What to do on the switch for lines of *forms*."""
    if "sha1" in forms and "sha256" in forms:
        sha1 = next(a.name for a in hashed if a.form == "sha1")
        return (
            "set both on the switch before the account lines, and the "
            f'password of "{sha1}" there by hand'
        )
    if "sha256" in forms:
        return (
            "set both on the switch before the account lines, or set "
            "the passwords there"
        )
    return (
        "set it on the switch before the account lines, or set the "
        "passwords there"
    )


def setting_review(accounts: Sequence[Account]) -> str:
    """The ``review:`` line written above *accounts* when a live line
    of them is hashed; ``""`` when none is (see the module docstring).
    It names the forms and the settings, and holds no secret."""
    hashed, forms = _hashed(accounts)
    if not hashed:
        return ""
    written = "neither is written" if "sha256" in forms else "not written"
    return (
        f"; review: a hashed password line ({', '.join(forms)}) needs "
        f"{_needs(forms)}; {written} -- {_setting_advice(hashed, forms)}"
    )


def setting_warning(accounts: Sequence[Account]) -> str:
    """The job's warning beside :func:`setting_review`; ``""`` when no
    live line of *accounts* is hashed."""
    hashed, forms = _hashed(accounts)
    if not hashed:
        return ""
    names = " and ".join(f'"{a.name}"' for a in hashed)
    what = "a hashed password" if len(hashed) == 1 else "hashed passwords"
    written = "neither is written" if "sha256" in forms else "it is not written"
    advice = _setting_advice(hashed, forms)
    return (
        f"The AOS-S output writes {names} with {what} "
        f"({', '.join(forms)}), and a hashed password line needs "
        f"{_needs(forms)}; {written}.  {advice[0].upper()}{advice[1:]}."
    )


def account_lines(users: Sequence[CanonicalLocalUser]) -> list[str]:
    """The lines the AOS-S output has for *users*: the review line of
    :func:`setting_review` (if any), then the accounts."""
    accounts = aoss_accounts(users)
    review = setting_review(accounts)
    return [review] * bool(review) + [account.line for account in accounts]


def account_warnings(users: Sequence[CanonicalLocalUser]) -> list[str]:
    """The job's warnings for *users* on an AOS-S target: the one of
    :func:`setting_warning` (if any), then one a user left out."""
    accounts = aoss_accounts(users)
    said = setting_warning(accounts)
    return [said] * bool(said) + [
        account.warning for account in accounts if account.warning
    ]
