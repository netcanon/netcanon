"""Aruba AOS-S render: no stanza that says ``enable`` and nothing else
for a port another line of the output names.

The device prints an ``interface`` stanza only for a port with a
setting of its own; a port with none is in the config through the
VLAN lists and ``trunk`` lines that name it.  The parser gives every
such port the record an empty stanza makes, so a config whose ports
have no stanza used to come back out with three lines for each of
them -- ``interface N`` / ``enable`` / ``exit`` -- that the source
never had and that say nothing.

A stanza is left out only when all of this holds: it would hold
``enable`` alone; the port's name is in one of the device's own forms;
and a VLAN's list or a ``trunk`` line of the same output gives the
port back when the parser reads it, which is what gives it its record
again.  Anything else is written as before.

Whether a line gives a port back is the parser's to say, and the
renderer asks its reader, of the line as written.  A line counts for
its ports only if every one of them comes back as itself: a ``trunk``
line with a space in a member's name is no ``trunk`` line to the
parser, a zero-padded number is written without its zeros, and a list
under a stanza that a line of the top ended -- the rest of a VLAN's
name, after a line break, can be one -- is read by nobody.  The port
beside such a name keeps its stanza, or it would be in no record of
the output read back.  (A line break alone ends no stanza: the rest of
the name in column 0 is the stanza's, and the lists under it are read.)
"""

from __future__ import annotations

import collections
import json
import random
import re
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalLAG,
    CanonicalVlan,
)
from netcanon.migration.codecs.aruba_aoss import parse as aoss_parse
from netcanon.migration.codecs.aruba_aoss import render as aoss_render
from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
CAPTURES = sorted(
    list((FIXTURES / "real" / "aruba_aoss").glob("*.cfg"))
    + list((FIXTURES / "synthetic" / "aruba_aoss").glob("*.cfg"))
)


def _stanzas(text: str) -> dict[str, list[str]]:
    """``interface`` header -> the lines of its body, ``exit`` left off."""
    out: dict[str, list[str]] = {}
    name = None
    for line in text.splitlines():
        if line.startswith("interface "):
            name = line[len("interface "):].strip().strip('"')
            out[name] = []
        elif name is not None and line[:1] in (" ", "\t"):
            if line.strip() != "exit":
                out[name].append(line.strip())
        else:
            name = None
    return out


def _tree(*ports: CanonicalInterface, untagged: list[str], lags: list[CanonicalLAG] | None = None) -> CanonicalIntent:
    return CanonicalIntent(
        interfaces=list(ports),
        vlans=[CanonicalVlan(id=10, name="V10", untagged_ports=untagged)],
        lags=lags or [],
    )


def test_a_listed_port_gets_no_bare_stanza() -> None:
    tree = _tree(
        CanonicalInterface(name="1"), CanonicalInterface(name="1/2"),
        CanonicalInterface(name="1/A1"), CanonicalInterface(name="A2"),
        untagged=["1", "1/2", "1/A1", "A2"],
    )
    out = ArubaAOSSCodec().render(tree)
    assert "   untagged 1,1/2,1/A1,A2\n" in out + "\n"
    assert _stanzas(out) == {}


def test_an_unlisted_port_keeps_its_stanza() -> None:
    """Nothing else in the output would say the port is there."""
    tree = _tree(CanonicalInterface(name="1"), CanonicalInterface(name="2"), untagged=["1"])
    assert _stanzas(ArubaAOSSCodec().render(tree)) == {"2": ["enable"]}


@pytest.mark.parametrize(
    ("port", "body"),
    [
        (CanonicalInterface(name="1", enabled=False), ["disable"]),
        (CanonicalInterface(name="1", description="uplink"), ['name "uplink"', "enable"]),
        (
            CanonicalInterface(name="1", ipv4_addresses=[CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24)]),
            ["enable", "routing", "ip address 10.0.0.1/24"],
        ),
        (
            CanonicalInterface(name="1", ipv6_addresses=[CanonicalIPv6Address(ip="2001:db8::1", prefix_length=64)]),
            ["enable", "routing", "ipv6 address 2001:db8::1/64"],
        ),
    ],
    ids=["disabled", "described", "ipv4", "ipv6"],
)
def test_a_stanza_that_says_more_is_written(port: CanonicalInterface, body: list[str]) -> None:
    assert _stanzas(ArubaAOSSCodec().render(_tree(port, untagged=["1"]))) == {"1": body}


def test_a_trunk_line_names_its_members() -> None:
    lag = CanonicalLAG(name="trk1", members=["23", "24"], mode="active")
    tree = _tree(
        CanonicalInterface(name="23", lag_member_of="trk1"),
        CanonicalInterface(name="24", lag_member_of="trk1"),
        CanonicalInterface(name="trk1", interface_type="ianaift:ieee8023adLag"),
        untagged=["trk1"], lags=[lag],
    )
    out = ArubaAOSSCodec().render(tree)
    assert "trunk 23-24 trk1 lacp" in out and "   untagged Trk1" in out
    assert _stanzas(out) == {}


def test_an_unlisted_lag_keeps_its_stanza() -> None:
    """A ``trunk`` line names a LAG's members.  It makes no record for
    the LAG itself, so the LAG's own stanza is what says it is there."""
    lag = CanonicalLAG(name="trk1", members=["23", "24"], mode="active")
    tree = _tree(
        CanonicalInterface(name="23", lag_member_of="trk1"),
        CanonicalInterface(name="trk1", interface_type="ianaift:ieee8023adLag"),
        untagged=["5"], lags=[lag],
    )
    assert _stanzas(ArubaAOSSCodec().render(tree)) == {"Trk1": ["enable"]}


@pytest.mark.parametrize("name", ["Ethernet1", "ge-0/0/1", "1/1/1", "GigabitEthernet1/0/1", "eth0"])
def test_a_foreign_name_keeps_its_stanza(name: str) -> None:
    """What the device does with a port that has no setting of its own
    is known of its own ports.  A name in another form is written as
    it always was, whether or not its list reads back."""
    tree = _tree(CanonicalInterface(name=name, switchport_mode="access", access_vlan=10), untagged=[name])
    assert _stanzas(ArubaAOSSCodec().render(tree)) == {name: ["enable"]}


@pytest.mark.parametrize(
    "name",
    ["1", "24", "1/24", "1/A1", "10/B12", "A1", "Z9", "Trk1", "trk12", "TRK3",
     "Ethernet1", "ge-0/0/1", "1/1/1", "AB1", "1/", "A", "", "loopback0", "Vlan10", "oobm", "1/1.5", "1-2"],
)
def test_the_devices_forms_are_the_parsers(name: str) -> None:
    """The renderer's notion of a port of the device is the parser's:
    the forms a port list may hold a range between.  (It is not what
    decides whether a line gives a port back: the tests below.)"""
    assert aoss_render._is_a_port_of_the_device(name) == bool(aoss_parse._AOS_PORT_SHAPE_RE.match(name))


def test_a_collision_is_still_reported() -> None:
    """Two records on one name are reported in the comment block
    whether or not the first of them has a stanza to write."""
    tree = _tree(
        CanonicalInterface(name="1/1"),
        CanonicalInterface(name="1/1", description="AppGigabitEthernet1/0/1"),
        untagged=["1/1"],
    )
    out = ArubaAOSSCodec().render(tree)
    assert "; interface 1/1 collides" in out
    assert ";   collided source: AppGigabitEthernet1/0/1" in out
    assert _stanzas(out) == {}


@pytest.mark.parametrize("path", CAPTURES, ids=[p.name for p in CAPTURES])
def test_a_config_gains_no_stanza(path: Path) -> None:
    """AOS-S onto AOS-S: every ``interface`` stanza of the output is
    for an interface the source config has a stanza for."""
    raw = path.read_text(encoding="utf-8")
    codec = ArubaAOSSCodec()
    had = {name.casefold() for name in _stanzas(raw)}
    got = {name.casefold() for name in _stanzas(codec.render(codec.parse(raw)))}
    assert got <= had, sorted(got - had)


@pytest.mark.parametrize("path", CAPTURES, ids=[p.name for p in CAPTURES])
def test_every_port_reads_back(path: Path) -> None:
    """The ports of a config are the ports of its own rendering: a
    stanza left out takes no record with it."""
    raw = path.read_text(encoding="utf-8")
    codec = ArubaAOSSCodec()
    first = codec.parse(raw)
    second = codec.parse(codec.render(first))

    def ports(tree: CanonicalIntent) -> dict[str, tuple]:
        return {
            iface.name: (iface.enabled, iface.interface_type, iface.lag_member_of, iface.switchport_mode,
                         iface.access_vlan, iface.trunk_native_vlan, sorted(iface.trunk_allowed_vlans))
            for iface in tree.interfaces if not re.match(r"(?i)vlan\d", iface.name)
        }

    assert ports(first) == ports(second)
    assert len(ports(first)) == len([i for i in first.interfaces if not re.match(r"(?i)vlan\d", i.name)])


def test_the_captures_are_found() -> None:
    """The two tests above pass on an empty list."""
    names = {path.name for path in CAPTURES}
    assert "kitchen_sink.cfg" in names and "user_contrib_2930m_wc1611.cfg" in names
    assert len(CAPTURES) >= 7


# ---------------------------------------------------------------------------
# A line counts only if the parser reads every port of it back
# ---------------------------------------------------------------------------

_HEAD = '; J9727A Configuration Editor; Created on release #WB.16.08.0001\nhostname "sw"\n'


def _read_back(tree: CanonicalIntent) -> tuple[dict[str, list[str]], set[str]]:
    """(the stanzas of the output, the records its own parser makes)."""
    codec = ArubaAOSSCodec()
    out = codec.render(tree)
    return _stanzas(out), {iface.name for iface in codec.parse(out).interfaces}


@pytest.mark.parametrize("spelt", ["trk1", "Trk1", "TRK1"])
def test_a_lag_comes_back_however_spelt(spelt: str) -> None:
    """A list writes a LAG ``Trk1`` and the parser reads it ``trk1``:
    that is the LAG coming back as itself, whichever spelling the tree
    has -- a job that renames a port-channel calls it ``Trk1``."""
    tree = _tree(
        CanonicalInterface(name=spelt, interface_type="ianaift:ieee8023adLag"),
        CanonicalInterface(name="7", lag_member_of=spelt),
        untagged=[spelt], lags=[CanonicalLAG(name=spelt, members=["7"])],
    )
    stanzas, records = _read_back(tree)
    assert stanzas == {} and {"trk1", "7"} <= records


def test_a_trunk_line_with_a_space() -> None:
    """``trunk 1,my port trk1 lacp`` is no ``trunk`` line to the
    parser, which takes the member list as one word.  Port ``1`` beside
    the name with the space keeps its stanza: left out, it came back
    in no record at all."""
    lag = CanonicalLAG(name="trk1", members=["1", "my port"], mode="active")
    tree = _tree(
        CanonicalInterface(name="1", lag_member_of="trk1"),
        CanonicalInterface(name="my port", lag_member_of="trk1"),
        CanonicalInterface(name="3"),
        untagged=["3"], lags=[lag],
    )
    out = ArubaAOSSCodec().render(tree)
    assert "trunk 1,my port trk1 lacp" in out
    stanzas, records = _read_back(tree)
    assert stanzas["1"] == ["enable"] and "3" not in stanzas
    assert {"1", "3"} <= records


_EOS_LAG = """hostname sw1
vlan 10
   name users
interface Ethernet1
   channel-group 1 mode active
interface Ethernet2
   channel-group 1 mode active
interface Ethernet3
   switchport access vlan 10
interface Port-Channel1
   switchport mode trunk
   switchport trunk allowed vlan 10
"""

_ROUTEROS_LAG = """/interface ethernet
set [ find default-name=ether2 ] name="my port"
/interface bonding
add mode=802.3ad name=bond1 slaves="my port,ether3"
/ip address
add address=10.0.0.2/24 interface=bond1
"""


@pytest.mark.parametrize(
    ("source", "text", "port_map", "port", "written"),
    [
        ("arista_eos", _EOS_LAG, {"Ethernet2": "my port"}, "Ethernet1", "1"),
        ("mikrotik_routeros", _ROUTEROS_LAG, {}, "ether3", "3"),
    ],
    ids=["a name the operator gave", "a name the config has"],
)
def test_the_port_beside_a_name_with_a_space(
    source: str, text: str, port_map: dict[str, str], port: str, written: str,
) -> None:
    """Two jobs in which a LAG member's name has a space in it: one
    through an entry of the port map, one because the source config
    names its port so.  The member BESIDE it is a port the job reports
    under a name, and the output read back has that port."""
    aoss = get_codec("aruba_aoss")
    job = run_plan_with_checked_names(get_codec(source), aoss, text, port_rename_map=dict(port_map))
    assert job.rendered is not None, job.error
    assert job.port_renames[port] == written
    assert re.search(r"^trunk \S*my port\S* trk1 lacp$", job.rendered, flags=re.M), job.rendered
    assert _stanzas(job.rendered)[written] == ["enable"]
    assert written in {iface.name for iface in aoss.parse(job.rendered).interfaces}


@pytest.mark.parametrize("name", ["01", "007", "A01", "trk01", "Trk007"])
def test_a_zero_padded_name_keeps_its_stanza(name: str) -> None:
    """A list writes a number without its leading zeros (``01`` is
    ``1``), so the line gives back another port than the one it was
    written for: the stanza is the only line that holds the name."""
    lag = name.lower().startswith("trk")
    tree = _tree(
        CanonicalInterface(
            name=name, switchport_mode="access", access_vlan=10,
            interface_type="ianaift:ieee8023adLag" if lag else "ianaift:ethernetCsmacd",
        ),
        CanonicalInterface(name="5", switchport_mode="access", access_vlan=10),
        untagged=[name, "5"],
    )
    stanzas, records = _read_back(tree)
    assert stanzas == {aoss_render._as_the_device_writes(name): ["enable"], "5": ["enable"]}
    assert {name.lower() if lag else name, "5"} <= records


def test_a_line_counts_whole_or_not_at_all() -> None:
    """``1-3`` is one name to the tree and a range of three ports to
    the parser.  The line that holds it gives back none of its ports,
    ``5`` included, though ``5`` alone would have come back."""
    tree = CanonicalIntent(
        interfaces=[
            CanonicalInterface(name="1-3", description="x"), CanonicalInterface(name="5"), CanonicalInterface(name="7"),
        ],
        vlans=[CanonicalVlan(id=10, untagged_ports=["1-3", "5"]), CanonicalVlan(id=20, untagged_ports=["7"])],
    )
    stanzas, records = _read_back(tree)
    assert stanzas["5"] == ["enable"] and "7" not in stanzas
    assert {"5", "7"} <= records


@pytest.mark.parametrize(
    ("name", "kept"),
    [("first\nsecond", set()), ("first\nhostname second", {"1", "2"})],
    ids=["the rest is the stanza's", "the rest is a line of the top"],
)
def test_a_list_under_a_cut_name(name: str, kept: set[str]) -> None:
    """A line break in a VLAN's name puts the rest of the name in
    column 0.  That line is the stanza's -- it enters no context and
    the top of the config does not read it -- so the lists under it are
    read and their ports need no stanza.  Where the rest IS a line of
    the top, the stanza ends there, and the lists under it are read by
    nobody: their ports keep their stanzas.  The line alone would read
    back either way, which is why the reader is asked of the stanza."""
    tree = CanonicalIntent(
        interfaces=[CanonicalInterface(name="1"), CanonicalInterface(name="2"), CanonicalInterface(name="3")],
        vlans=[
            CanonicalVlan(id=10, name=name, untagged_ports=["1"], tagged_ports=["2"]),
            CanonicalVlan(id=20, name="whole", untagged_ports=["3"]),
        ],
    )
    stanzas, records = _read_back(tree)
    assert set(stanzas) == kept
    assert {"1", "2", "3"} <= records
    assert aoss_parse._lists_read_from("vlan 10\n   untagged 1\n   tagged 2") == (["1"], ["2"])


@pytest.mark.parametrize(
    "line",
    [
        "trunk 23-24 trk1 lacp", "trunk A1,A2 Trk2 trunk", "trunk 1,my port trk1 lacp",
        "trunk 1/1-1/3,2/A1 trk3 dt-lacp", "trunk 01 trk1 lacp", "trunk 1-2000 trk1 lacp",
        " trunk 1-2 trk1 lacp", "trunk 1-2 trk1", "untagged 1-2", "trunk 1-2\ntrk1 lacp",
    ],
    ids=["a range", "two names", "a space in a name", "stack names", "zero-padded", "a span too wide",
         "indented", "no type", "not a trunk line", "cut in two"],
)
def test_a_trunk_line_as_the_parse_reads_it(line: str) -> None:
    """What the renderer is told of a ``trunk`` line is what a parse of
    a config that holds the line makes of it."""
    parsed = [member for lag in ArubaAOSSCodec().parse(_HEAD + line + "\n").lags for member in lag.members]
    assert aoss_parse._members_read_from(line) == parsed


@pytest.mark.parametrize(
    "stanza",
    [
        "vlan 10\n   untagged 1-4,A1\n   tagged Trk1,7",
        'vlan 10\n   name "V 10"\n   untagged 1,my port\n   tagged 01',
        'vlan 10\n   name "cut\nhere"\n   untagged 1-4',
        'vlan 10\n   name "cut\nhostname here"\n   untagged 1-4',
        "vlan 10\n   untagged 1-4\n   no untagged 2",
        "vlan 10\n   tagged 1-2000",
        " vlan 10\n   untagged 1-4",
        "vlan ten\n   untagged 1-4",
    ],
    ids=["both lists", "a space, a zero", "a name cut in two", "a name cut by a line of the top",
         "a port taken out", "a span too wide", "indented", "no header"],
)
def test_a_vlan_stanza_as_the_parse_reads_it(stanza: str) -> None:
    """...and the same of a VLAN's lists, read where they stand.  (A
    parse puts a list in port order when it is done; the names are
    what is compared.)"""
    vlans = [v for v in ArubaAOSSCodec().parse(_HEAD + stanza + "\n   exit\n").vlans if v.id == 10]
    parsed = (sorted(vlans[0].untagged_ports), sorted(vlans[0].tagged_ports)) if vlans else ([], [])
    untagged, tagged = aoss_parse._lists_read_from(stanza)
    assert (sorted(untagged), sorted(tagged)) == parsed


_OWN = [str(n) for n in range(1, 25)] + ["A1", "A2", "B1", "1/1", "1/2", "2/1", "1/A1", "1/A2", "Trk1", "Trk2", "trk3"]
_ODD = [
    "a1", "1/1/1", "uplink", "ge-0/0/1", "Ethernet1", "1-2", "my port", "lag 1", "ae0", "A", "1/", "Trk", "0",
    "01", "007", "A01", "trk01", "1,2", "5 ", "A1-A3", "1/1-1/3", "Trk1-Trk2", "x_y", "loopback0", "1/1.5",
]


def _a_tree(rng: random.Random) -> CanonicalIntent:
    names = rng.sample(_OWN, rng.randint(3, 14)) + rng.sample(_ODD, rng.randint(0, 3))
    names = [name.lower() if name.lower().startswith("trk") else name for name in names]
    ports = []
    for name in names:
        if rng.random() < 0.85:
            ports.append(CanonicalInterface(
                name=name, enabled=rng.random() > 0.1, description="d" if rng.random() < 0.1 else "",
                interface_type="ianaift:ieee8023adLag" if name.startswith("trk") else "ianaift:ethernetCsmacd",
            ))
    vlans = []
    for vid in rng.sample(range(2, 60), rng.randint(0, 4)):
        untagged = rng.sample(names, rng.randint(0, min(5, len(names))))
        tagged = [name for name in rng.sample(names, rng.randint(0, min(5, len(names)))) if name not in untagged]
        vlans.append(CanonicalVlan(id=vid, name=rng.choice(["V", "two words", "cut\nhere", "cut\nhostname here"]),
                                   untagged_ports=untagged, tagged_ports=tagged))
    ports_only = [name for name in names if not name.startswith("trk")]
    lags = []
    for name in [n for n in names if n.startswith("trk")][:2]:
        members = rng.sample(ports_only, rng.randint(0, min(3, len(ports_only))))
        if members and rng.random() < 0.3:
            members.insert(rng.randrange(len(members) + 1), rng.choice(["my port", "lag 1"]))
        lags.append(CanonicalLAG(name=name, members=members))
    return CanonicalIntent(interfaces=ports, vlans=vlans, lags=lags)


def _what_reads_back(text: str) -> tuple:
    tree = ArubaAOSSCodec().parse(text)
    records = collections.Counter(
        json.dumps([i.name, i.enabled, i.interface_type, i.description, i.lag_member_of, i.switchport_mode,
                    i.access_vlan, i.trunk_native_vlan, sorted(i.trunk_allowed_vlans)])
        for i in tree.interfaces
    )
    return (
        records,
        sorted((v.id, sorted(v.untagged_ports), sorted(v.tagged_ports)) for v in tree.vlans),
        sorted((lag.name, sorted(lag.members)) for lag in tree.lags),
    )


def test_a_stanza_left_out_takes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The experiment that needs no list of shapes: trees of the
    device's names and of names it does not have, each rendered twice
    -- as it is, and with every stanza written -- and both outputs
    parsed.  They read back alike, record for record."""
    rng = random.Random(1611)
    trees = [_a_tree(rng) for _ in range(600)]
    codec = ArubaAOSSCodec()
    as_it_is = [codec.render(tree.model_copy(deep=True)) for tree in trees]
    monkeypatch.setattr(aoss_render, "_given_back", lambda read, written: [])
    every_stanza = [codec.render(tree.model_copy(deep=True)) for tree in trees]
    # The second rendering is what the first is compared with, so it is
    # looked at by itself: every record under one of the device's names
    # has its stanza there.  (A path that left a stanza out without
    # asking would leave it out of both, and the two would agree.)
    for tree, text in zip(trees, every_stanza):
        written = set(_stanzas(text))
        ours = {
            aoss_render._as_the_device_writes(iface.name) for iface in tree.interfaces
            if re.fullmatch(r"\d+(/[A-Za-z]?\d+)?|trk\d+", iface.name)
        }
        assert ours <= written, sorted(ours - written)
    left_out = sum(a != b for a, b in zip(as_it_is, every_stanza))
    assert left_out > 300, f"a stanza was left out of {left_out} outputs only: this compares little"
    # ... and the trees hold what the parser cannot read, of both kinds.
    spaced = sum(bool(re.search(r"^trunk .*(my port|lag 1)", text, flags=re.M)) for text in as_it_is)
    # A stanza a line of the top cuts short: the rest of a name.
    cut_short = sum("\nhostname here" in text for text in as_it_is)
    assert min(spaced, cut_short) > 40, f"{spaced} trunk lines with a space, {cut_short} stanzas cut short"
    differ = [n for n, (a, b) in enumerate(zip(as_it_is, every_stanza)) if _what_reads_back(a) != _what_reads_back(b)]
    assert differ == [], f"{len(differ)} of {len(trees)} read back differently; the first: {as_it_is[differ[0]]!r}"
