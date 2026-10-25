"""A sub-interface numbered above what the target numbers goes by its TAG.

Juniper's ``unit`` statement at ``[edit interfaces interface-name]``
gives "Range: 0 through 16,384".  An IOS-XE
``interface GigabitEthernet0/0/1.20000`` with ``encapsulation dot1Q 200``
was sent after its port with its own number, and written ``set interfaces
ge-0/0/1 unit 20000``: a unit Junos does not number, in a job that said
``completed`` with nothing to report.  Across vendors such a unit now goes
where its port goes named by its 802.1Q tag (a tag is at most 4094), as a
tagged unit 0 already did (``CodecBase.largest_unit``,
``port_names.goes_by_its_tag``); one with no tag is not sent after its
port, and holds the job as a name the translator did not place.  A unit
of two tags is named by its INNER tag: the outer can be every unit's of
a port, and the committed IOS-XE carrier capture numbers six such
units outer-then-inner (``GigabitEthernet2/0/4.223415``, ``dot1Q 2234
second-dot1q 15``), which the outer tag put on one Junos unit.

What each source holds is typed by hand.  The output is read two ways: as
text, by a reader of Junos set lines typed here, and with the Junos
parser.  Each check is handed the defect it is for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from netcanon.definitions import LIBRARY_DIR
from netcanon.migration.canonical import port_names
from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalInterface
from netcanon.migration.canonical.port_names import (
    above_the_largest_unit,
    goes_by_its_tag,
    unit_tags,
)
from netcanon.migration.codecs.juniper_junos.codec import JunosCodec
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.device_models import inventory_from_profile
from netcanon.migration.target_profiles import load_profiles_dir
from netcanon.models.migration import MigrationJobStatus
from netcanon.services import migration_pipeline
from netcanon.services.migration_pipeline import (
    run_plan_with_checked_names,
    run_plan_with_models,
)

_JUNOS = "juniper_junos"


@dataclass(frozen=True)
class Source:
    codec: str
    text: str
    port: str  # the source's name for the port the unit is on


#: A unit numbered 20000 that carries VLAN 200 and 198.51.100.1/24.
SOURCES = {
    "iosxe": Source(
        "cisco_iosxe_cli",
        "hostname r1\n"
        "interface GigabitEthernet0/0/2\n no switchport\n!\n"
        "interface GigabitEthernet0/0/2.20000\n encapsulation dot1Q 200\n"
        " ip address 198.51.100.1 255.255.255.0\n!\n",
        "GigabitEthernet0/0/2",
    ),
    "iosxr": Source(
        "cisco_iosxr",
        "hostname r1\n!\ninterface GigabitEthernet0/0/0/2\n!\n"
        "interface GigabitEthernet0/0/0/2.20000\n encapsulation dot1q 200\n"
        " ipv4 address 198.51.100.1 255.255.255.0\n!\n",
        "GigabitEthernet0/0/0/2",
    ),
    "nxos": Source(
        "cisco_nxos",
        "hostname r1\n!\ninterface Ethernet1/2\n  no switchport\n!\n"
        "interface Ethernet1/2.20000\n  encapsulation dot1q 200\n"
        "  ip address 198.51.100.1/24\n!\n",
        "Ethernet1/2",
    ),
    "eos": Source(
        "arista_eos",
        "hostname r1\n!\ninterface Ethernet2\n   no switchport\n!\n"
        "interface Ethernet2.20000\n   encapsulation dot1q vlan 200\n"
        "   ip address 198.51.100.1/24\n!\n",
        "Ethernet2",
    ),
}
_CIDR = "198.51.100.1/24"


# --- a reader of Junos set lines, typed here --------------------------------

_UNIT_LINE = re.compile(r"^set interfaces (\S+) unit (\d+) (.+)$")


def _units(text: str) -> dict[tuple[str, str], list[str]]:
    """What each ``(device, unit)`` of *text* states, line by line."""
    found: dict[tuple[str, str], list[str]] = {}
    for line in text.splitlines():
        m = _UNIT_LINE.match(line.strip())
        if m:
            found.setdefault((m.group(1), m.group(2)), []).append(m.group(3))
    return found


def _text_problems(text: str, port: str, unit: str, tag: int) -> list[str]:
    units = _units(text)
    problems = [
        f"unit {number} of {device}: Junos numbers a unit to 16384"
        for device, number in units if int(number) > 16384
    ]
    where = [key for key, lines in units.items() if f"family inet address {_CIDR}" in lines]
    if where != [(port, unit)]:
        problems.append(f"{_CIDR} is on {where}, not unit {unit} of {port}")
    elif f"vlan-id {tag}" not in units[(port, unit)]:
        problems.append(f"unit {unit} of {port} does not carry VLAN {tag}")
    return problems


def _parsed_problems(text: str, name: str, tag: int) -> list[str]:
    tree = get_codec(_JUNOS).parse(text)
    held = [
        (iface.name, iface.dot1q_vlan) for iface in tree.interfaces
        if any(f"{a.ip}/{a.prefix_length}" == _CIDR for a in iface.ipv4_addresses)
    ]
    return [] if held == [(name, tag)] else [f"{_CIDR}: read back as {held}"]


def _job(key: str, port_map: dict[str, str | None] | None = None):
    src = SOURCES[key]
    return run_plan_with_checked_names(
        get_codec(src.codec), get_codec(_JUNOS), src.text, port_rename_map=port_map or {},
    )


# --- the bound is typed here ------------------------------------------------


def test_the_codecs_that_state_a_largest_unit() -> None:
    """Typed here, not read from the codec: a codec that states a bound,
    or a bound that moves, fails until this table says what the
    vendor's page gives."""
    stated = {
        name: get_codec(name).largest_unit for name in list_public_codecs()
        if get_codec(name).largest_unit is not None
    }
    assert stated == {_JUNOS: 16384}


@pytest.mark.parametrize(
    ("unit", "largest", "above"),
    [
        ("16384", 16384, False),
        ("16385", 16384, True),
        ("0016384", 16384, False),
        ("016385", 16384, True),
        ("20000", 16384, True),
        ("9999", 16384, False),
        ("99999999999999999999", 16384, True),
        ("0", 16384, False),
        ("20000", None, False),
    ],
)
def test_above_the_largest_unit(unit: str, largest: int | None, above: bool) -> None:
    assert above_the_largest_unit(unit, largest) is above


@pytest.mark.parametrize(
    ("unit", "same_codec", "named_by_tag", "largest", "by_tag"),
    [
        ("20000", False, False, 16384, True),
        ("16384", False, False, 16384, False),
        ("54", False, False, 16384, False),
        ("0", False, False, None, True),
        ("00", False, False, None, True),
        ("20000", False, False, None, False),
        # Between two configs of one codec a unit keeps its number.
        ("20000", True, False, 16384, False),
        ("0", True, False, None, False),
        # Onto VyOS a unit is always its tag.
        ("54", True, True, None, True),
        ("54", False, True, None, True),
    ],
)
def test_goes_by_its_tag(unit, same_codec, named_by_tag, largest, by_tag) -> None:
    assert goes_by_its_tag(
        unit, same_codec=same_codec, named_by_tag=named_by_tag, largest_unit=largest,
    ) is by_tag


def test_the_tag_a_unit_is_named_by() -> None:
    tree = CanonicalIntent(interfaces=[
        CanonicalInterface(name="p.1", dot1q_vlan=100),
        CanonicalInterface(name="p.2", dot1q_vlan=100, dot1q_inner_vlan=20),
        CanonicalInterface(name="p.3"),
    ])
    assert unit_tags(tree, named_by_tag=False) == {"p.1": 100, "p.2": 20}
    # On VyOS the number of a vif is its (outer) tag, as before.
    assert unit_tags(tree, named_by_tag=True) == {"p.1": 100, "p.2": 100}


# --- the source trees are what is typed here -------------------------------


@pytest.mark.parametrize("key", sorted(SOURCES))
def test_each_source_holds_its_unit(key: str) -> None:
    src = SOURCES[key]
    tree = get_codec(src.codec).parse(src.text)
    held = {(i.name, i.dot1q_vlan) for i in tree.interfaces if i.dot1q_vlan is not None}
    assert held == {(f"{src.port}.20000", 200)}


# --- the output -------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(SOURCES))
def test_a_unit_above_the_bound_is_its_tag_on_junos(key: str) -> None:
    job = _job(key)
    port = job.port_renames[SOURCES[key].port]
    assert job.status == MigrationJobStatus.completed, job.error
    assert job.port_renames[f"{SOURCES[key].port}.20000"] == f"{port}.200"
    assert _text_problems(job.rendered, port, "200", 200) == []
    assert _parsed_problems(job.rendered, f"{port}.200", 200) == []


def _iosxe(*units: tuple[str, int | None, str]) -> str:
    lines = ["hostname r1", "interface GigabitEthernet0/0/1", " no switchport"]
    for unit, tag, address in units:
        lines.append(f"interface GigabitEthernet0/0/1.{unit}")
        if tag is not None:
            lines.append(f" encapsulation dot1Q {tag}")
        lines.append(f" ip address {address} 255.255.255.0")
    return "\n".join(lines) + "\n"


def _ios_job(text: str, port_map: dict[str, str | None] | None = None):
    return run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec(_JUNOS), text, port_rename_map=port_map or {},
    )


def test_the_bound_is_a_unit_and_one_above_it_is_not() -> None:
    job = _ios_job(_iosxe(
        ("16384", 10, "198.51.100.1"), ("16385", 11, "203.0.113.1"),
        ("016385", 12, "192.0.2.1"),
    ))
    assert job.status == MigrationJobStatus.completed, job.error
    assert {k: v for k, v in job.port_renames.items() if "." in k} == {
        "GigabitEthernet0/0/1.16384": "ge-0/0/1.16384",
        "GigabitEthernet0/0/1.16385": "ge-0/0/1.11",
        "GigabitEthernet0/0/1.016385": "ge-0/0/1.12",
    }
    assert set(_units(job.rendered)) == {
        ("ge-0/0/1", "16384"), ("ge-0/0/1", "11"), ("ge-0/0/1", "12"),
    }


def test_a_unit_above_the_bound_with_no_tag_holds_the_job() -> None:
    """It has nothing Junos can number it by: it is left as the source
    names it, and the job lists it for an entry."""
    job = _ios_job(_iosxe(("20000", None, "198.51.100.1")))
    assert job.status == MigrationJobStatus.partial
    assert job.untranslated_ports == ["GigabitEthernet0/0/1.20000"]
    assert ("ge-0/0/1", "20000") not in _units(job.rendered)


def test_a_tag_that_is_another_units_number_is_two_on_one_name() -> None:
    """The tag of unit 20000 is the number of unit 200: one name, which
    the job lists."""
    job = _ios_job(_iosxe(("20000", 200, "198.51.100.1"), ("200", 999, "203.0.113.1")))
    assert job.status == MigrationJobStatus.partial
    assert job.fused_ports == {
        "ge-0/0/1.200": ["GigabitEthernet0/0/1.20000", "GigabitEthernet0/0/1.200"],
    }


def test_an_entry_decides() -> None:
    """An entry is the operator's name, whatever its number."""
    job = _ios_job(
        _iosxe(("20000", 200, "198.51.100.1")),
        {"GigabitEthernet0/0/1.20000": "ge-0/0/1.300"},
    )
    assert job.status == MigrationJobStatus.completed, job.error
    assert _units(job.rendered)[("ge-0/0/1", "300")][0] == "vlan-id 200"


def test_between_two_configs_of_one_codec_a_unit_keeps_its_number() -> None:
    ios = get_codec("cisco_iosxe_cli")
    text = _iosxe(("20000", 200, "198.51.100.1"))
    job = run_plan_with_checked_names(ios, ios, text, port_rename_map={})
    assert job.status == MigrationJobStatus.completed, job.error
    assert "interface GigabitEthernet0/0/1.20000" in job.rendered.splitlines()


# --- a unit of two tags ------------------------------------------------------

_CARRIER = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "real" / "cisco_iosxe" / "ntc_carrier_interfaces.txt"
)

#: The capture's units, typed from its text: name -> (outer, inner).
_CARRIER_UNITS = {
    "GigabitEthernet2/0/4.223415": (2234, 15),
    "GigabitEthernet2/0/4.223427": (2234, 27),
    "GigabitEthernet2/0/4.223436": (2234, 36),
    "GigabitEthernet2/0/4.223449": (2234, 49),
    "GigabitEthernet2/0/4.223478": (2234, 1011),
    "GigabitEthernet2/0/4.22341020": (2234, 1020),
}

_TWO_TAGS = re.compile(r"^vlan-tags outer (\d+) inner (\d+)$")


def _carrier_problems(text: str) -> list[str]:
    """Each unit of the capture, read from *text*: on a unit of its
    inner tag, with both its tags, and no unit Junos does not number."""
    units = _units(text)
    problems = [
        f"unit {number} of {device}" for device, number in units if int(number) > 16384
    ]
    for outer, inner in _CARRIER_UNITS.values():
        held = [
            key for key, lines in units.items()
            if any((m := _TWO_TAGS.match(line)) and (int(m[1]), int(m[2])) == (outer, inner)
                   for line in lines)
        ]
        if held != [("ge-2/0/4", str(inner))]:
            problems.append(f"outer {outer} inner {inner}: on {held}")
    return problems


def test_a_carriers_units_are_named_by_their_inner_tag() -> None:
    text = _CARRIER.read_text(encoding="utf-8")
    tree = get_codec("cisco_iosxe_cli").parse(text)
    assert {
        i.name: (i.dot1q_vlan, i.dot1q_inner_vlan) for i in tree.interfaces
        if i.dot1q_inner_vlan is not None
    } == _CARRIER_UNITS
    job = _ios_job(text)
    assert job.status == MigrationJobStatus.completed, job.error
    assert {name: job.port_renames[name] for name in _CARRIER_UNITS} == {
        name: f"ge-2/0/4.{inner}" for name, (_outer, inner) in _CARRIER_UNITS.items()
    }
    assert _carrier_problems(job.rendered) == []


def test_two_units_with_one_inner_tag_are_one_name() -> None:
    text = (
        "hostname r1\ninterface GigabitEthernet0/0/1\n no switchport\n"
        "interface GigabitEthernet0/0/1.100010\n encapsulation dot1Q 100 second-dot1q 10\n"
        " ip address 198.51.100.1 255.255.255.0\n"
        "interface GigabitEthernet0/0/1.200010\n encapsulation dot1Q 200 second-dot1q 10\n"
        " ip address 203.0.113.1 255.255.255.0\n"
    )
    job = _ios_job(text)
    assert job.status == MigrationJobStatus.partial
    assert job.fused_ports == {
        "ge-0/0/1.10": ["GigabitEthernet0/0/1.100010", "GigabitEthernet0/0/1.200010"],
    }


def test_a_junos_unit_0_of_two_tags_is_named_by_its_inner_tag() -> None:
    text = (
        "set system host-name r1\n"
        "set interfaces ge-0/0/1 stacked-vlan-tagging\n"
        "set interfaces ge-0/0/1 unit 0 vlan-tags outer 100 inner 10\n"
        "set interfaces ge-0/0/1 unit 0 family inet address 198.51.100.1/24\n"
    )
    job = run_plan_with_checked_names(
        get_codec(_JUNOS), get_codec("arista_eos"), text, port_rename_map={},
    )
    assert job.status == MigrationJobStatus.completed, job.error
    assert job.port_renames["ge-0/0/1.0"] == "Ethernet1.10"
    assert "   encapsulation dot1q vlan 100 inner 10" in job.rendered.splitlines()


# --- with devices declared ---------------------------------------------------

_PROFILES = load_profiles_dir(LIBRARY_DIR / "target_profiles")


def test_onto_a_declared_device_the_unit_follows_by_its_tag() -> None:
    src = (
        "hostname r1\ninterface GigabitEthernet1/0/1\n no switchport\n"
        "interface GigabitEthernet1/0/1.20000\n encapsulation dot1Q 200\n"
        " ip address 198.51.100.1 255.255.255.0\n"
    )
    job = run_plan_with_models(
        get_codec("cisco_iosxe_cli"), get_codec(_JUNOS), src,
        inventory_from_profile(_PROFILES["cisco_iosxe/C9300-48P"]),
        inventory_from_profile(_PROFILES["juniper_junos/EX4300-48T"]),
    )
    plan = job.port_mapping_plan
    port = job.port_renames["GigabitEthernet1/0/1"]
    assert job.status == MigrationJobStatus.completed, job.error
    assert plan.sub_interfaces == {"GigabitEthernet1/0/1.20000": f"{port}.200"}
    assert plan.off_inventory == [] and plan.unresolved_ports == []
    assert _text_problems(job.rendered, port, "200", 200) == []


def test_onto_a_declared_device_an_untagged_one_holds_the_job() -> None:
    src = (
        "hostname r1\ninterface GigabitEthernet1/0/1\n no switchport\n"
        "interface GigabitEthernet1/0/1.20000\n"
        " ip address 198.51.100.1 255.255.255.0\n"
    )
    job = run_plan_with_models(
        get_codec("cisco_iosxe_cli"), get_codec(_JUNOS), src,
        inventory_from_profile(_PROFILES["cisco_iosxe/C9300-48P"]),
        inventory_from_profile(_PROFILES["juniper_junos/EX4300-48T"]),
    )
    assert job.status == MigrationJobStatus.partial
    assert job.port_mapping_plan.unresolved_ports == ["GigabitEthernet1/0/1.20000"]


@pytest.mark.parametrize(
    ("renames", "expected"),
    [
        ({"p1": "q7", "p1.20000": "q7.200"}, {"p1.20000": "q7.200"}),
        ({"p1": "q7", "p1.20000": "q7.20000"}, {}),
    ],
)
def test_what_followed_is_read_by_its_tag(renames, expected) -> None:
    """The model path reads the run the way the translator sends a
    unit: above the bound, by its tag."""
    plan = SimpleNamespace(off_inventory=["p1.20000"])
    job = SimpleNamespace(port_renames=renames, port_drops=[])
    assert migration_pipeline._units_that_followed(
        plan, {}, {"p1": "q7"}, job, {}, tags={"p1.20000": 200}, largest_unit=16384,
    ) == expected


# --- each check is handed the defect it is for ------------------------------


@pytest.mark.parametrize("key", ["iosxe", "eos"])
def test_the_output_with_the_units_number_is_seen(
    key: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the bound taken off Junos the translator sends the unit
    with its number, and both readings see it."""
    monkeypatch.setattr(JunosCodec, "largest_unit", None)
    job = _job(key)
    port = job.port_renames[SOURCES[key].port]
    assert _text_problems(job.rendered, port, "200", 200)
    assert _parsed_problems(job.rendered, f"{port}.200", 200)


def test_the_untagged_unit_is_seen_without_the_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """With only the tag rule (no check for a unit with no tag) the
    untagged unit is sent with its number, in a job that says
    ``completed``."""
    monkeypatch.setattr(
        "netcanon.migration.canonical.port_names.above_the_largest_unit",
        lambda unit, largest: False,
    )
    job = _ios_job(_iosxe(("20000", None, "198.51.100.1")))
    assert job.status == MigrationJobStatus.completed
    assert ("ge-0/0/1", "20000") in _units(job.rendered)


def test_the_outer_tag_is_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Named by the outer tag, the carrier's six units are one Junos
    unit, which both the job and the reader see."""
    monkeypatch.setattr(
        port_names, "unit_tags",
        lambda intent, *, named_by_tag: {
            i.name: i.dot1q_vlan for i in intent.interfaces if i.dot1q_vlan is not None
        },
    )
    job = _ios_job(_CARRIER.read_text(encoding="utf-8"))
    assert job.status == MigrationJobStatus.partial
    assert len(_carrier_problems(job.rendered)) == len(_CARRIER_UNITS)


def test_the_carrier_reader_sees_each_defect() -> None:
    good = _ios_job(_CARRIER.read_text(encoding="utf-8")).rendered
    assert _carrier_problems(good) == []
    broken = {
        "the unit's number": good.replace(" unit 15 ", " unit 223415 "),
        "the outer tag's unit": good.replace(" unit 27 ", " unit 2234 "),
        "no inner tag": good.replace(" inner 36", ""),
    }
    for what, text in broken.items():
        assert text != good, what
        assert _carrier_problems(text), what


def test_the_reader_sees_each_defect() -> None:
    job = _job("iosxe")
    port = job.port_renames["GigabitEthernet0/0/2"]
    good = job.rendered
    assert _text_problems(good, port, "200", 200) == []
    broken = {
        "the unit's number": good.replace(" unit 200 ", " unit 20000 "),
        "another unit": good.replace(" unit 200 family", " unit 201 family"),
        "no tag": good.replace(" vlan-id 200", " description x"),
        "on another port": good.replace(f"interfaces {port} ", "interfaces ge-0/0/9 "),
    }
    for what, text in broken.items():
        assert text != good, what
        assert _text_problems(text, port, "200", 200), what
