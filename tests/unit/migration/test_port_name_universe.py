"""Does a renamed port take everything with it?

The port translator rewrites port names in a list of places, and the
check that model-to-model mapping makes on a finished run reads names
from a list of places.  Both lists were written by reading the
canonical tree, and a place was missing from them more than once while
this feature was built: a port moved while something that named it
stayed behind, in a job that reported success.

A test that walks such a list cannot find a place nobody listed.  The
experiment here walks none.  It sends port names to one another
through the real translator and the real renderer, and compares what
comes out:

    the output of the moved run, parsed again
        must equal
    the output of the unmoved run, parsed again, with the same names
    sent to one another in every text value it holds.

**What it reaches, and what it does not.**  Said here once, and held
by tests below rather than by this paragraph:

* It reaches a field only where a committed capture puts one of the
  moved names in it AND the codec's own parser reads the field back
  from the codec's own rendering.  Both sides go through the same
  render and the same parse, so what a codec loses on a round trip
  cancels out -- and so does a name on a line its parser does not
  read.  ``TestWhatTheExperimentReaches`` breaks the translator at
  each place in turn and records which places the captures catch; the
  others are caught by a small config written for the purpose.
* It moves names the device already has, among ports of one name
  shape.  It cannot see what happens to a name that is NEW -- a port
  an operator calls ``WAN`` -- which is pinned by hand below.
* It runs between two configs of one codec.
* One public codec, ``cisco_iosxe`` (NETCONF / XML), has no committed
  captures and is in neither run.

**The one field that must NOT follow.**  RouterOS keeps a port's
factory name (``default_name``) beside the name an operator gives it.
Without devices declared, an entry of the rename map gives a port a
NAME: the factory name is which hardware it is, and stays
(``set [ find default-name=ether1 ] name=WAN``).  So the experiment
without devices requires that field to stand still, and the one with
devices declared -- where an entry whose target is a port of the
declared target MOVES the port -- requires it to follow.
"""

from __future__ import annotations

import re
import types
from collections import defaultdict
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

import pytest
from pydantic import BaseModel, create_model

from netcanon.migration.canonical import port_names
from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.canonical.port_names import (
    collect_hardware_port_names,
    collect_port_names,
    translate_port_names,
)
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.port_inventory import Inventory, PhysicalPort
from netcanon.services.migration_pipeline import (
    run_plan_with_models,
    run_plan_with_overrides,
)

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

#: The field that says which HARDWARE a port is, as opposed to what
#: the port is called.  See the module docstring.
_HARDWARE_IDENTITY = ("default_name",)


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


def _capture_id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


# ---------------------------------------------------------------------------
# The oracle: send names to one another in a parsed tree, with no list of fields
# ---------------------------------------------------------------------------


def _move_text(value: str, moves: dict[str, str]) -> str:
    """*value* as *moves* sends it, when it IS one of the moved names
    -- or one of them with a numeric unit (``ge-0/0/1.0``).  Free text
    that merely mentions a port is left alone, as the translator must
    leave it."""
    if value in moves:
        return moves[value]
    port, dot, unit = value.rpartition(".")
    if dot and unit.isdigit() and port in moves:
        return moves[port] + dot + unit
    return value


def _move_tree(node: Any, moves: dict[str, str], keep: tuple[str, ...] = ()) -> Any:
    """*node* with every text value sent where *moves* sends it,
    except under a key in *keep*."""
    if isinstance(node, str):
        return _move_text(node, moves)
    if isinstance(node, dict):
        return {
            (_move_text(key, moves) if isinstance(key, str) else key): (
                value if key in keep else _move_tree(value, moves, keep)
            )
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_move_tree(value, moves, keep) for value in node]
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


def _rotation(groups: dict[str, list[str]]) -> dict[str, str]:
    """Each name of a group sent to the next name of its group."""
    return {
        name: names[(index + 1) % len(names)]
        for names in groups.values() if len(names) >= 2
        for index, name in enumerate(names)
    }


def _ports_to_move(codec: Any, tree: CanonicalIntent) -> dict[str, str]:
    """Every physical port of each name shape, sent to the next port
    of its shape.

    A port that has sub-interfaces in the tree is left out: without
    declared devices a unit is translated by the shape of its own
    name, apart from its port (a documented limit of that path; with
    devices declared it follows its port, which
    ``test_run_plan_with_models.py`` pins).  So is a port an operator
    named (RouterOS), which the config does not call by its hardware
    name.
    """
    every = collect_port_names(tree)
    with_units = {
        name.rpartition(".")[0] for name in every
        if name.rpartition(".")[2].isdigit() and name.rpartition(".")[0]
    }
    named = {
        iface.name for iface in tree.interfaces
        if iface.default_name and iface.default_name != iface.name
    }
    groups: dict[str, list[str]] = defaultdict(list)
    for name in collect_hardware_port_names(tree, classify=codec.classify_port_name):
        if name in with_units or name in named:
            continue
        if _kind(codec, name) in ("physical", "breakout"):
            groups[re.sub(r"\d+", "#", name)].append(name)
    return _rotation(groups)


def _names_to_move(codec: Any, tree: CanonicalIntent) -> dict[str, str]:
    """:func:`_ports_to_move`, and every LAG name of each shape sent to
    the next LAG of its shape -- so the places that hold only a LAG's
    name are moved too."""
    groups: dict[str, list[str]] = defaultdict(list)
    for lag in tree.lags:
        if lag.name and _kind(codec, lag.name) == "lag":
            groups[re.sub(r"\d+", "#", lag.name)].append(lag.name)
    return {**_ports_to_move(codec, tree), **_rotation(groups)}


def _what_did_not_follow(codec: Any, text: str, moves: dict[str, str]) -> list[str]:
    """Run *text* through the translator twice, with no devices
    declared -- every hardware port pinned to its own name, then with
    *moves* -- and return the values of the second output that are not
    the first output's with the names moved.  A port's hardware
    identity must stand still (see the module docstring)."""
    tree = codec.parse(text)
    pin = {
        name: name
        for name in collect_hardware_port_names(tree, classify=codec.classify_port_name)
    }
    base = run_plan_with_overrides(codec, codec, text, port_rename_map=pin)
    moved = run_plan_with_overrides(codec, codec, text, port_rename_map={**pin, **moves})
    assert base.rendered and moved.rendered, (base.error, moved.error)
    expected = _move_tree(codec.parse(base.rendered).model_dump(), moves, keep=_HARDWARE_IDENTITY)
    return _differences(expected, codec.parse(moved.rendered).model_dump())


def _the_device_this_config_is_from(codec: Any, tree: CanonicalIntent) -> Inventory:
    """An inventory that lists exactly the hardware ports *tree* uses,
    each by its hardware name: enough to declare "this device, on both
    sides" for a config no device model describes."""
    factory = {
        iface.name: iface.default_name for iface in tree.interfaces if iface.default_name
    }
    names = dict.fromkeys(
        factory.get(name, name)
        for name in collect_hardware_port_names(tree, classify=codec.classify_port_name)
    )
    return Inventory(
        vendor=codec.name,
        ports=[
            PhysicalPort(name=name, role="access", ordinal=at)
            for at, name in enumerate(names, start=1)
        ],
    )


def _what_did_not_follow_with_devices(
    codec: Any, text: str, moves: dict[str, str],
) -> list[str] | None:
    """The same experiment with the device declared on both sides and
    *moves* as the operator's entries.  Every target is a port of the
    declared device, so each entry MOVES a port, and the hardware
    identity has to follow with everything else.  ``None`` when no
    pairing can be made for this config."""
    device = _the_device_this_config_is_from(codec, codec.parse(text))
    base = run_plan_with_models(codec, codec, text, device, device)
    plan = base.port_mapping_plan
    if base.rendered is None or plan is None or not plan.applied:
        return None
    moved = run_plan_with_models(codec, codec, text, device, device, port_rename_map=moves)
    assert moved.rendered, moved.error
    expected = _move_tree(codec.parse(base.rendered).model_dump(), moves)
    return _differences(expected, codec.parse(moved.rendered).model_dump())


_PARSED: dict[Path, tuple[Any, str, CanonicalIntent | None]] = {}


def _parse(codec_name: str, path: Path) -> tuple[Any, str, CanonicalIntent | None]:
    if path not in _PARSED:
        codec = get_codec(codec_name)
        text = path.read_text(encoding="utf-8")
        try:
            tree = codec.parse(text)
        except Exception:
            tree = None
        _PARSED[path] = (codec, text, tree if isinstance(tree, CanonicalIntent) else None)
    return _PARSED[path]


def _comparable(codec_name: str, path: Path) -> tuple[Any, str, CanonicalIntent | None]:
    """The capture, with its tree -- or ``None`` where the experiment
    cannot be run on it."""
    codec, text, tree = _parse(codec_name, path)
    # A rename clears verbatim Junos apply-group bodies, by design: the
    # moved run would differ from the unmoved one for that reason.
    if tree is not None and (tree.group_content or tree.apply_groups):
        return codec, text, None
    return codec, text, tree


#: Captures the experiment cannot be run on, each for the reason given.
#: Pinned, so that a capture cannot leave the experiment quietly: a new
#: capture that belongs here fails the test until it is added, and one
#: listed here that has become comparable fails it until it is removed.
_NO_TWO = "no two physical ports (or two LAGs) of one name shape, without sub-interfaces"
_APPLY_GROUPS = "carries Junos apply-groups, whose verbatim bodies a rename clears by design"
_NOT_EXERCISED: dict[str, str] = {
    "aruba_aoss/hpe_community_5406rzl2_kb1515.cfg": _NO_TWO,
    "cisco_iosxe/batfish_cisco_aaa.txt": _NO_TWO,
    "cisco_iosxe/batfish_cisco_interface.txt": _NO_TWO,
    "cisco_iosxe/batfish_cisco_ip_route.txt": _NO_TWO,
    "cisco_iosxe/batfish_cisco_logging.txt": _NO_TWO,
    "cisco_iosxe/batfish_cisco_snmp.txt": _NO_TWO,
    "cisco_iosxe/ntc_carrier_interfaces.txt": _NO_TWO,
    "cisco_iosxe/racc_cat8000v_iosxe179_netconf.txt": _NO_TWO,
    "cisco_iosxe/racc_csr1000v_iosxe169_bgp_ospf.txt": _NO_TWO,
    "cisco_iosxe/racc_csr1_iosxe173_umbrella_sig.txt": _NO_TWO,
    "dell_os10/dellgeos_S5212F-TOR1-Advanced.cfg": _NO_TWO,
    "dell_os10/dellgeos_S5212F-TOR1-Universal.cfg": _NO_TWO,
    "dell_os10/dellgeos_S5212F-TOR2-Advanced.cfg": _NO_TWO,
    "dell_os10/dellgeos_S5212F-TOR2-Universal.cfg": _NO_TWO,
    "junos/buraglio_netlab_junos184.set": _NO_TWO,
    "junos/jnprautomate_mnha_vsrx_a_junos.set": _APPLY_GROUPS,
    "junos/ksator_labmgmt_ex4550_junos151.set": _APPLY_GROUPS,
    "junos/ksator_labmgmt_qfx10k2_junos173.set": _APPLY_GROUPS,
    "junos/ksator_labmgmt_qfx5100_junos173.set": _APPLY_GROUPS,
    "junos/ksator_labmgmt_qfx5110_junos173.set": _APPLY_GROUPS,
    "mikrotik/ntc_ip_address_export.rsc": _NO_TWO,
    "opnsense/opnsense_acl_test_config.xml": _NO_TWO,
    "opnsense/opnsense_core_default.xml": _NO_TWO,
    "opnsense/opnsense_paramiko_shell_capture.xml": _NO_TWO,
    "opnsense/user_contrib_supergate_opn25.xml": _NO_TWO,
    "vyos/vyos_forum_snmpv3_user_eq13.conf": _NO_TWO,
}


# ---------------------------------------------------------------------------
# Every codec's captures
# ---------------------------------------------------------------------------


class TestEveryCapture:
    def test_the_captures_left_out_are_exactly_these(self) -> None:
        """A capture with fewer than two ports of one shape cannot be
        exchanged, and one that carries Junos apply-groups is left
        out by design.  The list is pinned so that neither the
        selection nor a new capture can shrink the experiment without
        this test changing."""
        left_out = set()
        for codec_name, path in CAPTURES:
            codec, _text, tree = _comparable(codec_name, path)
            if tree is None or not _names_to_move(codec, tree):
                left_out.add(_capture_id(path))
        assert left_out == set(_NOT_EXERCISED)

    def test_the_flag_is_what_the_captures_show(self) -> None:
        """A codec whose parser records a factory name beside a
        port's own finds ports by it, and has to say so
        (``ports_keep_a_factory_name``): model-to-model mapping sets
        the field only for a target that does, and a port an operator
        names is otherwise looked up by a name no device has.  Read
        off the committed captures rather than a list of codecs, so
        a codec that starts recording one cannot leave the flag at
        its default unnoticed."""
        records: dict[str, bool] = {}
        for codec_name, path in CAPTURES:
            _codec, _text, tree = _parse(codec_name, path)
            if tree is not None:
                records[codec_name] = records.get(codec_name, False) or any(
                    iface.default_name for iface in tree.interfaces
                )
        assert set(records) == set(FIXTURE_DIR_CODEC.values())
        assert any(records.values())
        for codec_name, records_one in sorted(records.items()):
            assert get_codec(codec_name).ports_keep_a_factory_name is records_one, codec_name

    def test_every_codec_with_captures_is_exercised(self) -> None:
        exercised = {
            codec_name for codec_name, path in CAPTURES
            if _capture_id(path) not in _NOT_EXERCISED
        }
        assert exercised == set(FIXTURE_DIR_CODEC.values())

    @pytest.mark.parametrize(
        ("codec_name", "path"), CAPTURES, ids=[_capture_id(path) for _, path in CAPTURES],
    )
    def test_a_renamed_port_takes_every_reference_with_it(
        self, codec_name: str, path: Path,
    ) -> None:
        if _capture_id(path) in _NOT_EXERCISED:
            pytest.skip(_NOT_EXERCISED[_capture_id(path)])
        codec, text, tree = _comparable(codec_name, path)
        moves = _names_to_move(codec, tree)
        stayed = _what_did_not_follow(codec, text, moves)
        assert not stayed, (
            f"moving {len(moves)} name(s): {len(stayed)} value(s) of the output did "
            f"not follow -- a place the translator does not reach:\n  "
            + "\n  ".join(stayed[:8])
        )

    @pytest.mark.parametrize(
        ("codec_name", "path"), CAPTURES, ids=[_capture_id(path) for _, path in CAPTURES],
    )
    def test_with_the_device_declared_its_hardware_follows_as_well(
        self, codec_name: str, path: Path,
    ) -> None:
        """The same captures through ``run_plan_with_models``, the
        device declared on both sides and the moves given as the
        operator's entries.  This is where a factory name has to move:
        left behind, the output told the device to find each port by
        the name of the hardware it had LEFT."""
        if _capture_id(path) in _NOT_EXERCISED:
            pytest.skip(_NOT_EXERCISED[_capture_id(path)])
        codec, text, tree = _comparable(codec_name, path)
        moves = _ports_to_move(codec, tree)
        if not moves:
            pytest.skip("only LAG names to exchange, which are not ports of a device")
        stayed = _what_did_not_follow_with_devices(codec, text, moves)
        # No capture is skipped here for want of a pairing.  If one
        # ever is, it is named in ``_NOT_EXERCISED`` with its reason,
        # not passed over.
        assert stayed is not None, "no pairing could be made for this config"
        assert not stayed, (
            f"moving {len(moves)} port(s): {len(stayed)} value(s) of the output did "
            f"not follow:\n  " + "\n  ".join(stayed[:8])
        )

    def test_the_declared_experiment_runs_where_a_factory_name_exists(self) -> None:
        """The run above skips a capture it can make no pairing for.
        It must not skip its way past the one platform it is there
        for."""
        ran = 0
        for codec_name, path in CAPTURES:
            if codec_name != "mikrotik_routeros" or _capture_id(path) in _NOT_EXERCISED:
                continue
            codec, text, tree = _comparable(codec_name, path)
            assert any(iface.default_name for iface in tree.interfaces)
            assert _what_did_not_follow_with_devices(
                codec, text, _ports_to_move(codec, tree),
            ) == []
            ran += 1
        assert ran


# ---------------------------------------------------------------------------
# What the experiment reaches
# ---------------------------------------------------------------------------

#: Every place the rename sweep rewrites: its name, and the objects of
#: a tree that hold it with the attribute that does.
_PLACES: dict[str, Callable[[CanonicalIntent], list[tuple[Any, str]]]] = {
    "interfaces[].name": lambda t: [(i, "name") for i in t.interfaces],
    "interfaces[].lag_member_of": lambda t: [(i, "lag_member_of") for i in t.interfaces],
    "interfaces[].vrrp_groups[].track_interfaces": lambda t: [
        (g, "track_interfaces") for i in t.interfaces for g in i.vrrp_groups
    ],
    "vlans[].tagged_ports": lambda t: [(v, "tagged_ports") for v in t.vlans],
    "vlans[].untagged_ports": lambda t: [(v, "untagged_ports") for v in t.vlans],
    "lags[].name": lambda t: [(lag, "name") for lag in t.lags],
    "lags[].members": lambda t: [(lag, "members") for lag in t.lags],
    "static_routes[].interface": lambda t: [(r, "interface") for r in t.static_routes],
    "static_routes[].gateway": lambda t: [(r, "gateway") for r in t.static_routes],
    "dhcp_servers[].interface": lambda t: [(p, "interface") for p in t.dhcp_servers],
    "vxlan_vnis[].source_interface": lambda t: [(v, "source_interface") for v in t.vxlan_vnis],
}

#: The places at which a broken translator is caught by the experiment
#: on a committed capture.
_CAUGHT_ON_A_CAPTURE: frozenset[str] = frozenset({
    "interfaces[].name",
    "interfaces[].lag_member_of",
    "vlans[].tagged_ports",
    "vlans[].untagged_ports",
    "lags[].name",
    "lags[].members",
    "static_routes[].interface",
})

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

_IOS_TRACK = """hostname sw
!
interface GigabitEthernet1/0/1
 description a
!
interface GigabitEthernet1/0/2
 description b
!
interface Vlan10
 ip address 10.0.10.2 255.255.255.0
 vrrp 20 ip 10.0.10.1
 vrrp 20 track GigabitEthernet1/0/1
!
end
"""

_FORTIGATE_DHCP = """config system interface
    edit "port1"
        set ip 10.1.1.1 255.255.255.0
        set type physical
    next
    edit "port2"
        set ip 10.2.2.1 255.255.255.0
        set type physical
    next
end
config system dhcp server
    edit 1
        set default-gateway 10.1.1.1
        set netmask 255.255.255.0
        set interface "port1"
        config ip-range
            edit 1
                set start-ip 10.1.1.10
                set end-ip 10.1.1.20
            next
        end
    next
end
"""

_EOS_VTEP = """hostname leaf
!
interface Loopback0
   ip address 10.255.0.1/32
!
interface Loopback1
   ip address 10.255.1.1/32
!
interface Vxlan1
   vxlan source-interface Loopback1
   vxlan vlan 10 vni 10010
!
vlan 10
!
end
"""

#: For each place no committed capture catches: a small config that
#: fills it, and the names to exchange in it.
_SMALL_CONFIGS: dict[str, tuple[str, str, dict[str, str]]] = {
    "static_routes[].gateway": (
        "mikrotik_routeros", _ROUTEROS_NEXT_HOPS, {"ether1": "ether2", "ether2": "ether1"},
    ),
    "interfaces[].vrrp_groups[].track_interfaces": (
        "cisco_iosxe_cli", _IOS_TRACK,
        {
            "GigabitEthernet1/0/1": "GigabitEthernet1/0/2",
            "GigabitEthernet1/0/2": "GigabitEthernet1/0/1",
        },
    ),
    "dhcp_servers[].interface": (
        "fortigate_cli", _FORTIGATE_DHCP, {"port1": "port2", "port2": "port1"},
    ),
    "vxlan_vnis[].source_interface": (
        "arista_eos", _EOS_VTEP, {"Loopback0": "Loopback1", "Loopback1": "Loopback0"},
    ),
}


def _holds(value: Any, moves: dict[str, str]) -> bool:
    if isinstance(value, str):
        return _move_text(value, moves) != value
    return any(_holds(item, moves) for item in value or [])


def _a_translator_that_skips(place: str) -> Callable[..., Any]:
    """The real translator, with *place* put back as it was: what the
    sweep would do if that place were missing from it."""
    real = port_names.translate_port_names

    def broken(intent: Any, *args: Any, **kwargs: Any) -> Any:
        if not isinstance(intent, CanonicalIntent):
            return real(intent, *args, **kwargs)
        saved = [
            (holder, attribute, getattr(holder, attribute))
            for holder, attribute in _PLACES[place](intent)
        ]
        saved = [
            (holder, attribute, list(value) if isinstance(value, list) else value)
            for holder, attribute, value in saved
        ]
        result = real(intent, *args, **kwargs)
        for holder, attribute, value in saved:
            setattr(holder, attribute, value)
        return result

    return broken


def _captures_that_fill(place: str) -> list[tuple[Any, str, dict[str, str]]]:
    found = []
    for codec_name, path in CAPTURES:
        if _capture_id(path) in _NOT_EXERCISED:
            continue
        codec, text, tree = _comparable(codec_name, path)
        moves = _names_to_move(codec, tree)
        if any(_holds(getattr(holder, attribute), moves) for holder, attribute in _PLACES[place](tree)):
            found.append((codec, text, moves))
    return found


class TestWhatTheExperimentReaches:
    """"No list of fields" is a claim about the oracle, not a promise
    that every field is reached.  Here the translator is broken at
    each place in turn -- that place put back as it was after the
    sweep -- and something has to notice.  Which places a committed
    capture notices is pinned; each of the others has a small config
    that does."""

    def test_the_table_the_sweep_and_the_collector_name_the_same_places(self) -> None:
        """Three lists of the places a port name lives in: the names
        the collector yields, the fields the rename pass rewrites, and
        the table above.  They are compared on a tree BUILT FROM THE
        SCHEMA -- a name of its own in every text field the canonical
        model has -- so that no fourth list, a fixture kept by hand,
        stands between them: a field added to one and not to the
        others fails here without anyone having to remember a tree.

        ``gateway`` is the table's one entry the other two do not
        have: it is rewritten only when it is the name of an
        interface, which a field with a name of its own never is."""
        codec = get_codec("aruba_aoss")
        tree, where = _a_name_in_every_text_field()
        collected = {where[name] for name in port_names._swept_names(tree)}
        translate_port_names(
            tree, codec, codec, rename_map={name: "x-" + name for name in where},
        )
        rewritten = {
            path for path, value in _text_fields(tree)
            if value.startswith("x-") and where.get(value[2:]) == path
        }
        assert collected == rewritten
        assert collected == set(_PLACES) - {"static_routes[].gateway"}

    @pytest.mark.parametrize("place", sorted(_PLACES))
    def test_a_translator_broken_at_one_place_is_caught(
        self, place: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captures = _captures_that_fill(place)
        monkeypatch.setattr(port_names, "translate_port_names", _a_translator_that_skips(place))
        on_a_capture = any(
            _what_did_not_follow(codec, text, moves) for codec, text, moves in captures
        )
        assert on_a_capture == (place in _CAUGHT_ON_A_CAPTURE), (
            f"{place}: caught on a committed capture is {on_a_capture}; "
            f"the pinned list says {place in _CAUGHT_ON_A_CAPTURE}"
        )
        if not on_a_capture:
            codec_name, text, moves = _SMALL_CONFIGS[place]
            assert _what_did_not_follow(get_codec(codec_name), text, moves), (
                f"{place}: nothing notices a translator that skips it"
            )

    def test_every_place_no_capture_catches_has_a_small_config(self) -> None:
        assert set(_SMALL_CONFIGS) == set(_PLACES) - _CAUGHT_ON_A_CAPTURE

    @pytest.mark.parametrize("place", sorted(_SMALL_CONFIGS))
    def test_the_small_configs_pass_on_the_real_translator(self, place: str) -> None:
        codec_name, text, moves = _SMALL_CONFIGS[place]
        assert _what_did_not_follow(get_codec(codec_name), text, moves) == []


# ---------------------------------------------------------------------------
# Shapes no committed capture has
# ---------------------------------------------------------------------------


class TestShapesNoCaptureHas:
    def test_a_unit_next_hop_follows_between_two_configs_of_one_codec(self) -> None:
        moves = {"xe-0/0/1": "xe-0/0/2", "xe-0/0/2": "xe-0/0/1"}
        assert _what_did_not_follow(get_codec("juniper_junos"), _JUNOS_NEXT_HOP, moves) == []

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


# ---------------------------------------------------------------------------
# A name that is new, and the factory name
# ---------------------------------------------------------------------------


class TestAnEntryNamesAPort:
    """What the experiment cannot see: it exchanges names the device
    already has.  The commonest entry of a rename map on RouterOS
    gives a port a name it never had.  Without devices declared that
    is ALL an entry does there -- the port's hardware stays -- and it
    is what such an entry has always rendered."""

    @pytest.mark.parametrize(
        "name", ["WAN", "ether1-WAN", "uplink to core", "sfp1", "ETHER5", "ether5"],
    )
    def test_the_port_is_found_by_its_factory_name_and_given_the_name(self, name: str) -> None:
        """``sfp1`` and ``ETHER5`` read as port names to the RouterOS
        codec, and ``ether5`` is one.  None of that makes the entry a
        move: nothing here knows which ports the TARGET has."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_overrides(
            mikrotik, mikrotik, _ROUTEROS_NEXT_HOPS, port_rename_map={"ether1": name},
        )
        shown = f'"{name}"' if " " in name else name
        assert f'set [ find default-name=ether1 ] name={shown} comment="wan"' in job.rendered
        assert f"default-name={name}" not in job.rendered
        assert f"add address=192.0.2.2/30 interface={shown}" in job.rendered
        # The route's next hop follows the name.  (The RouterOS
        # renderer writes a next hop unquoted, as it does a route's
        # interface, so a name with a space in it is written bare
        # there: the renderer's own, older, limit.)
        assert f"add dst-address=0.0.0.0/0 gateway={name}" in job.rendered
        assert job.port_renames == {"ether1": name}

    def test_on_a_committed_capture(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        text = (REAL / "mikrotik" / "user_contrib_crs310_ros7.rsc").read_text(encoding="utf-8")
        job = run_plan_with_overrides(
            mikrotik, mikrotik, text, port_rename_map={"ether1": "uplink-to-core"},
        )
        lines = [line for line in job.rendered.splitlines() if "uplink-to-core" in line]
        assert lines[0].startswith("set [ find default-name=ether1 ] name=uplink-to-core ")
        assert "default-name=uplink-to-core" not in job.rendered

    def test_the_translator_never_touches_a_factory_name(self) -> None:
        """Renamed by an entry, renamed by the shape of its name onto
        another vendor, or left alone: the field says which hardware
        the port WAS, and only a caller that knows the target device
        may change it."""
        mikrotik, eos = get_codec("mikrotik_routeros"), get_codec("arista_eos")
        for target, entries in ((mikrotik, {"ether1": "ether2"}), (eos, {}), (eos, {"ether1": "Ethernet9"})):
            tree = mikrotik.parse(_ROUTEROS_NEXT_HOPS)
            before = sorted(iface.default_name for iface in tree.interfaces)
            translate_port_names(tree, mikrotik, target, rename_map=entries)
            assert sorted(iface.default_name for iface in tree.interfaces) == before

    def test_the_key_of_an_entry_is_the_name_the_config_uses(self) -> None:
        """``core-a`` is the operator's name for the port whose
        factory name is ``ether1``, and every line of the config calls
        it ``core-a``.  An entry keyed by ``ether1`` names nothing in
        the config, does nothing, and is said."""
        mikrotik = get_codec("mikrotik_routeros")
        tree = mikrotik.parse(_ROUTEROS_RENAMED_PORTS)
        assert collect_port_names(tree) == ["core-a", "core-b"]
        assert collect_hardware_port_names(
            tree, classify=mikrotik.classify_port_name,
        ) == ["core-a", "core-b"]
        for entries in ({"ether1": "ether2"}, {"ether1": None}):
            job = run_plan_with_overrides(
                mikrotik, mikrotik, _ROUTEROS_RENAMED_PORTS, port_rename_map=entries,
            )
            assert "set [ find default-name=ether1 ] name=core-a" in job.rendered
            assert "add address=10.0.0.1/30 interface=core-a" in job.rendered
            assert job.port_renames == {} and job.port_drops == []
            assert any(
                "source port 'ether1' does not exist in the parsed config" in w
                for w in job.warnings
            )

    def test_a_port_the_operator_named_is_renamed_and_dropped_by_that_name(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_overrides(
            mikrotik, mikrotik, _ROUTEROS_RENAMED_PORTS,
            port_rename_map={"core-a": "wan", "core-b": None},
        )
        assert "set [ find default-name=ether1 ] name=wan" in job.rendered
        assert "add address=10.0.0.1/30 interface=wan" in job.rendered
        assert "core-b" not in job.rendered and "10.0.0.5/30" not in job.rendered
        assert job.port_drops == ["core-b"]


# ---------------------------------------------------------------------------
# The oracle can fail
# ---------------------------------------------------------------------------


class TestTheOracleCanFail:
    def test_a_value_that_did_not_follow(self) -> None:
        before = {"interfaces": [{"name": "p1", "lookup": "p1"}, {"name": "p2", "lookup": "p2"}]}
        stale = {"interfaces": [{"name": "p2", "lookup": "p1"}, {"name": "p1", "lookup": "p2"}]}
        moved = {"interfaces": [{"name": "p2", "lookup": "p2"}, {"name": "p1", "lookup": "p1"}]}
        moves = {"p1": "p2", "p2": "p1"}
        assert _differences(_move_tree(before, moves), moved) == []
        stayed = _differences(_move_tree(before, moves), stale)
        assert [line.split(":")[0] for line in stayed] == [
            "interfaces.[p1].lookup", "interfaces.[p2].lookup",
        ]

    def test_a_record_that_vanished(self) -> None:
        """A value absent on one side is a difference, not a blank."""
        whole = {"interfaces": [{"name": "p1", "mtu": 9000}, {"name": "p2", "mtu": 1500}]}
        short = {"interfaces": [{"name": "p1", "mtu": 9000}]}
        assert [line.split(":")[0] for line in _differences(whole, short)] == [
            "interfaces.[p2].mtu", "interfaces.[p2].name",
        ]
        assert _differences(short, whole)

    def test_a_list_of_names_is_compared_by_what_is_in_it(self) -> None:
        """...and not by how long it is: one member exchanged for
        another is a difference, and the same members in another order
        are not."""
        one = {"vlans": [{"id": 10, "tagged_ports": ["p1", "p2"]}]}
        assert _differences(one, {"vlans": [{"id": 10, "tagged_ports": ["p2", "p1"]}]}) == []
        assert _differences(one, {"vlans": [{"id": 10, "tagged_ports": ["p1", "p3"]}]})

    def test_a_name_with_a_unit_moves_with_its_port(self) -> None:
        assert _move_text("ge-0/0/1.54", {"ge-0/0/1": "ge-0/0/9"}) == "ge-0/0/9.54"
        assert _move_text("ge-0/0/1.backup", {"ge-0/0/1": "ge-0/0/9"}) == "ge-0/0/1.backup"
        assert _move_text("uplink to ge-0/0/1", {"ge-0/0/1": "ge-0/0/9"}) == "uplink to ge-0/0/1"

    def test_the_field_that_must_stand_still_is_not_moved(self) -> None:
        tree = {"interfaces": [{"name": "ether1", "default_name": "ether1"}]}
        moves = {"ether1": "ether2"}
        assert _move_tree(tree, moves, keep=_HARDWARE_IDENTITY) == {
            "interfaces": [{"name": "ether2", "default_name": "ether1"}],
        }
        assert _move_tree(tree, moves) == {
            "interfaces": [{"name": "ether2", "default_name": "ether2"}],
        }


# ---------------------------------------------------------------------------
# The two lists agree with each other
# ---------------------------------------------------------------------------


def _unwrapped(annotation: Any) -> Any:
    """``X`` out of ``X | None``."""
    if get_origin(annotation) in (Union, types.UnionType):
        kinds = [arg for arg in get_args(annotation) if arg is not type(None)]
        return kinds[0] if len(kinds) == 1 else annotation
    return annotation


#: Fields that hold text in a shape :func:`_filled` does not fill, and
#: no port name: verbatim sections, and Junos group bodies.
_TEXT_NOT_FILLED = {"raw_sections", "group_content"}


def _can_hold_text(annotation: Any) -> bool:
    """Is ``str`` -- or a model, which may hold one -- anywhere in
    *annotation*?"""
    if annotation is str:
        return True
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return True
    return any(_can_hold_text(arg) for arg in get_args(annotation))


def _filled(model: type[BaseModel], path: str, where: dict[str, str]) -> BaseModel:
    """An instance of *model* with a name of its own in every ``str``
    and ``list[str]`` field, one element in every list of models, and
    every other field at its default.  Built without validation: the
    port translator reads attributes, and a made-up name is not a
    valid address or keyword.

    A field that can hold text in any OTHER shape -- a dict, a tuple,
    a set, a union -- is refused, not skipped: left empty, a port name
    kept in it would be in none of the three lists this tree compares,
    and the comparison would pass.  Teach this helper the shape, or
    list the field in ``_TEXT_NOT_FILLED`` as holding no port name."""
    values: dict[str, Any] = {}
    # The declared types, resolved here: pydantic leaves a forward
    # reference unresolved on ``model_fields`` until the model is first
    # used, so what this saw would depend on which test ran before it.
    declared = get_type_hints(model)
    for name in model.model_fields:
        here = f"{path}.{name}" if path else name
        kind = _unwrapped(declared[name])
        item = _unwrapped(get_args(kind)[0]) if get_origin(kind) is list and get_args(kind) else None
        if kind is str:
            values[name] = _named(here, where)
        elif isinstance(kind, type) and issubclass(kind, BaseModel):
            values[name] = _filled(kind, here, where)
        elif item is str:
            values[name] = [_named(here + "[]", where)]
        elif isinstance(item, type) and issubclass(item, BaseModel):
            values[name] = [_filled(item, here + "[]", where)]
        elif _can_hold_text(declared[name]) and here not in _TEXT_NOT_FILLED:
            raise AssertionError(
                f"{here}: a field that can hold text, in a shape this helper does not fill"
            )
    return model.model_construct(**values)


def _named(path: str, where: dict[str, str]) -> str:
    name = f"n{len(where)}"
    where[name] = path
    return name


def _a_name_in_every_text_field() -> tuple[CanonicalIntent, dict[str, str]]:
    """A canonical tree built from the schema, and each made-up
    name's place in it (``interfaces[].vrrp_groups[].track_interfaces[]``
    is written ``interfaces[].vrrp_groups[].track_interfaces``, as the
    table of places writes it)."""
    where: dict[str, str] = {}
    tree = _filled(CanonicalIntent, "", where)
    for name, path in where.items():
        where[name] = path.removesuffix("[]")
    assert isinstance(tree, CanonicalIntent)
    return tree, where


def _text_fields(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(node, BaseModel):
        for name in type(node).model_fields:
            yield from _text_fields(getattr(node, name, None), f"{path}.{name}" if path else name)
    elif isinstance(node, list):
        for item in node:
            yield from _text_fields(item, path + "[]" if isinstance(item, BaseModel) else path)
    elif isinstance(node, str):
        yield path, node


class TestTheTwoListsAgree:
    def test_the_schema_built_tree_reaches_every_place(self) -> None:
        """The tree the comparisons are made on fills every place the
        table names -- else a comparison on it compares nothing."""
        _tree, where = _a_name_in_every_text_field()
        assert set(_PLACES) <= set(where.values())
        assert "interfaces[].default_name" in where.values()

    @pytest.mark.parametrize(
        "shape", [dict[str, str], tuple[str, ...], set[str], str | int, list[list[str]]],
        ids=["dict", "tuple", "set", "union", "nested-list"],
    )
    def test_the_builder_refuses_a_text_field_it_cannot_fill(self, shape: Any) -> None:
        """A port name kept in a shape the builder leaves empty would
        be missing from all three lists alike, and the comparison
        would pass.  So a new field of such a shape fails HERE until
        someone decides what it is."""
        odd = create_model("Odd", holds_text=(shape, None))
        with pytest.raises(AssertionError, match="a field that can hold text"):
            _filled(odd, "", {})

    def test_the_two_fields_it_leaves_alone_hold_no_port_name(self) -> None:
        declared = get_type_hints(CanonicalIntent)
        assert set(declared) >= _TEXT_NOT_FILLED
        tree, where = _a_name_in_every_text_field()
        assert not _TEXT_NOT_FILLED & set(where.values())
        assert tree.raw_sections == {} and tree.group_content == {}

    def test_a_factory_name_is_not_a_place_the_sweep_rewrites(self) -> None:
        """A port's hardware identity is not a reference to it, and
        the translator leaves it alone."""
        codec = get_codec("aruba_aoss")
        tree, where = _a_name_in_every_text_field()
        before = [iface.default_name for iface in tree.interfaces]
        assert before and all(before)
        translate_port_names(
            tree, codec, codec, rename_map={name: "x-" + name for name in where},
        )
        assert [iface.default_name for iface in tree.interfaces] == before

    def test_a_dropped_name_is_gone_from_every_place(self) -> None:
        codec = get_codec("aruba_aoss")
        tree, _where = _a_name_in_every_text_field()
        before = collect_port_names(tree)
        assert before
        translate_port_names(tree, codec, codec, rename_map=dict.fromkeys(before))
        assert collect_port_names(tree) == []


# ---------------------------------------------------------------------------
# What the translator says when an operator drops a port
# ---------------------------------------------------------------------------


class TestWarningsUnderADrop:
    def test_a_dropped_port_is_not_named_among_the_sources_of_a_clash(self) -> None:
        """Two ports are sent onto the name of a third, which the
        operator drops.  The dropped port is stripped before any name
        is resolved, so it shares that name with nobody and the warning
        names the two that do."""
        ios = get_codec("cisco_iosxe_cli")
        text = (
            "hostname sw\n!\ninterface GigabitEthernet1/0/1\n description a\n!\n"
            "interface GigabitEthernet1/0/2\n description b\n!\n"
            "interface GigabitEthernet1/0/3\n description c\n!\nend\n"
        )
        job = run_plan_with_overrides(
            ios, ios, text, port_rename_map={
                "GigabitEthernet1/0/1": "GigabitEthernet1/0/3",
                "GigabitEthernet1/0/2": "GigabitEthernet1/0/3",
                "GigabitEthernet1/0/3": None,
            },
        )
        clashes = [w for w in job.warnings if "multiple source ports map to" in w]
        assert len(clashes) == 1
        assert "(sources: GigabitEthernet1/0/1, GigabitEthernet1/0/2)" in clashes[0]
        assert job.port_drops == ["GigabitEthernet1/0/3"]

    def test_nor_is_a_name_the_translator_dropped_on_its_own(self) -> None:
        """IOS-XE has no form for a Junos ``me0``, so the translator
        drops it.  Two ports renamed onto that name do share it; the
        dropped one shares nothing, and is not named as a third."""
        junos, ios = get_codec("juniper_junos"), get_codec("cisco_iosxe_cli")
        text = (
            "set interfaces me0 unit 0 family inet address 192.0.2.5/24\n"
            "set interfaces xe-0/0/0 unit 0 family inet address 10.0.0.1/24\n"
            "set interfaces xe-0/0/1 unit 0 family inet address 10.0.1.1/24\n"
        )
        job = run_plan_with_overrides(
            junos, ios, text, port_rename_map={"xe-0/0/0": "me0", "xe-0/0/1": "me0"},
        )
        assert job.port_drops == ["me0"]
        clashes = [w for w in job.warnings if "multiple source ports map to" in w]
        assert len(clashes) == 1
        assert "(sources: xe-0/0/0, xe-0/0/1)" in clashes[0]


class TestANextHopNamingAnInterfaceTheTargetCannotExpress:
    def test_the_route_goes_with_the_interface(self) -> None:
        """IOS-XE has no form for a Junos ``me0``, so the translator
        drops it on its own.  A route whose next hop is that interface
        goes with it, as it would for an interface an operator dropped
        -- it does not stay behind naming an interface the output no
        longer has."""
        junos, ios = get_codec("juniper_junos"), get_codec("cisco_iosxe_cli")
        text = (
            "set interfaces me0 unit 0 family inet address 192.0.2.5/24\n"
            "set interfaces ge-0/0/1 unit 0 family inet address 10.0.1.1/24\n"
            "set routing-options static route 10.99.0.0/16 next-hop me0.0\n"
            "set routing-options static route 10.98.0.0/16 next-hop 10.0.1.254\n"
        )
        tree = junos.parse(text)
        assert [route.gateway for route in tree.static_routes] == ["me0.0", "10.0.1.254"]
        job = run_plan_with_overrides(junos, ios, text, port_rename_map={})
        assert job.port_drops == ["me0"]
        assert "10.99.0.0" not in job.rendered
        assert "ip route 10.98.0.0 255.255.0.0 10.0.1.254" in job.rendered
