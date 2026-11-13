"""The switch's management plane: its DNS resolvers and domain, its time
client and its syslog servers, read from a config and written for a
tree.

What HPE documents.  The Aruba 2930F / 2930M Management and
Configuration Guide for ArubaOS-Switch 16.08:

* ``[no] ip dns server-address priority <1-3> <ip-addr>``, where
  configuring another address for a priority already given one "is not
  allowed", and ``[no] ip dns domain-name <domain-name-suffix>``, one
  suffix.  The HP 8200zl IPv6 configuration guide (K.13.01 and later):
  "Up to three DNS servers can be configured", IPv4 and IPv6 "in any
  combination", tried in ascending order of priority.
* ``[no] timesync { timep | sntp | timep-or-sntp | ntp }``, whose
  command page names ``timep-or-sntp`` the default.  (A page on SNTP
  speaks of a factory default where TimeP is selected; the command
  page is followed.  The output says ``timesync`` itself, so nothing
  written rests on the default.)
* SNTP: "Enabling the SNTP mode means to configure it for either
  broadcast or unicast mode"; ``sntp server`` is "Required only for
  unicast mode"; and SNTP has to be selected with ``timesync`` as
  well.  ``sntp server priority <1-3> <ip-addr>``, three at most, with
  a version number or a ``key-id`` after the address.  HP's IPv6 guide
  gives it IPv6 servers, a link-local one scoped ``%vlan<id>``.
* NTP: ``ntp [broadcast|unicast]`` "selects the operating mode of the
  NTP client", and "The default mode is broadcast"; ``ntp enable``,
  which the switch refuses unless ``timesync`` is ``ntp``; and ``ntp
  server <IP-ADDR|IPV6-ADDR> [key-id <id>] [max-poll <n>] [min-poll
  <n>] [burst|iburst]``.
* ``[no] logging <syslog-ip-addr>``: "You can configure up to six
  addresses".  The HP 8200zl IPv6 guide gives the command an
  ``<syslog-ipv4-addr>``; that AOS-S takes an IPv6 syslog server is
  not established.

So the parser (:class:`ManagementPlane`, given each such line at the
top of the config by ``parse_intent``) reads:

* the domain, the last line's;
* each resolver, by its priority: a line for a priority an earlier
  line gave is not read, the switch refusing it;
* the time servers the switch POLLS: the SNTP servers where SNTP is in
  unicast mode and ``timesync`` selects it (``sntp``, ``timep-or-sntp``
  or no ``timesync`` line), by priority, a priority read once as a
  resolver's is (no page says which of two the switch keeps); and the
  NTP servers where ``ntp enable`` is stated and ``timesync`` is
  ``ntp``.  A time server the switch does not poll is a statement it
  holds and does not run, and is left out and said
  (``left_out_rows``, kind ``unpolled``).  An NTP client in broadcast
  mode, its default, is a client of which no page says whether it
  polls its servers: they are not translated either, and the row
  says that it is not established, not that the switch does not
  poll them;
* the syslog servers, six at most.

What is read and not translated is said in a row, which names the
statement by its words and never a value: words after an address
(``oobm``, a transport and port, a description), a server's
``key-id``, and the lines no field of the tree holds (``time
timezone``, ``logging facility``, ``sntp authentication``, ...).  A
version number, a poll interval and NTP's ``burst``, ``iburst``,
``min-poll`` and ``max-poll`` are read and not kept, the tree holding
no polling.

The renderer (:func:`management_lines`) writes the domain, each
resolver at the next priority, the time servers in SNTP form
(``timesync sntp``, ``sntp unicast`` and a ``sntp server priority``
line each, the form every AOS-S release takes) and a ``logging`` line
for each IPv4 syslog server.  What AOS-S cannot be given is a ``;
review:`` line, which names its kind and never its value, and a
warning of the job read from the same function: a fourth resolver or
time server and a seventh syslog server, a value that is no address
AOS-S can be given there (a name, the unspecified address, a
link-local address whose scope names no VLAN), and a syslog server
with an IPv6 address.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from ...limits import ticked

#: A line of the management plane, at the top of the config: the
#: lines :class:`ManagementPlane` reads.  The parser's loop matches a
#: top-level line with it, and a stanza ends at a line it matches.
MANAGEMENT_LINE_RE = re.compile(
    r"^(?:ip[ \t]+dns[ \t]+(?:domain-name|server-address)|timesync|sntp|ntp|logging|time)(?![^ \t])",
    re.IGNORECASE,
)

#: The most resolvers, SNTP servers and syslog servers AOS-S takes.
MOST_RESOLVERS = 3
MOST_SNTP_SERVERS = 3
MOST_SYSLOG_SERVERS = 6

#: The priorities ``ip dns server-address`` and ``sntp server`` take.
_PRIORITIES = {"1": 1, "2": 2, "3": 3}

#: What ``timesync`` may select.
_TIMESYNC = frozenset({"timep", "sntp", "timep-or-sntp", "ntp"})

#: The ``timesync`` settings under which the switch runs SNTP; ``None``
#: is a config with no ``timesync`` line.
_RUNS_SNTP = frozenset({None, "sntp", "timep-or-sntp"})

#: NTP server words that set how the client polls, which the tree does
#: not hold: alone, and followed by a value.
_POLLING_WORDS = frozenset({"burst", "iburst"})
_POLLING_SETTINGS = frozenset({"min-poll", "max-poll"})

#: The kind of :func:`netcanon.migration._tier3_detection.left_out_rows`
#: a time server the switch does not poll is left out as.
UNPOLLED = "unpolled"

_NOT_TRANSLATED = "not translated"


def _an_address(word: str) -> bool:
    """Whether *word* is an IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(word)
    except ValueError:
        return False
    return True


def _a_keyword(word: str) -> bool:
    """Whether *word* is shaped as a statement's keyword (letters and
    hyphens, from a letter), as a row may show it."""
    return word[:1].isalpha() and word.isascii() and word.replace("-", "").isalpha()


def _statement(words: Sequence[str]) -> str:
    """How a row names the line of *words*: its first word, and its
    second where that is a keyword, never a value."""
    shown = words[0].lower()
    if len(words) > 1 and _a_keyword(words[1]):
        shown += f" {words[1].lower()}"
    return shown if len(words) <= 2 else f"{shown} ..."


def _unquoted(value: str) -> str:
    """*value* without the double quotes round it, if it has them."""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


@dataclass
class Read:
    """What the management plane's lines state, once a config is read.

    Attributes:
        domain: The domain suffix, or ``""``.
        dns_servers: The resolvers, by priority.
        ntp_servers: The time servers the switch polls: SNTP servers by
            priority, or NTP servers in the order of their lines
            where the NTP client is in unicast mode.
        syslog_servers: The syslog servers, in the order of their lines.
        left_out: ``(kind, path)`` for each time server the switch does
            not poll.
    """

    domain: str = ""
    dns_servers: list[str] = field(default_factory=list)
    ntp_servers: list[str] = field(default_factory=list)
    syslog_servers: list[str] = field(default_factory=list)
    left_out: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)


class ManagementPlane:
    """The management plane's lines while a config is read: what is in
    force is known after the last (:meth:`finish`).

    Args:
        say: Keeps a row for a line, or part of one, that is read and
            not translated; a row ends in a closing bracket.
    """

    def __init__(self, say: Callable[[str], None]) -> None:
        self._say = say
        self._domain = ""
        self._resolvers: dict[int, str] = {}
        self._sntp: dict[int, str] = {}
        self._ntp: dict[str, None] = {}
        self._syslog: dict[str, None] = {}
        self._timesync: str | None = None
        self._sntp_mode: str | None = None
        self._ntp_mode: str | None = None
        self._ntp_enabled = False

    def read(self, line: str) -> None:
        """Read *line*, a top-level line :data:`MANAGEMENT_LINE_RE`
        matches, with no white space at its ends."""
        words = line.split()
        first = words[0].lower()
        if first == "ip":
            self._dns(line, words)
        elif first == "timesync":
            if len(words) == 2 and words[1].lower() in _TIMESYNC:
                self._timesync = words[1].lower()
            else:
                self._not_translated(words)
        elif first == "sntp":
            self._sntp_line(words)
        elif first == "ntp":
            self._ntp_line(words)
        elif first == "logging":
            self._logging(words)
        else:
            self._not_translated(words)

    def _not_translated(self, words: Sequence[str], why: str = _NOT_TRANSLATED) -> None:
        self._say(f"{_statement(words)} ({why})")

    def _dns(self, line: str, words: Sequence[str]) -> None:
        if words[2].lower() == "domain-name":
            parts = line.split(None, 3)
            if len(parts) == 4:
                self._domain = _unquoted(parts[3])
            else:
                self._not_translated(words, "states no suffix; not translated")
            return
        priority = _PRIORITIES.get(words[4]) if len(words) > 5 and words[3].lower() == "priority" else None
        if priority is None or not _an_address(words[5]):
            self._say("ip dns server-address ... (a form the parser does not read; not translated)")
        elif priority in self._resolvers:
            self._say(
                "ip dns server-address priority ... (a priority an earlier line gave, "
                "which the switch refuses; not translated)",
            )
        else:
            self._resolvers[priority] = words[5]
            if len(words) > 6:
                self._say("ip dns server-address ... (the words after the address are not translated)")

    def _sntp_line(self, words: Sequence[str]) -> None:
        second = words[1].lower() if len(words) > 1 else ""
        if len(words) == 2 and second in ("unicast", "broadcast"):
            self._sntp_mode = second
        elif len(words) == 2 and second.isdigit():
            return  # the poll interval, which the tree does not hold
        elif second == "server":
            priority = _PRIORITIES.get(words[3]) if len(words) > 4 and words[2].lower() == "priority" else None
            if priority is None or not _an_address(words[4]):
                self._say("sntp server ... (a form the parser does not read; not translated)")
            elif priority in self._sntp:
                self._say(
                    "sntp server priority ... (a priority an earlier line gave; "
                    "not translated)",
                )
            else:
                self._sntp[priority] = words[4]
                rest = list(words[5:])
                if rest and rest[0].isdigit():
                    rest = rest[1:]  # the SNTP version
                keyed = len(rest) >= 2 and rest[0].lower() == "key-id"
                self._said("sntp server", keyed=keyed, unread=len(rest) > (2 if keyed else 0))
        else:
            self._not_translated(words)

    def _ntp_line(self, words: Sequence[str]) -> None:
        second = words[1].lower() if len(words) > 1 else ""
        if len(words) == 2 and second in ("unicast", "broadcast"):
            self._ntp_mode = second
        elif len(words) == 2 and second == "enable":
            self._ntp_enabled = True
        elif second == "server":
            if len(words) < 3 or not _an_address(words[2]):
                self._say("ntp server ... (a form the parser does not read; not translated)")
                return
            self._ntp[words[2]] = None
            # HPE prints the key first, and a pasted line may not.
            keyed = unread = False
            at = 3
            while at < len(words) and not unread:
                word = words[at].lower()
                if word in _POLLING_WORDS:
                    at += 1
                elif word in _POLLING_SETTINGS and at + 1 < len(words):
                    at += 2
                elif word == "key-id" and at + 1 < len(words):
                    keyed = True
                    at += 2
                else:
                    unread = True
            self._said("ntp server", keyed=keyed, unread=unread)
        else:
            self._not_translated(words)

    def _said(self, statement: str, *, keyed: bool, unread: bool) -> None:
        """Say what is after a time server's address that is not
        translated: its ``key-id``, and words the parser does not read."""
        if keyed:
            self._say(f"{statement} ... key-id (the key the source authenticates the server with is not translated)")
        if unread:
            self._say(f"{statement} ... (the words after the address are not translated)")

    def _logging(self, words: Sequence[str]) -> None:
        if len(words) < 2 or not _an_address(words[1]):
            self._not_translated(words)
            return
        if words[1] not in self._syslog:
            if len(self._syslog) == MOST_SYSLOG_SERVERS:
                self._say("logging ... (an address after the sixth, which the switch does not take; not translated)")
                return
            self._syslog[words[1]] = None
        if len(words) > 2:
            self._say("logging ... (the words after the address are not translated)")

    def finish(self) -> Read:
        """What the lines state, now that the config has been read."""
        read = Read(domain=self._domain)
        read.dns_servers = [self._resolvers[p] for p in sorted(self._resolvers)]
        read.syslog_servers = list(self._syslog)
        sntp_polled = self._sntp_mode == "unicast" and self._timesync in _RUNS_SNTP
        ntp_runs = self._ntp_enabled and self._timesync == "ntp"
        ntp_polled = ntp_runs and self._ntp_mode == "unicast"
        for priority in ticked(sorted(self._sntp)):
            if sntp_polled:
                read.ntp_servers.append(self._sntp[priority])
            else:
                read.left_out.append((UNPOLLED, ("sntp", "server")))
        for server in ticked(self._ntp):
            if ntp_polled:
                read.ntp_servers.append(server)
            elif ntp_runs:
                self._say(
                    "ntp server (the source's NTP client is in broadcast mode, its default, and "
                    "no HPE page says whether it polls the servers it names; not translated)",
                )
            else:
                read.left_out.append((UNPOLLED, ("ntp", "server")))
        return read


# ---------------------------------------------------------------------------
# The renderer's half
# ---------------------------------------------------------------------------


@dataclass
class Written:
    """An AOS-S output's management plane.

    Attributes:
        lines: Its lines, and a review line for each value not written.
        warnings: One for each review line among *lines*.
    """

    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def review(self, line: str, warning: str) -> None:
        self.lines.append(f"; review: {line}")
        self.warnings.append(f"AOS-S {warning}; a review line in the output says so.")


def _given(value: str) -> bool:
    """Whether *value* is an address AOS-S can be given for a resolver
    or a time server: an IPv4 or IPv6 address that is not the
    unspecified one, and whose scope, if it has one, names a VLAN."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if address.is_unspecified:
        return False
    scope = getattr(address, "scope_id", None)
    return scope is None or (scope[:4].lower() == "vlan" and scope[4:].isdigit() and scope.isascii())


_NOT_GIVEN = (
    "is no address AOS-S can be given there (a name, the unspecified address, "
    "or a link-local address whose scope names no VLAN)"
)


def _resolver_lines(written: Written, servers: Iterable[str]) -> None:
    priority = 0
    for server in ticked(servers):
        if not _given(server):
            written.review(
                f"a DNS resolver of the source is not written: it {_NOT_GIVEN}",
                f"is not given a DNS resolver of the source, which {_NOT_GIVEN}",
            )
        elif priority == MOST_RESOLVERS:
            written.review(
                "a DNS resolver of the source after the third is not written: AOS-S takes three",
                "is not given a DNS resolver after the third, as it takes three",
            )
        else:
            priority += 1
            written.lines.append(f"ip dns server-address priority {priority} {server}")


def _time_lines(written: Written, servers: Iterable[str]) -> None:
    taken: list[str] = []
    for server in ticked(servers):
        if not _given(server):
            written.review(
                f"a time server of the source is not written: it {_NOT_GIVEN}",
                f"is not given a time server of the source, which {_NOT_GIVEN}",
            )
        elif len(taken) == MOST_SNTP_SERVERS:
            written.review(
                "a time server of the source after the third is not written: AOS-S takes "
                "three SNTP servers",
                "is not given a time server after the third, as it takes three SNTP servers",
            )
        else:
            taken.append(server)
    if taken:
        written.lines += ["timesync sntp", "sntp unicast"]
        written.lines += [
            f"sntp server priority {priority} {server}"
            for priority, server in enumerate(taken, start=1)
        ]


def _syslog_lines(written: Written, servers: Iterable[str]) -> None:
    count = 0
    for server in ticked(servers):
        try:
            address = ipaddress.ip_address(server)
        except ValueError:
            address = None
        if address is None or address.is_unspecified:
            written.review(
                "a syslog server of the source is not written: it is no address AOS-S can be "
                "given there (a name, or the unspecified address)",
                "is not given a syslog server of the source that is no address it can be given",
            )
        elif address.version == 6:
            written.review(
                "a syslog server of the source with an IPv6 address is not written: HPE "
                "documents logging for an IPv4 address, and that AOS-S takes an IPv6 one is "
                "not established",
                "is not given a syslog server with an IPv6 address, which is not established "
                "that it takes",
            )
        elif count == MOST_SYSLOG_SERVERS:
            written.review(
                "a syslog server of the source after the sixth is not written: AOS-S takes six",
                "is not given a syslog server after the sixth, as it takes six",
            )
        else:
            count += 1
            written.lines.append(f"logging {server}")


def management_lines(domain: str, dns_servers: Iterable[str], ntp_servers: Iterable[str],
                     syslog_servers: Iterable[str]) -> Written:
    """The management plane of an AOS-S output, and the job's warnings.

    Args:
        domain: The tree's domain; it is written as it stands
            (``one_value_tree`` has left out one that is not one word).
        dns_servers: The tree's resolvers.
        ntp_servers: The tree's time servers.
        syslog_servers: The tree's syslog servers.

    Returns:
        The lines (none where the tree has none of these) and a warning
        for each review line.
    """
    written = Written()
    if domain:
        written.lines.append(f"ip dns domain-name {domain}")
    _resolver_lines(written, dns_servers)
    _time_lines(written, ntp_servers)
    _syslog_lines(written, syslog_servers)
    return written
