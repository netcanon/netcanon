"""An Aruba AOS-S line in column 0 that nothing translates is a row.

The AOS-S parser reads a hostname, SNMP (the first community, the
location and contact, a trap host named by an IPv4 address, SNMPv3
users and their groups), the management plane (DNS, SNTP and NTP, the
time, logging), the default gateway and static routes, RADIUS servers
named by an IPv4 address and their key, the two accounts and the local
users, trunks, ``vlan`` and ``interface`` stanzas and the lines of the
top that set a port's VLANs, and the switch's own DHCP server; and the
AOS-S Tier-3 patterns give a row to access lists, class and policy
maps, route maps and the like, ``stacking``, ``vsf`` and ``oobm``.
Every other line in column 0 was in no output and no
row: an AOS-S config's spanning tree, its authorised managers, its SSH
and port-access settings, ``ip routing``, a second SNMP community, an
SNMP host or a RADIUS server named by an IPv6 address were dropped in
jobs that said ``completed``.

Now each kind of such line is a row of ``dropped_tier3_sections``
(``aruba_aoss.parse._rows_for_what_no_reader_takes``): its command
word, and the word after it where that says which command it is
(``spanning-tree mode``, ``aaa port-access``, ``ip ssh``), never a
value.  A line that begins with a word AOS-S configurations are not
seen to begin with is counted in one row that shows none of its text.
The body of a context nothing reads (``stacking``, ``device-profile``,
``router ospf``) is said by its header's row, with its indentation or
without (``aruba_aoss.parse._past_a_line_nothing_reads``).

The check reads the text with a list of what the parser reads, typed
here from the AOS-S grammar the parser takes -- the lines of the top,
and where a context of HPE's CLI ends: at its ``exit``, at an ``end``,
or at a line in column 0 that the top reads or that enters another
context -- and holds the rows to it: each line the list does not read
is said by a row, and each row says a line the list does not read.  It
is handed the parser with the rows taken out, with every line taken
for another row's, with no line taken for another row's, with every
community line read, with no context's flat body passed, and with
``logging`` a word whose next word a row shows, and has to fail.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration._tier3_detection import (
    LEFT_OUT_ROWS_SHOWN,
    detect_tier3_sections_aoss,
    is_no_command_row,
)
from netcanon.migration.codecs.aruba_aoss import parse as aoss_parse
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_vlan_members_reach_the_output import CAPTURES

pytestmark = pytest.mark.unit

_IPV4 = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}")

#: SNMPv3's algorithms, as ``snmpv3 user`` names them.
AUTH = frozenset({"md5", "sha", "sha256"})
PRIV = frozenset({"des", "aes", "aes128", "aes192", "aes256"})

#: The first words of the management plane's lines (``ip dns`` apart):
#: each such line is read, or said in a row of its own.
PLANE = frozenset({"timesync", "sntp", "ntp", "logging", "time"})

#: Words of a session, not of the configuration.
SESSION = frozenset({"configure", "end", "exit", "write"})

#: The commands of the ``oobm`` context whose words mean something else
#: at the top (HPE: the OOBM port's address and gateway are configured
#: "within the OOBM context"): none of them ends the context.
OOBM_WORDS = (
    ["ip", "address"], ["ip", "default-gateway"], ["enable"], ["disable"],
    ["interface", "enable"], ["interface", "disable"], ["interface", "speed-duplex"],
)


def _words(text: str) -> list[str]:
    return text.lower().split()


def _snmpv3_user(words: list[str]) -> bool:
    """``snmpv3 user <name> [auth <algorithm> <key>] [priv <algorithm>
    <key>]`` and nothing else."""
    rest = words[3:]
    if rest[:1] == ["auth"]:
        if len(rest) < 3 or rest[1] not in AUTH:
            return False
        rest = rest[3:]
    if rest[:1] == ["priv"]:
        if len(rest) < 3 or rest[1] not in PRIV:
            return False
        rest = rest[3:]
    return not rest


def _a_port_vlan_line(words: list[str]) -> bool:
    """``interface <ports> tagged|untagged vlan <ids>``."""
    return len(words) == 5 and words[2] in ("tagged", "untagged") and words[3] == "vlan"


def _a_line_of_the_top(words: list[str]) -> bool:
    """Whether the top of the config takes the line of *words* (in lower
    case) -- reads it, or says it in a row of another kind -- typed from
    the AOS-S grammar the parser takes.

    * ``hostname <name>``, every one (the last is the switch's).
    * ``snmp-server community <name> ...`` (the first is read:
      :func:`_unread_lines`), ``snmp-server location|contact <text>``,
      ``snmp-server host <IPv4 address> ...``.
    * ``snmpv3 user <name> [auth <algorithm> <key>] [priv <algorithm>
      <key>]``; ``snmpv3 group <group> user <name> sec-model ver3``.
    * The management plane: ``ip dns domain-name|server-address ...``,
      ``timesync``, ``sntp``, ``ntp``, ``logging``, ``time``.
    * ``ip default-gateway <IPv4 address>``; ``ip route ...`` and ``ipv6
      route ...``: a route, or said in a row of its own.
    * ``radius-server host <IPv4 address> ...``; ``radius-server
      key|encrypted-key <key>``.
    * ``password manager|operator [user-name <name>] [<kind>
      [<value>]]``; ``aaa authentication local-user ...``: an account,
      or said in a row of its own.
    * ``trunk <ports> <trunk> <type>``.
    * ``vlan <id>`` alone; ``interface <name>`` alone, ``interface
      loopback <n>``; ``[no] interface <ports> tagged|untagged vlan
      <ids>``.
    * ``oobm`` alone; ``[no] dhcp-server <word> ...``, a pool among them.
    """
    n = len(words)
    first, pair = words[0], words[:2]
    if first == "hostname":
        return n >= 2
    if pair in (["snmp-server", "community"], ["snmp-server", "location"], ["snmp-server", "contact"]):
        return n >= 3
    if pair == ["snmp-server", "host"]:
        return n >= 3 and _IPV4.match(words[2]) is not None
    if pair == ["snmpv3", "user"]:
        return n >= 3 and _snmpv3_user(words)
    if pair == ["snmpv3", "group"]:
        return n == 7 and words[3] == "user" and words[5:] == ["sec-model", "ver3"]
    if first in PLANE or words[:3] in (["ip", "dns", "domain-name"], ["ip", "dns", "server-address"]):
        return True
    if pair == ["ip", "default-gateway"]:
        return n >= 3 and _IPV4.match(words[2]) is not None
    if pair in (["ip", "route"], ["ipv6", "route"]):
        return True
    if pair == ["radius-server", "host"]:
        return n >= 3 and _IPV4.fullmatch(words[2]) is not None
    if pair in (["radius-server", "key"], ["radius-server", "encrypted-key"]):
        return n >= 3
    if pair in (["password", "manager"], ["password", "operator"]):
        rest = words[2:]
        if rest[:1] == ["user-name"]:
            if len(rest) < 2:
                return False
            rest = rest[2:]
        return len(rest) <= 2 and not (rest and rest[0].startswith('"'))
    if words[:3] == ["aaa", "authentication", "local-user"]:
        return True
    if first == "trunk":
        return n == 4
    if first == "vlan":
        return n == 2 and re.fullmatch(r"[0-9]+", words[1]) is not None
    if first == "interface":
        return _an_interface_header(words) or _a_port_vlan_line(words)
    if pair == ["no", "interface"]:
        return _a_port_vlan_line(words[1:])
    if first == "oobm":
        return n == 1
    if first == "dhcp-server":
        return n >= 2 and '"' not in words[1]
    if pair == ["no", "dhcp-server"]:
        return n >= 3 and '"' not in words[2]
    return False


def _an_interface_header(words: list[str]) -> bool:
    """``interface <name>``, ``interface <port>,<port>...`` or
    ``interface loopback <n>``: a stanza the top reads."""
    if len(words) == 3:
        return words[1] == "loopback" and re.fullmatch(r"[0-9]+", words[2]) is not None
    return len(words) == 2 and (
        re.fullmatch(r'[a-z0-9][a-z0-9./,-]*|"[a-z0-9][a-z0-9./-]*"', words[1]) is not None
    )


def _opens_a_stanza(words: list[str]) -> str:
    """The kind of stanza a line the top reads opens, or ``""``: a
    ``vlan``, an ``interface``, ``oobm`` or a DHCP pool alone on its
    line."""
    if words[0] in ("vlan", "interface") and len(words) <= 3 and not _a_port_vlan_line(words):
        return words[0]
    if words == ["oobm"]:
        return "oobm"
    if words[:2] == ["dhcp-server", "pool"] and len(words) == 3:
        return "pool"
    return ""


def _enters_a_context(words: list[str]) -> bool:
    """A line that enters a context of HPE's CLI that the top reads
    nothing of: ``stacking``, ``vsf``, ``router <protocol>``,
    ``device-profile <kind> <name>``, ``interface <name>``."""
    return (
        words in (["stacking"], ["vsf"])
        or (len(words) == 2 and words[0] in ("router", "interface"))
        or (len(words) == 3 and words[0] == "device-profile")
    )


def _a_nested_context(words: list[str]) -> bool:
    """A context inside another, with an ``exit`` of its own: a stack
    member's (``member <n>``, in ``oobm`` and ``vsf``), a VRRP group's
    (``vrrp vrid <n>``, in a ``vlan``)."""
    return (len(words) == 2 and words[0] == "member") or (len(words) == 3 and words[:2] == ["vrrp", "vrid"])


def _body_in_column_0(lines: list[str], after: int) -> bool:
    """Whether the first line after index *after* that is not blank or
    a comment begins in column 0."""
    for line in lines[after + 1:]:
        if line.strip() and not line.strip().startswith(";"):
            return not line[0].isspace()
    return False


def _unread_lines(text: str) -> list[tuple[int, list[str]]]:
    """(number, words) of each line in column 0 of *text* that begins
    with a letter and that the lists above, :data:`SESSION` and the
    detector do not account for, and that no context holds: what
    nothing translates.  Of the community lines the first with a value
    is read.  A context's body ends at its ``exit`` (one of a context
    nested in it first), an ``end``, or a line in column 0 that the top
    reads or that enters another context; the body of a context the
    top reads nothing of is held by it only where it is in column 0
    (where it is indented, the top passes its lines anyway)."""
    lines = aoss_parse.without_banner_bodies(text).splitlines()
    found = []
    community_read = False
    stanza, depth = "", 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        words = _words(line)
        if stanza:
            if words in (["exit"], ["end"]):
                if words == ["exit"] and depth:
                    depth -= 1
                else:
                    stanza, depth = "", 0
                continue
            held = (
                line[0].isspace()
                or (stanza == "oobm" and any(words[: len(w)] == w for w in OOBM_WORDS))
                or not (_a_line_of_the_top(words) or _enters_a_context(words))
            )
            if held:
                if _a_nested_context(words):
                    depth += 1
                continue
            stanza, depth = "", 0
        if line[0].isspace() or not line[:1].isalpha():
            continue
        if words[:2] == ["snmp-server", "community"] and len(words) >= 3 and not community_read:
            community_read = True
            continue
        if words[0] in SESSION or words == ["running", "configuration:"]:
            continue
        if _a_line_of_the_top(words) and words[:2] != ["snmp-server", "community"]:
            stanza = _opens_a_stanza(words)
            continue
        if not detect_tier3_sections_aoss(line):
            found.append((index + 1, words))
        if _enters_a_context(words) and _body_in_column_0(lines, index):
            stanza = "context"
    return found


#: The row that counts the lines that begin with no command word the
#: parser knows, in its two forms.
ONE_UNKNOWN = "a line in column 0 that begins with no command this parser knows (line {first})"
MANY_UNKNOWN = (
    "{count} lines in column 0 that begin with no command this parser knows "
    "(the first is line {first})"
)
_COUNTS_UNKNOWN = re.compile(r"begins? with no command this parser knows")
_LINE_NUMBER = re.compile(r"\((?:the first is )?line [0-9]+\)$")


def _says(row: str, words: list[str]) -> bool:
    """Whether *row* names the line of *words*: its words begin the
    line's (a row cut after a word that names a secret ends ``...``)."""
    shown = _words(row.removesuffix(" ..."))
    return words[: len(shown)] == shown


def _rows_of_this_kind(tree_rows: list[str], text: str) -> list[str]:
    """The rows of *tree_rows* that the walk of the top level could
    have made: not a detector's, and not a row of a statement read and
    not translated, of a stanza's lines or of a count (each says why in
    brackets) -- the row that counts lines of no known command apart."""
    elsewhere = set(detect_tier3_sections_aoss(aoss_parse.without_banner_bodies(text)))
    return [
        row for row in tree_rows
        if row not in elsewhere and ("(" not in row or _COUNTS_UNKNOWN.search(row))
    ]


def _check_every_unread_line_is_said(text: str) -> None:
    """Each line nothing translates is said by a row of its kind or
    counted in the row for lines with no known command, and each such
    row says a line nothing translates."""
    tree = get_codec("aruba_aoss").parse(text)
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


def _flat(text: str) -> str:
    """*text* with every line's indentation taken out."""
    return "".join(line.lstrip(" \t") for line in text.splitlines(keepends=True))


CONFIG = (
    "Running configuration:\n"  # 1
    "\n"
    "; JL000A Configuration Editor; Created on release #WC.16.11.0001\n"
    'hostname "sw1"\n'
    'hostname "sw2"\n'  # 5
    "module 1 type jl000a\n"
    'snmp-server community "fakeCommunityA" operator\n'
    'snmp-server community "fakeCommunityB" manager unrestricted\n'
    'snmp-server location "lab"\n'
    'snmp-server host 192.0.2.162 community "fakeCommunityA"\n'  # 10
    'snmp-server host 2001:db8::162 community "fakeCommunityA"\n'
    "snmp-server enable traps link-change 1\n"
    "snmpv3 enable\n"
    'snmpv3 user "v3u" auth sha "fakeAuthPass" priv aes "fakePrivPass"\n'
    'snmpv3 user "v3x" auth sha "fakeAuthPass" extra\n'  # 15
    'snmpv3 group "managerpriv" user "v3u" sec-model ver3\n'
    "ip dns server-address priority 1 192.0.2.53\n"
    "logging 192.0.2.40\n"
    "ip default-gateway 192.0.2.1\n"
    "ip route 10.9.0.0 255.255.0.0 192.0.2.254\n"  # 20
    "ip route 10.8.0.0/16 reject\n"
    "ip routing\n"
    "ip authorized-managers 192.0.2.0 255.255.255.0 access manager\n"
    "ip ssh filetransfer\n"
    'radius-server host 192.0.2.50 key "fakeRadiusKey"\n'  # 25
    "radius-server host 2001:db8::50\n"
    "radius-server timeout 3\n"
    'password manager user-name "boss" sha1 "fakeHash1"\n'
    "password minimum-length 8\n"
    'aaa authentication local-user "ops" group "Level-1" password sha1 "fakeHash2"\n'  # 30
    "aaa authentication login privilege-mode\n"
    "aaa port-access authenticator 1\n"
    "spanning-tree\n"
    "spanning-tree mode rapid-pvst\n"
    "no telnet-server\n"  # 35
    "trunk 47-48 trk1 lacp\n"
    "vlan 1\n"
    '   name "DEFAULT_VLAN"\n'
    "   untagged 1-46\n"
    "   exit\n"  # 40
    "vlan 10\n"
    '   name "ten"\n'
    "   tagged trk1\n"
    "   ip address 198.51.100.1 255.255.255.0\n"
    "   exit\n"  # 45
    "vlan 10,20\n"
    "interface 6 forbid vlan 20\n"
    "interface 7 untagged vlan 10\n"
    "interface 1\n"
    '   name "uplink"\n'  # 50
    "   exit\n"
    "oobm\n"
    "   ip address 192.0.2.10 255.255.255.0\n"
    "   exit\n"
    "stacking\n"  # 55
    '   member 1 type "JL000A"\n'
    "   exit\n"
    'device-profile name "default-ap-profile"\n'
    "   cos 0\n"
    "   exit\n"  # 60
    'dhcp-server pool "p1"\n'
    "   network 198.51.100.0 255.255.255.0\n"
    "   range 198.51.100.10 198.51.100.99\n"
    "   exit\n"
    "dhcp-server enable\n"  # 65
    "router ospf\n"
    "   area backbone\n"
    "   exit\n"
    'ip access-list extended "ACL1"\n'
    "   10 permit ip any any\n"  # 70
    "   exit\n"
    "frobnicate 1\n"
    "frobnicate 2\n"
    "42 is no command\n"
    "configure terminal\n"  # 75
    "write memory\n"
)

#: What CONFIG's lines in column 0 that nothing reads are, in the order
#: they come: typed by hand.  The printout's first line is no line of
#: the config; ``stacking``, ``oobm`` and the access list have rows of
#: their own; the route of a form not read is said in a row of its own.
CONFIG_ROWS = [
    "module",
    "snmp-server community",
    "snmp-server host",
    "snmp-server enable",
    "snmpv3 enable",
    "snmpv3 user",
    "ip routing",
    "ip authorized-managers",
    "ip ssh",
    "radius-server host",
    "radius-server timeout",
    "password",
    "aaa authentication",
    "aaa port-access",
    "spanning-tree",
    "spanning-tree mode",
    "no telnet-server",
    "vlan",
    "interface",
    "device-profile name",
    "router ospf",
    MANY_UNKNOWN.format(count=2, first=72),
]

#: The rows CONFIG's other lines are given: the Tier-3 patterns', then
#: the route of a form the parser does not read.
CONFIG_OTHER_ROWS = [
    'ip access-list extended "ACL1"',
    "oobm",
    "stacking",
    "ip route 10.8.0.0/16 reject (a static route in a form this parser does not read; not translated)",
]

#: Every row of this kind the committed AOS-S inputs give, together:
#: typed by hand.  Their other lines in column 0 are read, a detector's
#: or a prompt (counted in the row of lines with no known command).
COMMITTED_ROWS = {
    "allow-unsupported-transceiver",
    "device-profile name",
    "device-profile type",
    "dhcp-snooping",
    "dhcp-snooping authorized-server",
    "dhcp-snooping vlan",
    "include-credentials",
    "ip authorized-managers",
    "ip routing",
    "mac-delimiter",
    "management-vlan",
    "module",
    "no autorun",
    "no cwmp enable",
    "no dhcp",
    "no dhcp config-file-update",
    "no dhcp image-file-update",
    "no dhcp-snooping option",
    "no sntp",
    "no telnet-server",
    "no tftp server",
    "no web-management",
    "primary-vlan",
    "snmp-server enable",
    "snmpv3 engineid",
    "spanning-tree",
    "spanning-tree config-name",
    "spanning-tree priority",
    "web-management ssl",
}

AOSS_CAPTURES = [path for codec, _, path in CAPTURES if codec == "aruba_aoss"]


def test_each_kind_of_line_nothing_reads_is_a_row() -> None:
    """The rows of a config whose lines nothing reads are their kinds,
    in the order they come, and the lines with no command word are
    counted; a line read, a detector's line, a stanza's lines, a line
    that begins with no letter and a word of a session are no row of
    this kind."""
    tree = get_codec("aruba_aoss").parse(CONFIG)
    assert tree.dropped_tier3_sections == [*CONFIG_OTHER_ROWS, *CONFIG_ROWS]
    _check_every_unread_line_is_said(CONFIG)


def test_a_text_without_its_indentation_has_the_same_rows() -> None:
    """CONFIG with every line in column 0 is the same config, its rows
    the same."""
    flat = _flat(CONFIG)
    assert get_codec("aruba_aoss").parse(flat).model_dump(mode="json") == (
        get_codec("aruba_aoss").parse(CONFIG).model_dump(mode="json")
    )
    _check_every_unread_line_is_said(flat)


def test_what_the_parser_reads_is_still_read() -> None:
    """The lines CONFIG's rows leave out are read as they were: the last
    hostname, the first community, the location, the trap host named by
    an IPv4 address, the SNMPv3 user whose form is read, the routes, the
    RADIUS server named by an IPv4 address, the accounts, the trunk and
    the VLANs."""
    tree = get_codec("aruba_aoss").parse(CONFIG)
    assert tree.hostname == "sw2"
    assert tree.snmp is not None
    assert (tree.snmp.community, tree.snmp.location) == ("fakeCommunityA", "lab")
    assert tree.snmp.trap_hosts == ["192.0.2.162"]
    assert [u.name for u in tree.snmp.v3_users] == ["v3u"]
    assert [(r.destination, r.gateway) for r in tree.static_routes] == [
        ("0.0.0.0/0", "192.0.2.1"), ("10.9.0.0/16", "192.0.2.254"),
    ]
    assert [r.host for r in tree.radius_servers] == ["192.0.2.50"]
    assert [(u.name, u.role) for u in tree.local_users] == [("boss", "manager"), ("ops", "")]
    assert [lag.name for lag in tree.lags] == ["trk1"]
    assert [v.id for v in tree.vlans] == [1, 10]


#: A line of each kind whose words after its command are values.
VALUES = (
    'hostname "sw1"\n'
    'snmp-server community "fakeCommunityA" operator\n'
    'snmp-server community "fakeCommunityB" manager\n'
    "password minimum-length 8\n"
    'radius-server host 2001:db8::50 key "fakeRadiusKey"\n'
    'snmpv3 user "fakeUser" auth sha "fakeAuthPass" extra\n'
    "ip authorized-managers 192.0.2.0 255.255.255.0 access manager\n"
    "no logging loghost\n"
    "primary-vlan 10\n"
    "fakeword fakeSecret\n"
)


def _check_no_value(text: str) -> None:
    """No row of *text*'s shows a value: a name, a secret, an address
    or a server's name."""
    rows = get_codec("aruba_aoss").parse(text).dropped_tier3_sections
    # The row that counts lines shows the number of its first line,
    # which is no value of the config.
    shown = [_LINE_NUMBER.sub("", row) for row in rows]
    assert not [
        row for row in shown
        if any(value in row.lower() for value in ("fake", "loghost", "192.0.2", "2001:", " 10", " 8"))
    ], rows


def test_a_row_shows_no_value() -> None:
    """A row is a command's words: a secret, a community, an address or
    a name that follows them is not in it, nor is any word of a line
    that begins with no command the parser knows.  ``logging`` is a
    word whose next word is a syslog server, which can be a host's
    name, so ``no logging loghost`` is the row ``no logging``."""
    rows = get_codec("aruba_aoss").parse(VALUES).dropped_tier3_sections
    assert rows == [
        "snmp-server community",
        "password",
        "radius-server host",
        "snmpv3 user",
        "ip authorized-managers",
        "no logging",
        "primary-vlan",
        ONE_UNKNOWN.format(first=10),
    ]
    _check_no_value(VALUES)
    _check_every_unread_line_is_said(VALUES)


#: Two communities: the tree holds one, and the parser reads the first.
TWO_COMMUNITIES = (
    'hostname "sw1"\n'
    'snmp-server community "fakeCommunityA" operator\n'
    'snmp-server community "fakeCommunityB" operator\n'
)


def test_a_second_community_is_a_row() -> None:
    """The tree holds one SNMP community, the first line of one the
    parser reads: a second line is in no output, and a row says so --
    one row, with no community in it."""
    one = get_codec("aruba_aoss").parse(TWO_COMMUNITIES.rsplit("snmp", 1)[0])
    assert one.snmp is not None and one.snmp.community == "fakeCommunityA"
    assert one.dropped_tier3_sections == []
    two = get_codec("aruba_aoss").parse(TWO_COMMUNITIES)
    assert two.snmp is not None and two.snmp.community == "fakeCommunityA"
    assert two.dropped_tier3_sections == ["snmp-server community"]
    _check_every_unread_line_is_said(TWO_COMMUNITIES)


#: Contexts HPE's CLI enters that the top reads nothing of, a stack
#: member's nested in one, and a line of the top after them.
CONTEXTS = (
    "stacking\n"
    '   member 1 type "JL000A"\n'
    '   member 2 type "JL000A"\n'
    "   exit\n"
    'device-profile name "default-ap-profile"\n'
    "   cos 0\n"
    "   tagged-vlan 10\n"
    "   exit\n"
    "router ospf\n"
    "   area backbone\n"
    "   enable\n"
    "   exit\n"
    "vsf\n"
    "   member 1\n"
    '      type "JL000A"\n'
    "      priority 255\n"
    "      exit\n"
    "   exit\n"
    "spanning-tree\n"
)


def _check_a_context_says_its_body() -> None:
    """The rows of :data:`CONTEXTS` are its headers' and the line of the
    top after them, with its indentation or without."""
    for text in (CONTEXTS, _flat(CONTEXTS)):
        tree = get_codec("aruba_aoss").parse(text)
        assert tree.dropped_tier3_sections == [
            "stacking", "vsf", "device-profile name", "router ospf", "spanning-tree",
        ], tree.dropped_tier3_sections
        _check_every_unread_line_is_said(text)


def test_a_context_nothing_reads_says_its_body() -> None:
    """The lines of a context the top reads nothing of are said by the
    row of its header: without their indentation they are lines of the
    context still, to its ``exit``, and no row of their own."""
    _check_a_context_says_its_body()


def test_the_committed_inputs_give_the_rows_typed_here() -> None:
    """Over the committed AOS-S inputs the rows of this kind are the
    ones typed here, and each input's rows say each line nothing reads,
    with its indentation and without."""
    assert AOSS_CAPTURES
    found: set[str] = set()
    for path in AOSS_CAPTURES:
        text = path.read_text(encoding="utf-8")
        rows = _rows_of_this_kind(get_codec("aruba_aoss").parse(text).dropped_tier3_sections, text)
        found.update(row for row in rows if not _COUNTS_UNKNOWN.search(row))
        _check_every_unread_line_is_said(text)
        _check_every_unread_line_is_said(_flat(text))
    assert found == COMMITTED_ROWS


def test_the_rows_are_bounded() -> None:
    """Past ``LEFT_OUT_ROWS_SHOWN`` kinds one row counts the rest, and
    any number of lines with no known command is one row."""
    def letters(n: int) -> str:
        return "".join(chr(ord("a") + int(d)) for d in str(n))

    kinds = LEFT_OUT_ROWS_SHOWN + 100
    text = "".join(f"ip kind{letters(n)} 1\n" for n in range(kinds))
    text += "".join(f"frobnicate {n}\n" for n in range(1000))
    rows = get_codec("aruba_aoss").parse(text).dropped_tier3_sections
    assert len(rows) == LEFT_OUT_ROWS_SHOWN + 2
    assert rows[LEFT_OUT_ROWS_SHOWN] == (
        "(100 more kinds of top-level command not read; not listed)"
    )
    assert rows[-1] == MANY_UNKNOWN.format(count=1000, first=kinds + 1)


def test_a_job_says_the_rows() -> None:
    """A job from AOS-S says them, as every row is said, and what those
    lines hold is in no output."""
    job = run_plan_with_checked_names(
        get_codec("aruba_aoss"), get_codec("cisco_iosxe_cli"), CONFIG, port_rename_map={},
    )
    assert job.rendered, job.error
    for row in CONFIG_ROWS:
        assert row in job.dropped_tier3_sections, row
    for value in ("fakeCommunityB", "2001:db8::162", "2001:db8::50", "rapid-pvst", "authorized-managers"):
        assert value not in job.rendered, value


def test_the_row_that_counts_lines_is_known_by_its_form() -> None:
    """A row of a command's words is not taken for the row that counts
    lines of no known command."""
    for row in [*CONFIG_ROWS[:-1], *COMMITTED_ROWS]:
        assert not is_no_command_row(row), row
    assert is_no_command_row(CONFIG_ROWS[-1])


def test_a_text_that_is_no_config_is_still_said_to_be_none() -> None:
    """Text that is no config, given as AOS-S, has the row that counts
    its lines and nothing else, and its job is ``partial``, as it was
    before the row: the row is no sign that the text was a config.  A
    line of a command the parser knows is."""
    garbage = "lorem ipsum dolor\nsit amet\n"
    job = run_plan_with_checked_names(
        get_codec("aruba_aoss"), get_codec("cisco_iosxe_cli"), garbage, port_rename_map={},
    )
    assert job.dropped_tier3_sections == [MANY_UNKNOWN.format(count=2, first=1)]
    assert job.status is MigrationJobStatus.partial
    assert job.error and "recognized" in job.error.lower()
    known = run_plan_with_checked_names(
        get_codec("aruba_aoss"), get_codec("cisco_iosxe_cli"), "spanning-tree mode mstp\n",
        port_rename_map={},
    )
    assert known.dropped_tier3_sections == ["spanning-tree mode"]
    assert known.status is MigrationJobStatus.completed


# ---------------------------------------------------------------------------
# Each check, handed the defect it is for
# ---------------------------------------------------------------------------


def test_the_check_fails_without_the_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the rows taken out, the check fails."""
    monkeypatch.setattr(aoss_parse, "_rows_for_what_no_reader_takes", lambda lines, unread: [])
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_with_every_line_taken_for_another_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Were every line taken for a line another row says, lines nothing
    reads would have no row: the check fails."""
    monkeypatch.setattr(aoss_parse, "_said_elsewhere", lambda line: True)
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_with_no_line_taken_for_another_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Were no line taken for another row's, the printout's first line
    and the access list's header would be rows of this kind too: the
    check fails."""
    monkeypatch.setattr(aoss_parse, "_said_elsewhere", lambda line: False)
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_with_every_community_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Were every community line read, nothing would say the second,
    which the tree does not hold: the check sees it."""
    rows = aoss_parse._rows_for_what_no_reader_takes
    monkeypatch.setattr(
        aoss_parse, "_rows_for_what_no_reader_takes",
        lambda lines, unread: rows(
            lines, [n for n in unread if not lines[n].startswith("snmp-server community")],
        ),
    )
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(TWO_COMMUNITIES)


def test_the_context_check_fails_when_a_flat_body_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Were a context's body read at the top of a text without its
    indentation, its lines would be rows of their own: the check fails."""
    monkeypatch.setattr(aoss_parse, "_past_a_line_nothing_reads", lambda lines, at: at + 1)
    with pytest.raises(AssertionError):
        _check_a_context_says_its_body()


def test_the_value_check_fails_with_logging_a_family(monkeypatch: pytest.MonkeyPatch) -> None:
    """Were the word after ``logging`` shown, a syslog server's name
    would be in a row: the check sees it."""
    monkeypatch.setattr(aoss_parse, "_FAMILIES", aoss_parse._FAMILIES | {"logging"})
    with pytest.raises(AssertionError):
        _check_no_value(VALUES)
