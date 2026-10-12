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
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalInterface, CanonicalVlan
from netcanon.migration.canonical.vlan_names import translate_vlan_ids
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_overrides
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


@pytest.mark.parametrize("trunk,reported", [
    # Every VLAN, and so no VLAN in particular: 555 is nowhere.
    ((), True),
    ((f"{_ALLOWED} all",), True),
    ((f"{_ALLOWED} 1-4094",), True),
    # A list like any other names its ids: 555 is on the trunk, and
    # the drop takes it off.
    ((f"{_ALLOWED} 2-4094",), False),
    ((f"{_ALLOWED} 10,555",), False),
    ((f"{_ALLOWED} 10",), True),
    ((f"{_ALLOWED} none",), True),
])
def test_a_map_entry_for_a_vlan_nowhere(trunk: tuple[str, ...], reported: bool) -> None:
    """The pane's map can name a VLAN the config does not have (a
    typed id, a map kept from another config).  The job says so --
    and one trunk that states no allowed list, which is a trunk of
    every VLAN, does not make every id there is a VLAN of the
    config."""
    job = run_plan_with_overrides(
        get_codec(SOURCE), get_codec("juniper_junos"), _source(*trunk),
        port_rename_map={}, vlan_rename_map={555: None}, force=True,
    )
    said = [str(text) for text in job.warnings if _NOWHERE in str(text)]
    assert len(said) == reported, (trunk, job.warnings)
    if reported:
        assert said[0].endswith("entry ignored"), said
    # And the VLANs the pane offers are the config's own, not 4,094.
    assert set(job.source_vlans) - {555} == {10, _ACCESS, 100, 999}, (trunk, len(job.source_vlans))


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
