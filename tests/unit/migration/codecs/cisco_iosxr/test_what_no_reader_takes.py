"""A Cisco IOS XR line in column 0 that nothing translates is a row.

The IOS XR parser reads a hostname, a domain, the release, DNS, NTP and
syslog servers, interfaces, VRFs, static routes, LAGs and local users,
and the IOS XR Tier-3 patterns give a row to routing protocols, MPLS,
route policies and their sets, access lists, classes, policies, L2VPN,
EVPN and multicast.  Every other line in column 0 was in no output and
no row: an IOS XR config's SNMP, SSH and ``line`` settings, its
telemetry, its configuration groups and the ``apply-group`` lines that
apply them, segment routing, a second ``hostname`` and a second line of
a local user's name were dropped in jobs that said ``completed``.

Now each kind of such line is a row of ``dropped_tier3_sections``
(``cisco_iosxr.parse._rows_for_what_no_reader_takes``): its command
word, and the word after it where that says which command it is
(``ssh server``, ``line console``, ``router hsrp``), never a value
(a ``logging`` line's row is the word alone).  A line that begins with a word IOS XR configurations are not seen to
begin with is counted in one row that shows none of its text.

The check reads the text with a list of what the parser reads, typed
here from the IOS XR grammar the parser takes, and holds the rows to
it: each line the list does not read is said by a row, and each row
says a line the list does not read.  It is handed the parser with the
rows taken out, with a reader that takes every line, with one that
takes none, with one that takes every hostname, domain or ``username``
line, with no lines of the printout or ends of a block taken, and has
to fail; and a ``logging`` line's row, whose next word can be a host's
name, is the word alone, which a check handed the parser that shows
that word sees.
"""

from __future__ import annotations

import ipaddress
import re

import pytest

from netcanon.migration._tier3_detection import (
    LEFT_OUT_ROWS_SHOWN,
    detect_tier3_sections_iosxr,
    is_no_command_row,
)
from netcanon.migration.codecs.cisco_iosxr import parse as xr_parse
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_vlan_members_reach_the_output import CAPTURES

pytestmark = pytest.mark.unit

#: The kinds of line the tree holds one of, by the words each begins
#: with: the parser reads the first line of the kind that has a value
#: after its words, and no other.
READ_ONCE = (
    ("hostname",),
    ("domain", "name"),
)

#: The words that end a block in column 0, whose block a row of its own
#: says (``route-policy`` ... ``end-policy``).
BLOCK_ENDS = frozenset({
    "end-class-map", "end-group", "end-policy", "end-policy-map", "end-set",
})

#: A line the router prints before the configuration: the time the
#: output was made, and ``Building configuration...``.  Typed from
#: printed IOS XR output, in lower case.
PRINTOUT = re.compile(
    r"building configuration\.\.\."
    r"|(?:mon|tue|wed|thu|fri|sat|sun) [a-z]{3} +[0-9]{1,2} "
    r"[0-9]{1,2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?: [a-z]+)?"
)


def _an_address(word: str) -> bool:
    try:
        ipaddress.ip_address(word)
    except ValueError:
        return False
    return True


def _read_by_hand(words: list[str]) -> bool:
    """Whether the parser reads the line of *words* (in lower case),
    whichever line of its kind it is: the forms the parser reads of the
    commands it reads, typed from the IOS XR grammar.

    * ``interface <name> ...``: every header is a record, a LAG, or a
      row of its own (``interface preconfigure``, a sub-interface whose
      tag is not read).
    * ``vrf <name>``, alone on its line.
    * ``router static``, alone on its line.
    * ``ntp``, alone on its line: the block whose servers are read.
    * ``domain name-server <address>``.
    * ``logging ... <address> ...``: a syslog host.
    """
    if words[0] == "interface":
        return len(words) >= 2
    if words[0] == "vrf":
        return len(words) == 2
    if words in (["router", "static"], ["ntp"]):
        return True
    if words[:2] == ["domain", "name-server"]:
        return len(words) >= 3
    if words[0] == "logging":
        return any(_an_address(word) for word in words[1:])
    return False


def _a_user_line(words: list[str]) -> bool:
    """``username <name>`` alone, the header of a user's block, or
    ``username <name> secret|password <type> <value>``: the lines of a
    local user the parser reads, the first of each name
    (:func:`_unread_lines`)."""
    if not words or words[0] != "username":
        return False
    if len(words) == 2:
        return True
    return (
        len(words) >= 5 and words[2] in ("secret", "password")
        and re.fullmatch(r"[0-9]+", words[3]) is not None
    )


#: Words of a session, not of the configuration.
SESSION = frozenset({"configure", "commit", "end", "exit"})

#: The row that counts the lines that begin with no command word the
#: parser knows, in its two forms.
ONE_UNKNOWN = "a line in column 0 that begins with no command this parser knows (line {first})"
MANY_UNKNOWN = (
    "{count} lines in column 0 that begin with no command this parser knows "
    "(the first is line {first})"
)
_COUNTS_UNKNOWN = re.compile(r"begins? with no command this parser knows")

CONFIG = (
    "Thu Apr 23 18:31:17.384 UTC\n"  # 1
    "Building configuration...\n"
    "!! IOS XR Configuration 7.5.2\n"
    "!\n"
    "hostname r1\n"  # 5
    "hostname r2\n"
    "domain name example.net\n"
    "domain name example.org\n"
    "domain name-server 192.0.2.53\n"
    "domain lookup disable\n"  # 10
    "domain vrf mgmt name-server 192.0.2.54\n"
    "logging 192.0.2.10 vrf default severity info\n"
    "logging console debugging\n"
    "logging source-interface Loopback0\n"
    "username alice\n"  # 15
    " group root-lr\n"
    " secret 10 $6$fake$hash\n"
    "!\n"
    "username alice\n"
    " group netadmin\n"  # 20
    "!\n"
    "username bob secret 5 $1$fake$hash\n"
    "username bob password 7 0000FAKE\n"
    "banner motd #\n"
    "frobnicate in a banner\n"  # 25
    "#\n"
    "snmp-server community fakeCommunityA RO\n"
    "snmp-server location lab\n"
    "ssh server v2\n"
    "ssh server vrf mgmt\n"  # 30
    "line console\n"
    " exec-timeout 0 0\n"
    "!\n"
    "line default\n"
    "group G1\n"  # 35
    " interface 'GigabitEthernet.*'\n"
    "  mtu 9000\n"
    " !\n"
    "end-group\n"
    "apply-group G1\n"  # 40
    "telemetry model-driven\n"
    " sensor-group S\n"
    " !\n"
    "!\n"
    "ntp\n"  # 45
    " server 192.0.2.1\n"
    "!\n"
    "ntp source Loopback0\n"
    "vrf blue\n"
    " address-family ipv4 unicast\n"  # 50
    " !\n"
    "!\n"
    "vrf red extra\n"
    "interface GigabitEthernet0/0/0/0\n"
    " ipv4 address 198.51.100.1 255.255.255.0\n"  # 55
    "!\n"
    "interface preconfigure GigabitEthernet0/0/0/9\n"
    " shutdown\n"
    "!\n"
    "router static\n"  # 60
    " address-family ipv4 unicast\n"
    "  0.0.0.0/0 198.51.100.254\n"
    " !\n"
    "!\n"
    "router bgp 65000\n"  # 65
    " bgp router-id 192.0.2.1\n"
    "!\n"
    "router hsrp\n"
    "route-policy PASS\n"
    "  pass\n"  # 70
    "end-policy\n"
    "!\n"
    "segment-routing\n"
    "no ipv4 source-route\n"
    "frobnicate 1\n"  # 75
    "frobnicate 2\n"
    "42 is no command\n"
    "configure terminal\n"
    "commit\n"
    "end\n"  # 80
)

#: What CONFIG's lines in column 0 that nothing reads are, in the order
#: they come: typed by hand.  The banner is text, not lines of the
#: config, its opening line among them: its row is the banner's own.
CONFIG_ROWS = [
    "hostname",
    "domain name",
    "domain lookup",
    "domain vrf",
    "logging",
    "username",
    "snmp-server community",
    "snmp-server location",
    "ssh server",
    "line console",
    "line default",
    "group",
    "apply-group",
    "telemetry model-driven",
    "ntp source",
    "vrf",
    "router hsrp",
    "segment-routing",
    "no ipv4 source-route",
    MANY_UNKNOWN.format(count=2, first=75),
]

#: Every row the committed IOS XR inputs give, together: typed by hand.
#: Their other lines in column 0 are read (``hostname``, ``domain``,
#: ``logging`` with a host, ``ntp``, ``username``, ``vrf``,
#: ``interface``, ``router static``), a detector's (``router bgp``,
#: ``router isis``, ``mpls``, ``route-policy``, ``prefix-set``,
#: ``class-map``, ``policy-map``, ``l2vpn``, ``multicast-routing``,
#: ``call-home``), the end of a block, or the printout's
#: ``Building configuration...``.  ``key`` is a word that names a
#: secret, and its row is cut after it.
COMMITTED_ROWS = {
    "apply-group",
    "cdp",
    "fpd auto-upgrade",
    "frequency synchronization",
    "group",
    "grpc",
    "key ...",
    "line default",
    "lldp",
    "logging",
    "netconf agent",
    "netconf-yang agent",
    "performance-measurement",
    "ptp",
    "segment-routing",
    "snmp-server community",
    "snmp-server ifindex",
    "ssh client",
    "ssh server",
    "telemetry model-driven",
    "telnet vrf",
    "tftp vrf",
}

XR_CAPTURES = [path for codec, _, path in CAPTURES if codec == "cisco_iosxr"]


def _words(text: str) -> list[str]:
    return text.lower().split()


def _unread_lines(text: str) -> list[tuple[int, list[str]]]:
    """(number, words) of each line in column 0 of *text* that begins
    with a letter and that the lists above, :data:`SESSION` and the
    detector do not account for: what nothing translates.  Of a kind in
    :data:`READ_ONCE` the first line with a value is read, and of each
    local user's name the first line in a form that is read."""
    found = []
    once_read: set[tuple[str, ...]] = set()
    users: set[str] = set()
    for number, line in enumerate(xr_parse.without_banner_bodies(text).splitlines(), start=1):
        if not line[:1].isalpha():
            continue
        words = _words(line)
        kind = next((k for k in READ_ONCE if tuple(words[: len(k)]) == k), None)
        if kind is not None:
            if kind not in once_read and len(words) > len(kind):
                once_read.add(kind)
                continue
        elif _a_user_line(words):
            # A name is the operator's, and is told apart as written.
            name = line.split()[1]
            if name not in users:
                users.add(name)
                continue
        elif (
            words[0] in SESSION
            or words[0] in BLOCK_ENDS
            or PRINTOUT.fullmatch(" ".join(words))
            or _read_by_hand(words)
        ):
            continue
        if detect_tier3_sections_iosxr(line):
            continue
        found.append((number, words))
    return found


def _says(row: str, words: list[str]) -> bool:
    """Whether *row* names the line of *words*: its words begin the
    line's (a row cut after a word that names a secret ends ``...``)."""
    shown = _words(row.removesuffix(" ..."))
    return words[: len(shown)] == shown


def _rows_of_this_kind(tree_rows: list[str], text: str) -> list[str]:
    """The rows of *tree_rows* that the walk of the top level could
    have made: not a detector's, not a banner's, not a header's
    (``interface ...``), not a row of a stanza's statements or of a
    count (each has a ``:`` after its words, or begins with ``(``)."""
    elsewhere = {
        *detect_tier3_sections_iosxr(xr_parse.without_banner_bodies(text)),
        *xr_parse.banner_rows(text),
    }
    return [
        row for row in tree_rows
        if row not in elsewhere
        and not row.startswith(("interface ", "("))
        and ":" not in row
    ]


def _check_every_unread_line_is_said(text: str) -> None:
    """Each line nothing translates is said by a row of its kind or
    counted in the row for lines with no known command, and each such
    row says a line nothing translates."""
    tree = get_codec("cisco_iosxr").parse(text)
    rows = _rows_of_this_kind(tree.dropped_tier3_sections, text)
    named = [row for row in rows if not _COUNTS_UNKNOWN.search(row)]
    unread = _unread_lines(text)
    uncounted = [(n, words) for n, words in unread if not any(_says(r, words) for r in named)]
    for row in named:
        assert any(_says(row, words) for _, words in unread), row
    expected = []
    if len(uncounted) == 1:
        expected = [ONE_UNKNOWN.format(first=uncounted[0][0])]
    elif uncounted:
        expected = [MANY_UNKNOWN.format(count=len(uncounted), first=uncounted[0][0])]
    assert [row for row in rows if _COUNTS_UNKNOWN.search(row)] == expected


def test_each_kind_of_line_nothing_reads_is_a_row() -> None:
    """The rows of a config whose lines nothing reads are their kinds, in
    the order they come, and the lines with no command word are counted;
    a line read, a detector's stanza, a banner, the end of a block, a
    line of the printout, a line that begins with no letter and a word
    of a session are no row of this kind."""
    rows = xr_parse._rows_for_what_no_reader_takes(xr_parse.without_banner_bodies(CONFIG))
    assert rows == CONFIG_ROWS
    tree = get_codec("cisco_iosxr").parse(CONFIG)
    assert tree.dropped_tier3_sections == [
        *detect_tier3_sections_iosxr(xr_parse.without_banner_bodies(CONFIG)),
        "preconfigure: interface GigabitEthernet0/0/0/9 (held for an interface the source "
        "does not have; not translated)",
        *xr_parse.banner_rows(CONFIG),
        *CONFIG_ROWS,
    ]
    _check_every_unread_line_is_said(CONFIG)


def test_what_the_parser_reads_is_still_read() -> None:
    """The lines CONFIG's rows leave out are read as they were: the
    first hostname and domain, the name server, the syslog host, the
    NTP server, the first line of a user's name, the VRF on a line of
    its own, the interface and the static route."""
    tree = get_codec("cisco_iosxr").parse(CONFIG)
    assert tree.hostname == "r1"
    assert tree.domain == "example.net"
    assert tree.dns_servers == ["192.0.2.53"]
    assert tree.syslog_servers == ["192.0.2.10"]
    assert tree.ntp_servers == ["192.0.2.1"]
    assert [u.name for u in tree.local_users] == ["alice", "bob"]
    assert [r.name for r in tree.routing_instances] == ["blue"]
    assert [i.name for i in tree.interfaces] == ["GigabitEthernet0/0/0/0"]
    assert [r.destination for r in tree.static_routes] == ["0.0.0.0/0"]


def test_a_row_shows_no_value() -> None:
    """A row is a command's words: a secret, a community, an address or
    a name that follows them is not in it, nor is any word of a line
    that begins with no command the parser knows."""
    text = (
        "hostname r1\n"
        "tacacs-server key 7 fakeTacacsKey\n"
        "radius-server key 7 fakeRadiusKey\n"
        "username admin secret 10 $6$fake$hashA\n"
        "username admin secret 10 $6$fake$hashB\n"
        "snmp-server community fakeCommunityA RO\n"
        "snmp-server community fakeCommunityB RO\n"
        "key chain fakeChain\n"
        "fakeword fakeSecret\n"
        "logging loghost vrf default\n"
    )
    rows = get_codec("cisco_iosxr").parse(text).dropped_tier3_sections
    assert "tacacs-server key" in rows
    assert "radius-server key" in rows
    assert "username" in rows
    assert "snmp-server community" in rows
    assert "key ..." in rows
    assert ONE_UNKNOWN.format(first=9) in rows
    assert "logging" in rows
    assert not [
        row for row in rows
        if "fake" in row.lower() or "$" in row or "admin" in row or "r1" in row
        or "loghost" in row
    ], rows
    _check_every_unread_line_is_said(text)


#: ``logging`` lines that name a host by its name, and one that names
#: no host: IOS XR takes a host straight after the word.
LOGGING_BY_NAME = (
    "logging loghost vrf default severity info\n"
    "logging collector-a\n"
    "logging console debugging\n"
)


def _check_no_host_name_in_a_row(text: str) -> None:
    """No row of ``text`` shows the name of a syslog host."""
    rows = get_codec("cisco_iosxr").parse(text).dropped_tier3_sections
    assert not [
        row for row in rows if "loghost" in row or "collector" in row
    ], rows


def test_a_logging_row_is_the_word_alone() -> None:
    """A ``logging`` line whose host is a name is not read as a syslog
    server (the parser reads an address), and its row is the word
    alone: the word after ``logging`` can be the host's name, which a
    row does not show.  One row for every such line."""
    tree = get_codec("cisco_iosxr").parse(LOGGING_BY_NAME)
    assert tree.syslog_servers == []
    assert tree.dropped_tier3_sections == ["logging"]
    _check_no_host_name_in_a_row(LOGGING_BY_NAME)
    _check_every_unread_line_is_said(LOGGING_BY_NAME)


def test_the_check_fails_with_logging_a_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Were the word after ``logging`` shown, a host's name would be in
    a row, and the check sees it."""
    monkeypatch.setattr(xr_parse, "_FAMILIES", xr_parse._FAMILIES | {"logging"})
    with pytest.raises(AssertionError):
        _check_no_host_name_in_a_row(LOGGING_BY_NAME)


def test_a_line_read_once_is_read_once() -> None:
    """Of a hostname, a domain and a local user's name the parser reads
    one line, the first: a second is a row.  A user's name is the same
    in the block form and on one line."""
    text = (
        "hostname r1\n"
        "hostname r2\n"
        "domain name example.net\n"
        "domain name example.org\n"
        "username ops secret 10 $6$fake$hashA\n"
        "username ops\n"
        " secret 10 $6$fake$hashB\n"
        "!\n"
    )
    tree = get_codec("cisco_iosxr").parse(text)
    assert tree.hostname == "r1"
    assert tree.domain == "example.net"
    assert [u.name for u in tree.local_users] == ["ops"]
    assert tree.dropped_tier3_sections == ["hostname", "domain name", "username"]
    _check_every_unread_line_is_said(text)


def test_a_reader_reads_its_own_line() -> None:
    """A reader of a hostname, a domain, a name server, a syslog host or
    the release takes its value from its own line.  ``\\s`` crossed the
    line break: a ``hostname`` line with no value was read with the next
    line's first word for the hostname, a ``domain name`` line with none
    with the next line's for the domain, a ``logging`` line with none
    with the next line's address for a syslog host -- and the next line
    had no row."""
    text = (
        "!! IOS XR Configuration\n"
        "7.5.2\n"
        "hostname\n"
        "r9\n"
        "domain name\n"
        "example.net\n"
        "domain name-server\n"
        "192.0.2.53\n"
        "logging\n"
        "192.0.2.10\n"
    )
    tree = get_codec("cisco_iosxr").parse(text)
    assert tree.hostname == ""
    assert tree.domain == ""
    assert tree.dns_servers == []
    assert tree.syslog_servers == []
    assert tree.source_version != "7.5.2"
    assert tree.dropped_tier3_sections == [
        "hostname",
        "domain name",
        "domain name-server",
        "logging",
        MANY_UNKNOWN.format(count=2, first=4),
    ]
    _check_every_unread_line_is_said(text)


def test_the_committed_inputs_give_the_rows_typed_here() -> None:
    """Over the committed IOS XR inputs the rows of this kind are the ones
    typed here, and each input's rows say each line nothing reads."""
    assert XR_CAPTURES
    found: set[str] = set()
    for path in XR_CAPTURES:
        text = path.read_text(encoding="utf-8")
        found.update(xr_parse._rows_for_what_no_reader_takes(xr_parse.without_banner_bodies(text)))
        _check_every_unread_line_is_said(text)
    assert found == COMMITTED_ROWS


def test_the_rows_are_bounded() -> None:
    """Past ``LEFT_OUT_ROWS_SHOWN`` kinds one row counts the rest, and
    any number of lines with no known command is one row."""
    def letters(n: int) -> str:
        return "".join(chr(ord("a") + int(d)) for d in str(n))

    kinds = LEFT_OUT_ROWS_SHOWN + 100
    text = "".join(f"ssh kind{letters(n)} 1\n" for n in range(kinds))
    text += "".join(f"frobnicate {n}\n" for n in range(1000))
    rows = xr_parse._rows_for_what_no_reader_takes(text)
    assert len(rows) == LEFT_OUT_ROWS_SHOWN + 2
    assert rows[LEFT_OUT_ROWS_SHOWN] == (
        "(100 more kinds of top-level command not read; not listed)"
    )
    assert rows[-1] == MANY_UNKNOWN.format(count=1000, first=kinds + 1)


def test_a_job_says_the_rows() -> None:
    """A job from IOS XR says them, as every row is said, and what those
    lines hold is in no output."""
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxr"), get_codec("cisco_iosxe_cli"), CONFIG, port_rename_map={},
    )
    assert job.rendered, job.error
    for row in CONFIG_ROWS:
        assert row in job.dropped_tier3_sections, row
    for value in ("example.org", "fakeCommunityA", "192.0.2.54", "r2"):
        assert value not in job.rendered, value


def test_the_row_that_counts_lines_is_known_by_its_form() -> None:
    """A row of a command's words is not taken for the row that counts
    lines of no known command."""
    for row in [*CONFIG_ROWS[:-1], *COMMITTED_ROWS]:
        assert not is_no_command_row(row), row
    assert is_no_command_row(CONFIG_ROWS[-1])


def test_a_text_that_is_no_config_is_still_said_to_be_none() -> None:
    """Text that is no config, given as IOS XR, has the row that counts
    its lines and nothing else, and its job is ``partial``, as it was
    before the row: the row is no sign that the text was a config.
    A line of a command the parser knows is."""
    garbage = "lorem ipsum dolor\nsit amet\n"
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxr"), get_codec("cisco_iosxe_cli"), garbage, port_rename_map={},
    )
    assert job.dropped_tier3_sections == [MANY_UNKNOWN.format(count=2, first=1)]
    assert job.status is MigrationJobStatus.partial
    assert job.error and "recognized" in job.error.lower()
    known = run_plan_with_checked_names(
        get_codec("cisco_iosxr"), get_codec("cisco_iosxe_cli"), "ssh server v2\n",
        port_rename_map={},
    )
    assert known.dropped_tier3_sections == ["ssh server"]
    assert known.status is MigrationJobStatus.completed


def test_the_check_fails_without_the_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the rows taken out, the check fails."""
    monkeypatch.setattr(xr_parse, "_rows_for_what_no_reader_takes", lambda raw: [])
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_for_a_reader_that_takes_every_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reader said to take every line leaves lines nothing reads with
    no row: the check fails."""
    monkeypatch.setattr(xr_parse, "_TOP_LEVEL_READERS", (re.compile(r".*").match,))
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_for_rows_of_lines_that_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no reader listed, the lines read have rows: the check fails."""
    monkeypatch.setattr(xr_parse, "_TOP_LEVEL_READERS", ())
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


@pytest.mark.parametrize(
    ("reader", "text"),
    [
        pytest.param(
            xr_parse._HOSTNAME_RE.match, "hostname r1\nhostname r2\n", id="every-hostname",
        ),
        pytest.param(
            xr_parse._DOMAIN_RE.match,
            "domain name example.net\ndomain name example.org\n",
            id="every-domain",
        ),
        pytest.param(
            re.compile(r"logging\b").match,
            "logging 192.0.2.10\nlogging console debugging\n",
            id="every-logging-line",
        ),
    ],
)
def test_the_check_fails_for_a_reader_of_lines_the_parse_does_not_read(
    monkeypatch: pytest.MonkeyPatch, reader: object, text: str,
) -> None:
    """Were every line of a kind taken -- a second hostname, a second
    domain, a ``logging`` line that names no host -- nothing would say
    the one the parse does not read, and the check sees it."""
    monkeypatch.setattr(
        xr_parse, "_TOP_LEVEL_READERS", (*xr_parse._TOP_LEVEL_READERS, reader),
    )
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(text)


def test_the_check_fails_for_a_reader_of_every_line_of_a_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Were every ``username`` line taken, a second block of a user's
    name, which the parse does not read, would have no row: the check
    sees it."""
    never = re.compile(r"(?!)")
    monkeypatch.setattr(xr_parse, "_USERNAME_INLINE_RE", never)
    monkeypatch.setattr(xr_parse, "_USERNAME_HDR_RE", never)
    monkeypatch.setattr(
        xr_parse, "_TOP_LEVEL_READERS",
        (*xr_parse._TOP_LEVEL_READERS, re.compile(r"username\b").match),
    )
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(
            "username ops\n secret 10 $6$fake$hashA\n!\nusername ops\n!\n",
        )


def test_the_check_fails_with_the_printout_read_as_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the printout's lines not taken, ``Building configuration...``
    is counted as a line of no known command, which the check does not
    allow."""
    monkeypatch.setattr(xr_parse, "_PRINTOUT_RE", re.compile(r"(?!)"))
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_with_the_ends_of_a_block_read_as_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no end of a block taken, ``end-policy`` and ``end-group`` are
    counted as lines of no known command: the check fails."""
    monkeypatch.setattr(xr_parse, "_BLOCK_ENDS", frozenset())
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)
