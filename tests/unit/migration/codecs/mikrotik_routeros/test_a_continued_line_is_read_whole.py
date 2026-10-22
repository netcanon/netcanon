"""A RouterOS line that ends in a backslash goes on in the next one.

An ``export`` breaks a long line at any column and indents the rest:
between two words, right after a key (``name=\\``), inside a quoted
value, inside a word (``100M-\\`` then ``baseT-half``).  The device
reads its own export back as the line was before the break, so the
backslash, the line break and the next line's indentation are dropped
and nothing is put in their place.  White space before the backslash
is the line's own, and is kept.

The parser used to strip the next line and join it on with a space,
which is right only for a break between two words.  A ``name=`` that
an export carried onto the next line was then read as no name: every
port of the committed CRS310 capture kept its factory name, and the
address the capture puts on ``"Access Point"`` was on no interface of
the tree, in jobs that said ``completed``.

The expectations below are typed from the capture's text by hand,
not read back through the parser.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netcanon.migration.codecs.mikrotik_routeros.parse import _join_continuations

pytestmark = pytest.mark.unit

BS = "\\"
CAPTURE = (
    Path(__file__).resolve().parents[4]
    / "fixtures" / "real" / "mikrotik" / "user_contrib_crs310_ros7.rsc"
)


@pytest.mark.parametrize(
    ("lines", "joined"),
    [
        # Between two words: the space is before the backslash.
        ([f"add mtu=1500 {BS}", "    name=x"], "add mtu=1500 name=x"),
        # Right after a key.
        ([f"set mtu=1500 name={BS}", '    "Access Point" rx=off'], 'set mtu=1500 name="Access Point" rx=off'),
        # Inside a quoted list, before its comma.
        (
            [f'set advertise="10M-baseT-full{BS}', '    ,100M-baseT-half"'],
            'set advertise="10M-baseT-full,100M-baseT-half"',
        ),
        # Inside a word.
        ([f'set advertise="2.5G-{BS}', '    baseT"'], 'set advertise="2.5G-baseT"'),
        # Inside a quoted value, after a space of its own.
        ([f'add comment="switch mgmt {BS}', '    vlan address"'], 'add comment="switch mgmt vlan address"'),
        # White space after the backslash is not the line's.
        ([f"add mtu=1500 {BS}  ", "    name=x"], "add mtu=1500 name=x"),
        # Three lines.
        ([f"add a=1 {BS}", f"    b={BS}", "    2 c=3"], "add a=1 b=2 c=3"),
    ],
    ids=["between-words", "after-a-key", "in-a-list", "in-a-word", "in-a-quote",
         "space-after", "three-lines"],
)
def test_a_break_is_dropped_and_nothing_is_put_in_its_place(lines: list[str], joined: str) -> None:
    assert _join_continuations("\n".join(lines)) == joined


def test_a_line_that_is_not_continued_is_kept_as_it_is() -> None:
    """Trailing white space included; and a backslash the value keeps
    (a quoted ``\\\\`` at the end) continues nothing."""
    text = "\n".join([
        "/interface ethernet  ",
        f'set [ find default-name=ether1 ] comment="a{BS}{BS}"',
        "set [ find default-name=ether2 ] comment=b",
    ])
    assert _join_continuations(text) == text


def test_the_last_line_may_end_in_a_backslash() -> None:
    assert _join_continuations(f"add a=1 {BS}") == "add a=1 "


class TestTheCommittedCapture:
    """The CRS310 export: nine of its ten ports have a name of their
    own, each carried onto the line after ``name=``."""

    #: Factory name to the name the capture gives the port.
    NAMES = {
        "ether1": "Desktop",
        "ether2": "Access Point",
        "ether3": "CLUSTER - PVENAS",
        "ether4": "PROD - PVENAS",
        "ether5": "CLUSTER - PVE5",
        "ether6": "PROD - PVE5",
        "ether7": "CLUSTER - PVE3",
        "ether8": "PROD - PVE3",
        "sfp-sfpplus1": "UPLINKSFP",
        "sfp-sfpplus2": "sfp-sfpplus2",
    }

    def test_every_port_has_the_name_the_capture_gives_it(self) -> None:
        tree = MikroTikRouterOSCodec().parse(CAPTURE.read_text(encoding="utf-8"))
        ports = {
            iface.default_name: iface.name
            for iface in tree.interfaces if iface.default_name
        }
        assert ports == self.NAMES

    def test_the_address_is_on_the_port_the_capture_puts_it_on(self) -> None:
        """``add address=192.168.88.1/24 ... interface=\\`` and then
        ``"Access Point"``."""
        tree = MikroTikRouterOSCodec().parse(CAPTURE.read_text(encoding="utf-8"))
        on = {
            f"{address.ip}/{address.prefix_length}": iface.name
            for iface in tree.interfaces for address in iface.ipv4_addresses
        }
        assert on["192.168.88.1/24"] == "Access Point"

    #: The ``advertise=`` list of each port, broken by the export inside
    #: a word (``100M-`` / ``baseT-half``) on the copper ports and before
    #: a comma on the SFP+ ports.
    COPPER = "10M-baseT-half,10M-baseT-full,100M-baseT-half,100M-baseT-full,1G-baseT-full,2.5G-baseT"
    SFP = (
        "10M-baseT-half,10M-baseT-full,100M-baseT-half,100M-baseT-full,1G-baseT-half,"
        "1G-baseT-full,1G-baseX,2.5G-baseT,2.5G-baseX,5G-baseT,10G-baseT,10G-baseSR-LR,"
        "10G-baseCR"
    )

    def test_a_quoted_list_broken_inside_it_is_one_list(self) -> None:
        joined = _join_continuations(CAPTURE.read_text(encoding="utf-8"))
        advertised = {
            line.split("default-name=", 1)[1].split(" ", 1)[0]:
                line.split('advertise="', 1)[1].split('"', 1)[0]
            for line in joined.splitlines()
            if line.startswith("set [ find default-name=") and 'advertise="' in line
        }
        assert advertised == {
            **{f"ether{n}": self.COPPER for n in range(1, 9)},
            "sfp-sfpplus1": self.SFP,
            "sfp-sfpplus2": self.SFP,
        }
