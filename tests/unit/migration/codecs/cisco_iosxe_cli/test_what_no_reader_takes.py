"""A Cisco IOS-XE line in column 0 that nothing translates is a row.

The IOS-XE CLI parser reads a hostname, the release, a domain, DNS, NTP
and syslog servers, interfaces, VLANs, VRFs, static routes, SNMP, local
users, DHCP pools, RADIUS servers and the anycast-gateway MAC, and the
IOS-XE Tier-3 patterns give a row to ACLs, NAT, class and policy maps,
route maps, crypto, zone pairs and a stack's own lines.  Every other
line in column 0 was in no output and no row: an IOS-XE config's
spanning tree, its ``line``, SSH, HTTP and AAA settings, its
``logging`` settings, its routing protocols, its prefix lists, a
second SNMP community and a second line of a local user were dropped
in jobs that said ``completed``.

Now each kind of such line is a row of ``dropped_tier3_sections``
(``cisco_iosxe_cli.parse._rows_for_what_no_reader_takes``): its command
word, and the word after it where that says which command it is
(``spanning-tree mode``, ``line vty``, ``router ospf``), never a value.
A line that begins with a word IOS-XE configurations are not seen to
begin with is counted in one row that shows none of its text.

The check reads the text with a list of what the parser reads, typed
here from the IOS-XE grammar the parser takes, and holds the rows to
it: each line the list does not read is said by a row, and each row
says a line the list does not read.  It is handed the parser with the
rows taken out, with a reader that takes every line, with one that
takes none, with ones that take every line of a kind the parser reads
once, and with the printout's lines read as config, and has to fail.
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
from netcanon.migration.codecs.cisco_iosxe_cli import parse as xe_parse
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_vlan_members_reach_the_output import CAPTURES

pytestmark = pytest.mark.unit

#: The kinds of line the tree holds one of, by the words each begins
#: with: the parser reads the first line of the kind in the form
#: :func:`_read_once_form` gives, and no other.  ``ip domain name`` and
#: ``ip domain-name`` are one kind.
READ_ONCE = (
    ("hostname",),
    ("version",),
    ("ip", "domain", "name"),
    ("ip", "domain-name"),
    ("snmp-server", "community"),
    ("snmp-server", "location"),
    ("snmp-server", "contact"),
    ("fabric", "forwarding", "anycast-gateway-mac"),
)

#: A line the device prints around the configuration: typed from
#: printed IOS-XE output, in lower case, its words one space apart.
PRINTOUT = re.compile(
    r"building configuration\.\.\."
    r"|current configuration ?: ?[0-9]+ bytes"
    r"|using [0-9]+ out of [0-9]+ bytes(?:, ?uncompressed size ?= ?[0-9]+ bytes)?"
    r"|boot-start-marker|boot-end-marker"
)

#: Words of a session, not of the configuration.
SESSION = frozenset({"configure", "end", "exit", "write"})

_V3_AUTH = ("md5", "sha", "sha224", "sha256", "sha384", "sha512")


def _an_address(word: str) -> bool:
    try:
        ipaddress.ip_address(word)
    except ValueError:
        return False
    return True


def _dotted(word: str) -> bool:
    """Four runs of digits with dots between, as the parser's IPv4
    patterns ask (they do not ask that each run is below 256)."""
    return re.match(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+", word) is not None


def _kind(words: list[str]) -> tuple[str, ...] | None:
    """The read-once kind a line of *words* is of, or ``None``."""
    found = next((k for k in READ_ONCE if tuple(words[: len(k)]) == k), None)
    if found == ("ip", "domain-name"):
        return ("ip", "domain", "name")
    return found


def _read_once_form(kind: tuple[str, ...], words: list[str]) -> bool:
    """Whether the line of *words* is of the form the parser looks for
    of the read-once *kind*: ``ip domain name <name>`` (or ``ip
    domain-name <name>``) and the anycast MAC with one word after their
    words; the others with a value after their words."""
    if kind == ("ip", "domain", "name"):
        return len(words) == (3 if words[1] == "domain-name" else 4)
    if kind == ("fabric", "forwarding", "anycast-gateway-mac"):
        return len(words) == 4
    return len(words) > len(kind)


def _read_once_value(kind: tuple[str, ...], words: list[str]) -> bool:
    """Whether the first line of *kind* in its form is read: the
    anycast MAC only where it is a MAC (twelve hex digits); the others
    always."""
    if kind == ("fabric", "forwarding", "anycast-gateway-mac"):
        return len(re.sub(r"[^0-9a-f]", "", words[3])) == 12
    return True


def _a_v3_user(words: list[str]) -> bool:
    """``snmp-server user <name> <group> v3 [encrypted] [auth
    <algorithm> <password>] [priv des|3des|aes [128|192|256]
    <password>]``, and nothing after it."""
    if len(words) < 5 or words[4] != "v3":
        return False
    rest = words[5:]
    if rest[:1] == ["encrypted"]:
        rest = rest[1:]
    if rest[:1] == ["auth"]:
        if len(rest) < 3 or rest[1] not in _V3_AUTH:
            return False
        rest = rest[3:]
    if rest[:1] == ["priv"]:
        if len(rest) < 3 or rest[1] not in ("des", "3des", "aes"):
            return False
        rest = rest[2:]
        if rest[0] in ("128", "192", "256") and len(rest) >= 2:
            rest = rest[1:]
        rest = rest[1:]
    return not rest


def _read_by_hand(words: list[str]) -> bool:
    """Whether the parser reads the line of *words* (in lower case),
    whichever line of its kind it is: the forms the parser reads of the
    commands it reads, typed from the IOS-XE grammar.

    * ``interface <name> ...``: every header is a record, the VXLAN
      container, or a row of its own (``interface range``).
    * ``vrf definition <name>`` and ``ip vrf <name>``, alone.
    * ``vlan <id> ...``, ``vlan configuration <id>`` alone, and ``vlan
      dot1q tag native [exclude control]``.
    * ``ip name-server ...`` and ``ntp server ...`` with a word after.
    * ``logging ... <address> ...``: a syslog host.
    * ``ip route [vrf <name>] <address> <mask> <next hop> ...``, ``ipv6
      route [vrf <name>] <prefix>/<length> <next hop> ...`` and ``ip
      default-gateway <address>``.
    * ``snmp-server host <IPv4 address> ...`` and an SNMPv3 user
      (:func:`_a_v3_user`).
    * ``ip dhcp pool <name>``, ``ip dhcp excluded-address ...`` and
      ``[no] service dhcp``.
    * ``radius server <name>`` and ``radius-server host <IPv4
      address> ...``.
    """
    if words[0] == "interface":
        return len(words) >= 2
    if words[:2] in (["vrf", "definition"], ["ip", "vrf"]):
        return len(words) == 3
    if words[0] == "vlan":
        if words[1:2] == ["configuration"]:
            return len(words) == 3 and words[2].isdigit()
        if words[1:] in (["dot1q", "tag", "native"], ["dot1q", "tag", "native", "exclude", "control"]):
            return True
        return len(words) >= 2 and words[1][:1].isdigit()
    if words[:2] in (["ip", "name-server"], ["ntp", "server"]):
        return len(words) >= 3
    if words[0] == "logging":
        return any(_an_address(word) for word in words[1:])
    if words[:2] == ["ip", "route"]:
        rest = words[4:] if words[2:3] == ["vrf"] else words[2:]
        return len(rest) >= 3 and _dotted(rest[0]) and _dotted(rest[1]) and rest[0].count(".") == 3
    if words[:2] == ["ipv6", "route"]:
        rest = words[4:] if words[2:3] == ["vrf"] else words[2:]
        return len(rest) >= 2 and re.fullmatch(r"[0-9a-f:]+/[0-9]+", rest[0]) is not None
    if words[:2] == ["ip", "default-gateway"]:
        return len(words) >= 3 and _dotted(words[2])
    if words[:2] == ["snmp-server", "host"]:
        return len(words) >= 3 and _dotted(words[2])
    if words[:2] == ["snmp-server", "user"]:
        return _a_v3_user(words)
    if words[:3] == ["ip", "dhcp", "pool"]:
        return len(words) >= 4
    if words[:3] == ["ip", "dhcp", "excluded-address"]:
        return True
    if words in (["service", "dhcp"], ["no", "service", "dhcp"]):
        return True
    if words[:2] == ["radius", "server"]:
        return len(words) >= 3
    if words[:2] == ["radius-server", "host"]:
        return len(words) >= 3 and _dotted(words[2])
    return False


def _a_user_line(words: list[str]) -> bool:
    """``username <name> [privilege <level>] secret|password [<type>]
    <value>`` or ``username <name> [privilege <level>] nopassword``:
    the line of a local user the parser reads, the first of each name
    (:func:`_unread_lines`)."""
    if len(words) < 3 or words[0] != "username":
        return False
    rest = words[2:]
    if rest[:1] == ["privilege"]:
        if len(rest) < 2 or not rest[1].isdigit():
            return False
        rest = rest[2:]
    if rest == ["nopassword"]:
        return True
    return rest[:1] in (["secret"], ["password"]) and len(rest) >= 2


#: The row that counts the lines that begin with no command word the
#: parser knows, in its two forms.
ONE_UNKNOWN = "a line in column 0 that begins with no command this parser knows (line {first})"
MANY_UNKNOWN = (
    "{count} lines in column 0 that begin with no command this parser knows "
    "(the first is line {first})"
)
_COUNTS_UNKNOWN = re.compile(r"begins? with no command this parser knows")

CONFIG = (
    "Building configuration...\n"  # 1
    "\n"
    "Current configuration : 1234 bytes\n"
    "!\n"
    "version 17.9\n"  # 5
    "service timestamps debug datetime msec\n"
    "hostname r1\n"
    "hostname r2\n"
    "!\n"
    "boot-start-marker\n"  # 10
    "boot system flash:packages.conf\n"
    "boot-end-marker\n"
    "!\n"
    "vrf definition blue\n"
    " rd 65000:1\n"  # 15
    " address-family ipv4\n"
    " exit-address-family\n"
    "!\n"
    "aaa new-model\n"
    "aaa authentication login default local\n"  # 20
    "ip domain name example.net\n"
    "ip domain name example.org\n"
    "ip name-server 192.0.2.53\n"
    "ip routing\n"
    "ip ssh version 2\n"  # 25
    "ip http server\n"
    "ip dhcp excluded-address 10.0.0.1 10.0.0.9\n"
    "ip dhcp snooping\n"
    "ip dhcp pool users\n"
    " network 10.0.0.0 255.255.255.0\n"  # 30
    "!\n"
    "no service pad\n"
    "service dhcp\n"
    "spanning-tree mode rapid-pvst\n"
    "spanning-tree extend system-id\n"  # 35
    "username admin privilege 15 secret 9 $9$fake$hashA\n"
    "username admin privilege 15 secret 9 $9$fake$hashB\n"
    "username ops algorithm-type scrypt secret 9 $9$fake$hashC\n"
    "banner motd ^C\n"
    "frobnicate in a banner\n"  # 40
    "^C\n"
    "vlan 10\n"
    " name users\n"
    "vlan internal allocation policy ascending\n"
    "vlan configuration 10\n"  # 45
    "vlan dot1q tag native\n"
    "!\n"
    "interface GigabitEthernet1/0/1\n"
    " switchport mode access\n"
    " switchport access vlan 10\n"  # 50
    "!\n"
    "ip access-list extended EDGE\n"
    " permit ip any any\n"
    "route-map RM permit 10\n"
    "ip prefix-list PL seq 5 permit 10.0.0.0/8\n"  # 55
    "ip route 0.0.0.0 0.0.0.0 192.0.2.1\n"
    "ip route vrf blue 10.1.0.0 255.255.0.0 192.0.2.2\n"
    "ipv6 route ::/0 2001:db8::1\n"
    "ip default-gateway 192.0.2.1\n"
    "logging host 192.0.2.10\n"  # 60
    "logging 192.0.2.11\n"
    "logging buffered 5000\n"
    "logging loghost.example.net\n"
    "snmp-server community fakeCommunityA RO\n"
    "snmp-server community fakeCommunityB RW\n"  # 65
    "snmp-server location lab\n"
    "snmp-server host 192.0.2.20 version 2c fakeCommunityA\n"
    "snmp-server host 2001:db8::20 version 2c fakeCommunityA\n"
    "snmp-server enable traps\n"
    "radius server rad1\n"  # 70
    " address ipv4 192.0.2.30 auth-port 1812 acct-port 1813\n"
    " key fakeRadiusKey\n"
    "radius-server host 192.0.2.31 key fakeRadiusKey\n"
    "ntp server 192.0.2.40\n"
    "ntp source Loopback0\n"  # 75
    "line con 0\n"
    " exec-timeout 5 0\n"
    "line vty 0 4\n"
    " transport input ssh\n"
    "router ospf 1\n"  # 80
    " network 10.0.0.0 0.0.0.255 area 0\n"
    "fabric forwarding anycast-gateway-mac 0000.2222.3333\n"
    "frobnicate 1\n"
    "frobnicate 2\n"
    "42 is no command\n"  # 85
    "end\n"
)

#: What CONFIG's lines in column 0 that nothing reads are, in the order
#: they come: typed by hand.  The banner is text, not lines of the
#: config, its opening line among them: no row is made of it here.
CONFIG_ROWS = [
    "service timestamps",
    "hostname",
    "boot system",
    "aaa new-model",
    "aaa authentication",
    "ip domain",
    "ip routing",
    "ip ssh",
    "ip http",
    "ip dhcp",
    "no service pad",
    "spanning-tree mode",
    "spanning-tree extend",
    "username",
    "vlan internal",
    "ip prefix-list",
    "logging",
    "snmp-server community",
    "snmp-server host",
    "snmp-server enable",
    "ntp source",
    "line con",
    "line vty",
    "router ospf",
    MANY_UNKNOWN.format(count=2, first=83),
]

#: Every row the committed IOS-XE inputs give, together: typed by hand.
COMMITTED_ROWS = {
    "aaa accounting", "aaa authentication", "aaa authorization", "aaa group",
    "aaa new-model", "aaa server", "aaa session-id",
    "app-hosting appid",
    "archive",
    "call-home",
    "clock timezone",
    "control-plane",
    "crypto", "crypto engine", "crypto logging",
    "diagnostic bootup",
    "enable secret",
    "iox",
    "ip access-list", "ip audit", "ip cef", "ip forward-protocol", "ip http",
    "ip multicast-routing", "ip pim", "ip route", "ip scp", "ip sla", "ip ssh",
    "ip tcp",
    "ipv6 ioam",
    "l2vpn evpn",
    "license accept", "license boot", "license udi",
    "line aux", "line con", "line vty",
    "lldp run",
    "logging",
    "login on-failure", "login on-success",
    "memory free",
    "mmi polling-interval", "mmi snmp-timeout",
    "multilink bundle-name",
    "netconf-yang", "netconf-yang feature",
    "no aaa authentication", "no aaa new-model", "no aaa root", "no aaa user",
    "no cdp log",
    "no errdisable detect",
    "no ip domain", "no ip http", "no ip icmp", "no ip igmp",
    "no ipv6 cef",
    "no license smart",
    "no logging",
    "no mmi auto-configure", "no mmi pvc",
    "no platform punt-keepalive",
    "no scheduler allocate",
    "no service password-encryption",
    "no snmp-server aaa", "no snmp-server contact", "no snmp-server enable",
    "no snmp-server globalenforcepriv", "no snmp-server location",
    "platform console", "platform punt-keepalive", "platform qfp",
    "privilege exec",
    "redundancy",
    "restconf",
    "router bgp", "router eigrp", "router isis", "router ospf",
    "sampler",
    "service call-home", "service password-encryption", "service timestamps",
    "snmp-server", "snmp-server aaa-user", "snmp-server chassis-id",
    "snmp-server community", "snmp-server community-map", "snmp-server context",
    "snmp-server enable", "snmp-server engineid", "snmp-server file-transfer",
    "snmp-server group", "snmp-server ifindex", "snmp-server ifmib",
    "snmp-server logging", "snmp-server manager",
    "snmp-server max-ifindex-per-module", "snmp-server mib",
    "snmp-server overload-control", "snmp-server packetsize",
    "snmp-server priority", "snmp-server protocol", "snmp-server queue-length",
    "snmp-server source-interface", "snmp-server system-shutdown",
    "snmp-server tcp-session", "snmp-server tftp-server-list",
    "snmp-server trap", "snmp-server trap-source", "snmp-server trap-timeout",
    "snmp-server traps", "snmp-server user", "snmp-server view", "snmp-server vrf",
    "spanning-tree extend", "spanning-tree mode", "spanning-tree pathcost",
    "spanning-tree vlan",
    "subscriber templating",
    "switchport access",
    "telemetry ietf",
    "transceiver type",
    "username",
    "vlan internal",
    "vtp mode", "vtp version",
}

XE_CAPTURES = [path for codec, _, path in CAPTURES if codec == "cisco_iosxe_cli"]


def _words(text: str) -> list[str]:
    return text.lower().split()


def _unread_lines(text: str) -> list[tuple[int, list[str]]]:
    """(number, words) of each line in column 0 of *text* that begins
    with a letter and that the lists above, :data:`SESSION`,
    :data:`PRINTOUT` and the detector do not account for: what nothing
    translates.  Of a kind in :data:`READ_ONCE` the first line in its
    form is the one the parser looks at, and of each local user's name
    the first line in its read form is read."""
    found = []
    once_seen: set[tuple[str, ...]] = set()
    users: set[str] = set()
    for number, line in enumerate(xe_parse.without_banner_bodies(text).splitlines(), start=1):
        if not line[:1].isalpha():
            continue
        words = _words(line)
        kind = _kind(words)
        if kind is not None:
            if kind not in once_seen and _read_once_form(kind, words):
                once_seen.add(kind)
                if _read_once_value(kind, words):
                    continue
        elif _a_user_line(words):
            # A name is the operator's, and is told apart as written.
            name = line.split()[1]
            if name not in users:
                users.add(name)
                continue
        elif (
            words[0] in SESSION
            or PRINTOUT.fullmatch(" ".join(words))
            or _read_by_hand(words)
        ):
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


def _rows_of_this_kind(tree_rows: list[str], text: str) -> list[str]:
    """The rows of *tree_rows* that the walk of the top level could
    have made: not a detector's, not a header's (``interface ...``),
    not a row of a stanza's statements or of a count (each has a ``:``
    or a ``(`` after its words, or begins with ``(``), except the row
    that counts lines with no known command."""
    elsewhere = set(detect_tier3_sections_iosxe_cli(xe_parse.without_banner_bodies(text)))
    return [
        row for row in tree_rows
        if row not in elsewhere
        and not row.startswith(("interface ", "("))
        and ":" not in row
        and ("(" not in row or _COUNTS_UNKNOWN.search(row))
    ]


def _check_every_unread_line_is_said(text: str) -> None:
    """Each line nothing translates is said by a row of its kind or
    counted in the row for lines with no known command, and each such
    row says a line nothing translates."""
    tree = get_codec("cisco_iosxe_cli").parse(text)
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
    a line read, a detector's stanza, a banner, the printout's lines, a
    line that begins with no letter and a word of a session are no row
    of this kind."""
    rows = xe_parse._rows_for_what_no_reader_takes(xe_parse.without_banner_bodies(CONFIG))
    assert rows == CONFIG_ROWS
    tree = get_codec("cisco_iosxe_cli").parse(CONFIG)
    assert tree.dropped_tier3_sections == [
        *detect_tier3_sections_iosxe_cli(xe_parse.without_banner_bodies(CONFIG)),
        *CONFIG_ROWS,
    ]
    _check_every_unread_line_is_said(CONFIG)


def test_what_the_parser_reads_is_still_read() -> None:
    """The lines CONFIG's rows leave out are read as they were: the
    first hostname and domain, the name server, the syslog hosts named
    by an address, the NTP server, the first line of a user's name, the
    VRF, the VLAN, the interface, the routes, SNMP, the RADIUS servers
    and the anycast-gateway MAC."""
    tree = get_codec("cisco_iosxe_cli").parse(CONFIG)
    assert tree.hostname == "r1"
    assert tree.source_version == "17.9"
    assert tree.domain == "example.net"
    assert tree.dns_servers == ["192.0.2.53"]
    assert tree.syslog_servers == ["192.0.2.10", "192.0.2.11"]
    assert tree.ntp_servers == ["192.0.2.40"]
    assert [u.name for u in tree.local_users] == ["admin"]
    assert [r.name for r in tree.routing_instances] == ["blue"]
    assert [v.id for v in tree.vlans] == [10]
    assert "GigabitEthernet1/0/1" in [i.name for i in tree.interfaces]
    assert sorted((r.vrf, r.destination) for r in tree.static_routes) == [
        ("", "0.0.0.0/0"), ("", "0.0.0.0/0"), ("", "::/0"), ("blue", "10.1.0.0/16"),
    ]
    assert tree.snmp is not None
    assert tree.snmp.community == "fakeCommunityA"
    assert tree.snmp.location == "lab"
    assert tree.snmp.trap_hosts == ["192.0.2.20"]
    assert [s.host for s in tree.radius_servers] == ["192.0.2.30", "192.0.2.31"]
    assert tree.anycast_gateway_mac == "00:00:22:22:33:33"


def test_a_row_shows_no_value() -> None:
    """A row is a command's words: a secret, a community, an address or
    a name that follows them is not in it, nor is any word of a line
    that begins with no command the parser knows."""
    text = (
        "hostname r1\n"
        "interface GigabitEthernet1\n no switchport\n"
        "tacacs-server key 7 fakeTacacsKey\n"
        "radius-server key 7 fakeRadiusKey\n"
        "enable secret 9 $9$fake$hashE\n"
        "username admin secret 9 $9$fake$hashA\n"
        "username admin secret 9 $9$fake$hashB\n"
        "snmp-server community fakeCommunityA RO\n"
        "snmp-server community fakeCommunityB RO\n"
        "key chain fakeChain\n"
        "sampler fakeSampler\n"
        "fakeword fakeSecret\n"
    )
    rows = get_codec("cisco_iosxe_cli").parse(text).dropped_tier3_sections
    assert "tacacs-server key" in rows
    assert "radius-server key" in rows
    assert "enable secret" in rows
    assert "username" in rows
    assert "snmp-server community" in rows
    assert "key ..." in rows
    assert "sampler" in rows
    assert ONE_UNKNOWN.format(first=13) in rows
    assert not [
        row for row in rows
        if "fake" in row.lower() or "$" in row or "admin" in row or "r1" in row
    ], rows
    _check_every_unread_line_is_said(text)


#: ``logging`` lines that name a host by its name, and one that names
#: no host: IOS-XE takes a host straight after the word.
LOGGING_BY_NAME = (
    "logging loghost.example.net\n"
    "logging collector-a\n"
    "logging host collector-b\n"
    "logging buffered 5000\n"
)


def _check_no_host_name_in_a_row(text: str) -> None:
    """No row of ``text`` shows the name of a syslog host."""
    rows = get_codec("cisco_iosxe_cli").parse(text).dropped_tier3_sections
    assert not [
        row for row in rows if "loghost" in row or "collector" in row
    ], rows


def test_a_logging_row_is_the_word_alone() -> None:
    """A ``logging`` line whose host is a name is not read as a syslog
    server (the parser reads an address), and its row is the word
    alone: the word after ``logging`` can be the host's name, which a
    row does not show.  One row for every such line."""
    tree = get_codec("cisco_iosxe_cli").parse(LOGGING_BY_NAME)
    assert tree.syslog_servers == []
    assert tree.dropped_tier3_sections == ["logging"]
    _check_no_host_name_in_a_row(LOGGING_BY_NAME)
    _check_every_unread_line_is_said(LOGGING_BY_NAME)


def test_the_check_fails_with_logging_a_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Were the word after ``logging`` shown, a host's name would be in
    a row, and the check sees it."""
    monkeypatch.setattr(xe_parse, "_FAMILIES", xe_parse._FAMILIES | {"logging"})
    with pytest.raises(AssertionError):
        _check_no_host_name_in_a_row(LOGGING_BY_NAME)


def test_a_line_read_once_is_read_once() -> None:
    """Of a hostname, a domain, an SNMP community, an anycast-gateway MAC
    and a local user's name the parser reads one line, the first: a
    second is a row, and a MAC that is no MAC is not read at all."""
    text = (
        "hostname r1\n"
        "hostname r2\n"
        "ip domain name example.net\n"
        "ip domain-name example.org\n"
        "snmp-server community fakeCommunityA RO\n"
        "snmp-server community fakeCommunityB RO\n"
        "fabric forwarding anycast-gateway-mac 0000.2222.3333\n"
        "fabric forwarding anycast-gateway-mac 0000.2222.4444\n"
        "username ops privilege 1 secret 9 $9$fake$hashA\n"
        "username ops privilege 15 secret 9 $9$fake$hashB\n"
    )
    tree = get_codec("cisco_iosxe_cli").parse(text)
    assert tree.hostname == "r1"
    assert tree.domain == "example.net"
    assert tree.snmp is not None and tree.snmp.community == "fakeCommunityA"
    assert tree.anycast_gateway_mac == "00:00:22:22:33:33"
    assert [u.name for u in tree.local_users] == ["ops"]
    assert tree.dropped_tier3_sections == [
        "hostname", "ip domain-name", "snmp-server community", "fabric forwarding", "username",
    ]
    _check_every_unread_line_is_said(text)
    bad = "fabric forwarding anycast-gateway-mac nothing\n" + text
    tree = get_codec("cisco_iosxe_cli").parse(bad)
    assert not tree.anycast_gateway_mac
    assert "fabric forwarding" in tree.dropped_tier3_sections
    _check_every_unread_line_is_said(bad)


def test_a_reader_reads_its_own_line() -> None:
    """A reader of a hostname, the release, a domain, a name server, an
    NTP server, the SNMP community and location or the anycast MAC
    takes its value from its own line.  ``\\s`` crossed the line break:
    a ``hostname`` line with no value was read with the next line's
    first word for the hostname, an ``ip domain name`` line with none
    with the next line's for the domain, and so on -- and the next line
    had no row."""
    text = (
        "hostname\n"
        "r9\n"
        "ip domain name\n"
        "example.net\n"
        "ip name-server\n"  # 5
        "192.0.2.53\n"
        "ntp server\n"
        "192.0.2.123\n"
        "snmp-server community\n"
        "fakeCommunityA\n"  # 10
        "snmp-server location\n"
        "lab\n"
        "fabric forwarding anycast-gateway-mac\n"
        "0000.2222.3333\n"
        "version\n"  # 15
        "17.9\n"
    )
    tree = get_codec("cisco_iosxe_cli").parse(text)
    assert tree.hostname == ""
    assert tree.domain == ""
    assert tree.dns_servers == []
    assert tree.ntp_servers == []
    assert tree.snmp is None
    assert not tree.anycast_gateway_mac
    assert tree.source_version != "17.9"
    assert tree.dropped_tier3_sections == [
        "hostname",
        "ip domain",
        "ip name-server",
        "ntp server",
        "snmp-server community",
        "snmp-server location",
        "fabric forwarding",
        "version",
        MANY_UNKNOWN.format(count=4, first=2),
    ]
    _check_every_unread_line_is_said(text)


def test_the_committed_inputs_give_the_rows_typed_here() -> None:
    """Over the committed IOS-XE inputs the rows of this kind are the ones
    typed here, and each input's rows say each line nothing reads."""
    assert XE_CAPTURES
    found: set[str] = set()
    for path in XE_CAPTURES:
        text = path.read_text(encoding="utf-8")
        found.update(xe_parse._rows_for_what_no_reader_takes(xe_parse.without_banner_bodies(text)))
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
    rows = xe_parse._rows_for_what_no_reader_takes(text)
    assert len(rows) == LEFT_OUT_ROWS_SHOWN + 2
    assert rows[LEFT_OUT_ROWS_SHOWN] == (
        "(100 more kinds of top-level command not read; not listed)"
    )
    assert rows[-1] == MANY_UNKNOWN.format(count=1000, first=kinds + 1)


def test_a_job_says_the_rows() -> None:
    """A job from IOS-XE says them, as every row is said, and what those
    lines hold is in no output."""
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec("cisco_nxos"), CONFIG, port_rename_map={},
    )
    assert job.rendered, job.error
    for row in CONFIG_ROWS:
        assert row in job.dropped_tier3_sections, row
    for value in ("loghost.example.net", "fakeCommunityB", "example.org", "rapid-pvst"):
        assert value not in job.rendered, value


def test_the_row_that_counts_lines_is_known_by_its_form() -> None:
    """A row of a command's words is not taken for the row that counts
    lines of no known command."""
    for row in [*CONFIG_ROWS[:-1], *COMMITTED_ROWS]:
        assert not is_no_command_row(row), row
    assert is_no_command_row(CONFIG_ROWS[-1])
    assert is_no_command_row(ONE_UNKNOWN.format(first=5))


def test_a_text_that_is_no_config_is_still_said_to_be_none() -> None:
    """Text that is no config, given as IOS-XE, has the row that counts
    its lines and nothing else, and its job is ``partial``, as it was
    before the row: the row is no sign that the text was a config.
    A line of a command the parser knows is."""
    garbage = "lorem ipsum dolor\nsit amet\n"
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec("cisco_nxos"), garbage, port_rename_map={},
    )
    assert job.dropped_tier3_sections == [MANY_UNKNOWN.format(count=2, first=1)]
    assert job.status is MigrationJobStatus.partial
    assert job.error and "recognized" in job.error.lower()
    known = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec("cisco_nxos"), "spanning-tree mode rapid-pvst\n",
        port_rename_map={},
    )
    assert known.dropped_tier3_sections == ["spanning-tree mode"]
    assert known.status is MigrationJobStatus.completed


def test_the_servers_are_still_read() -> None:
    """The DNS, NTP and syslog lines are read as they were, each syslog
    server once, and give no row; a ``logging`` line that names no
    address is a row."""
    text = (
        "ip name-server 192.0.2.53 192.0.2.54\n"
        "ip name-server vrf mgmt 192.0.2.55\n"
        "ntp server 192.0.2.123\n"
        "ntp server vrf mgmt 192.0.2.124\n"
        "logging host 192.0.2.20\n"
        "logging host 192.0.2.21 transport udp port 514\n"
        "logging 192.0.2.20\n"
        "logging trap informational\n"
    )
    tree = get_codec("cisco_iosxe_cli").parse(text)
    assert tree.dns_servers == ["192.0.2.53", "192.0.2.54", "192.0.2.55"]
    assert tree.ntp_servers == ["192.0.2.123", "192.0.2.124"]
    assert tree.syslog_servers == ["192.0.2.20", "192.0.2.21"]
    assert tree.dropped_tier3_sections == ["logging"]
    _check_every_unread_line_is_said(text)


def test_the_dhcp_lines_of_the_top_are_read() -> None:
    """``ip dhcp excluded-address`` and ``[no] service dhcp`` are read
    with the pools (``dhcp_pools.read_top``), and are no row; ``ip dhcp
    snooping`` is."""
    text = (
        "ip dhcp excluded-address 10.0.0.1 10.0.0.9\n"
        "no service dhcp\n"
        "service dhcp\n"
        "ip dhcp snooping\n"
    )
    assert xe_parse._rows_for_what_no_reader_takes(text) == ["ip dhcp"]
    _check_every_unread_line_is_said(text)


def test_the_check_fails_without_the_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the rows taken out, the check fails."""
    monkeypatch.setattr(xe_parse, "_rows_for_what_no_reader_takes", lambda raw: [])
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_for_a_reader_that_takes_every_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reader said to take every line leaves lines nothing reads with
    no row: the check fails."""
    monkeypatch.setattr(xe_parse, "_TOP_LEVEL_READERS", (re.compile(r".*").match,))
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


def test_the_check_fails_for_rows_of_lines_that_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no reader listed, the lines read have rows: the check fails."""
    monkeypatch.setattr(xe_parse, "_TOP_LEVEL_READERS", ())
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)


@pytest.mark.parametrize(
    ("reader", "text"),
    [
        pytest.param(
            xe_parse._HOSTNAME_RE.match, "hostname r1\nhostname r2\n", id="every-hostname",
        ),
        pytest.param(
            xe_parse._TOP_DOMAIN_RE.match,
            "ip domain name example.net\nip domain name example.org\n",
            id="every-domain",
        ),
        pytest.param(
            xe_parse._SNMP_COMMUNITY_RE.match,
            "snmp-server community fakeCommunityA RO\nsnmp-server community fakeCommunityB RO\n",
            id="every-community",
        ),
        pytest.param(
            re.compile(r"logging\b").match,
            "logging 192.0.2.10\nlogging buffered 5000\n",
            id="every-logging-line",
        ),
        pytest.param(
            re.compile(r"username\b").match,
            "username ops secret 9 $9$fake$hashA\nusername ops secret 9 $9$fake$hashB\n",
            id="every-line-of-a-name",
        ),
    ],
)
def test_the_check_fails_for_a_reader_of_lines_the_parse_does_not_read(
    monkeypatch: pytest.MonkeyPatch, reader: object, text: str,
) -> None:
    """Were every line of a kind taken -- a second hostname, a second
    domain, a second community, a ``logging`` line that names no host,
    a second line of a user's name -- nothing would say the one the
    parse does not read, and the check sees it."""
    if "username" in text:
        monkeypatch.setattr(xe_parse, "_LOCAL_USER_RE", re.compile(r"(?!)"))
    monkeypatch.setattr(
        xe_parse, "_TOP_LEVEL_READERS", (*xe_parse._TOP_LEVEL_READERS, reader),
    )
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(text)


def test_the_check_fails_with_the_printout_read_as_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the printout's lines not taken, ``Building configuration...``
    is counted as a line of no known command, which the check does not
    allow."""
    monkeypatch.setattr(xe_parse, "_PRINTOUT_RE", re.compile(r"(?!)"))
    with pytest.raises(AssertionError):
        _check_every_unread_line_is_said(CONFIG)
