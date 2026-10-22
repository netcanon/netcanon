"""A routed sub-interface of another vendor is a VLAN interface on its port
onto FortiOS, with its own tag.

IOS-XE ``interface GigabitEthernet0/0/1.100`` with ``encapsulation dot1Q
200``, a Junos ``unit 100 vlan-id 200``: FortiOS was written ``edit
"port1.100"`` / ``set vlanid 100``, the number in the name and not the
tag, in a job that was ``partial`` for ``/interfaces/interface/dot1q-vlan``
(unsupported) -- whose reason said the tag was flagged as a drop rather
than mis-rendered.  FortiOS's own form is a VLAN interface on the port:
``set type vlan`` / ``set vlanid 200`` / ``set interface "port1"``.

What each source holds is typed by hand.  The output is read two ways:
as text, by a reader of FortiOS's grammar typed here, and with the
FortiOS parser, which reads such a block back as a VLAN interface and a
VLAN of its tag (the matrix says so: FortiOS writes a VLAN interface on a
port and on a switch interface alike).  Each check is handed the defect
it is for.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from netcanon.migration.codecs.fortigate_cli import codec as fgt_codec
from netcanon.migration.codecs.fortigate_cli import render as fgt_render
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.services.migration_pipeline import run_plan, run_plan_with_checked_names

_DOT1Q = "/interfaces/interface/dot1q-vlan"
_FGT = "fortigate_cli"


@dataclass(frozen=True)
class Sub:
    """A sub-interface as the source states it."""

    address: str
    mask: str
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
            Sub("198.51.100.1", "255.255.255.0", "100", 200, "users"),
            Sub("203.0.113.1", "255.255.255.128", "300", 301, enabled=False),
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
        (Sub("198.51.100.1", "255.255.255.0", "100", 10, "users"),),
    ),
    "eos": Source(
        "arista_eos",
        "hostname r1\n!\ninterface Ethernet2\n   no switchport\n!\n"
        "interface Ethernet2.10\n   encapsulation dot1q vlan 10\n"
        "   ip address 198.51.100.1/24\n!\n",
        "Ethernet2",
        (Sub("198.51.100.1", "255.255.255.0", "10", 10),),
    ),
    "nxos": Source(
        "cisco_nxos",
        "hostname r1\n!\ninterface Ethernet1/2\n  no switchport\n!\n"
        "interface Ethernet1/2.10\n  encapsulation dot1q 10\n"
        "  ip address 198.51.100.1/24\n!\n",
        "Ethernet1/2",
        (Sub("198.51.100.1", "255.255.255.0", "10", 10),),
    ),
    "iosxr": Source(
        "cisco_iosxr",
        "hostname r1\n!\ninterface GigabitEthernet0/0/0/2\n!\n"
        "interface GigabitEthernet0/0/0/2.10\n encapsulation dot1q 10\n"
        " ipv4 address 198.51.100.1 255.255.255.0\n!\n",
        "GigabitEthernet0/0/0/2",
        (Sub("198.51.100.1", "255.255.255.0", "10", 10),),
    ),
    "vyos": Source(
        "vyos",
        "interfaces {\n    ethernet eth2 {\n        vif 10 {\n"
        "            address 198.51.100.1/24\n        }\n    }\n}\n"
        "system {\n    host-name r1\n}\n",
        "eth2",
        (Sub("198.51.100.1", "255.255.255.0", "10", 10),),
    ),
}


# --- a reader of FortiOS's grammar, typed here ----------------------------


@dataclass
class Block:
    name: str
    sets: dict[str, list[str]]
    reviews: list[str]


def _words(rest: str) -> list[str]:
    """The values of a ``set`` line: quoted strings unquoted, the rest
    split on white space."""
    return [
        re.sub(r"\\(.)", r"\1", q) if q or not b else b
        for q, b in re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', rest)
    ]


def _blocks(text: str) -> list[Block]:
    """Each ``edit`` block of ``config system interface`` in *text*, with
    its ``set`` lines and its ``# review:`` lines.  A nested ``config``
    (``secondaryip``, ``ipv6``, ``vrrp``) is skipped to its ``end``."""
    out: list[Block] = []
    in_section = False
    depth = 0
    block: Block | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not in_section:
            in_section = line == "config system interface"
            continue
        if depth:
            if line.startswith("config "):
                depth += 1
            elif line == "end":
                depth -= 1
            continue
        if block is None:
            if line == "end":
                in_section = False
            elif line.startswith("edit "):
                block = Block(_words(line[5:])[0], {}, [])
            continue
        if line == "next":
            out.append(block)
            block = None
        elif line.startswith("config "):
            depth = 1
        elif line.startswith("# review:"):
            block.reviews.append(line)
        elif line.startswith("set "):
            key, _, rest = line[4:].partition(" ")
            block.sets[key] = _words(rest)
    return out


def _text_problems(text: str, port: str, subs: tuple[Sub, ...]) -> list[str]:
    """What the text gets wrong about *subs* on *port*: each is a VLAN
    interface ``<port>.<unit>`` on *port*, with its own tag, its address,
    its description as the alias and its admin state."""
    blocks = _blocks(text)
    problems: list[str] = []
    for sub in subs:
        name = f"{port}.{sub.unit}"
        mine = [b for b in blocks if b.name == name]
        if len(mine) != 1:
            problems.append(f"{len(mine)} blocks are {name}")
            continue
        sets = mine[0].sets
        if sets.get("type") != ["vlan"]:
            problems.append(f"{name} has type {sets.get('type')}")
        if sets.get("vlanid") != [str(sub.tag)]:
            problems.append(f"{name} has vlanid {sets.get('vlanid')}, want {sub.tag}")
        if sets.get("interface") != [port]:
            problems.append(f"{name} rides on {sets.get('interface')}, want {port}")
        if sets.get("ip") != [sub.address, sub.mask]:
            problems.append(f"{name} has ip {sets.get('ip')}")
        if sets.get("alias", [""]) != [sub.description[:25]]:
            problems.append(f"{name} has alias {sets.get('alias')}, want {sub.description!r}")
        if sets.get("status") != ["up" if sub.enabled else "down"]:
            problems.append(f"{name} has status {sets.get('status')}, want enabled={sub.enabled}")
        if mine[0].reviews:
            problems.append(f"{name} has a review line: {mine[0].reviews}")
        tagged_alike = [
            b.name for b in blocks
            if b.name != name
            and b.sets.get("vlanid") == [str(sub.tag)]
            and b.sets.get("interface") == [port]
        ]
        if tagged_alike:
            problems.append(f"{tagged_alike} have tag {sub.tag} on {port} too")
    return problems


def _parsed_problems(text: str, port: str, subs: tuple[Sub, ...]) -> list[str]:
    """What the FortiOS parser reads back: an interface ``<port>.<unit>``
    with the address, a VLAN interface on *port*, and a VLAN of the tag
    under that name -- its reading of a VLAN interface on a port."""
    tree = get_codec(_FGT).parse(text)
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
            problems.append(f"{name} is read as {iface.interface_type}")
        if iface.vlan_parent != port:
            problems.append(f"{name} is read on {iface.vlan_parent}")
        if iface.enabled != sub.enabled:
            problems.append(f"{name} is read enabled={iface.enabled}")
        if (sub.tag, name) not in {(v.id, v.name) for v in tree.vlans}:
            problems.append(f"no VLAN {sub.tag} named {name}")
    return problems


def _job(key: str, path: str, port_map: dict[str, str] | None = None):
    src = SOURCES[key]
    if path == "bare":
        return run_plan(get_codec(src.codec), get_codec(_FGT), src.text)
    return run_plan_with_checked_names(
        get_codec(src.codec), get_codec(_FGT), src.text, port_rename_map=port_map or {},
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
def test_a_sub_interface_is_a_vlan_interface_on_its_port(key: str, path: str) -> None:
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


def test_a_port_with_no_block_of_its_own_is_still_the_parent() -> None:
    """A config can state a port only by its units.  The unit's name
    still says which port it rides on, and the port is on the device."""
    text = (
        "hostname r1\n"
        "interface GigabitEthernet0/0/2.100\n encapsulation dot1Q 200\n"
        " ip address 198.51.100.1 255.255.255.0\n!\n"
    )
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec(_FGT), text, port_rename_map={},
    )
    # No record of the port: its name is the unit's, up to the unit.
    port, _, unit = job.port_renames["GigabitEthernet0/0/2.100"].rpartition(".")
    assert unit == "100"
    assert port not in {b.name for b in _blocks(job.rendered)}
    sub = (Sub("198.51.100.1", "255.255.255.0", "100", 200),)
    assert _text_problems(job.rendered, port, sub) == []


def test_a_vlan_whose_id_is_a_units_number_is_written() -> None:
    """VLAN 100 of the switch is not the unit ``.100`` tagged 200: both
    are written, each with its own id.  Read from the unit's name, the
    VLAN was taken for the unit's and left out."""
    text = (
        "hostname r1\nvlan 100\n name SERVERS\n!\n"
        "interface GigabitEthernet0/0/2\n no switchport\n!\n"
        "interface GigabitEthernet0/0/2.100\n encapsulation dot1Q 200\n"
        " ip address 198.51.100.1 255.255.255.0\n!\n"
    )
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec(_FGT), text, port_rename_map={},
    )
    port = job.port_renames["GigabitEthernet0/0/2"]
    ids = {(b.name, tuple(b.sets.get("vlanid", ()))) for b in _blocks(job.rendered)}
    assert (f"{port}.100", ("200",)) in ids
    assert ("vlan100", ("100",)) in ids


def test_a_sub_interface_whose_name_gives_no_port_says_where_it_went() -> None:
    """An entry can name a sub-interface with no port in it.  Its port is
    then not known: it rides on the parent chosen for every VLAN, under a
    review line that says so."""
    job = _job("iosxe", "plan", {"GigabitEthernet0/0/2.100": "wan10"})
    port = job.port_renames["GigabitEthernet0/0/2"]
    wan = [b for b in _blocks(job.rendered) if b.name == "wan10"]
    assert [(b.sets.get("vlanid"), b.sets.get("interface")) for b in wan] == [
        (["200"], [port]),
    ]
    assert wan[0].reviews == [
        f'# review: a routed sub-interface (tag 200) whose name gives no port; '
        f'it is written on "{port}" -- move it to its port',
    ]
    # The other unit keeps its port.
    assert _text_problems(job.rendered, port, SOURCES["iosxe"].subs[1:]) == []


def test_a_sub_interface_is_no_vlans_parent() -> None:
    """A sub-interface named with no unit in it is still no port: a VLAN
    interface whose parent is chosen is not put on it, though it holds
    the private address the chooser looks for."""
    text = (
        "hostname r1\nvlan 30\n!\n"
        "interface GigabitEthernet0/0/2\n no switchport\n!\n"
        "interface GigabitEthernet0/0/2.100\n encapsulation dot1Q 200\n"
        " ip address 10.0.0.1 255.255.255.0\n!\n"
        "interface Vlan30\n ip address 198.51.100.1 255.255.255.0\n!\n"
    )
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec(_FGT), text,
        port_rename_map={"GigabitEthernet0/0/2.100": "wan10"},
    )
    rides = {b.name: b.sets.get("interface") for b in _blocks(job.rendered)}
    assert rides["wan10"] == [job.port_renames["GigabitEthernet0/0/2"]]
    assert [name for name, on in rides.items() if on == ["wan10"]] == []


# --- a VLAN id twice on one parent ----------------------------------------
#
# A FortiGate takes a VLAN id once on an interface (Fortinet, "Rules about
# VLAN configuration and VDOM interface assignment").  With each
# sub-interface's own tag, two of them can say the same one on a port --
# or a VLAN interface whose parent is chosen can land on a port a
# sub-interface tags with its id -- and the output says so under the
# second block.


def _repeat_problems(text: str) -> list[str]:
    """Each block of *text* whose review lines of a repeated VLAN id are
    not the one line its place calls for: the line under every block
    whose VLAN id is on its parent in a block before it, and under no
    other block."""
    first: dict[tuple[str, str], str] = {}
    problems = []
    for block in _blocks(text):
        on, vid = block.sets.get("interface"), block.sets.get("vlanid")
        said = [r for r in block.reviews if "a FortiGate takes a VLAN id once" in r]
        want: list[str] = []
        if on and vid:
            seen = first.setdefault((on[0], vid[0]), block.name)
            if seen != block.name:
                want = [
                    f'# review: VLAN {vid[0]} is on "{on[0]}" already ("{seen}"); '
                    f"a FortiGate takes a VLAN id once on an interface",
                ]
        if said != want:
            problems.append(f"{block.name}: says {said}, want {want}")
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
        get_codec("cisco_iosxe_cli"), get_codec(_FGT), _TWICE, port_rename_map={},
    )


def test_a_vlan_id_twice_on_one_port_is_said() -> None:
    """Two units of one port tagged 200: the second is written under a
    line that names the first.  A unit of another port tagged 200 is
    another VLAN, and has none."""
    job = _twice()
    names = job.port_renames
    blocks = {b.name: b for b in _blocks(job.rendered)}
    second = blocks[names["GigabitEthernet0/0/2.300"]]
    port = names["GigabitEthernet0/0/2"]
    assert second.reviews == [
        f'# review: VLAN 200 is on "{port}" already '
        f'("{names["GigabitEthernet0/0/2.100"]}"); '
        f"a FortiGate takes a VLAN id once on an interface",
    ]
    assert blocks[names["GigabitEthernet0/0/2.100"]].reviews == []
    assert blocks[names["GigabitEthernet0/0/3.200"]].reviews == []
    assert _repeat_problems(job.rendered) == []


def test_a_vlan_interface_on_a_port_a_sub_interface_tags_is_said() -> None:
    """The parent of a VLAN interface of another vendor is chosen, and
    can be a port a sub-interface tags with the same id."""
    text = (
        "hostname r1\nvlan 200\n name SWITCHVLAN\n!\n"
        "interface GigabitEthernet0/0/1\n no ip address\n!\n"
        "interface GigabitEthernet0/0/1.100\n encapsulation dot1Q 200\n"
        " ip address 198.51.100.1 255.255.255.0\n!\n"
        "interface Vlan200\n ip address 203.0.113.1 255.255.255.0\n!\n"
    )
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec(_FGT), text, port_rename_map={},
    )
    blocks = {b.name: b for b in _blocks(job.rendered)}
    port = job.port_renames["GigabitEthernet0/0/1"]
    vlan = blocks[job.port_renames["Vlan200"]]
    # The chooser puts it on the one port with an address under it.
    assert vlan.sets.get("interface") == [port]
    assert len(vlan.reviews) == 1
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


#: The captures whose output onto FortiOS has a VLAN id twice on one
#: parent, and how many blocks repeat one.  The IOS-XE carrier capture's
#: six Q-in-Q units of `GigabitEthernet2/0/4` are read with their outer
#: tag alone (2234), so five of them repeat the first.
_REPEATS = {"ntc_carrier_interfaces.txt": 5}


def test_every_capture_says_each_repeat() -> None:
    target = get_codec(_FGT)
    repeats = {}
    for codec, path in _captures():
        text = path.read_text(encoding="utf-8", errors="replace")
        job = run_plan_with_checked_names(get_codec(codec), target, text, port_rename_map={})
        if not job.rendered:
            continue
        assert _repeat_problems(job.rendered) == [], path.name
        said = job.rendered.count("a FortiGate takes a VLAN id once")
        if said:
            repeats[path.name] = said
    assert repeats == _REPEATS


def test_a_repeat_with_no_line_or_a_line_for_none_is_seen() -> None:
    job = _twice()
    good = job.rendered
    lines = good.splitlines(keepends=True)
    without = "".join(line for line in lines if "takes a VLAN id once" not in line)
    assert _repeat_problems(without)
    said = next(line for line in lines if "takes a VLAN id once" in line)
    first = f'    edit "{job.port_renames["GigabitEthernet0/0/2.100"]}"\n'
    assert first in good
    assert _repeat_problems(good.replace(first, first + said))


# --- each check is handed the defect it is for ----------------------------


def _as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renderer as it was: a tree whose sub-interfaces it does not see."""
    real = fgt_codec.render_intent

    def render(tree):
        tree = copy.deepcopy(tree)
        for iface in tree.interfaces:
            iface.dot1q_vlan = None
        return real(tree)

    monkeypatch.setattr(fgt_codec, "render_intent", render)


def test_the_output_with_the_units_number_is_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    _as_before(monkeypatch)
    job = _job("iosxe", "plan")
    port = _port("iosxe", "plan", job)
    problems = _text_problems(job.rendered, port, SOURCES["iosxe"].subs)
    assert any("has vlanid ['100'], want 200" in p for p in problems), problems
    assert _parsed_problems(job.rendered, port, SOURCES["iosxe"].subs)


@pytest.mark.parametrize("key", ["junos", "iosxr"])
def test_the_output_on_another_parent_is_seen(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Handed a renderer that does not find a unit's port, the text
    reader sees the review line the chosen parent is written under."""
    monkeypatch.setattr(fgt_render, "_port_of_unit", lambda name: None)
    job = _job(key, "plan")
    port = _port(key, "plan", job)
    problems = _text_problems(job.rendered, port, SOURCES[key].subs)
    assert any("review line" in p for p in problems), problems


_GOOD = (
    "config system interface\n"
    '    edit "port2"\n'
    "        set status up\n"
    "    next\n"
    '    edit "port2.100"\n'
    '        set alias "users"\n'
    "        set type vlan\n"
    "        set vlanid 200\n"
    '        set interface "port2"\n'
    "        set ip 198.51.100.1 255.255.255.0\n"
    "        set mode static\n"
    "        set status up\n"
    "    next\n"
    "end\n"
)


@pytest.mark.parametrize(("broken", "said"), [
    (_GOOD.replace("set vlanid 200", "set vlanid 100"), "has vlanid ['100']"),
    (_GOOD.replace('        set alias "users"\n', ""), "has alias None"),
    (_GOOD.replace("        set status up\n    next\nend", "        set status down\n    next\nend"),
     "has status ['down']"),
    (_GOOD.replace('set interface "port2"', 'set interface "port1"'), "rides on ['port1']"),
    (_GOOD.replace("        set type vlan\n", ""), "has type None"),
    (_GOOD.replace("        set vlanid 200\n", "        set vlanid 200\n        # review: put somewhere\n"),
     "review line"),
    (_GOOD.replace("198.51.100.1 255.255.255.0", "198.51.100.1 255.255.255.128"), "has ip"),
    (_GOOD.replace('    edit "port2.100"', '    edit "port2.200"'), "0 blocks are port2.100"),
    (_GOOD.replace("end\n", '    edit "x"\n        set vlanid 200\n        set interface "port2"\n    next\nend\n'),
     "have tag 200 on port2 too"),
])
def test_the_reader_sees_each_defect(broken: str, said: str) -> None:
    sub = (Sub("198.51.100.1", "255.255.255.0", "100", 200, "users"),)
    assert _text_problems(_GOOD, "port2", sub) == []
    assert any(said in p for p in _text_problems(broken, "port2", sub)), _text_problems(broken, "port2", sub)


def test_the_reader_skips_a_nested_config() -> None:
    """A ``config secondaryip`` inside a block is not the block's end."""
    text = _GOOD.replace(
        "        set mode static\n",
        "        set mode static\n        config secondaryip\n            edit 1\n"
        "                set ip 192.0.2.1 255.255.255.0\n            next\n        end\n",
    )
    sub = (Sub("198.51.100.1", "255.255.255.0", "100", 200, "users"),)
    assert _text_problems(text, "port2", sub) == []
