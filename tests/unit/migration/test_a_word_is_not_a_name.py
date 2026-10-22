"""A word is not a name.

A field that holds a port name is given a port name or nothing, and an
interface record is made only for a name the config configures
something under.  Four parsers broke one half of that or the other, in
the five forms below, and each put a line into the output that no
device would take as meant:

* IOS XR ``interface preconfigure TenGigE0/0/0/12`` -- configuration
  the router holds for an interface it does not have -- made an
  interface called ``preconfigure``, written into every target's
  output.
* IOS-XE and IOS XR ``interface ethernet 1/11`` made an interface
  called ``ethernet``; two such stanzas made one name.
* IOS-XE ``ip route 0.0.0.0 0.0.0.0 loopback 66 100`` was a route out
  an interface called ``loopback`` at distance 66.
* OPNsense ``<dhcpd><lan>`` put the ZONE's name in a DHCP pool's
  interface: Junos bound a DHCP server to ``interface lan``.
* Junos ``set interfaces irb unit 100 ...`` made an empty interface
  ``irb`` beside ``irb.100``, which no target has a name for.

One word is still where a name goes, and is pinned here as it stands:
IOS-XE ``ip route <prefix> <mask> dhcp`` keeps the keyword in the
route's interface.  The canonical route has no way to say "the next
hop comes from DHCP", and kept there the line is written back to
IOS-XE as it was.

Each is read here from the OUTPUT, not from the tree alone: a small
config goes through the plan path the API uses
(``run_plan_with_checked_names`` with an empty port map) onto every
public codec, and the rendered text is read as text and with the
target's own parser.  Where a target cannot say something the pin is a
named set compared for equality with what is measured, so that a
target that comes to say it fails here until its name is taken out.
The committed captures that carry each form are read by path.
"""

from __future__ import annotations

import functools
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from netcanon.migration._tier3_detection import LEFT_OUT_ROWS_SHOWN, is_left_out_row
from netcanon.migration.codecs._helpers import (
    NOT_AN_INTERFACE_TYPE,
    keyword_stanza_rows,
    spaced_port_name,
    without_keyword_stanzas,
)
from netcanon.migration.codecs.juniper_junos import parse as junos_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
PUBLIC = list_public_codecs()


@functools.cache
def _plan(source: str, text: str, target: str) -> MigrationJob:
    """*text* onto *target*, as the plan endpoints run it."""
    return run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map={},
    )


def _job(source: str, text: str, target: str) -> MigrationJob:
    """The same, for a text that has something to render."""
    job = _plan(source, text, target)
    assert job.rendered, f"{source} -> {target}: {job.error}"
    return job


def _capture(rel: str) -> str:
    return (FIXTURES / rel).read_text(encoding="utf-8")


def _lines_with(text: str, word: str) -> list[str]:
    """The lines of *text* in which *word* stands as a word of its own:
    not inside a longer name (``irb.100``, ``interface-range``)."""
    alone = re.compile(r"(?<![\w./:-])" + re.escape(word) + r"(?![\w./:-])")
    return [line.strip() for line in text.splitlines() if alone.search(line)]


def _listed(job: MigrationJob) -> list[str]:
    """Every name a job says something about."""
    return [
        *job.port_renames, *job.port_drops, *job.untranslated_ports, *job.unresolved_ports,
        *(name for names in job.fused_ports.values() for name in names),
    ]


def _holder(tree, ip: str) -> list[str]:
    """The names of the interfaces of *tree* that hold address *ip*."""
    return [
        iface.name for iface in tree.interfaces
        if any(address.ip == ip for address in iface.ipv4_addresses)
    ]


def _own_output_read_back(codec_name: str, text: str):
    """The codec's own render of *text*, parsed again."""
    codec = get_codec(codec_name)
    return codec.parse(codec.render(codec.parse(text)))


# ---------------------------------------------------------------------------
# 1. IOS XR: an interface the router does not have
# ---------------------------------------------------------------------------

_XR = """!! IOS XR Configuration 7.5.2
hostname xr1
interface Loopback 0
 ipv4 address 10.255.0.1 255.255.255.255
!
interface Bundle-Ether 7
 description core
!
interface GigabitEthernet0/0/0/12
 description in-service
 ipv4 address 10.12.0.1 255.255.255.0
!
interface GigabitEthernet0/0/0/13
 bundle id 7 mode active
!
interface preconfigure TenGigE0/0/0/12
 description held-for-a-line-card
 ipv4 address 198.51.100.77 255.255.255.0
 bundle id 7 mode active
!
interface preconfigure TenGigE0/0/0/12.300
 ipv4 address 198.51.100.78 255.255.255.0
 encapsulation dot1q 300
!
router static
 address-family ipv4 unicast
  0.0.0.0/0 10.12.0.254
 !
!
end
"""


def _held(name: str) -> str:
    """The row for an ``interface preconfigure <name>`` stanza: a
    left-out row, which shows the stanza's path and no word of its
    body."""
    return f"preconfigure: interface {name} (held for an interface the source does not have; not translated)"


#: What a job's list says of the two stanzas the router holds and does
#: not run, and all it says.
_HELD = [_held("TenGigE0/0/0/12"), _held("TenGigE0/0/0/12.300")]

#: A text that is nothing but a stanza the router holds.
_ALL_HELD = "interface preconfigure TenGigE0/0/0/1\n shutdown\n!\n"

_PA3 = "real/cisco_iosxr/iosxr_design_cst_pa3_xr752.cfg"


class TestAnInterfaceTheRouterDoesNotHave:
    def test_it_makes_no_record_binds_nothing(self) -> None:
        """Neither the keyword nor the port it names is an interface,
        and nothing in the stanza is read: no member of the bundle, no
        VLAN from its sub-interface, no address."""
        tree = get_codec("cisco_iosxr").parse(_XR)
        assert [iface.name for iface in tree.interfaces] == [
            "Loopback0", "Bundle-Ether7", "GigabitEthernet0/0/0/12", "GigabitEthernet0/0/0/13",
        ]
        assert [(lag.name, lag.members) for lag in tree.lags] == [
            ("Bundle-Ether7", ["GigabitEthernet0/0/0/13"]),
        ]
        assert tree.vlans == []
        assert "198.51.100." not in tree.model_dump_json()
        assert tree.dropped_tier3_sections == _HELD

    @pytest.mark.parametrize("target", PUBLIC)
    def test_no_output_names_it(self, target: str) -> None:
        job = _job("cisco_iosxr", _XR, target)
        assert _lines_with(job.rendered, "preconfigure") == []
        assert "198.51.100." not in job.rendered
        assert "held-for-a-line-card" not in job.rendered
        back = get_codec(target).parse(job.rendered)
        assert not [
            iface.name for iface in back.interfaces
            if "preconfigure" in iface.name.lower() or "tengig" in iface.name.lower()
        ]
        # The port in service is there, by its address, once.
        assert len(_holder(back, "10.12.0.1")) == 1
        assert not [
            name for name in _listed(job)
            if "preconfigure" in name.lower() or "tengig" in name.lower()
        ]

    @pytest.mark.parametrize("target", PUBLIC)
    def test_the_job_says_what_was_left_out(self, target: str) -> None:
        """One row a stanza, of the kind every statement a device holds
        and does not run is given: the stanza's path, and no word of
        its body."""
        job = _job("cisco_iosxr", _XR, target)
        rows = [row for row in job.dropped_tier3_sections if "preconfigure" in row]
        assert rows == _HELD
        assert all(is_left_out_row(row) for row in rows)
        assert not [
            row for row in job.dropped_tier3_sections
            if "held-for" in row or "198.51.100" in row
        ]

    def test_the_capture_that_has_one(self) -> None:
        text = _capture(_PA3)
        assert "\ninterface preconfigure TenGigE0/0/0/12\n" in text.replace("\r\n", "\n")
        tree = get_codec("cisco_iosxr").parse(text)
        names = [iface.name for iface in tree.interfaces]
        assert "preconfigure" not in names and "TenGigE0/0/0/12" not in names
        assert names.count("GigabitEthernet0/0/0/12") == 1
        for target in PUBLIC:
            job = _job("cisco_iosxr", text, target)
            assert _lines_with(job.rendered, "preconfigure") == [], target
            assert [row for row in job.dropped_tier3_sections if "preconfigure" in row] == [
                _held("TenGigE0/0/0/12"),
            ], target
            assert "preconfigure" not in _listed(job), target

    def test_its_own_output_gains_no_interface(self) -> None:
        """IOS XR onto IOS XR: the interfaces of the output are the
        interfaces the source has, and neither the keyword nor the
        port the stanza names is one of them."""
        text = _capture(_PA3)
        tree = get_codec("cisco_iosxr").parse(text)
        rendered = _job("cisco_iosxr", text, "cisco_iosxr").rendered
        written = re.findall(r"(?m)^interface (\S+)", rendered)
        assert sorted(written) == sorted(iface.name for iface in tree.interfaces)
        assert "preconfigure" not in written and "TenGigE0/0/0/12" not in written

    def test_its_own_output_reads_back_right(self) -> None:
        """What the text should give, written out: four interfaces,
        one bundle of one member, the address in service on its port,
        and nothing the held stanzas state."""
        back = _own_output_read_back("cisco_iosxr", _XR)
        assert sorted(iface.name for iface in back.interfaces) == [
            "Bundle-Ether7", "GigabitEthernet0/0/0/12", "GigabitEthernet0/0/0/13", "Loopback0",
        ]
        assert [(lag.name, lag.members) for lag in back.lags] == [
            ("Bundle-Ether7", ["GigabitEthernet0/0/0/13"]),
        ]
        assert _holder(back, "10.12.0.1") == ["GigabitEthernet0/0/0/12"]
        assert _holder(back, "10.255.0.1") == ["Loopback0"]
        assert back.vlans == [] and "198.51.100." not in back.model_dump_json()
        # The output holds no such stanza, so it has no row for one.
        assert back.dropped_tier3_sections == []

    @pytest.mark.parametrize("target", PUBLIC)
    def test_all_held_is_not_completed(self, target: str) -> None:
        """Nothing in such a text is in force, so nothing of it was
        translated: the row is not a sign that a config was read."""
        job = _plan("cisco_iosxr", _ALL_HELD, target)
        assert job.dropped_tier3_sections == [_held("TenGigE0/0/0/1")]
        assert job.status.value == "partial"
        assert job.error is not None and job.error.startswith("No source constructs were recognized")
        assert "statements the source held and did not run" in job.error

    def test_beside_a_line_in_force(self) -> None:
        job = _plan("cisco_iosxr", "hostname xr1\n" + _ALL_HELD, "arista_eos")
        assert job.dropped_tier3_sections == [_held("TenGigE0/0/0/1")]
        assert job.status.value == "completed"

    def test_the_rows_are_bounded(self) -> None:
        """The list is in every answer: past the bound one row counts
        the stanzas that are not listed."""
        more = 50
        text = "hostname xr1\n" + "".join(
            f"interface preconfigure TenGigE0/0/0/{number}\n shutdown\n!\n"
            for number in range(LEFT_OUT_ROWS_SHOWN + more)
        )
        tree = get_codec("cisco_iosxr").parse(text)
        rows = tree.dropped_tier3_sections
        assert len(rows) == LEFT_OUT_ROWS_SHOWN + 1
        assert rows[0] == _held("TenGigE0/0/0/0")
        assert rows[-1] == f"preconfigure: ... ({more} more statements left out; not listed)"
        assert all(is_left_out_row(row) for row in rows) and not tree.interfaces

    def test_the_keyword_in_another_letter_case(self) -> None:
        """``interface`` is read in any letter case, and so is the
        keyword after it."""
        text = _XR.replace(
            "interface preconfigure TenGigE0/0/0/12\n", "Interface PRECONFIGURE TenGigE0/0/0/12\n",
        )
        assert "Interface PRECONFIGURE" in text
        tree = get_codec("cisco_iosxr").parse(text)
        assert [iface.name for iface in tree.interfaces] == [
            "Loopback0", "Bundle-Ether7", "GigabitEthernet0/0/0/12", "GigabitEthernet0/0/0/13",
        ]
        assert [(lag.name, lag.members) for lag in tree.lags] == [
            ("Bundle-Ether7", ["GigabitEthernet0/0/0/13"]),
        ]
        assert tree.dropped_tier3_sections == _HELD


# ---------------------------------------------------------------------------
# 2. A type and its number written apart
# ---------------------------------------------------------------------------

_XE_HEADERS = """hostname xe1
!
interface ethernet 1/11
 description first
 ip address 10.11.0.1 255.255.255.0
!
interface ethernet 1/12
 description second
 ip address 10.12.0.1 255.255.255.0
!
interface Cable 1/2/3:4
 description coax
!
interface Port-channel 5
 description uplink
!
interface GigabitEthernet 1/0/3
 channel-group 5 mode active
!
interface Vlan 20
 ip address 10.20.0.1 255.255.255.0
!
interface Serial0/0/0.100 point-to-point
 ip address 10.30.0.1 255.255.255.252
!
end
"""

#: The seven interfaces that text states, one for each header.
_XE_HEADER_NAMES = [
    "Cable1/2/3:4", "GigabitEthernet1/0/3", "Port-channel5", "Serial0/0/0.100",
    "Vlan20", "ethernet1/11", "ethernet1/12",
]

#: The targets on which a port of module 1 has no name: it is dropped,
#: and the job lists it.
_NO_NAME_FOR_MODULE_ONE = {"aruba_aoss"}

_SPACED = "real/cisco_iosxe/batfish_cisco_interface.txt"


class TestATypeAndItsNumberWrittenApart:
    @pytest.mark.parametrize(
        ("first", "second", "name"),
        [
            ("ethernet", "1/11", "ethernet1/11"),
            ("Cable", "1/2/3:4", "Cable1/2/3:4"),
            ("Bundle-Ether", "10", "Bundle-Ether10"),
            ("Dot11Radio", "0", "Dot11Radio0"),
            ("loopback", "66", "loopback66"),
            # A whole name, and the keyword after it.
            ("Serial0/0/0.100", "point-to-point", "Serial0/0/0.100"),
            ("GigabitEthernet0/0/0/1.100", "l2transport", "GigabitEthernet0/0/0/1.100"),
            # A whole name is whole whatever follows it.
            ("Loopback99", "150", "Loopback99"),
            ("Null0", "250", "Null0"),
            # A type with no number after it is left as it is.
            ("Loopback", None, "Loopback"),
            ("Loopback", "description", "Loopback"),
        ],
    )
    def test_when_two_words_are_one_name(self, first: str, second: str | None, name: str) -> None:
        assert spaced_port_name(first, second) == name

    def test_the_keywords(self) -> None:
        assert sorted(NOT_AN_INTERFACE_TYPE) == ["breakout", "preconfigure", "range"]

    @pytest.mark.parametrize("keyword", sorted(NOT_AN_INTERFACE_TYPE))
    def test_a_keyword_is_never_joined(self, keyword: str) -> None:
        assert spaced_port_name(keyword, "1/0/1") == keyword
        assert spaced_port_name(keyword.upper(), "0/0/0/12") == keyword.upper()

    def test_iosxe_reads_each_header_as_one_name(self) -> None:
        tree = get_codec("cisco_iosxe_cli").parse(_XE_HEADERS)
        assert sorted(iface.name for iface in tree.interfaces) == _XE_HEADER_NAMES
        assert [(lag.name, lag.members) for lag in tree.lags] == [
            ("Port-channel5", ["GigabitEthernet1/0/3"]),
        ]
        assert _holder(tree, "10.11.0.1") == ["ethernet1/11"]
        assert _holder(tree, "10.12.0.1") == ["ethernet1/12"]

    def test_iosxr_reads_each_header_as_one_name(self) -> None:
        tree = get_codec("cisco_iosxr").parse(_XR)
        assert "Loopback0" in [iface.name for iface in tree.interfaces]
        assert [lag.name for lag in tree.lags] == ["Bundle-Ether7"]
        spaced_member = _XR.replace(
            "interface GigabitEthernet0/0/0/13", "interface GigabitEthernet 0/0/0/13",
        )
        assert [(lag.name, lag.members) for lag in get_codec("cisco_iosxr").parse(spaced_member).lags] == [
            ("Bundle-Ether7", ["GigabitEthernet0/0/0/13"]),
        ]

    def test_two_stanzas_are_two_ports(self) -> None:
        """Read back by address: the two are two interfaces of the
        output, or the job lists both as dropped; no interface of
        any output is called by the type alone."""
        dropped_on = set()
        for target in PUBLIC:
            job = _job("cisco_iosxe_cli", _XE_HEADERS, target)
            back = get_codec(target).parse(job.rendered)
            assert not [
                iface.name for iface in back.interfaces
                if iface.name.lower() in ("ethernet", "cable", "port-channel", "vlan")
            ], target
            first, second = _holder(back, "10.11.0.1"), _holder(back, "10.12.0.1")
            if {"ethernet1/11", "ethernet1/12"} <= set(job.unresolved_ports):
                dropped_on.add(target)
                assert not first and not second, target
                continue
            assert len(first) == 1 and len(second) == 1 and first != second, (target, first, second)
        assert dropped_on == _NO_NAME_FOR_MODULE_ONE

    def test_the_capture_that_writes_them_apart(self) -> None:
        text = _capture(_SPACED)
        for header in ("interface Cable 1/2/3:4", "interface ethernet 1/11", "interface ethernet 1/12"):
            assert f"\n{header}\n" in text.replace("\r\n", "\n")
        tree = get_codec("cisco_iosxe_cli").parse(text)
        names = [iface.name for iface in tree.interfaces]
        assert {"ethernet1/11", "ethernet1/12", "Cable1/2/3:4"} <= set(names)
        # No interface is a word with no number in it, and none is there twice.
        assert not [name for name in names if not re.search(r"\d", name)]
        assert len(names) == len(set(names))
        own = _job("cisco_iosxe_cli", text, "cisco_iosxe_cli").rendered
        written = re.findall(r"(?m)^interface (\S+)", own)
        assert "ethernet1/11" in written and "ethernet1/12" in written
        assert not [name for name in written if not re.search(r"\d", name)]

    def test_its_own_output_reads_back_right(self) -> None:
        """Seven headers, seven interfaces, each under the one name its
        two words spell, and each address on its own port."""
        back = _own_output_read_back("cisco_iosxe_cli", _XE_HEADERS)
        assert sorted(iface.name for iface in back.interfaces) == _XE_HEADER_NAMES
        assert [(lag.name, lag.members) for lag in back.lags] == [
            ("Port-channel5", ["GigabitEthernet1/0/3"]),
        ]
        for address, name in (
            ("10.11.0.1", "ethernet1/11"), ("10.12.0.1", "ethernet1/12"),
            ("10.20.0.1", "Vlan20"), ("10.30.0.1", "Serial0/0/0.100"),
        ):
            assert _holder(back, address) == [name]


# ---------------------------------------------------------------------------
# 2b. A keyword where a type would be
# ---------------------------------------------------------------------------

_XE_RANGE = """hostname xe1
!
interface GigabitEthernet1/0/1
 ip address 10.1.0.1 255.255.255.0
!
interface range GigabitEthernet1/0/2 - 3
 description held-as-a-range
 channel-group 3 mode active
!
interface GigabitEthernet1/0/4
 channel-group 4 mode active
!
end
"""

_RANGE_ROW = "interface range GigabitEthernet1/0/2 - 3"

#: OS10's line for splitting a port into lanes, in a text the IOS-XE
#: parser is handed: two of them, and an interface after them.
_XE_BREAKOUT = """hostname sw1
!
interface breakout 1/1/49 map 100g-1x
interface breakout 1/1/50 map 25g-4x
!
interface GigabitEthernet1/0/1
 description uplink
 ip address 10.1.0.1 255.255.255.0
!
end
"""

_BREAKOUT_ROWS = [
    "interface breakout 1/1/49 map 100g-1x",
    "interface breakout 1/1/50 map 25g-4x",
]

#: A stanza whose body has a line indented with a tab, and an empty
#: line with more of the body after it.
_ODD_BODY = (
    "hostname xr1\n"
    "interface preconfigure TenGigE0/0/0/12\n"
    "\tdescription tabbed\n"
    " ipv4 address 198.51.100.77 255.255.255.0\n"
    "\n"
    " bundle id 7 mode active\n"
    "!\n"
    "interface GigabitEthernet0/0/0/13\n"
    " description kept\n"
    "!\n"
)


class TestAKeywordWhereATypeWouldBe:
    def test_the_stanzas_are_taken_out_whole(self) -> None:
        text, headers = without_keyword_stanzas(_XE_RANGE)
        assert headers == [_RANGE_ROW]
        assert "range" not in text and "held-as-a-range" not in text and "mode active\n!\nend" in text
        assert "interface GigabitEthernet1/0/4\n channel-group 4 mode active\n" in text

    def test_a_tab_or_an_empty_line_is_body(self) -> None:
        """A stanza ends at the next line that is not indented: a line
        that begins with a tab is of the body, and so is what follows
        an empty line."""
        text, headers = without_keyword_stanzas(_ODD_BODY)
        assert headers == ["interface preconfigure TenGigE0/0/0/12"]
        assert text == (
            "hostname xr1\n"
            "!\n"
            "interface GigabitEthernet0/0/0/13\n"
            " description kept\n"
            "!\n"
        )
        tree = get_codec("cisco_iosxr").parse(_ODD_BODY)
        assert [(iface.name, iface.description) for iface in tree.interfaces] == [
            ("GigabitEthernet0/0/0/13", "kept"),
        ]
        assert tree.lags == [] and "198.51.100." not in tree.model_dump_json()

    def test_a_text_with_none_comes_back_itself(self) -> None:
        """Not a copy of it: the text is whatever was pasted, and most
        of what is pasted has no such stanza."""
        text = "hostname r1\ninterface Loopback0\n ip address 10.0.0.1 255.255.255.255\n!\n"
        assert without_keyword_stanzas(text) == (text, [])
        assert without_keyword_stanzas(text)[0] is text

    def test_line_endings_are_kept(self) -> None:
        text, headers = without_keyword_stanzas(_XE_RANGE.replace("\n", "\r\n"))
        assert headers == [_RANGE_ROW]
        assert "\n" not in text.replace("\r\n", "")

    def test_a_header_met_twice_is_one_row(self) -> None:
        stanza = "interface  preconfigure   TenGigE0/0/0/1\n shutdown\n!\n"
        _text, headers = without_keyword_stanzas("hostname r\n" + stanza + stanza)
        assert headers == ["interface preconfigure TenGigE0/0/0/1"]

    def test_two_keywords_two_kinds_of_row(self) -> None:
        """A stanza held for hardware that is absent is a statement the
        device does not run: a left-out row.  A range or a breakout
        line is in force where it was typed and is not translated: a
        section, the header as written."""
        rows = keyword_stanza_rows([
            _RANGE_ROW, "Interface PRECONFIGURE TenGigE0/0/0/1", "interface preconfigure Bundle-Ether 9",
            _BREAKOUT_ROWS[0],
        ])
        assert rows == [
            _held("TenGigE0/0/0/1"), _held("Bundle-Ether 9"), _RANGE_ROW, _BREAKOUT_ROWS[0],
        ]
        assert [is_left_out_row(row) for row in rows] == [True, True, False, False]

    @pytest.mark.parametrize("target", PUBLIC)
    def test_a_range_is_no_interface(self, target: str) -> None:
        """``interface range`` configures several ports and names
        none: no record called ``range``, no bundle of its body, and
        its header in the job's list, as a section."""
        tree = get_codec("cisco_iosxe_cli").parse(_XE_RANGE)
        assert [iface.name for iface in tree.interfaces] == [
            "GigabitEthernet1/0/1", "GigabitEthernet1/0/4",
        ]
        assert [(lag.name, lag.members) for lag in tree.lags] == [
            ("Port-channel4", ["GigabitEthernet1/0/4"]),
        ]
        job = _job("cisco_iosxe_cli", _XE_RANGE, target)
        assert _RANGE_ROW in job.dropped_tier3_sections
        assert not [row for row in job.dropped_tier3_sections if is_left_out_row(row)]
        assert "held-as-a-range" not in job.rendered
        back = get_codec(target).parse(job.rendered)
        assert "range" not in [iface.name.lower() for iface in back.interfaces]
        assert "range" not in [name.lower() for name in _listed(job)]

    @pytest.mark.parametrize("target", PUBLIC)
    def test_a_breakout_line_is_no_interface(self, target: str) -> None:
        """``interface breakout <port> map <profile>`` splits a port
        and names no interface: no record called ``breakout`` (two
        such lines were one name, written twice), none called
        ``breakout1/1/49``, and each line in the job's list, as a
        section."""
        tree = get_codec("cisco_iosxe_cli").parse(_XE_BREAKOUT)
        assert [iface.name for iface in tree.interfaces] == ["GigabitEthernet1/0/1"]
        assert tree.dropped_tier3_sections == _BREAKOUT_ROWS
        job = _job("cisco_iosxe_cli", _XE_BREAKOUT, target)
        assert [row for row in job.dropped_tier3_sections if "breakout" in row] == _BREAKOUT_ROWS
        assert not [row for row in job.dropped_tier3_sections if is_left_out_row(row)]
        assert "breakout" not in job.rendered.lower()
        back = get_codec(target).parse(job.rendered)
        assert not [iface.name for iface in back.interfaces if "breakout" in iface.name.lower()]
        assert not [name for name in _listed(job) if "breakout" in name.lower()]
        # The interface after the two lines is there, by its address.
        assert len(_holder(back, "10.1.0.1")) <= 1
        assert _holder(back, "10.1.0.1") or "GigabitEthernet1/0/1" in job.unresolved_ports

    def test_iosxr_reads_the_keywords_the_same(self) -> None:
        """The two parsers share the list: on IOS XR too a range or a
        breakout header makes no interface and is a section row."""
        text = (
            "!! IOS XR Configuration 7.5.2\nhostname xr1\n"
            "interface breakout 0/0/0/4 map 10g-4x\n"
            "interface range GigabitEthernet0/0/0/2 - 3\n description typed\n!\n"
            "interface GigabitEthernet0/0/0/1\n ipv4 address 10.0.0.1 255.255.255.0\n!\nend\n"
        )
        tree = get_codec("cisco_iosxr").parse(text)
        assert [iface.name for iface in tree.interfaces] == ["GigabitEthernet0/0/0/1"]
        assert tree.dropped_tier3_sections == [
            "interface breakout 0/0/0/4 map 10g-4x", "interface range GigabitEthernet0/0/0/2 - 3",
        ]


# ---------------------------------------------------------------------------
# 3. IOS-XE static routes: a spaced interface, and the keyword dhcp
# ---------------------------------------------------------------------------

_ROUTES = "real/cisco_iosxe/batfish_cisco_ip_route.txt"
_DHCP_ROUTES = "real/cisco_iosxe/racc_csr1_iosxe173_umbrella_sig.txt"

_XE_ROUTES = """hostname xe1
!
interface Loopback77
 ip address 10.255.0.77 255.255.255.255
!
interface GigabitEthernet1/0/1
 ip address 10.1.0.1 255.255.255.0
!
ip route 198.51.100.0 255.255.255.0 loopback 77 123
ip route 192.0.2.0 255.255.255.0 GigabitEthernet 1/0/1 10.1.0.2 45
!
end
"""

#: Targets whose output, read back, has no route out the loopback: it
#: has no loopback 77, or its codec writes or reads no such route.
_NO_ROUTE_OUT_THE_LOOPBACK = {
    "aruba_aoss",       # no loopback 77: the name is dropped, and listed
    "cisco_iosxe",      # the NETCONF codec renders no static route
    "juniper_junos",    # writes no route whose next hop is an interface alone
    "opnsense",         # renders no static route
}

#: AOS-CX writes the loopback as its own grammar does, ``loopback 77``,
#: and its own parser then reads the interface as ``loopback`` and the
#: distance as 77: the fault mended here for IOS-XE, in another parser.
#: The line it writes is pinned as text below.
_READS_ITS_OWN_SPACE_APART = {"aruba_aoscx"}


def _dhcp_route_lines(text: str) -> list[str]:
    """The ``ip route ... dhcp`` lines of a text, white space apart."""
    return sorted(
        " ".join(line.split()) for line in text.splitlines()
        if re.match(r"ip route .* dhcp\s*$", line)
    )


def _route_words(line: str):
    """(interface, gateway, distance, name) of one IOS-XE route line."""
    tree = get_codec("cisco_iosxe_cli").parse("hostname r1\n!\n" + line + "\n!\nend\n")
    assert tree.dropped_tier3_sections == []
    (route,) = tree.static_routes
    return route.interface, route.gateway, route.metric, route.description


class TestARouteOutASpacedInterface:
    @pytest.mark.parametrize(
        ("line", "read"),
        [
            ("ip route 0.0.0.0 0.0.0.0 loopback 66 100", ("loopback66", "", 100, "")),
            ("ip route 0.0.0.0 0.0.0.0 loopback99 150", ("loopback99", "", 150, "")),
            ("ip route 0.0.0.0 0.0.0.0 dialer 1 250", ("dialer1", "", 250, "")),
            ("ip route 0.0.0.0 0.0.0.0 Dialer2 253", ("Dialer2", "", 253, "")),
            ("ip route 0.0.0.0 0.0.0.0 Null 0", ("Null0", "", 0, "")),
            ("ip route 10.9.0.0 255.255.0.0 GigabitEthernet 0/0/1 10.0.0.2 20 name wan",
             ("GigabitEthernet0/0/1", "10.0.0.2", 20, "wan")),
            ("ip route 10.9.0.0 255.255.0.0 Serial5/1:5 1.2.32.59 240", ("Serial5/1:5", "1.2.32.59", 240, "")),
            ("ip route 10.9.0.0 255.255.0.0 1.2.32.39 210", ("", "1.2.32.39", 210, "")),
            ("ip route vrf red 10.9.0.0 255.255.0.0 loopback 5 7", ("loopback5", "", 7, "")),
            ("ipv6 route ::/0 loopback 66 100", ("loopback66", "", 100, "")),
            ("ipv6 route ::/0 dialer 1 250", ("dialer1", "", 250, "")),
            ("ipv6 route 2001:db8::/32 GigabitEthernet 0/0/1 2001:db8::1 30",
             ("GigabitEthernet0/0/1", "2001:db8::1", 30, "")),
            # The distance is the FIRST bare number after the next hop:
            # a second one is read past, and does not replace it.
            ("ip route 10.9.0.0 255.255.0.0 1.2.32.39 210 77", ("", "1.2.32.39", 210, "")),
            ("ip route 0.0.0.0 0.0.0.0 loopback 66 100 7", ("loopback66", "", 100, "")),
            ("ipv6 route ::/0 dialer 1 250 9", ("dialer1", "", 250, "")),
        ],
    )
    def test_the_number_after_is_the_distance(self, line: str, read: tuple) -> None:
        assert _route_words(line) == read

    @pytest.mark.parametrize(
        ("line", "read"),
        [
            ("ip route 0.0.0.0 0.0.0.0 Dialer 10.0.0.1", ("Dialer", "10.0.0.1", 0, "")),
            ("ip route 0.0.0.0 0.0.0.0 Dialer 10.0.0.1 50", ("Dialer", "10.0.0.1", 50, "")),
            ("ip route vrf red 10.9.0.0 255.255.0.0 Serial 192.0.2.1 name wan", ("Serial", "192.0.2.1", 0, "wan")),
            ("ipv6 route ::/0 Dialer 2001:db8::1", ("Dialer", "2001:db8::1", 0, "")),
            ("ipv6 route ::/0 Dialer 2001:db8::1 30", ("Dialer", "2001:db8::1", 30, "")),
            # An address of the other family is no number either.
            ("ipv6 route ::/0 Dialer 10.0.0.1", ("Dialer", "", 0, "")),
            ("ip route 0.0.0.0 0.0.0.0 Dialer 2001:db8::1", ("Dialer", "", 0, "")),
            # With its number, the type is joined to it and the address is the gateway.
            ("ip route 0.0.0.0 0.0.0.0 Dialer 1 10.0.0.1 50", ("Dialer1", "10.0.0.1", 50, "")),
            ("ipv6 route ::/0 Dialer 1 2001:db8::1 30", ("Dialer1", "2001:db8::1", 30, "")),
        ],
    )
    def test_an_address_is_no_number(self, line: str, read: tuple) -> None:
        """A type word with an ADDRESS after it is not a name written
        apart: the address is the gateway.  Joined, the route went out
        ``Dialer10.0.0.1`` and had no next hop."""
        assert _route_words(line) == read

    @pytest.mark.parametrize(
        ("line", "next_hop"),
        [
            ("ip route 0.0.0.0 0.0.0.0 Dialer 10.0.0.1", "route 0.0.0.0/0 next-hop 10.0.0.1"),
            ("ipv6 route ::/0 Dialer 2001:db8::1", "route ::/0 next-hop 2001:db8::1"),
        ],
    )
    def test_the_gateway_reaches_the_output(self, line: str, next_hop: str) -> None:
        """Onto Junos, which writes a route by its next hop; and this
        codec's own output has the line as it was."""
        next_hop = "set routing-options static " + next_hop
        text = "hostname r1\n!\n" + line + "\n!\nend\n"
        assert next_hop in _job("cisco_iosxe_cli", text, "juniper_junos").rendered.splitlines()
        assert line in _job("cisco_iosxe_cli", text, "cisco_iosxe_cli").rendered.splitlines()

    def test_it_is_the_loopbacks_route(self) -> None:
        """Read back: the route to 198.51.100.0/24 is out the port the
        job says ``loopback77`` became, at distance 123."""
        no_route, apart = set(), set()
        for target in PUBLIC:
            job = _job("cisco_iosxe_cli", _XE_ROUTES, target)
            back = get_codec(target).parse(job.rendered)
            assert "loopback" not in [iface.name.lower() for iface in back.interfaces], target
            routes = [route for route in back.static_routes if route.destination == "198.51.100.0/24"]
            if not routes:
                no_route.add(target)
                continue
            (route,) = routes
            if route.metric != 123:
                apart.add(target)
                continue
            out = route.interface or route.gateway
            assert out == job.port_renames.get("loopback77", "loopback77"), (target, out)
        assert no_route == _NO_ROUTE_OUT_THE_LOOPBACK
        assert apart == _READS_ITS_OWN_SPACE_APART
        cx = _job("cisco_iosxe_cli", _XE_ROUTES, "aruba_aoscx").rendered
        assert "ip route 198.51.100.0/24 loopback 77 123" in cx.splitlines()

    def test_the_capture_that_writes_them_apart(self) -> None:
        text = _capture(_ROUTES)
        assert "\nip route 0.0.0.0 0.0.0.0 loopback 66 100\n" in text.replace("\r\n", "\n")
        tree = get_codec("cisco_iosxe_cli").parse(text)
        out = [(route.destination, route.interface, route.metric) for route in tree.static_routes if route.interface]
        assert ("0.0.0.0/0", "loopback66", 100) in out and ("::/0", "loopback66", 100) in out
        assert ("0.0.0.0/0", "dialer1", 250) in out and ("::/0", "dialer1", 250) in out
        assert not [route for route in tree.static_routes if not re.search(r"\d", route.interface or "0")]
        own = _job("cisco_iosxe_cli", text, "cisco_iosxe_cli").rendered.splitlines()
        assert "ip route 0.0.0.0 0.0.0.0 loopback66 100" in own
        assert "ipv6 route ::/0 dialer1 250" in own

    def test_its_own_output_reads_back_right(self) -> None:
        """Two lines, two routes: each out the one name its words
        spell, at the distance written after it."""
        back = _own_output_read_back("cisco_iosxe_cli", _XE_ROUTES)
        assert sorted((r.destination, r.gateway, r.interface, r.metric) for r in back.static_routes) == [
            ("192.0.2.0/24", "10.1.0.2", "GigabitEthernet1/0/1", 45),
            ("198.51.100.0/24", "", "loopback77", 123),
        ]


class TestTheKeywordDhcpStaysWhereItWas:
    """``ip route <prefix> <mask> dhcp``: the next hop is the default
    router a DHCP server hands out.  The canonical route cannot say
    that, so the keyword stays in the route's interface, where the
    IOS-XE renderer writes it back.  A word in a name field, known and
    pinned: these lines are read as they were before the spaced
    interface was."""

    @pytest.mark.parametrize(
        ("line", "read"),
        [
            ("ip route 203.0.113.0 255.255.255.0 dhcp", ("dhcp", "", 0, "")),
            ("ip route 203.0.113.0  255.255.255.0   DHCP", ("DHCP", "", 0, "")),
            # Never joined to the distance after it, as a type is to its number,
            # in whatever letter case the keyword is written.
            ("ip route 203.0.113.0 255.255.255.0 dhcp 200", ("dhcp", "", 200, "")),
            ("ip route 203.0.113.0 255.255.255.0 DHCP 200", ("DHCP", "", 200, "")),
            ("ipv6 route 2001:db8:dc::/48 Dhcp 5", ("Dhcp", "", 5, "")),
            ("ip route vrf red 203.0.113.0 255.255.255.0 dhcp", ("dhcp", "", 0, "")),
            ("ipv6 route 2001:db8:dc::/48 dhcp", ("dhcp", "", 0, "")),
            # After an interface the keyword is read past.
            ("ip route 203.0.113.0 255.255.255.0 GigabitEthernet1/0/1 dhcp", ("GigabitEthernet1/0/1", "", 0, "")),
            ("ip route 203.0.113.0 255.255.255.0 GigabitEthernet 1/0/1 dhcp 10", ("GigabitEthernet1/0/1", "", 10, "")),
            ("ip route 192.0.2.0 255.255.255.0 10.1.0.9 name dhcp", ("", "10.1.0.9", 0, "dhcp")),
        ],
    )
    def test_how_the_line_is_read(self, line: str, read: tuple) -> None:
        assert _route_words(line) == read

    @pytest.mark.parametrize(
        "line",
        [
            "ip route 203.0.113.0 255.255.255.0 dhcp",
            "ip route 192.0.2.0 255.255.255.0 dhcp 200",
            "ipv6 route 2001:db8:dc::/48 dhcp",
        ],
    )
    def test_iosxe_writes_it_back_as_it_was(self, line: str) -> None:
        job = _job("cisco_iosxe_cli", "hostname r1\n!\n" + line + "\n!\nend\n", "cisco_iosxe_cli")
        assert line in job.rendered.splitlines()
        assert job.dropped_tier3_sections == []

    def test_the_capture_that_has_twenty(self) -> None:
        text = _capture(_DHCP_ROUTES)
        lines = _dhcp_route_lines(text)
        assert len(lines) == 20
        tree = get_codec("cisco_iosxe_cli").parse(text)
        assert [route.interface for route in tree.static_routes].count("dhcp") == 20
        assert not [row for row in tree.dropped_tier3_sections if row.endswith(" dhcp")]
        own = _job("cisco_iosxe_cli", text, "cisco_iosxe_cli")
        assert _dhcp_route_lines(own.rendered) == lines
        # Onto a platform that cannot say it, the validation report
        # holds the job: the route's interface is no interface there.
        junos = _job("cisco_iosxe_cli", text, "juniper_junos")
        assert junos.validation is not None and junos.validation.severity == "block"
        assert junos.status.value == "partial"


# ---------------------------------------------------------------------------
# 4. OPNsense: a DHCP pool is on the device of its zone
# ---------------------------------------------------------------------------

_OPN = """<?xml version="1.0"?>
<opnsense>
  <system><hostname>fw1</hostname><domain>example.net</domain></system>
  <interfaces>
    <wan><if>em1</if><enable/><ipaddr>192.0.2.2</ipaddr><subnet>30</subnet></wan>
    <lan><if>em2</if><enable/><ipaddr>192.168.50.1</ipaddr><subnet>24</subnet></lan>
    <opt1><if>em3</if><enable/><ipaddr>192.168.60.1</ipaddr><subnet>24</subnet></opt1>
  </interfaces>
  <dhcpd>
    <lan><enable/><range><from>192.168.50.100</from><to>192.168.50.200</to></range></lan>
    <opt1><enable/><range><from>192.168.60.100</from><to>192.168.60.200</to></range></opt1>
  </dhcpd>
</opnsense>
"""

#: The same, with a pool keyed by a zone that <interfaces> does not have.
_OPN_ORPHAN = _OPN.replace(
    "  </dhcpd>",
    "    <opt9><enable/><range><from>10.99.0.10</from><to>10.99.0.20</to></range></opt9>\n  </dhcpd>",
)

#: And with the LAN zone assigned to no device, so that the zone is
#: named by its own tag: an interface called ``lan``.
_OPN_ORPHAN_BESIDE_LAN = _OPN_ORPHAN.replace("<lan><if>em2</if>", "<lan>")

_ORPHAN_ROW = "<dhcpd><opt9>: no <opt9> in <interfaces>, so its DHCP pool has no interface"

#: The targets whose output, read back, says which interface a pool is on.
_SAYS_A_POOLS_INTERFACE = {"arista_eos", "fortigate_cli", "juniper_junos", "opnsense"}

_OPN_CAPTURES = {
    "real/opnsense/opnsense_acl_test_config.xml": "mismatch0",
    "real/opnsense/opnsense_docs_carp_ha_master.xml": "em0",
    "real/opnsense/opnsense_docs_carp_ha_backup.xml": "em0",
    "synthetic/opnsense/kitchen_sink.xml": "em1",
}


def _zones(xml: str, section: str) -> list[str]:
    """The tags of the children of <interfaces> or <dhcpd>, as text has them."""
    element = ET.fromstring(xml).find(section)
    return [] if element is None else [child.tag for child in element]


def _pools(tree) -> list[tuple[str, str]]:
    return [(pool.interface, pool.start_ip) for pool in tree.dhcp_servers]


class TestAPoolIsOnTheDeviceOfItsZone:
    def test_the_field_holds_the_device(self) -> None:
        tree = get_codec("opnsense").parse(_OPN)
        assert _pools(tree) == [("em2", "192.168.50.100"), ("em3", "192.168.60.100")]
        assert tree.dropped_tier3_sections == []

    def test_a_pool_with_no_device_is_left_out(self) -> None:
        """It has no interface to be on.  The row says which zone, and
        it is then true of the row that the pool is in no output."""
        tree = get_codec("opnsense").parse(_OPN_ORPHAN)
        assert _pools(tree) == [("em2", "192.168.50.100"), ("em3", "192.168.60.100")]
        assert tree.dropped_tier3_sections == [_ORPHAN_ROW]
        for target in PUBLIC:
            job = _job("opnsense", _OPN_ORPHAN, target)
            assert _ORPHAN_ROW in job.dropped_tier3_sections, target
            assert "10.99.0." not in job.rendered, target
            assert _lines_with(job.rendered, "opt9") == [], target
        own = _job("opnsense", _OPN_ORPHAN, "opnsense").rendered
        assert _zones(own, "dhcpd") == ["em2", "em3"]

    def test_it_is_not_a_second_lan(self) -> None:
        """This codec's renderer writes a pool with no interface under
        ``<lan>``.  Kept in the tree, the pool of the zone that has no
        device was a second ``<dhcpd><lan>`` beside the real one."""
        tree = get_codec("opnsense").parse(_OPN_ORPHAN_BESIDE_LAN)
        assert _pools(tree) == [("lan", "192.168.50.100"), ("em3", "192.168.60.100")]
        own = _job("opnsense", _OPN_ORPHAN_BESIDE_LAN, "opnsense").rendered
        assert _zones(own, "dhcpd") == ["lan", "em3"]
        assert set(_zones(own, "dhcpd")) <= set(_zones(own, "interfaces"))
        assert _pools(get_codec("opnsense").parse(own)) == [
            ("lan", "192.168.50.100"), ("em3", "192.168.60.100"),
        ]

    def test_a_zone_named_by_its_own_tag(self) -> None:
        """A zone with no <if> is named by its tag, as an interface
        and as a pool's interface alike: it is in <interfaces>, so its
        pool is no orphan."""
        text = _OPN.replace("<lan><if>em2</if>", "<lan>")
        tree = get_codec("opnsense").parse(text)
        assert _holder(tree, "192.168.50.1") == ["lan"]
        assert _pools(tree) == [("lan", "192.168.50.100"), ("em3", "192.168.60.100")]
        assert tree.dropped_tier3_sections == []

    def test_the_pool_follows_its_port(self) -> None:
        """Read back: where an output says which interface the LAN
        pool is on, it is the interface that holds the LAN address.
        No line of any output has the zone's name."""
        says = set()
        for target in PUBLIC:
            job = _job("opnsense", _OPN, target)
            assert _lines_with(job.rendered, "lan") == [], target
            back = get_codec(target).parse(job.rendered)
            pools = {pool.start_ip: pool.interface for pool in back.dhcp_servers}
            for start, address in (("192.168.50.100", "192.168.50.1"), ("192.168.60.100", "192.168.60.1")):
                if pools.get(start):
                    says.add(target)
                    assert [pools[start]] == _holder(back, address), (target, start)
        assert says == _SAYS_A_POOLS_INTERFACE

    def test_its_own_output_agrees_with_itself(self) -> None:
        """OPNsense onto OPNsense: every zone <dhcpd> is keyed by is a
        zone of the same output's <interfaces>."""
        rendered = _job("opnsense", _OPN, "opnsense").rendered
        assert _zones(rendered, "dhcpd") == ["em2", "em3"]
        assert set(_zones(rendered, "dhcpd")) <= set(_zones(rendered, "interfaces"))

    @pytest.mark.parametrize("rel", sorted(_OPN_CAPTURES))
    def test_the_captures_that_have_a_pool(self, rel: str) -> None:
        text = _capture(rel)
        device = _OPN_CAPTURES[rel]
        assert "lan" in _zones(text, "dhcpd")
        assert ET.fromstring(text).findtext("interfaces/lan/if") == device
        tree = get_codec("opnsense").parse(text)
        assert [pool.interface for pool in tree.dhcp_servers] == [device]
        start = tree.dhcp_servers[0].start_ip
        for target in PUBLIC:
            job = _job("opnsense", text, target)
            assert not [w for w in job.warnings if "'lan'" in w], target
            back = get_codec(target).parse(job.rendered)
            on = [pool.interface for pool in back.dhcp_servers if pool.start_ip == start and pool.interface]
            if target in _SAYS_A_POOLS_INTERFACE:
                # The pool is on the port its zone's device became, or
                # on the device's own name where the job left that.
                assert on == [job.port_renames.get(device, device)], (target, on)
            assert "lan" not in on, target
        own = _job("opnsense", text, "opnsense").rendered
        assert set(_zones(own, "dhcpd")) <= set(_zones(own, "interfaces"))

    def test_junos_binds_the_server_to_a_port(self) -> None:
        """The line that was wrong in two ``completed`` jobs."""
        for rel in ("real/opnsense/opnsense_docs_carp_ha_master.xml", "real/opnsense/opnsense_docs_carp_ha_backup.xml"):
            job = _job("opnsense", _capture(rel), "juniper_junos")
            bound = re.findall(r"(?m)^set system services dhcp-local-server group \S+ interface (\S+)$", job.rendered)
            assert bound == [job.port_renames["em0"]] == ["ge-0/0/0"], rel

    def test_its_own_output_reads_back_right(self) -> None:
        """Each pool on the device of its zone, in the config's own
        output as in the config: the device, written out."""
        assert _pools(_own_output_read_back("opnsense", _OPN)) == [
            ("em2", "192.168.50.100"), ("em3", "192.168.60.100"),
        ]
        assert _pools(_own_output_read_back("opnsense", _OPN_ORPHAN)) == [
            ("em2", "192.168.50.100"), ("em3", "192.168.60.100"),
        ]
        for rel, device in _OPN_CAPTURES.items():
            back = _own_output_read_back("opnsense", _capture(rel))
            assert [pool.interface for pool in back.dhcp_servers] == [device], rel


# ---------------------------------------------------------------------------
# 5. Junos: an interface is a name some line configures
# ---------------------------------------------------------------------------

_JUNOS = """set system host-name j1
set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.1/24
set interfaces ge-0/0/3 unit 7 vlan-id 7
set interfaces ge-0/0/3 unit 7 family inet address 10.7.0.1/24
set interfaces irb unit 100 family inet address 10.1.100.1/24
set interfaces irb unit 100 description users
set interfaces st0 unit 1 family inet address 10.9.9.1/30
set interfaces vlan unit 5 family inet address 10.5.5.1/24
set routing-instances T instance-type vrf
set routing-instances T interface irb.100
"""

#: The interfaces that text states: each unit a line is under, and the
#: one port that is hardware.  No ``irb``, ``st0`` or ``vlan``: every
#: line that names one of them is under a unit above 0.
_JUNOS_NAMES = ["ge-0/0/1", "ge-0/0/3", "ge-0/0/3.7", "irb.100", "st0.1", "vlan.5"]

#: A description on the IRB device itself, and a unit beside it.
_JUNOS_DESCRIBED = """set system host-name j1
set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.1/24
set interfaces irb description all-the-svis
set interfaces irb unit 100 family inet address 10.1.100.1/24
set routing-instances T instance-type vrf
set routing-instances T interface irb.100
"""

#: An MTU on the device and an address on its unit 0, beside a unit
#: that is folded onto its VLAN.
_JUNOS_UNIT_ZERO = """set system host-name j1
set interfaces irb mtu 9100
set interfaces irb unit 0 family inet address 10.8.0.1/24
set interfaces irb unit 100 family inet address 10.1.100.1/24
set vlans V100 vlan-id 100
set vlans V100 l3-interface irb.100
"""

#: The usual route-based VPN: an unnumbered tunnel on unit 0, and a
#: route out of it.  No handler reads ``family inet`` with no address.
_JUNOS_TUNNEL = """set system host-name srx1
set interfaces ge-0/0/0 unit 0 family inet address 192.0.2.2/30
set interfaces st0 unit 0 family inet
set routing-options static route 10.50.0.0/16 next-hop st0.0
"""

_JUNOS_HEAD = "set system host-name j1\nset interfaces ge-0/0/1 unit 0 family inet address 10.1.0.1/24\n"

#: Lines that configure a device or its unit 0 and that no handler
#: reads, each with the bare name it makes.
_STATED_AND_NOT_READ = [
    ("set interfaces st0 unit 0 family inet", "st0"),
    ("set interfaces st0", "st0"),
    ("set interfaces st0 unit 0", "st0"),
    ("set interfaces irb gratuitous-arp-reply", "irb"),
    ("set interfaces lo0 unit 0 family iso", "lo0"),
    ("set interfaces vlan unit 0 family inet", "vlan"),
    ("set interfaces gr-0/0/0 unit 0 tunnel source 192.0.2.2", "gr-0/0/0"),
    ("set interfaces reth0 redundant-ether-options redundancy-group 1", "reth0"),
]

#: Lines under a unit above 0, each with the one interface it makes:
#: the unit, and no record for the device it hangs off.
_ONLY_A_UNIT = [
    ("set interfaces irb unit 100 family inet address 10.1.100.1/24", "irb.100"),
    ("set interfaces st0 unit 1 family inet", "st0.1"),
    ("set interfaces st0 unit 1", "st0.1"),
    ("set interfaces lo0 unit 1 family inet address 10.255.1.1/32", "lo0.1"),
    ("set interfaces vlan unit 5 family inet address 10.5.5.1/24", "vlan.5"),
    ("set interfaces gr-0/0/0 unit 1 family inet address 10.6.0.1/30", "gr-0/0/0.1"),
    ("set interfaces reth0 unit 9 family inet address 10.9.0.1/24", "reth0.9"),
    # Ports, and not yet read as ports by the classifier: until they
    # are, each is a name like any other, and has no record of its own
    # with nothing but a unit above 0.
    ("set interfaces xe-0/0/6:2 unit 10 family inet address 10.6.0.1/24", "xe-0/0/6:2.10"),
    ("set interfaces so-0/0/0 unit 5 family inet address 10.5.0.1/30", "so-0/0/0.5"),
]

#: Names the classifier reads as hardware or as a bundle, each with
#: only a tagged unit: such a name keeps its record whatever the
#: config says of it, and its unit rides on it.
_PORTS_WITH_ONLY_UNITS = [
    ("set interfaces ge-0/0/3 unit 7 vlan-id 7", ["ge-0/0/3", "ge-0/0/3.7"]),
    ("set interfaces xe-1/0/2 unit 30 vlan-id 30", ["xe-1/0/2", "xe-1/0/2.30"]),
    ("set interfaces fxp0 unit 4 family inet address 10.4.0.1/24", ["fxp0", "fxp0.4"]),
    ("set interfaces em1 unit 2 family inet address 10.4.1.1/24", ["em1", "em1.2"]),
    ("set interfaces ae3 unit 9 vlan-id 9", ["ae3", "ae3.9"]),
]

_CARRIERS = ("irb", "st0", "vlan")

#: Targets that write no description for an interface they have no
#: stanza for.
_WRITES_NO_DESCRIPTION = {"mikrotik_routeros"}

_JUNOS_EMPTY = {
    "real/junos/batfish_evpntype5_router1_junos2541.set": "irb",
    "real/junos/ksator_labmgmt_qfx10k2_junos173.set": "irb",
    "synthetic/juniper_junos/kitchen_sink.set": "irb",
    "real/junos/jnprautomate_mnha_vsrx_a_junos.set": "st0",
}
_JUNOS_DESCRIBED_CAPTURE = "real/junos/saidvandeklundert_snmpv3_junos172.set"


def _junos_names(text: str) -> list[str]:
    return [iface.name for iface in get_codec("juniper_junos").parse(text).interfaces]


def _stanzas_of(text: str, name: str, target: str) -> list[str]:
    """The lines of an output that open a stanza for the bare *name*.

    On Junos a unit's line has the word in it (``set interfaces irb
    unit 100 ...``); the stanza of the device itself is a line that
    says something of ``irb`` and not of a unit of it.
    """
    if target == "juniper_junos":
        return [
            line for line in text.splitlines()
            if re.match(rf"set interfaces {name}(?:\s+(?!unit\s+[1-9])\S.*)?$", line.strip())
        ]
    return _lines_with(text, name)


class TestAnInterfaceIsANameSomeLineConfigures:
    def test_a_unit_line_makes_the_unit_alone(self) -> None:
        assert _junos_names(_JUNOS) == _JUNOS_NAMES

    @pytest.mark.parametrize(("line", "unit"), _ONLY_A_UNIT)
    def test_each_such_line(self, line: str, unit: str) -> None:
        """Whatever the device is called, and whatever follows the
        unit's number: nothing at all, or a statement no handler
        reads."""
        assert _junos_names(_JUNOS_HEAD + line + "\n") == ["ge-0/0/1", unit]

    @pytest.mark.parametrize(("line", "name"), _STATED_AND_NOT_READ)
    def test_a_device_or_unit_zero_line_makes_it(self, line: str, name: str) -> None:
        """What decides is what the line says, not whether a handler
        read it: each of these leaves the record empty, and each
        configures the device."""
        tree = get_codec("juniper_junos").parse(_JUNOS_HEAD + line + "\n")
        assert [iface.name for iface in tree.interfaces] == ["ge-0/0/1", name]
        (made,) = [iface for iface in tree.interfaces if iface.name == name]
        assert not made.ipv4_addresses and not made.description and made.mtu is None

    @pytest.mark.parametrize(("line", "names"), _PORTS_WITH_ONLY_UNITS)
    def test_a_port_with_only_units_stays(self, line: str, names: list[str]) -> None:
        tree = get_codec("juniper_junos").parse("set system host-name j1\n" + line + "\n")
        assert [iface.name for iface in tree.interfaces] == names
        assert not tree.interfaces[0].ipv4_addresses and not tree.interfaces[0].description

    def test_the_kinds_with_a_record_unstated(self) -> None:
        """The classifier's kinds for hardware and for a LAG, all of
        them: two of the five are kinds no Junos name is given yet."""
        assert sorted(junos_parse._HAS_A_RECORD_UNSTATED) == [
            "breakout", "hw_aggregate", "lag", "mgmt", "physical",
        ]

    def test_a_range_member_is_configured(self) -> None:
        text = (
            "set system host-name j1\n"
            "set interfaces interface-range TUNNELS member lo0\n"
            "set interfaces interface-range TUNNELS member ge-0/0/5\n"
        )
        assert _junos_names(text) == ["ge-0/0/5", "lo0"]

    def test_a_deactivated_line_states_nothing(self) -> None:
        """A line the device does not run is left out before it is
        read, here as everywhere."""
        text = _JUNOS_HEAD + "set interfaces st0 unit 0 family inet\nset interfaces st0 unit 1 family inet\n"
        assert _junos_names(text) == ["ge-0/0/1", "st0", "st0.1"]
        assert _junos_names(text + "deactivate interfaces st0 unit 0\n") == ["ge-0/0/1", "st0.1"]
        assert _junos_names(text + "deactivate interfaces st0\n") == ["ge-0/0/1"]

    @pytest.mark.parametrize("target", PUBLIC)
    def test_the_tunnel_of_a_route_is_there(self, target: str) -> None:
        """An unnumbered ``st0.0`` is an interface of the tree, and a
        job says what became of it: no target has a name for it, so
        it is left as the source has it and listed -- never gone in
        silence, with the route to it still in the output."""
        tree = get_codec("juniper_junos").parse(_JUNOS_TUNNEL)
        assert [(iface.name, iface.tunnel_type) for iface in tree.interfaces] == [
            ("ge-0/0/0", ""), ("st0", "ipsec"),
        ]
        assert [(route.destination, route.gateway) for route in tree.static_routes] == [
            ("10.50.0.0/16", "st0.0"),
        ]
        job = _job("juniper_junos", _JUNOS_TUNNEL, target)
        if target == "juniper_junos":
            # This codec's own renderer writes no line for an empty
            # ``st0`` that stands alone (it writes a bare ``set
            # interfaces st0`` where the config has a unit of it too
            # or a routing instance names it), so its output has the
            # route and not the tunnel.  Older than this rule; pinned
            # as it is, to fail when the renderer comes to write the
            # unit.
            assert "set routing-options static route 10.50.0.0/16 next-hop st0.0" in job.rendered.splitlines()
            assert _stanzas_of(job.rendered, "st0", target) == []
        else:
            assert job.untranslated_ports == ["st0"]
            assert job.status.value == "partial"

    @pytest.mark.parametrize("target", PUBLIC)
    def test_no_output_has_a_stanza_for_it(self, target: str) -> None:
        job = _job("juniper_junos", _JUNOS, target)
        back = get_codec(target).parse(job.rendered)
        names = [iface.name for iface in back.interfaces]
        for carrier in _CARRIERS:
            assert carrier not in names, (target, carrier)
            assert carrier not in _listed(job), (target, carrier)
            # As text too -- but `vlan` is a word of other platforms'
            # own grammar (`interface vlan 5`, `set type vlan`), so
            # for that one the text is read on Junos alone.
            if carrier != "vlan" or target == "juniper_junos":
                assert _stanzas_of(job.rendered, carrier, target) == [], (target, carrier)
        # The units are still there, by their addresses, or listed as dropped.
        for unit, address in (("irb.100", "10.1.100.1"), ("st0.1", "10.9.9.1")):
            assert _holder(back, address) or unit in job.unresolved_ports or any(
                address in [a.ip for a in vlan.ipv4_addresses] for vlan in back.vlans
            ), (target, unit)

    @pytest.mark.parametrize("target", PUBLIC)
    def test_one_that_has_a_description_keeps_it(self, target: str) -> None:
        tree = get_codec("juniper_junos").parse(_JUNOS_DESCRIBED)
        assert [(i.name, i.description) for i in tree.interfaces if i.name == "irb"] == [
            ("irb", "all-the-svis"),
        ]
        job = _job("juniper_junos", _JUNOS_DESCRIBED, target)
        assert ("all-the-svis" in job.rendered) is (target not in _WRITES_NO_DESCRIPTION)
        if target != "juniper_junos":
            # No target has a name for it: it is left, and listed.
            assert job.untranslated_ports == ["irb"]

    def test_an_mtu_and_unit_zero_make_one(self) -> None:
        """Beside a unit that is folded onto its VLAN, too: what the
        device itself states is not a unit's to fold."""
        tree = get_codec("juniper_junos").parse(_JUNOS_UNIT_ZERO)
        (irb,) = [iface for iface in tree.interfaces if iface.name == "irb"]
        assert irb.mtu == 9086  # the media MTU less its Ethernet header
        assert [(a.ip, a.prefix_length) for a in irb.ipv4_addresses] == [("10.8.0.1", 24)]
        assert [(v.id, [a.ip for a in v.ipv4_addresses]) for v in tree.vlans] == [(100, ["10.1.100.1"])]
        own = _job("juniper_junos", _JUNOS_UNIT_ZERO, "juniper_junos").rendered.splitlines()
        assert "set interfaces irb mtu 9100" in own
        assert "set interfaces irb unit 0 family inet address 10.8.0.1/24" in own

    @pytest.mark.parametrize("rel", sorted(_JUNOS_EMPTY))
    def test_the_captures_with_units_only(self, rel: str) -> None:
        text = _capture(rel)
        carrier = _JUNOS_EMPTY[rel]
        assert re.search(rf"(?m)^set interfaces {carrier} unit [1-9]", text)
        assert not re.search(rf"(?m)^set interfaces {carrier} (?!unit [1-9])", text)
        tree = get_codec("juniper_junos").parse(text)
        names = [iface.name for iface in tree.interfaces]
        assert carrier not in names
        assert [name for name in names if name.startswith(carrier + ".")]
        for target in PUBLIC:
            job = _job("juniper_junos", text, target)
            assert carrier not in _listed(job), target
            assert carrier not in [iface.name for iface in get_codec(target).parse(job.rendered).interfaces], target
        # Junos onto Junos gains no line for the device that the source did not have.
        own = _job("juniper_junos", text, "juniper_junos").rendered
        assert _stanzas_of(own, carrier, "juniper_junos") == []

    def test_the_capture_that_describes_it(self) -> None:
        text = _capture(_JUNOS_DESCRIBED_CAPTURE)
        assert '\nset interfaces irb description "mgmt"\n' in text.replace("\r\n", "\n")
        tree = get_codec("juniper_junos").parse(text)
        assert [(i.name, i.description) for i in tree.interfaces if i.name == "irb"] == [("irb", "mgmt")]
        for target in PUBLIC:
            job = _job("juniper_junos", text, target)
            assert ("irb" in job.untranslated_ports) is (target != "juniper_junos"), target

    def test_its_own_output_reads_back_right(self) -> None:
        """The interfaces each text states, written out, in the
        config's own output as in the config."""
        assert [iface.name for iface in _own_output_read_back("juniper_junos", _JUNOS).interfaces] == _JUNOS_NAMES
        described = _own_output_read_back("juniper_junos", _JUNOS_DESCRIBED)
        assert [(iface.name, iface.description) for iface in described.interfaces] == [
            ("ge-0/0/1", ""), ("irb", "all-the-svis"), ("irb.100", ""),
        ]
        unit_zero = _own_output_read_back("juniper_junos", _JUNOS_UNIT_ZERO)
        assert [(iface.name, iface.mtu) for iface in unit_zero.interfaces] == [("irb", 9086)]
        assert [(a.ip, a.prefix_length) for a in unit_zero.interfaces[0].ipv4_addresses] == [("10.8.0.1", 24)]
        assert [(v.id, [a.ip for a in v.ipv4_addresses]) for v in unit_zero.vlans] == [(100, ["10.1.100.1"])]
