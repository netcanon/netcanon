"""A sub-interface's tag is an 802.1Q VLAN id, 1 to 4094, or the
sub-interface is left out and said.

A frame of VID 0 carries a priority and no VLAN, and 4095 is reserved
(IEEE 802.1Q); the tree's tag is a VLAN id.  The IOS-XE, IOS XR, EOS
and Junos parsers read a tag statement whole and left such a
sub-interface out with a row.  Four did not:

* VyOS read ``vif 0`` (a block VyOS takes) as a sub-interface of tag
  0, and ``vif 5000`` of tag 5000, and both were written so onto every
  target that writes a tag;
* NX-OS read ``encapsulation dot1q 0`` for its first number, the same;
* RouterOS made a VLAN of ``vlan-id=0`` and refused the whole config;
* FortiOS made no VLAN of ``set vlanid 0`` and kept the interface, its
  address on an interface of no tag.

Each source here holds a sub-interface of tag 10 beside the one whose
tag is no VLAN id, and the row each parser writes is typed by hand.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.base import ParseError
from netcanon.migration.codecs.cisco_nxos import parse as nxos_parse
from netcanon.migration.codecs.fortigate_cli import parse as fgt_parse
from netcanon.migration.codecs.mikrotik_routeros import parse as ros_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.codecs.vyos import parse as vyos_parse
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

#: The end of the row of a sub-interface whose tag statement is not read.
_ROW = (
    " -- not one 802.1Q tag and at most one inner tag, so the "
    "sub-interface is not translated"
)

#: Per codec: the source, with ``{tag}`` for the tag of the second
#: sub-interface, and its row.  The first is tag 10, 192.0.2.129; the
#: second, 203.0.113.1.
SOURCES = {
    "vyos": (
        "interfaces {\n"
        "    ethernet eth0 {\n"
        "        vif 10 {\n"
        "            address 192.0.2.129/25\n"
        "        }\n"
        "        vif {tag} {\n"
        "            address 203.0.113.1/24\n"
        "        }\n"
        "    }\n"
        "}\n",
        "interfaces ethernet eth0: vif {tag}" + _ROW,
    ),
    "cisco_nxos": (
        "interface Ethernet1/1.10\n"
        "  encapsulation dot1q 10\n"
        "  ip address 192.0.2.129/25\n"
        "\n"
        "interface Ethernet1/1.20\n"
        "  encapsulation dot1q {tag}\n"
        "  ip address 203.0.113.1/24\n",
        "interface Ethernet1/1.20: encapsulation dot1q {tag}" + _ROW,
    ),
    "mikrotik_routeros": (
        "/interface vlan\n"
        "add interface=ether1 name=ether1.10 vlan-id=10\n"
        "add interface=ether1 name=ether1.20 vlan-id={tag}\n"
        "/ip address\n"
        "add address=192.0.2.129/25 interface=ether1.10\n"
        "add address=203.0.113.1/24 interface=ether1.20\n",
        "/interface vlan ether1.20: vlan-id= a number that is no VLAN id, "
        "1 to 4094 -- not one 802.1Q tag and at most one inner tag, so the "
        "interface is not translated",
    ),
    "fortigate_cli": (
        "config system interface\n"
        '    edit "port1"\n'
        "        set type physical\n"
        "    next\n"
        '    edit "sub10"\n'
        "        set ip 192.0.2.129 255.255.255.128\n"
        '        set interface "port1"\n'
        "        set vlanid 10\n"
        "    next\n"
        '    edit "sub20"\n'
        "        set ip 203.0.113.1 255.255.255.0\n"
        '        set interface "port1"\n'
        "        set vlanid {tag}\n"
        "    next\n"
        "end\n",
        "config system interface edit sub20: set vlanid -- a number that "
        "is no VLAN id, 1 to 4094, so the interface is not translated",
    ),
    "cisco_iosxe_cli": (
        "interface GigabitEthernet0/1.10\n"
        " encapsulation dot1Q 10\n"
        " ip address 192.0.2.129 255.255.255.128\n"
        "!\n"
        "interface GigabitEthernet0/1.20\n"
        " encapsulation dot1Q {tag}\n"
        " ip address 203.0.113.1 255.255.255.0\n"
        "!\n",
        "interface GigabitEthernet0/1.20: encapsulation dot1Q {tag}" + _ROW,
    ),
    "cisco_iosxr": (
        "interface GigabitEthernet0/0/0/1.10\n"
        " encapsulation dot1q 10\n"
        " ipv4 address 192.0.2.129 255.255.255.128\n"
        "!\n"
        "interface GigabitEthernet0/0/0/1.20\n"
        " encapsulation dot1q {tag}\n"
        " ipv4 address 203.0.113.1 255.255.255.0\n"
        "!\n",
        "interface GigabitEthernet0/0/0/1.20: encapsulation dot1q {tag}" + _ROW,
    ),
    "arista_eos": (
        "interface Ethernet1.10\n"
        "   encapsulation dot1q vlan 10\n"
        "   ip address 192.0.2.129/25\n"
        "!\n"
        "interface Ethernet1.20\n"
        "   encapsulation dot1q vlan {tag}\n"
        "   ip address 203.0.113.1/24\n"
        "!\n",
        "interface Ethernet1.20: encapsulation dot1q vlan {tag}" + _ROW,
    ),
    "juniper_junos": (
        "set interfaces ge-0/0/1 vlan-tagging\n"
        "set interfaces ge-0/0/1 unit 10 vlan-id 10\n"
        "set interfaces ge-0/0/1 unit 10 family inet address 192.0.2.129/25\n"
        "set interfaces ge-0/0/1 unit 20 vlan-id {tag}\n"
        "set interfaces ge-0/0/1 unit 20 family inet address 203.0.113.1/24\n",
        "interfaces ge-0/0/1 unit 20: vlan-id {tag}" + _ROW,
    ),
}

#: Tags that are no VLAN id: the null VID, the reserved one, and one
#: past the twelve bits.
NOT_AN_ID = ["0", "4095", "5000"]

CASES = [(codec, tag) for codec in SOURCES for tag in NOT_AN_ID]


def _text(codec: str, tag: str) -> str:
    return SOURCES[codec][0].replace("{tag}", tag)


def _row(codec: str, tag: str) -> str:
    return SOURCES[codec][1].replace("{tag}", tag)


def problems(codec: str, tag: str) -> list[str]:
    """What is wrong with the parse of *codec*'s source with *tag*."""
    try:
        tree = get_codec(codec).parse(_text(codec, tag))
    except ParseError as exc:
        return [f"the parse was refused: {exc}"]
    found = []
    by_address = {
        a.ip: i for i in tree.interfaces for a in i.ipv4_addresses
    }
    if "203.0.113.1" in by_address:
        found.append("the sub-interface whose tag is no VLAN id is in the tree")
    neighbour = by_address.get("192.0.2.129")
    if neighbour is None or neighbour.dot1q_vlan != 10:
        found.append("its neighbour of tag 10 is not")
    tags = {
        t for i in tree.interfaces for t in (i.dot1q_vlan, i.dot1q_inner_vlan)
        if t is not None
    }
    if not tags <= set(range(1, 4095)):
        found.append(f"a tag that is no VLAN id: {sorted(tags)}")
    if _row(codec, tag) not in tree.dropped_tier3_sections:
        found.append(f"no row: {tree.dropped_tier3_sections}")
    return found


@pytest.mark.parametrize(("codec", "tag"), CASES)
def test_a_tag_that_is_no_vlan_id_is_left_out_and_said(codec: str, tag: str) -> None:
    assert problems(codec, tag) == []


def test_vyos_in_set_form_is_read_the_same() -> None:
    """``show configuration commands`` is the same block, one leaf a
    line."""
    tree = get_codec("vyos").parse(
        "set interfaces ethernet eth0 vif 10 address '192.0.2.129/25'\n"
        "set interfaces ethernet eth0 vif 0 address '203.0.113.1/24'\n"
        "set interfaces ethernet eth0 vif 0 description 'zero'\n"
        "set system host-name 'r1'\n"
    )
    by_address = {a.ip: i.dot1q_vlan for i in tree.interfaces for a in i.ipv4_addresses}
    assert by_address == {"192.0.2.129": 10}
    assert _row("vyos", "0") in tree.dropped_tier3_sections


@pytest.mark.parametrize("codec", list(SOURCES))
def test_the_source_reads_a_vlan_id(codec: str) -> None:
    """With tag 20 in its place, each source is two sub-interfaces:
    the texts are ones each parser reads."""
    tree = get_codec(codec).parse(_text(codec, "20"))
    by_address = {a.ip: i.dot1q_vlan for i in tree.interfaces for a in i.ipv4_addresses}
    assert by_address == {"192.0.2.129": 10, "203.0.113.1": 20}


#: Where the neighbour of tag 10 is not in the output either, for a
#: reason of its own: AOS-S has no name for the NX-OS port the units
#: are on, and the job is ``partial`` with the unit listed.
NEIGHBOUR_NOT_WRITTEN = {("cisco_nxos", "aruba_aoss")}


@pytest.mark.parametrize("codec", list(SOURCES))
def test_on_every_target_it_is_said_and_not_written(codec: str) -> None:
    source = get_codec(codec)
    not_written = set()
    for target in list_public_codecs():
        job = run_plan_with_checked_names(
            source, get_codec(target), _text(codec, "0"), port_rename_map={},
        )
        assert "203.0.113.1" not in job.rendered, target
        assert _row(codec, "0") in job.dropped_tier3_sections, target
        if "192.0.2.129" not in job.rendered:
            not_written.add((codec, target))
            assert job.status == MigrationJobStatus.partial, target
            assert any(".10" in name for name in job.unresolved_ports), target
    assert not_written == {p for p in NEIGHBOUR_NOT_WRITTEN if p[0] == codec}


def _captures() -> list[tuple[str, Path]]:
    found = []
    root = Path(__file__).resolve().parents[2] / "fixtures" / "real"
    for directory in sorted(root.iterdir()):
        codec = DIR_TO_CODEC_NAME.get(directory.name)
        if codec is None or not directory.is_dir():
            continue
        found.extend(
            (codec, path) for path in sorted(directory.iterdir())
            if path.is_file()
            and path.suffix.lower() in {".txt", ".cfg", ".xml", ".conf", ".rsc", ".set"}
        )
    return found


def test_no_committed_capture_holds_a_tag_that_is_no_vlan_id() -> None:
    seen = 0
    for codec, path in _captures():
        try:
            tree = get_codec(codec).parse(path.read_text(encoding="utf-8", errors="replace"))
        except ParseError:
            continue
        for iface in tree.interfaces:
            for tag in (iface.dot1q_vlan, iface.dot1q_inner_vlan):
                if tag is not None:
                    seen += 1
                    assert 1 <= tag <= 4094, (path.name, iface.name, tag)
    # The captures hold sub-interfaces: a loop that read none passes.
    assert seen > 0


# -- Each check is handed the defect it is for ---------------------------


def _int_if_digits(word: str) -> int | None:
    return int(word) if word.isdigit() else None


def test_the_check_sees_vyos_read_tag_0(monkeypatch) -> None:
    monkeypatch.setattr(vyos_parse, "a_tag", _int_if_digits)
    assert problems("vyos", "0") != []


def test_the_check_sees_nxos_read_tag_0(monkeypatch) -> None:
    monkeypatch.setattr(
        nxos_parse, "without_unread_tags", lambda raw, _a, _b: (raw, []),
    )
    assert problems("cisco_nxos", "0") != []


def test_the_check_sees_routeros_refuse_the_config(monkeypatch) -> None:
    monkeypatch.setattr(ros_parse, "a_tag", _int_if_digits)
    assert problems("mikrotik_routeros", "0") != []


def test_the_check_sees_fortios_keep_an_untagged_interface(monkeypatch) -> None:
    monkeypatch.setattr(fgt_parse, "a_tag", lambda _word: 1)
    assert problems("fortigate_cli", "0") != []
