"""A Cisco NX-OS line in column 0 that nothing translates is a row.

The NX-OS parser reads a hostname, the release, a domain, DNS, NTP and
syslog servers, interfaces, VLANs, VRFs, static routes, SNMP, local
users, VXLAN and the anycast-gateway MAC, and the NX-OS Tier-3 patterns
give a row to routing protocols, ACLs, route maps, QoS maps, crypto,
AAA and SPAN sessions.  Every other line in column 0 was in no output
and no row: an NX-OS config's vPC domain, its EVPN stanza, its prefix
lists, its spanning tree, its ``logging`` settings, its line and CoPP
settings, the services it enables (``feature bgp``, ``feature ssh``),
a second SNMP community and a second line of a local user were dropped
in jobs that said ``completed``.

Now each kind of such line is a row of ``dropped_tier3_sections``
(``cisco_nxos.parse._rows_for_what_no_reader_takes``): its command
word, and the word after it where that says which command it is
(``vpc domain``, ``logging level``, ``feature bgp``), never a value.  A
line that begins with a word NX-OS configurations are not seen to
begin with is counted in one row that shows none of its text.

The check reads the text with a list of what the parser reads, typed
here from the NX-OS grammar the parser takes, and holds the rows to it:
each line the list does not read is said by a row, and each row says a
line the list does not read.  It is handed the parser with the rows
taken out, with a reader that takes every line, with one that takes
none and with one that takes every community line, and has to fail.
"""

from __future__ import annotations

import ipaddress
import re

import pytest

from netcanon.migration._tier3_detection import (
    LEFT_OUT_ROWS_SHOWN,
    detect_tier3_sections_nxos,
    is_no_command_row,
)
from netcanon.migration.codecs.cisco_nxos import parse as nx_parse
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_vlan_members_reach_the_output import CAPTURES

pytestmark = pytest.mark.unit

#: The lines in column 0 the parser reads whatever follows, or says in
#: a row of their own (an ``interface`` header names a record, the VXLAN
#: container, or is a row of ``test_a_header_names_one_interface.py``),
#: by how each begins: typed from the NX-OS grammar, not taken from the
#: parser.  The lines it reads only in one form, or only once, are asked
#: by :func:`_read_by_hand` and :func:`_unread_lines`.
READ_BY_HAND = (
    "interface ",
    "ntp server ",
    "vlan dot1q tag native",
)

#: The ``feature`` lines whose features the parser reads the
#: configuration of: SVIs, LAGs, HSRP, tunnels, VXLAN and the anycast
#: gateway.
FEATURES_READ = (
    "fabric forwarding", "hsrp", "interface-vlan", "lacp", "nv overlay",
    "tunnel", "vn-segment-vlan-based",
)

#: The kinds of line the tree holds one of, by the words each begins
#: with: the parser reads the first line of the kind (in the form
#: :func:`_read_once_form` gives) and no other.
READ_ONCE = (
    ("hostname",),
    ("version",),
    ("ip", "domain-name"),
    ("snmp-server", "community"),
    ("snmp-server", "location"),
    ("snmp-server", "contact"),
    ("fabric", "forwarding", "anycast-gateway-mac"),
)


def _an_address(word: str) -> bool:
    try:
        ipaddress.ip_address(word)
    except ValueError:
        return False
    return True


def _read_once_form(kind: tuple[str, ...], words: list[str]) -> bool:
    """Whether the line of *words* is of the form the parser reads of
    the read-once *kind*: ``ip domain-name <name>`` alone on its line;
    the anycast MAC as a MAC (twelve hex digits); the others with a
    value after their words."""
    if kind == ("ip", "domain-name"):
        return len(words) == 3
    if kind == ("fabric", "forwarding", "anycast-gateway-mac"):
        return len(words) == 4 and len(re.sub(r"[^0-9a-f]", "", words[3])) == 12
    return len(words) > len(kind)


def _read_by_hand(words: list[str]) -> bool:
    """Whether the parser reads the line of *words* (in lower case),
    whichever line of its kind it is: one that begins as
    :data:`READ_BY_HAND` has it, or one of the forms the parser reads
    of a command whose other forms it does not.

    * ``vrf context <name>``.
    * ``vlan <id list>``; ``vlan configuration ...`` is not read.
    * ``feature <name>`` of :data:`FEATURES_READ`.
    * ``ip name-server [vrf <name>] <address> ...``: a line that names
      an address.
    * ``logging ...``: a line that names an address, a syslog server.
    * ``ip route <IPv4 prefix>/<length> <next hop> ...`` and ``ipv6
      route <prefix>/<length> <next hop> ...``.
    * ``snmp-server host <IPv4 address> ...``.
    * ``snmp-server user <name> [<group>] auth <algorithm> ...``.
    """
    line = " ".join(words)
    if (line + " ").startswith(READ_BY_HAND) or line == "vlan dot1q tag native":
        return True
    if words[:2] == ["vrf", "context"]:
        return len(words) == 3
    if words[0] == "vlan":
        return len(words) == 2 and re.fullmatch(r"[\d,-]+", words[1]) is not None
    if words[0] == "feature":
        return " ".join(words[1:]) in FEATURES_READ
    if words[:2] == ["ip", "name-server"]:
        rest = words[4:] if words[2:3] == ["vrf"] else words[2:]
        return any(_an_address(word) for word in rest)
    if words[0] == "logging":
        return any(_an_address(word) for word in words[1:])
    if words[:2] == ["ip", "route"]:
        return len(words) > 3 and re.fullmatch(r"\d+\.\d+\.\d+\.\d+/\d+", words[2]) is not None
    if words[:2] == ["ipv6", "route"]:
        return len(words) > 3 and re.fullmatch(r"[0-9a-f:]+/\d+", words[2]) is not None
    if words[:2] == ["snmp-server", "host"]:
        return len(words) > 2 and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", words[2]) is not None
    if words[:2] == ["snmp-server", "user"]:
        return "auth" in words[3:5] and words.index("auth") + 2 < len(words) and words[
            words.index("auth") + 1
        ] in ("md5", "sha", "sha224", "sha256", "sha384", "sha512")
    return False


def _a_user_line(words: list[str]) -> bool:
    """``username <name> password <type> <hash> role <role>``: the line
    of a local user the parser reads, the first of each name
    (:func:`_unread_lines`)."""
    return (
        len(words) >= 7 and words[0] == "username" and words[2] == "password"
        and words[3].isdigit() and words[5] == "role"
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
    "!Command: show running-config\n"  # 1
    "version 9.3(8) Bios:version\n"
    "hostname leaf1\n"
    "switchname leaf1\n"
    "vdc leaf1 id 1\n"  # 5
    "  limit-resource vlan minimum 16 maximum 4094\n"
    "\n"
    "feature bgp\n"
    "feature interface-vlan\n"
    "feature lacp\n"  # 10
    "feature vpc\n"
    "feature nv overlay\n"
    "\n"
    "username admin password 5 $5$fake$hash role network-admin\n"
    "username admin sshkey ssh-rsa fakeKey\n"  # 15
    "username ops password 5 $5$fake$hash role network-operator\n"
    "banner motd #\n"
    "frobnicate in a banner\n"
    "#\n"
    "ip domain-lookup\n"  # 20
    "ip domain-name example.net\n"
    "ip name-server 192.0.2.53 192.0.2.54 use-vrf management\n"
    "logging server 192.0.2.20 6 use-vrf management\n"
    "logging server loghost.example.net\n"
    "logging level aaa 5\n"  # 25
    "ntp server 192.0.2.123 use-vrf management\n"
    "ntp source-interface mgmt0\n"
    "snmp-server contact noc\n"
    "snmp-server location lab\n"
    "snmp-server community fakeCommunityA group network-operator\n"  # 30
    "snmp-server community fakeCommunityB group network-admin\n"
    "snmp-server host 192.0.2.30 traps version 2c fakeCommunityA\n"
    "snmp-server enable traps\n"
    "\n"
    "vlan 1,10,20\n"  # 35
    "vlan 30\n"
    "  name users\n"
    "vlan configuration 10\n"
    "spanning-tree mode mst\n"
    "\n"  # 40
    "vrf context blue\n"
    "  rd 65001:1\n"
    "vpc domain 1\n"
    "  peer-keepalive destination 192.0.2.99\n"
    "\n"  # 45
    "interface Vlan10\n"
    "  no shutdown\n"
    "  ip address 198.51.100.1/24\n"
    "\n"
    "interface Ethernet1/1\n"  # 50
    "  switchport\n"
    "\n"
    "ip access-list EDGE\n"
    "  10 permit ip any any\n"
    "route-map RM permit 10\n"  # 55
    "ip prefix-list PL seq 5 permit 10.0.0.0/8\n"
    "ip route 0.0.0.0/0 198.51.100.254\n"
    "router bgp 65001\n"
    "  neighbor 198.51.100.2 remote-as 65002\n"
    "fabric forwarding anycast-gateway-mac 0000.2222.3333\n"  # 60
    "evpn\n"
    "  vni 10010 l2\n"
    "line console\n"
    "  exec-timeout 0\n"
    "line vty\n"  # 65
    "boot nxos bootflash:/nxos.bin\n"
    "no password strength-check\n"
    "frobnicate 1\n"
    "frobnicate 2\n"
    "42 is no command\n"  # 70
    "end\n"
)

#: What CONFIG's lines in column 0 that nothing reads are, in the order
#: they come: typed by hand.  The banner is text, not lines of the
#: config, its opening line among them: no row is made of it here.
CONFIG_ROWS = [
    "switchname",
    "vdc",
    "feature bgp",
    "feature vpc",
    "username",
    "ip domain-lookup",
    "logging server",
    "logging level",
    "ntp source-interface",
    "snmp-server community",
    "snmp-server enable",
    "vlan configuration",
    "spanning-tree mode",
    "vpc domain",
    "ip prefix-list",
    "evpn",
    "line console",
    "line vty",
    "boot nxos",
    "no password ...",
    MANY_UNKNOWN.format(count=2, first=68),
]

#: Every row the committed NX-OS inputs give, together: typed by hand.
#: One input is pasted with the terminal's prompt line above the
#: printout, which holds nothing to translate and is counted, as any
#: line that begins with no command is.
COMMITTED_ROWS = {
    "boot nxos",
    "cfs eth",
    "cli alias",
    "copp profile",
    "errdisable recovery",
    "evpn",
    "feature bash-shell",
    "feature bgp",
    "feature grpc",
    "feature lldp",
    "feature netconf",
    "feature nxapi",
    "feature ospf",
    "feature scp-server",
    "feature telnet",
    "feature vpc",
    "hardware access-list",
    "hardware ip",
    "icam monitor",
    "ip domain-lookup",
    "ip igmp",
    "ip prefix-list",
    "ip tcp",
    "ip tftp",
    "key ...",
    "line console",
    "line vty",
    "logging level",
    "logging origin-id",
    "logging source-interface",
    "mac address-table",
    "no hardware access-list",
    "no ip domain-lookup",
    "no ip igmp",
    "no ip source-route",
    "no lldp tlv-select",
    "no password",
    "no password ...",
    "ntp access-group",
    "ntp source-interface",
    "nv overlay",
    "nxapi ssl",
    "rmon event",
    "snmp-server community",
    "snmp-server enable",
    "spanning-tree mode",
    "spanning-tree mst",
    "ssh key",
    "system qos",
    "username",
    "vdc",
    "vpc domain",
    ONE_UNKNOWN.format(first=5),
}

NXOS_CAPTURES = [path for codec, _, path in CAPTURES if codec == "cisco_nxos"]


def _words(text: str) -> list[str]:
    return text.lower().split()


def _unread_lines(text: str) -> list[tuple[int, list[str]]]:
    """(number, words) of each line in column 0 of *text* that begins
    with a letter and that the lists above, :data:`SESSION` and the
    detector do not account for: what nothing translates.  Of a kind in
    :data:`READ_ONCE` the first line in its read form is read, and of
    each local user's name the first line in its read form."""
    found = []
    once_read: set[tuple[str, ...]] = set()
    users: set[str] = set()
    for number, line in enumerate(nx_parse.without_banner_bodies(text).splitlines(), start=1):
        if not line[:1].isalpha():
            continue
        words = _words(line)
        kind = next((k for k in READ_ONCE if tuple(words[: len(k)]) == k), None)
        if kind is not None:
            if kind not in once_read and _read_once_form(kind, words):
                once_read.add(kind)
                continue
        elif _a_user_line(words):
            if words[1] not in users:
                users.add(words[1])
                continue
        elif words[0] in SESSION or _read_by_hand(words):
            continue
        if detect_tier3_sections_nxos(line):
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
    elsewhere = set(detect_tier3_sections_nxos(nx_parse.without_banner_bodies(text)))
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
    tree = get_codec("cisco_nxos").parse(text)
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
    rows = nx_parse._rows_for_what_no_reader_takes(nx_parse.without_banner_bodies(CONFIG))
    assert rows == CONFIG_ROWS
    tree = get_codec("cisco_nxos").parse(CONFIG)
    assert tree.dropped_tier3_sections == [
        *detect_tier3_sections_nxos(nx_parse.without_banner_bodies(CONFIG)),
        *CONFIG_ROWS,
    ]
    _check_every_unread_line_is_said(CONFIG)


def test_a_row_shows_no_value() -> None:
    """A row is a command's words: a secret, a community, an address or
    a name that follows them is not in it, nor is any word of a line
    that begins with no command the parser knows."""
    text = (
        "hostname leaf1\n"
        "interface Ethernet1/1\n  no switchport\n"
        "tacacs-server key 7 fakeTacacsKey\n"
        "ntp authentication-key 1 md5 fakeNtpKey 7\n"
        "username admin password 5 $5$fake$hash role network-admin\n"
        "username admin sshkey ssh-rsa fakeKey\n"
        "snmp-server community fakeCommunityA group network-operator\n"
        "snmp-server community fakeCommunityB group network-admin\n"
        "key chain fakeChain\n"
        "fakeword fakeSecret\n"
    )
    rows = get_codec("cisco_nxos").parse(text).dropped_tier3_sections
    assert "tacacs-server key" in rows
    assert "ntp authentication-key" in rows
    assert "username" in rows
    assert "snmp-server community" in rows
    assert "key ..." in rows
    assert ONE_UNKNOWN.format(first=11) in rows
    assert not [
        row for row in rows
        if "fake" in row.lower() or "$5$" in row or "admin" in row or "leaf1" in row
    ], rows
    _check_every_unread_line_is_said(text)


#: Two communities: the tree holds one, and the parser reads the first.
TWO_COMMUNITIES = (
    "hostname leaf1\n"
    "snmp-server community fakeCommunityA group network-operator\n"
    "snmp-server community fakeCommunityB group network-admin\n"
)


def test_a_second_community_is_a_row() -> None:
    """The tree holds one SNMP community, the first line of one the
    parser reads: a second line is in no output, and a row says so --
    one row, with no community in it."""
    one = get_codec("cisco_nxos").parse(TWO_COMMUNITIES.rsplit("snmp", 1)[0])
    assert one.snmp is not None and one.snmp.community == "fakeCommunityA"
    assert "snmp-server community" not in one.dropped_tier3_sections
    two = get_codec("cisco_nxos").parse(TWO_COMMUNITIES)
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
        nx_parse, "_TOP_LEVEL_READERS",
        (*nx_parse._TOP_LEVEL_READERS, nx_parse._SNMP_COMMUNITY_RE.match),
    )
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(TWO_COMMUNITIES)


def test_a_line_read_once_is_read_once() -> None:
    """Of a hostname, an anycast-gateway MAC and a local user's name the
    parser reads one line, the first: a second is a row, and one whose
    MAC is no MAC is not read at all."""
    text = (
        "hostname leaf1\n"
        "hostname leaf2\n"
        "fabric forwarding anycast-gateway-mac 0000.2222.3333\n"
        "fabric forwarding anycast-gateway-mac 0000.2222.4444\n"
        "username ops password 5 $5$fake$hash role network-operator\n"
        "username ops password 5 $5$fake$hash role network-admin\n"
    )
    tree = get_codec("cisco_nxos").parse(text)
    assert tree.hostname == "leaf1"
    assert tree.anycast_gateway_mac == "00:00:22:22:33:33"
    assert [(u.name, u.role) for u in tree.local_users] == [("ops", "network-operator")]
    assert tree.dropped_tier3_sections == ["hostname", "fabric forwarding", "username"]
    _check_every_unread_line_is_said(text)
    bad = "fabric forwarding anycast-gateway-mac nothing\n" + text.split("\n", 2)[2]
    tree = get_codec("cisco_nxos").parse(bad)
    assert not tree.anycast_gateway_mac
    assert "fabric forwarding" in tree.dropped_tier3_sections
    _check_every_unread_line_is_said(bad)


def test_the_committed_inputs_give_the_rows_typed_here() -> None:
    """Over the committed NX-OS inputs the rows of this kind are the ones
    typed here, and each input's rows say each line nothing reads."""
    assert NXOS_CAPTURES
    found: set[str] = set()
    for path in NXOS_CAPTURES:
        text = path.read_text(encoding="utf-8")
        found.update(nx_parse._rows_for_what_no_reader_takes(nx_parse.without_banner_bodies(text)))
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
    rows = nx_parse._rows_for_what_no_reader_takes(text)
    assert len(rows) == LEFT_OUT_ROWS_SHOWN + 2
    assert rows[LEFT_OUT_ROWS_SHOWN] == (
        "(100 more kinds of top-level command not read; not listed)"
    )
    assert rows[-1] == MANY_UNKNOWN.format(count=1000, first=kinds + 1)


def test_a_job_says_the_rows() -> None:
    """A job from NX-OS says them, as every row is said, and what those
    lines hold is in no output."""
    job = run_plan_with_checked_names(
        get_codec("cisco_nxos"), get_codec("cisco_iosxe_cli"), CONFIG, port_rename_map={},
    )
    assert job.rendered, job.error
    for row in CONFIG_ROWS:
        assert row in job.dropped_tier3_sections, row
    for value in ("loghost.example.net", "65002", "fakeCommunityB", "192.0.2.99"):
        assert value not in job.rendered, value


def test_the_row_that_counts_lines_is_known_by_its_form() -> None:
    """A row of a command's words is not taken for the row that counts
    lines of no known command."""
    for row in [*CONFIG_ROWS[:-1], *COMMITTED_ROWS - {ONE_UNKNOWN.format(first=5)}]:
        assert not is_no_command_row(row), row
    assert is_no_command_row(CONFIG_ROWS[-1])
    assert is_no_command_row(ONE_UNKNOWN.format(first=5))


def test_a_text_that_is_no_config_is_still_said_to_be_none() -> None:
    """Text that is no config, given as NX-OS, has the row that counts
    its lines and nothing else, and its job is ``partial``, as it was
    before the row: the row is no sign that the text was a config.
    A line of a command the parser knows is."""
    garbage = "lorem ipsum dolor\nsit amet\n"
    job = run_plan_with_checked_names(
        get_codec("cisco_nxos"), get_codec("cisco_iosxe_cli"), garbage, port_rename_map={},
    )
    assert job.dropped_tier3_sections == [MANY_UNKNOWN.format(count=2, first=1)]
    assert job.status is MigrationJobStatus.partial
    assert job.error and "recognized" in job.error.lower()
    known = run_plan_with_checked_names(
        get_codec("cisco_nxos"), get_codec("cisco_iosxe_cli"), "spanning-tree mode mst\n",
        port_rename_map={},
    )
    assert known.dropped_tier3_sections == ["spanning-tree mode"]
    assert known.status is MigrationJobStatus.completed


def test_the_servers_are_still_read() -> None:
    """The DNS, NTP and syslog lines that name an address are read as
    they were, each syslog server once, and give no row; the others
    are rows."""
    text = (
        "ip name-server 192.0.2.53 192.0.2.54 use-vrf management\n"
        "ntp server 192.0.2.123 use-vrf management\n"
        "logging server 192.0.2.20\n"
        "logging server 192.0.2.21 6 use-vrf management\n"
        "logging server 192.0.2.20 5\n"
        "logging level aaa 5\n"
    )
    tree = get_codec("cisco_nxos").parse(text)
    assert tree.dns_servers == ["192.0.2.53", "192.0.2.54"]
    assert tree.ntp_servers == ["192.0.2.123"]
    assert tree.syslog_servers == ["192.0.2.20", "192.0.2.21"]
    assert tree.dropped_tier3_sections == ["logging level"]


def test_a_feature_is_a_row_where_nothing_reads_what_it_enables() -> None:
    """A ``feature`` line of what the parser reads is taken -- what it
    enables is translated -- and any other is a row of its name."""
    text = "".join(f"feature {name}\n" for name in (*FEATURES_READ, "bgp", "ssh", "udld"))
    tree = get_codec("cisco_nxos").parse(text)
    assert tree.dropped_tier3_sections == ["feature bgp", "feature ssh", "feature udld"]
    _check_every_unread_line_is_said(text)


def test_the_check_fails_without_the_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the rows taken out, the check fails."""
    monkeypatch.setattr(nx_parse, "_rows_for_what_no_reader_takes", lambda raw: [])
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_for_a_reader_that_takes_every_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reader said to take every line leaves lines nothing reads with
    no row: the check fails."""
    monkeypatch.setattr(nx_parse, "_TOP_LEVEL_READERS", (re.compile(r".*").match,))
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_for_rows_of_lines_that_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no reader listed, the lines read have rows: the check fails."""
    monkeypatch.setattr(nx_parse, "_TOP_LEVEL_READERS", ())
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_for_a_reader_of_every_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Were a second hostname taken, nothing would say it, and the
    check sees it."""
    monkeypatch.setattr(
        nx_parse, "_TOP_LEVEL_READERS",
        (*nx_parse._TOP_LEVEL_READERS, nx_parse._HOSTNAME_RE.match),
    )
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said("hostname leaf1\nhostname leaf2\n")
