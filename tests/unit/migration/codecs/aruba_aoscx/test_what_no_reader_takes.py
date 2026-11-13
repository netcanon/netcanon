"""An Aruba AOS-CX line in column 0 that nothing translates is a row.

The AOS-CX parser reads a hostname, the release, interfaces, VLANs,
VRFs, static routes, LAGs, local users, SNMP and VXLAN, and the AOS-CX
Tier-3 patterns give a row to routing protocols, access lists, route
maps, classes, policies and VSF.  Every other line in column 0 was in
no output and no row: an AOS-CX config's VSX and EVPN stanzas, its
NTP, DNS and SSH settings, its spanning tree, its prefix lists, its
TACACS servers, the access lists it applies, a second SNMP community
and a second line of a local user were dropped in jobs that said
``completed``.

Now each kind of such line is a row of ``dropped_tier3_sections``
(``aruba_aoscx.parse._rows_for_what_no_reader_takes``): its command
word, and the word after it where that says which command it is
(``ntp server``, ``spanning-tree mode``, ``router vrrp``), never a
value.  A line that begins with a word AOS-CX configurations are not
seen to begin with is counted in one row that shows none of its text.

The check reads the text with a list of what the parser reads, typed
here from the AOS-CX grammar the parser takes, and holds the rows to
it: each line the list does not read is said by a row, and each row
says a line the list does not read.  It is handed the parser with the
rows taken out, with a reader that takes every line, with one that
takes none, with one that takes every community line, every hostname
line and every ``vlan`` line, and has to fail.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration._tier3_detection import (
    LEFT_OUT_ROWS_SHOWN,
    detect_tier3_sections_aoscx,
    is_no_command_row,
)
from netcanon.migration.codecs.aruba_aoscx import parse as cx_parse
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
    ("snmp-server", "community"),
    ("snmp-server", "system-location"),
    ("snmp-server", "system-contact"),
)

#: What a secret of a local user or an SNMPv3 user is said to be.
SECRET_KINDS = ("ciphertext", "plaintext")


def _read_by_hand(words: list[str]) -> bool:
    """Whether the parser reads the line of *words* (in lower case),
    whichever line of its kind it is: the forms the parser reads of the
    commands it reads, typed from the AOS-CX grammar.

    * ``interface <name> ...``: every header is a record, a LAG, the
      VTEP, or a row of its own.
    * ``vrf <name>``, alone on its line.
    * ``vlan <id>``, one id the switch has (1-4094), alone on its line.
    * ``ip route ...`` and ``ipv6 route ...``: a route, or counted in a
      row of the routes that are not held.
    * ``snmpv3 user <name> auth <algorithm> auth-pass <kind> <value>
      ...``.
    """
    if words[0] == "interface":
        return len(words) >= 2
    if words[0] == "vrf":
        return len(words) == 2
    if words[0] == "vlan":
        return (
            len(words) == 2
            and re.fullmatch(r"[0-9]{1,10}", words[1]) is not None
            and 1 <= int(words[1]) <= 4094
        )
    if words[:2] in (["ip", "route"], ["ipv6", "route"]):
        return len(words) >= 3
    if words[:2] == ["snmpv3", "user"]:
        return (
            len(words) >= 8 and words[3] == "auth" and words[5] == "auth-pass"
            and words[6] in SECRET_KINDS
        )
    return False


def _a_user_line(words: list[str]) -> bool:
    """``user <name> group <group> password <kind> <value>``: the line
    of a local user the parser reads, the first of each name
    (:func:`_unread_lines`)."""
    return (
        len(words) >= 7 and words[0] == "user" and words[2] == "group"
        and words[4] == "password" and words[5] in SECRET_KINDS
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
    "!Version ArubaOS-CX FL.10.13.1000\n"  # 1
    "!export-password: default\n"
    "hostname leaf1\n"
    "hostname leaf2\n"
    "user admin group administrators password ciphertext AQBfakeCipherA==\n"  # 5
    "user admin group operators password ciphertext AQBfakeCipherB==\n"
    "user ops group operators\n"
    "banner motd !\n"
    "frobnicate in a banner\n"
    "!\n"  # 10
    "clock timezone us/pacific\n"
    "ntp server 192.0.2.123 iburst\n"
    "ntp enable\n"
    "ssh server vrf mgmt\n"
    "https-server rest access-mode read-write\n"  # 15
    "https-server vrf mgmt\n"
    "spanning-tree\n"
    "spanning-tree mode mstp\n"
    "vrf red\n"
    "vrf blue extra\n"  # 20
    "vlan 10\n"
    "    name ten\n"
    "vlan 5000\n"
    "vlan 10,20\n"
    "snmp-server community fakeCommunityA\n"  # 25
    "snmp-server community fakeCommunityB\n"
    "snmp-server system-location lab\n"
    "snmp-server system-contact noc\n"
    "snmpv3 user v3u auth sha auth-pass plaintext fakeAuthPass"
    " priv aes priv-pass plaintext fakePrivPass\n"
    "snmpv3 user v3x\n"  # 30
    "snmpv3 context ctx\n"
    "interface 1/1/1\n"
    "    no shutdown\n"
    "interface lag 1\n"
    "    no shutdown\n"  # 35
    "interface vlan 10\n"
    "    ip address 198.51.100.1/24\n"
    "ip route 0.0.0.0/0 198.51.100.254\n"
    "ip route 10.9.0.0/16 nullroute\n"
    "ip dns server-address 192.0.2.53\n"  # 40
    "ip prefix-list PL seq 10 permit 10.0.0.0/8\n"
    "router bgp 65000\n"
    "    neighbor 198.51.100.2 remote-as 65002\n"
    "router vrrp enable\n"
    "access-list ip ACL1\n"  # 45
    "    10 permit any any any\n"
    "apply access-list ip ACL1 in\n"
    "vsx\n"
    "    role primary\n"
    "evpn\n"  # 50
    "    vlan 10\n"
    "aruba-central\n"
    "    disable\n"
    "no ip icmp redirect\n"
    "tacacs-server host 192.0.2.40 key ciphertext AQBfakeTacacs==\n"  # 55
    "frobnicate 1\n"
    "frobnicate 2\n"
    "42 is no command\n"
    "configure terminal\n"
    "end\n"  # 60
)

#: What CONFIG's lines in column 0 that nothing reads are, in the order
#: they come: typed by hand.  The banner is text, not lines of the
#: config, its opening line among them: no row is made of it here.
CONFIG_ROWS = [
    "hostname",
    "user",
    "clock timezone",
    "ntp server",
    "ntp enable",
    "ssh server",
    "https-server rest",
    "https-server vrf",
    "spanning-tree",
    "spanning-tree mode",
    "vrf",
    "vlan",
    "snmp-server community",
    "snmpv3 user",
    "snmpv3 context",
    "ip dns",
    "ip prefix-list",
    "router vrrp",
    "apply access-list",
    "vsx",
    "evpn",
    "aruba-central",
    "no ip icmp",
    "tacacs-server host",
    MANY_UNKNOWN.format(count=2, first=56),
]

#: The row the parser makes for CONFIG's route that discards.
DISCARD_ROW = (
    "ip route: 1 route(s) that discard (nullroute, reject): the tree has no "
    "form for a route that discards; not translated"
)

#: Every row the committed AOS-CX inputs give, together: typed by hand.
#: Their other lines in column 0 are read (``hostname``, ``user``,
#: ``vlan``, ``vrf``, ``interface``, ``ip route``, ``snmpv3 user``, the
#: first community, location and contact) or a detector's
#: (``router bgp``, ``router ospf``, ``router pim``, ``access-list
#: ip``, ``route-map``).
COMMITTED_ROWS = {
    "apply access-list",
    "aruba-central",
    "clock timezone",
    "configuration-lockout central",
    "evpn",
    "https-server rest",
    "https-server vrf",
    "ip dns",
    "ip prefix-list",
    "no ip icmp",
    "ntp enable",
    "ntp server",
    "ntp vrf",
    "profile",
    "snmp-server vrf",
    "spanning-tree",
    "spanning-tree config-name",
    "spanning-tree config-revision",
    "spanning-tree forward-delay",
    "spanning-tree priority",
    "ssh server",
    "system interface-group",
    "tacacs-server host",
    "vsx",
}

CX_CAPTURES = [path for codec, _, path in CAPTURES if codec == "aruba_aoscx"]


def _words(text: str) -> list[str]:
    return text.lower().split()


def _unread_lines(text: str) -> list[tuple[int, list[str]]]:
    """(number, words) of each line in column 0 of *text* that begins
    with a letter and that the lists above, :data:`SESSION` and the
    detector do not account for: what nothing translates.  Of a kind in
    :data:`READ_ONCE` the first line with a value is read, and of each
    local user's name the first line in its read form."""
    found = []
    once_read: set[tuple[str, ...]] = set()
    users: set[str] = set()
    for number, line in enumerate(cx_parse.without_banner_bodies(text).splitlines(), start=1):
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
        elif words[0] in SESSION or _read_by_hand(words):
            continue
        if detect_tier3_sections_aoscx(line):
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
    have made: not a detector's, not a header's (``interface ...``),
    not a row of a stanza's statements or of a count (each has a
    ``:`` after its words, or begins with ``(``)."""
    elsewhere = set(detect_tier3_sections_aoscx(cx_parse.without_banner_bodies(text)))
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
    tree = get_codec("aruba_aoscx").parse(text)
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
    a line read, a detector's stanza, a banner, a line that begins with
    no letter and a word of a session are no row of this kind."""
    rows = cx_parse._rows_for_what_no_reader_takes(cx_parse.without_banner_bodies(CONFIG))
    assert rows == CONFIG_ROWS
    tree = get_codec("aruba_aoscx").parse(CONFIG)
    assert tree.dropped_tier3_sections == [
        *detect_tier3_sections_aoscx(cx_parse.without_banner_bodies(CONFIG)),
        DISCARD_ROW,
        *CONFIG_ROWS,
    ]
    _check_every_unread_line_is_said(CONFIG)


def test_what_the_parser_reads_is_still_read() -> None:
    """The lines CONFIG's rows leave out are read as they were: the
    first hostname, community, location and contact, the first line of
    a user's name, the VRF and the VLAN on lines of their own, the
    SNMPv3 user whose secrets are stated."""
    tree = get_codec("aruba_aoscx").parse(CONFIG)
    assert tree.hostname == "leaf1"
    assert [(u.name, u.role) for u in tree.local_users] == [("admin", "administrators")]
    assert [r.name for r in tree.routing_instances] == ["red"]
    assert [v.id for v in tree.vlans] == [10]
    assert tree.snmp is not None
    assert tree.snmp.community == "fakeCommunityA"
    assert (tree.snmp.location, tree.snmp.contact) == ("lab", "noc")
    assert [u.name for u in tree.snmp.v3_users] == ["v3u"]


def test_a_row_shows_no_value() -> None:
    """A row is a command's words: a secret, a community, an address or
    a name that follows them is not in it, nor is any word of a line
    that begins with no command the parser knows."""
    text = (
        "hostname leaf1\n"
        "tacacs-server key ciphertext AQBfakeTacacsKey==\n"
        "radius-server key ciphertext AQBfakeRadiusKey==\n"
        "user admin group administrators password ciphertext AQBfakeCipherA==\n"
        "user admin group operators password ciphertext AQBfakeCipherB==\n"
        "snmp-server community fakeCommunityA\n"
        "snmp-server community fakeCommunityB\n"
        "ntp authentication-key 1 sha1 ciphertext AQBfakeNtpKey==\n"
        "fakeword fakeSecret\n"
    )
    rows = get_codec("aruba_aoscx").parse(text).dropped_tier3_sections
    assert "tacacs-server key" in rows
    assert "user" in rows
    assert "snmp-server community" in rows
    assert "ntp authentication-key" in rows
    # ``radius-server`` is no word the committed inputs begin a line
    # with: its line is counted with the other, and shows nothing.
    assert MANY_UNKNOWN.format(count=2, first=3) in rows
    assert not [
        row for row in rows
        if "fake" in row.lower() or "aqb" in row.lower() or "admin" in row or "leaf1" in row
    ], rows
    _check_every_unread_line_is_said(text)


#: Two communities: the tree holds one, and the parser reads the first.
TWO_COMMUNITIES = (
    "hostname leaf1\n"
    "snmp-server community fakeCommunityA\n"
    "snmp-server community fakeCommunityB\n"
)


def test_a_second_community_is_a_row() -> None:
    """The tree holds one SNMP community, the first line of one the
    parser reads: a second line is in no output, and a row says so --
    one row, with no community in it."""
    one = get_codec("aruba_aoscx").parse(TWO_COMMUNITIES.rsplit("snmp", 1)[0])
    assert one.snmp is not None and one.snmp.community == "fakeCommunityA"
    assert "snmp-server community" not in one.dropped_tier3_sections
    two = get_codec("aruba_aoscx").parse(TWO_COMMUNITIES)
    assert two.snmp is not None and two.snmp.community == "fakeCommunityA"
    assert two.dropped_tier3_sections.count("snmp-server community") == 1
    assert not [row for row in two.dropped_tier3_sections if "fake" in row.lower()]
    _check_every_unread_line_is_said(TWO_COMMUNITIES)


def test_a_line_read_once_is_read_once() -> None:
    """Of a hostname and a local user's name the parser reads one line,
    the first: a second is a row."""
    text = (
        "hostname leaf1\n"
        "hostname leaf2\n"
        "user ops group operators password ciphertext AQBfakeCipherA==\n"
        "user ops group administrators password ciphertext AQBfakeCipherB==\n"
    )
    tree = get_codec("aruba_aoscx").parse(text)
    assert tree.hostname == "leaf1"
    assert [(u.name, u.role) for u in tree.local_users] == [("ops", "operators")]
    assert tree.dropped_tier3_sections == ["hostname", "user"]
    _check_every_unread_line_is_said(text)


def test_a_reader_reads_its_own_line() -> None:
    """A reader of a hostname, a location, a contact, a community or a
    user takes its value from its own line.  ``\\s`` crossed the line
    break: a ``snmp-server system-location`` line with no value was
    read with the next line for its location, a ``hostname`` line with
    none with the next line's first word for the hostname, and a
    ``user`` line with none with the next line for the account -- and
    the next line had no row."""
    text = (
        "snmp-server system-location\n"
        "snmp-server system-contact noc\n"
        "hostname\n"
        "leaf9\n"
        "user\n"
        "ops group operators password ciphertext AQBfakeCipherA==\n"
    )
    tree = get_codec("aruba_aoscx").parse(text)
    assert tree.snmp is not None
    assert (tree.snmp.location, tree.snmp.contact) == ("", "noc")
    assert tree.hostname == ""
    assert tree.local_users == []
    assert tree.dropped_tier3_sections == [
        "snmp-server system-location",
        "hostname",
        "user",
        MANY_UNKNOWN.format(count=2, first=4),
    ]
    _check_every_unread_line_is_said(text)


def test_a_vlan_the_switch_cannot_have_is_a_row() -> None:
    """A ``vlan`` line whose id is not one a switch has (0, above 4094,
    more digits than an id is read from, digits of another script)
    declares no VLAN, and is a row.  ``vlan`` and two Arabic-Indic
    digits had been read as VLAN 10."""
    text = (
        "vlan 0\n"
        "vlan 4095\n"
        "vlan 0010\n"
        "vlan \u0661\u0660\n"
        "vlan 00000000020\n"
        "vlan 20\n"
    )
    tree = get_codec("aruba_aoscx").parse(text)
    assert sorted(v.id for v in tree.vlans) == [10, 20]
    assert tree.dropped_tier3_sections == ["vlan"]
    _check_every_unread_line_is_said(text)


def test_the_committed_inputs_give_the_rows_typed_here() -> None:
    """Over the committed AOS-CX inputs the rows of this kind are the ones
    typed here, and each input's rows say each line nothing reads."""
    assert CX_CAPTURES
    found: set[str] = set()
    for path in CX_CAPTURES:
        text = path.read_text(encoding="utf-8")
        found.update(cx_parse._rows_for_what_no_reader_takes(cx_parse.without_banner_bodies(text)))
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
    rows = cx_parse._rows_for_what_no_reader_takes(text)
    assert len(rows) == LEFT_OUT_ROWS_SHOWN + 2
    assert rows[LEFT_OUT_ROWS_SHOWN] == (
        "(100 more kinds of top-level command not read; not listed)"
    )
    assert rows[-1] == MANY_UNKNOWN.format(count=1000, first=kinds + 1)


def test_a_job_says_the_rows() -> None:
    """A job from AOS-CX says them, as every row is said, and what those
    lines hold is in no output."""
    job = run_plan_with_checked_names(
        get_codec("aruba_aoscx"), get_codec("cisco_iosxe_cli"), CONFIG, port_rename_map={},
    )
    assert job.rendered, job.error
    for row in CONFIG_ROWS:
        assert row in job.dropped_tier3_sections, row
    for value in ("192.0.2.123", "192.0.2.53", "fakeCommunityB", "192.0.2.40"):
        assert value not in job.rendered, value


def test_the_row_that_counts_lines_is_known_by_its_form() -> None:
    """A row of a command's words is not taken for the row that counts
    lines of no known command."""
    for row in [*CONFIG_ROWS[:-1], *COMMITTED_ROWS]:
        assert not is_no_command_row(row), row
    assert is_no_command_row(CONFIG_ROWS[-1])


def test_a_text_that_is_no_config_is_still_said_to_be_none() -> None:
    """Text that is no config, given as AOS-CX, has the row that counts
    its lines and nothing else, and its job is ``partial``, as it was
    before the row: the row is no sign that the text was a config.
    A line of a command the parser knows is."""
    garbage = "lorem ipsum dolor\nsit amet\n"
    job = run_plan_with_checked_names(
        get_codec("aruba_aoscx"), get_codec("cisco_iosxe_cli"), garbage, port_rename_map={},
    )
    assert job.dropped_tier3_sections == [MANY_UNKNOWN.format(count=2, first=1)]
    assert job.status is MigrationJobStatus.partial
    assert job.error and "recognized" in job.error.lower()
    known = run_plan_with_checked_names(
        get_codec("aruba_aoscx"), get_codec("cisco_iosxe_cli"), "spanning-tree mode mstp\n",
        port_rename_map={},
    )
    assert known.dropped_tier3_sections == ["spanning-tree mode"]
    assert known.status is MigrationJobStatus.completed


def test_the_check_fails_without_the_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the rows taken out, the check fails."""
    monkeypatch.setattr(cx_parse, "_rows_for_what_no_reader_takes", lambda raw: [])
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_for_a_reader_that_takes_every_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reader said to take every line leaves lines nothing reads with
    no row: the check fails."""
    monkeypatch.setattr(cx_parse, "_TOP_LEVEL_READERS", (re.compile(r".*").match,))
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_for_rows_of_lines_that_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no reader listed, the lines read have rows: the check fails."""
    monkeypatch.setattr(cx_parse, "_TOP_LEVEL_READERS", ())
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


@pytest.mark.parametrize(
    ("reader", "text"),
    [
        pytest.param(
            cx_parse._SNMP_COMMUNITY_RE.match, TWO_COMMUNITIES, id="every-community",
        ),
        pytest.param(
            cx_parse._HOSTNAME_RE.match, "hostname leaf1\nhostname leaf2\n", id="every-hostname",
        ),
        pytest.param(cx_parse._VLAN_TOP_RE.match, "vlan 10\nvlan 5000\n", id="every-vlan-line"),
    ],
)
def test_the_check_fails_for_a_reader_of_lines_the_parse_does_not_read(
    monkeypatch: pytest.MonkeyPatch, reader: object, text: str,
) -> None:
    """Were every line of a kind taken -- a second community, a second
    hostname, a ``vlan`` line of an id no switch has -- nothing would
    say the one the parse does not read, and the check sees it."""
    monkeypatch.setattr(
        cx_parse, "_TOP_LEVEL_READERS", (*cx_parse._TOP_LEVEL_READERS, reader),
    )
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(text)
