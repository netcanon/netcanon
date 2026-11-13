"""An Arista EOS line in column 0 that nothing translates is a row.

The EOS parser reads a hostname, DNS, NTP and syslog servers,
interfaces, VLANs, VRFs, static routes, SNMP, local users, RADIUS
servers, the DHCP server and the VARP MAC, and the shared IOS-XE
Tier-3 patterns give a row to ACLs of the IOS form, route maps, QoS
maps, crypto and MLAG.  Every other line in column 0 was in no output
and no row: an EOS config's BGP and OSPF, its plain ``ip access-list
<name>`` ACLs and its prefix lists, its spanning tree, its AAA, its
eAPI and TerminAttr, its ``logging`` settings and a VLAN range were
dropped in jobs that said ``completed`` -- while the codec's docstring
said that BGP/OSPF, eAPI, STP, AAA and TerminAttr were routed to the
banner.

Now each kind of such line is a row of ``dropped_tier3_sections``
(``arista_eos.parse._rows_for_what_no_reader_takes``): its command
word, and the word after it where that says which command it is
(``router bgp``, ``logging buffered``), never a value.  A line that
begins with a word EOS configurations are not seen to begin with is
counted in one row that shows none of its text.

The check reads the text with a list of what the parser reads, typed
here from the EOS grammar the parser takes, and holds the rows to it:
each line the list does not read is said by a row, and each row says a
line the list does not read.  It is handed the parser with the rows
taken out, with a reader that takes every line and with one that takes
none, and has to fail.
"""

from __future__ import annotations

import ipaddress
import re

import pytest

from netcanon.migration._tier3_detection import (
    LEFT_OUT_ROWS_SHOWN,
    detect_tier3_sections_iosxe_cli,
    is_no_command_row,
)
from netcanon.migration.codecs.arista_eos import parse as eos_parse
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_vlan_members_reach_the_output import CAPTURES

pytestmark = pytest.mark.unit

#: The lines in column 0 the parser reads whatever follows, or says in
#: a row of their own (an ``interface`` header names a record, or is a
#: row of ``test_a_header_names_one_interface.py``), by how each
#: begins: typed from the EOS grammar, not taken from the parser.  The
#: lines it reads only in one form are asked by :func:`_read_by_hand`.
READ_BY_HAND = (
    "hostname ",
    "dns domain ",
    "ntp server ",
    "ip route ",
    "ipv6 route ",
    "ip virtual-router mac-address ",
    "snmp-server location ",
    "snmp-server contact ",
    "username ",
    "radius-server host ",
    "vrf instance ",
    "vrf definition ",
    "ip dhcp pool ",
    "interface ",
)


def _an_address(word: str) -> bool:
    try:
        ipaddress.ip_address(word)
    except ValueError:
        return False
    return True


def _read_by_hand(words: list[str]) -> bool:
    """Whether the parser reads the line of *words* (in lower case):
    one that begins as :data:`READ_BY_HAND` has it, or one of the forms
    the parser reads of a command whose other forms it does not.

    * ``vlan <id>``: one VLAN; a range or a list is not read.
    * ``ip name-server [vrf <name>] <server>``: one server a line.
    * ``logging ...``: a line that names an address, a syslog server.
    * ``snmp-server community <name> ro|rw``: the access right first;
      and only the first such line (:func:`_unread_lines`), as the
      tree holds one community.
    * ``snmp-server host <IPv4 address>``.
    * ``snmp-server user <name> <group> v3 ...``.
    * ``dhcp server [vrf <name>]``.
    """
    if (" ".join(words) + " ").startswith(READ_BY_HAND):
        return True
    if words[0] == "vlan":
        return len(words) == 2 and words[1].isdigit()
    if words[:2] == ["ip", "name-server"]:
        rest = words[4:] if words[2:3] == ["vrf"] else words[2:]
        return len(rest) == 1
    if words[0] == "logging":
        return any(_an_address(word) for word in words[1:])
    if words[:2] == ["snmp-server", "community"]:
        return len(words) > 3 and words[3] in ("ro", "rw")
    if words[:2] == ["snmp-server", "host"]:
        return len(words) > 2 and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", words[2]) is not None
    if words[:2] == ["snmp-server", "user"]:
        return len(words) > 4 and words[4] == "v3"
    if words[:2] == ["dhcp", "server"]:
        return len(words) == 2 or (len(words) == 4 and words[2] == "vrf")
    return False


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
    "! Command: show running-config\n"  # 1
    "hostname leaf1\n"
    "!\n"
    "banner motd\n"
    "frobnicate in a banner\n"  # 5
    "EOF\n"
    "!\n"
    "ip name-server vrf MGMT 192.0.2.53\n"
    "ip name-server vrf MGMT 192.0.2.54 192.0.2.55\n"
    "dns domain example.net\n"  # 10
    "ntp server 192.0.2.123 prefer\n"
    "ntp local-interface Management1\n"
    "logging host 192.0.2.20\n"
    "logging host loghost.example.net\n"
    "logging buffered 10000\n"  # 15
    "spanning-tree mode mstp\n"
    "!\n"
    "vlan 10\n"
    "   name users\n"
    "!\n"  # 20
    "vlan 20-30\n"
    "!\n"
    "vrf instance blue\n"
    "!\n"
    "interface Ethernet1\n"  # 25
    "   no switchport\n"
    "   ip address 198.51.100.1/24\n"
    "!\n"
    "interface Ethernet2-4\n"
    "   shutdown\n"  # 30
    "!\n"
    "ip access-list EDGE\n"
    "   10 permit ip any any\n"
    "!\n"
    "ip access-list standard MGMT\n"  # 35
    "   10 permit 192.0.2.0/24\n"
    "!\n"
    "route-map RM permit 10\n"
    "!\n"
    "ip routing\n"  # 40
    "ip route 0.0.0.0/0 198.51.100.254\n"
    "!\n"
    "router bgp 65001\n"
    "   neighbor 198.51.100.2 remote-as 65002\n"
    "!\n"  # 45
    "mlag configuration\n"
    "   domain-id d1\n"
    "!\n"
    "management api http-commands\n"
    "   no shutdown\n"  # 50
    "!\n"
    "daemon TerminAttr\n"
    "   exec /usr/bin/TerminAttr\n"
    "!\n"
    "no aaa root\n"  # 55
    "frobnicate 1\n"
    "frobnicate 2\n"
    "42 is no command\n"
    "end\n"
)

#: What CONFIG's lines in column 0 that nothing reads are, in the order
#: they come: typed by hand.  The banner's body is text, not lines of
#: the config; its ``banner motd`` line is a row, as no reader takes it.
CONFIG_ROWS = [
    "banner motd",
    "ip name-server",
    "ntp local-interface",
    "logging host",
    "logging buffered",
    "spanning-tree mode",
    "vlan",
    "ip access-list",
    "ip routing",
    "router bgp",
    "management api",
    "daemon",
    "no aaa root",
    MANY_UNKNOWN.format(count=2, first=56),
]

#: Every row the committed EOS inputs give, together: typed by hand.
COMMITTED_ROWS = {
    "aaa authentication",
    "aaa authorization",
    "bfd multihop",
    "daemon",
    "errdisable recovery",
    "ip address",
    "ip igmp",
    "ip multicast-routing",
    "ip prefix-list",
    "ip routing",
    "ipv6 unicast-routing",
    "load-interval default",
    "mac address-table",
    "management api",
    "no aaa root",
    "no ip routing",
    "no spanning-tree vlan-id",
    "ntp local-interface",
    "queue-monitor length",
    "router bfd",
    "router bgp",
    "service routing",
    "service running-config",
    "service unsupported-transceiver",
    "snmp-server community",
    "spanning-tree mode",
    "spanning-tree mst",
    "switchport default",
    "system",
    "transceiver qsfp",
    "vlan internal",
}

EOS_CAPTURES = [path for codec, _, path in CAPTURES if codec == "arista_eos"]


def _words(text: str) -> list[str]:
    return text.lower().split()


def _unread_lines(text: str) -> list[tuple[int, list[str]]]:
    """(number, words) of each line in column 0 of *text* that begins
    with a letter and that :func:`_read_by_hand`, :data:`SESSION` and
    the detector do not account for: what nothing translates."""
    found = []
    communities = 0
    for number, line in enumerate(eos_parse.without_bodies(text).splitlines(), start=1):
        if not line[:1].isalpha():
            continue
        words = _words(line)
        if words[:2] == ["snmp-server", "community"] and _read_by_hand(words):
            communities += 1
            if communities == 1:
                continue
        elif words[0] in SESSION or _read_by_hand(words):
            continue
        if detect_tier3_sections_iosxe_cli(line):
            continue
        found.append((number, words))
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
    tree = get_codec("arista_eos").parse(text)
    elsewhere = set(detect_tier3_sections_iosxe_cli(eos_parse.without_bodies(text)))
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
    a line read, a detector's stanza, a banner's body, a line that
    begins with no letter and a word of a session are no row of this
    kind."""
    rows = eos_parse._rows_for_what_no_reader_takes(eos_parse.without_bodies(CONFIG))
    assert rows == CONFIG_ROWS
    tree = get_codec("arista_eos").parse(CONFIG)
    assert tree.dropped_tier3_sections == [
        "ip access-list standard MGMT", "route-map RM", "mlag configuration",
        "interface Ethernet2-4", *CONFIG_ROWS,
    ]
    _check_every_unread_line_is_said(CONFIG)


def test_a_row_shows_no_value() -> None:
    """A row is a command's words: a secret, a community, an address or
    a name that follows them is not in it, nor is any word of a line
    that begins with no command the parser knows."""
    text = (
        "hostname leaf1\n!\n"
        "interface Ethernet1\n   no switchport\n!\n"
        "radius-server key 7 fakeRadiusKey\n"
        "tacacs-server key 7 fakeTacacsKey\n"
        "ntp authentication-key 1 md5 fakeNtpKey\n"
        "enable password sha512 $6$fake$hash\n"
        "aaa root secret sha512 $6$fake$hash\n"
        "snmp-server community fakeCommunity view all ro\n"
        "fakeword fakeSecret\n"
    )
    rows = get_codec("arista_eos").parse(text).dropped_tier3_sections
    assert "radius-server key" in rows
    assert "ntp authentication-key" in rows
    assert "snmp-server community" in rows
    assert ONE_UNKNOWN.format(first=12) in rows
    assert not [row for row in rows if "fake" in row.lower() or "$6$" in row], rows
    _check_every_unread_line_is_said(text)


#: Two communities: the tree holds one, and the parser reads the first.
TWO_COMMUNITIES = (
    "hostname leaf1\n"
    "snmp-server community fakeCommunityA ro\n"
    "snmp-server community fakeCommunityB rw\n"
)


def test_a_second_community_is_a_row() -> None:
    """The tree holds one SNMP community, the first line of one the
    parser reads: a second line is in no output, and a row says so --
    one row, with no community in it."""
    one = get_codec("arista_eos").parse(TWO_COMMUNITIES.rsplit("snmp", 1)[0])
    assert one.snmp is not None and one.snmp.community == "fakeCommunityA"
    assert "snmp-server community" not in one.dropped_tier3_sections
    two = get_codec("arista_eos").parse(TWO_COMMUNITIES)
    assert two.snmp is not None and two.snmp.community == "fakeCommunityA"
    assert two.dropped_tier3_sections.count("snmp-server community") == 1
    assert not [row for row in two.dropped_tier3_sections if "fake" in row.lower()]
    _check_every_unread_line_is_said(TWO_COMMUNITIES)


def test_the_check_fails_for_a_reader_of_every_community(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Were every community line taken, the second would be said by
    nothing, and the check sees it."""
    monkeypatch.setattr(
        eos_parse, "_TOP_LEVEL_READERS",
        (*eos_parse._TOP_LEVEL_READERS, eos_parse._SNMP_COMMUNITY_RE.match),
    )
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(TWO_COMMUNITIES)


def test_the_committed_inputs_give_the_rows_typed_here() -> None:
    """Over the committed EOS inputs the rows of this kind are the ones
    typed here, and each input's rows say each line nothing reads."""
    assert EOS_CAPTURES
    found: set[str] = set()
    for path in EOS_CAPTURES:
        text = path.read_text(encoding="utf-8")
        found.update(eos_parse._rows_for_what_no_reader_takes(eos_parse.without_bodies(text)))
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
    rows = eos_parse._rows_for_what_no_reader_takes(text)
    assert len(rows) == LEFT_OUT_ROWS_SHOWN + 2
    assert rows[LEFT_OUT_ROWS_SHOWN] == (
        "(100 more kinds of top-level command not read; not listed)"
    )
    assert rows[-1] == MANY_UNKNOWN.format(count=1000, first=kinds + 1)


def test_a_job_says_the_rows() -> None:
    """A job from EOS says them, as every row is said, and what those
    lines hold is in no output."""
    job = run_plan_with_checked_names(
        get_codec("arista_eos"), get_codec("cisco_iosxe_cli"), CONFIG, port_rename_map={},
    )
    assert job.rendered, job.error
    for row in CONFIG_ROWS:
        assert row in job.dropped_tier3_sections, row
    for value in ("192.0.2.54", "192.0.2.55", "loghost.example.net", "65002"):
        assert value not in job.rendered, value


def test_the_row_that_counts_lines_is_known_by_its_form() -> None:
    """A row of a command's words is not taken for the row that counts
    lines of no known command."""
    for row in [*CONFIG_ROWS[:-1], *COMMITTED_ROWS]:
        assert not is_no_command_row(row), row
    assert is_no_command_row(CONFIG_ROWS[-1])


def test_a_text_that_is_no_config_is_still_said_to_be_none() -> None:
    """Text that is no config, given as EOS, has the row that counts
    its lines and nothing else, and its job is ``partial``, as it was
    before the row: the row is no sign that the text was a config.
    A line of a command the parser knows is."""
    garbage = "lorem ipsum dolor\nsit amet\n"
    job = run_plan_with_checked_names(
        get_codec("arista_eos"), get_codec("cisco_iosxe_cli"), garbage, port_rename_map={},
    )
    assert job.dropped_tier3_sections == [MANY_UNKNOWN.format(count=2, first=1)]
    assert job.status is MigrationJobStatus.partial
    assert job.error and "recognized" in job.error.lower()
    known = run_plan_with_checked_names(
        get_codec("arista_eos"), get_codec("cisco_iosxe_cli"), "spanning-tree mode mstp\n",
        port_rename_map={},
    )
    assert known.dropped_tier3_sections == ["spanning-tree mode"]
    assert known.status is MigrationJobStatus.completed


def test_a_syslog_server_is_still_read() -> None:
    """The ``logging`` lines that name an address are read as they were,
    each server once, and give no row; the others are rows."""
    text = (
        "logging host 192.0.2.20\n"
        "logging vrf MGMT host 192.0.2.21\n"
        "logging host 192.0.2.20 514\n"
        "logging trap informational\n"
    )
    tree = get_codec("arista_eos").parse(text)
    assert tree.syslog_servers == ["192.0.2.20", "192.0.2.21"]
    assert tree.dropped_tier3_sections == ["logging trap"]


def test_the_check_fails_without_the_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the rows taken out, the check fails."""
    monkeypatch.setattr(eos_parse, "_rows_for_what_no_reader_takes", lambda raw: [])
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_for_a_reader_that_takes_every_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reader said to take every line leaves lines nothing reads with
    no row: the check fails."""
    monkeypatch.setattr(eos_parse, "_TOP_LEVEL_READERS", (re.compile(r".*").match,))
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_for_rows_of_lines_that_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no reader listed, the lines read have rows: the check fails."""
    monkeypatch.setattr(eos_parse, "_TOP_LEVEL_READERS", ())
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)
