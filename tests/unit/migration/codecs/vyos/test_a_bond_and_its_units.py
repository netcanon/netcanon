"""A bond's members and its units, as VyOS prints them.

VyOS defines ``member interface`` under ``interfaces bonding bondN`` as
a leaf of many values: ``show configuration`` prints one bare line a
member (``interface eth1``), and ``show configuration commands`` puts
each value in quotes (``member interface 'eth1'``).  A bond takes ``vif
<vid>`` as an ethernet port does.  The parser read none of the three.
A bond in the block form had no members; a bond in the set form had
members called ``'eth1'``, quotes and all, and two interfaces of those
names beside the ports; and a ``vif`` under a bond was not read, its
address with it -- lost on every target, in jobs that said
``completed``.  The renderer wrote each member as a node, ``interface
eth1 { }``, which is not the grammar of this leaf, and a unit of a bond
as ``ethernet bond1.10``: an ethernet port of that name.

Here each printed form is parsed and held to one tree typed by hand;
the renderer's output is read as TEXT by a reader of VyOS braces typed
here, and with the parser; and the unit of a bond is followed from
VyOS onto every public codec, found in the output by its address with
the target's own parser.  Each check is handed the defect it is for.

See also: ``docs/vendors/vyos.md``,
``tests/unit/migration/test_vyos.py``.
"""

from __future__ import annotations

import functools

import pytest

from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

#: One bond of two members, an address of its own, and a unit with tag
#: 10 -- in each form a VyOS config comes in.
FORMS = {
    # ``show configuration``: a leaf of many values is one bare line each.
    "block": """\
interfaces {
    bonding bond0 {
        address 10.0.0.1/24
        member {
            interface eth1
            interface eth2
        }
        mode 802.3ad
        vif 10 {
            address 10.0.10.1/24
            description unit10
        }
    }
    ethernet eth1 {
    }
    ethernet eth2 {
    }
}
system {
    host-name r1
}
""",
    # ``show configuration commands``: every leaf value quoted.
    "set": """\
set interfaces bonding bond0 address '10.0.0.1/24'
set interfaces bonding bond0 member interface 'eth1'
set interfaces bonding bond0 member interface 'eth2'
set interfaces bonding bond0 mode '802.3ad'
set interfaces bonding bond0 vif 10 address '10.0.10.1/24'
set interfaces bonding bond0 vif 10 description 'unit10'
set interfaces ethernet eth1
set interfaces ethernet eth2
set system host-name 'r1'
""",
    # The form this codec wrote before it wrote VyOS's own: each member
    # a node.  Read still, so that its old outputs read back.
    "member as a node": """\
interfaces {
    bonding bond0 {
        address "10.0.0.1/24"
        mode 802.3ad
        member {
            interface eth1 {
            }
            interface eth2 {
            }
        }
        vif 10 {
            address "10.0.10.1/24"
            description "unit10"
        }
    }
    ethernet eth1 {
    }
    ethernet eth2 {
    }
}
system {
    host-name r1
}
""",
}

#: What every form states, typed by hand.
NAMES = {"bond0", "bond0.10", "eth1", "eth2"}
LAG = ("bond0", ["eth1", "eth2"], "active")
UNIT = ("bond0.10", 10, ["10.0.10.1/24"], "unit10")


def _shape(tree):
    (lag,) = tree.lags
    (unit,) = [i for i in tree.interfaces if i.name == "bond0.10"]
    return (
        {i.name for i in tree.interfaces},
        (lag.name, sorted(lag.members), lag.mode),
        (
            unit.name,
            unit.dot1q_vlan,
            [f"{a.ip}/{a.prefix_length}" for a in unit.ipv4_addresses],
            unit.description,
        ),
    )


@pytest.mark.parametrize("form", sorted(FORMS))
def test_every_printed_form_is_one_tree(form: str) -> None:
    tree = get_codec("vyos").parse(FORMS[form])
    assert _shape(tree) == (NAMES, LAG, UNIT)
    members = {i.name: i.lag_member_of for i in tree.interfaces}
    assert members["eth1"] == members["eth2"] == "bond0"


# ---------------------------------------------------------------------------
# The output, read as text
# ---------------------------------------------------------------------------


def _blocks(text: str) -> dict[tuple[str, ...], list[str]]:
    """Every block of a VyOS block-form text by its path of headers,
    with the lines it holds that open no block."""
    found: dict[tuple[str, ...], list[str]] = {}
    path: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.endswith("{"):
            path.append(line[:-1].strip())
            found.setdefault(tuple(path), [])
        elif line == "}":
            path.pop()
        elif path:
            found[tuple(path)].append(line)
    return found


def _what_is_wrong(text: str, bond: str, members: list[str], vid: int, address: str) -> list[str]:
    """What a reader of VyOS braces finds wrong with how *text* writes
    the bond *bond*: its members, its unit, and no port of the unit's
    name."""
    blocks = _blocks(text)
    wrong: list[str] = []
    member = ("interfaces", f"bonding {bond}", "member")
    written = sorted(blocks.get(member, []))
    if written != sorted(f"interface {m}" for m in members):
        wrong.append(f"members written {written}")
    nodes = [path[-1] for path in blocks if path[:-1] == member]
    if nodes:
        wrong.append(f"members written as nodes {nodes}")
    unit = ("interfaces", f"bonding {bond}", f"vif {vid}")
    if f'address "{address}"' not in blocks.get(unit, []):
        wrong.append(f"no vif {vid} under bonding {bond} holds {address}")
    ports = [path[1] for path in blocks if len(path) == 2 and "." in path[1]]
    if ports:
        wrong.append(f"a unit written as an interface of its own {ports}")
    return wrong


def test_the_renderer_writes_the_bond_as_vyos_prints_it() -> None:
    codec = get_codec("vyos")
    text = codec.render(codec.parse(FORMS["block"]))
    assert _what_is_wrong(text, "bond0", ["eth1", "eth2"], 10, "10.0.10.1/24") == []
    assert _shape(codec.parse(text)) == (NAMES, LAG, UNIT)


#: What the renderer wrote before, for the tree of :data:`FORMS`.
OLD_RENDER = """\
interfaces {
    ethernet bond0.10 {
        address "10.0.10.1/24"
        description "unit10"
    }
    ethernet eth1 {
    }
    ethernet eth2 {
    }
    bonding bond0 {
        address "10.0.0.1/24"
        mode 802.3ad
        member {
            interface eth1 {
            }
            interface eth2 {
            }
        }
    }
}
"""


def test_the_reader_finds_what_the_renderer_wrote_before() -> None:
    wrong = _what_is_wrong(OLD_RENDER, "bond0", ["eth1", "eth2"], 10, "10.0.10.1/24")
    assert wrong == [
        "members written []",
        "members written as nodes ['interface eth1', 'interface eth2']",
        "no vif 10 under bonding bond0 holds 10.0.10.1/24",
        "a unit written as an interface of its own ['ethernet bond0.10']",
    ]


#: A LAG with a unit, in grammars whose parsers read one, onto VyOS.
UNITS_ONTO_VYOS = {
    "arista_eos": (
        "hostname r1\n!\ninterface Ethernet1\n   channel-group 1 mode active\n!\n"
        "interface Port-Channel1\n   no switchport\n!\n"
        "interface Port-Channel1.10\n   encapsulation dot1q vlan 10\n"
        "   ip address 10.0.10.1/24\n!\n"
    ),
    "juniper_junos": (
        "set system host-name r1\n"
        "set interfaces ge-0/0/1 ether-options 802.3ad ae1\n"
        "set interfaces ae1 aggregated-ether-options lacp active\n"
        "set interfaces ae1 vlan-tagging\n"
        "set interfaces ae1 unit 10 vlan-id 10\n"
        "set interfaces ae1 unit 10 family inet address 10.0.10.1/24\n"
    ),
}


@pytest.mark.parametrize("source", sorted(UNITS_ONTO_VYOS))
def test_a_unit_of_a_lag_is_a_vif_of_its_bond(source: str) -> None:
    job = run_plan_with_checked_names(
        get_codec(source), get_codec("vyos"), UNITS_ONTO_VYOS[source], port_rename_map={},
    )
    renames = job.port_renames
    bond = next(v for k, v in renames.items() if k.lower() in ("port-channel1", "ae1"))
    members = [v for k, v in renames.items() if k in ("Ethernet1", "ge-0/0/1")]
    assert _what_is_wrong(job.rendered or "", bond, members, 10, "10.0.10.1/24") == []
    (unit,) = [
        i for i in get_codec("vyos").parse(job.rendered or "").interfaces
        if any(str(a.ip) == "10.0.10.1" for a in i.ipv4_addresses)
    ]
    assert (unit.name, unit.dot1q_vlan) == (f"{bond}.10", 10)


# ---------------------------------------------------------------------------
# The unit of a bond, from VyOS onto every codec
# ---------------------------------------------------------------------------


#: Targets that write no LAG: the IOS-XE NETCONF codec models no
#: membership, and its parser reads none back.
WRITES_NO_LAG = {"cisco_iosxe"}

#: Targets whose own parser reads the unit back on the LAG itself, so
#: that one interface carries both addresses.  The AOS-CX output says
#: ``interface lag 0.10``; its parser reads ``lag 0``.  Compared for
#: equality, so a parser that comes to read the unit fails until the
#: pin is taken out.
UNIT_READ_ONTO_ITS_LAG = {"aruba_aoscx"}


@functools.cache
def _from_vyos(form: str, target: str, parse=None) -> MigrationJob:
    return run_plan_with_checked_names(
        parse or get_codec("vyos"), get_codec(target), FORMS[form], port_rename_map={},
    )


def _losses(job: MigrationJob, target: str) -> list[str]:
    """What the target's own parser does not find in the output: the
    bond's members on one LAG, the bond's address, and the unit's on an
    interface of its own."""
    tree = get_codec(target).parse(job.rendered or "")
    lost: list[str] = []
    holding = {
        ip: [i.name for i in tree.interfaces if any(str(a.ip) == ip for a in i.ipv4_addresses)]
        for ip in ("10.0.0.1", "10.0.10.1")
    }
    for ip, names in holding.items():
        if len(names) != 1:
            lost.append(f"{ip} on {names}")
    if holding["10.0.0.1"] and holding["10.0.0.1"] == holding["10.0.10.1"]:
        lost.append(f"both addresses on {holding['10.0.0.1']}")
    if target not in WRITES_NO_LAG and not any(len(lag.members) == 2 for lag in tree.lags):
        lost.append(f"no LAG of two members in {[(lag.name, lag.members) for lag in tree.lags]}")
    return lost


@pytest.mark.parametrize("target", PUBLIC)
@pytest.mark.parametrize("form", ["block", "set"])
def test_the_bond_and_its_unit_reach_every_target(form: str, target: str) -> None:
    lost = _losses(_from_vyos(form, target), target)
    if target in UNIT_READ_ONTO_ITS_LAG:
        assert len(lost) == 1 and lost[0].startswith("both addresses on "), lost
    else:
        assert lost == []


def test_the_pin_is_what_is_measured() -> None:
    measured = {
        target for target in PUBLIC
        if any(loss.startswith("both addresses") for loss in _losses(_from_vyos("block", target), target))
    }
    assert measured == UNIT_READ_ONTO_ITS_LAG


class _OldParse(type(get_codec("vyos"))):
    """The VyOS parser as it was for a bond: no unit, and no member in
    the block form."""

    def parse(self, text, *args, **kwargs):
        tree = super().parse(text, *args, **kwargs)
        tree.interfaces = [i for i in tree.interfaces if i.name != "bond0.10"]
        for lag in tree.lags:
            lag.members = []
        for iface in tree.interfaces:
            iface.lag_member_of = None
        return tree


@pytest.mark.parametrize("target", PUBLIC)
def test_the_check_finds_the_old_parse_on_every_target(target: str) -> None:
    lost = _losses(_from_vyos("block", target, _OldParse()), target)
    assert any(loss.startswith("10.0.10.1 on []") for loss in lost), lost
