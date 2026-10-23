"""A trunk's native VLAN in the grammar before ELS is read, or said.

EX switches before ELS state a trunk's native VLAN under the unit,
``unit 0 family ethernet-switching native-vlan-id <id>`` ("Configure the
VLAN identifier to associate with untagged packets received on the
interface", Juniper, the statement's page for EX Series), beside its
``vlan members``.  Not a member, the VLAN is carried untagged both ways;
a member as well, it is received untagged and sent tagged (KB17419, for
non-ELS EX switches).  The parser read nothing of the statement, so the
trunk's untagged VLAN was lost and nothing said so.

What such a trunk carries onto every target is held, with every other
shape of trunk, in ``tests/unit/migration/test_the_list_holds_the_native_vlan.py``
(shapes ``p1`` and ``p2``).  Here: each statement the tree has no form
for is said in a row, typed by hand, and its trunk keeps what it
carries -- the VLAN on its list, tagged, onto every target.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_the_list_holds_the_native_vlan import SWITCHES, read_text

pytestmark = pytest.mark.unit

_UNIT = "unit 0 family ethernet-switching"


def _text(*trunk: str, mode: str = "trunk") -> str:
    return "\n".join([
        "set system host-name sw1",
        "set vlans ten vlan-id 10", "set vlans twenty vlan-id 20",
        f"set interfaces ge-0/0/1 {_UNIT} port-mode {mode}",
        *(f"set interfaces ge-0/0/1 {line}" for line in trunk),
        f"set interfaces ge-0/0/2 {_UNIT} port-mode access",
        f"set interfaces ge-0/0/2 {_UNIT} vlan members twenty",
        "",
    ])


def _row(shown: str, why: str) -> str:
    return (
        f"interfaces {shown}: unit 0 family ethernet-switching native-vlan-id "
        f"-- {why}, so the statement is not translated"
    )


_ON_THE_MEMBERS = (
    "also on the trunk's vlan members, where it is received untagged and "
    "sent tagged (Juniper KB17419), which the tree has no form for"
)

#: (the text, the row, the trunk's native VLAN, its list), by hand.
SAID = {
    "a member as well": (
        _text(f"{_UNIT} native-vlan-id 10", f"{_UNIT} vlan members ten", f"{_UNIT} vlan members twenty"),
        _row("ge-0/0/1 (10)", _ON_THE_MEMBERS), None, {10, 20},
    ),
    "on vlan members all": (
        _text(f"{_UNIT} native-vlan-id 10", f"{_UNIT} vlan members all"),
        _row("ge-0/0/1 (10)", _ON_THE_MEMBERS), None, set(range(1, 4095)),
    ),
    "beside the interface's own": (
        _text("native-vlan-id 20", f"{_UNIT} native-vlan-id 10", f"{_UNIT} vlan members twenty"),
        _row("ge-0/0/1 (10)", "beside a native-vlan-id on the interface itself"), 20, {20},
    ),
    "not a trunk": (
        _text(f"{_UNIT} native-vlan-id 10", f"{_UNIT} vlan members twenty", mode="access"),
        _row("ge-0/0/1 (10)", "on a port that is not a trunk"), None, set(),
    ),
    "not a VLAN id": (
        _text(f"{_UNIT} native-vlan-id ten", f"{_UNIT} vlan members twenty"),
        _row("ge-0/0/1", "not one VLAN id"), None, {20},
    ),
}


@pytest.mark.parametrize("case", sorted(SAID))
def test_what_the_tree_has_no_form_for_is_said(case: str) -> None:
    text, row, native, listed = SAID[case]
    tree = get_codec("juniper_junos").parse(text)
    trunk = next(i for i in tree.interfaces if i.name == "ge-0/0/1")
    assert tree.dropped_tier3_sections == [row]
    assert (trunk.trunk_native_vlan, set(trunk.trunk_allowed_vlans)) == (native, listed)


def test_a_native_vlan_off_the_members_is_carried() -> None:
    tree = get_codec("juniper_junos").parse(_text(f"{_UNIT} native-vlan-id 10", f"{_UNIT} vlan members twenty"))
    trunk = next(i for i in tree.interfaces if i.name == "ge-0/0/1")
    assert (trunk.trunk_native_vlan, set(trunk.trunk_allowed_vlans)) == (10, {10, 20})
    assert tree.dropped_tier3_sections == []


@pytest.mark.parametrize(("native", "members", "listed"), [
    ("15", ("ten", "twenty"), [10, 15, 20]),
    ("1", ("2-4094",), list(range(1, 4095))),
])
def test_the_list_stays_in_rising_order(native: str, members: tuple[str, ...], listed: list[int]) -> None:
    """Put where ``_helpers.trunk_list_read`` puts it, before the first
    id greater than it: ``2-4094`` beside VLAN 1 is the list of every
    VLAN, in its order."""
    text = _text(f"{_UNIT} native-vlan-id {native}", *(f"{_UNIT} vlan members {m}" for m in members))
    trunk = next(i for i in get_codec("juniper_junos").parse(text).interfaces if i.name == "ge-0/0/1")
    assert (trunk.trunk_native_vlan, trunk.trunk_allowed_vlans) == (int(native), listed)


def test_the_rows_are_bounded() -> None:
    """A row for each reason, naming three and counting the rest."""
    lines = ["set system host-name sw1", "set vlans ten vlan-id 10"]
    for port in range(1, 6):
        lines += [
            f"set interfaces ge-0/0/{port} {_UNIT} port-mode trunk",
            f"set interfaces ge-0/0/{port} {_UNIT} native-vlan-id 10",
            f"set interfaces ge-0/0/{port} {_UNIT} vlan members ten",
        ]
    lines += [f"set interfaces ge-0/0/9 {_UNIT} native-vlan-id 10", ""]
    tree = get_codec("juniper_junos").parse("\n".join(lines))
    assert tree.dropped_tier3_sections == [
        _row("ge-0/0/1 (10), ge-0/0/2 (10), ge-0/0/3 (10) and 2 more", _ON_THE_MEMBERS),
        _row("ge-0/0/9 (10)", "on a port that is not a trunk"),
    ]


@pytest.mark.parametrize("target", SWITCHES)
def test_a_member_as_well_is_carried_tagged_and_said(target: str) -> None:
    """The trunk whose native VLAN is a member as well: onto every
    target the job says the statement, and the trunk carries VLAN 10
    tagged and not untagged -- read from the output's text, by the
    guard's reader of each grammar."""
    text, row, _native, _listed = SAID["a member as well"]
    port_map = {"ge-0/0/1": "1", "ge-0/0/2": "2"} if target == "aruba_aoss" else {}
    job = run_plan_with_checked_names(
        get_codec("juniper_junos"), get_codec(target), text, port_rename_map=port_map,
    )
    assert job.rendered, job.error
    assert row in job.dropped_tier3_sections
    final = re.sub(r"\s+", "", job.port_renames.get("ge-0/0/1", "ge-0/0/1")).casefold()
    port = {re.sub(r"\s+", "", name).casefold(): p for name, p in read_text(job.rendered, target).items()}[final]
    assert port.untagged != 10 and port.carries_tagged(10), (target, port)
