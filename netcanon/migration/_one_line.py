"""A value of the canonical tree is written on one line, as text.

Every renderer writes a config a line at a time and puts a value into
its line as it stands, so a value that holds a line break is written as
lines of its own, and the device reads the text after the break as a
command.  An interface description that held ``username x privilege 15
nopassword`` after a break was that account, with no password, on
IOS-XE, EOS, NX-OS, AOS-CX and OS10, in a job that said ``completed``;
every renderer wrote the extra line.  The parsers that read XML (OPNsense,
IOS-XE over NETCONF) keep a line break that an element's text holds, and
FortiOS prints a value of several lines inside its quotes, so the tree
can hold one.

No target is given a value of more than one line, whatever the field:

* :func:`one_line_each` writes each run of line breaks in a value as
  one space, in place, and returns where it did -- the pipeline calls it
  after the transforms (an operator's map is a value too) and before
  validation, and says each place in the job's warnings;
* :func:`first_line_break` is the check :meth:`CodecBase.render` makes
  before any renderer runs: a tree that still holds a line break is
  refused, so a caller that renders without the pipeline cannot write
  one either.

A line break is any character :meth:`str.splitlines` ends a line at
(:data:`LINE_BREAKS`), not only ``\\n``: a device, or a reader of the
output, may end a line at any of them.

What this costs a target that could hold the break -- an XML target, or
FortiOS inside its quotes -- is the layout of the text, and the warning
says so.  It is the same rule for every target because the alternative
is a list of which field of which target may hold a break, and a value
in the wrong place on that list is an account.

Nor is any target given a control character (:data:`CONTROL_CHARACTERS`:
every code point Unicode calls one, but a tab and the line breaks).  A
parser that reads its config as text keeps one a value holds, and a
renderer writes it as it stands, so an IOS-XE description holding
``ESC [1A ESC [2K`` -- up a line, and erase it -- was written into every
target's output, and an operator who read that output on a terminal saw
the line above it gone: an account written there from another part of
the config, say.  The same two halves: :func:`text_only_each` writes
each run of them as one space and returns where, and the pipeline says
so; :func:`first_control_character` is the render's check.  A space and
not nothing, so that the words on either side of it stay two.

A secret is mended neither way: with a space in the place of a break
or a control character, or with the character taken out, it is
another secret, and a target that writes a secret with white space
between quotes (AOS-S, FortiOS, Junos, RouterOS, OPNsense) wrote it.
:func:`secrets_left_out` runs first: each secret (:data:`SECRETS`)
that holds either is left out with what it composes -- a local user
or an SNMPv3 user whole, a community with every trap host that would
carry it, a RADIUS key or an FHRP authentication alone, the server and
the group kept -- the granularity the credential rules set.  The
pipeline says each place and holds the job ``partial``.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from .limits import ticked

#: The characters :meth:`str.splitlines` ends a line at.  A test holds
#: this to what ``splitlines`` does over every code point.
LINE_BREAKS = "\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"

#: A run of them; the same characters, as a test holds.
_A_RUN = re.compile(r"[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]+")

#: The code points Unicode calls control characters (category ``Cc``)
#: but a tab, which is white space, and :data:`LINE_BREAKS`, which have
#: a rule of their own: what a terminal acts on rather than shows.  A
#: test holds this to ``unicodedata`` over every code point.
CONTROL_CHARACTERS = (
    "".join(map(chr, range(0x09)))
    + "".join(map(chr, range(0x0E, 0x1C)))
    + "\x1f\x7f"
    + "".join(map(chr, range(0x80, 0x85)))
    + "".join(map(chr, range(0x86, 0xA0)))
)

#: A run of them; the same characters, as a test holds.
_A_CONTROL_RUN = re.compile(r"[\x00-\x08\x0e-\x1b\x1f\x7f-\x84\x86-\x9f]+")

#: The field that names a record in a place, first present first:
#: ``interfaces[Gi1].description``, ``vlans[10].name``,
#: ``static_routes[0.0.0.0/0].description``.
_NAMED_BY = ("name", "id", "destination", "network", "host", "prefix")


def _label(record: Any, index: int) -> str:
    for key in _NAMED_BY:
        value = getattr(record, key, None)
        if isinstance(value, bool) or value is None or value == "":
            continue
        if isinstance(value, (str, int)):
            text = str(value)
            if not _A_RUN.search(text) and not _A_CONTROL_RUN.search(text):
                return text
    return str(index)


#: The types a value of the tree has that hold no text.
_NO_TEXT = frozenset({int, float, bool, type(None)})


class _Walk:
    """One walk of a tree for the runs *pattern* finds.  ``mend`` writes
    each run as a space; ``named`` puts each record's name in the
    place, else ``[]``.

    It reads every field a record holds, whatever the schema says the
    field is (a parser that appends to a list is not validated), and a
    list of values with no text in them, or of text with no line break
    in it, is read at once rather than value by value: a trunk's list
    of every VLAN is 4,094 of them."""

    def __init__(
        self, *, mend: bool, named: bool, first: bool,
        pattern: re.Pattern[str] = _A_RUN,
    ) -> None:
        self.pattern = pattern
        self.mend = mend
        self.named = named
        self.first = first
        self.found: list[str] = []

    def done(self) -> bool:
        return self.first and bool(self.found)

    def _one(self, value: str, where: str) -> str | None:
        if self.pattern.search(value) is None:
            return None
        self.found.append(where)
        return self.pattern.sub(" ", value) if self.mend else None

    def model(self, record: BaseModel, where: str) -> None:
        held = dict(record.__dict__)
        held.update(record.__pydantic_extra__ or {})
        for name, value in held.items():
            if type(value) in _NO_TEXT or not value:
                continue
            here = f"{where}.{name}" if where else name
            if isinstance(value, str):
                mended = self._one(value, here)
                if mended is not None:
                    setattr(record, name, mended)
            else:
                self.value(value, here)
            if self.done():
                return

    def value(self, value: Any, where: str) -> None:
        if isinstance(value, BaseModel):
            self.model(value, where)
        elif isinstance(value, list):
            self.items(value, where)
        elif isinstance(value, dict):
            self.mapping(value, where)
        elif isinstance(value, (tuple, set, frozenset)):
            for item in ticked(list(value)):
                if isinstance(item, str):
                    self._one(item, f"{where}[]")
                else:
                    self.value(item, f"{where}[]")
            # Not mended: no field of the tree is one, and what a
            # tuple or a set holds is not written back in place.

    def items(self, values: list[Any], where: str) -> None:
        kinds = set(map(type, values))
        if kinds <= _NO_TEXT:
            return
        if kinds == {str} and not self.pattern.search("".join(values)):
            return
        for index, item in enumerate(ticked(values)):
            if isinstance(item, str):
                mended = self._one(item, where)
                if mended is not None:
                    values[index] = mended
            elif isinstance(item, BaseModel):
                label = _label(item, index) if self.named else ""
                self.model(item, f"{where}[{label}]")
            elif type(item) not in _NO_TEXT:
                self.value(item, f"{where}[]")
            if self.done():
                return

    def mapping(self, values: dict[Any, Any], where: str) -> None:
        renamed: dict[Any, Any] = {}
        for key in ticked(list(values)):
            item = values[key]
            label = key if self.named and isinstance(key, str) else ""
            if isinstance(key, str):
                mended = self._one(key, f"{where} (a key)")
                if mended is not None:
                    renamed[key] = mended
                    label = mended if self.named else ""
            if isinstance(item, str):
                mended = self._one(item, f"{where}[{label}]")
                if mended is not None:
                    values[key] = mended
            elif type(item) not in _NO_TEXT:
                self.value(item, f"{where}[{label}]")
            if self.done():
                return
        if renamed:
            rebuilt = {renamed.get(k, k): v for k, v in values.items()}
            values.clear()
            values.update(rebuilt)


def one_line_each(tree: Any) -> list[str]:
    """Write each run of line breaks in every text value of *tree* as
    one space, in place.

    Returns:
        Where a value held one, a place each value, the records named
        (``interfaces[Gi1].description``).  Empty when no value did,
        and then *tree* is as it was.
    """
    walk = _Walk(mend=True, named=True, first=False)
    walk.value(tree, "")
    return walk.found


def first_line_break(tree: Any) -> str | None:
    """The first place in *tree* whose value holds a line break, by
    field and not by record (``interfaces[].description``: what it
    returns is said in an error, and an error is logged, so it names
    nothing of the config), or ``None``."""
    walk = _Walk(mend=False, named=False, first=True)
    walk.value(tree, "")
    return walk.found[0] if walk.found else None


def said(where: str) -> str:
    """The job's warning for a value :func:`one_line_each` wrote on one
    line."""
    return (
        f"{where} held a line break: it is written on one line, each "
        "break as a space, because no target is given a value of more "
        "than one line"
    )


def text_only_each(tree: Any) -> list[str]:
    """Write each run of :data:`CONTROL_CHARACTERS` in every text value
    of *tree* as one space, in place.

    Returns:
        Where a value held one, as :func:`one_line_each` returns it.
        Empty when no value did, and then *tree* is as it was.
    """
    walk = _Walk(mend=True, named=True, first=False, pattern=_A_CONTROL_RUN)
    walk.value(tree, "")
    return walk.found


def first_control_character(tree: Any) -> str | None:
    """The first place in *tree* whose value holds one of the
    :data:`CONTROL_CHARACTERS`, by field, as :func:`first_line_break`
    names it; or ``None``."""
    walk = _Walk(mend=False, named=False, first=True, pattern=_A_CONTROL_RUN)
    walk.value(tree, "")
    return walk.found[0] if walk.found else None


def said_of_a_control_character(where: str) -> str:
    """The job's warning for a value :func:`text_only_each` mended."""
    return (
        f"{where} held a control character: each run of them is written "
        "as a space, because no target is given a character a terminal "
        "acts on rather than shows"
    )


#: The places of the tree that hold a secret, by field.  A test holds
#: them to the schema, and :func:`secrets_left_out` to each.
SECRETS = (
    "snmp.community",
    "snmp.v3_users.auth_passphrase",
    "snmp.v3_users.priv_passphrase",
    "local_users.hashed_password",
    "radius_servers.key",
    "interfaces.vrrp_groups.authentication",
)


def _not_text(value: Any) -> bool:
    """Whether *value* holds a line break or a control character."""
    return isinstance(value, str) and (
        _A_RUN.search(value) is not None
        or _A_CONTROL_RUN.search(value) is not None
    )


def _secret_said(where: str, what: str) -> str:
    return (
        f"{where} held a line break or a control character: with a "
        f"space in its place it would be another secret, so {what}"
    )


def secrets_left_out(tree: Any) -> list[str]:
    """Leave out, in place, each secret of *tree* (:data:`SECRETS`)
    that holds a line break or a control character, with what it
    composes.  The pipeline calls it before :func:`one_line_each`, which
    would write such a secret with a space in its place.

    Returns:
        The job's warning for each, naming the place and never the
        value.  Empty when no secret held one, and then *tree* is as it
        was.
    """
    said: list[str] = []
    snmp = getattr(tree, "snmp", None)
    if snmp is not None:
        if _not_text(snmp.community):
            snmp.community = ""
            snmp.trap_hosts = []
            said.append(_secret_said(
                "snmp.community",
                "it is left out, with every trap host that would carry "
                "it; re-create them on the device"))
        kept = []
        for index, user in enumerate(snmp.v3_users):
            if _not_text(user.auth_passphrase) or _not_text(user.priv_passphrase):
                said.append(_secret_said(
                    f"snmp.v3_users[{_label(user, index)}]",
                    "the user is left out, with every line that composes "
                    "it; re-create it on the device"))
            else:
                kept.append(user)
        if len(kept) != len(snmp.v3_users):
            snmp.v3_users = kept
    users = getattr(tree, "local_users", None) or []
    kept_users = []
    for index, user in enumerate(users):
        if _not_text(user.hashed_password):
            said.append(_secret_said(
                f"local_users[{_label(user, index)}].hashed_password",
                "the account is left out; re-create it on the device"))
        else:
            kept_users.append(user)
    if len(kept_users) != len(users):
        tree.local_users = kept_users
    for index, server in enumerate(getattr(tree, "radius_servers", None) or []):
        if _not_text(server.key):
            server.key = ""
            said.append(_secret_said(
                f"radius_servers[{_label(server, index)}].key",
                "the key is left out and the server kept; set the key on "
                "the device"))
    for index, iface in enumerate(getattr(tree, "interfaces", None) or []):
        for number, group in enumerate(iface.vrrp_groups):
            if _not_text(group.authentication):
                group.authentication = ""
                said.append(_secret_said(
                    f"interfaces[{_label(iface, index)}].vrrp_groups"
                    f"[{_label(group, number)}].authentication",
                    "the authentication is left out and the group kept; "
                    "set it on the device"))
    return said
