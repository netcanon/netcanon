"""A routed sub-interface of another vendor is a VLAN device on its port
onto OPNsense, with its own tag.

IOS-XE ``interface GigabitEthernet0/0/1.100`` with ``encapsulation dot1Q
200``, a Junos ``unit 100 vlan-id 200``: OPNsense was written a zone whose
``<if>`` was ``igb1.100`` and no ``<vlan>``, so the zone assigned a device
the output did not have and the tag was nowhere, in a job that was
``partial`` for ``/interfaces/interface/dot1q-vlan`` (unsupported).
OPNsense's own form is a VLAN device (core ``Vlan.xml``): a ``<vlan>``
with ``<if>`` the port, ``<tag>`` and ``<vlanif>`` the device's name, which
the zone's ``<if>`` assigns.

What each source holds is typed by hand.  The output is read two ways:
as XML, by a reader typed here, and with the OPNsense parser, which reads
such a device back as a VLAN device and a VLAN of its tag (the matrix
says so).  Each check is handed the defect it is for.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from netcanon.migration.codecs.opnsense import codec as opn_codec
from netcanon.migration.codecs.opnsense import render as opn_render
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.services.migration_pipeline import run_plan, run_plan_with_checked_names

_DOT1Q = "/interfaces/interface/dot1q-vlan"
_OPN = "opnsense"


@dataclass(frozen=True)
class Sub:
    """A sub-interface as the source states it."""

    address: str
    prefix: int
    unit: str
    tag: int
    description: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class Source:
    codec: str
    text: str
    port: str  # the source's name for the port the units are on
    subs: tuple[Sub, ...]


SOURCES = {
    "iosxe": Source(
        "cisco_iosxe_cli",
        # Neither unit is its tag.
        "hostname r1\n"
        "interface GigabitEthernet0/0/2\n no switchport\n!\n"
        "interface GigabitEthernet0/0/2.100\n description users\n"
        " encapsulation dot1Q 200\n ip address 198.51.100.1 255.255.255.0\n!\n"
        "interface GigabitEthernet0/0/2.300\n encapsulation dot1Q 301\n shutdown\n"
        " ip address 203.0.113.1 255.255.255.128\n!\n",
        "GigabitEthernet0/0/2",
        (
            Sub("198.51.100.1", 24, "100", 200, "users"),
            Sub("203.0.113.1", 25, "300", 301, enabled=False),
        ),
    ),
    "junos": Source(
        "juniper_junos",
        "set system host-name r1\n"
        "set interfaces ge-0/0/2 vlan-tagging\n"
        "set interfaces ge-0/0/2 unit 100 description users\n"
        "set interfaces ge-0/0/2 unit 100 vlan-id 10\n"
        "set interfaces ge-0/0/2 unit 100 family inet address 198.51.100.1/24\n",
        "ge-0/0/2",
        (Sub("198.51.100.1", 24, "100", 10, "users"),),
    ),
    "eos": Source(
        "arista_eos",
        "hostname r1\n!\ninterface Ethernet2\n   no switchport\n!\n"
        "interface Ethernet2.10\n   encapsulation dot1q vlan 10\n"
        "   ip address 198.51.100.1/24\n!\n",
        "Ethernet2",
        (Sub("198.51.100.1", 24, "10", 10),),
    ),
    "nxos": Source(
        "cisco_nxos",
        "hostname r1\n!\ninterface Ethernet1/2\n  no switchport\n!\n"
        "interface Ethernet1/2.10\n  encapsulation dot1q 10\n"
        "  ip address 198.51.100.1/24\n!\n",
        "Ethernet1/2",
        (Sub("198.51.100.1", 24, "10", 10),),
    ),
    "iosxr": Source(
        "cisco_iosxr",
        "hostname r1\n!\ninterface GigabitEthernet0/0/0/2\n!\n"
        "interface GigabitEthernet0/0/0/2.10\n encapsulation dot1q 10\n"
        " ipv4 address 198.51.100.1 255.255.255.0\n!\n",
        "GigabitEthernet0/0/0/2",
        (Sub("198.51.100.1", 24, "10", 10),),
    ),
    "vyos": Source(
        "vyos",
        "interfaces {\n    ethernet eth2 {\n        vif 10 {\n"
        "            address 198.51.100.1/24\n        }\n    }\n}\n"
        "system {\n    host-name r1\n}\n",
        "eth2",
        (Sub("198.51.100.1", 24, "10", 10),),
    ),
}


# --- a reader of OPNsense's config.xml, typed here ------------------------


@dataclass
class Device:
    """A ``<vlan>`` of ``<vlans>``: what it says, and its comments."""

    parent: str
    tag: str
    pcp: str
    proto: str
    name: str
    comments: list[str]


@dataclass
class Zone:
    """A zone of ``<interfaces>``: the device it assigns and what it gives
    the device."""

    device: str
    descr: str
    enabled: bool
    address: str
    subnet: str


def _root(text: str) -> ET.Element:
    """*text* as XML, its comments kept."""
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    return ET.fromstring(text, parser=parser)


def _text(element: ET.Element, tag: str) -> str:
    return (element.findtext(tag) or "").strip()


def _devices(text: str) -> list[Device]:
    out = []
    for vlan in _root(text).iterfind("vlans/vlan"):
        comments = [
            (child.text or "").strip() for child in vlan
            if child.tag is ET.Comment
        ]
        out.append(Device(
            _text(vlan, "if"), _text(vlan, "tag"), _text(vlan, "pcp"),
            _text(vlan, "proto"), _text(vlan, "vlanif"), comments,
        ))
    return out


def _zones(text: str) -> list[Zone]:
    interfaces = _root(text).find("interfaces")
    if interfaces is None:
        return []
    return [
        Zone(
            _text(zone, "if"), _text(zone, "descr"),
            zone.find("enable") is not None,
            _text(zone, "ipaddr"), _text(zone, "subnet"),
        )
        for zone in interfaces
        if zone.tag is not ET.Comment
    ]


def _name_review(name: str, port: str, tag: int) -> str:
    """The review comment OPNsense's VLAN form calls for under a device
    *name* it refuses (``Vlan.php``: ``<parent>_vlan<tag>``, or ``vlan0``
    and digits and dots)."""
    return (
        f"review: OPNsense's VLAN form refuses the device name {name} when "
        f"this VLAN is saved; it takes vlan0 followed by digits and dots, "
        f"or {port}_vlan{tag}"
    )


def _text_problems(text: str, port: str, subs: tuple[Sub, ...]) -> list[str]:
    """What the XML gets wrong about *subs* on *port*: each is a VLAN
    device ``<port>.<unit>`` on *port* with its own tag, and a zone that
    assigns it with its address, its description and its admin state."""
    devices, zones = _devices(text), _zones(text)
    problems: list[str] = []
    for sub in subs:
        name = f"{port}.{sub.unit}"
        mine = [d for d in devices if d.name == name]
        if len(mine) != 1:
            problems.append(f"{len(mine)} <vlan> are {name}")
        else:
            device = mine[0]
            if device.parent != port:
                problems.append(f"{name} rides on {device.parent!r}, want {port}")
            if device.tag != str(sub.tag):
                problems.append(f"{name} has tag {device.tag!r}, want {sub.tag}")
            if device.pcp != "0":
                problems.append(f"{name} has pcp {device.pcp!r}")
            if device.proto not in ("", "802.1q"):
                problems.append(f"{name} has proto {device.proto!r}")
            # A name with a dot is not one the form takes, and the device
            # says so; nothing else is to be said of it.
            if device.comments != [_name_review(name, port, sub.tag)]:
                problems.append(f"{name} has review comments {device.comments}")
            alike = [
                d.name for d in devices
                if d.name != name and d.parent == port and d.tag == str(sub.tag)
            ]
            if alike:
                problems.append(f"{alike} have tag {sub.tag} on {port} too")
        assigned = [z for z in zones if z.device == name]
        if len(assigned) != 1:
            problems.append(f"{len(assigned)} zones assign {name}")
            continue
        zone = assigned[0]
        if (zone.address, zone.subnet) != (sub.address, str(sub.prefix)):
            problems.append(f"the zone of {name} has {zone.address}/{zone.subnet}")
        if zone.descr != sub.description:
            problems.append(f"the zone of {name} has descr {zone.descr!r}, want {sub.description!r}")
        if zone.enabled != sub.enabled:
            problems.append(f"the zone of {name} has enabled={zone.enabled}")
    return problems


def _parsed_problems(text: str, port: str, subs: tuple[Sub, ...]) -> list[str]:
    """What the OPNsense parser reads back: an interface ``<port>.<unit>``
    with the address, a VLAN device on *port*, and a VLAN of the tag under
    that name -- its reading of a ``<vlan>``."""
    tree = get_codec(_OPN).parse(text)
    by_name = {i.name: i for i in tree.interfaces}
    problems: list[str] = []
    for sub in subs:
        name = f"{port}.{sub.unit}"
        iface = by_name.get(name)
        if iface is None:
            problems.append(f"the parser reads no {name}")
            continue
        if [a.ip for a in iface.ipv4_addresses] != [sub.address]:
            problems.append(f"{name} holds {[a.ip for a in iface.ipv4_addresses]}")
        if iface.interface_type != "ianaift:l3ipvlan":
            problems.append(f"{name} is read as {iface.interface_type!r}")
        if iface.vlan_parent != port:
            problems.append(f"{name} is read on {iface.vlan_parent}")
        if iface.enabled != sub.enabled:
            problems.append(f"{name} is read enabled={iface.enabled}")
        if (sub.tag, name) not in {(v.id, v.name) for v in tree.vlans}:
            problems.append(f"no VLAN {sub.tag} named {name}")
    return problems


def _job(key: str, path: str, port_map: dict[str, str | None] | None = None):
    src = SOURCES[key]
    if path == "bare":
        return run_plan(get_codec(src.codec), get_codec(_OPN), src.text)
    return run_plan_with_checked_names(
        get_codec(src.codec), get_codec(_OPN), src.text, port_rename_map=port_map or {},
    )


def _port(key: str, path: str, job) -> str:
    """The port's name in the output: the source's on the bare path, which
    translates no name; the translator's on the plan path."""
    port = SOURCES[key].port
    return port if path == "bare" else job.port_renames[port]


# --- the source trees are what is typed here ------------------------------


@pytest.mark.parametrize("key", sorted(SOURCES))
def test_each_source_holds_its_sub_interfaces(key: str) -> None:
    src = SOURCES[key]
    tree = get_codec(src.codec).parse(src.text)
    held = {(i.name, i.dot1q_vlan) for i in tree.interfaces if i.dot1q_vlan is not None}
    assert held == {(f"{src.port}.{s.unit}", s.tag) for s in src.subs}


# --- the output -----------------------------------------------------------


@pytest.mark.parametrize("path", ["plan", "bare"])
@pytest.mark.parametrize("key", sorted(SOURCES))
def test_a_sub_interface_is_a_vlan_device_on_its_port(key: str, path: str) -> None:
    job = _job(key, path)
    port = _port(key, path, job)
    assert _text_problems(job.rendered, port, SOURCES[key].subs) == []
    assert _parsed_problems(job.rendered, port, SOURCES[key].subs) == []


@pytest.mark.parametrize("key", sorted(SOURCES))
def test_the_job_says_how_it_is_read_back(key: str) -> None:
    """The output is what the device runs as the sub-interface; the
    report says it is read back otherwise, and nothing holds the job."""
    job = _job(key, "plan")
    assert job.status.value == "completed", job.error
    assert _DOT1Q in {p.path for p in job.validation.lossy_paths}
    assert _DOT1Q not in {p.path for p in job.validation.unsupported_paths}


def test_a_port_with_no_zone_of_its_own_is_still_the_parent() -> None:
    """A config can state a port only by its units.  The unit's name
    still says which port it rides on, and the port is on the device."""
    text = (
        "hostname r1\n"
        "interface GigabitEthernet0/0/2.100\n encapsulation dot1Q 200\n"
        " ip address 198.51.100.1 255.255.255.0\n!\n"
    )
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec(_OPN), text, port_rename_map={},
    )
    # No record of the port: its name is the unit's, up to the unit.
    port, _, unit = job.port_renames["GigabitEthernet0/0/2.100"].rpartition(".")
    assert unit == "100"
    assert port not in {z.device for z in _zones(job.rendered)}
    assert _text_problems(job.rendered, port, (Sub("198.51.100.1", 24, "100", 200),)) == []


def test_a_sub_interface_that_holds_nothing_is_a_device_and_no_zone() -> None:
    """A zone assigns a device only to give it something; a unit with a
    tag and nothing else is a device in <vlans> alone, as a VLAN
    interface of the same kind is, and the parser makes a record of it."""
    text = (
        "hostname r1\n"
        "interface GigabitEthernet0/0/2\n no switchport\n!\n"
        "interface GigabitEthernet0/0/2.100\n encapsulation dot1Q 200\n!\n"
    )
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec(_OPN), text, port_rename_map={},
    )
    name = job.port_renames["GigabitEthernet0/0/2.100"]
    port = job.port_renames["GigabitEthernet0/0/2"]
    assert name not in {z.device for z in _zones(job.rendered)}
    assert [(d.parent, d.tag) for d in _devices(job.rendered) if d.name == name] == [(port, "200")]
    back = {i.name: i for i in get_codec(_OPN).parse(job.rendered).interfaces}
    assert back[name].vlan_parent == port


def test_a_vlan_whose_id_is_a_units_number_is_written() -> None:
    """VLAN 100 of the switch is not the unit ``.100`` tagged 200: both
    are written, each with its own tag."""
    text = (
        "hostname r1\nvlan 100\n name SERVERS\n!\n"
        "interface GigabitEthernet0/0/2\n no switchport\n!\n"
        "interface GigabitEthernet0/0/2.100\n encapsulation dot1Q 200\n"
        " ip address 198.51.100.1 255.255.255.0\n!\n"
    )
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec(_OPN), text, port_rename_map={},
    )
    port = job.port_renames["GigabitEthernet0/0/2"]
    tags = {(d.name, d.tag) for d in _devices(job.rendered)}
    assert (f"{port}.100", "200") in tags
    assert [name for name, tag in tags if tag == "100"] == [f"{port}_vlan100"], tags


def test_a_vlan_made_of_the_tag_is_the_sub_interfaces() -> None:
    """The IOS XR parser makes a VLAN record of each sub-interface's tag.
    That VLAN is the sub-interface's own device, not a second device of
    the tag on another parent."""
    job = _job("iosxr", "plan")
    port = _port("iosxr", "plan", job)
    assert [(d.name, d.parent, d.tag) for d in _devices(job.rendered)] == [
        (f"{port}.10", port, "10"),
    ]


def test_a_sub_interface_whose_name_gives_no_port_says_where_it_went() -> None:
    """An entry can name a sub-interface with no port in it.  Its port is
    then not known: it rides on the parent chosen for every VLAN, under a
    review comment that says so."""
    job = _job("iosxe", "plan", {"GigabitEthernet0/0/2.100": "wan10"})
    port = job.port_renames["GigabitEthernet0/0/2"]
    wan = [d for d in _devices(job.rendered) if d.name == "wan10"]
    assert [(d.parent, d.tag) for d in wan] == [(port, "200")]
    assert wan[0].comments[-1] == (
        f"review: a routed sub-interface (tag 200) whose name gives no port; "
        f"it is written on {port}, move it to its port"
    )
    # The other unit keeps its port.
    assert _text_problems(job.rendered, port, SOURCES["iosxe"].subs[1:]) == []


def test_a_sub_interface_is_no_vlans_parent() -> None:
    """A sub-interface that comes first is still no port: the VLAN
    interface whose parent is chosen is not put on it."""
    text = (
        "hostname r1\nvlan 30\n!\n"
        "interface GigabitEthernet0/0/2.100\n encapsulation dot1Q 200\n"
        " ip address 10.0.0.1 255.255.255.0\n!\n"
        "interface GigabitEthernet0/0/2\n no switchport\n!\n"
        "interface Vlan30\n ip address 198.51.100.1 255.255.255.0\n!\n"
    )
    for port_map in ({}, {"GigabitEthernet0/0/2.100": "wan10"}):
        job = run_plan_with_checked_names(
            get_codec("cisco_iosxe_cli"), get_codec(_OPN), text, port_rename_map=port_map,
        )
        sub = job.port_renames["GigabitEthernet0/0/2.100"]
        parents = {d.name: d.parent for d in _devices(job.rendered)}
        assert parents[sub] == job.port_renames["GigabitEthernet0/0/2"]
        assert [name for name, on in parents.items() if on == sub] == [], port_map


# --- a tag twice on one parent --------------------------------------------
#
# OPNsense keeps one VLAN device for a tag on a parent (``Vlan.xml``: the
# tag is unique with <if>).  With each sub-interface's own tag, two of them
# can say the same one on a port, and the output says so in the second.


def _repeat_problems(text: str, vlan_only: tuple[tuple[str, str], ...] = ()) -> list[str]:
    """Each ``<vlan>`` of *text* whose review comments of a repeated tag
    are not the one its place calls for: the comment in every device
    whose tag is on its parent in a ``<vlan>`` before it, and in no other."""
    first: dict[tuple[str, str], str] = {}
    problems = []
    for device in _devices(text):
        said = [c for c in device.comments if "keeps one VLAN device" in c]
        want: list[str] = []
        seen = first.setdefault((device.parent, device.tag), device.name)
        if seen != device.name:
            want = [
                f"review: VLAN {device.tag} is on {device.parent} already "
                f"({seen}); OPNsense keeps one VLAN device for a tag on a parent",
            ]
        if said != want:
            problems.append(f"{device.name}: says {said}, want {want}")
    return problems


_TWICE = (
    "hostname r1\n"
    "interface GigabitEthernet0/0/2\n no switchport\n!\n"
    "interface GigabitEthernet0/0/2.100\n encapsulation dot1Q 200\n"
    " ip address 198.51.100.1 255.255.255.0\n!\n"
    "interface GigabitEthernet0/0/2.300\n encapsulation dot1Q 200\n"
    " ip address 203.0.113.1 255.255.255.0\n!\n"
    "interface GigabitEthernet0/0/3\n no switchport\n!\n"
    "interface GigabitEthernet0/0/3.200\n encapsulation dot1Q 200\n"
    " ip address 192.0.2.1 255.255.255.0\n!\n"
)


def _twice():
    return run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec(_OPN), _TWICE, port_rename_map={},
    )


def test_a_tag_twice_on_one_port_is_said() -> None:
    """Two units of one port tagged 200: the second is written with a
    comment that names the first.  A unit of another port tagged 200 is
    another VLAN, and has none."""
    job = _twice()
    names = job.port_renames
    devices = {d.name: d for d in _devices(job.rendered)}
    port = names["GigabitEthernet0/0/2"]
    first, second = names["GigabitEthernet0/0/2.100"], names["GigabitEthernet0/0/2.300"]
    assert devices[second].comments[-1] == (
        f"review: VLAN 200 is on {port} already ({first}); "
        f"OPNsense keeps one VLAN device for a tag on a parent"
    )
    assert len(devices[first].comments) == 1
    assert len(devices[names["GigabitEthernet0/0/3.200"]].comments) == 1
    assert _repeat_problems(job.rendered) == []


def test_a_sub_interface_on_a_vlan_written_with_no_device_is_said() -> None:
    """A switch VLAN no interface is for is written as a device of its
    own on what carries it; a sub-interface of the same tag on that port
    is the second there."""
    text = (
        "hostname r1\nvlan 200\n name SWITCHVLAN\n!\nvlan 201\n!\n"
        "interface GigabitEthernet0/0/1\n switchport mode trunk\n"
        " switchport trunk allowed vlan 200,201\n!\n"
        "interface GigabitEthernet0/0/2\n no switchport\n!\n"
        "interface GigabitEthernet0/0/2.100\n encapsulation dot1Q 201\n"
        " ip address 198.51.100.1 255.255.255.0\n!\n"
        "interface GigabitEthernet0/0/1.100\n encapsulation dot1Q 200\n"
        " ip address 203.0.113.1 255.255.255.0\n!\n"
    )
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec(_OPN), text, port_rename_map={},
    )
    assert _repeat_problems(job.rendered) == []


def _captures() -> list[tuple[str, Path]]:
    found = []
    for directory in sorted((Path(__file__).resolve().parents[2] / "fixtures" / "real").iterdir()):
        codec = DIR_TO_CODEC_NAME.get(directory.name)
        if codec is None or not directory.is_dir():
            continue
        found.extend(
            (codec, path) for path in sorted(directory.iterdir())
            if path.is_file()
            and path.suffix.lower() in {".txt", ".cfg", ".xml", ".conf", ".rsc", ".set"}
        )
    return found


#: The captures whose output onto OPNsense has a tag twice on one parent,
#: and how many devices repeat one.  The IOS-XE carrier capture's six
#: Q-in-Q units of `GigabitEthernet2/0/4` are written with their outer
#: tag (2234), the inner one a drop, so five of them repeat the first.
_REPEATS = {"ntc_carrier_interfaces.txt": 5}


def test_every_capture_says_each_repeat() -> None:
    target = get_codec(_OPN)
    repeats = {}
    for codec, path in _captures():
        text = path.read_text(encoding="utf-8", errors="replace")
        job = run_plan_with_checked_names(get_codec(codec), target, text, port_rename_map={})
        if not job.rendered:
            continue
        assert _repeat_problems(job.rendered) == [], path.name
        said = job.rendered.count("keeps one VLAN device for a tag")
        if said:
            repeats[path.name] = said
    assert repeats == _REPEATS


def test_a_repeat_with_no_comment_or_a_comment_for_none_is_seen() -> None:
    job = _twice()
    good = job.rendered
    lines = good.splitlines(keepends=True)
    without = "".join(line for line in lines if "keeps one VLAN device" not in line)
    assert _repeat_problems(without)
    said = next(line for line in lines if "keeps one VLAN device" in line)
    first = f"      <vlanif>{job.port_renames['GigabitEthernet0/0/2.100']}</vlanif>\n"
    assert first in good
    assert _repeat_problems(good.replace(first, first + said))


# --- each check is handed the defect it is for ----------------------------


def test_the_output_as_it_was_is_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renderer as it was: a tree whose sub-interfaces it does not
    see.  The zone is written and no device."""
    real = opn_codec.render_intent

    def render(tree, *args, **kwargs):
        tree = copy.deepcopy(tree)
        for iface in tree.interfaces:
            iface.dot1q_vlan = None
        return real(tree, *args, **kwargs)

    monkeypatch.setattr(opn_codec, "render_intent", render)
    job = _job("iosxe", "plan")
    port = _port("iosxe", "plan", job)
    problems = _text_problems(job.rendered, port, SOURCES["iosxe"].subs)
    assert any("0 <vlan> are" in p for p in problems), problems
    assert _parsed_problems(job.rendered, port, SOURCES["iosxe"].subs)


def test_the_output_on_another_parent_is_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Handed a renderer that does not find a unit's port, the reader sees
    the review comment the chosen parent is written with."""
    monkeypatch.setattr(opn_render, "_port_of_unit", lambda name: None)
    job = _job("iosxe", "plan")
    port = _port("iosxe", "plan", job)
    problems = _text_problems(job.rendered, port, SOURCES["iosxe"].subs)
    assert any("review comments" in p for p in problems), problems


_GOOD = (
    "<opnsense>\n"
    "  <interfaces>\n"
    "    <igb2>\n      <if>igb2</if>\n      <enable/>\n    </igb2>\n"
    "    <igb2_100>\n      <if>igb2.100</if>\n      <descr>users</descr>\n"
    "      <enable/>\n      <ipaddr>198.51.100.1</ipaddr>\n"
    "      <subnet>24</subnet>\n    </igb2_100>\n"
    "  </interfaces>\n"
    "  <vlans>\n"
    "    <vlan>\n      <if>igb2</if>\n      <tag>200</tag>\n      <pcp>0</pcp>\n"
    "      <proto/>\n      <vlanif>igb2.100</vlanif>\n"
    "      <!-- review: OPNsense's VLAN form refuses the device name igb2.100 "
    "when this VLAN is saved; it takes vlan0 followed by digits and dots, "
    "or igb2_vlan200 -->\n"
    "    </vlan>\n"
    "  </vlans>\n"
    "</opnsense>\n"
)


@pytest.mark.parametrize(("broken", "said"), [
    (_GOOD.replace("<tag>200</tag>", "<tag>100</tag>"), "has tag '100'"),
    (_GOOD.replace("      <if>igb2</if>\n      <tag>", "      <if>igb1</if>\n      <tag>"),
     "rides on 'igb1'"),
    (_GOOD.replace("<pcp>0</pcp>", "<pcp>3</pcp>"), "has pcp '3'"),
    (_GOOD.replace("<proto/>", "<proto>802.1ad</proto>"), "has proto '802.1ad'"),
    (_GOOD.replace("<vlanif>igb2.100</vlanif>", "<vlanif>igb2.200</vlanif>"), "0 <vlan> are igb2.100"),
    (_GOOD.replace("    </vlan>\n", "      <!-- review: put somewhere -->\n    </vlan>\n"),
     "has review comments"),
    (_GOOD.replace("<if>igb2.100</if>", "<if>igb2.101</if>"), "0 zones assign igb2.100"),
    (_GOOD.replace("<subnet>24</subnet>", "<subnet>25</subnet>"), "has 198.51.100.1/25"),
    (_GOOD.replace("<descr>users</descr>", ""), "has descr ''"),
    (_GOOD.replace("      <enable/>\n      <ipaddr>", "      <ipaddr>"), "has enabled=False"),
    (_GOOD.replace("  </vlans>", "    <vlan>\n      <if>igb2</if>\n      <tag>200</tag>\n"
                   "      <vlanif>vlan0.1</vlanif>\n    </vlan>\n  </vlans>"),
     "have tag 200 on igb2 too"),
])
def test_the_reader_sees_each_defect(broken: str, said: str) -> None:
    sub = (Sub("198.51.100.1", 24, "100", 200, "users"),)
    assert _text_problems(_GOOD, "igb2", sub) == []
    found = _text_problems(broken, "igb2", sub)
    assert any(said in p for p in found), found


def test_the_parsed_reading_sees_a_device_on_another_parent() -> None:
    sub = (Sub("198.51.100.1", 24, "100", 200, "users"),)
    assert _parsed_problems(_GOOD, "igb2", sub) == []
    broken = _GOOD.replace("      <if>igb2</if>\n      <tag>", "      <if>igb1</if>\n      <tag>")
    assert any("is read on igb1" in p for p in _parsed_problems(broken, "igb2", sub))
