"""A trunk that states no native VLAN has its platform's, in the tree.

What a trunk carries untagged when its text has no native line is its
platform's own default, and the platforms differ: VLAN 1 on IOS-XE,
NX-OS, EOS and AOS-CX, none on Junos, the default VLAN of the switch
on OS10.  (The vendors' sentences are in
``docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md``,
the table "And when the config states no untagged VLAN at all".)  The
canonical tree had "not stated" for all of them.  VLAN 1 of a Cisco,
Arista or AOS-CX trunk was a tagged VLAN there like any other, and
was written TAGGED on the targets that state the untagged VLAN in a
line of their own.

Each of the four parsers now puts the default
(``TRUNK_THAT_STATES_NO_NATIVE`` in ``codecs/_helpers.py``): a port
that SAYS it is a trunk and states no native VLAN has VLAN 1 where
its list holds VLAN 1, and none where the list leaves VLAN 1 out.
The default is a trunk's.  A port in another mode that keeps trunk
lines, and a port a parser took for a trunk from a trunk line alone,
are given nothing from it, as they are given nothing of the
platform's list.  This module is the four parsers on small texts,
one statement at a time, with what each tree has written beside it
by hand -- the port's native VLAN, and who is in VLAN 1 -- and the
three renderers that leave out the native line no capture of theirs
prints.  Jobs through every pair, and the committed captures, are in
``test_the_list_holds_the_native_vlan.py``.

What is not here: OS10 and Junos fill nothing in, and nothing is
filled in under the words that say a native VLAN is sent tagged.
"""

from __future__ import annotations

from typing import Any

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalInterface
from netcanon.migration.codecs._helpers import (
    TrunksByName,
    tags_every_native_vlan,
    tags_its_native_vlan,
)
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit

IOSXE, NXOS, EOS, AOSCX = "cisco_iosxe_cli", "cisco_nxos", "arista_eos", "aruba_aoscx"
SWITCHPORT = (IOSXE, NXOS, EOS)
FOUR = (*SWITCHPORT, AOSCX)

_INDENT = {IOSXE: " ", NXOS: "  ", EOS: "   ", AOSCX: "    "}
_PORT = {IOSXE: "GigabitEthernet1/0/{}", NXOS: "Ethernet1/{}", EOS: "Ethernet{}", AOSCX: "1/1/{}"}
_LAG = {IOSXE: "Port-channel1", NXOS: "port-channel1", EOS: "Port-Channel1", AOSCX: "lag 1"}
_MEMBER = {IOSXE: "channel-group 1 mode active", NXOS: "channel-group 1 mode active",
           EOS: "channel-group 1 mode active", AOSCX: "lag 1"}

#: A trunk's lines, in each grammar.  AOS-CX states a trunk by its
#: ``vlan trunk`` lines and has no mode line.
TRUNK = {IOSXE: ("switchport mode trunk",), NXOS: ("switchport mode trunk",), EOS: ("switchport mode trunk",),
         AOSCX: ()}


def allowed(codec: str, ids: str) -> str:
    return f"vlan trunk allowed {ids}" if codec == AOSCX else f"switchport trunk allowed vlan {ids}"


def native(codec: str, vid: int) -> str:
    return f"vlan trunk native {vid}" if codec == AOSCX else f"switchport trunk native vlan {vid}"


def config(codec: str, *ports: tuple[str, ...], top: tuple[str, ...] = (), names: tuple[str, ...] = ()) -> str:
    """VLANs 10 and 20 declared, and one stanza for each of *ports*,
    numbered from 1 unless *names* gives a name."""
    out = ["hostname sw1", *top]
    out += ["vlan 10,20"] if codec == NXOS else [line for vid in (10, 20) for line in (f"vlan {vid}",)]
    for at, lines in enumerate(ports, 1):
        name = names[at - 1] if at <= len(names) and names[at - 1] else _PORT[codec].format(at)
        out.append(f"interface {name}")
        if codec == AOSCX:
            out += ["    no shutdown", "    no routing"]
        out += [_INDENT[codec] + line for line in lines]
    return "\n".join(out) + "\n"


def read(codec: str, text: str) -> tuple[list[tuple[Any, ...]], tuple[list[str], list[str]] | None, CanonicalIntent]:
    """(each port's (mode, native VLAN, whether its list holds VLAN 1),
    VLAN 1's (tagged ports, untagged ports) or ``None``, the tree)."""
    tree = get_codec(codec).parse(text)
    ports = [
        (iface.switchport_mode, iface.trunk_native_vlan, 1 in iface.trunk_allowed_vlans)
        for iface in tree.interfaces if not iface.name.lower().startswith("vlan")
    ]
    one = [(vlan.tagged_ports, vlan.untagged_ports) for vlan in tree.vlans if vlan.id == 1]
    return ports, (one[0] if one else None), tree


def port(codec: str, at: int = 1) -> str:
    return _PORT[codec].format(at)


# ---------------------------------------------------------------------------
# 1. The four parsers, one statement at a time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("codec", FOUR)
class TestWhereTheListHoldsVlanOne:
    def test_the_list_names_it(self, codec: str) -> None:
        ports, one, tree = read(codec, config(codec, (*TRUNK[codec], allowed(codec, "1,10,20"))))
        assert ports == [("trunk", 1, True)]
        assert one == ([], [port(codec)])
        # The record is the projection's, for a single VLAN a port is
        # bound to: it has no name, and nothing else.
        (record,) = [vlan for vlan in tree.vlans if vlan.id == 1]
        assert (record.name, record.description, record.ipv4_addresses) == ("", "", [])

    def test_the_list_leaves_it_out(self, codec: str) -> None:
        """Nothing is filled in: no native VLAN is put that the list
        does not hold, and VLAN 1 is not made."""
        for ids in ("10,20", "2-4094"):
            ports, one, _tree = read(codec, config(codec, (*TRUNK[codec], allowed(codec, ids))))
            assert ports == [("trunk", None, False)], ids
            assert one is None, ids

    def test_no_list_at_all(self, codec: str) -> None:
        """No allowed line is every VLAN on these four (on AOS-CX the
        one line ``vlan trunk allowed all``): the list is resolved
        first, and holds VLAN 1."""
        lines = (allowed(codec, "all"),) if codec == AOSCX else TRUNK[codec]
        ports, one, tree = read(codec, config(codec, lines))
        assert ports == [("trunk", 1, True)]
        assert one == ([], [port(codec)])
        assert len(tree.interfaces[0].trunk_allowed_vlans) == 4094
        assert sorted(vlan.id for vlan in tree.vlans) == [1, 10, 20]

    def test_a_native_line_is_what_it_says(self, codec: str) -> None:
        """A stated native VLAN is never replaced: VLAN 1 on its list
        or off it, and another id beside a list that holds VLAN 1."""
        on = read(codec, config(codec, (*TRUNK[codec], native(codec, 1), allowed(codec, "1,10,20"))))
        assert (on[0], on[1]) == ([("trunk", 1, True)], ([], [port(codec)]))
        off = read(codec, config(codec, (*TRUNK[codec], native(codec, 1), allowed(codec, "10,20"))))
        assert (off[0], off[1]) == ([("trunk", 1, False)], ([], []))          # stated, and not carried
        other = read(codec, config(codec, (*TRUNK[codec], native(codec, 10), allowed(codec, "1,10,20"))))
        assert (other[0], other[1]) == ([("trunk", 10, True)], ([port(codec)], []))
        outside = read(codec, config(codec, (*TRUNK[codec], native(codec, 10), allowed(codec, "1,20"))))
        assert (outside[0], outside[1]) == ([("trunk", 10, True)], ([port(codec)], []))

    def test_a_port_with_no_trunk_line_is_left(self, codec: str) -> None:
        access = "vlan access 10" if codec == AOSCX else "switchport access vlan 10"
        ports, one, _tree = read(codec, config(codec, (access,)))
        assert ports == [("access", None, False)] and one is None

    def test_a_lag_and_its_members(self, codec: str) -> None:
        """Each record is given the default by its own lines: a member
        that repeats the LAG's lines has it, and one that states only
        its membership has no list and is left alone."""
        lines = (*TRUNK[codec], allowed(codec, "1,10,20"))
        both = config(codec, lines, (*lines, _MEMBER[codec]), names=(_LAG[codec],))
        if codec != AOSCX:      # (an AOS-CX member states `lag N` and no VLAN line of its own)
            ports, one, _tree = read(codec, both)
            assert ports == [("trunk", 1, True), ("trunk", 1, True)]
            assert one is not None and one[0] == [] and len(one[1]) == 2
        alone = config(codec, lines, (_MEMBER[codec],), names=(_LAG[codec],))
        ports, one, _tree = read(codec, alone)
        assert ports == [("trunk", 1, True), (None, None, False)]
        assert one is not None and one[0] == [] and len(one[1]) == 1


@pytest.mark.parametrize("codec", SWITCHPORT)
class TestTheWordsThatTagIt:
    """``vlan dot1q tag native`` and ``switchport trunk native vlan
    tag`` say the native VLAN is sent TAGGED.  They are not read into
    the tree, and a native VLAN put there would be read as untagged:
    nothing is filled in under them."""

    def test_for_every_trunk_of_the_config(self, codec: str) -> None:
        text = config(codec, (*TRUNK[codec], allowed(codec, "1,10,20")), TRUNK[codec], top=("vlan dot1q tag native",))
        ports, one, _tree = read(codec, text)
        assert ports == [("trunk", None, True), ("trunk", None, True)]
        assert one == ([port(codec, 1), port(codec, 2)], [])
        assert tags_every_native_vlan(text) and not tags_every_native_vlan(text.replace("vlan dot1q", " vlan dot1q"))

    def test_for_one_trunk(self, codec: str) -> None:
        lines = (*TRUNK[codec], allowed(codec, "1,10,20"))
        text = config(codec, (*lines, "switchport trunk native vlan tag"), lines)
        ports, one, _tree = read(codec, text)
        assert ports == [("trunk", None, True), ("trunk", 1, True)]
        assert one == ([port(codec, 1)], [port(codec, 2)])

    def test_the_words_are_whole_lines(self, codec: str) -> None:
        assert tags_its_native_vlan("  switchport trunk native vlan tag") and tags_its_native_vlan(
            "switchport trunk native vlan tag\r")
        for line in (" switchport trunk native vlan 10", " description switchport trunk native vlan tag",
                     " no switchport trunk native vlan tag", " switchport trunk native vlan tagged"):
            assert not tags_its_native_vlan(line), line
        for text in ("description vlan dot1q tag native\n", "no vlan dot1q tag native\n", "vlan dot1q tag native x\n"):
            assert not tags_every_native_vlan(text), text
        assert tags_every_native_vlan("hostname a\r\nvlan dot1q tag native\r\ninterface X\r\n")


def test_aoscx_tag_is_on_the_native_line() -> None:
    """AOS-CX writes ``tag`` after a native VLAN's id, so a port that
    has the word states its native VLAN: it is read as before, and
    nothing is filled in beside it."""
    for vid in (1, 10):
        ports, _one, _tree = read(AOSCX, config(AOSCX, (f"vlan trunk native {vid} tag", allowed(AOSCX, "1,10,20"))))
        assert ports == [("trunk", vid, True)]


class TestAPortThatDoesNotSayItIsATrunk:
    """The default native VLAN is a trunk's.  A port that keeps
    trunk lines in another mode, and a port a parser took for a
    trunk from a trunk line alone, are given nothing from it -- as
    they are given nothing of the platform's list."""

    def test_iosxe_in_another_mode(self) -> None:
        """IOS-XE keeps trunk lines on a port in any mode.  The record
        has its list and NO native VLAN, and the port is on no VLAN's
        member list: it is no trunk."""
        for mode_line, mode in (("switchport mode dynamic auto", "dynamic"), (None, None),
                                ("switchport mode access", "access")):
            lines = tuple(line for line in (mode_line, allowed(IOSXE, "1,10,20")) if line)
            ports, one, _tree = read(IOSXE, config(IOSXE, lines))
            assert ports == [(mode, None, True)], mode_line
            assert one is None, mode_line
        ports, one, _tree = read(IOSXE, config(IOSXE, ("switchport mode dynamic auto",)))
        assert ports == [("dynamic", None, False)] and one is None
        # A second stanza of the name that says it is a trunk makes a
        # trunk of ITS record, which has the default; the record of the
        # stanza that does not say so is still no trunk, and has none.
        twice = config(IOSXE, (allowed(IOSXE, "1,10,20"),), TRUNK[IOSXE], names=(port(IOSXE),) * 2)
        ports, one, _tree = read(IOSXE, twice)
        assert ports == [(None, None, True), ("trunk", 1, True)] and one == ([], [port(IOSXE)])
        ports, _one, _tree = read(IOSXE, config(IOSXE, (native(IOSXE, 99),)))
        assert ports == [(None, 99, False)]

    def test_iosxe_keeps_the_native_line_it_states(self) -> None:
        """...and a native line such a port STATES comes back, VLAN 1
        beside a list that holds it among them.  On a trunk that
        line is the default and is left out; here no default is put
        when the output is read, so a line left out would be lost."""
        for mode_lines, mode in ((("switchport mode access", "switchport access vlan 10"), "access"), ((), None)):
            text = config(IOSXE, (*mode_lines, native(IOSXE, 1), allowed(IOSXE, "1,10,20")))
            ports, one, _tree = read(IOSXE, text)
            assert ports == [(mode, 1, True)] and one is None, mode
            rendered = get_codec(IOSXE).render(get_codec(IOSXE).parse(text))
            assert [line.strip() for line in rendered.splitlines()].count("switchport trunk native vlan 1") == 1
            assert read(IOSXE, rendered)[0] == ports, mode

    @pytest.mark.parametrize("codec", [NXOS, EOS])
    def test_a_trunk_line_and_no_mode_line(self, codec: str) -> None:
        """These two parsers take a port for a trunk from a trunk
        line alone.  Such a trunk is given nothing from the platform's
        LIST, and nothing from its default native VLAN either: VLAN
        1 on its own list is a tagged VLAN of it, as the text has
        it."""
        ports, one, _tree = read(codec, config(codec, (allowed(codec, "1,10,20"),)))
        assert ports == [("trunk", None, True)] and one == ([port(codec)], [])
        # ... and the same port once its interface says it is a
        # trunk: in the same stanza, or in another of its name.
        said = config(codec, (allowed(codec, "1,10,20"), "switchport mode trunk"))
        ports, one, _tree = read(codec, said)
        assert ports == [("trunk", 1, True)] and one == ([], [port(codec)])
        twice = config(codec, (allowed(codec, "1,10,20"),), ("switchport mode trunk",), names=(port(codec),) * 2)
        ports, one, _tree = read(codec, twice)
        assert set(ports) == {("trunk", 1, True)} and one == ([], [port(codec)])
        # A native line alone: no list is made up for it, and no default.
        ports, one, tree = read(codec, config(codec, (native(codec, 99),)))
        assert ports == [("trunk", 99, False)] and one is None
        assert tree.interfaces[0].trunk_allowed_vlans == []


class TestAnInterfaceNotAStanza:
    """What is stated is stated by the interface.  A stanza met again
    is the same interface, and a native line in either is its own."""

    @pytest.mark.parametrize("codec", [IOSXE, NXOS])
    def test_a_native_line_in_the_other_stanza(self, codec: str) -> None:
        """Two stanzas of one interface, each of which says it is a
        trunk, so each record has the interface's list -- and one
        states the native VLAN.  The record of the other is owed no
        default: the interface has a native VLAN."""
        first = (*TRUNK[codec], native(codec, 99), allowed(codec, "1,10,20"))
        for order in ((first, TRUNK[codec]), (TRUNK[codec], first)):
            text = config(codec, *order, names=(port(codec), port(codec)))
            tree = get_codec(codec).parse(text)
            assert [iface.trunk_allowed_vlans for iface in tree.interfaces] == [[1, 10, 20], [1, 10, 20]], order
            assert sorted(str(iface.trunk_native_vlan) for iface in tree.interfaces) == ["99", "None"], order
            assert [vlan.untagged_ports for vlan in tree.vlans if vlan.id == 1] == [[]], order

    def test_aoscx_a_native_line_in_the_other_stanza(self) -> None:
        """AOS-CX states a trunk by its ``vlan trunk`` lines, so a
        stanza that states only the native VLAN is a trunk's, and so
        is one that states only the list.  The record of the second
        is owed no default -- the interface has a native VLAN -- and
        ONE ``vlan trunk native`` line comes back, the one stated."""
        listed, stated = (allowed(AOSCX, "1,10,20"),), (native(AOSCX, 20),)
        for order in ((listed, stated), (stated, listed)):
            text = config(AOSCX, *order, names=(port(AOSCX), port(AOSCX)))
            tree = get_codec(AOSCX).parse(text)
            assert [iface.switchport_mode for iface in tree.interfaces] == ["trunk", "trunk"], order
            assert sorted(str(iface.trunk_native_vlan) for iface in tree.interfaces) == ["20", "None"], order
            assert [vlan.untagged_ports for vlan in tree.vlans if vlan.id == 1] == [[]], order
            written = [line for line in _lines(AOSCX, text) if line.startswith("vlan trunk native")]
            assert written == ["vlan trunk native 20"], order

    def test_the_words_in_the_other_stanza(self) -> None:
        lines = (*TRUNK[IOSXE], allowed(IOSXE, "1,10,20"))
        text = config(IOSXE, lines, ("switchport trunk native vlan tag",), names=(port(IOSXE), port(IOSXE)))
        assert [iface.trunk_native_vlan for iface in get_codec(IOSXE).parse(text).interfaces] == [None, None]

    def test_by_hand(self) -> None:
        """``TrunksByName`` itself: the default is given after the
        list, to a trunk whose interface says it is one and states
        neither a native VLAN nor the words, and from no table but
        the codec's own."""
        def settled(
            codec: str, *said: tuple[str, ...], says: bool = True, mode: str | None = "trunk",
        ) -> CanonicalInterface:
            trunks = TrunksByName(codec)
            if says:
                trunks.says_trunk("a")
            for what in said:
                getattr(trunks, what[0])(*what[1:])
            iface = trunks.made("a", CanonicalInterface(name="a", switchport_mode=mode))
            trunks.settle()
            return iface

        for codec in FOUR:
            assert settled(codec).trunk_native_vlan == 1, codec                 # no list: every VLAN
            assert settled(codec, ("allowed_is", "a", [1, 10])).trunk_native_vlan == 1, codec
            assert settled(codec, ("allowed_is", "a", [10])).trunk_native_vlan is None, codec
            assert settled(codec, ("native_line", "a")).trunk_native_vlan is None, codec
            assert settled(codec, ("native_is_tagged", "a")).trunk_native_vlan is None, codec
            assert settled(codec, ("native_is_tagged",)).trunk_native_vlan is None, codec
            assert settled(codec, ("native_is_tagged", "another")).trunk_native_vlan == 1, codec
            assert settled(codec, ("native_line", "another")).trunk_native_vlan == 1, codec
            # A trunk the parser inferred -- the record is a trunk and
            # its interface never says so -- is given none, and keeps
            # the list its lines name.  Neither is a record in
            # another mode, whatever its interface says elsewhere.
            inferred = settled(codec, ("allowed_is", "a", [1, 10]), says=False)
            assert (inferred.trunk_native_vlan, inferred.trunk_allowed_vlans) == (None, [1, 10]), codec
            assert settled(codec, ("says_trunk", "another"), says=False).trunk_native_vlan is None, codec
            for mode in ("access", "dynamic", None):
                other = settled(codec, ("allowed_is", "a", [1, 10]), mode=mode)
                assert (other.trunk_native_vlan, other.trunk_allowed_vlans) == (None, [1, 10]), (codec, mode)
        for codec in ("dell_os10", "juniper_junos"):
            assert settled(codec, ("allowed_is", "a", [1, 10])).trunk_native_vlan is None, codec

    def test_a_stated_native_vlan_is_kept(self) -> None:
        trunks = TrunksByName(NXOS)
        trunks.says_trunk("a")
        iface = trunks.made("a", CanonicalInterface(name="a", switchport_mode="trunk", trunk_native_vlan=30))
        trunks.settle()
        assert iface.trunk_native_vlan == 30


@pytest.mark.parametrize("codec,text", [
    ("juniper_junos",
     "set vlans one vlan-id 1\nset interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk\n"
     "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members one\n"),
    ("juniper_junos",
     "set vlans ten vlan-id 10\nset interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk\n"
     "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members all\n"),
    ("dell_os10",
     "interface vlan1\n no shutdown\ninterface ethernet1/1/1\n no shutdown\n switchport mode trunk\n"
     " switchport trunk allowed vlan 1,10\n"),
])
def test_where_there_is_no_id_nothing_is_put(codec: str, text: str) -> None:
    """A Junos trunk has no default, and an OS10 trunk's is its
    switch's default VLAN, which its text does not give: VLAN 1 on
    the list of either is a tagged VLAN, as the text has it."""
    tree = get_codec(codec).parse(text)
    (trunk,) = [iface for iface in tree.interfaces if iface.switchport_mode == "trunk"]
    assert trunk.trunk_native_vlan is None and 1 in trunk.trunk_allowed_vlans
    assert not [vlan.untagged_ports for vlan in tree.vlans if vlan.untagged_ports]


# ---------------------------------------------------------------------------
# 2. The three renderers leave out what their device does not print
# ---------------------------------------------------------------------------


def _lines(codec: str, text: str, target: str | None = None) -> list[str]:
    return [line.strip() for line in get_codec(target or codec).render(get_codec(codec).parse(text)).splitlines()]


@pytest.mark.parametrize("codec", SWITCHPORT)
class TestNoNativeLineForTheDefault:
    def test_a_default_trunk_comes_back_as_it_went(self, codec: str) -> None:
        for lines in (TRUNK[codec], (*TRUNK[codec], allowed(codec, "1,10,20"))):
            out = _lines(codec, config(codec, lines))
            assert not [line for line in out if "native" in line], (lines, out)
            assert out.count("switchport mode trunk") == 1

    def test_a_default_spelt_out_gets_no_line(self, codec: str) -> None:
        out = _lines(codec, config(codec, (*TRUNK[codec], native(codec, 1), allowed(codec, "1,10,20"))))
        assert not [line for line in out if "native" in line], out

    def test_a_statement_is_written(self, codec: str) -> None:
        """VLAN 1 beside a list that leaves it out, and any other id."""
        out = _lines(codec, config(codec, (*TRUNK[codec], native(codec, 1), allowed(codec, "10,20"))))
        assert out.count("switchport trunk native vlan 1") == 1, out
        out = _lines(codec, config(codec, (*TRUNK[codec], native(codec, 10), allowed(codec, "1,10,20"))))
        assert out.count("switchport trunk native vlan 10") == 1, out

    def test_from_another_platform_too(self, codec: str) -> None:
        """An AOS-CX trunk states ``vlan trunk native 1``: on these
        three that is the default, and no line."""
        text = config(AOSCX, ("vlan trunk native 1", "vlan trunk allowed 1,10,20"))
        tree = get_codec(AOSCX).parse(text)
        tree.interfaces[0].name = port(codec)
        for vlan in tree.vlans:
            vlan.untagged_ports = [port(codec) for _name in vlan.untagged_ports]
            vlan.tagged_ports = [port(codec) for _name in vlan.tagged_ports]
        out = [line.strip() for line in get_codec(codec).render(tree).splitlines()]
        assert "switchport mode trunk" in out and not [line for line in out if "native" in line], out


def test_aoscx_prints_its_native_line() -> None:
    """Every AOS-CX trunk of the captures states ``vlan trunk native
    1``, so a trunk that stated none is written it."""
    out = _lines(AOSCX, config(AOSCX, (allowed(AOSCX, "1,10,20"),)))
    assert out.count("vlan trunk native 1") == 1 and out.count("vlan trunk allowed 1,10,20") == 1, out


# ---------------------------------------------------------------------------
# 3. The VLAN a default brings is declared like any other
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("codec", FOUR)
def test_a_default_trunks_vlan_one_is_declared(codec: str) -> None:
    """A default trunk brings VLAN 1 into the tree, with the trunk as
    its untagged member, and every renderer writes a ``vlan`` line
    for every VLAN of the tree.  So the text comes back with VLAN 1
    declared, though it had no word for it: no rule decides from
    the tree whether the text had the line.  (On NX-OS and AOS-CX
    every capture names VLAN 1 on a ``vlan`` line; on IOS-XE and EOS
    no real capture does, and the line is one the output gains.)"""
    lines = (allowed(codec, "all"),) if codec == AOSCX else TRUNK[codec]
    text = config(codec, lines)
    assert "vlan 1" not in [line.strip() for line in text.splitlines()]
    assert sorted(vlan.id for vlan in get_codec(codec).parse(text).vlans) == [1, 10, 20]
    out = _lines(codec, text)
    assert "vlan 1" in out or "vlan 1,10,20" in out, out
    # ... and VLANs 10 and 20 are declared as they were.
    assert {"vlan 10", "vlan 20"} <= set(out) or "vlan 1,10,20" in out, out


@pytest.mark.parametrize("codec", [IOSXE, EOS])
def test_a_vlan_one_line_of_the_text_comes_back(codec: str) -> None:
    """A ``vlan 1`` line the text HAS, beside a default trunk, is
    written again: nothing takes a declared VLAN out of an output."""
    text = config(codec, TRUNK[codec]).replace("vlan 10\n", "vlan 1\nvlan 10\n", 1)
    assert [line.strip() for line in text.splitlines()].count("vlan 1") == 1
    assert _lines(codec, text).count("vlan 1") == 1


@pytest.mark.parametrize("codec", [IOSXE, EOS])
def test_no_vlan_one_where_no_trunk_carries_it(codec: str) -> None:
    """No default, no record, no line: a trunk whose list leaves
    VLAN 1 out, and a port that keeps a trunk line and does not say
    it is a trunk (IOS-XE, where such a port is no trunk in the
    tree)."""
    assert "vlan 1" not in _lines(codec, config(codec, (*TRUNK[codec], allowed(codec, "10,20"))))
    if codec == IOSXE:
        assert "vlan 1" not in _lines(codec, config(codec, ("switchport mode dynamic auto", allowed(codec, "1-4094"))))
