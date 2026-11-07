"""What an HSRP group states, read the same way from both Cisco grammars.

IOS-XE writes each statement of a group on a line of its own under the
interface (``standby <group> <statement>``, the number left out for
group 0); NX-OS opens a block (``hsrp <group>``) whose lines are the
statements alone.  After the group number the words are Cisco's in
both, and so is what a group is when it states nothing: priority 100,
no preemption, version 1 (Cisco's IOS and Nexus HSRP guides: "The
default priority is 100", preemption "is disabled by default",
"Version 1 is the default version of HSRP").

A statement the tree holds is read into the group: the virtual
addresses (``ip <address> [secondary]``, a link-local ``ipv6
<address>``), ``priority``, ``preempt``, a key typed as it is
(``authentication text <key>``, ``authentication md5 key-string [0]
<key>``) and ``mac-address``.  Every other statement is said in a row of
``dropped_tier3_sections`` (:meth:`Unread.rows`), one row for each kind
of statement, naming a few of the places it was found and never a
value -- a key, an address, a name.  Before this module both parsers
let such lines go by: the IOS-XE parser read no ``standby`` line at
all, and the NX-OS parser read ``authentication md5 key-string 7
<key>`` as the key ``7``.

A key the device printed encrypted (``key-string 7``) is not read.  It
is not the key, and written into another device's key slot it would be
a key the group's other routers do not have; the group is kept with no
authentication, and its row says so.

The version is a statement of the interface, not of a group.  Version 2
is what a group above 255, or a group with an IPv6 address, needs, and
a renderer that writes HSRP writes it for such a group; stated where no
group needs it, it is not kept, and said.

The hello time is not read (``timers`` is said), and a group's
``advertisement_interval`` keeps the tree's default: neither renderer
that writes HSRP writes one.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..canonical.intent import CanonicalVRRPGroup
from ._helpers import NAMES_SHOWN, _is_link_local_v6

#: The highest group number of HSRP version 2.  Version 1 numbers its
#: groups 0 to :data:`V1_GROUP_MAX`.
GROUP_MAX = 4095
V1_GROUP_MAX = 255

#: The statements a group makes, after its number.  A line of the
#: interface whose first word after ``standby`` is one of these, and no
#: number, is a statement of group 0.
GROUP_STATEMENTS = frozenset({
    "authentication", "follow", "ip", "ipv6", "mac-address", "name",
    "preempt", "priority", "timers", "track",
})

#: The statements of the interface the readers know by name.  Any
#: other word is said as "another statement": a row shows a word of the
#: config only where the word is one of the grammar's.
_INTERFACE_STATEMENTS = frozenset({
    "bfd", "delay", "mac-refresh", "redirect", "use-bia", "version",
})

#: What each kind of statement that is not read leaves out, for its row.
_LEFT_OUT: dict[str, str] = {
    "authentication md5 key-chain": (
        "the key chain is not translated, and the group is written with "
        "no authentication"
    ),
    "authentication md5 key-string 7": (
        "a key the device printed encrypted is not the key, and the group "
        "is written with no authentication"
    ),
    "authentication md5 key-string timeout": (
        "the key is written without its timeout"
    ),
    "authentication": (
        "the statement is not read, and the group is written with no "
        "authentication"
    ),
    "follow": "the group no longer follows another group",
    "ip": "the statement is not read: no virtual address is taken from it",
    "ip (no address)": (
        "the virtual address is learned from the group's other routers, "
        "which is not translated: the group has no address"
    ),
    "ipv6": "the IPv6 virtual address is not translated",
    "ipv6 autoconfig": "the IPv6 virtual address is not translated",
    "ipv6 group": "the IPv6 group is not translated",
    "mac-address": "the statement is not read: the group uses its own MAC",
    "name": "the redundancy name is not translated",
    "preempt delay": (
        "the delay is not translated: the group preempts without it"
    ),
    "priority": "the statement is not read: the group has priority 100",
    "timers": (
        "the hello and hold times are not translated: the group uses its "
        "target's own"
    ),
    "track": "the priority tracking is not translated",
    "version 2": (
        "the version is not kept: it is written only where a group needs "
        "version 2 (a group above 255, or an IPv6 address), and a group "
        "written for version 1 does not talk to a version 2 peer"
    ),
    "bfd": "BFD for the groups is not translated",
    "delay": "the delay before the groups start is not translated",
    "mac-refresh": "the statement is not translated",
    "redirect": "the statement is not translated",
    "use-bia": (
        "the groups are written with their virtual MAC, not the interface's "
        "own"
    ),
    "version": "the statement is not read",
    "a group number above 4095": "the statement is not read",
    "another statement": "the statement is not translated",
}

#: A MAC as Cisco prints one.
_DOTTED_MAC_RE = re.compile(r"[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}", re.IGNORECASE)


def group_number(word: str) -> int | None:
    """The group number *word* is, or ``None`` past :data:`GROUP_MAX`.

    Read only from a word of digits: four at most after any leading
    zeros, so that no long run of digits is converted.
    """
    if not word.isdigit() or not word.isascii():
        return None
    digits = word.lstrip("0") or "0"
    if len(digits) > 4:
        return None
    number = int(digits)
    return number if number <= GROUP_MAX else None


def _ipv4(word: str) -> bool:
    try:
        ipaddress.IPv4Address(word)
    except ValueError:
        return False
    return True


def _link_local(word: str) -> bool:
    if "/" in word:
        return False
    try:
        ipaddress.IPv6Address(word)
    except ValueError:
        return False
    return _is_link_local_v6(word)


@dataclass
class _Group:
    primary: str = ""
    secondaries: list[str] = field(default_factory=list)
    ipv6s: list[str] = field(default_factory=list)
    mac: str = ""
    priority: int = 100
    preempt: bool = False
    authentication: str = ""


class Groups:
    """The HSRP groups of one interface, as its lines state them."""

    def __init__(self) -> None:
        self._groups: dict[int, _Group] = {}
        self._version_2 = False
        #: ``(kind, group)`` for each statement not read; ``group`` is
        #: ``None`` for a statement of the interface.
        self.unread: list[tuple[str, int | None]] = []

    def open(self, gid: int) -> None:
        """A group is configured, whatever its lines go on to state."""
        self._groups.setdefault(gid, _Group())

    def left_out(self, kind: str, gid: int | None = None) -> None:
        """A statement of *kind* is not read."""
        self.unread.append((kind, gid))

    def group_statement(
        self, gid: int, words: Sequence[str], *, negated: bool = False,
    ) -> None:
        """Read one statement of group *gid*: *words* from its keyword on.

        ``no preempt`` is read; any other statement that begins with
        ``no`` is said.
        """
        group = self._groups.setdefault(gid, _Group())
        keyword = words[0].lower()
        rest = list(words[1:])
        if negated:
            if keyword == "preempt" and not rest:
                group.preempt = False
            else:
                self.left_out("another statement", gid)
            return
        reader = _READERS.get(keyword)
        kind = reader(group, rest) if reader else (
            keyword if keyword in GROUP_STATEMENTS else "another statement"
        )
        if kind:
            self.left_out(kind, gid)

    def interface_statement(self, words: Sequence[str]) -> None:
        """Read a statement of the interface: *words* after ``standby``
        or ``hsrp``, the first of which is not a group's."""
        keyword = words[0].lower() if words else ""
        if keyword == "version" and len(words) == 2 and words[1] in ("1", "2"):
            self._version_2 = words[1] == "2"
            return
        if keyword.isdigit():
            self.left_out("a group number above 4095")
            return
        self.left_out(
            keyword if keyword in _INTERFACE_STATEMENTS else "another statement"
        )

    def built(self) -> list[CanonicalVRRPGroup]:
        """The groups, in the order of their numbers."""
        return [
            CanonicalVRRPGroup(
                group_id=gid,
                mode="hsrp",
                virtual_ips=[*([g.primary] if g.primary else []), *g.secondaries],
                virtual_ipv6s=list(g.ipv6s),
                virtual_mac=g.mac,
                priority=g.priority,
                preempt=g.preempt,
                authentication=g.authentication,
            )
            for gid, g in sorted(self._groups.items())
        ]

    def kinds_left_out(self) -> list[tuple[str, int | None]]:
        """Each statement not read, and version 2 where no group needs it."""
        needs_2 = any(
            gid > V1_GROUP_MAX or g.ipv6s for gid, g in self._groups.items()
        )
        if self._version_2 and not needs_2:
            return [*self.unread, ("version 2", None)]
        return list(self.unread)


def _read_ip(group: _Group, rest: list[str]) -> str | None:
    if not rest:
        return "ip (no address)"
    if len(rest) == 1 and _ipv4(rest[0]):
        group.primary = rest[0]
        return None
    if len(rest) == 2 and rest[1].lower() == "secondary" and _ipv4(rest[0]):
        group.secondaries.append(rest[0])
        return None
    return "ip"


def _read_ipv6(group: _Group, rest: list[str]) -> str | None:
    if len(rest) == 1 and rest[0].lower() == "autoconfig":
        return "ipv6 autoconfig"
    if len(rest) == 1 and _link_local(rest[0]):
        group.ipv6s.append(rest[0])
        return None
    return "ipv6"


def _read_priority(group: _Group, rest: list[str]) -> str | None:
    if (
        len(rest) == 1 and rest[0].isdigit() and rest[0].isascii()
        and len(rest[0]) <= 3 and int(rest[0]) <= 255
    ):
        group.priority = int(rest[0])
        return None
    return "priority"


def _read_preempt(group: _Group, rest: list[str]) -> str | None:
    group.preempt = True
    return "preempt delay" if rest else None


def _read_authentication(group: _Group, rest: list[str]) -> str | None:
    words = [w.lower() for w in rest[:3]]
    kind: str | None = "authentication"
    key = ""
    if len(rest) == 2 and words[0] == "text":
        key, kind = f"plain:{rest[1]}", None
    elif len(rest) == 1 and words[0] not in ("text", "md5"):
        # The form of a text key with no ``text`` before it.
        key, kind = f"plain:{rest[0]}", None
    elif words[:2] == ["md5", "key-chain"]:
        kind = "authentication md5 key-chain"
    elif words[:2] == ["md5", "key-string"]:
        kind, key = _md5_key(rest[2:])
    group.authentication = key
    return kind


def _md5_key(words: list[str]) -> tuple[str | None, str]:
    """What ``key-string [0 | 7] <key> [timeout <seconds>]`` holds: the
    kind of row it needs, if any, and the key as the tree holds it."""
    if len(words) >= 2 and words[0] in ("0", "7"):
        if words[0] == "7":
            return "authentication md5 key-string 7", ""
        words = words[1:]
    if len(words) == 1:
        return None, f"md5:{words[0]}"
    if len(words) == 3 and words[1].lower() == "timeout" and words[2].isdigit():
        return "authentication md5 key-string timeout", f"md5:{words[0]}"
    return "authentication", ""


def _read_mac(group: _Group, rest: list[str]) -> str | None:
    if len(rest) == 1 and _DOTTED_MAC_RE.fullmatch(rest[0]):
        hex_only = rest[0].replace(".", "").lower()
        group.mac = ":".join(hex_only[i:i + 2] for i in (0, 2, 4, 6, 8, 10))
        return None
    return "mac-address"


_READERS = {
    "authentication": _read_authentication,
    "ip": _read_ip,
    "ipv6": _read_ipv6,
    "mac-address": _read_mac,
    "preempt": _read_preempt,
    "priority": _read_priority,
}


@dataclass
class _Seen:
    shown: list[str] = field(default_factory=list)
    count: int = 0


class Unread:
    """The HSRP statements the parser of a config did not read, by kind.

    *keyword* is the word the platform writes them with (``standby``,
    ``hsrp``).  A row is a kind of statement, a few of the places it is
    in and how many more, and what is not translated: bounded by the
    number of kinds, however many interfaces state it.
    """

    def __init__(self, keyword: str) -> None:
        self._keyword = keyword
        self._seen: dict[str, _Seen] = {}

    def add(self, interface: str, groups: Groups) -> None:
        """What *groups*, the groups of *interface*, did not read."""
        for kind, gid in groups.kinds_left_out():
            seen = self._seen.setdefault(kind, _Seen())
            seen.count += 1
            if len(seen.shown) < NAMES_SHOWN:
                where = interface if gid is None else f"{interface} group {gid}"
                seen.shown.append(where)

    def rows(self) -> list[str]:
        """One row of ``dropped_tier3_sections`` for each kind."""
        rows = []
        for kind, seen in self._seen.items():
            where = ", ".join(seen.shown)
            rest = seen.count - len(seen.shown)
            if rest > 0:
                where += f" and {rest} more"
            left_out = _LEFT_OUT.get(kind, _LEFT_OUT["another statement"])
            rows.append(f"{self._keyword} {kind}: {where} -- {left_out}")
        return rows
