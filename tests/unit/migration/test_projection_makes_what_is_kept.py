"""The switchport projection makes what its caller keeps -- and gives what its rule says.

``project_switchport_to_vlan`` mirrors each port's VLANs onto the VLAN
records.  For a trunk whose list is wide it made a record for every id
of the list and stamped the port on each, and the six codecs that call
it dropped, on their next line, every record they had not kept: on a
switch that declares ten VLANs, 48 trunks that state ``1-4093`` were
196,464 records and stamps, for the 480 that stayed.  And each stamp
was indexed by a queue of its own.
Nothing in such a config is odd, and nothing in it is long.

The projection is now told what its caller keeps (``keep``), indexes a
port list with two counts a name, and the lists of ids it reads are
built from one shared tuple of ints.  None of that may change a tree.
Four kinds of test:

* **The same tree, the same errors.**  The projection is written out
  here with plain lists -- as it stood before it was told what its
  caller keeps, with the one rule that has changed since: a trunk is
  an untagged member of its native VLAN only where its list holds
  that VLAN -- and the one that ships is compared with it over trees
  built to hold every way of writing a trunk's list, with the set a
  codec keeps and without it.
* **The same reading of a text.**  Texts for each codec that prunes,
  and what each came to before the change: a digest of the ports and
  the VLANs, or the sentence the parse failed with.  A list wider than
  the bound that also names an id that is not a VLAN id (``1-200,5000``)
  is the case a set of kept ids cannot see by itself: the parse failed
  before, and has to fail still.
* **What an entry costs**, counted in bytes by ``tracemalloc`` and
  never read from a clock: a port-side id, and a membership.  The
  ceilings are several times what is measured, and far under what the
  same entry cost before.
* **The shared ids** are equal to the ranges they replace, and are the
  same objects wherever a list is expanded.
"""

from __future__ import annotations

import gc
import hashlib
import json
import random
import tracemalloc
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from netcanon.migration.canonical import transforms
from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalInterface, CanonicalVlan
from netcanon.migration.canonical.transforms import (
    _natural_port_sort_key,
    project_switchport_to_vlan,
    project_vlan_to_switchport,
    switchport_declared_vlan_ids,
)
from netcanon.migration.codecs._helpers import (
    VLAN_IDS,
    _parse_vlan_list,
    merge_trunk_allowed,
    vlan_id_run,
)
from netcanon.migration.codecs.arista_eos.parse import _expand_vlan_list
from netcanon.migration.codecs.base import ParseError
from netcanon.migration.codecs.juniper_junos.parse import _resolve_vlan_member_to_vids
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# The projection in plain lists
# ---------------------------------------------------------------------------


def _in_plain_lists(intent: CanonicalIntent) -> None:
    """``project_switchport_to_vlan`` as it stood before it was told
    what its caller keeps: a record for every id of a list that is
    not one of the two whole ones, and every port looked for in the
    list it joins.  Written with plain lists, and kept to be compared
    with.

    Its rule for a native VLAN is the one that ships.  The list is
    what a trunk carries: the port is untagged in its native VLAN
    where the list holds that VLAN, and no member of it where the
    list leaves it out.  The record is made either way."""
    by_id = {vlan.id: vlan for vlan in intent.vlans}

    def vlan_of(vid: int) -> CanonicalVlan:
        if vid not in by_id:
            by_id[vid] = CanonicalVlan(id=vid)
            intent.vlans.append(by_id[vid])
        return by_id[vid]

    def add(ports: list[str], name: str) -> None:
        if name not in ports:
            ports.append(name)

    whole = (set(range(1, 4095)), set(range(2, 4095)))
    for iface in intent.interfaces:
        if iface.switchport_mode == "access":
            if iface.access_vlan is not None:
                vlan_of(iface.access_vlan)
        elif iface.switchport_mode == "trunk":
            if set(iface.trunk_allowed_vlans) not in whole:
                for vid in iface.trunk_allowed_vlans:
                    vlan_of(vid)
            if iface.trunk_native_vlan is not None:
                vlan_of(iface.trunk_native_vlan)
    for iface in intent.interfaces:
        if iface.switchport_mode == "access":
            if iface.access_vlan is not None:
                add(vlan_of(iface.access_vlan).untagged_ports, iface.name)
        elif iface.switchport_mode == "trunk":
            allowed = set(iface.trunk_allowed_vlans)
            if allowed in whole:
                for vlan in intent.vlans:
                    if vlan.id in allowed:
                        add(vlan.tagged_ports, iface.name)
            else:
                for vid in iface.trunk_allowed_vlans:
                    add(vlan_of(vid).tagged_ports, iface.name)
            if iface.trunk_native_vlan is not None and iface.trunk_native_vlan in allowed:
                vlan = vlan_of(iface.trunk_native_vlan)
                add(vlan.untagged_ports, iface.name)
                if iface.name in vlan.tagged_ports:
                    vlan.tagged_ports.remove(iface.name)
    for vlan in intent.vlans:
        vlan.tagged_ports.sort(key=_natural_port_sort_key)
        vlan.untagged_ports.sort(key=_natural_port_sort_key)


def _outcome(project: Callable[[CanonicalIntent], None], tree: CanonicalIntent) -> object:
    """What *project* made of a copy of *tree*: the tree, or the
    errors it refused an id with."""
    mine = tree.model_copy(deep=True)
    try:
        project(mine)
    except ValidationError as refused:
        return [(error["type"], error["loc"], error["msg"], error["input"]) for error in refused.errors()]
    return mine.model_dump()


def _as_a_codec_calls(project: Callable[..., None], *, tell: bool) -> Callable[[CanonicalIntent], None]:
    """*project* the way the six port-centric codecs run it: the set
    they keep, the projection, the prune -- handing the set over, or
    not."""

    def run(tree: CanonicalIntent) -> None:
        kept = {vlan.id for vlan in tree.vlans} | switchport_declared_vlan_ids(tree)
        if tell:
            project(tree, keep=kept)
        else:
            project(tree)
        tree.vlans = [vlan for vlan in tree.vlans if vlan.id in kept]

    return run


#: Every way of writing a trunk's list.
LISTS: dict[str, list[int]] = {
    "no list": [],
    "a narrow list": [10, 20, 30],
    "a narrow list with an id twice, out of order": [20, 10, 20],
    "as many ids as still count as narrow": list(range(1, 129)),
    "one id more than that": list(range(1, 130)),
    "a wide range": list(range(100, 3001)),
    "every id but one in the middle": [vid for vid in range(1, 4095) if vid != 100],
    "every id but the last": list(range(1, 4094)),
    "every id": list(range(1, 4095)),
    "every id, backwards and one of them twice": [*range(4094, 0, -1), 7],
    "every id but 1": list(range(2, 4095)),
    "4,094 entries that are not every id": [1, *range(1, 4094)],
    "a wide list and an id past the last": [*range(1, 201), 5000],
    "zero and then a wide list": [0, *range(1, 301)],
    "a narrow list and an id past the last": [10, 5000],
}

#: The native VLAN of the trunk under test: none, one its list holds
#: and the config declares, one its list holds that nobody declares,
#: and one outside every list here.
NATIVES = (None, 20, 150, 999)

#: The VLANs the config declares -- some already holding ports, one of
#: them twice, as a record made by an earlier pass can.
DECLARED: tuple[tuple[tuple[int, list[str], list[str]], ...], ...] = (
    (),
    ((10, [], []), (20, ["Gi1", "Gi1"], [])),
    ((1, [], ["Gi9"]), (10, ["Po7"], []), (20, [], []), (150, [], []), (300, ["Gi1"], ["Gi2"]), (3000, [], [])),
)


def _built(allowed: list[int], native: int | None, declared: tuple) -> CanonicalIntent:
    """A switch with the trunk under test on it, beside a port of each
    other kind: a trunk of every id ahead of an access port whose VLAN
    nobody declared, two ports on one VLAN, names that sort alike."""
    tree = CanonicalIntent(vlans=[
        CanonicalVlan(id=vid, tagged_ports=list(tagged), untagged_ports=list(untagged))
        for vid, tagged, untagged in declared
    ])
    ports: list[dict] = [
        {"name": "Po1", "switchport_mode": "trunk", "trunk_allowed_vlans": list(range(1, 4095))},
        {"name": "Gi1", "switchport_mode": "trunk", "trunk_allowed_vlans": list(allowed),
         "trunk_native_vlan": native},
        {"name": "Gi2", "switchport_mode": "trunk", "trunk_allowed_vlans": [10, 20]},
        {"name": "Gi01", "switchport_mode": "access", "access_vlan": 20},
        {"name": "Gi3", "switchport_mode": "access", "access_vlan": 777},
        {"name": "Po2", "switchport_mode": "trunk", "trunk_allowed_vlans": list(range(2, 4095)),
         "trunk_native_vlan": 10},
        {"name": "Gi4", "switchport_mode": "dynamic", "trunk_allowed_vlans": [30, 40]},
        {"name": "Gi5", "trunk_allowed_vlans": [50]},
        {"name": "Gi6", "switchport_mode": "access"},
    ]
    tree.interfaces = [CanonicalInterface.model_validate(port) for port in ports]
    return tree


class TestTheSameTreeAsBefore:
    @pytest.mark.parametrize("written", sorted(LISTS))
    def test_with_the_kept_set_and_without(self, written: str) -> None:
        """Three calls that have to agree with the projection in
        plain lists: the one a codec makes now (the set handed over),
        the one it made (not handed over), and the one AOS-S makes
        (nothing pruned)."""
        for native in NATIVES:
            for declared in DECLARED:
                tree = _built(LISTS[written], native, declared)
                was_pruned = _outcome(_as_a_codec_calls(_in_plain_lists, tell=False), tree)
                where = f"{written}, native {native}, {len(declared)} VLANs declared"
                assert _outcome(_as_a_codec_calls(project_switchport_to_vlan, tell=True), tree) == was_pruned, where
                assert _outcome(_as_a_codec_calls(project_switchport_to_vlan, tell=False), tree) == was_pruned, where
                assert _outcome(project_switchport_to_vlan, tree) == _outcome(_in_plain_lists, tree), where

    def test_each_kind_of_outcome_is_among_them(self) -> None:
        """A table that only ever refused, or never did, would agree
        with anything."""
        outcomes = {
            written: _outcome(_as_a_codec_calls(project_switchport_to_vlan, tell=True), _built(ids, 20, DECLARED[1]))
            for written, ids in LISTS.items()
        }
        refused = sorted(written for written, outcome in outcomes.items() if isinstance(outcome, list))
        assert refused == [
            "a narrow list and an id past the last", "a wide list and an id past the last",
            "zero and then a wide list",
        ]
        kept = outcomes["a wide range"]
        assert isinstance(kept, dict) and [vlan["id"] for vlan in kept["vlans"]] == [10, 20, 777]

    def test_on_random_switches(self) -> None:
        names = [f"Gi1/0/{number}" for number in range(1, 12)] + ["Gi1", "Gi01", "Gi001", "Po1", "1/A1", "ae0"]
        rng = random.Random(40)
        for case in range(120):
            tree = CanonicalIntent()
            for vid in rng.sample(range(1, 80), rng.randrange(0, 10)):
                tagged = [rng.choice(names) for _ in range(rng.randrange(0, 4))] if rng.random() < 0.3 else []
                untagged = [rng.choice(names) for _ in range(rng.randrange(0, 3))] if rng.random() < 0.3 else []
                tree.vlans.append(CanonicalVlan(id=vid, tagged_ports=tagged, untagged_ports=untagged))
            wide_left = 2
            for name in rng.sample(names, rng.randrange(1, len(names))):
                port = CanonicalInterface(name=name)
                roll = rng.random()
                if roll < 0.25:
                    port.switchport_mode = "access"
                    port.access_vlan = rng.randrange(1, 90) if rng.random() < 0.9 else None
                elif roll < 0.9:
                    port.switchport_mode = "trunk"
                    written = rng.choice(sorted(LISTS))
                    if len(LISTS[written]) > 128:
                        written = written if wide_left else "a narrow list"
                        wide_left -= 1 if wide_left else 0
                    port.trunk_allowed_vlans = list(LISTS[written])
                    if rng.random() < 0.4:
                        port.trunk_native_vlan = rng.choice([1, rng.randrange(1, 90), rng.randrange(1, 4095)])
                elif roll < 0.95:
                    port.switchport_mode = "dynamic"
                tree.interfaces.append(port)
            if rng.random() < 0.15:
                twin = tree.interfaces[0].model_copy(deep=True)
                twin.trunk_native_vlan = rng.randrange(1, 90)
                tree.interfaces.append(twin)
            was_pruned = _outcome(_as_a_codec_calls(_in_plain_lists, tell=False), tree)
            assert _outcome(_as_a_codec_calls(project_switchport_to_vlan, tell=True), tree) == was_pruned, case
            assert _outcome(project_switchport_to_vlan, tree) == _outcome(_in_plain_lists, tree), case

    def test_a_second_call_changes_nothing(self) -> None:
        for written in ("a wide range", "every id", "every id but 1", "a narrow list"):
            tree = _built(LISTS[written], 150, DECLARED[2])
            kept = {vlan.id for vlan in tree.vlans} | switchport_declared_vlan_ids(tree)
            project_switchport_to_vlan(tree, keep=kept)
            once = tree.model_dump()
            project_switchport_to_vlan(tree, keep=kept)
            assert tree.model_dump() == once, written


class TestOnlyWhatIsKeptIsMade:
    def test_nothing_is_made_to_be_dropped(self) -> None:
        """The point of handing the set over: after the projection
        there is nothing left for the prune to take out."""
        for written, ids in LISTS.items():
            tree = _built(ids, 150, DECLARED[2])
            kept = {vlan.id for vlan in tree.vlans} | switchport_declared_vlan_ids(tree)
            try:
                project_switchport_to_vlan(tree, keep=kept)
            except ValidationError:
                continue
            assert {vlan.id for vlan in tree.vlans} <= kept, written

    def test_without_the_set_every_id_is_made(self) -> None:
        tree = _built(LISTS["a wide range"], None, ())
        project_switchport_to_vlan(tree)
        assert {vlan.id for vlan in tree.vlans} >= set(range(100, 3001))

    @pytest.mark.parametrize("stray", [5000, 4095, 0, -3, 99999999999999999999999])
    def test_an_id_that_is_no_vlan_id_is_refused(self, stray: int) -> None:
        """A narrow list is in the kept set whole, so its stray id
        reaches the record.  A wide one is not -- and its stray id is
        handed to the record all the same."""
        for ids in ([10, stray], [*range(1, 201), stray], [stray, *range(1, 301)]):
            tree = CanonicalIntent(interfaces=[
                CanonicalInterface(name="Gi1", switchport_mode="trunk", trunk_allowed_vlans=ids),
            ])
            kept = switchport_declared_vlan_ids(tree)
            with pytest.raises(ValidationError):
                project_switchport_to_vlan(tree, keep=kept)

    def test_a_ports_sort_key_is_worked_out_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Thirty trunks on thirty VLANs are thirty names, each in
        thirty lists that are sorted."""
        asked: list[str] = []

        def counted(name: str) -> tuple:
            asked.append(name)
            return _natural_port_sort_key(name)

        monkeypatch.setattr(transforms, "_natural_port_sort_key", counted)
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(id=vid) for vid in range(2, 32)],
            interfaces=[
                CanonicalInterface(
                    name=f"Gi1/0/{port}", switchport_mode="trunk", trunk_allowed_vlans=list(range(1, 4095)),
                )
                for port in range(30, 0, -1)
            ],
        )
        project_switchport_to_vlan(tree)
        assert sorted(asked) == sorted(port.name for port in tree.interfaces)
        assert tree.vlans[0].tagged_ports == [f"Gi1/0/{port}" for port in range(1, 31)]

    def test_which_lists_are_whole(self) -> None:
        every, but_one = transforms._TRUNK_ALL_RANGE_FULL, transforms._TRUNK_ALL_RANGE_OPERATIONAL
        assert transforms._every_id(list(range(1, 4095))) is every
        assert transforms._every_id([*range(4094, 0, -1), 7, 7]) is every
        assert transforms._every_id(list(range(2, 4095))) is but_one
        for neither in (
            [], [1], list(range(1, 4094)), list(range(3, 4095)), [1, *range(1, 4094)], [*range(2, 4095), 5000],
        ):
            assert transforms._every_id(neither) is None


class TestTheReverseProjection:
    """``project_vlan_to_switchport`` looked through a port's own list
    for every VLAN the port is tagged in."""

    def test_a_vlan_is_listed_once_in_its_place(self) -> None:
        tree = CanonicalIntent(
            vlans=[
                CanonicalVlan(id=10, tagged_ports=["1"]), CanonicalVlan(id=20, tagged_ports=["1", "2"]),
                CanonicalVlan(id=10, tagged_ports=["1", "2"]), CanonicalVlan(id=30, tagged_ports=["1"]),
                CanonicalVlan(id=40, untagged_ports=["1"]), CanonicalVlan(id=20, tagged_ports=["2"]),
            ],
            interfaces=[CanonicalInterface(name="1", trunk_allowed_vlans=[30, 10, 30]), CanonicalInterface(name="2")],
        )
        project_vlan_to_switchport(tree)
        one, two = tree.interfaces
        # (VLAN 40, which port 1 is untagged in, is in its list as well:
        # the list is what the trunk carries.)
        assert (one.switchport_mode, one.trunk_allowed_vlans, one.trunk_native_vlan) == (
            "trunk", [30, 10, 30, 20, 40], 40,
        )
        assert (two.switchport_mode, two.trunk_allowed_vlans) == ("trunk", [20, 10])

    @pytest.mark.parametrize("untagged_in,tagged_in,listed,native", [
        # Among the tagged VLANs, where its record stands among theirs.
        ((10,), (20, 30), [10, 20, 30], 10),
        ((20,), (10, 30), [10, 20, 30], 20),
        ((30,), (10, 20), [10, 20, 30], 30),
        # Untagged in two: the first is the native VLAN, and the only
        # one of the two the trunk can carry untagged.
        ((10, 20), (30,), [10, 30], 10),
        # One VLAN both ways: it is in the list once.
        ((10,), (10, 20), [10, 20], 10),
        # Tagged only: no native VLAN, and nothing is added.
        ((), (20, 30), [20, 30], None),
    ])
    def test_the_untagged_vlan_is_in_the_list(
        self, untagged_in: tuple, tagged_in: tuple, listed: list[int], native: int | None,
    ) -> None:
        """A port tagged in some VLANs and untagged in one is a trunk
        that carries all of them.  Its list left the untagged one out,
        and a target on which the list decides what a trunk carries
        was written a native VLAN it does not carry."""
        tree = CanonicalIntent(vlans=[
            CanonicalVlan(
                id=vid,
                tagged_ports=["1"] if vid in tagged_in else [],
                untagged_ports=["1"] if vid in untagged_in else [],
            )
            for vid in (10, 20, 30)
        ])
        project_vlan_to_switchport(tree)
        (port,) = tree.interfaces
        assert (port.switchport_mode, port.trunk_allowed_vlans, port.trunk_native_vlan) == ("trunk", listed, native)

    def test_a_native_vlan_it_had_already(self) -> None:
        """A record that states a native VLAN the lists do not name it
        untagged in keeps it, and it stays out of the list: stated,
        and not carried.  One the lists do name it untagged in goes
        into the list like any other."""
        for had, listed in ((5, [20]), (10, [10, 20])):
            tree = CanonicalIntent(
                vlans=[CanonicalVlan(id=10, untagged_ports=["1"]), CanonicalVlan(id=20, tagged_ports=["1"])],
                interfaces=[CanonicalInterface(name="1", trunk_native_vlan=had)],
            )
            project_vlan_to_switchport(tree)
            (port,) = tree.interfaces
            assert (port.trunk_native_vlan, port.trunk_allowed_vlans) == (had, listed)

    def test_the_two_projections_agree(self) -> None:
        """What one makes of a port, the other reads back as the same
        memberships: untagged where the list holds the native VLAN."""
        tree = CanonicalIntent(vlans=[
            CanonicalVlan(id=10, untagged_ports=["1"]), CanonicalVlan(id=20, tagged_ports=["1"]),
            CanonicalVlan(id=30, tagged_ports=["1"]),
        ])
        project_vlan_to_switchport(tree)
        before = [(vlan.id, vlan.tagged_ports, vlan.untagged_ports) for vlan in tree.vlans]
        for vlan in tree.vlans:
            vlan.tagged_ports, vlan.untagged_ports = [], []
        project_switchport_to_vlan(tree)
        assert [(vlan.id, vlan.tagged_ports, vlan.untagged_ports) for vlan in tree.vlans] == before


# ---------------------------------------------------------------------------
# Texts, and what each came to before the change
# ---------------------------------------------------------------------------

_Port = tuple


def _lines(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _iosxe(vlans: list[int], ports: list[_Port]) -> str:
    out = ["hostname T", "!"]
    for vid in vlans:
        out += [f"vlan {vid}", f" name V{vid}", "!"]
    for at, port in enumerate(ports, 1):
        out.append(f"interface GigabitEthernet1/0/{at}")
        if port[0] == "access":
            out += [" switchport mode access", f" switchport access vlan {port[1]}"]
        else:
            out.append(" switchport mode trunk")
            if port[2] is not None:
                out.append(f" switchport trunk native vlan {port[2]}")
            out += [f" switchport trunk allowed vlan {spec}" for spec in port[1]]
        out.append("!")
    return _lines(*out, "end")


def _nxos(vlans: list[int], ports: list[_Port]) -> str:
    out = ["hostname T", ""]
    for vid in vlans:
        out += [f"vlan {vid}", f"  name V{vid}"]
    out.append("")
    for at, port in enumerate(ports, 1):
        out += [f"interface Ethernet1/{at}", "  switchport"]
        if port[0] == "access":
            out += ["  switchport mode access", f"  switchport access vlan {port[1]}"]
        else:
            out.append("  switchport mode trunk")
            if port[2] is not None:
                out.append(f"  switchport trunk native vlan {port[2]}")
            out += [f"  switchport trunk allowed vlan {spec}" for spec in port[1]]
        out.append("")
    return _lines(*out)


def _arista(vlans: list[int], ports: list[_Port]) -> str:
    out = ["hostname T", "!"]
    for vid in vlans:
        out += [f"vlan {vid}", f"   name V{vid}", "!"]
    for at, port in enumerate(ports, 1):
        out.append(f"interface Ethernet{at}")
        if port[0] == "access":
            out.append(f"   switchport access vlan {port[1]}")
        else:
            out.append("   switchport mode trunk")
            if port[2] is not None:
                out.append(f"   switchport trunk native vlan {port[2]}")
            out += [f"   switchport trunk allowed vlan {spec}" for spec in port[1]]
        out.append("!")
    return _lines(*out, "end")


def _os10(vlans: list[int], ports: list[_Port]) -> str:
    out = ["! Version 10.5.4.0", "hostname T", "!"]
    for vid in vlans:
        out += [f"interface vlan{vid}", " no shutdown", "!"]
    for at, port in enumerate(ports, 1):
        out += [f"interface ethernet1/1/{at}", " no shutdown"]
        if port[0] == "access":
            out += [" switchport mode access", f" switchport access vlan {port[1]}"]
        else:
            out.append(" switchport mode trunk")
            if port[2] is not None:
                out.append(f" switchport access vlan {port[2]}")
            out += [f" switchport trunk allowed vlan {spec}" for spec in port[1]]
        out.append("!")
    return _lines(*out)


def _aoscx(vlans: list[int], ports: list[_Port]) -> str:
    out = ["hostname T"]
    for vid in vlans:
        out += [f"vlan {vid}", f"    name V{vid}"]
    for at, port in enumerate(ports, 1):
        out += [f"interface 1/1/{at}", "    no shutdown", "    no routing"]
        if port[0] == "access":
            out.append(f"    vlan access {port[1]}")
        else:
            if port[2] is not None:
                out.append(f"    vlan trunk native {port[2]}")
            out += [f"    vlan trunk allowed {spec}" for spec in port[1]]
    return _lines(*out)


def _junos(vlans: list[int], ports: list[_Port]) -> str:
    out = ["set system host-name T"]
    for vid in vlans:
        out.append(f"set vlans V{vid} vlan-id {vid}")
    for at, port in enumerate(ports):
        base = f"set interfaces ge-0/0/{at} unit 0 family ethernet-switching"
        if port[0] == "access":
            out += [f"{base} interface-mode access", f"{base} vlan members {port[1]}"]
        else:
            out.append(f"{base} interface-mode trunk")
            if port[2] is not None:
                out.append(f"set interfaces ge-0/0/{at} native-vlan-id {port[2]}")
            out += [f"{base} vlan members {token}" for spec in port[1] for token in spec.split(",")]
    return _lines(*out)


#: The six codecs that prune after projecting, and how each writes a
#: switch: declared VLANs, then ports -- ``("trunk", [list, ...],
#: native)`` with a line for each list, or ``("access", vlan)``.
WRITTEN_BY: dict[str, Callable[[list[int], list[_Port]], str]] = {
    "arista_eos": _arista, "aruba_aoscx": _aoscx, "cisco_iosxe_cli": _iosxe,
    "cisco_nxos": _nxos, "dell_os10": _os10, "juniper_junos": _junos,
}

#: The four whose list takes the Cisco keywords.
CISCO_LISTS = ("arista_eos", "cisco_iosxe_cli", "cisco_nxos", "dell_os10")


def _trunk(*lists: str, native: int | None = None) -> _Port:
    return ("trunk", list(lists), native)


#: Switches written to reach where a projection that makes only what
#: is kept could differ from one that makes everything.
SWITCHES: dict[str, tuple[list[int], list[_Port]]] = {
    "a wide list and an id past the last": ([10, 20], [_trunk("1-200,5000")]),
    "a narrow list that is an id past the last": ([10, 20], [_trunk("5000")]),
    "a wide list and 4095": ([10, 20], [_trunk("1-200,4095")]),
    "zero and then a wide list": ([10, 20], [_trunk("0,1-300")]),
    "a wide list and a number of 23 digits": ([10, 20], [_trunk("1-300,99999999999999999999999")]),
    "a wide list after a port that is fine": ([10], [_trunk("10"), _trunk("1-4093,4095")]),
    "one range twice": ([10, 20, 250], [_trunk("2-300,2-300")]),
    "a wide list and a native VLAN nobody declared": ([10, 20], [_trunk("1-500", native=999)]),
    "a wide list and a declared native VLAN inside it": ([10, 20, 300], [_trunk("1-500", native=300)]),
    "a wide list and an undeclared native VLAN inside it": ([10, 20], [_trunk("1-500", native=150)]),
    "an access VLAN nobody declared beside a wide list": ([10], [("access", 777), _trunk("1-4093")]),
    "every way of writing a list, on one switch": (
        [*range(10, 20), 3000],
        [
            _trunk("all"), _trunk("1-4094"), _trunk("1-4093"), _trunk("10-19"), _trunk("2-4094", native=10),
            _trunk("1-99,101-4094"), _trunk(), _trunk("100-3000"), _trunk("3000,10,15"), ("access", 12),
        ],
    ),
    "a wide list and then narrow ones, nothing declared": ([], [_trunk("1-600"), _trunk("300,301"), _trunk("5-7")]),
    "narrow lists and then a wide one, nothing declared": ([], [_trunk("300,301"), _trunk("5-7"), _trunk("1-600")]),
    "two trunks of 2-4000, nothing declared": ([], [_trunk("2-4000"), _trunk("2-4000")]),
    "129 ids": ([5], [_trunk("1-129")]),
    "128 ids": ([5], [_trunk("1-128")]),
    "VLAN 1 declared under every id but 1": ([1, 10], [_trunk("2-4094"), _trunk("1-4094")]),
}

#: And with the keywords, for the four codecs that read them.
SWITCHES_WITH_KEYWORDS: dict[str, tuple[list[int], list[_Port]]] = {
    "all, none and except": ([10, 100, 200], [_trunk("all"), _trunk("none"), _trunk("except 100"), _trunk("except 1")]),
    "a list that goes on with add": ([10, 20, 600], [_trunk("1-500", "add 501-900"), _trunk("10", "add 20")]),
    "a list cut with remove": ([10, 20, 600], [_trunk("1-900", "remove 20-30")]),
    "add that brings an id past the last": ([10], [_trunk("1-300", "add 5000")]),
}


def _texts() -> dict[str, tuple[str, str]]:
    """Title to ``(codec, text)``."""
    texts: dict[str, tuple[str, str]] = {}
    for codec, write in WRITTEN_BY.items():
        for title, (vlans, ports) in SWITCHES.items():
            texts[f"{codec}: {title}"] = (codec, write(vlans, ports))
        if codec in CISCO_LISTS:
            for title, (vlans, ports) in SWITCHES_WITH_KEYWORDS.items():
                texts[f"{codec}: {title}"] = (codec, write(vlans, ports))
    texts["cisco_nxos: every VLAN declared in one line"] = ("cisco_nxos", _nxos([], [
        _trunk("all"), _trunk("1-4093"), _trunk("7-900"),
    ]).replace("hostname T\n", "hostname T\nvlan 1-4094\n"))
    texts["juniper_junos: members by name beside a wide range"] = ("juniper_junos", _junos([10, 20, 3000], [
        _trunk("V10,V20"), _trunk("100-3000", native=20), _trunk("V3000,1-4093"),
    ]))
    return texts


TEXTS = _texts()


def _came_to(codec: str, text: str) -> str:
    """What the parse made of the ports and the VLANs, as a digest --
    or the sentence it failed with."""
    try:
        tree = get_codec(codec).parse(text)
    except ParseError as refused:
        return "fails: " + str(refused).split("(", 1)[-1].rstrip(")")
    facts = {
        "vlans": [[vlan.id, vlan.name, vlan.tagged_ports, vlan.untagged_ports] for vlan in tree.vlans],
        "ports": [
            [port.name, port.switchport_mode, port.access_vlan, port.trunk_native_vlan, port.trunk_allowed_vlans]
            for port in tree.interfaces
        ],
    }
    return hashlib.sha256(json.dumps(facts).encode("utf-8")).hexdigest()[:12]


_TOO_HIGH = "fails: id: Input should be less than or equal to 4094"
_TOO_LOW = "fails: id: Input should be greater than or equal to 1"

#: What :func:`_came_to` gave for each text on the code as it was
#: before the projection took ``keep``.  A value changes only when a
#: parser's reading of that text is changed on purpose; the failing
#: assertion prints the new one.
#:
#: Four have been changed on purpose, and by one port each: "every
#: way of writing a list, on one switch" for the four codecs whose
#: trunk carries every VLAN when it states no list.  That text has a
#: trunk with no allowed line (on AOS-CX, one that says ``all``),
#: which was read as an empty list and is read as every id, so the
#: port is also among the tagged ports of each declared VLAN.
#: ``TestATrunkThatStatesNoList`` below says the same in full.
#:
#: Seven more were changed on purpose, when a trunk's list became what
#: the trunk carries.  "A wide list and a native VLAN nobody declared"
#: on each of the six codecs, and Junos's "members by name beside a
#: wide range": each has a trunk whose native VLAN its list leaves
#: out, and that port is no longer among the untagged ports of that
#: VLAN.  (On OS10, whose allowed line names tagged VLANs only, the
#: access VLAN is in the trunk's list instead and the port is still
#: untagged in it.)
#:
#: And every text of the four codecs whose trunk has a default native
#: VLAN was changed on purpose where a trunk states no native VLAN and
#: its list holds VLAN 1 (IOS-XE, NX-OS, EOS, AOS-CX; OS10 and Junos
#: not at all).  Such a port has native VLAN 1 in the tree and is an
#: UNTAGGED member of VLAN 1, where it was a tagged one -- and VLAN 1
#: has a record with no name where the text declares none, the wide
#: lists among them: a default is a single VLAN, as a native line is.
#: Nothing else about any of those trees is other than it was
#: (``TestADefaultNativeVlan`` below says one in full).
BEFORE: dict[str, str] = {
    "arista_eos: 128 ids": "41ac02c43ffb",
    "arista_eos: 129 ids": "ad426963f10b",
    "arista_eos: VLAN 1 declared under every id but 1": "008624ef2c13",
    "arista_eos: a list cut with remove": "a6dc5658da08",
    "arista_eos: a list that goes on with add": "823d8ef3000c",
    "arista_eos: a narrow list that is an id past the last": _TOO_HIGH,
    "arista_eos: a wide list after a port that is fine": _TOO_HIGH,
    "arista_eos: a wide list and 4095": _TOO_HIGH,
    "arista_eos: a wide list and a declared native VLAN inside it": "c691f6aa6a4f",
    "arista_eos: a wide list and a native VLAN nobody declared": "7a7cd3a9e540",
    "arista_eos: a wide list and a number of 23 digits": _TOO_HIGH,
    "arista_eos: a wide list and an id past the last": _TOO_HIGH,
    "arista_eos: a wide list and an undeclared native VLAN inside it": "9c6674502d41",
    "arista_eos: a wide list and then narrow ones, nothing declared": "72a1fa030835",
    "arista_eos: add that brings an id past the last": _TOO_HIGH,
    "arista_eos: all, none and except": "b8edc291a0d7",
    "arista_eos: an access VLAN nobody declared beside a wide list": "8e21f67dfff4",
    "arista_eos: every way of writing a list, on one switch": "c748cd23554e",
    "arista_eos: narrow lists and then a wide one, nothing declared": "ba972aae1a75",
    "arista_eos: one range twice": "870f7ab849bc",
    "arista_eos: two trunks of 2-4000, nothing declared": "95276150441a",
    "arista_eos: zero and then a wide list": _TOO_LOW,
    "aruba_aoscx: 128 ids": "fedb1a6797ee",
    "aruba_aoscx: 129 ids": "8ff40fd096a0",
    "aruba_aoscx: VLAN 1 declared under every id but 1": "25cf9123979c",
    "aruba_aoscx: a narrow list that is an id past the last": _TOO_HIGH,
    "aruba_aoscx: a wide list after a port that is fine": _TOO_HIGH,
    "aruba_aoscx: a wide list and 4095": _TOO_HIGH,
    "aruba_aoscx: a wide list and a declared native VLAN inside it": "15fbc947bafd",
    "aruba_aoscx: a wide list and a native VLAN nobody declared": "f65d970a7b27",
    "aruba_aoscx: a wide list and a number of 23 digits": _TOO_HIGH,
    "aruba_aoscx: a wide list and an id past the last": _TOO_HIGH,
    "aruba_aoscx: a wide list and an undeclared native VLAN inside it": "a115a442ae2a",
    "aruba_aoscx: a wide list and then narrow ones, nothing declared": "91d23ba28359",
    "aruba_aoscx: an access VLAN nobody declared beside a wide list": "e26b5041c061",
    "aruba_aoscx: every way of writing a list, on one switch": "7fc0cd8dffe9",
    "aruba_aoscx: narrow lists and then a wide one, nothing declared": "ccdeb7c8f1c9",
    "aruba_aoscx: one range twice": "3ea30c295a65",
    "aruba_aoscx: two trunks of 2-4000, nothing declared": "a0914c53fca5",
    "aruba_aoscx: zero and then a wide list": _TOO_LOW,
    "cisco_iosxe_cli: 128 ids": "c3b346a588ce",
    "cisco_iosxe_cli: 129 ids": "cfa411d31c5c",
    "cisco_iosxe_cli: VLAN 1 declared under every id but 1": "96af86704781",
    "cisco_iosxe_cli: a list cut with remove": "85df43fa2b46",
    "cisco_iosxe_cli: a list that goes on with add": "650217b3e3e6",
    "cisco_iosxe_cli: a narrow list that is an id past the last": _TOO_HIGH,
    "cisco_iosxe_cli: a wide list after a port that is fine": _TOO_HIGH,
    "cisco_iosxe_cli: a wide list and 4095": _TOO_HIGH,
    "cisco_iosxe_cli: a wide list and a declared native VLAN inside it": "a8015c1f37d9",
    "cisco_iosxe_cli: a wide list and a native VLAN nobody declared": "d43ddd1addf7",
    "cisco_iosxe_cli: a wide list and a number of 23 digits": _TOO_HIGH,
    "cisco_iosxe_cli: a wide list and an id past the last": _TOO_HIGH,
    "cisco_iosxe_cli: a wide list and an undeclared native VLAN inside it": "53e1daa17ffe",
    "cisco_iosxe_cli: a wide list and then narrow ones, nothing declared": "0c0137371015",
    "cisco_iosxe_cli: add that brings an id past the last": _TOO_HIGH,
    "cisco_iosxe_cli: all, none and except": "4cbe41d72760",
    "cisco_iosxe_cli: an access VLAN nobody declared beside a wide list": "4976d4a992e4",
    "cisco_iosxe_cli: every way of writing a list, on one switch": "bcef6218de63",
    "cisco_iosxe_cli: narrow lists and then a wide one, nothing declared": "68952f454893",
    "cisco_iosxe_cli: one range twice": "10711d3b14d2",
    "cisco_iosxe_cli: two trunks of 2-4000, nothing declared": "c8d9c8e86a78",
    "cisco_iosxe_cli: zero and then a wide list": _TOO_LOW,
    "cisco_nxos: 128 ids": "613589687578",
    "cisco_nxos: 129 ids": "5f402bb3bcb8",
    "cisco_nxos: VLAN 1 declared under every id but 1": "dea7856b584e",
    "cisco_nxos: a list cut with remove": "cc24da4397f3",
    "cisco_nxos: a list that goes on with add": "1d74e69a4bb9",
    "cisco_nxos: a narrow list that is an id past the last": _TOO_HIGH,
    "cisco_nxos: a wide list after a port that is fine": _TOO_HIGH,
    "cisco_nxos: a wide list and 4095": _TOO_HIGH,
    "cisco_nxos: a wide list and a declared native VLAN inside it": "334c03d2ce8f",
    "cisco_nxos: a wide list and a native VLAN nobody declared": "e623f701474f",
    "cisco_nxos: a wide list and a number of 23 digits": _TOO_HIGH,
    "cisco_nxos: a wide list and an id past the last": _TOO_HIGH,
    "cisco_nxos: a wide list and an undeclared native VLAN inside it": "53695a139d0d",
    "cisco_nxos: a wide list and then narrow ones, nothing declared": "efa2bdc8c72b",
    "cisco_nxos: add that brings an id past the last": _TOO_HIGH,
    "cisco_nxos: all, none and except": "61c3fe6a5292",
    "cisco_nxos: an access VLAN nobody declared beside a wide list": "61d79337a951",
    "cisco_nxos: every VLAN declared in one line": "009a3b813c31",
    "cisco_nxos: every way of writing a list, on one switch": "7454ebbca130",
    "cisco_nxos: narrow lists and then a wide one, nothing declared": "0863a603ad11",
    "cisco_nxos: one range twice": "0ef9fe5ea6fe",
    "cisco_nxos: two trunks of 2-4000, nothing declared": "fc265cc28dd9",
    "cisco_nxos: zero and then a wide list": _TOO_LOW,
    "dell_os10: 128 ids": "76796bd8a3ae",
    "dell_os10: 129 ids": "5aed0292f480",
    "dell_os10: VLAN 1 declared under every id but 1": "a5df166bf196",
    "dell_os10: a list cut with remove": "bece7d1f0d3a",
    "dell_os10: a list that goes on with add": "2a2a3702fd90",
    "dell_os10: a narrow list that is an id past the last": _TOO_HIGH,
    "dell_os10: a wide list after a port that is fine": _TOO_HIGH,
    "dell_os10: a wide list and 4095": _TOO_HIGH,
    "dell_os10: a wide list and a declared native VLAN inside it": "2b6b73ba0597",
    "dell_os10: a wide list and a native VLAN nobody declared": "d85e3d655aec",
    "dell_os10: a wide list and a number of 23 digits": _TOO_HIGH,
    "dell_os10: a wide list and an id past the last": _TOO_HIGH,
    "dell_os10: a wide list and an undeclared native VLAN inside it": "a5df138c8935",
    "dell_os10: a wide list and then narrow ones, nothing declared": "c8285343d3eb",
    "dell_os10: add that brings an id past the last": _TOO_HIGH,
    "dell_os10: all, none and except": "0a670a4988a5",
    "dell_os10: an access VLAN nobody declared beside a wide list": "cf15e629faeb",
    "dell_os10: every way of writing a list, on one switch": "3156d975a18e",
    "dell_os10: narrow lists and then a wide one, nothing declared": "4e6fe2869f7a",
    "dell_os10: one range twice": "f4a5c1d35a9c",
    "dell_os10: two trunks of 2-4000, nothing declared": "3c947f43b9f1",
    "dell_os10: zero and then a wide list": _TOO_LOW,
    "juniper_junos: 128 ids": "9dd34d5ff134",
    "juniper_junos: 129 ids": "26c26958a1f0",
    "juniper_junos: VLAN 1 declared under every id but 1": "c4dbaae61a4c",
    "juniper_junos: a narrow list that is an id past the last": "7edd23f93c1b",
    "juniper_junos: a wide list after a port that is fine": "583010b8e29f",
    "juniper_junos: a wide list and 4095": "9c653e656ffa",
    "juniper_junos: a wide list and a declared native VLAN inside it": "5ca0f6bc26a6",
    "juniper_junos: a wide list and a native VLAN nobody declared": "ecd49be1199f",
    "juniper_junos: a wide list and a number of 23 digits": "df365b67089e",
    "juniper_junos: a wide list and an id past the last": "9c653e656ffa",
    "juniper_junos: a wide list and an undeclared native VLAN inside it": "188d898b14ee",
    "juniper_junos: a wide list and then narrow ones, nothing declared": "4a6e7601f14b",
    "juniper_junos: an access VLAN nobody declared beside a wide list": "e8aab2c6e265",
    "juniper_junos: every way of writing a list, on one switch": "985d9440ef07",
    "juniper_junos: members by name beside a wide range": "951656277886",
    "juniper_junos: narrow lists and then a wide one, nothing declared": "7b87835d9035",
    "juniper_junos: one range twice": "5f66a1cef95d",
    "juniper_junos: two trunks of 2-4000, nothing declared": "5a75958c2db9",
    "juniper_junos: zero and then a wide list": "df365b67089e",
}


class TestTheSameReadingOfAText:
    def test_every_text_has_what_it_came_to(self) -> None:
        assert set(BEFORE) == set(TEXTS)

    @pytest.mark.parametrize("title", sorted(TEXTS))
    def test_it_comes_to_what_it_did(self, title: str) -> None:
        codec, text = TEXTS[title]
        assert _came_to(codec, text) == BEFORE[title], title

    def test_the_texts_reach_both_outcomes(self) -> None:
        """Some fail and some parse, on each codec whose list can hold
        an id that is not a VLAN id (Junos drops one as it reads)."""
        for codec in WRITTEN_BY:
            mine = [value for title, value in BEFORE.items() if title.startswith(codec + ":")]
            assert any(not value.startswith("fails: ") for value in mine), codec
            if codec != "juniper_junos":
                assert _TOO_HIGH in mine and _TOO_LOW in mine, codec

    def test_one_reading_in_full(self) -> None:
        """One reading in full, beside the digests."""
        tree = get_codec("cisco_iosxe_cli").parse(_iosxe([10, 20, 3000], [_trunk("1-99,101-4094", native=20)]))
        port = "GigabitEthernet1/0/1"
        assert [(vlan.id, vlan.tagged_ports, vlan.untagged_ports) for vlan in tree.vlans] == [
            (10, [port], []), (20, [], [port]), (3000, [port], []),
        ]

    def test_a_native_vlan_left_out_in_full(self) -> None:
        """And one of the seven readings that changed, in full: the
        native VLAN has its record, and the trunk is no member of it.
        On OS10 the same two lines put the VLAN in the trunk's list,
        and the port is untagged in it."""
        tree = get_codec("cisco_iosxe_cli").parse(_iosxe([10, 20], [_trunk("1-500", native=999)]))
        port = "GigabitEthernet1/0/1"
        assert [(vlan.id, vlan.tagged_ports, vlan.untagged_ports) for vlan in tree.vlans] == [
            (10, [port], []), (20, [port], []), (999, [], []),
        ]
        assert tree.interfaces[0].trunk_native_vlan == 999 and 999 not in tree.interfaces[0].trunk_allowed_vlans
        tree = get_codec("dell_os10").parse(_os10([10, 20], [_trunk("1-500", native=999)]))
        assert [vlan.untagged_ports for vlan in tree.vlans if vlan.id == 999] == [["ethernet1/1/1"]]
        trunk = next(iface for iface in tree.interfaces if iface.name == "ethernet1/1/1")
        assert trunk.trunk_native_vlan == 999 and trunk.trunk_allowed_vlans == [*range(1, 501), 999]


class TestADefaultNativeVlan:
    """A trunk that states no native VLAN, on a platform whose trunk
    then has native VLAN 1: the readings that changed, in full."""

    def test_a_wide_list_makes_vlan_one_and_no_other(self) -> None:
        """``1-129`` is too wide to declare its VLANs, and still does
        not: the one record it makes is VLAN 1, which the trunk
        carries untagged by default.  A list as wide that leaves
        VLAN 1 out makes none."""
        port = "GigabitEthernet1/0/1"
        tree = get_codec("cisco_iosxe_cli").parse(_iosxe([5], [_trunk("1-129")]))
        assert [(vlan.id, vlan.name, vlan.tagged_ports, vlan.untagged_ports) for vlan in tree.vlans] == [
            (5, "V5", [port], []), (1, "", [], [port]),
        ]
        assert tree.interfaces[0].trunk_native_vlan == 1
        tree = get_codec("cisco_iosxe_cli").parse(_iosxe([5], [_trunk("2-130")]))
        assert [(vlan.id, vlan.tagged_ports, vlan.untagged_ports) for vlan in tree.vlans] == [(5, [port], [])]
        assert tree.interfaces[0].trunk_native_vlan is None

    def test_a_declared_vlan_one_changes_hands(self) -> None:
        """VLAN 1 declared, a trunk of ``2-4094`` and a trunk of every
        id: the second is an untagged member of VLAN 1, where it was a
        tagged one, and the first is no member of it."""
        tree = get_codec("cisco_nxos").parse(_nxos([1, 10], [_trunk("2-4094"), _trunk("1-4094")]))
        assert [(vlan.id, vlan.tagged_ports, vlan.untagged_ports) for vlan in tree.vlans] == [
            (1, [], ["Ethernet1/2"]), (10, ["Ethernet1/1", "Ethernet1/2"], []),
        ]
        assert [port.trunk_native_vlan for port in tree.interfaces] == [None, 1]

    @pytest.mark.parametrize("codec", ["dell_os10", "juniper_junos"])
    def test_where_there_is_no_default_nothing_moves(self, codec: str) -> None:
        """An OS10 trunk's default VLAN is its switch's, which no trunk
        states, and a Junos trunk has none: neither parser fills one
        in, for any list."""
        for title, (source, text) in TEXTS.items():
            if source != codec or BEFORE[title].startswith("fails: "):
                continue
            tree = get_codec(codec).parse(text)
            stated = "native" in text or "access vlan" in text
            if not stated:
                assert not [port.name for port in tree.interfaces if port.trunk_native_vlan is not None], title


# ---------------------------------------------------------------------------
# What an entry costs
# ---------------------------------------------------------------------------


def _peak(work: Callable[[], object]) -> int:
    """The most memory *work* held at once beyond what was held when
    it began, in bytes -- whether or not the interpreter was already
    tracing (``-X tracemalloc``)."""
    already = tracemalloc.is_tracing()
    if not already:
        tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        before = tracemalloc.get_traced_memory()[0]
        work()
        return tracemalloc.get_traced_memory()[1] - before
    finally:
        if not already:
            tracemalloc.stop()


#: Trunks in the texts below, and the VLANs they declare.
_TRUNKS = 48
_DECLARED = list(range(10, 20))

#: Bytes a port-side id may cost while a config is parsed.  A place in
#: a list is 8, and the parse holds a list and its copy for a moment;
#: an int of its own for every id was 38 with nothing else counted,
#: and a VLAN record and a stamp for every id were over 900.
_BYTES_AN_ID = 28

#: Bytes a membership may cost while it is stamped: its place in the
#: VLAN's list and in the index of that list.  A queue for every stamp
#: was some 800.
_BYTES_A_MEMBERSHIP = 200


class TestWhatAnEntryCosts:
    @pytest.mark.parametrize("allowed", ["2-4000", "1-99,101-4094", "100-3000", "1-4093"])
    @pytest.mark.parametrize("codec", sorted(WRITTEN_BY))
    def test_what_a_port_side_id_costs(self, codec: str, allowed: str) -> None:
        """48 trunks that each allow thousands of VLANs, ten declared:
        five kilobytes of text."""
        write, parse = WRITTEN_BY[codec], get_codec(codec).parse
        text = write(_DECLARED, [_trunk(allowed)] * _TRUNKS)
        parse(write(_DECLARED, [_trunk("10-12")] * 2))  # imports and compiled patterns are not the config's
        tree = parse(text)
        ids = sum(len(port.trunk_allowed_vlans) for port in tree.interfaces)
        assert ids >= _TRUNKS * 2900, "the text was not read as wide lists"
        peak = _peak(lambda: parse(text))
        assert peak < ids * _BYTES_AN_ID, (
            f"{codec}: {allowed!r} on {_TRUNKS} ports is {ids:,} ids and held {peak:,} bytes "
            f"({peak / ids:.0f} an id; the ceiling is {_BYTES_AN_ID})"
        )

    def test_what_a_membership_costs(self) -> None:
        """200 trunks of every id on 200 declared VLANs: 40,000
        memberships, each of them real.  The ports share one list of
        ids here, so that the projection alone is what is counted."""
        every = list(range(1, 4095))
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(id=vid) for vid in range(2, 202)],
            interfaces=[
                CanonicalInterface(name=f"Ethernet1/{port}", switchport_mode="trunk") for port in range(1, 201)
            ],
        )
        for port in tree.interfaces:
            port.trunk_allowed_vlans = every
        peak = _peak(lambda: project_switchport_to_vlan(tree, keep={vlan.id for vlan in tree.vlans}))
        made = sum(len(vlan.tagged_ports) for vlan in tree.vlans)
        assert made == 40_000
        assert peak < made * _BYTES_A_MEMBERSHIP, (
            f"{made:,} memberships held {peak:,} bytes ({peak / made:.0f} each; the ceiling is {_BYTES_A_MEMBERSHIP})"
        )

    def test_the_count_can_fail(self) -> None:
        """The same count, on work that makes an int and a queue for
        every entry, is over both ceilings."""
        from collections import deque

        ints = _peak(lambda: [list(range(300, 4000)) for _ in range(20)])
        assert ints > 20 * 3700 * _BYTES_AN_ID
        queues = _peak(lambda: [deque([entry]) for entry in range(4000)])
        assert queues > 4000 * _BYTES_A_MEMBERSHIP


# ---------------------------------------------------------------------------
# A trunk that states no list
# ---------------------------------------------------------------------------

#: The four codecs whose trunk carries every VLAN when it states no
#: allowed list, and such a trunk as each one's text has it.  (On
#: AOS-CX it is a native line with no allowed line beside it.)
NO_LIST_IS_EVERY_VLAN: dict[str, _Port] = {
    "arista_eos": _trunk(), "aruba_aoscx": _trunk(native=1), "cisco_iosxe_cli": _trunk(), "cisco_nxos": _trunk(),
}

#: Bytes a trunk of every VLAN may cost in the tree that is KEPT: 12
#: for each of its 4,094 ids.  The place of an id in the list is 8 and
#: the ids are the shared ints, so a trunk is some 35,000 bytes with
#: its record; with an int of its own for every id it is over 160,000.
_BYTES_A_TRUNK_OF_EVERY_VLAN = 4094 * 12


def _held(work: Callable[[], object]) -> tuple[object, int]:
    """What *work* returns, and the bytes still held for it once it
    has returned -- whether or not the interpreter was already tracing
    (``-X tracemalloc``)."""
    gc.collect()
    already = tracemalloc.is_tracing()
    if not already:
        tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        made = work()
        gc.collect()
        return made, tracemalloc.get_traced_memory()[0] - before
    finally:
        if not already:
            tracemalloc.stop()


class TestATrunkThatStatesNoList:
    """On four platforms a trunk with no allowed line carries every
    VLAN, and its list says so: 4,094 ids for a line that is not in
    the text.  A config can have such a trunk on every port.  What
    that costs is counted here in bytes, as the rest of this module
    counts: it is affordable only while an id in a list is its place
    there and nothing more."""

    @pytest.mark.parametrize("codec", sorted(NO_LIST_IS_EVERY_VLAN))
    def test_every_id_and_on_each_declared_vlan(self, codec: str) -> None:
        tree = get_codec(codec).parse(WRITTEN_BY[codec](_DECLARED, [NO_LIST_IS_EVERY_VLAN[codec], ("access", 12)]))
        trunk, access = tree.interfaces
        assert (trunk.switchport_mode, access.switchport_mode) == ("trunk", "access")
        assert trunk.trunk_allowed_vlans == list(range(1, 4095)) and _shared(trunk.trunk_allowed_vlans)
        assert access.trunk_allowed_vlans == []
        tagged = {vlan.id for vlan in tree.vlans if trunk.name in vlan.tagged_ports}
        assert tagged == set(_DECLARED), "on each VLAN the config declares, and on no other"

    @pytest.mark.parametrize("codec", ["dell_os10", "juniper_junos"])
    def test_on_the_other_two_it_is_no_vlan(self, codec: str) -> None:
        tree = get_codec(codec).parse(WRITTEN_BY[codec](_DECLARED, [_trunk()]))
        (trunk,) = (port for port in tree.interfaces if port.switchport_mode == "trunk")
        assert trunk.trunk_allowed_vlans == []
        assert not [vlan.id for vlan in tree.vlans if trunk.name in vlan.tagged_ports]

    @pytest.mark.parametrize("codec", sorted(NO_LIST_IS_EVERY_VLAN))
    def test_what_one_costs_in_the_tree(self, codec: str) -> None:
        """48 trunks that state no list, ten VLANs declared: some
        three kilobytes of text."""
        write, parse = WRITTEN_BY[codec], get_codec(codec).parse
        text = write(_DECLARED, [NO_LIST_IS_EVERY_VLAN[codec]] * _TRUNKS)
        parse(write(_DECLARED, [_trunk("10-12")] * 2))  # imports and compiled patterns are not the config's
        tree, held = _held(lambda: parse(text))
        trunks = [port for port in tree.interfaces if port.switchport_mode == "trunk"]
        assert len(trunks) == _TRUNKS and all(len(port.trunk_allowed_vlans) == 4094 for port in trunks)
        assert held < _TRUNKS * _BYTES_A_TRUNK_OF_EVERY_VLAN, (
            f"{codec}: {_TRUNKS} trunks that state no list are held in {held:,} bytes "
            f"({held // _TRUNKS:,} a trunk; the ceiling is {_BYTES_A_TRUNK_OF_EVERY_VLAN:,})"
        )

    @pytest.mark.parametrize("codec", sorted(NO_LIST_IS_EVERY_VLAN))
    def test_each_trunk_has_a_list_of_its_own(self, codec: str) -> None:
        """The ints are shared; the lists are not.  A pass that edits
        one trunk's list must not edit the next trunk's."""
        tree = get_codec(codec).parse(WRITTEN_BY[codec](_DECLARED, [NO_LIST_IS_EVERY_VLAN[codec]] * 2))
        first, second = (port.trunk_allowed_vlans for port in tree.interfaces)
        assert first == second and first is not second
        first.remove(100)
        assert len(second) == 4094

    def test_the_count_can_fail(self) -> None:
        """The same count, on as many lists whose ids are ints of
        their own, is over the ceiling."""
        made, held = _held(lambda: [list(range(300 + at, 4394 + at)) for at in range(_TRUNKS)])
        assert len(made) == _TRUNKS
        assert held > _TRUNKS * _BYTES_A_TRUNK_OF_EVERY_VLAN


# ---------------------------------------------------------------------------
# The shared ids
# ---------------------------------------------------------------------------


def _shared(ids: list[int]) -> bool:
    return all(vid is VLAN_IDS[vid] for vid in ids)


class TestTwoRecordsOfOneName:
    """A parser may make two records for one interface name (IOS-XE
    reads a stanza met twice as two).  The projection keeps what it
    knows of an interface by the record, not by the name: by name,
    the second record's list took the place of the first's and the
    first VLAN lost its port."""

    def test_each_records_list_is_its_own(self) -> None:
        text = "\n".join([
            "hostname sw1", "!", "vlan 10", "!", "vlan 20", "!",
            "interface GigabitEthernet1/0/1", " switchport mode trunk",
            " switchport trunk allowed vlan 10", "!",
            "interface GigabitEthernet1/0/1", " switchport mode trunk",
            " switchport trunk allowed vlan 20", "!", "end", "",
        ])
        tree = get_codec("cisco_iosxe_cli").parse(text)
        tagged = {vlan.id: vlan.tagged_ports for vlan in tree.vlans}
        assert tagged == {10: ["GigabitEthernet1/0/1"], 20: ["GigabitEthernet1/0/1"]}

    def test_two_records_built_by_hand(self) -> None:
        intent = CanonicalIntent(
            vlans=[CanonicalVlan(id=10), CanonicalVlan(id=20)],
            interfaces=[
                CanonicalInterface(name="Gi1", switchport_mode="trunk", trunk_allowed_vlans=[10]),
                CanonicalInterface(name="Gi1", switchport_mode="trunk", trunk_allowed_vlans=[20]),
            ],
        )
        project_switchport_to_vlan(intent, keep={10, 20})
        assert {vlan.id: vlan.tagged_ports for vlan in intent.vlans} == {10: ["Gi1"], 20: ["Gi1"]}


class TestTheSharedIds:
    def test_the_int_at_an_index_is_the_index(self) -> None:
        assert list(VLAN_IDS) == list(range(4095)) and type(VLAN_IDS) is tuple

    @pytest.mark.parametrize(("low", "high"), [(1, 4094), (2, 4000), (1, 1), (4094, 4094), (300, 302), (257, 258)])
    def test_a_run_is_the_range_it_stands_for(self, low: int, high: int) -> None:
        run = vlan_id_run(low, high)
        assert run == list(range(low, high + 1)) and type(run) is list and _shared(run)

    def test_a_run_is_a_list_of_its_own(self) -> None:
        first, second = vlan_id_run(1, 10), vlan_id_run(1, 10)
        first.append(99)
        assert second == list(range(1, 11)) and VLAN_IDS[1:11] == tuple(range(1, 11))

    def test_every_expander_gives_shared_ints(self) -> None:
        for expanded, wanted in (
            (_parse_vlan_list("2-4000"), list(range(2, 4001))),
            (_parse_vlan_list("300-302,10,5-7"), [300, 301, 302, 10, 5, 6, 7]),
            (_parse_vlan_list("0-9999"), list(range(1, 4095))),
            (_expand_vlan_list("2-4000"), list(range(2, 4001))),
            (_expand_vlan_list("4000-4094,1-50"), [*range(4000, 4095), *range(1, 51)]),
            (merge_trunk_allowed([], "all"), list(range(1, 4095))),
            (merge_trunk_allowed([], "except 100,300-310"), [*range(1, 100), *range(101, 300), *range(311, 4095)]),
            (merge_trunk_allowed(_parse_vlan_list("1-500"), "add 400-900"), list(range(1, 901))),
            (merge_trunk_allowed(_parse_vlan_list("1-900"), "remove 20-30"), [*range(1, 20), *range(31, 901)]),
            (_resolve_vlan_member_to_vids("100-3000", {}), list(range(100, 3001))),
        ):
            assert expanded == wanted
            assert _shared([vid for vid in expanded if vid > 256]), "ints of its own"

    @pytest.mark.parametrize("codec", sorted(WRITTEN_BY))
    def test_a_parsed_tree_holds_shared_ints(self, codec: str) -> None:
        """Through the handler, the model and the projection: what a
        port's list holds at the end is still the one object an id."""
        tree = get_codec(codec).parse(WRITTEN_BY[codec](_DECLARED, [_trunk("2-4000"), _trunk("1-4094")]))
        wide, every = (port.trunk_allowed_vlans for port in tree.interfaces if port.switchport_mode == "trunk")
        assert wide == list(range(2, 4001)) and _shared(wide)
        assert every == list(range(1, 4095)) and _shared(every)

    def test_junos_members_all_is_shared_ints(self) -> None:
        tree = get_codec("juniper_junos").parse(_junos(_DECLARED, [_trunk("all")]))
        (trunk,) = tree.interfaces
        assert trunk.trunk_allowed_vlans == list(range(1, 4095)) and _shared(trunk.trunk_allowed_vlans)
