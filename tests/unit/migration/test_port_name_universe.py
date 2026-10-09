"""Does a renamed port take everything with it?

The port translator rewrites port names in a list of places, and the
check that model-to-model mapping makes on a finished run reads names
from a list of places.  Both lists were written by reading the
canonical tree.  Three times in one change a place was missing from
them, and each time a port moved while something that named it stayed
behind -- the last being RouterOS's factory name, which the renderer
uses to find the port on the device: every moved port came out as
"find the port with the OLD name and call it the new one", in a job
that reported success.

A test that lists the places cannot find a place nobody listed.  This
one lists none.  It exchanges two port names through the real
translator and the real renderer and compares what comes out:

    the output of the swapped run, parsed again
        must equal
    the output of the unswapped run, parsed again, with the two names
    exchanged in every text value it holds.

A value that did not follow is a place the translator does not reach
-- whatever field it lives in, on whichever codec, including a field
added after this was written.  Both sides go through the same render
and the same parse, so anything a codec loses or normalises on a round
trip cancels out.

It runs over every committed real capture of every codec, and over a
few small configs for shapes no capture has (a next hop that is an
interface; a port an operator renamed).
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.canonical.port_names import (
    collect_hardware_port_names,
    collect_port_names,
    translate_port_names,
)
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.services.migration_pipeline import run_plan_with_overrides

pytestmark = pytest.mark.unit

REAL = Path(__file__).resolve().parents[2] / "fixtures" / "real"

#: Capture directory under ``tests/fixtures/real`` to the codec that
#: reads it: the repository's one table of that, shared with the
#: real-capture test and the cross-mesh tools, so a new directory is
#: exercised here as soon as it is mapped there.
FIXTURE_DIR_CODEC = DIR_TO_CODEC_NAME
#: The native capture extensions (the same filter the real-capture
#: test and the mesh tool use).
_CAPTURE_SUFFIXES = {".txt", ".cfg", ".xml", ".conf", ".rsc", ".set"}

#: Keys that identify one record of a list, tried in this order, so a
#: record is compared with the SAME record on the other side and not
#: with whichever one sits at the same index.
_RECORD_KEYS = ("name", "id", "destination", "network", "username")


def _capture_files() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for directory in sorted(REAL.iterdir()):
        codec = FIXTURE_DIR_CODEC.get(directory.name)
        if codec is None or not directory.is_dir():
            continue
        found.extend(
            (codec, path) for path in sorted(directory.iterdir())
            if path.is_file() and path.suffix.lower() in _CAPTURE_SUFFIXES
        )
    return found


CAPTURES = _capture_files()


# ---------------------------------------------------------------------------
# The oracle: exchange two names in a parsed tree, with no list of fields
# ---------------------------------------------------------------------------


def _swap_text(value: str, a: str, b: str) -> str:
    """*value* with the port names *a* and *b* exchanged, when it IS
    one of them -- or one of them with a numeric unit (``ge-0/0/1.0``).
    Free text that merely mentions a port is left alone, as the
    translator must leave it."""
    for old, new in ((a, b), (b, a)):
        if value == old:
            return new
        if value.startswith(old + ".") and value[len(old) + 1:].isdigit():
            return new + value[len(old):]
    return value


def _swap_tree(node: Any, a: str, b: str) -> Any:
    if isinstance(node, str):
        return _swap_text(node, a, b)
    if isinstance(node, dict):
        return {
            (_swap_text(key, a, b) if isinstance(key, str) else key): _swap_tree(value, a, b)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_swap_tree(value, a, b) for value in node]
    return node


def _flatten(node: Any, path: tuple[str, ...] = (), out: dict | None = None) -> dict:
    """Every leaf of *node* by its path.  A list of records is keyed by
    what identifies each record; a list of plain values is compared as
    a whole, without regard to order (a renderer may sort a port list)."""
    out = {} if out is None else out
    if isinstance(node, dict):
        for key in sorted(node, key=str):
            _flatten(node[key], (*path, str(key)), out)
    elif isinstance(node, list):
        if node and all(isinstance(item, dict) for item in node):
            seen: dict[str, int] = defaultdict(int)
            for index, item in enumerate(node):
                ident = next(
                    (str(item[key]) for key in _RECORD_KEYS if item.get(key) not in (None, "")),
                    f"#{index}",
                )
                seen[ident] += 1
                again = f"~{seen[ident]}" if seen[ident] > 1 else ""
                _flatten(item, (*path, f"[{ident}]{again}"), out)
        else:
            out[path] = tuple(sorted(map(repr, node)))
    else:
        out[path] = node
    return out


def _differences(expected: Any, actual: Any) -> list[str]:
    left, right = _flatten(expected), _flatten(actual)
    absent = "<absent>"
    return [
        f"{'.'.join(path)}: expected {left.get(path, absent)!r}, got {right.get(path, absent)!r}"
        for path in sorted(set(left) | set(right))
        if left.get(path, absent) != right.get(path, absent)
    ]


def _kind(codec: Any, name: str) -> str:
    try:
        identity = codec.classify_port_name(name)
    except Exception:
        return "unknown"
    return identity.kind if identity is not None else "unknown"


def _pairs_to_swap(codec: Any, tree: CanonicalIntent) -> list[tuple[str, str]]:
    """Up to three pairs of physical ports of one name shape.

    A port that has sub-interfaces in the tree is left out: without
    declared devices a unit is translated by the shape of its own
    name, apart from its port (a documented limit of that path; with
    devices declared it follows its port, which
    ``test_run_plan_with_models.py`` pins).
    """
    every = collect_port_names(tree)
    with_units = {
        name.rpartition(".")[0] for name in every
        if name.rpartition(".")[2].isdigit() and name.rpartition(".")[0]
    }
    shapes: dict[str, list[str]] = defaultdict(list)
    for name in collect_hardware_port_names(tree, classify=codec.classify_port_name):
        if name not in with_units and _kind(codec, name) in ("physical", "breakout"):
            shapes[re.sub(r"\d+", "#", name)].append(name)
    return [(names[0], names[-1]) for names in shapes.values() if len(names) >= 2][:3]


def _what_did_not_follow(codec: Any, text: str, a: str, b: str) -> list[str]:
    """Run *text* through the translator twice -- every hardware port
    pinned to its own name, then with *a* and *b* exchanged -- and
    return the values of the second output that are not the first
    output's with the two names exchanged."""
    tree = codec.parse(text)
    pin = {
        name: name
        for name in collect_hardware_port_names(tree, classify=codec.classify_port_name)
    }
    base = run_plan_with_overrides(codec, codec, text, port_rename_map=pin)
    swapped = run_plan_with_overrides(
        codec, codec, text, port_rename_map={**pin, a: b, b: a},
    )
    assert base.rendered and swapped.rendered, (base.error, swapped.error)
    expected = _swap_tree(codec.parse(base.rendered).model_dump(), a, b)
    return _differences(expected, codec.parse(swapped.rendered).model_dump())


def _parse(codec_name: str, path: Path) -> tuple[Any, str, CanonicalIntent | None]:
    codec = get_codec(codec_name)
    text = path.read_text(encoding="utf-8")
    try:
        tree = codec.parse(text)
    except Exception:
        return codec, text, None
    return codec, text, tree if isinstance(tree, CanonicalIntent) else None


def _comparable(codec_name: str, path: Path) -> tuple[Any, str, list[tuple[str, str]]]:
    codec, text, tree = _parse(codec_name, path)
    if tree is None:
        return codec, text, []
    # A rename clears verbatim Junos apply-group bodies, by design: the
    # swapped run would differ from the unswapped one for that reason.
    if tree.group_content or tree.apply_groups:
        return codec, text, []
    return codec, text, _pairs_to_swap(codec, tree)


# ---------------------------------------------------------------------------
# Every codec, every capture
# ---------------------------------------------------------------------------


class TestEveryCapture:
    def test_every_codec_with_captures_is_actually_exercised(self) -> None:
        """A capture with fewer than two ports of one shape is skipped
        below.  No codec may be skipped altogether: that would be the
        test passing by not running."""
        exercised = {
            codec_name for codec_name, path in CAPTURES if _comparable(codec_name, path)[2]
        }
        assert exercised == set(FIXTURE_DIR_CODEC.values())

    @pytest.mark.parametrize(
        ("codec_name", "path"), CAPTURES,
        ids=[f"{path.parent.name}/{path.name}" for _, path in CAPTURES],
    )
    def test_a_renamed_port_takes_every_reference_with_it(
        self, codec_name: str, path: Path,
    ) -> None:
        codec, text, pairs = _comparable(codec_name, path)
        if not pairs:
            pytest.skip("no two physical ports of one name shape to exchange")
        for a, b in pairs:
            stayed = _what_did_not_follow(codec, text, a, b)
            assert not stayed, (
                f"exchanging {a} and {b}: {len(stayed)} value(s) of the output did "
                f"not follow the rename -- a place the translator does not reach:\n  "
                + "\n  ".join(stayed[:8])
            )


# ---------------------------------------------------------------------------
# Shapes no committed capture has
# ---------------------------------------------------------------------------

_ROUTEROS_NEXT_HOPS = """/interface ethernet
set [ find default-name=ether1 ] comment="wan"
set [ find default-name=ether2 ] comment="lan"
/ip address
add address=192.0.2.2/30 interface=ether1
add address=10.9.0.1/24 interface=ether2
/ip route
add dst-address=0.0.0.0/0 gateway=ether1
add dst-address=10.9.0.0/16 gateway=ether2
"""

_ROUTEROS_RENAMED_PORTS = """/interface ethernet
set [ find default-name=ether1 ] name=core-a comment="core A"
set [ find default-name=ether2 ] name=core-b comment="core B"
/ip address
add address=10.0.0.1/30 interface=core-a
add address=10.0.0.5/30 interface=core-b
"""

_JUNOS_NEXT_HOP = """set system host-name sw
set interfaces xe-0/0/1 unit 0 family inet address 10.0.0.1/30
set interfaces xe-0/0/2 unit 0 family inet address 10.1.0.1/24
set routing-options static route 0.0.0.0/0 next-hop xe-0/0/1.0
"""


class TestShapesNoCaptureHas:
    @pytest.mark.parametrize(
        ("codec_name", "text", "a", "b"),
        [
            ("mikrotik_routeros", _ROUTEROS_NEXT_HOPS, "ether1", "ether2"),
            ("juniper_junos", _JUNOS_NEXT_HOP, "xe-0/0/1", "xe-0/0/2"),
        ],
        ids=["routeros-gateway-is-an-interface", "junos-next-hop-is-a-unit"],
    )
    def test_a_next_hop_that_is_an_interface_follows_it(
        self, codec_name: str, text: str, a: str, b: str,
    ) -> None:
        assert _what_did_not_follow(get_codec(codec_name), text, a, b) == []

    def test_across_vendors_a_unit_next_hop_is_left_as_written(self) -> None:
        """``xe-0/0/1.0`` names unit 0 of a Junos port.  The suffix
        means that only on Junos, so onto another vendor the next hop
        is not rewritten into a name that vendor would read differently
        -- while a next hop that is exactly an interface name still
        follows it."""
        junos, eos = get_codec("juniper_junos"), get_codec("arista_eos")
        tree = junos.parse(_JUNOS_NEXT_HOP)
        translate_port_names(tree, junos, eos, rename_map={"xe-0/0/1": "Ethernet7"})
        assert [route.gateway for route in tree.static_routes] == ["xe-0/0/1.0"]
        tree = junos.parse(_JUNOS_NEXT_HOP)
        tree.static_routes[0].gateway = "xe-0/0/1"
        translate_port_names(tree, junos, eos, rename_map={"xe-0/0/1": "Ethernet7"})
        assert [route.gateway for route in tree.static_routes] == ["Ethernet7"]

    def test_the_oracle_can_fail(self) -> None:
        """The comparison itself, on a tree in which one value did not
        follow: it must say which."""
        before = {"interfaces": [{"name": "p1", "lookup": "p1"}, {"name": "p2", "lookup": "p2"}]}
        stale = {"interfaces": [{"name": "p2", "lookup": "p1"}, {"name": "p1", "lookup": "p2"}]}
        moved = {"interfaces": [{"name": "p2", "lookup": "p2"}, {"name": "p1", "lookup": "p1"}]}
        assert _differences(_swap_tree(before, "p1", "p2"), moved) == []
        stayed = _differences(_swap_tree(before, "p1", "p2"), stale)
        assert [line.split(":")[0] for line in stayed] == [
            "interfaces.[p1].lookup", "interfaces.[p2].lookup",
        ]

    def test_a_port_an_operator_renamed_moves_by_its_factory_name(self) -> None:
        """RouterOS: ``core-a`` is the operator's name for the port
        whose factory name is ``ether1``.  Exchanging the two FACTORY
        names moves the hardware under each alias; the aliases, and
        everything that refers to them, stay."""
        mikrotik = get_codec("mikrotik_routeros")
        tree = mikrotik.parse(_ROUTEROS_RENAMED_PORTS)
        assert collect_hardware_port_names(
            tree, classify=mikrotik.classify_port_name,
        ) == ["ether1", "ether2"]
        job = run_plan_with_overrides(
            mikrotik, mikrotik, _ROUTEROS_RENAMED_PORTS,
            port_rename_map={"ether1": "ether2", "ether2": "ether1"},
        )
        assert "set [ find default-name=ether2 ] name=core-a" in job.rendered
        assert "set [ find default-name=ether1 ] name=core-b" in job.rendered
        assert "add address=10.0.0.1/30 interface=core-a" in job.rendered
        assert job.port_renames == {"ether1": "ether2", "ether2": "ether1"}

    def test_a_port_that_still_has_its_factory_name_leaves_none_behind(self) -> None:
        """Renamed by the shape of its name, with no map entry at all
        (RouterOS onto another vendor): the tree must not go on holding
        the old name in the factory-name field, for whatever reads the
        tree next."""
        mikrotik, eos = get_codec("mikrotik_routeros"), get_codec("arista_eos")
        tree = mikrotik.parse(_ROUTEROS_NEXT_HOPS)
        translate_port_names(tree, mikrotik, eos, rename_map={})
        ports = [iface for iface in tree.interfaces if iface.default_name]
        assert ports and all(iface.default_name == iface.name for iface in ports)
        assert not [iface for iface in ports if iface.name.startswith("ether")]

    def test_a_port_dropped_by_its_factory_name_goes_under_its_alias(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_overrides(
            mikrotik, mikrotik, _ROUTEROS_RENAMED_PORTS, port_rename_map={"ether1": None},
        )
        assert job.port_drops == ["ether1"]
        assert "core-a" not in job.rendered and "10.0.0.1/30" not in job.rendered
        assert "set [ find default-name=ether2 ] name=core-b" in job.rendered


# ---------------------------------------------------------------------------
# The two lists agree with each other
# ---------------------------------------------------------------------------


def _a_name_in_every_place() -> CanonicalIntent:
    return CanonicalIntent.model_validate({
        "interfaces": [
            {"name": "if-a", "default_name": "if-a", "lag_member_of": "lag-a",
             "vrrp_groups": [{"group_id": 1, "track_interfaces": ["track-a"]}]},
            {"name": "alias-b", "default_name": "factory-b"},
        ],
        "vlans": [{"id": 2, "tagged_ports": ["tag-a"], "untagged_ports": ["untag-a"]}],
        "lags": [{"name": "lag-b", "members": ["member-a"]}],
        "static_routes": [{"destination": "0.0.0.0/0", "interface": "route-a"}],
        "dhcp_servers": [{"interface": "pool-a"}],
        "vxlan_vnis": [{"vni": 10, "vlan_id": 10, "source_interface": "vtep-a"}],
    })


class TestTheTwoListsAgree:
    def test_the_rename_pass_moves_every_name_the_collector_lists(self) -> None:
        """Give every name the collector returns a new name, and
        collect again: every one must have moved.  A place added to
        the collector and not to the rename pass -- or the other way
        round -- fails here."""
        codec = get_codec("aruba_aoss")
        tree = _a_name_in_every_place()
        before = collect_port_names(tree)
        assert len(before) == len(set(before)) == 12
        translate_port_names(
            tree, codec, codec, rename_map={name: f"x-{name}" for name in before},
        )
        assert sorted(collect_port_names(tree)) == sorted(f"x-{name}" for name in before)

    def test_a_dropped_name_is_gone_from_every_place(self) -> None:
        codec = get_codec("aruba_aoss")
        tree = _a_name_in_every_place()
        before = collect_port_names(tree)
        translate_port_names(tree, codec, codec, rename_map=dict.fromkeys(before))
        assert collect_port_names(tree) == []
