"""What a trunk's list says after a VLAN is dropped or renumbered.

The VLAN pane of the rename modal hands the pipeline a map: this VLAN
gets that id, this one is not rendered.  Two things about a trunk's
list follow from "a list means what it says", and both went wrong
before it did.

* A trunk that allowed only VLANs the operator dropped is left with an
  empty list, and an empty list is a trunk that allows NO VLAN.  On
  four targets it came out as a trunk of every VLAN, with no warning.
  It is written as none now, and the job says so.
* A list of every id is the statement "every VLAN".  It is the same
  statement after a VLAN is dropped or renumbered, so it is left as it
  stands.  Rewritten id by id, a trunk that said ``all`` came out as
  ``1-99,101-4094``, and so would every trunk of a config that states
  no list, for one edit in the pane.

Nine cases from one IOS-XE source, onto every target that writes a
trunk's VLANs.  The OUTPUT is read as text by the readers of
``test_a_trunk_says_none_nothing_or_all.py`` (a target's parser reads
its own default) and with the target's parser, and the job's warnings
are read for the one this change adds.

The source's access port is in a VLAN no case touches (20), so that
what is read is the trunk and not a port a drop detached.

A third thing follows from the second.  A list of every id names no
VLAN in particular, so it is no reference to one: a map entry for a
VLAN the config does not have is reported as such, whatever trunks of
every VLAN the config holds (``test_a_map_entry_for_a_vlan_nowhere``).

And one thing about a port's NATIVE VLAN follows from "the list is
what a trunk carries".  A native VLAN the list leaves out is stated
and not carried, and a map can bring it INTO the list.  What the
pass then does turns on the ids of the list that the map puts on the
native VLAN's id:

* One of them is a VLAN of the config (it has a record before the
  map).  The map has made two VLANs one, and the trunk would carry
  untagged a VLAN it carried tagged, on every target that writes a
  native line, while AOS-S -- written from the VLANs' member lists --
  kept it tagged.  The native VLAN is cleared, and the job says so
  (``TestANativeVlanMergedIntoTheList``,
  ``test_a_merged_vlan_stays_tagged``).
* None of them is: the list named that number only as part of a
  range, and no VLAN had it -- ``native vlan 1000`` beside ``allowed
  vlan 2-999,1001-4094``, and 1000 renumbered to 900.  Nothing was
  merged.  The new id is taken out of the list and the native VLAN is
  kept, with a warning of its own, so the trunk carries that VLAN on
  no target, as before the map (``TestANumberNoVlanHad``,
  ``test_a_renumbered_native_vlan_stays_off_the_trunk``).

It is asked of every port that has the two fields, whatever its mode
(``TestWhateverThePortsMode``): a port in a dynamic mode or with no
mode line can become a trunk.  And one test holds the pass to what
all of this is for, with no list of cases: no map makes a port carry
untagged a VLAN it did not carry untagged before
(``test_no_map_makes_a_port_carry_untagged_what_it_did_not``).  What
a trunk carries in an output is read by the readers of
``test_the_list_holds_the_native_vlan.py``, each platform by its own
grammar, and the warnings are compared whole.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalInterface, CanonicalVlan
from netcanon.migration.canonical.transforms import TRUNK_ALLOWED_SPECIFICITY_BOUND
from netcanon.migration.canonical.vlan_names import translate_vlan_ids
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names, run_plan_with_overrides
from tests.unit.migration.test_a_trunk_says_none_nothing_or_all import (
    _ALLOWED,
    _IDS_OS10_HAS_NOT,
    _SOME,
    ALL,
    AOSS_WRITES_NO_PORT_OF,
    CANNOT_BE_TOLD_ALL,
    NONE,
    WRITES_A_TRUNKS_VLANS,
    _ports_in,
    _says_in_text,
)
from tests.unit.migration.test_the_list_holds_the_native_vlan import (
    HAVE_A_DEFAULT,
    PORT_FORM,
    SAID_OF_A_PORT,
    SAID_ON_OS10,
    SWITCHES,
    _ids,
    _stanzas,
    read_text,
    read_tree,
    said_how,
)

pytestmark = pytest.mark.unit

SOURCE = "cisco_iosxe_cli"
assert SOURCE not in AOSS_WRITES_NO_PORT_OF       # AOS-S has names for this source's ports

_NOW_NONE = "the trunk now allows no VLAN"

#: The access port's VLAN, which no case drops or renumbers.
_ACCESS = 20


def _source(*trunk: str) -> str:
    return "\n".join([
        "hostname sw1", "!",
        "vlan 10", " name users", "!", f"vlan {_ACCESS}", " name desks", "!",
        "vlan 100", " name secure", "!", "vlan 999", " name mgmt", "!",
        "interface GigabitEthernet1/0/1", " switchport mode trunk", *(f" {line}" for line in trunk), "!",
        "interface GigabitEthernet1/0/2", " switchport mode access", f" switchport access vlan {_ACCESS}", "!",
        "end", "",
    ])


#: title -> (the trunk's lines, the VLAN map, what the trunk's list is
#: afterwards, the VLANs the output still declares, what the warning
#: says of the VLANs that went -- or None for no such warning).
#: The list afterwards is NONE, ALL, or the ids.
CASES: dict[str, tuple[tuple[str, ...], dict[int, int | None], object, tuple[int, ...], str | None]] = {
    "a trunk of 100 only, 100 dropped": (
        (f"{_ALLOWED} 100",), {100: None}, NONE, (10, _ACCESS, 999), "allowed only VLAN 100 which was dropped",
    ),
    "a trunk of 10 and 999, both dropped": (
        (f"{_ALLOWED} 10,999",), {10: None, 999: None}, NONE, (_ACCESS, 100),
        "allowed only VLANs 10, 999 which were dropped",
    ),
    "a trunk that states no list, 100 dropped": ((), {100: None}, ALL, (10, _ACCESS, 999), None),
    "a trunk that states no list, 100 renumbered": ((), {100: 200}, ALL, (10, _ACCESS, 200, 999), None),
    "a trunk of 10 and 100, 100 dropped": ((f"{_ALLOWED} 10,100",), {100: None}, {10}, (10, _ACCESS, 999), None),
    "every id but 100, 10 dropped": (
        (f"{_ALLOWED} 1-99,101-4094",), {10: None}, set(range(1, 4095)) - {10, 100}, (_ACCESS, 100, 999), None,
    ),
    # It allowed no VLAN before the drop: nothing was emptied.
    "a trunk of none, 100 dropped": ((f"{_ALLOWED} none",), {100: None}, NONE, (10, _ACCESS, 999), None),
    # A renumbered VLAN keeps its place on the trunk under its new id.
    "every id but 1, 10 renumbered to 1": (
        (f"{_ALLOWED} 2-4094",), {10: 1}, set(range(1, 4095)) - {10}, (1, _ACCESS, 100, 999), None,
    ),
    # More VLANs than a warning names one by one: the first eight,
    # and a count of the rest.
    "a trunk of twenty VLANs, all dropped": (
        (f"{_ALLOWED} 30-49",), dict.fromkeys(range(30, 50)), NONE, (10, _ACCESS, 100, 999),
        "allowed only VLANs 30, 31, 32, 33, 34, 35, 36, 37 and 12 more which were dropped",
    ),
}


def _job(title: str, target: str):
    lines, vlan_map, _after, _declared, _warning = CASES[title]
    job = run_plan_with_overrides(
        get_codec(SOURCE), get_codec(target), _source(*lines),
        port_rename_map={}, vlan_rename_map=vlan_map, force=True,
    )
    assert job.rendered, f"{title} to {target}: nothing rendered ({job.status})"
    return job


def _trunk_of(parsed):
    trunks = [iface for iface in parsed.interfaces if iface.switchport_mode == "trunk"]
    assert len(trunks) == 1, [iface.name for iface in trunks]
    return trunks[0]


@pytest.mark.parametrize("target", sorted(WRITES_A_TRUNKS_VLANS))
@pytest.mark.parametrize("title", sorted(CASES))
def test_the_output_says_what_is_left(title: str, target: str) -> None:
    _lines, vlan_map, after, declared, _warning = CASES[title]
    job = _job(title, target)
    parsed = get_codec(target).parse(job.rendered)
    gone = {vid for vid, to in vlan_map.items() if to is None or to != vid}
    # The VLANs that went are no VLAN of the output, and on no port.
    assert not gone & {vlan.id for vlan in parsed.vlans}, (title, target)
    # 1. As text.
    said = _says_in_text(target, job.rendered, declared=declared)
    if target in CANNOT_BE_TOLD_ALL and (after == ALL or (after != NONE and 4094 in after)):
        # The pinned gap of the module the readers are from, and its
        # older half: OS10's ids end at 4093, and a list that holds
        # 4094 is written with it, as it always was.
        assert said == _IDS_OS10_HAS_NOT, (title, target, said)
    elif target == "aruba_aoss" and after not in (NONE, ALL):
        # AOS-S has no list: the port is tagged in the declared VLANs
        # the list holds, which is all of them, some, or none.
        held = set(declared) & after
        assert said == (ALL if held == set(declared) else _SOME if held else NONE), (title, target, said)
    else:
        assert said == (after if after in (NONE, ALL) else _SOME), (
            f"{title}: the {target} output says {said}"
        )
    # 2. With the target's parser: each declared VLAN is on the trunk
    # or not, and the access port is in its own.
    carried = set() if after == NONE else set(declared) if after == ALL else after
    if after not in (NONE, ALL) and target != "aruba_aoss":
        assert set(_trunk_of(parsed).trunk_allowed_vlans) == after, (title, target)
    for vid in declared:
        assert len(_ports_in(parsed, vid)) == (vid in carried) + (vid == _ACCESS), (title, target, vid)


@pytest.mark.parametrize("target", sorted(WRITES_A_TRUNKS_VLANS))
@pytest.mark.parametrize("title", sorted(CASES))
def test_the_job_says_a_trunk_was_emptied(title: str, target: str) -> None:
    """One warning, in the shape of its neighbours, for a trunk whose
    every allowed VLAN was dropped -- and none for any other trunk."""
    warning = CASES[title][4]
    job = _job(title, target)
    said = [str(text) for text in job.warnings if _NOW_NONE in str(text)]
    if warning is None:
        assert not said, (title, target, said)
        return
    assert len(said) == 1, (title, target, job.warnings)
    assert said[0].startswith("vlan_rename: interface '"), said
    assert f"is a trunk that {warning} — {_NOW_NONE}" in said[0], said
    # As for a port detached by a drop, the job is not failed by it.
    assert job.status == MigrationJobStatus.completed, (title, target, job.status)


# ---------------------------------------------------------------------------
# A map entry for a VLAN the config does not have
# ---------------------------------------------------------------------------

_NOWHERE = "VLAN 555 is present nowhere in the parsed config"


@pytest.mark.parametrize("trunk,reported,native_one", [
    # Every VLAN, and so no VLAN in particular: 555 is nowhere.
    ((), True, True),
    ((f"{_ALLOWED} all",), True, True),
    ((f"{_ALLOWED} 1-4094",), True, True),
    # A list like any other names its ids: 555 is on the trunk, and
    # the drop takes it off.
    ((f"{_ALLOWED} 2-4094",), False, False),
    ((f"{_ALLOWED} 10,555",), False, False),
    ((f"{_ALLOWED} 10",), True, False),
    ((f"{_ALLOWED} none",), True, False),
])
def test_a_map_entry_for_a_vlan_nowhere(trunk: tuple[str, ...], reported: bool, native_one: bool) -> None:
    """The pane's map can name a VLAN the config does not have (a
    typed id, a map kept from another config).  The job says so --
    and one trunk that states no allowed list, which is a trunk of
    every VLAN, does not make every id there is a VLAN of the
    config.  It makes ONE: the trunk states no native VLAN, which on
    IOS-XE is native VLAN 1, so where its list holds VLAN 1 the port
    carries it untagged and the pane offers it."""
    job = run_plan_with_overrides(
        get_codec(SOURCE), get_codec("juniper_junos"), _source(*trunk),
        port_rename_map={}, vlan_rename_map={555: None}, force=True,
    )
    said = [str(text) for text in job.warnings if _NOWHERE in str(text)]
    assert len(said) == reported, (trunk, job.warnings)
    if reported:
        assert said[0].endswith("entry ignored"), said
    # And the VLANs the pane offers are the config's own, not 4,094.
    own = {10, _ACCESS, 100, 999} | ({1} if native_one else set())
    assert set(job.source_vlans) - {555} == own, (trunk, len(job.source_vlans))


# ---------------------------------------------------------------------------
# The pass itself
# ---------------------------------------------------------------------------


def _tree(allowed: list[int], mode: str | None = "trunk") -> CanonicalIntent:
    return CanonicalIntent(
        vlans=[CanonicalVlan(id=vid) for vid in (10, 100, 999)],
        interfaces=[CanonicalInterface(name="Port1", switchport_mode=mode, trunk_allowed_vlans=allowed)],
    )


class TestThePass:
    @pytest.mark.parametrize("vlan_map", [{100: None}, {100: 200}, {10: None, 100: 5, 999: None}])
    def test_every_vlan_is_still_every_vlan(self, vlan_map: dict[int, int | None]) -> None:
        tree = _tree(list(range(1, 4095)))
        result = translate_vlan_ids(tree, vlan_map)
        assert tree.interfaces[0].trunk_allowed_vlans == list(range(1, 4095))
        assert not [text for text in result.warnings if _NOW_NONE in text]

    @pytest.mark.parametrize("order", ["backwards", "VLAN 1 last", "an id twice"])
    def test_every_vlan_in_any_order_is_kept(self, order: str) -> None:
        """A tree that was posted need not list the ids in their
        order: it is every VLAN however it is written."""
        allowed = {
            "backwards": list(range(4094, 0, -1)),
            "VLAN 1 last": [*range(2, 4095), 1],
            "an id twice": [*range(1, 4095), 7],
        }[order]
        tree = _tree(list(allowed))
        result = translate_vlan_ids(tree, {100: None, 10: 5})
        assert tree.interfaces[0].trunk_allowed_vlans == allowed
        assert not [text for text in result.warnings if _NOW_NONE in text]

    @pytest.mark.parametrize("allowed,reported", [
        (list(range(1, 4095)), True), (list(range(4094, 0, -1)), True),
        (list(range(2, 4095)), False), ([10, 555], False), ([10], True), ([], True),
    ])
    def test_every_vlan_is_no_reference_to_one(self, allowed: list[int], reported: bool) -> None:
        result = translate_vlan_ids(_tree(allowed), {555: None})
        assert len([text for text in result.warnings if _NOWHERE in text]) == reported, result.warnings

    def test_one_id_short_of_all_is_a_list(self) -> None:
        """`2-4094` is a list like any other: a drop takes its id out."""
        tree = _tree(list(range(2, 4095)))
        translate_vlan_ids(tree, {100: None})
        assert tree.interfaces[0].trunk_allowed_vlans == [vid for vid in range(2, 4095) if vid != 100]

    @pytest.mark.parametrize("allowed,dropped,named", [
        ([100], {100}, "VLAN 100 which was dropped"),
        ([10, 999], {10, 999}, "VLANs 10, 999 which were dropped"),
        (list(range(1, 9)), set(range(1, 9)), "VLANs 1, 2, 3, 4, 5, 6, 7, 8 which were dropped"),
        (list(range(1, 21)), set(range(1, 21)), "VLANs 1, 2, 3, 4, 5, 6, 7, 8 and 12 more which were dropped"),
    ])
    def test_the_warning_names_what_went(self, allowed: list[int], dropped: set[int], named: str) -> None:
        tree = _tree(allowed)
        result = translate_vlan_ids(tree, dict.fromkeys(dropped))
        assert tree.interfaces[0].trunk_allowed_vlans == []
        assert result.warnings.count(
            f"vlan_rename: interface 'Port1' is a trunk that allowed only {named} — {_NOW_NONE}"
        ) == 1, result.warnings

    @pytest.mark.parametrize("mode", [None, "access"])
    def test_a_port_that_is_no_trunk_is_quiet(self, mode: str | None) -> None:
        """The warning is for trunks.  A list kept on a port that is
        not `switchport mode trunk` is emptied by the drop with no
        warning -- and, a KNOWN LIMITATION, with no line either: on
        such a port an empty list and no list are one value.  An
        access port carries nothing by that list before or after.  A
        port in a dynamic mode that negotiates a trunk does: it
        carried the VLANs listed, and carries every VLAN once the
        list is gone."""
        tree = _tree([100], mode)
        result = translate_vlan_ids(tree, {100: None})
        assert tree.interfaces[0].trunk_allowed_vlans == []
        assert not [text for text in result.warnings if _NOW_NONE in text]

    def test_a_trunk_left_with_a_vlan_is_quiet(self) -> None:
        tree = _tree([10, 100])
        result = translate_vlan_ids(tree, {100: None})
        assert tree.interfaces[0].trunk_allowed_vlans == [10]
        assert not [text for text in result.warnings if _NOW_NONE in text]


# ---------------------------------------------------------------------------
# A native VLAN outside its list, and a map that brings it into the list
# ---------------------------------------------------------------------------

_CLEARED = "native VLAN cleared"

#: The warning for a port whose native VLAN the map DROPS, whole; and
#: what it ends with where the port's list is every VLAN, which the
#: pass leaves as it stands.  Typed here, and taken from no code.
_DROPPED = "vlan_rename: interface {port!r} had native VLAN {vid} which was dropped — native VLAN cleared"
_STILL_HELD = (
    "; the port allows every VLAN, and an output that writes it as a trunk"
    " of every VLAN still allows VLAN {vid}"
)
_OUTSIDE = "outside its allowed list"
_TAKEN_OUT = "is taken out of the list"

#: Every id but VLAN 10: what `allowed vlan except 10`, `remove 10`
#: and `1-9,11-4094` all are.
_ALL_BUT_10 = [vid for vid in range(1, 4095) if vid != 10]

#: A range no VLAN of these trees is in.
_100_TO_600 = list(range(100, 601))

#: Every mode a port's record can have.  The pass asks the same of
#: each: a port's trunk lines say what it carries when it is a trunk.
MODES = ["trunk", "dynamic", None, "access"]


def _native(
    native: int | None, allowed: list[int], mode: str | None = "trunk", vlans: tuple[int, ...] = (10, 20, 30),
) -> CanonicalIntent:
    """One port, and the VLANs of the config: the ids that have a
    record."""
    return CanonicalIntent(
        vlans=[CanonicalVlan(id=vid) for vid in vlans],
        interfaces=[CanonicalInterface(
            name="Port1", switchport_mode=mode, trunk_native_vlan=native, trunk_allowed_vlans=list(allowed),
        )],
    )


def _after(tree: CanonicalIntent) -> tuple[int | None, list[int]]:
    port = tree.interfaces[0]
    return port.trunk_native_vlan, port.trunk_allowed_vlans


def _moved(allowed: list[int], vlan_map: dict[int, int | None]) -> list[int]:
    """*allowed* after *vlan_map*, by hand: drops out, each id where
    the map sends it, an id once."""
    out: list[int] = []
    for vid in allowed:
        if vid in vlan_map and vlan_map[vid] is None:
            continue
        to = vlan_map.get(vid, vid)
        if to not in out:
            out.append(to)
    return out


class TestANativeVlanMergedIntoTheList:
    """Native VLAN 10 beside a list that leaves it out is stated and
    not carried.  A map that makes it ONE VLAN with a VLAN of the
    config that the list names: cleared, and said."""

    def test_the_warning_whole(self) -> None:
        """Both forms of it, typed out: the native VLAN moved onto the
        VLAN of the list, and the VLAN of the list moved onto it."""
        tree = _native(10, [20, 30])
        assert translate_vlan_ids(tree, {10: 20}).warnings[-1] == (
            "vlan_rename: interface 'Port1' had native VLAN 10 outside its allowed list, and the map merges it "
            "into VLAN 20, which the trunk carries tagged — native VLAN cleared"
        )
        tree = _native(10, [20, 30])
        assert translate_vlan_ids(tree, {20: 10}).warnings[-1] == (
            "vlan_rename: interface 'Port1' had native VLAN 10 outside its allowed list, and the map merges "
            "VLAN 20, which the trunk carries tagged, into it — native VLAN cleared"
        )

    @pytest.mark.parametrize("allowed,vlans,vlan_map,said", [
        # 10 goes onto 20, which the trunk carries tagged.
        ([20, 30], (10, 20, 30), {10: 20}, "the map merges it into VLAN 20, which the trunk carries tagged"),
        # 20 goes onto 10: the same two VLANs made one, the other way.
        ([20, 30], (10, 20, 30), {20: 10}, "the map merges VLAN 20, which the trunk carries tagged, into it"),
        # Both go onto an id neither had.
        ([20, 30], (10, 20, 30), {10: 40, 30: 40}, "the map merges it into VLAN 40, which the trunk carries tagged"),
        # A VLAN of the list that is dropped is not the one it is merged with.
        (
            [20, 30], (10, 20, 30), {10: 20, 20: None, 30: 20},
            "the map merges it into VLAN 20, which the trunk carries tagged",
        ),
        # The merged VLAN is not the first of the list: it is the one named.
        ([30, 20], (10, 20, 30), {20: 10}, "the map merges VLAN 20, which the trunk carries tagged, into it"),
        ([30, 20, 40], (10, 20, 30, 40), {40: 10}, "the map merges VLAN 40, which the trunk carries tagged, into it"),
        # A list written around the native VLAN -- `except 10`,
        # `remove 10`, `1-9,11-4094` -- holds the VLANs of the config
        # among its thousands of numbers.
        (_ALL_BUT_10, (10, 20, 30), {10: 20}, "the map merges it into VLAN 20, which the trunk carries tagged"),
        (_ALL_BUT_10, (10, 20, 30), {30: 10}, "the map merges VLAN 30, which the trunk carries tagged, into it"),
        # Two ids of the list go onto the native VLAN's, and one of
        # them is a VLAN of the config: it is a merge, and that VLAN
        # is the one named, whichever place it has.
        ([500, 20], (10, 20), {500: 10, 20: 10}, "the map merges VLAN 20, which the trunk carries tagged, into it"),
        ([20, 500], (10, 20), {500: 10, 20: 10}, "the map merges VLAN 20, which the trunk carries tagged, into it"),
        (
            _100_TO_600, (10, 500), {450: 10, 500: 10},
            "the map merges VLAN 500, which the trunk carries tagged, into it",
        ),
    ])
    def test_it_is_cleared_and_said(
        self, allowed: list[int], vlans: tuple[int, ...], vlan_map: dict[int, int | None], said: str,
    ) -> None:
        tree = _native(10, allowed, vlans=vlans)
        result = translate_vlan_ids(tree, vlan_map)
        # Cleared, and the list is what the map makes of it: nothing
        # is taken out of it.
        assert _after(tree) == (None, _moved(allowed, vlan_map))
        assert result.warnings.count(
            f"vlan_rename: interface 'Port1' had native VLAN 10 {_OUTSIDE}, and {said} — {_CLEARED}"
        ) == 1, result.warnings
        # One warning says it, and it is this one.
        assert len([text for text in result.warnings if _OUTSIDE in text]) == 1, result.warnings
        assert not [text for text in result.warnings if _TAKEN_OUT in text], result.warnings

    @pytest.mark.parametrize("native,allowed,vlan_map,after", [
        # Carried, and renumbered with its list.
        (10, [10, 20, 30], {10: 100}, (100, [100, 20, 30])),
        # Carried, and merged with another VLAN of its list: as it
        # always was, the native VLAN goes where the map sends it.
        (10, [10, 20, 30], {10: 20}, (20, [20, 30])),
        # Not carried, and still outside the list afterwards.
        (10, [20, 30], {10: 100}, (100, [20, 30])),
        (10, [20, 30], {20: 200}, (10, [200, 30])),
        (10, [20, 30], {10: 20, 20: 10}, (20, [10, 30])),
        (10, [20, 30], {10: 20, 20: None}, (20, [30])),
        (10, [], {10: 20}, (20, [])),
        # A drop of another VLAN leaves it where it was.
        (10, [20, 30], {20: None}, (10, [30])),
        # No native VLAN stated: nothing to clear.
        (None, [20, 30], {20: 10}, (None, [10, 30])),
    ])
    def test_what_does_not_move(
        self, native: int | None, allowed: list[int], vlan_map: dict[int, int | None],
        after: tuple[int | None, list[int]],
    ) -> None:
        tree = _native(native, allowed)
        result = translate_vlan_ids(tree, vlan_map)
        assert _after(tree) == after
        assert not [
            text for text in result.warnings if _CLEARED in text or _OUTSIDE in text or _TAKEN_OUT in text
        ], result.warnings

    def test_a_drop_has_its_own_warning(self) -> None:
        """Its own warning, as before, and not this one.  The line is
        held WHOLE: beside a list that names its VLANs, which the
        drop is taken out of as well, it says no more than this."""
        for allowed, after in (([20, 30], [20, 30]), ([10, 20, 30], [20, 30]), ([], [])):
            tree = _native(10, allowed)
            result = translate_vlan_ids(tree, {10: None})
            assert _after(tree) == (None, after)
            assert [text for text in result.warnings if _CLEARED in text] == [
                _DROPPED.format(port="Port1", vid=10),
            ], allowed

    def test_a_drop_beside_every_vlan_says_the_list_holds_it(self) -> None:
        """A list of every id is the statement "every VLAN", and is
        left as it stands: it still holds the id that was dropped.
        "Native VLAN cleared" alone reads as "no longer carried",
        so the warning says what the list still holds.  The line,
        whole -- and the tree it speaks of."""
        for every in (list(range(1, 4095)), list(range(4094, 0, -1))):
            tree = _native(10, list(every))
            result = translate_vlan_ids(tree, {10: None})
            assert _after(tree) == (None, every)
            assert [text for text in result.warnings if _CLEARED in text] == [
                _DROPPED.format(port="Port1", vid=10) + _STILL_HELD.format(vid=10),
            ]
        # Every id but the one dropped is a list like any other: the
        # line as it was.
        tree = _native(10, _ALL_BUT_10)
        result = translate_vlan_ids(tree, {10: None})
        assert [text for text in result.warnings if _CLEARED in text] == [_DROPPED.format(port="Port1", vid=10)]

    @pytest.mark.parametrize("vlan_map", [{10: 20}, {20: 10}, {10: 4000}])
    def test_every_vlan_held_it_before(self, vlan_map: dict[int, int | None]) -> None:
        """A list of every id holds every native VLAN, before the map
        and after it: the native VLAN is renumbered and the list is
        left as it stands."""
        tree = _native(10, list(range(1, 4095)))
        result = translate_vlan_ids(tree, vlan_map)
        assert _after(tree) == (vlan_map.get(10, 10), list(range(1, 4095)))
        assert not [text for text in result.warnings if _CLEARED in text or _TAKEN_OUT in text]

    def test_each_trunk_by_its_own_list(self) -> None:
        tree = _native(10, [20, 30])
        tree.interfaces.append(CanonicalInterface(
            name="Port2", switchport_mode="trunk", trunk_native_vlan=10, trunk_allowed_vlans=[10, 20],
        ))
        tree.interfaces.append(CanonicalInterface(
            name="Port3", switchport_mode="trunk", trunk_native_vlan=10, trunk_allowed_vlans=[30],
        ))
        result = translate_vlan_ids(tree, {10: 20})
        assert [(port.name, port.trunk_native_vlan, port.trunk_allowed_vlans) for port in tree.interfaces] == [
            ("Port1", None, [20, 30]), ("Port2", 20, [20]), ("Port3", 20, [30]),
        ]
        assert len([text for text in result.warnings if _CLEARED in text]) == 1
        assert "'Port1'" in next(text for text in result.warnings if _CLEARED in text)

    def test_two_trunks_that_both_need_it(self) -> None:
        """Every trunk of the config is asked, not the first: each is
        cleared, and each has its warning under its own name."""
        tree = _native(10, [20, 30])
        tree.interfaces.append(CanonicalInterface(
            name="Port2", switchport_mode="trunk", trunk_native_vlan=10, trunk_allowed_vlans=[20],
        ))
        tree.interfaces.append(CanonicalInterface(
            name="Port3", switchport_mode="trunk", trunk_native_vlan=10, trunk_allowed_vlans=list(_ALL_BUT_10),
        ))
        result = translate_vlan_ids(tree, {10: 20})
        assert [(port.name, port.trunk_native_vlan) for port in tree.interfaces] == [
            ("Port1", None), ("Port2", None), ("Port3", None),
        ]
        assert [text for text in result.warnings if _OUTSIDE in text] == [
            f"vlan_rename: interface {name!r} had native VLAN 10 {_OUTSIDE}, and the map merges it into VLAN 20, "
            f"which the trunk carries tagged — {_CLEARED}"
            for name in ("Port1", "Port2", "Port3")
        ]

    def test_a_lag_and_its_members(self) -> None:
        """A port-channel and a member that states the same lines are
        two records, and each is held to it: a member left with the
        merged VLAN as its native VLAN would carry it untagged."""
        tree = _native(10, [20, 30])
        tree.interfaces[0].name = "Port-channel1"
        for name in ("Port1", "Port2"):
            tree.interfaces.append(CanonicalInterface(
                name=name, switchport_mode="trunk", trunk_native_vlan=10, trunk_allowed_vlans=[20, 30],
                lag_member_of="Port-channel1",
            ))
        result = translate_vlan_ids(tree, {10: 20})
        assert [(port.name, port.trunk_native_vlan, port.trunk_allowed_vlans) for port in tree.interfaces] == [
            ("Port-channel1", None, [20, 30]), ("Port1", None, [20, 30]), ("Port2", None, [20, 30]),
        ]
        assert len([text for text in result.warnings if _CLEARED in text]) == 3, result.warnings


class TestANumberNoVlanHad:
    """Native VLAN 10 beside a list that leaves it out -- and the id
    the map brings into the list is one the list named only as a
    NUMBER: part of a range, with no VLAN of the config under it.
    Nothing was merged, and nothing was carried tagged under that
    number.  The new id is taken out of the list and the native VLAN
    is kept: stated, and not carried, as before the map."""

    def test_a_parking_vlan_beside_every_other_id(self) -> None:
        """A parking VLAN as the native VLAN beside a list of every
        other id, and a plain renumber of it: `native vlan 1000`
        beside `allowed vlan 2-999,1001-4094`, and 1000 given the id
        900."""
        allowed = [*range(2, 1000), *range(1001, 4095)]
        tree = _native(1000, allowed, vlans=(10, 20, 1000))
        result = translate_vlan_ids(tree, {1000: 900})
        assert _after(tree) == (900, [vid for vid in allowed if vid != 900])
        assert [text for text in result.warnings if _OUTSIDE in text] == [
            "vlan_rename: interface 'Port1' had native VLAN 1000 outside its allowed list, and the map gives it "
            "the id 900, which the list named only as a number no VLAN of the config had — 900 is taken out of "
            "the list, and the trunk does not carry native VLAN 900",
        ]
        assert sorted(vlan.id for vlan in tree.vlans) == [10, 20, 900]
        # It is a renumber, and the pass says nothing of a merge.
        assert not [text for text in result.warnings if "merg" in text or "carries tagged" in text or _CLEARED in text]

    def test_a_number_of_the_list_moved_onto_it(self) -> None:
        """The other way: the map gives the native VLAN's id to a
        number of the list.  Native VLAN 10 beside `100-600`, and 500
        -- which no VLAN has -- given the id 10."""
        tree = _native(10, _100_TO_600)
        result = translate_vlan_ids(tree, {500: 10})
        assert _after(tree) == (10, [vid for vid in _100_TO_600 if vid != 500])
        assert [text for text in result.warnings if _OUTSIDE in text] == [
            "vlan_rename: interface 'Port1' had native VLAN 10 outside its allowed list, and the map gives its "
            "id to 500, which the list named only as a number no VLAN of the config had — 10 is taken out of "
            "the list, and the trunk does not carry native VLAN 10",
        ]

    def test_both_moved_onto_one_id(self) -> None:
        tree = _native(10, _100_TO_600)
        result = translate_vlan_ids(tree, {10: 900, 500: 900})
        assert _after(tree) == (900, [vid for vid in _100_TO_600 if vid != 500])
        assert [text for text in result.warnings if _OUTSIDE in text] == [
            "vlan_rename: interface 'Port1' had native VLAN 10 outside its allowed list, and the map gives it "
            "the id 900 and gives the same id to 500, which the list named only as a number no VLAN of the "
            "config had — 900 is taken out of the list, and the trunk does not carry native VLAN 900",
        ]

    @pytest.mark.parametrize("allowed,vlans,vlan_map,after,how", [
        # `allowed vlan except 10`, and 10 given the id 4000.
        (
            _ALL_BUT_10, (10, 20, 30), {10: 4000}, (4000, [vid for vid in _ALL_BUT_10 if vid != 4000]),
            "the map gives it the id 4000",
        ),
        # Another VLAN of the list is renumbered beside it, and stays.
        (_ALL_BUT_10, (10, 20, 30), {10: 4000, 20: 200}, (4000, None), "the map gives it the id 4000"),
        # Two numbers of the list are moved onto it: the first is named.
        (_100_TO_600, (10, 20, 30), {500: 10, 550: 10}, (10, None), "the map gives its id to 500"),
        # A VLAN of the list that is DROPPED lands nowhere.  VLAN 20
        # goes, 10 takes its id and so does the number 600: no VLAN
        # of the config was merged with anything.
        (
            [20, *_100_TO_600], (10, 20), {10: 20, 20: None, 600: 20}, (20, None),
            "the map gives it the id 20 and gives the same id to 600",
        ),
    ])
    def test_it_is_taken_out_and_said(
        self, allowed: list[int], vlans: tuple[int, ...], vlan_map: dict[int, int | None],
        after: tuple[int, list[int] | None], how: str,
    ) -> None:
        tree = _native(10, allowed, vlans=vlans)
        result = translate_vlan_ids(tree, vlan_map)
        native, listed = after
        if listed is None:
            listed = [vid for vid in _moved(allowed, vlan_map) if vid != native]
        assert _after(tree) == (native, listed)
        assert native not in listed                 # stated, and not carried
        assert [text for text in result.warnings if _OUTSIDE in text] == [
            f"vlan_rename: interface 'Port1' had native VLAN 10 {_OUTSIDE}, and {how}, which the list named only "
            f"as a number no VLAN of the config had — {native} {_TAKEN_OUT}, and the trunk does not carry "
            f"native VLAN {native}",
        ]
        assert not [text for text in result.warnings if _CLEARED in text], result.warnings

    def test_two_trunks_that_both_need_it(self) -> None:
        tree = _native(10, _ALL_BUT_10)
        tree.interfaces.append(CanonicalInterface(
            name="Port2", switchport_mode="trunk", trunk_native_vlan=10, trunk_allowed_vlans=list(_100_TO_600),
        ))
        result = translate_vlan_ids(tree, {10: 150})
        assert [(port.name, port.trunk_native_vlan, 150 in port.trunk_allowed_vlans) for port in tree.interfaces] == [
            ("Port1", 150, False), ("Port2", 150, False),
        ]
        assert [text.split(" had ")[0] for text in result.warnings if _TAKEN_OUT in text] == [
            "vlan_rename: interface 'Port1'", "vlan_rename: interface 'Port2'",
        ]

    def test_what_a_vlan_of_the_config_is(self) -> None:
        """An id that has a record before the map.  The same list and
        the same map, with and without a record for 500: a merge with
        it, a number without."""
        with_one = _native(10, _100_TO_600, vlans=(10, 500))
        result = translate_vlan_ids(with_one, {10: 500})
        assert _after(with_one) == (None, _100_TO_600)
        assert [text for text in result.warnings if _CLEARED in text and "merges it into VLAN 500" in text]
        without = _native(10, _100_TO_600, vlans=(10,))
        result = translate_vlan_ids(without, {10: 500})
        assert _after(without) == (500, [vid for vid in _100_TO_600 if vid != 500])
        assert [text for text in result.warnings if _TAKEN_OUT in text and "gives it the id 500" in text]


_INTO_500 = "the map merges it into VLAN 500, which the trunk carries tagged"
_FROM_600 = "the map merges VLAN 600, which the trunk carries tagged, into it"


class TestAShortListNamesItsVlans:
    """A list no longer than the parsers' bound names VLANs, with or
    without a record for each: it is how a trunk's list is read, and
    a port in another mode gets no record from its trunk lines and
    means the same by them.  An id of such a list is never taken out
    as a number -- which, for the list's only id, would leave a port
    its native line and no list at all."""

    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("allowed,vlan_map,after,how", [
        # The list's only id.
        ([500], {10: 500}, (None, [500]), _INTO_500),
        # One of two, and the other stays.
        ([500, 600], {10: 500}, (None, [500, 600]), _INTO_500),
        # The other way: an id of the list given the native VLAN's.
        ([500, 600], {600: 10}, (None, [500, 10]), _FROM_600),
        # A record for one id of the list and none for the other.
        ([20, 500], {10: 500}, (None, [20, 500]), _INTO_500),
    ])
    def test_it_is_a_merge_without_a_record(
        self, allowed: list[int], vlan_map: dict[int, int | None], after: tuple[int | None, list[int]], how: str,
        mode: str | None,
    ) -> None:
        tree = _native(10, allowed, mode, vlans=(10, 20))
        result = translate_vlan_ids(tree, vlan_map)
        assert _after(tree) == after, mode
        assert [text for text in result.warnings if _OUTSIDE in text] == [
            f"vlan_rename: interface 'Port1' had native VLAN 10 {_OUTSIDE}, and {how} — {_CLEARED}",
        ]
        assert not [text for text in result.warnings if _TAKEN_OUT in text], result.warnings

    @pytest.mark.parametrize("mode", MODES)
    def test_where_short_ends(self, mode: str | None) -> None:
        """The bound is the parsers' (128 ids): a list of that many
        names VLANs, and one id more is a range of numbers."""
        assert TRUNK_ALLOWED_SPECIFICITY_BOUND == 128
        short = list(range(100, 228))
        tree = _native(10, short, mode, vlans=(10,))
        result = translate_vlan_ids(tree, {10: 150})
        assert _after(tree) == (None, short)
        assert len([text for text in result.warnings if _CLEARED in text]) == 1, result.warnings
        longer = list(range(100, 229))
        tree = _native(10, longer, mode, vlans=(10,))
        result = translate_vlan_ids(tree, {10: 150})
        assert _after(tree) == (150, [vid for vid in longer if vid != 150])
        assert len([text for text in result.warnings if _TAKEN_OUT in text]) == 1, result.warnings


class TestWhateverThePortsMode:
    """A port's trunk lines say what it carries when it is a trunk,
    and a port in a dynamic mode or with no mode line can become one.
    The pass asks the same of every port that has the two fields."""

    @pytest.mark.parametrize("mode", MODES)
    def test_a_merge_clears_it(self, mode: str | None) -> None:
        tree = _native(10, [20, 30], mode)
        result = translate_vlan_ids(tree, {10: 20})
        assert _after(tree) == (None, [20, 30]), mode
        assert [text for text in result.warnings if _OUTSIDE in text] == [
            f"vlan_rename: interface 'Port1' had native VLAN 10 {_OUTSIDE}, and the map merges it into VLAN 20, "
            f"which the trunk carries tagged — {_CLEARED}",
        ]

    @pytest.mark.parametrize("mode", MODES)
    def test_a_number_is_taken_out(self, mode: str | None) -> None:
        tree = _native(10, _ALL_BUT_10, mode)
        result = translate_vlan_ids(tree, {10: 4000})
        assert _after(tree) == (4000, [vid for vid in _ALL_BUT_10 if vid != 4000]), mode
        assert len([text for text in result.warnings if _TAKEN_OUT in text]) == 1, result.warnings

    @pytest.mark.parametrize("mode", MODES)
    def test_what_does_not_move_does_not(self, mode: str | None) -> None:
        tree = _native(10, [20, 30], mode)
        result = translate_vlan_ids(tree, {10: 100, 20: 200})
        assert _after(tree) == (100, [200, 30])
        assert not [text for text in result.warnings if _OUTSIDE in text]


def test_no_map_makes_a_port_carry_untagged_what_it_did_not() -> None:
    """What a pass over a trunk's fields has to hold: the VLAN a port
    carries untagged AFTER it is the one it carried BEFORE, under the
    id the map gives that VLAN, or none.  A port that carried none
    carries none.

    Asked here apart from the code, of every map of three ids onto
    five and a drop, for every mode, four native VLANs and nine lists:
    a native VLAN is carried where the list holds it."""

    def carried(native: int | None, allowed: list[int]) -> int | None:
        return native if native is not None and native in allowed else None

    lists = (
        [], [10], [20, 30], [10, 20, 30], [30, 500], [500, 20], _100_TO_600, _ALL_BUT_10, list(range(1, 4095)),
    )
    choices = (0, 10, 20, 500, 900, None)           # 0: the id is not in the map
    maps = [
        {vid: to for vid, to in zip((10, 20, 500), (a, b, c)) if to != 0 and to != vid}
        for a in choices for b in choices for c in choices
    ]
    asked = left_none = 0
    for mode in MODES:
        for native in (None, 10, 20, 500):
            for allowed in lists:
                before = carried(native, allowed)
                for vlan_map in maps:
                    tree = _native(native, allowed, mode)
                    translate_vlan_ids(tree, vlan_map)
                    after = carried(*_after(tree))
                    if before is None or vlan_map.get(before, before) is None:
                        want = None
                    else:
                        want = vlan_map.get(before, before)
                    assert after == want, (mode, native, len(allowed), vlan_map, _after(tree)[0])
                    asked += 1
                    left_none += before is None and native is not None
    # It asked what it says it asked: thousands of ports that stated a
    # native VLAN and did not carry it.
    assert asked == len(MODES) * 4 * len(lists) * len(maps) and left_none > 5_000


# ---------------------------------------------------------------------------
# ... and through jobs, onto every switch
# ---------------------------------------------------------------------------

#: The trunk of ``_source``: native VLAN 10 outside a list of 100 and 999.
_NATIVE_OUTSIDE = ("switchport trunk native vlan 10", f"{_ALLOWED} 100,999")

#: Onto AOS-S the trunk is given a name: the output is read by it.
_TRUNK = "GigabitEthernet1/0/1"


def _eos(*trunk: str) -> str:
    """An EOS config: VLANs 10, 20 and 1000, one trunk, one access
    port in VLAN 20."""
    return "\n".join([
        "hostname sw1", "!",
        "vlan 10", "   name users", "!", f"vlan {_ACCESS}", "   name desks", "!", "vlan 1000", "   name parking", "!",
        "interface Ethernet1", "   switchport mode trunk", *(f"   {line}" for line in trunk), "!",
        "interface Ethernet2", f"   switchport access vlan {_ACCESS}", "!",
        "end", "",
    ])


def _job_of(source: str, text: str, trunk: str, target: str, vlan_map: dict[int, int | None]):
    job = run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map={}, vlan_rename_map=vlan_map, force=True,
    )
    assert job.rendered, (target, job.error)
    return job, job.port_renames.get(trunk, trunk)


def _merged_job(target: str, vlan_map: dict[int, int | None]):
    return _job_of(SOURCE, _source(*_NATIVE_OUTSIDE), _TRUNK, target, vlan_map)


def _on_the_trunk(target: str, job, final: str):
    """What the device of *target* carries on the trunk, read from
    the output's text and from the output parsed again."""
    codec = get_codec(target)
    fold = (lambda name: name.casefold()) if not codec.port_names_case_sensitive else (lambda name: name)
    found = []
    for ports in (read_text(job.rendered, target), read_tree(codec.parse(job.rendered), target)):
        ports = {fold(name.replace(" ", "")): port for name, port in ports.items()}
        found.append(ports[fold(final.replace(" ", ""))])
    return found


def _said_of_the_native(job) -> list[str]:
    return [str(text) for text in job.warnings if _OUTSIDE in str(text)]


@pytest.mark.parametrize("target", SWITCHES)
@pytest.mark.parametrize("vlan_map,merged,how", [
    ({10: 100}, 100, "the map merges it into VLAN 100, which the trunk carries tagged"),
    ({100: 10}, 10, "the map merges VLAN 100, which the trunk carries tagged, into it"),
])
def test_a_merged_vlan_stays_tagged(
    target: str, vlan_map: dict[int, int | None], merged: int, how: str,
) -> None:
    """The source trunk carries VLAN 100 tagged and no VLAN untagged.
    With VLANs 10 and 100 made one, the trunk still carries that VLAN
    tagged and none untagged -- on the six targets that write the
    port's own lines and on AOS-S, which is written from the VLANs'
    member lists.  The two halves of the tree say one thing."""
    job, final = _merged_job(target, vlan_map)
    for port in _on_the_trunk(target, job, final):
        assert port.untagged is None and port.left_out is None, (target, vlan_map, port)
        assert port.carries_tagged(merged) and port.carries_tagged(999), (target, vlan_map, port)
    assert _said_of_the_native(job) == [
        f"vlan_rename: interface {final!r} had native VLAN 10 {_OUTSIDE}, and {how} — {_CLEARED}",
    ], job.warnings
    assert not said_how(job.rendered) and "no switchport access vlan" not in job.rendered
    assert job.status == MigrationJobStatus.completed, (target, job.status)


@pytest.mark.parametrize("target", SWITCHES)
def test_a_native_vlan_still_outside_is_kept(target: str) -> None:
    """The neighbour, through a job: VLAN 10 becomes 50, which the
    list still leaves out.  The trunk carries no VLAN untagged, as
    before, and the pass has nothing to say of it."""
    job, final = _merged_job(target, {10: 50})
    for port in _on_the_trunk(target, job, final):
        assert port.untagged is None, (target, port)
        assert port.carries_tagged(100) and port.carries_tagged(999), (target, port)
    assert not [text for text in job.warnings if _OUTSIDE in str(text) or _CLEARED in str(text)], job.warnings
    if target not in ("aruba_aoss", "dell_os10"):
        # Where a native line is its own statement it is still made,
        # beside a list that leaves the VLAN out.
        assert {port.left_out for port in _on_the_trunk(target, job, final)} == {50}, target


#: title -> (source codec, its text, its trunk, the map, the native
#: VLAN's id before and after, two VLANs the trunk carries tagged).
#: A plain renumber of a native VLAN the list leaves out, onto an id
#: the list's range covers and no VLAN of the config has.
RENUMBERED: dict[str, tuple[str, str, str, dict[int, int | None], int, int, tuple[int, int]]] = {
    "EOS, a parking VLAN beside every other id": (
        "arista_eos", _eos("switchport trunk native vlan 1000", f"{_ALLOWED} 2-999,1001-4094"),
        "Ethernet1", {1000: 900}, 1000, 900, (10, _ACCESS),
    ),
    "IOS-XE, every id except the native one": (
        SOURCE, _source("switchport trunk native vlan 10", f"{_ALLOWED} except 10"),
        _TRUNK, {10: 4000}, 10, 4000, (100, 999),
    ),
}


@pytest.mark.parametrize("target", SWITCHES)
@pytest.mark.parametrize("title", sorted(RENUMBERED))
def test_a_renumbered_native_vlan_stays_off_the_trunk(title: str, target: str) -> None:
    """The source trunk states the VLAN as its native VLAN and its
    list is every id BUT that one.  Renumbered onto an id the range
    covers, the VLAN is carried by the trunk on none of the seven --
    not untagged, and not tagged either -- the native line is there
    beside a list without it (on AOS-S and OS10: the review line),
    and the job says what was done, in the words for a number and
    not in the words for a merge."""
    source, text, trunk, vlan_map, before, after, tagged = RENUMBERED[title]
    job, final = _job_of(source, text, trunk, target, vlan_map)
    readings = _on_the_trunk(target, job, final)
    for port in readings:
        assert port.untagged is None, (title, target, port.untagged)
        assert not port.carries_tagged(after), (title, target)
        assert all(port.carries_tagged(vid) for vid in tagged), (title, target)
    if target == "aruba_aoss":
        assert said_how(job.rendered) == [(str(after), after, final, PORT_FORM)], job.rendered
        stanza = dict(_stanzas(job.rendered, "vlan "))[str(after)]
        assert SAID_OF_A_PORT.format(port=final, native=after) in stanza
        assert not [line for line in stanza if line.startswith(("untagged", "tagged"))], stanza
    elif target == "dell_os10":
        stanza = dict(_stanzas(job.rendered, "interface "))[final]
        at = stanza.index("no switchport access vlan")
        assert stanza[at - 1] == SAID_ON_OS10.format(native=after), stanza
    else:
        assert {port.left_out for port in readings} == {after}, (title, target)
    assert _said_of_the_native(job) == [
        f"vlan_rename: interface {final!r} had native VLAN {before} outside its allowed list, and the map gives "
        f"it the id {after}, which the list named only as a number no VLAN of the config had — {after} is taken "
        f"out of the list, and the trunk does not carry native VLAN {after}",
    ], job.warnings
    assert job.status == MigrationJobStatus.completed, (title, target, job.status)


@pytest.mark.parametrize("target", SWITCHES)
def test_a_merge_beside_such_a_list_still_clears(target: str) -> None:
    """The same EOS trunk, and the parking VLAN given the id of VLAN
    10 -- a VLAN of the config, which the trunk's range holds and the
    trunk carries tagged.  That is a merge: cleared, on all seven."""
    source, text, trunk, _map, _before, _after_id, _tagged = RENUMBERED["EOS, a parking VLAN beside every other id"]
    job, final = _job_of(source, text, trunk, target, {1000: 10})
    for port in _on_the_trunk(target, job, final):
        assert port.untagged is None and port.left_out is None, (target, port.untagged, port.left_out)
        assert port.carries_tagged(10) and port.carries_tagged(_ACCESS), target
    assert _said_of_the_native(job) == [
        f"vlan_rename: interface {final!r} had native VLAN 1000 {_OUTSIDE}, and the map merges it into VLAN 10, "
        f"which the trunk carries tagged — {_CLEARED}",
    ], job.warnings
    assert not said_how(job.rendered) and "no switchport access vlan" not in job.rendered


def _a_port(*lines: str) -> str:
    """An IOS-XE config with one port whose lines are *lines*: no
    `switchport mode trunk` is written for it here."""
    return "\n".join([
        "hostname sw1", "!", "vlan 10", " name users", "!", "vlan 20", " name desks", "!", "vlan 30", " name lab", "!",
        f"interface {_TRUNK}", *(f" {line}" for line in lines), "!", "end", "",
    ])


#: What a port that is not `switchport mode trunk` can say first, and
#: the mode its record then has.
_NOT_A_TRUNK = [
    (("switchport mode dynamic desirable",), "dynamic"),
    (("switchport mode dynamic auto",), "dynamic"),
    ((), None),
]


@pytest.mark.parametrize("first,mode", _NOT_A_TRUNK)
def test_a_port_that_can_become_a_trunk_is_cleared(first: tuple[str, ...], mode: str | None) -> None:
    """IOS-XE onto IOS-XE, whose renderer writes the trunk lines of a
    port in any mode.  A port in a dynamic mode, or with no mode line,
    states native VLAN 10 beside `allowed vlan 20,30`; with 10 given
    the id 20 it would, once it negotiates a trunk, carry VLAN 20
    untagged.  Its native line is not written, and the job says so."""
    text = _a_port(*first, "switchport trunk native vlan 10", f"{_ALLOWED} 20,30")
    assert get_codec(SOURCE).parse(text).interfaces[0].switchport_mode == mode
    job, final = _job_of(SOURCE, text, _TRUNK, SOURCE, {10: 20})
    stanza = dict(_stanzas(job.rendered, "interface "))[final]
    assert [line for line in stanza if "trunk" in line] == [f"{_ALLOWED} 20,30"], stanza
    assert _said_of_the_native(job) == [
        f"vlan_rename: interface {final!r} had native VLAN 10 {_OUTSIDE}, and the map merges it into VLAN 20, "
        f"which the trunk carries tagged — {_CLEARED}",
    ], job.warnings


@pytest.mark.parametrize("first,mode", _NOT_A_TRUNK)
def test_a_port_that_can_become_a_trunk_keeps_a_number_out(first: tuple[str, ...], mode: str | None) -> None:
    """...and beside `allowed vlan except 10`, with 10 given the id
    4000: the native line names 4000, and the list leaves it out."""
    text = _a_port(*first, "switchport trunk native vlan 10", f"{_ALLOWED} except 10")
    assert get_codec(SOURCE).parse(text).interfaces[0].switchport_mode == mode
    job, final = _job_of(SOURCE, text, _TRUNK, SOURCE, {10: 4000})
    stanza = dict(_stanzas(job.rendered, "interface "))[final]
    assert "switchport trunk native vlan 4000" in stanza, stanza
    allowed = next(line for line in stanza if line.startswith(_ALLOWED))
    assert _ids(allowed.rsplit(" ", 1)[1]) == set(range(1, 4095)) - {10, 4000}
    assert len(_said_of_the_native(job)) == 1 and _TAKEN_OUT in _said_of_the_native(job)[0], job.warnings


@pytest.mark.parametrize("target", SWITCHES)
def test_the_job_says_it_of_such_a_port_on_every_target(target: str) -> None:
    """The pass is the tree's, whatever is then written from it: the
    warning is the same onto all seven."""
    text = _a_port("switchport mode dynamic desirable", "switchport trunk native vlan 10", f"{_ALLOWED} 20,30")
    job, _final = _job_of(SOURCE, text, _TRUNK, target, {10: 20})
    said = _said_of_the_native(job)
    assert len(said) == 1 and said[0].endswith(
        f"the map merges it into VLAN 20, which the trunk carries tagged — {_CLEARED}"
    ), job.warnings


@pytest.mark.parametrize("first,mode", _NOT_A_TRUNK)
def test_such_a_ports_short_list_names_its_vlans(first: tuple[str, ...], mode: str | None) -> None:
    """`native vlan 10` beside `allowed vlan 500`, no VLAN 500 in the
    config, and 10 given the id 500.  The parser makes no VLAN from
    the trunk lines of a port that is not `switchport mode trunk`,
    and the port's short list is read as a trunk's is all the same:
    VLAN 500 is a VLAN the list names, the map merges VLAN 10 into
    it, and the native VLAN is cleared.  Taken out as a number, 500
    would leave the port its native line and NO allowed line --
    every VLAN, once it negotiates a trunk."""
    text = _a_port(*first, "switchport trunk native vlan 10", f"{_ALLOWED} 500")
    parsed = get_codec(SOURCE).parse(text)
    assert parsed.interfaces[0].switchport_mode == mode and 500 not in {vlan.id for vlan in parsed.vlans}
    job, final = _job_of(SOURCE, text, _TRUNK, SOURCE, {10: 500})
    stanza = dict(_stanzas(job.rendered, "interface "))[final]
    assert [line for line in stanza if "trunk" in line] == [f"{_ALLOWED} 500"], stanza
    assert _said_of_the_native(job) == [
        f"vlan_rename: interface {final!r} had native VLAN 10 {_OUTSIDE}, and the map merges it into VLAN 500, "
        f"which the trunk carries tagged — {_CLEARED}",
    ], job.warnings


def test_a_trunks_short_list_makes_it_a_merge() -> None:
    """...and the same lines under `switchport mode trunk` come to
    the same by another road: the parser makes a VLAN of each id of
    a trunk's short list, so VLAN 500 has a record, the map merges
    VLAN 10 into it, and the native VLAN is cleared."""
    text = _a_port("switchport mode trunk", "switchport trunk native vlan 10", f"{_ALLOWED} 500")
    assert 500 in {vlan.id for vlan in get_codec(SOURCE).parse(text).vlans}
    job, final = _job_of(SOURCE, text, _TRUNK, SOURCE, {10: 500})
    stanza = dict(_stanzas(job.rendered, "interface "))[final]
    assert [line for line in stanza if "trunk" in line] == ["switchport mode trunk", f"{_ALLOWED} 500"], stanza
    assert _said_of_the_native(job) == [
        f"vlan_rename: interface {final!r} had native VLAN 10 {_OUTSIDE}, and the map merges it into VLAN 500, "
        f"which the trunk carries tagged — {_CLEARED}",
    ], job.warnings


# ---------------------------------------------------------------------------
# A native VLAN the map DROPS, through jobs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", SWITCHES)
@pytest.mark.parametrize("trunk,vid,every", [
    # VLAN 1, which an IOS-XE trunk that states no native VLAN has by
    # its platform's default: beside no list (every VLAN), beside
    # `all`, and beside a list that names its VLANs.
    ((), 1, True),
    ((f"{_ALLOWED} all",), 1, True),
    ((f"{_ALLOWED} 1,10,100",), 1, False),
    # A native VLAN the trunk states.
    (("switchport trunk native vlan 10",), 10, True),
    (("switchport trunk native vlan 10", f"{_ALLOWED} 10,100"), 10, False),
])
def test_the_job_says_what_a_dropped_native_vlan_leaves(
    trunk: tuple[str, ...], vid: int, every: bool, target: str,
) -> None:
    """The pane's map drops the VLAN a trunk carries untagged.  The
    job's one warning for it, WHOLE, in both its forms: ``native VLAN
    cleared``, and -- where the trunk's list is every VLAN, which the
    pass leaves as it stands -- that an output writing the port as a
    trunk of every VLAN still allows the VLAN.  A job that said only
    "cleared" there said less than its own output does on the targets
    whose trunk has a default native VLAN."""
    job, final = _job_of(SOURCE, _source(*trunk), _TRUNK, target, {vid: None})
    want = _DROPPED.format(port=final, vid=vid) + (_STILL_HELD.format(vid=vid) if every else "")
    assert [str(text) for text in job.warnings if _CLEARED in str(text)] == [want], job.warnings
    assert job.status == MigrationJobStatus.completed, (target, job.status)
    if every and vid == 1 and target in HAVE_A_DEFAULT:
        # What the warning is for.  The output's trunk is a trunk of
        # every VLAN (no allowed line; on AOS-CX `vlan trunk allowed
        # all`) with no VLAN untagged, written the target's form for
        # that -- on IOS-XE and NX-OS the line for every trunk, this
        # output's other port being an access port: it still allows the
        # dropped VLAN, and carries it tagged.
        by_text, by_parser = _on_the_trunk(target, job, final)
        assert (by_text.untagged, by_parser.untagged, by_text.carries_tagged(1)) == (None, None, True), by_text
