"""A native VLAN its trunk's list leaves out is said in the AOS-S output.

A trunk of IOS-XE, NX-OS, EOS, AOS-CX or Junos can state a native VLAN
its allowed list leaves out.  In the tree that VLAN is stated and not
carried, so no VLAN lists the port ``untagged`` and the AOS-S renderer,
which writes a VLAN's ``untagged`` line from that list, writes none for
it.  An output that stopped there said nothing at all, in a job that
said ``completed`` -- and by HPE's own sentences an AOS-S port is in
the default VLAN until it is removed from it (the sentences are in
``docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md``).

So the stanza of that VLAN carries one ``; review:`` line for each such
name.  What is held here:

* the line, WHOLE, in its two forms, typed out below and taken from no
  renderer: the port, the VLAN by the id the OUTPUT has for it, that
  the allowed list leaves it out (a fact of the text the trunk was read
  from -- what the source switch does with such a VLAN is not the same
  sentence for every vendor, and is not said), that no ``untagged``
  line is written, what an AOS-S switch does, and what to check.  For a
  port that is what HPE's two sentences say and no more: it is in the
  default VLAN, and remains there until it is removed.  ("Untagged" is
  in neither sentence, and is not in the line.)  For a trunk group
  (``Trk<n>``), and for a port the same output puts on a ``trunk``
  line, no sentence was found, and the line says "not established";
* which names get which form, decided from the tree's LAGs;
* where it stands and in which order, and for which names: every
  interface record that is such a trunk, as for a ``tagged`` line -- a
  LAG under ``Trk<n>`` and a member port that states the same lines
  under its own name -- whether the trunk is up or shut, and however
  its list is written around the VLAN;
* that it is a comment: the AOS-S parser reads the output back to the
  tree it reads without the line;
* a native VLAN the tree has no record of has no stanza, and is said
  where the stanza would stand;
* and the trunks of the committed captures that it is written for,
  found by reading each source by its own grammar
  (``test_the_list_holds_the_native_vlan.py`` holds every job to it;
  the names and the form of each are pinned here).
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalVlan,
)
from netcanon.migration.canonical.transforms import project_switchport_to_vlan
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_the_list_holds_the_native_vlan import (
    CAPTURES,
    GROUP_FORM,
    HOW_IT_IS_STATED,
    PORT_FORM,
    SAID_OF_A_GROUP,
    SAID_OF_A_PORT,
    in_a_trunk_line,
    is_a_trunk_group,
    read_tree,
    said_how,
    said_on_aoss,
)

pytestmark = pytest.mark.unit

_REVIEW = "; review: port "

#: The line for port 5 and VLAN 10, and the one for the trunk group
#: Trk1, each as the output has it in a stanza.  Typed in full, here.
_OF_PORT_5 = (
    "   ; review: port 5 -- native VLAN 10 is stated for this trunk and its allowed list leaves it out, so no "
    "untagged line is written for this port; in the factory default configuration an AOS-S port is in the "
    "default VLAN (VID 1), and it remains there until it is removed -- check what this port is to carry untagged"
)
_OF_TRK1 = (
    "   ; review: port Trk1 -- native VLAN 10 is stated for this trunk and its allowed list leaves it out, so no "
    "untagged line is written for this port; which VLAN an AOS-S trunk group, or a port that is in one, is in "
    "by default is not established -- check what this port is to carry untagged"
)

#: Every id but VLAN 10: what ``allowed vlan except 10``, ``remove
#: 10`` and ``1-9,11-4094`` all are.
_ALL_BUT_10 = [vid for vid in range(1, 4095) if vid != 10]


def _trunk(name: str, native: int | None, allowed: list[int], **more) -> CanonicalInterface:
    return CanonicalInterface(
        name=name, switchport_mode="trunk", trunk_native_vlan=native, trunk_allowed_vlans=list(allowed), **more,
    )


def _tree(*ports: CanonicalInterface, vlans: tuple[int, ...] = (10, 20, 30)) -> CanonicalIntent:
    """The ports, and the VLANs' member lists as a parser leaves them."""
    tree = CanonicalIntent(vlans=[CanonicalVlan(id=vid) for vid in vlans], interfaces=list(ports))
    project_switchport_to_vlan(tree, keep=set(vlans))
    return tree


def _stanza(text: str, vid: int) -> list[str]:
    """The lines of ``vlan <vid>``, to its ``exit``."""
    lines = text.splitlines()
    at = lines.index(f"vlan {vid}")
    return lines[at + 1:lines.index("   exit", at)]


def _said(text: str) -> list[str]:
    return [line for line in text.splitlines() if _REVIEW in line]


def _of_a_port(port: str, native: int = 10) -> str:
    return "   " + SAID_OF_A_PORT.format(port=port, native=native)


def _of_a_group(port: str, native: int = 10) -> str:
    return "   " + SAID_OF_A_GROUP.format(port=port, native=native)


@pytest.fixture(scope="module")
def codec():
    return get_codec("aruba_aoss")


class TestTheLine:
    def test_what_it_says_of_a_port(self, codec) -> None:
        """Whole.  The switch's part is HPE's two sentences and no
        more: in the default VLAN, and there until it is removed."""
        assert _said(codec.render(_tree(_trunk("5", 10, [20, 30])))) == [_OF_PORT_5]

    def test_what_it_says_of_a_trunk_group(self, codec) -> None:
        """Whole.  No sentence of HPE's was found for a trunk group:
        the line says "not established", and nothing of a port."""
        assert _said(codec.render(_tree(_trunk("trk1", 10, [20, 30])))) == [_OF_TRK1]

    def test_the_guard_holds_these_two(self) -> None:
        """The module that holds every job to its line types the two
        forms as well: they are these."""
        assert _of_a_port("5") == _OF_PORT_5 and _of_a_group("Trk1") == _OF_TRK1
        assert _of_a_group("5") != _OF_PORT_5

    def test_it_stands_in_that_vlans_stanza(self, codec) -> None:
        out = codec.render(_tree(_trunk("5", 10, [20, 30])))
        assert _stanza(out, 10) == [_OF_PORT_5]
        assert _stanza(out, 20) == ["   tagged 5"] and _stanza(out, 30) == ["   tagged 5"]
        # ... and no line makes the port untagged.
        assert not [line for line in out.splitlines() if line.strip().startswith("untagged")]

    def test_it_follows_the_vlans_lists(self, codec) -> None:
        """After the ``untagged`` and ``tagged`` lines of the stanza,
        which are ports that ARE in the VLAN."""
        out = codec.render(_tree(
            _trunk("5", 10, [20, 30]), _trunk("6", 10, [10, 20]), _trunk("7", 20, [10, 20]),
        ))
        assert _stanza(out, 10) == ["   untagged 6", "   tagged 7", _OF_PORT_5]
        assert said_on_aoss(out) == {(10, "5"): 1}

    def test_the_lines_of_a_stanza_keep_the_order_of_the_records(self, codec) -> None:
        """Three ports of one VLAN, in an order that is neither rising
        nor falling: one line each, as the records stand."""
        out = codec.render(_tree(_trunk("7", 10, [20]), _trunk("5", 10, [20, 30]), _trunk("6", 10, [])))
        assert _stanza(out, 10) == [_of_a_port("7"), _of_a_port("5"), _of_a_port("6")]

    @pytest.mark.parametrize("native,allowed", [
        (10, [10, 20, 30]),             # carried: the list names it
        (10, list(range(1, 4095))),     # carried: every VLAN
        (None, [20, 30]),               # none stated
    ])
    def test_nothing_left_out_has_none(self, codec, native, allowed) -> None:
        assert not _said(codec.render(_tree(_trunk("5", native, allowed))))

    def test_the_trunks_own_fields_decide(self, codec) -> None:
        """A tree whose VLANs list no port at all.  Port 5 states its
        native VLAN in its list and port 6 outside it: the line is
        port 6's alone.  (That no VLAN lists port 5 untagged is not
        what the line says.)"""
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(id=vid) for vid in (10, 20, 30)],
            interfaces=[_trunk("5", 10, [10, 20, 30]), _trunk("6", 10, [20, 30])],
        )
        assert said_on_aoss(codec.render(tree)) == {(10, "6"): 1}

    @pytest.mark.parametrize("mode", [None, "access", "dynamic"])
    def test_a_port_that_is_no_trunk_has_none(self, codec, mode) -> None:
        """The two fields are stated for later on such a port, and the
        renderer writes a trunk's lines for a trunk only."""
        port = CanonicalInterface(
            name="5", switchport_mode=mode, access_vlan=20 if mode == "access" else None,
            trunk_native_vlan=10, trunk_allowed_vlans=[20, 30],
        )
        assert not _said(codec.render(_tree(port)))

    def test_an_empty_list_leaves_it_out_too(self, codec) -> None:
        """A trunk that allows no VLAN: tagged in none, untagged in
        none, and the stanza of its native VLAN is the one place the
        output speaks of it."""
        out = codec.render(_tree(_trunk("5", 10, [])))
        assert _stanza(out, 10) == [_OF_PORT_5]
        assert not [line for line in out.splitlines() if line.strip().startswith(("tagged", "untagged"))]

    def test_a_list_written_around_the_vlan(self, codec) -> None:
        """``allowed vlan except 10``, ``remove 10``, ``1-9,11-4094``:
        a list of every id but the native one leaves it out like any
        other list, however long it is."""
        out = codec.render(_tree(_trunk("5", 10, _ALL_BUT_10)))
        assert _stanza(out, 10) == [_OF_PORT_5]
        assert _stanza(out, 20) == ["   tagged 5"] and _stanza(out, 30) == ["   tagged 5"]

    def test_a_trunk_that_is_shut(self, codec) -> None:
        """A port that is shut states its VLANs all the same, and
        carries them when it is brought up."""
        out = codec.render(_tree(_trunk("5", 10, [20, 30], enabled=False)))
        assert _stanza(out, 10) == [_OF_PORT_5]
        assert "   disable" in out.splitlines()

    def test_the_vlan_is_the_outputs(self) -> None:
        """After a VLAN map the id in the line is the one the OUTPUT
        has for the VLAN, in the stanza of that id: the line does not
        call it the source's, whose text says 10."""
        text = "\n".join([
            "hostname sw1", "!", "vlan 10", "!", "vlan 20", "!", "vlan 30", "!",
            "interface GigabitEthernet1/0/1", " switchport mode trunk", " switchport trunk native vlan 10",
            " switchport trunk allowed vlan 20,30", "!", "end", "",
        ])
        job = run_plan_with_checked_names(
            get_codec("cisco_iosxe_cli"), get_codec("aruba_aoss"), text,
            port_rename_map={"GigabitEthernet1/0/1": "5"}, vlan_rename_map={10: 40},
        )
        assert _said(job.rendered) == [_of_a_port("5", 40)]
        assert _stanza(job.rendered, 40) == [_of_a_port("5", 40)]
        assert "source" not in _said(job.rendered)[0] and "vlan 10" not in job.rendered.splitlines()


class TestWhichNames:
    def test_a_lag_and_its_members(self, codec) -> None:
        """One line a name the output uses, as the ``tagged`` line of
        VLAN 20 names them: the LAG in the form the device writes it
        outside its ``trunk`` line, each member under its own.  All
        three are in the form for a trunk group -- the output's own
        ``trunk`` line names the two ports -- and a port that is in no
        group is in the form for a port."""
        tree = _tree(
            _trunk("trk1", 10, [20, 30]),
            _trunk("1/1", 10, [20, 30], lag_member_of="trk1"),
            _trunk("1/2", 10, [20, 30], lag_member_of="trk1"),
            _trunk("1/3", 10, [10, 20, 30]),
            _trunk("1/4", 10, [20, 30]),
        )
        tree.lags.append(CanonicalLAG(name="trk1", members=["1/1", "1/2"], mode="active"))
        out = codec.render(tree)
        assert _stanza(out, 10) == [
            "   untagged 1/3", _OF_TRK1, _of_a_group("1/1"), _of_a_group("1/2"), _of_a_port("1/4"),
        ]
        assert _stanza(out, 20) == ["   tagged 1/1,1/2,1/3,1/4,Trk1"]
        # What the tree says of the two ports, the output's text says.
        assert in_a_trunk_line(out) == {"1/1", "1/2"}

    def test_a_member_is_one_by_the_lags_own_list(self, codec) -> None:
        """What puts a port on a ``trunk`` line is the LAG's list of
        members.  Port 1 is on that list, and its own record does not
        say so; port 3's record names a LAG that does not list it, and
        no ``trunk`` line of the output has port 3."""
        tree = _tree(_trunk("1", 10, [20]), _trunk("3", 10, [20], lag_member_of="trk1"))
        tree.lags.append(CanonicalLAG(name="trk1", members=["1", "2"], mode="active"))
        out = codec.render(tree)
        assert in_a_trunk_line(out) == {"1", "2"}
        assert _stanza(out, 10) == [_of_a_group("1"), _of_a_port("3")]

    def test_a_group_the_output_does_not_make(self, codec) -> None:
        """A LAG whose members the target has no name for has no
        ``trunk`` line, and the output says so.  Its name is a trunk
        group's all the same: nothing is said of it as of a port."""
        tree = _tree(_trunk("trk101", 10, [20, 30]))
        tree.lags.append(CanonicalLAG(name="trk101", members=[], mode="active"))
        out = codec.render(tree)
        assert "; LAG trk101 declared without members — cannot emit without ports" in out.splitlines()
        assert not in_a_trunk_line(out)
        assert _stanza(out, 10) == [_of_a_group("Trk101")]

    def test_a_lag_under_a_name_that_is_not_a_trunks(self, codec) -> None:
        """A tree whose names were not translated: the LAG is a LAG by
        the tree's own list, whatever it is called."""
        tree = _tree(_trunk("Port-channel1", 10, [20]))
        tree.lags.append(CanonicalLAG(name="Port-channel1", members=["1", "2"], mode="active"))
        assert [(port, form) for _stanza_of, _vid, port, form in said_how(codec.render(tree))] == [
            ("Port-channel1", GROUP_FORM),
        ]

    def test_another_letter_case_is_one_name(self, codec) -> None:
        """``TRK1`` and ``trk1`` are one port of the device, written
        ``Trk1``: one line."""
        out = codec.render(_tree(_trunk("TRK1", 10, [20]), _trunk("trk1", 10, [20])))
        assert _stanza(out, 10) == [_OF_TRK1]

    def test_each_port_under_its_own_native_vlan(self, codec) -> None:
        out = codec.render(_tree(_trunk("5", 10, [20, 30]), _trunk("6", 30, [10, 20]), _trunk("7", 10, [20])))
        assert said_on_aoss(out) == {(10, "5"): 1, (10, "7"): 1, (30, "6"): 1}
        assert _stanza(out, 30)[-1] == _of_a_port("6", 30)

    @pytest.mark.parametrize("named,listed", [("5", "5"), ("Trk1", "trk1"), ("trk1", "Trk1"), ("TRK1", "trk1")])
    def test_a_port_listed_untagged_has_none(self, codec, named: str, listed: str) -> None:
        """No parser makes this tree.  The output states an untagged
        VLAN for the port, and a line that said none is written would
        be false -- under whichever spelling of a trunk group's name
        the record and the list have it."""
        tree = _tree(_trunk(named, 10, [20, 30]))
        tree.vlans[2].untagged_ports.append(listed)
        out = codec.render(tree)
        assert not _said(out)
        assert f"   untagged {'Trk1' if is_a_trunk_group(named) else named}" in _stanza(out, 30)


class TestAVlanWithNoRecord:
    """The parsers make a record for every native VLAN a trunk states
    (``test_every_parser_makes_the_record``), so a stanza is there to
    hold the line.  A tree made another way may have none."""

    def test_it_is_said_where_it_would_stand(self, codec) -> None:
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(id=20, tagged_ports=["5"]), CanonicalVlan(id=30, tagged_ports=["5"])],
            interfaces=[_trunk("5", 10, [20, 30], description="uplink")],
        )
        out = codec.render(tree)
        lines = out.splitlines()
        # The line whole, at the margin: it is in no stanza.
        assert _said(out) == [_OF_PORT_5.strip()]
        # After the last VLAN stanza, before the port's own.
        at = lines.index(_OF_PORT_5.strip())
        assert lines[at - 1] == "   exit" and "vlan 30" in lines[:at]
        assert lines.index("interface 5") > at
        assert "vlan 10" not in lines

    @pytest.mark.parametrize("source,text", [
        ("cisco_iosxe_cli", "\n".join([
            "hostname sw1", "!", "vlan 20", "!",
            "interface GigabitEthernet1/0/1", " switchport mode trunk", " switchport trunk native vlan 77",
            " switchport trunk allowed vlan 20", "!", "end", "",
        ])),
        ("arista_eos", "\n".join([
            "hostname sw1", "!", "vlan 20", "!",
            "interface Ethernet1", "   switchport mode trunk", "   switchport trunk native vlan 77",
            "   switchport trunk allowed vlan 20", "!", "end", "",
        ])),
        ("cisco_nxos", "\n".join([
            "hostname sw1", "vlan 20",
            "interface Ethernet1/1", "  switchport mode trunk", "  switchport trunk native vlan 77",
            "  switchport trunk allowed vlan 20", "",
        ])),
        ("aruba_aoscx", "\n".join([
            "hostname sw1", "vlan 20",
            "interface 1/1/1", "    no shutdown", "    no routing", "    vlan trunk native 77",
            "    vlan trunk allowed 20", "",
        ])),
        ("juniper_junos", "\n".join([
            "set system host-name sw1", "set vlans twenty vlan-id 20",
            "set interfaces ge-0/0/1 native-vlan-id 77",
            "set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk",
            "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members twenty", "",
        ])),
    ])
    def test_every_parser_makes_the_record(self, source: str, text: str) -> None:
        """A native VLAN the config declares nowhere else, outside its
        list: each grammar that has a native line of its own makes the
        VLAN's record, and the line stands in its stanza."""
        assert HOW_IT_IS_STATED[source] == "the list decides"
        parsed = get_codec(source).parse(text)
        assert 77 in {vlan.id for vlan in parsed.vlans}, source
        port = next(iface.name for iface in parsed.interfaces if iface.switchport_mode == "trunk")
        job = run_plan_with_checked_names(
            get_codec(source), get_codec("aruba_aoss"), text, port_rename_map={port: "5"},
        )
        assert _said(job.rendered) == [_of_a_port("5", 77)], job.rendered
        assert _stanza(job.rendered, 77)[-1] == _of_a_port("5", 77)


def _a_lag_and_its_members() -> CanonicalIntent:
    tree = _tree(
        _trunk("trk1", 10, [20, 30]), _trunk("1/1", 10, [20, 30], lag_member_of="trk1"),
        _trunk("1/2", 10, [20, 30], lag_member_of="trk1"), _trunk("1/4", 10, [20]),
    )
    tree.lags.append(CanonicalLAG(name="trk1", members=["1/1", "1/2"], mode="active"))
    return tree


class TestItIsAComment:
    @pytest.mark.parametrize("tree", [
        _tree(_trunk("5", 10, [20, 30])),
        _tree(_trunk("5", 10, [])),
        _tree(
            _trunk("trk1", 10, [20, 30]), _trunk("1/1", 10, [20, 30]), _trunk("1/2", 30, [10]),
            _trunk("1/3", 10, [10, 20, 30]),
        ),
        _a_lag_and_its_members(),
        CanonicalIntent(
            vlans=[CanonicalVlan(id=20, tagged_ports=["5"])],
            interfaces=[_trunk("5", 10, [20], description="uplink")],
        ),
    ], ids=["one port", "an empty list", "a LAG and ports", "a LAG with its members", "no record of the VLAN"])
    def test_it_reads_back_the_same_without_it(self, codec, tree: CanonicalIntent) -> None:
        out = codec.render(tree)
        said = _said(out)
        assert said, out
        without = "\n".join(line for line in out.splitlines() if _REVIEW not in line) + "\n"
        assert without != out and not _said(without)
        assert codec.parse(out).model_dump(mode="json") == codec.parse(without).model_dump(mode="json")

    def test_both_forms_are_among_them(self, codec) -> None:
        forms = {form for _stanza_of, _vid, _port, form in said_how(codec.render(_a_lag_and_its_members()))}
        assert forms == {PORT_FORM, GROUP_FORM}

    def test_it_comes_back_untagged_nowhere(self, codec) -> None:
        """Read back, it is what the tree said: tagged in 20 and 30,
        untagged in none, and no native VLAN -- the words of the line
        are no port's name and no VLAN's member."""
        back = codec.parse(codec.render(_tree(_trunk("5", 10, [20, 30]))))
        assert [iface.name for iface in back.interfaces] == ["5"]
        port = back.interfaces[0]
        assert (port.switchport_mode, port.trunk_native_vlan, port.trunk_allowed_vlans) == ("trunk", None, [20, 30])
        assert {vlan.id: (vlan.untagged_ports, vlan.tagged_ports) for vlan in back.vlans} == {
            10: ([], []), 20: ([], ["5"]), 30: ([], ["5"]),
        }


# ---------------------------------------------------------------------------
# The committed captures
# ---------------------------------------------------------------------------

#: capture -> the names of its AOS-S output that are said, each in the
#: stanza of VLAN 1, and the form of each line.  Every trunk of the
#: committed captures that states a native VLAN outside its allowed
#: list and has a name on AOS-S; compared for EQUALITY with what is
#: measured.  One is a port.  The other eight are trunk groups, and
#: the output makes none of them (the test below): the target has no
#: name for their member ports, which the job lists.
SAID_OF: dict[str, dict[str, str]] = {
    "real/aruba_aoscx/aoscx_dcn_arch4_core1_1.cfg": {"Trk101": GROUP_FORM, "Trk102": GROUP_FORM},
    "real/aruba_aoscx/aoscx_dcn_arch4_core1_2.cfg": {"Trk101": GROUP_FORM, "Trk102": GROUP_FORM},
    "real/aruba_aoscx/netutils_aoscx_snmpv3_glcx1009.cfg": {
        "Trk10": GROUP_FORM, "Trk12": GROUP_FORM, "Trk14": GROUP_FORM, "Trk17": GROUP_FORM,
    },
    "synthetic/arista_eos/kitchen_sink.txt": {"3": PORT_FORM},
}

#: capture -> the source trunks of that kind that AOS-S has no name
#: for.  The job drops such a port from the output and lists it
#: (``unresolved_ports``), so there is no port to say it of.
NO_NAME_ON_AOSS: dict[str, list[str]] = {
    "synthetic/aruba_aoscx/kitchen_sink.cfg": ["1/1/4"],
    "synthetic/cisco_nxos/kitchen_sink.cfg": ["Ethernet1/4"],
}


def _groups_made(text: str) -> set[str]:
    """The trunk groups an AOS-S output makes: the names its ``trunk``
    lines end in, folded."""
    return {
        m.group(1).casefold() for m in (re.fullmatch(r"trunk \S+ (\S+)(?: \S+)?", line) for line in text.splitlines())
        if m
    }


def test_the_trunks_of_the_captures() -> None:
    """Every committed capture of a codec with a native line of its
    own, onto AOS-S.  Which source trunks leave their native VLAN out
    is read from the source's tree by its platform's row, written by
    hand in the module the readers are from -- not by the function
    the renderer asks."""
    found: dict[str, dict[str, str]] = {}
    no_name: dict[str, list[str]] = {}
    not_made: list[str] = []
    for source, label, path in CAPTURES:
        if HOW_IT_IS_STATED.get(source) != "the list decides":
            continue
        raw = path.read_text(encoding="utf-8")
        trunks = {
            name for name, port in read_tree(get_codec(source).parse(raw), source).items()
            if port.left_out is not None
        }
        job = run_plan_with_checked_names(get_codec(source), get_codec("aruba_aoss"), raw, port_rename_map={})
        said = said_how(job.rendered)
        if said:
            # Each in the stanza of VLAN 1, once, and whole.
            assert {(stanza, vid) for stanza, vid, _port, _form in said} == {("1", 1)}, (label, said)
            found[label] = {port: form for _stanza_of, _vid, port, form in said}
            assert len(found[label]) == len(said) and None not in found[label].values(), (label, said)
            # Each is a source trunk that left its native VLAN out.
            finals = {re.sub(r"\s+", "", job.port_renames.get(name, name)).casefold() for name in trunks}
            assert {port.casefold() for port in found[label]} <= finals, (label, found[label], finals)
            # A trunk group that is said is one the output does not
            # make: no `trunk` line has it, the output says the LAG
            # has no members, and the job lists ports it has no name
            # for.
            made = _groups_made(job.rendered)
            for port in found[label]:
                if is_a_trunk_group(port):
                    assert port.casefold() not in made, (label, port)
                    assert f"; LAG {port} declared without members — cannot emit without ports" in (
                        job.rendered.splitlines()
                    ), (label, port)
                    assert job.unresolved_ports, label
                    not_made.append(port)
        gone = trunks & set(job.unresolved_ports)
        if gone:
            no_name[label] = sorted(gone)
        assert len(said) == len(trunks) - len(gone), (label, sorted(trunks), said)
    assert found == SAID_OF
    assert no_name == NO_NAME_ON_AOSS
    # Nine names of four outputs: one port, and eight trunk groups
    # that the output does not make.
    forms = [form for names in SAID_OF.values() for form in names.values()]
    assert (len(SAID_OF), len(forms), forms.count(PORT_FORM), forms.count(GROUP_FORM)) == (4, 9, 1, 8)
    assert len(not_made) == 8
