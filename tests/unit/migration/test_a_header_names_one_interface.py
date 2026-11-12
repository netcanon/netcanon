"""An NX-OS or EOS interface header names one interface, or none.

Both platforms take a type and its number written apart where a name
goes (``interface ethernet 1/2``, ``interface Ethernet 1``) and print
them together; both take a range or a list there too (``interface
Ethernet1/1-4``, ``interface Ethernet1,3``), which configures every
interface it names and names no ONE of them.  The two parsers read a
header a word at a time, and each got both wrong in its own way:

* NX-OS took the first word for the name.  ``interface ethernet 1/1``
  was an interface called ``ethernet``, two such stanzas one record,
  and ``interface port-channel 1`` and ``interface port-channel 2`` one
  port-channel; a range was an interface named for the range, and
  ``interface breakout module 1 port 49-52 map 10g-4x`` one called
  ``breakout`` -- on every target, in jobs that said ``completed``.
* EOS matched a header of one word only.  A header of two opened no
  stanza: the interface, its address and its VLANs were in no record
  and no row, and nothing said so.  A range was an interface of that
  name.

Now a header is read for the one interface it names
(``_helpers.one_interface_named``): one word, or a type and its number,
joined as IOS-XE and IOS XR join them (``spaced_port_name``).  A
header that names none -- a range, a list, a keyword, words that are
not one name -- has its stanza taken out before any reader sees it,
and its header line is a section row of ``dropped_tier3_sections``
(``without_stanzas_of_no_one_interface``).

The oracle for a spaced header is the parser's own reading of the
header written together: every committed NX-OS and EOS input with its
headers spaced parses to the tree of the input, and a spaced text and
its joined twin make the same job onto every public codec.  Each check
is handed the defect it is for, and has to fail.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs._helpers import (
    keyword_stanza_rows,
    one_interface_named,
    without_stanzas_of_no_one_interface,
)
from netcanon.migration.codecs.arista_eos import parse as eos_parse
from netcanon.migration.codecs.cisco_nxos import parse as nxos_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_vlan_members_reach_the_output import CAPTURES

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()
SOURCES = ("arista_eos", "cisco_nxos")


@functools.cache
def _plan(source: str, text: str, target: str) -> MigrationJob:
    """*text* onto *target*, as the plan endpoints run it."""
    return run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map={},
    )


#: A header whose name is a type and then its number, one word.
_JOINED_HEADER = re.compile(
    r"^(interface[ \t]+)([A-Za-z][A-Za-z-]*[A-Za-z])(\d[^ \t\r\n]*)[ \t]*$", re.MULTILINE,
)


def _spaced(text: str) -> tuple[str, int]:
    """*text* with every header that names a type and its number in one
    word written with a space between them, and how many there were."""
    return _JOINED_HEADER.subn(r"\1\2 \3", text)


def _joined(text: str) -> str:
    """*text* with every spaced header written in one word, as the
    platform prints it."""
    return re.sub(
        r"^(interface[ \t]+)([A-Za-z][A-Za-z-]*[A-Za-z])[ \t]+(\d[^ \t\r\n]*)[ \t]*$",
        r"\1\2\3", text, flags=re.MULTILINE,
    )


def _holder(tree: CanonicalIntent, ip: str) -> list[str]:
    """The names of the interfaces of *tree* that hold address *ip*."""
    return [
        iface.name for iface in tree.interfaces
        if any(address.ip == ip for address in iface.ipv4_addresses)
    ]


# ---------------------------------------------------------------------------
# The reading of one header
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "name"),
    [
        ("interface Ethernet1/1", "Ethernet1/1"),
        ("interface ethernet 1/1", "ethernet1/1"),
        ("interface  Ethernet 1/1  ", "Ethernet1/1"),
        ("interface\tEthernet\t1", "Ethernet1"),
        ("interface Port-Channel10", "Port-Channel10"),
        ("interface port-channel 10", "port-channel10"),
        ("interface san-port-channel 3", "san-port-channel3"),
        ("interface Ethernet1/1.100", "Ethernet1/1.100"),
        ("interface Ethernet 1/1.100", "Ethernet1/1.100"),
        ("interface Vlan 10", "Vlan10"),
        ("interface mgmt0", "mgmt0"),
        ("Interface Loopback 0", "Loopback0"),
        # The vendors' own examples: Cisco's Nexus 9000 interfaces
        # guide (a port, a range, a list) and Arista's manual.
        ("interface ethernet 2/1", "ethernet2/1"),
        ("interface ethernet 2/29-30", ""),
        ("interface ethernet 2/29, ethernet 2/33, ethernet 2/35", ""),
        ("interface ethernet 1", "ethernet1"),
        ("interface ethernet 1 - 4", ""),
        ("interface ethernet 4/1,4/3,4/5", ""),
        # A range or a list names no one interface.
        ("interface Ethernet1/1-4", ""),
        ("interface ethernet 1/1-4", ""),
        ("interface Ethernet1/1 - 4", ""),
        ("interface Ethernet1/1 -4", ""),
        ("interface Ethernet1-4", ""),
        ("interface Ethernet1,3", ""),
        ("interface Ethernet1/1,Ethernet1/3", ""),
        ("interface Ethernet1, Ethernet3", ""),
        ("interface Vlan10-20", ""),
        # A hyphen that a letter follows is in a name: another vendor's
        # name, written as it is, is read back as that name.
        ("interface ether1-gateway", "ether1-gateway"),
        ("interface VLAN10-guest", "VLAN10-guest"),
        ("interface port1-", "port1-"),
        # Nor does a keyword.
        ("interface breakout module 1 port 49-52 map 10g-4x", ""),
        ("interface range Ethernet1/1 - 4", ""),
        ("interface preconfigure Ethernet1/1", ""),
        ("interface breakout", ""),
        # Nor two words that are not one name, nor more than a name has.
        ("interface Ethernet1/1 2", ""),
        ("interface Ethernet1/1 description", ""),
        ("interface ethernet 1 / 1", ""),
        ("interface", ""),
    ],
)
def test_the_one_interface_a_header_names(header: str, name: str) -> None:
    assert one_interface_named(header) == name


_RANGES = (
    "hostname sw1\n"
    "interface Ethernet1/1\n"
    "  description kept\n"
    "interface Ethernet1/5-8\n"
    "  description held-as-a-range\n"
    "\n"
    "\tswitchport access vlan 30\n"
    "interface Ethernet1/9, Ethernet1/11\n"
    "  description held-as-a-list\n"
    "interface Ethernet1/5-8\n"
    "  description again\n"
    "interface breakout module 1 port 49-52 map 10g-4x\n"
    "interface ethernet 1/2\n"
    "  description kept-too\n"
)

_RANGE_ROWS = [
    "interface Ethernet1/5-8",
    "interface Ethernet1/9, Ethernet1/11",
    "interface breakout module 1 port 49-52 map 10g-4x",
]


class TestTheStanzasTakenOut:
    def test_each_stanza_is_taken_out_whole(self) -> None:
        """A stanza ends at the next line that is not indented: a line
        that begins with a tab is of the body, and so is what follows
        an empty line.  A header met twice is one row."""
        text, headers = without_stanzas_of_no_one_interface(_RANGES)
        assert headers == _RANGE_ROWS
        assert text == (
            "hostname sw1\n"
            "interface Ethernet1/1\n"
            "  description kept\n"
            "interface ethernet 1/2\n"
            "  description kept-too\n"
        )

    def test_a_text_with_none_comes_back_itself(self) -> None:
        text = "hostname sw1\ninterface ethernet 1/1\n  description d\n"
        assert without_stanzas_of_no_one_interface(text)[0] is text
        assert without_stanzas_of_no_one_interface(text)[1] == []

    def test_line_endings_are_kept(self) -> None:
        text, headers = without_stanzas_of_no_one_interface(_RANGES.replace("\n", "\r\n"))
        assert headers == _RANGE_ROWS
        assert "\n" not in text.replace("\r\n", "")

    def test_each_row_is_a_section(self) -> None:
        """A range, a list or a breakout line is in force where it was
        typed and is not translated: its row is the header as written,
        not a left-out row."""
        rows = keyword_stanza_rows(_RANGE_ROWS)
        assert rows == _RANGE_ROWS
        assert not [row for row in rows if is_left_out_row(row)]


# ---------------------------------------------------------------------------
# The two parsers
# ---------------------------------------------------------------------------

_NXOS = """!Command: show running-config
version 9.3(8) Bios:version 05.45
hostname n9k
feature lacp
feature interface-vlan

interface ethernet 1/1
  description first
  no switchport
  ip address 10.11.0.1/24

interface ethernet 1/2
  description second
  no switchport
  ip address 10.12.0.1/24

interface port-channel 1
  description pc-one
  switchport mode trunk
  switchport trunk allowed vlan 10

interface port-channel 2
  description pc-two
  switchport mode trunk
  switchport trunk allowed vlan 20

interface ethernet 1/3
  channel-group 1 mode active

interface ethernet 1/4
  channel-group 2 mode active

interface loopback 0
  ip address 10.255.0.1/32
"""

_NXOS_NAMES = [
    "ethernet1/1", "ethernet1/2", "port-channel1", "port-channel2",
    "ethernet1/3", "ethernet1/4", "loopback0",
]

_EOS = """! device: eos1 (DCS-7050SX3-48YC8, EOS-4.28.3M)
hostname eos1
!
interface Ethernet 1
   description first
   no switchport
   ip address 10.11.0.1/24
!
interface Ethernet 2
   description second
   no switchport
   ip address 10.12.0.1/24
!
interface Port-Channel 10
   description pc-ten
   switchport mode trunk
   switchport trunk allowed vlan 10
!
interface Ethernet 3
   channel-group 10 mode active
!
interface Loopback 0
   ip address 10.255.0.1/32
!
end
"""

_EOS_NAMES = ["Ethernet1", "Ethernet2", "Port-Channel10", "Ethernet3", "Loopback0"]

_TEXTS = {"cisco_nxos": _NXOS, "arista_eos": _EOS}
_NAMES = {"cisco_nxos": _NXOS_NAMES, "arista_eos": _EOS_NAMES}
_LAGS = {
    "cisco_nxos": [("port-channel1", ["ethernet1/3"]), ("port-channel2", ["ethernet1/4"])],
    "arista_eos": [("Port-Channel10", ["Ethernet3"])],
}

#: A range, a list and (on NX-OS) a breakout line, in each grammar,
#: beside an interface the text states as it is printed.
_WITH_RANGES = {
    "cisco_nxos": (
        "hostname n9k\nfeature lacp\n\n"
        "interface Ethernet1/5-8\n  description held-as-a-range\n  channel-group 5 mode active\n\n"
        "interface Ethernet1/9,Ethernet1/11\n  description held-as-a-list\n  ip address 10.9.0.1/24\n\n"
        "interface breakout module 1 port 49-52 map 10g-4x\n\n"
        "interface Ethernet1/1\n  no switchport\n  ip address 10.1.0.1/24\n"
    ),
    "arista_eos": (
        "hostname eos1\n!\n"
        "interface Ethernet5-8\n   description held-as-a-range\n   channel-group 5 mode active\n!\n"
        "interface Ethernet9,11\n   description held-as-a-list\n   no switchport\n   ip address 10.9.0.1/24\n!\n"
        "interface Ethernet1\n   no switchport\n   ip address 10.1.0.1/24\n!\nend\n"
    ),
}

_WITH_RANGES_ROWS = {
    "cisco_nxos": [
        "interface Ethernet1/5-8", "interface Ethernet1/9,Ethernet1/11",
        "interface breakout module 1 port 49-52 map 10g-4x",
    ],
    "arista_eos": ["interface Ethernet5-8", "interface Ethernet9,11"],
}

_WITH_RANGES_NAMES = {"cisco_nxos": ["Ethernet1/1"], "arista_eos": ["Ethernet1"]}


def _check_reads_each_spaced_header(source: str) -> None:
    """Each spaced header of the text is one interface, under the name
    its two words spell, with its own address; each port-channel is a
    LAG of its own member."""
    tree = get_codec(source).parse(_TEXTS[source])
    assert [iface.name for iface in tree.interfaces] == _NAMES[source], source
    assert [(lag.name, lag.members) for lag in tree.lags] == _LAGS[source], source
    first = _NAMES[source][0]
    second = _NAMES[source][1]
    assert _holder(tree, "10.11.0.1") == [first]
    assert _holder(tree, "10.12.0.1") == [second]
    assert _holder(tree, "10.255.0.1") == [_NAMES[source][-1]]


def _check_a_range_is_no_interface(source: str) -> None:
    """A range, a list or a breakout line makes no record, its body is
    in none, and its header is a section row."""
    tree = get_codec(source).parse(_WITH_RANGES[source])
    assert [iface.name for iface in tree.interfaces] == _WITH_RANGES_NAMES[source], source
    assert tree.lags == [], source
    assert _holder(tree, "10.9.0.1") == [], source
    assert "held-as-a" not in tree.model_dump_json(), source
    rows = [row for row in tree.dropped_tier3_sections if row.startswith("interface")]
    assert rows == _WITH_RANGES_ROWS[source], source


@pytest.mark.parametrize("source", SOURCES)
class TestTheParsers:
    def test_each_spaced_header_is_one_interface(self, source: str) -> None:
        _check_reads_each_spaced_header(source)

    def test_a_range_is_no_interface(self, source: str) -> None:
        _check_a_range_is_no_interface(source)

    def test_a_spaced_text_is_its_joined_twin(self, source: str) -> None:
        text = _TEXTS[source]
        joined = _joined(text)
        assert joined != text and _spaced(joined)[0] == text
        assert get_codec(source).parse(text) == get_codec(source).parse(joined)


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("target", PUBLIC)
def test_the_job_is_the_joined_texts(source: str, target: str) -> None:
    """Onto every public codec, a text whose headers are spaced makes
    the job its joined twin makes."""
    spaced = _plan(source, _TEXTS[source], target)
    joined = _plan(source, _joined(_TEXTS[source]), target)
    assert spaced.rendered and spaced.rendered == joined.rendered, (source, target)
    assert (spaced.status, spaced.warnings, spaced.dropped_tier3_sections) == (
        joined.status, joined.warnings, joined.dropped_tier3_sections,
    ), (source, target)


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("target", PUBLIC)
def test_no_output_has_the_range(source: str, target: str) -> None:
    """Onto every public codec the job says each range as a section
    and writes nothing of its body, and no interface of the output is
    named for it."""
    job = _plan(source, _WITH_RANGES[source], target)
    assert job.rendered, (source, target, job.error)
    for row in _WITH_RANGES_ROWS[source]:
        assert row in job.dropped_tier3_sections, (source, target, row)
    assert "held-as-a" not in job.rendered
    back = get_codec(target).parse(job.rendered)
    assert not [
        iface.name for iface in back.interfaces
        if "5-8" in iface.name or "," in iface.name or "breakout" in iface.name.lower()
    ]
    assert _holder(back, "10.9.0.1") == []
    # The interface beside them is there, by its address, or listed.
    assert len(_holder(back, "10.1.0.1")) == 1 or _WITH_RANGES_NAMES[source][0] in job.unresolved_ports


def test_an_eos_pool_is_on_the_spaced_interface() -> None:
    """The DHCP reader finds the interface that serves a subnet by the
    name the interface reader gives it."""
    text = (
        "hostname sw1\n!\n"
        "dhcp server\n   subnet 192.168.10.0/24\n      range 192.168.10.100 192.168.10.200\n!\n"
        "interface Ethernet 1\n   no switchport\n   ip address 192.168.10.1/24\n   dhcp server ipv4\n!\n"
    )
    tree = get_codec("arista_eos").parse(text)
    assert [(pool.interface, pool.network) for pool in tree.dhcp_servers] == [
        ("Ethernet1", "192.168.10.0/24"),
    ]


# ---------------------------------------------------------------------------
# The committed inputs, with their headers spaced
# ---------------------------------------------------------------------------

_INPUTS = [(codec, path) for codec, _rel, path in CAPTURES if codec in SOURCES]


def test_there_are_inputs_of_both() -> None:
    assert {codec for codec, _path in _INPUTS} == set(SOURCES)


@pytest.mark.parametrize(("source", "path"), _INPUTS, ids=[f"{c}-{i}" for i, (c, _p) in enumerate(_INPUTS)])
def test_an_input_with_its_headers_spaced_is_the_input(source: str, path) -> None:
    """Every header of every committed NX-OS and EOS input is printed in
    one word; written apart, each is read as the same interface, and
    the tree is the input's."""
    text = Path(path).read_text(encoding="utf-8")
    spaced, count = _spaced(text)
    assert count > 0
    assert get_codec(source).parse(spaced) == get_codec(source).parse(text)


# ---------------------------------------------------------------------------
# Each check, handed the defect it is for
# ---------------------------------------------------------------------------

_MODULES = {"cisco_nxos": nxos_parse, "arista_eos": eos_parse}


@pytest.mark.parametrize("source", SOURCES)
def test_the_check_sees_a_header_read_a_word_at_a_time(
    source: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_MODULES[source], "spaced_port_name", lambda first, _second: first)
    with pytest.raises(AssertionError):
        _check_reads_each_spaced_header(source)


@pytest.mark.parametrize("source", SOURCES)
def test_the_check_sees_a_range_read_as_a_name(source: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _MODULES[source], "without_stanzas_of_no_one_interface", lambda raw: (raw, []),
    )
    with pytest.raises(AssertionError):
        _check_a_range_is_no_interface(source)


@pytest.mark.parametrize("source", SOURCES)
def test_the_spaced_input_check_sees_a_word_at_a_time(
    source: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check over the committed inputs fails for a parser that
    reads a spaced header a word at a time, on the first input of
    each."""
    path = next(path for codec, path in _INPUTS if codec == source)
    text = Path(path).read_text(encoding="utf-8")
    monkeypatch.setattr(_MODULES[source], "spaced_port_name", lambda first, _second: first)
    assert get_codec(source).parse(_spaced(text)[0]) != get_codec(source).parse(text)
