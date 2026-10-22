"""A routed sub-interface of another vendor is a ``vif`` of its TAG onto VyOS.

On VyOS the number of a ``vif`` is the 802.1Q tag it carries: ``ethernet
eth1 { vif 200 { ... } }`` is ``eth1.200`` and carries VLAN 200.  IOS-XE
``interface GigabitEthernet0/0/1.100`` with ``encapsulation dot1Q 200``
and a Junos ``unit 100 vlan-id 200`` were sent after their port as
``eth1.100`` and written ``vif 100``: VLAN 100 on the wire, in a job that
was ``partial`` for ``/interfaces/interface/dot1q-vlan`` (unsupported) --
whose reason said the tag was flagged as a drop, not mis-rendered.  The
port translator now sends a unit with a tag after its port with the tag
(``CodecBase.units_are_named_by_their_tag``).

What each source holds is typed by hand.  The output is read two ways:
as text, by a reader of VyOS's grammar typed here, and with the VyOS
parser.  Each check is handed the defect it is for.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

import pytest

from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.codecs.vyos.codec import VyOSCodec
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import (
    _names_message,
    run_plan,
    run_plan_with_checked_names,
)

_DOT1Q = "/interfaces/interface/dot1q-vlan"
_VYOS = "vyos"


@dataclass(frozen=True)
class Sub:
    """A sub-interface as the source states it."""

    address: str
    mask: str
    unit: str
    tag: int
    description: str = ""
    enabled: bool = True

    @property
    def cidr(self) -> str:
        prefix = ipaddress.IPv4Network(f"0.0.0.0/{self.mask}").prefixlen
        return f"{self.address}/{prefix}"


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
        "interface Ethernet2.54\n   encapsulation dot1q vlan 300\n"
        "   ip address 198.51.100.1/24\n!\n",
        "Ethernet2",
        (Sub("198.51.100.1", "255.255.255.0", "54", 300),),
    ),
    "nxos": Source(
        "cisco_nxos",
        "hostname r1\n!\ninterface Ethernet1/2\n  no switchport\n!\n"
        "interface Ethernet1/2.54\n  encapsulation dot1q 300\n"
        "  ip address 198.51.100.1/24\n!\n",
        "Ethernet1/2",
        (Sub("198.51.100.1", "255.255.255.0", "54", 300),),
    ),
    "iosxr": Source(
        "cisco_iosxr",
        "hostname r1\n!\ninterface GigabitEthernet0/0/0/2\n!\n"
        "interface GigabitEthernet0/0/0/2.54\n encapsulation dot1q 300\n"
        " ipv4 address 198.51.100.1 255.255.255.0\n!\n",
        "GigabitEthernet0/0/0/2",
        (Sub("198.51.100.1", "255.255.255.0", "54", 300),),
    ),
}


# --- a reader of VyOS's grammar, typed here --------------------------------


def _blocks(text: str) -> dict[tuple[str, ...], list[str]]:
    """Every block of *text* by its path of headers (``("interfaces",
    "ethernet eth2", "vif 200")``), with the lines directly in it --
    comments included, in their order."""
    stack: list[str] = []
    found: dict[tuple[str, ...], list[str]] = {(): []}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.endswith("{") and not line.startswith("/*"):
            found[tuple(stack)].append(line)
            stack.append(line[:-1].strip())
            found.setdefault(tuple(stack), [])
        elif line == "}":
            stack.pop()
        else:
            found[tuple(stack)].append(line)
    return found


def _vif_of(blocks, cidr: str) -> list[tuple[str, str]]:
    """``(port, vif number)`` of each vif whose lines hold *cidr*."""
    return [
        (path[1].split()[1], path[2].split()[1])
        for path, lines in blocks.items()
        if len(path) == 3 and path[0] == "interfaces"
        and path[1].startswith("ethernet ") and path[2].startswith("vif ")
        and f'address "{cidr}"' in lines
    ]


def _text_problems(text: str, port: str, subs: tuple[Sub, ...]) -> list[str]:
    blocks = _blocks(text)
    problems: list[str] = []
    for sub in subs:
        where = _vif_of(blocks, sub.cidr)
        if where != [(port, str(sub.tag))]:
            problems.append(f"{sub.cidr}: in {where}, not vif {sub.tag} of {port}")
            continue
        lines = blocks[("interfaces", f"ethernet {port}", f"vif {sub.tag}")]
        if sub.description and f'description "{sub.description}"' not in lines:
            problems.append(f"{sub.cidr}: no description {sub.description!r}")
        if ("disable" in lines) == sub.enabled:
            problems.append(f"{sub.cidr}: `disable` is not what the source states")
        before = blocks[("interfaces", f"ethernet {port}")]
        header = before.index(f"vif {sub.tag} {{")
        if header and before[header - 1].startswith("/* review"):
            problems.append(f"{sub.cidr}: a review line says its tag is not its number")
    return problems


def _parsed_problems(text: str, port: str, subs: tuple[Sub, ...]) -> list[str]:
    tree = get_codec(_VYOS).parse(text)
    problems: list[str] = []
    for sub in subs:
        held = [
            (iface.name, iface.dot1q_vlan) for iface in tree.interfaces
            if any(str(a.ip) == sub.address for a in iface.ipv4_addresses)
        ]
        if held != [(f"{port}.{sub.tag}", sub.tag)]:
            problems.append(f"{sub.cidr}: read back as {held}")
    return problems


def _job(key: str, port_map: dict[str, str | None] | None = None):
    src = SOURCES[key]
    return run_plan_with_checked_names(
        get_codec(src.codec), get_codec(_VYOS), src.text, port_rename_map=port_map or {},
    )


# --- the source trees are what is typed here -------------------------------


@pytest.mark.parametrize("key", sorted(SOURCES))
def test_each_source_holds_its_sub_interfaces(key: str) -> None:
    src = SOURCES[key]
    tree = get_codec(src.codec).parse(src.text)
    held = {(i.name, i.dot1q_vlan) for i in tree.interfaces if i.dot1q_vlan is not None}
    assert held == {(f"{src.port}.{s.unit}", s.tag) for s in src.subs}


def test_the_codecs_that_name_a_unit_by_its_tag() -> None:
    """Typed here, not read from the codec: a codec whose flag moves
    fails until this set says why."""
    named = {
        name for name in list_public_codecs()
        if get_codec(name).units_are_named_by_their_tag
    }
    assert named == {_VYOS}


# --- the output -------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(SOURCES))
def test_a_sub_interface_is_a_vif_of_its_tag(key: str) -> None:
    job = _job(key)
    port = job.port_renames[SOURCES[key].port]
    assert _text_problems(job.rendered, port, SOURCES[key].subs) == []
    assert _parsed_problems(job.rendered, port, SOURCES[key].subs) == []
    for sub in SOURCES[key].subs:
        name = f"{SOURCES[key].port}.{sub.unit}"
        assert job.port_renames[name] == f"{port}.{sub.tag}"


#: What else a source's tree holds that VyOS declares unsupported.  The
#: IOS XR parser makes a VLAN record of each sub-interface's tag, and
#: VyOS has no VLAN table.
_HELD_FOR_ANOTHER_PATH = {"iosxr": ["/vlans/vlan/id"]}


@pytest.mark.parametrize("key", sorted(SOURCES))
def test_the_job_says_how_it_is_read_back(key: str) -> None:
    """The tag is carried; the report says the unit number is not kept,
    and the tag holds no job."""
    job = _job(key)
    unsupported = [p.path for p in job.validation.unsupported_paths]
    assert unsupported == _HELD_FOR_ANOTHER_PATH.get(key, [])
    assert _DOT1Q in {p.path for p in job.validation.lossy_paths}
    if not unsupported:
        assert job.status == MigrationJobStatus.completed, job.error


@pytest.mark.parametrize("key", sorted(SOURCES))
def test_the_bare_pipeline_says_the_tag_is_not_carried(key: str) -> None:
    """The bare pipeline translates no port name: a sub-interface of
    another vendor's name is a block of its own name there, which
    carries no tag, and its first line says so."""
    src = SOURCES[key]
    job = run_plan(get_codec(src.codec), get_codec(_VYOS), src.text)
    blocks = _blocks(job.rendered)
    for sub in src.subs:
        lines = blocks[("interfaces", f"ethernet {src.port}.{sub.unit}")]
        assert lines[0] == (
            f"/* review: the source config tags this interface {sub.tag}; on "
            f"VyOS a tag is a vif of its port, and this block carries none */"
        )


def test_a_vif_stands_between_two_vyos_configs() -> None:
    text = (
        "interfaces {\n    ethernet eth1 {\n        vif 54 {\n"
        "            address 10.54.0.1/24\n        }\n    }\n}\n"
        "system {\n    host-name r1\n}\n"
    )
    vyos = get_codec(_VYOS)
    job = run_plan_with_checked_names(vyos, vyos, text, port_rename_map={})
    assert job.status == MigrationJobStatus.completed, job.error
    assert job.rendered == run_plan(vyos, vyos, text).rendered
    assert _vif_of(_blocks(job.rendered), "10.54.0.1/24") == [("eth1", "54")]
    assert "review" not in job.rendered


# --- two units of one port with one tag --------------------------------------

_ONE_TAG = (
    "hostname r1\n"
    "interface GigabitEthernet0/0/2\n no switchport\n!\n"
    "interface GigabitEthernet0/0/2.100\n encapsulation dot1Q 200\n"
    " ip address 198.51.100.1 255.255.255.0\n!\n"
    "interface GigabitEthernet0/0/2.300\n encapsulation dot1Q 200\n"
    " ip address 203.0.113.1 255.255.255.0\n!\n"
)


def test_two_units_with_one_tag_are_one_name_and_said() -> None:
    """A port carries a VLAN once, and on VyOS the VLAN is the name: the
    two units are one name, which the job lists -- and it offers no pair
    of devices, which would send both units to one port again."""
    ios, vyos = get_codec("cisco_iosxe_cli"), get_codec(_VYOS)
    job = run_plan_with_checked_names(ios, vyos, _ONE_TAG, port_rename_map={})
    port = job.port_renames["GigabitEthernet0/0/2"]
    assert job.status == MigrationJobStatus.partial
    assert job.fused_ports == {
        f"{port}.200": ["GigabitEthernet0/0/2.100", "GigabitEthernet0/0/2.300"],
    }
    assert "both devices" not in job.error


def test_an_entry_that_gives_a_unit_another_number_is_said() -> None:
    """An entry decides the name, and on VyOS the name is the VLAN: the
    job says the entry's number is not the source's tag, and so does a
    line of the output."""
    ios, vyos = get_codec("cisco_iosxe_cli"), get_codec(_VYOS)
    port = run_plan_with_checked_names(
        ios, vyos, _ONE_TAG, port_rename_map={},
    ).port_renames["GigabitEthernet0/0/2"]
    entry = {"GigabitEthernet0/0/2.300": f"{port}.300"}
    job = run_plan_with_checked_names(ios, vyos, _ONE_TAG, port_rename_map=entry)
    assert job.status == MigrationJobStatus.completed, job.error
    assert (
        f"port_rename: the entry for 'GigabitEthernet0/0/2.300' names it "
        f"'{port}.300'; on vyos the number after the dot is the VLAN a "
        f"sub-interface carries, and the source config tags it 200 — name "
        f"it '<port>.200' to keep its tag"
    ) in job.warnings
    lines = _blocks(job.rendered)[("interfaces", f"ethernet {port}")]
    assert lines[lines.index("vif 300 {") - 1] == (
        "/* review: the source config tags this sub-interface 200, and a "
        "vif's number is its VLAN: it carries 300 */"
    )
    at = lines.index("vif 200 {")
    assert at == 0 or not lines[at - 1].startswith("/* review")


def test_the_pairing_is_offered_where_it_parts_the_names() -> None:
    """Units of one port go where the port goes, whether or not the
    config has a line for the port itself; units of two ports go to
    two."""
    ports = ["Gi0/0/2", "Gi0/0/2.100", "Gi0/0/2.300", "Gi0/0/3", "Gi0/0/3.100"]
    one_port = {"eth2.200": ["Gi0/0/2.100", "Gi0/0/2.300"]}
    two_ports = {"eth2.100": ["Gi0/0/2.100", "Gi0/0/3.100"]}
    assert "both devices" not in _names_message(one_port, [], [], ports)
    assert "both devices" not in _names_message(one_port, [], [], ports[1:3])
    assert _names_message(two_ports, [], [], ports).endswith(
        " Or declare both devices, to pair ports by position."
    )
    assert "Declaring both devices pairs the hardware ports among these" in (
        _names_message({**one_port, **two_ports}, [], [], ports)
    )


# --- each check is handed the defect it is for ------------------------------


@pytest.mark.parametrize("key", ["iosxe", "eos"])
def test_the_output_with_the_units_number_is_seen(
    key: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the flag taken off VyOS the translator sends the unit with
    its number, and both readings see the wrong vif."""
    monkeypatch.setattr(VyOSCodec, "units_are_named_by_their_tag", False)
    job = _job(key)
    port = job.port_renames[SOURCES[key].port]
    subs = SOURCES[key].subs
    assert len(_text_problems(job.rendered, port, subs)) == len(subs)
    assert len(_parsed_problems(job.rendered, port, subs)) == len(subs)


def test_the_reader_sees_each_defect() -> None:
    job = _job("iosxe")
    port = job.port_renames["GigabitEthernet0/0/2"]
    subs = SOURCES["iosxe"].subs
    good = job.rendered
    assert _text_problems(good, port, subs) == []
    broken = {
        "a vif of its unit": good.replace("vif 200 {", "vif 100 {"),
        "no description": good.replace('description "users"', ""),
        "no disable": good.replace("disable\n", ""),
        "a review line": good.replace(
            "vif 200 {", "/* review: the tag */\n        vif 200 {",
        ),
        "on another port": good.replace(f"ethernet {port} {{", "ethernet eth9 {"),
    }
    for what, text in broken.items():
        assert text != good, what
        assert _text_problems(text, port, subs), what
