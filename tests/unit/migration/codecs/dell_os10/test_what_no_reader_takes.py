"""An OS10 line in column 0 that nothing translates is a row.

The OS10 parser reads a hostname, VRFs, interfaces, static routes, LAGs,
local users and SNMP, and the Tier-3 detector gives a row to the kinds
of stanza it has a pattern for (routing protocols, ACLs, QoS, VLT and
the like).  Every other line in column 0 was in no output and no row:
an OS10 config's NTP and syslog servers, its DNS, its time zone, its
spanning tree, its DCBX and LLDP settings and its VXLAN overlay (``nve``,
``virtual-network``) were dropped in jobs that said ``completed``, and
the vendor page said "loss is reported, never silent".

Now each kind of such line is a row of ``dropped_tier3_sections``
(``dell_os10.parse._rows_for_what_no_reader_takes``): its command word,
and the word after it where that says which command it is (``ntp
server``, ``logging console``), never a value.  A line that begins with
a word OS10 configurations are not seen to begin with is counted in one
row that shows none of its text.

The check reads the text with a list of what the parser reads, typed
here, and holds the rows to it: each line the list does not read is
said by a row, and each row says a line the list does not read.  It is
handed the parser with the rows taken out, with a reader that takes
every line and with one that takes none, and has to fail.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration._tier3_detection import (
    LEFT_OUT_ROWS_SHOWN,
    detect_tier3_sections_dellos10,
    is_no_command_row,
)
from netcanon.migration.codecs.dell_os10 import parse as os10_parse
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_vlan_members_reach_the_output import CAPTURES

pytestmark = pytest.mark.unit

#: The lines in column 0 the parser reads, or says in a row of their
#: own (an ``interface`` header names a record, or is a row of
#: ``test_a_header_names_one_interface.py``), by how each begins:
#: typed from the OS10 grammar, not taken from the parser.
READ_BY_HAND = (
    "hostname ",
    "ip vrf ",
    "ip route ",
    "ipv6 route ",
    "management route ",
    "username ",
    "snmp-server community ",
    "snmp-server location ",
    "snmp-server contact ",
    "snmp-server host ",
    "snmp-server user ",
    "interface ",
)

#: Words of a session, not of the configuration.
SESSION = frozenset({"configure", "end", "exit", "write"})

#: The row that counts the lines that begin with no command word the
#: parser knows, in its two forms.
ONE_UNKNOWN = "a line in column 0 that begins with no command this parser knows (line {first})"
MANY_UNKNOWN = (
    "{count} lines in column 0 that begin with no command this parser knows "
    "(the first is line {first})"
)
_COUNTS_UNKNOWN = re.compile(r"begins? with no command this parser knows")

CONFIG = (
    "hostname tor1\n"  # 1
    "!\n"
    "ip vrf default\n"
    "!\n"
    "ip vrf blue\n"  # 5
    "!\n"
    "interface ethernet1/1/1\n"
    " no switchport\n"
    " ip address 10.1.0.1/24\n"
    "!\n"  # 10
    "interface range ethernet1/1/2-1/1/4\n"
    " shutdown\n"
    "!\n"
    "ip route 0.0.0.0/0 10.1.0.254\n"
    "ntp server 192.0.2.10\n"  # 15
    "ntp server 192.0.2.11\n"
    "ip name-server 192.0.2.53\n"
    "clock timezone UTC 0 0\n"
    "logging server 192.0.2.20\n"
    "spanning-tree mode rstp\n"  # 20
    "router bgp 65001\n"
    " router-id 10.0.0.1\n"
    "!\n"
    "nve\n"
    " source-interface loopback0\n"  # 25
    "!\n"
    "virtual-network 10\n"
    " vxlan-vni 10010\n"
    "!\n"
    "no ip ssh server enable\n"  # 30
    "frobnicate 1\n"
    "frobnicate 2\n"
    "42 is no command\n"
    "# a comment\n"
    "end\n"  # 35
)

#: What CONFIG's lines in column 0 that nothing reads are, in the order
#: they come: typed by hand.
CONFIG_ROWS = [
    "ntp server",
    "ip name-server",
    "clock timezone",
    "logging server",
    "spanning-tree mode",
    "nve",
    "virtual-network",
    "no ip ssh",
    MANY_UNKNOWN.format(count=2, first=31),
]

#: Every row the committed OS10 inputs give, together: typed by hand.
#: One of them begins with a title line that is no command.
COMMITTED_ROWS = {
    ONE_UNKNOWN.format(first=1),
    "clock timezone",
    "dcbx enable",
    "exec-timeout",
    "ip name-server",
    "ip ssh",
    "line vty",
    "lldp enable",
    "logging audit",
    "logging console",
    "logging server",
    "logging source-interface",
    "no ip access-list",
    "ntp server",
    "rest api",
    "snmp-server enable",
    "snmp-server group",
    "snmp-server view",
    "spanning-tree mode",
    "spanning-tree mst",
    "spanning-tree vlan",
}

OS10_CAPTURES = [path for codec, _, path in CAPTURES if codec == "dell_os10"]


def _words(text: str) -> list[str]:
    return text.lower().split()


def _unread_lines(text: str) -> list[tuple[int, list[str]]]:
    """(number, words) of each line in column 0 of *text* that begins
    with a letter and that :data:`READ_BY_HAND`, :data:`SESSION` and the
    detector do not account for: what nothing translates."""
    found = []
    for number, line in enumerate(os10_parse.without_banner_bodies(text).splitlines(), start=1):
        if not line[:1].isalpha():
            continue
        flat = " ".join(_words(line)) + " "
        if flat.split()[0] in SESSION or flat.startswith(READ_BY_HAND):
            continue
        if detect_tier3_sections_dellos10(line):
            continue
        found.append((number, _words(line)))
    return found


def _says(row: str, words: list[str]) -> bool:
    """Whether *row* names the line of *words*: its words begin the
    line's (a row cut after a word that names a secret ends ``...``)."""
    shown = _words(row.removesuffix(" ..."))
    return words[: len(shown)] == shown


def _check_every_unread_line_is_said(text: str) -> None:
    """Each line nothing translates is said by a row of its kind or
    counted in the row for lines with no known command, and each such
    row says a line nothing translates."""
    tree = get_codec("dell_os10").parse(text)
    elsewhere = set(detect_tier3_sections_dellos10(os10_parse.without_banner_bodies(text)))
    rows = [
        row for row in tree.dropped_tier3_sections
        if row not in elsewhere and not row.startswith(("interface ", "("))
    ]
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
    a line read, a detector's stanza, a line that begins with no letter
    and a word of a session are no row of this kind."""
    rows = os10_parse._rows_for_what_no_reader_takes(CONFIG)
    assert rows == CONFIG_ROWS
    tree = get_codec("dell_os10").parse(CONFIG)
    assert tree.dropped_tier3_sections == [
        "router bgp 65001", "interface range ethernet1/1/2-1/1/4", *CONFIG_ROWS,
    ]
    _check_every_unread_line_is_said(CONFIG)


def test_a_row_shows_no_value() -> None:
    """A row is a command's words: a secret, an address or a name that
    follows them is not in it, nor is any word of a line that begins
    with no command the parser knows."""
    text = (
        "hostname tor1\n!\n"
        "interface ethernet1/1/1\n no switchport\n!\n"
        "radius-server host 192.0.2.30 key 9 fakeRadiusKey\n"
        "tacacs-server key 0 fakeTacacsKey\n"
        "ntp authentication-key 1 md5 fakeNtpKey\n"
        "enable password 0 fakeEnablePass\n"
        "password-attributes min-length 6\n"
        "fakeword fakeSecret\n"
    )
    rows = get_codec("dell_os10").parse(text).dropped_tier3_sections
    assert "radius-server host" in rows
    assert "ntp authentication-key" in rows
    assert ONE_UNKNOWN.format(first=11) in rows
    assert not [row for row in rows if "fake" in row.lower() or "192.0.2" in row], rows
    _check_every_unread_line_is_said(text)


def test_the_committed_inputs_give_the_rows_typed_here() -> None:
    """Over the committed OS10 inputs the rows of this kind are the ones
    typed here, and each input's rows say each line nothing reads."""
    assert OS10_CAPTURES
    found: set[str] = set()
    for path in OS10_CAPTURES:
        text = path.read_text(encoding="utf-8")
        found.update(os10_parse._rows_for_what_no_reader_takes(os10_parse.without_banner_bodies(text)))
        _check_every_unread_line_is_said(text)
    assert found == COMMITTED_ROWS


def test_the_rows_are_bounded() -> None:
    """Past ``LEFT_OUT_ROWS_SHOWN`` kinds one row counts the rest, and
    any number of lines with no known command is one row."""
    def letters(n: int) -> str:
        return "".join(chr(ord("a") + int(d)) for d in str(n))

    kinds = LEFT_OUT_ROWS_SHOWN + 100
    text = "".join(f"ip kind{letters(n)} 1\n" for n in range(kinds))
    text += "".join(f"frobnicate {n}\n" for n in range(1000))
    rows = os10_parse._rows_for_what_no_reader_takes(text)
    assert len(rows) == LEFT_OUT_ROWS_SHOWN + 2
    assert rows[LEFT_OUT_ROWS_SHOWN] == (
        "(100 more kinds of top-level command not read; not listed)"
    )
    assert rows[-1] == MANY_UNKNOWN.format(count=1000, first=kinds + 1)


def test_a_job_says_the_rows() -> None:
    """A job from OS10 says them, as every row is said."""
    job = run_plan_with_checked_names(
        get_codec("dell_os10"), get_codec("cisco_iosxe_cli"), CONFIG, port_rename_map={},
    )
    assert job.rendered, job.error
    for row in CONFIG_ROWS:
        assert row in job.dropped_tier3_sections, row
    assert "ntp server" not in job.rendered


def test_the_row_that_counts_lines_is_known_by_its_form() -> None:
    """The row that counts lines of no known command is told from
    every other row by its form, in both of its forms, and a row of
    a command's words is not taken for it."""
    assert is_no_command_row(ONE_UNKNOWN.format(first=7))
    assert is_no_command_row(MANY_UNKNOWN.format(count=12, first=3))
    for row in [*CONFIG_ROWS[:-1], *COMMITTED_ROWS - {ONE_UNKNOWN.format(first=1)}]:
        assert not is_no_command_row(row), row
    assert not is_no_command_row(ONE_UNKNOWN.format(first=7) + " and more")


def test_a_text_that_is_no_config_is_still_said_to_be_none() -> None:
    """Text that is no config, given as OS10, has the row that counts
    its lines and nothing else, and its job is ``partial``, as it was
    before the row: the row is no sign that the text was a config.
    A line of a command the parser knows is."""
    garbage = "lorem ipsum dolor\nsit amet\n"
    job = run_plan_with_checked_names(
        get_codec("dell_os10"), get_codec("cisco_iosxe_cli"), garbage, port_rename_map={},
    )
    assert job.dropped_tier3_sections == [MANY_UNKNOWN.format(count=2, first=1)]
    assert job.status is MigrationJobStatus.partial
    assert job.error and "recognized" in job.error.lower()
    known = run_plan_with_checked_names(
        get_codec("dell_os10"), get_codec("cisco_iosxe_cli"), "ntp server 192.0.2.10\n",
        port_rename_map={},
    )
    assert known.dropped_tier3_sections == ["ntp server"]
    assert known.status is MigrationJobStatus.completed


def test_the_check_fails_without_the_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the rows taken out, the check fails."""
    monkeypatch.setattr(os10_parse, "_rows_for_what_no_reader_takes", lambda raw: [])
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_for_a_reader_that_takes_every_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reader said to take every line leaves lines nothing reads with
    no row: the check fails."""
    monkeypatch.setattr(os10_parse, "_TOP_LEVEL_READERS", (re.compile(r".*"),))
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_for_rows_of_lines_that_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no reader listed, the lines read have rows: the check fails."""
    monkeypatch.setattr(os10_parse, "_TOP_LEVEL_READERS", ())
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)
