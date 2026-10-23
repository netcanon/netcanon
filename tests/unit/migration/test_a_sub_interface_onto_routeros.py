"""A routed sub-interface of another vendor is a VLAN interface on its port
onto RouterOS.

IOS-XE ``interface GigabitEthernet1/0/2.10`` with ``encapsulation dot1Q
10``, a Junos ``unit 10 vlan-id 10``, an EOS ``Ethernet2.10``: RouterOS
was written the address on ``ether2.10`` and nothing that defines that
interface, in a job that was ``partial`` for it.  RouterOS's own form is
a VLAN interface on the port: ``/interface vlan add interface=ether2
name=ether2.10 vlan-id=10``.

What each source holds is typed by hand.  The output is read two ways:
as text, by a reader of RouterOS's grammar typed here, and with the
RouterOS parser, which reads such a line back as a sub-interface of the
port: typed as the port, with the tag its own, and no VLAN (one on a
bridge is the VLAN interface it reads as a VLAN interface and a VLAN of
its tag).  Each check is handed the defect it is for.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass

import pytest

from netcanon.migration.codecs.mikrotik_routeros import codec as ros_codec
from netcanon.migration.codecs.mikrotik_routeros import render as ros_render
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan, run_plan_with_checked_names

_DOT1Q = "/interfaces/interface/dot1q-vlan"


@dataclass(frozen=True)
class Sub:
    """A sub-interface as the source states it."""

    address: str
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
        "hostname r1\n"
        "interface GigabitEthernet1/0/2\n no switchport\n!\n"
        "interface GigabitEthernet1/0/2.10\n description users\n"
        " encapsulation dot1Q 10\n ip address 198.51.100.1 255.255.255.0\n!\n"
        "interface GigabitEthernet1/0/2.20\n encapsulation dot1Q 20\n shutdown\n"
        " ip address 198.51.100.129 255.255.255.128\n!\n",
        "GigabitEthernet1/0/2",
        (Sub("198.51.100.1", "10", 10, "users"), Sub("198.51.100.129", "20", 20, enabled=False)),
    ),
    "junos": Source(
        "juniper_junos",
        # The unit is not the tag.
        "set system host-name r1\n"
        "set interfaces ge-0/0/2 vlan-tagging\n"
        "set interfaces ge-0/0/2 unit 100 description users\n"
        "set interfaces ge-0/0/2 unit 100 vlan-id 10\n"
        "set interfaces ge-0/0/2 unit 100 family inet address 198.51.100.1/24\n",
        "ge-0/0/2",
        (Sub("198.51.100.1", "100", 10, "users"),),
    ),
    "eos": Source(
        "arista_eos",
        "hostname r1\n!\ninterface Ethernet2\n   no switchport\n!\n"
        "interface Ethernet2.10\n   encapsulation dot1q vlan 10\n"
        "   ip address 198.51.100.1/24\n!\n",
        "Ethernet2",
        (Sub("198.51.100.1", "10", 10),),
    ),
    "nxos": Source(
        "cisco_nxos",
        "hostname r1\n!\ninterface Ethernet1/2\n  no switchport\n!\n"
        "interface Ethernet1/2.10\n  encapsulation dot1q 10\n"
        "  ip address 198.51.100.1/24\n!\n",
        "Ethernet1/2",
        (Sub("198.51.100.1", "10", 10),),
    ),
    "iosxr": Source(
        "cisco_iosxr",
        "hostname r1\n!\ninterface GigabitEthernet0/0/0/2\n!\n"
        "interface GigabitEthernet0/0/0/2.10\n encapsulation dot1q 10\n"
        " ipv4 address 198.51.100.1 255.255.255.0\n!\n",
        "GigabitEthernet0/0/0/2",
        (Sub("198.51.100.1", "10", 10),),
    ),
    "vyos": Source(
        "vyos",
        "interfaces {\n    ethernet eth2 {\n        vif 10 {\n"
        "            address 198.51.100.1/24\n        }\n    }\n}\n"
        "system {\n    host-name r1\n}\n",
        "eth2",
        (Sub("198.51.100.1", "10", 10),),
    ),
}

_ROS = "mikrotik_routeros"


# --- a reader of RouterOS's grammar, typed here --------------------------

_KV = re.compile(r'([\w-]+)=("(?:[^"\\]|\\.)*"|\S+)')


@dataclass
class Line:
    section: str
    verb: str
    kv: dict[str, str]
    find: dict[str, str]
    review_above: str


def _value(raw: str) -> str:
    if raw.startswith('"') and raw.endswith('"'):
        return re.sub(r"\\(.)", r"\1", raw[1:-1])
    return raw


def _lines(text: str) -> list[Line]:
    """Each ``add`` / ``set`` line of *text* with its section, its
    ``key=value`` pairs, the pairs of its ``[ find ... ]`` and the
    ``# review:`` line right above it."""
    out: list[Line] = []
    section = ""
    review = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("/"):
            section, review = line, ""
            continue
        if line.startswith("# review:"):
            review = line
            continue
        verb = line.split(" ", 1)[0]
        if verb not in ("add", "set"):
            review = ""
            continue
        find: dict[str, str] = {}
        rest = line
        m = re.match(r"set \[ find ([^\]]*) \](.*)$", line)
        if m:
            find = {k: _value(v) for k, v in _KV.findall(m.group(1))}
            rest = m.group(2)
        out.append(Line(section, verb, {k: _value(v) for k, v in _KV.findall(rest)}, find, review))
        review = ""
    return out


def _text_problems(text: str, port: str, subs: tuple[Sub, ...]) -> list[str]:
    """What the text gets wrong about *subs* on *port*: each address is on
    ``<port>.<unit>``, which a VLAN interface on *port* with the tag
    defines, and which is no ethernet port."""
    lines = _lines(text)
    problems: list[str] = []
    ports = {
        ln.find.get("default-name") or ln.find.get("name") or ln.kv.get("name")
        for ln in lines if ln.section == "/interface ethernet"
    }
    ports |= {ln.find.get("default-name") for ln in lines if ln.section == "/interface ethernet"}
    if port not in ports:
        problems.append(f"the port {port} is not in /interface ethernet")
    for sub in subs:
        name = f"{port}.{sub.unit}"
        on = [
            ln.kv.get("interface") for ln in lines
            if ln.section == "/ip address" and ln.kv.get("address", "").startswith(sub.address + "/")
        ]
        if on != [name]:
            problems.append(f"{sub.address} is on {on}, want [{name!r}]")
        vlan = [ln for ln in lines if ln.section == "/interface vlan" and ln.kv.get("name") == name]
        if len(vlan) != 1:
            problems.append(f"{len(vlan)} /interface vlan lines define {name}")
            continue
        kv = vlan[0].kv
        if kv.get("interface") != port:
            problems.append(f"{name} rides on {kv.get('interface')}, want {port}")
        if kv.get("vlan-id") != str(sub.tag):
            problems.append(f"{name} has vlan-id={kv.get('vlan-id')}, want {sub.tag}")
        if kv.get("comment", "") != sub.description:
            problems.append(f"{name} has comment={kv.get('comment')!r}, want {sub.description!r}")
        if (kv.get("disabled") == "yes") == sub.enabled:
            problems.append(f"{name} disabled={kv.get('disabled')}, want enabled={sub.enabled}")
        if vlan[0].review_above:
            problems.append(f"{name} has a review line above it: {vlan[0].review_above}")
        if name in ports:
            problems.append(f"{name} is written as an ethernet port")
    return problems


def _parsed_problems(text: str, port: str, subs: tuple[Sub, ...]) -> list[str]:
    """What the RouterOS parser reads back: an interface ``<port>.<unit>``
    with the address, a sub-interface of *port* with the tag its own, and
    no VLAN under that name -- its reading of a VLAN interface on a
    port."""
    tree = get_codec(_ROS).parse(text)
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
        if iface.interface_type != "ianaift:ethernetCsmacd":
            problems.append(f"{name} is read as {iface.interface_type}")
        if (iface.dot1q_vlan, iface.vlan_parent) != (sub.tag, port):
            problems.append(f"{name} is read with tag {iface.dot1q_vlan} on {iface.vlan_parent}")
        if iface.enabled != sub.enabled:
            problems.append(f"{name} is read enabled={iface.enabled}")
        if name in {v.name for v in tree.vlans}:
            problems.append(f"a VLAN is named {name}")
    return problems


def _job(key: str, path: str, port_map: dict[str, str] | None = None):
    src = SOURCES[key]
    if path == "bare":
        return run_plan(get_codec(src.codec), get_codec(_ROS), src.text)
    return run_plan_with_checked_names(
        get_codec(src.codec), get_codec(_ROS), src.text, port_rename_map=port_map or {},
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
def test_the_job_says_it_is_supported(key: str) -> None:
    """The output is what the device runs as the sub-interface, and is
    read back as one: the report lists no loss of it."""
    job = _job(key, "plan")
    assert job.status.value == "completed", job.error
    assert _DOT1Q not in {p.path for p in job.validation.lossy_paths}
    assert _DOT1Q not in {p.path for p in job.validation.unsupported_paths}


def test_a_vlan_of_the_same_id_is_still_written() -> None:
    """The tag is the port's own: a VLAN of the switch with the same id
    is written as well."""
    text = (
        "hostname r1\nvlan 20\n name SERVERS\n!\n"
        "interface GigabitEthernet1/0/2\n no switchport\n!\n"
        "interface GigabitEthernet1/0/2.20\n encapsulation dot1Q 20\n"
        " ip address 198.51.100.1 255.255.255.0\n!\n"
    )
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec(_ROS), text, port_rename_map={},
    )
    vlans = [ln.kv for ln in _lines(job.rendered) if ln.section == "/interface vlan"]
    assert {(kv.get("name"), kv.get("vlan-id"), kv.get("comment", "")) for kv in vlans} == {
        ("ether2.20", "20", ""),
        ("vlan20", "20", "SERVERS"),
    }
    assert _text_problems(job.rendered, "ether2", (Sub("198.51.100.1", "20", 20),)) == []


def test_a_sub_interface_whose_name_gives_no_port_says_where_it_went() -> None:
    """An entry can name a sub-interface with no port in it.  Its port is
    then not known: it rides on the parent chosen for every VLAN, under a
    review line that says so, and it is neither an ethernet port nor the
    parent of itself."""
    job = _job("iosxe", "plan", {"GigabitEthernet1/0/2.10": "wan10"})
    lines = _lines(job.rendered)
    wan = [ln for ln in lines if ln.kv.get("name") == "wan10" or ln.find.get("name") == "wan10"]
    assert [(ln.section, ln.kv.get("interface"), ln.kv.get("vlan-id")) for ln in wan] == [
        ("/interface vlan", "bridge1", "10"),
    ]
    assert wan[0].review_above == (
        "# review: wan10 is a routed sub-interface (tag 10) whose name gives "
        "no port; it is written on bridge1 -- move it to its port"
    )
    assert ("/interface bridge", "bridge1") in {(ln.section, ln.kv.get("name")) for ln in lines}
    # The other unit keeps its port.
    assert _text_problems(job.rendered, "ether2", SOURCES["iosxe"].subs[1:]) == []


# --- each check is handed the defect it is for ----------------------------


def _as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renderer as it was: a tree whose sub-interfaces it does not see."""
    real = ros_codec.render_intent

    def render(tree):
        tree = copy.deepcopy(tree)
        for iface in tree.interfaces:
            iface.dot1q_vlan = None
        return real(tree)

    monkeypatch.setattr(ros_codec, "render_intent", render)


@pytest.mark.parametrize("key", sorted(SOURCES))
def test_the_output_with_no_vlan_interface_is_seen(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _as_before(monkeypatch)
    job = _job(key, "plan")
    port = _port(key, "plan", job)
    assert any("/interface vlan lines define" in p for p in _text_problems(job.rendered, port, SOURCES[key].subs))
    assert _parsed_problems(job.rendered, port, SOURCES[key].subs)


def test_a_sub_interface_on_another_parent_is_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Handed a renderer that does not find a unit's port, the reader sees
    the parent and the review line."""
    monkeypatch.setattr(ros_render, "_port_of_unit", lambda name: None)
    job = _job("iosxe", "plan")
    problems = _text_problems(job.rendered, "ether2", SOURCES["iosxe"].subs)
    assert any("rides on bridge1" in p for p in problems)
    assert any("review line" in p for p in problems)


_GOOD = (
    "/interface ethernet\n"
    "set [ find default-name=ether2 ] disabled=no\n"
    "/interface vlan\n"
    'add comment="users" interface=ether2 name=ether2.10 vlan-id=10\n'
    "/ip address\n"
    "add address=198.51.100.1/24 interface=ether2.10\n"
)


@pytest.mark.parametrize(("broken", "said"), [
    (_GOOD.replace("vlan-id=10", "vlan-id=100"), "has vlan-id=100"),
    (_GOOD.replace('comment="users" ', ""), "has comment=None"),
    (_GOOD.replace("vlan-id=10", "vlan-id=10 disabled=yes"), "disabled=yes"),
    (_GOOD.replace("interface=ether2 name", "interface=bridge1 name"), "rides on bridge1"),
    (_GOOD.replace("set [ find default-name=ether2 ] disabled=no",
                   "set [ find default-name=ether2 ] disabled=no\nset [ find name=ether2.10 ] disabled=no"),
     "written as an ethernet port"),
    (_GOOD.replace("/interface vlan\n", "/interface vlan\n# review: put somewhere\n"), "review line"),
    (_GOOD.replace("interface=ether2.10", "interface=ether2"), "is on ['ether2']"),
    (_GOOD.replace("default-name=ether2", "default-name=ether3"), "port ether2 is not"),
])
def test_the_reader_sees_each_defect(broken: str, said: str) -> None:
    sub = (Sub("198.51.100.1", "10", 10, "users"),)
    assert _text_problems(_GOOD, "ether2", sub) == []
    assert any(said in p for p in _text_problems(broken, "ether2", sub)), _text_problems(broken, "ether2", sub)


@pytest.mark.parametrize(("broken", "said"), [
    (_GOOD.replace("/interface vlan\n", "/interface bridge\nadd name=bridge1\n/interface vlan\n")
     .replace("interface=ether2 name", "interface=bridge1 name"), "is read as ianaift:l3ipvlan"),
    (_GOOD.replace("vlan-id=10", "vlan-id=100"), "is read with tag 100 on ether2"),
    (_GOOD.replace("vlan-id=10", "vlan-id=10 disabled=yes"), "is read enabled=False"),
])
def test_the_parser_reading_sees_each_defect(broken: str, said: str) -> None:
    sub = (Sub("198.51.100.1", "10", 10, "users"),)
    assert _parsed_problems(_GOOD, "ether2", sub) == []
    problems = _parsed_problems(broken, "ether2", sub)
    assert any(said in p for p in problems), problems
