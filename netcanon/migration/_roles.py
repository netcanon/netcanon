"""A local user's role crosses only between two codecs of one platform.

A role is a NAME that a device looks up among the roles it has: EOS,
NX-OS and OS10 ``role``, AOS-CX and IOS XR ``group``, Junos ``class``,
FortiOS ``accprofile``.  Another platform's name is a name the target
either does not have (a Junos ``super-user`` on NX-OS, an NX-OS
``network-admin`` on Junos) or has with rights of its own (an IOS-XE
privilege-1 account read as ``operator`` is, on Junos, a class that may
clear, reset and trace).  Up to 2026-11 seven renderers wrote the
source's role as it stood, whatever platform it came from, and over the
committed captures most of the accounts they wrote from another
platform named a role the target does not ship.

The rule
--------
The source's role is written only where the tree was read by a codec of
the TARGET's platform: ``tree.source_vendor`` (the ``vendor_id`` the
parser stamps) is the target codec's ``vendor_id``.  IOS-XE NETCONF and
IOS-XE CLI are one platform.  Everywhere else the target chooses one of
its own built-in roles from ``privilege_level``, as it does for an
account that names no role.  Each target's capability matrix declares
``/local-users/user/role`` lossy, so that the validation report of every
job that holds a role says so.

``privilege_level`` is the one fact about an account's rights that every
parser states in the same terms (15 is an administrator, anything below
is not), so it is the one a target reads.  A target with no built-in
role below an administrator leaves such an account out, with a review
line in its place (:func:`format_below_admin_comment`) and a warning in
the job (:func:`below_admin_warnings`), rather than make it an
administrator:

=================  ===================================================
target             why
=================  ===================================================
``vyos``           Every local login user on VyOS 1.3 to 1.5 has full
                   configuration access and sudo (``level`` was
                   removed in 1.3, vyos.dev T1323).
``fortigate_cli``  FortiOS documents no built-in admin profile below
                   ``super_admin``; the other, ``prof_admin``, is
                   read-write to every permission group.  An account
                   of a FortiGate keeps the profile it names.
=================  ===================================================

A tree built with no ``source_vendor`` (by hand, in a test) has no
platform, so its role is not written either: the safe side.

The parsers record the role their config NAMES, or none.  Four made one
up from the privilege level (IOS-XE, RouterOS, OPNsense and VyOS wrote
``admin`` / ``operator`` / ``user``), and FortiOS wrote such a name back
as the profile of an admin that named none.
"""

from __future__ import annotations

from collections.abc import Iterable

from ._comments import comment
from ._user_secrets import holds_no_secret, is_migratable

__all__ = [
    "BELOW_ADMIN_WHY",
    "below_admin",
    "below_admin_warnings",
    "format_below_admin_comment",
    "own_role",
    "same_platform",
]

#: The privilege level of an administrator, on every parser's scale.
ADMIN = 15

#: For each target that has no built-in role below an administrator, why
#: (a clause of the review line and of the warning).
BELOW_ADMIN_WHY: dict[str, str] = {
    "vyos": (
        "every local login user on VyOS has full configuration access "
        "and sudo"
    ),
    "fortigate_cli": (
        "FortiOS documents no built-in admin profile below super_admin "
        "(prof_admin can change the configuration)"
    ),
}

#: The targets of :data:`BELOW_ADMIN_WHY` that have roles below an
#: administrator of their own, which an account of their own platform
#: can name: a FortiGate's admin profiles.  VyOS has no role at all, so
#: no tree, a VyOS one included, keeps an account below one there.
_OWN_ROLES_BELOW_ADMIN = frozenset({"fortigate_cli"})


def _vendor_id(target_codec: str) -> str:
    """The ``vendor_id`` of the codec named *target_codec*, from the
    registry (imported here, not at module level: the codecs import this
    module)."""
    from netcanon.migration.codecs.registry import get_codec

    return get_codec(target_codec).capabilities.vendor_id


def same_platform(source_vendor: str, target_codec: str) -> bool:
    """True when a tree stamped *source_vendor* was read by a codec of
    *target_codec*'s platform.

    Args:
        source_vendor: The tree's ``source_vendor`` (a ``vendor_id``).
        target_codec: The name the target codec is registered under.

    Returns:
        False for an empty *source_vendor*.
    """
    if not source_vendor:
        return False
    return source_vendor == _vendor_id(target_codec)


def own_role(user, source_vendor: str, target_codec: str) -> str:
    """The role *user* names, where it is a name of *target_codec*'s
    platform; otherwise ``""``, which every renderer reads as "choose a
    role from the privilege level".

    Args:
        user: A :class:`~netcanon.migration.canonical.intent.CanonicalLocalUser`.
        source_vendor: The tree's ``source_vendor``.
        target_codec: The name the target codec is registered under.

    Returns:
        ``user.role`` or ``""``.
    """
    if same_platform(source_vendor, target_codec):
        return user.role
    return ""


def below_admin(user, source_vendor: str, target_codec: str) -> bool:
    """True when *target_codec* has no role for *user*: it is one of
    :data:`BELOW_ADMIN_WHY`, the account is below an administrator, and
    it names no role of the target's platform below one (only a
    FortiGate has such roles: :data:`_OWN_ROLES_BELOW_ADMIN`).

    Args:
        user: A local user of the tree.
        source_vendor: The tree's ``source_vendor``.
        target_codec: The name the target codec is registered under.
    """
    return (
        target_codec in BELOW_ADMIN_WHY
        and user.privilege_level < ADMIN
        and not (
            target_codec in _OWN_ROLES_BELOW_ADMIN
            and own_role(user, source_vendor, target_codec)
        )
    )


def format_below_admin_comment(
    user, target_codec: str, comment_syntax: str = "hash",
) -> str:
    """The review line written in place of an account
    :func:`below_admin` says the target has no role for::

        user "<name>" -- review: the source gives this account privilege
        level <n>, below an administrator, and <why>; it is left out:
        add it on the device with the rights it should have

    Args:
        user: The local user.
        target_codec: One of :data:`BELOW_ADMIN_WHY`.
        comment_syntax: As for
            :func:`netcanon.migration._user_secrets.format_review_comment`.
    """
    separator = "-" if comment_syntax == "xml" else "--"
    body = (
        f'user "{user.name}" {separator} review: the source gives this '
        f"account privilege level {user.privilege_level}, below an "
        f"administrator, and {BELOW_ADMIN_WHY[target_codec]}; it is left "
        f"out: add it on the device with the rights it should have"
    )
    return comment(body, comment_syntax)


def below_admin_warnings(
    users: Iterable, source_vendor: str, target_codec: str, target_label: str,
) -> list[str]:
    """The job's warning for each account the renderer leaves out for
    :func:`below_admin`.

    The renderer asks first whether the account holds a password and
    whether the target can take it (each a review line of its own), so
    an account is warned of here only where both hold.

    Args:
        users: The tree's ``local_users``.
        source_vendor: The tree's ``source_vendor``.
        target_codec: The name the target codec is registered under.
        target_label: The target's name in the sentence ("VyOS").

    Returns:
        One sentence an account, naming it and never a secret of it.
    """
    if target_codec not in BELOW_ADMIN_WHY:
        return []
    return [
        f'Local user "{user.name}" is not written for {target_label}: '
        f"the source gives it privilege level {user.privilege_level}, "
        f"below an administrator, and {BELOW_ADMIN_WHY[target_codec]}.  "
        f"It is a review comment; add it on the device with the rights "
        f"it should have."
        for user in users
        if not holds_no_secret(user.hashed_password)
        and is_migratable(user.hashed_password, target_codec)
        and below_admin(user, source_vendor, target_codec)
    ]
