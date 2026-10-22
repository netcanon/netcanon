"""A sub-interface's tag statement is read whole, or not at all.

Every reader of a tag statement took its first id.  ``encapsulation
dot1Q 2234 second-dot1q 15`` was VLAN 2234: the six Q-in-Q units of a
committed IOS-XE capture, each a customer's tag inside service VLAN
2234, came out as six sub-interfaces of VLAN 2234 alone -- on IOS-XE
itself as well -- in jobs that said ``completed``.  ``second-dot1q
any``, a range or a list of inner tags, an IOS XR ``dot1ad`` tag, an
EOS FlexEncap block and a Junos ``vlan-id-range`` were read the same
way, as the tag they begin with.  The Junos renderer, which wrote a
unit's ``vlan-id``, never wrote the statement on the device that makes
a unit's tag mean anything (``vlan-tagging``), and VyOS QinQ
(``vif-s``) went with nothing said.

So the tree holds an inner tag (``dot1q_inner_vlan``, both tags
802.1Q), four codecs read and write it, and a statement that is not
one tag and at most one inner tag leaves its sub-interface out with a
row of ``dropped_tier3_sections``.

Each source is typed by hand in its own grammar, and each output is
read with a reader of the test's own per target, not with the target's
parser alone: that parser was the one that read the first id.  Each
check is handed the defect it is for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
)
from netcanon.migration.canonical.vlan_names import translate_vlan_ids
from netcanon.migration.codecs.cisco_iosxe_cli import parse as iosxe_parse
from netcanon.migration.codecs.juniper_junos import render as junos_render
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

CAPTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "real" / "cisco_iosxe" / "ntc_carrier_interfaces.txt"
)

INNER = "/interfaces/interface/dot1q-inner-vlan"

#: The six units of the capture, (outer, inner) -> address, typed from
#: its text by hand.
CAPTURE_UNITS = {
    (2234, 15): "10.30.33.161",
    (2234, 27): "10.53.8.241",
    (2234, 36): "10.39.246.29",
    (2234, 49): "10.30.33.41",
    (2234, 1011): "10.39.18.217",
    (2234, 1020): "10.30.33.197",
}

#: How each target that has a form for the inner tag writes a
#: sub-interface of two tags, from the vendor's grammar: the line, and
#: whether the stanza is a Cisco-style ``interface`` block (``None``) or
#: Junos ``set`` lines.
TWO_TAGS = {
    "cisco_iosxe_cli": re.compile(r"^ encapsulation dot1Q (\d+) second-dot1q (\d+)$"),
    "cisco_iosxr": re.compile(r"^ encapsulation dot1q (\d+) second-dot1q (\d+)$"),
    "arista_eos": re.compile(r"^   encapsulation dot1q vlan (\d+) inner (\d+)$"),
    "juniper_junos": re.compile(
        r"^set interfaces (\S+) unit (\d+) vlan-tags outer (\d+) inner (\d+)$"
    ),
}

_ADDRESS = re.compile(r"\baddress (\d{1,3}(?:\.\d{1,3}){3})\b")
_JUNOS_ADDRESS = re.compile(
    r"^set interfaces (\S+) unit (\d+) family inet address "
    r"(\d{1,3}(?:\.\d{1,3}){3})/\d+$"
)


def units_of_two_tags(codec: str, text: str) -> dict[tuple[int, int], str]:
    """(outer, inner) -> the IPv4 address of each sub-interface of two
    tags in *text*, read by its grammar (:data:`TWO_TAGS`), not by its
    parser."""
    found: dict[tuple[int, int], str] = {}
    lines = text.splitlines()
    if codec == "juniper_junos":
        tags: dict[tuple[str, str], tuple[int, int]] = {}
        addresses: dict[tuple[str, str], str] = {}
        for line in lines:
            m = TWO_TAGS[codec].match(line)
            if m:
                tags[(m[1], m[2])] = (int(m[3]), int(m[4]))
            a = _JUNOS_ADDRESS.match(line)
            if a:
                addresses.setdefault((a[1], a[2]), a[3])
        for unit, pair in tags.items():
            found[pair] = addresses.get(unit, "")
        return found
    pair: tuple[int, int] | None = None
    address = ""
    for line in [*lines, "interface END"]:
        if line.startswith("interface "):
            if pair is not None:
                found[pair] = address
            pair, address = None, ""
            continue
        m = TWO_TAGS[codec].match(line)
        if m:
            pair = (int(m[1]), int(m[2]))
        a = _ADDRESS.search(line)
        if a and not address:
            address = a[1]
    return found


def _job(source: str, target: str, text: str):
    return run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map={},
    )


# --- the committed capture ---------------------------------------------


def capture_problems(target: str) -> list[str]:
    """What the capture's units are on *target*, where it is not each
    unit with both its tags and its address."""
    text = CAPTURE.read_text(encoding="utf-8")
    problems = []
    if units_of_two_tags("cisco_iosxe_cli", text) != CAPTURE_UNITS:
        problems.append("the reader does not read the capture as typed")
    got = units_of_two_tags(target, _job("cisco_iosxe_cli", target, text).rendered)
    if got != CAPTURE_UNITS:
        problems.append(f"{target}: {sorted(got.items())}")
    return problems


@pytest.mark.parametrize("target", sorted(TWO_TAGS))
def test_the_capture_keeps_both_tags(target: str) -> None:
    assert capture_problems(target) == []


def test_the_capture_check_sees_the_first_id_read_alone(monkeypatch) -> None:
    """The old reading: the outer tag, and nothing of the inner one."""
    def first_id(statement: str):
        words = statement.split()
        return (int(words[2]), None) if words[2].isdigit() else None

    monkeypatch.setattr(iosxe_parse, "second_dot1q_tags", first_id)
    assert capture_problems("cisco_iosxe_cli") != []


def test_the_capture_tree_holds_the_pairs() -> None:
    tree = get_codec("cisco_iosxe_cli").parse(CAPTURE.read_text(encoding="utf-8"))
    pairs = {
        (i.dot1q_vlan, i.dot1q_inner_vlan): i.ipv4_addresses[0].ip
        for i in tree.interfaces if i.dot1q_inner_vlan is not None
    }
    assert pairs == CAPTURE_UNITS


# --- each source grammar onto each target that has a form ---------------

#: A sub-interface of tags 20 and 30, address 203.0.113.1, beside one
#: of tag 40, in each grammar that has a form for it.
SOURCES = {
    "cisco_iosxe_cli": (
        "hostname r1\n!\ninterface GigabitEthernet0/0/1.20\n"
        " encapsulation dot1Q 20 second-dot1q 30\n"
        " ip address 203.0.113.1 255.255.255.0\n!\n"
        "interface GigabitEthernet0/0/1.40\n encapsulation dot1Q 40\n"
        " ip address 192.0.2.129 255.255.255.192\n!\nend\n"
    ),
    "cisco_iosxr": (
        "hostname r1\n!\ninterface GigabitEthernet0/0/0/1.20\n"
        " encapsulation dot1q 20 second-dot1q 30\n"
        " ipv4 address 203.0.113.1 255.255.255.0\n!\n"
        "interface GigabitEthernet0/0/0/1.40\n encapsulation dot1q 40\n"
        " ipv4 address 192.0.2.129 255.255.255.192\n!\nend\n"
    ),
    "arista_eos": (
        "hostname r1\n!\ninterface Ethernet1.20\n"
        "   encapsulation dot1q vlan 20 inner 30\n"
        "   ip address 203.0.113.1/24\n!\n"
        "interface Ethernet1.40\n   encapsulation dot1q vlan 40\n"
        "   ip address 192.0.2.129/26\n!\nend\n"
    ),
    "juniper_junos": (
        "set system host-name r1\n"
        "set interfaces ge-0/0/1 flexible-vlan-tagging\n"
        "set interfaces ge-0/0/1 unit 20 vlan-tags outer 0x8100.20 inner 0x8100.30\n"
        "set interfaces ge-0/0/1 unit 20 family inet address 203.0.113.1/24\n"
        "set interfaces ge-0/0/1 unit 40 vlan-id 40\n"
        "set interfaces ge-0/0/1 unit 40 family inet address 192.0.2.129/26\n"
    ),
}


@pytest.mark.parametrize("source", sorted(SOURCES))
@pytest.mark.parametrize("target", sorted(TWO_TAGS))
def test_each_grammar_onto_each_target(source: str, target: str) -> None:
    rendered = _job(source, target, SOURCES[source]).rendered
    assert units_of_two_tags(target, rendered) == {(20, 30): "203.0.113.1"}
    # The unit of one tag is not given a second.
    back = get_codec(target).parse(rendered)
    one = [i for i in back.interfaces if i.dot1q_vlan == 40]
    assert [i.dot1q_inner_vlan for i in one] == [None]


#: The public codecs with no form for an inner tag, typed by hand: a
#: job onto one of them is held for it.
NO_INNER_FORM = {
    "aruba_aoscx", "aruba_aoss", "cisco_iosxe", "cisco_nxos", "dell_os10",
    "fortigate_cli", "mikrotik_routeros", "opnsense", "vyos",
}


def test_the_matrices_say_which() -> None:
    supported = {
        c for c in list_public_codecs()
        if get_codec(c).capabilities.classify(INNER) == "supported"
    }
    assert supported == set(TWO_TAGS)
    assert set(list_public_codecs()) - supported == NO_INNER_FORM


@pytest.mark.parametrize("target", sorted(NO_INNER_FORM))
def test_a_target_with_no_form_holds_the_job(target: str) -> None:
    job = _job("cisco_iosxe_cli", target, SOURCES["cisco_iosxe_cli"])
    assert job.status != MigrationJobStatus.completed
    assert INNER in [u.path for u in job.validation.unsupported_paths]


# --- a statement that is not read whole -----------------------------------

_ROW = (
    " -- not one 802.1Q tag and at most one inner tag, so the "
    "sub-interface is not translated"
)


def _ios(statement: str) -> str:
    return SOURCES["cisco_iosxe_cli"].replace(
        "encapsulation dot1Q 20 second-dot1q 30", statement,
    )


def _xr(statement: str) -> str:
    return SOURCES["cisco_iosxr"].replace(
        "encapsulation dot1q 20 second-dot1q 30", statement,
    )


def _eos(statement: str) -> str:
    return SOURCES["arista_eos"].replace(
        "encapsulation dot1q vlan 20 inner 30", statement,
    )


def _junos(*statements: str) -> str:
    return SOURCES["juniper_junos"].replace(
        "set interfaces ge-0/0/1 unit 20 vlan-tags outer 0x8100.20 inner 0x8100.30\n",
        "".join(f"set interfaces ge-0/0/1 unit 20 {s}\n" for s in statements),
    )


#: (codec, text, the row), typed by hand.  Each statement matches more
#: than one tag, or a tag that is not 802.1Q, or none.
LEFT_OUT = [
    ("cisco_iosxe_cli", _ios("encapsulation dot1Q 20 second-dot1q any"),
     "interface GigabitEthernet0/0/1.20: encapsulation dot1Q 20 second-dot1q any"),
    ("cisco_iosxe_cli", _ios("encapsulation dot1Q 20 second-dot1q 100-200"),
     "interface GigabitEthernet0/0/1.20: encapsulation dot1Q 20 second-dot1q 100-200"),
    ("cisco_iosxe_cli", _ios("encapsulation dot1Q 20 second-dot1q 100,200"),
     "interface GigabitEthernet0/0/1.20: encapsulation dot1Q 20 second-dot1q 100,200"),
    ("cisco_iosxr", _xr("encapsulation dot1ad 20 dot1q 30"),
     "interface GigabitEthernet0/0/0/1.20: encapsulation dot1ad 20 dot1q 30"),
    ("cisco_iosxr", _xr("encapsulation dot1q 20 second-dot1q any"),
     "interface GigabitEthernet0/0/0/1.20: encapsulation dot1q 20 second-dot1q any"),
    ("cisco_iosxr", _xr("encapsulation dot1q 20-30"),
     "interface GigabitEthernet0/0/0/1.20: encapsulation dot1q 20-30"),
    ("arista_eos", _eos("encapsulation dot1q vlan 20 inner 30-40"),
     "interface Ethernet1.20: encapsulation dot1q vlan 20 inner 30-40"),
    ("arista_eos", _eos("encapsulation vlan"),
     "interface Ethernet1.20: encapsulation vlan"),
    ("juniper_junos", _junos("vlan-tags outer 0x88a8.20 inner 30"),
     "interfaces ge-0/0/1 unit 20: vlan-tags outer 0x88a8.20 inner 30"),
    ("juniper_junos", _junos("vlan-tags outer 20 inner-range 30-40"),
     "interfaces ge-0/0/1 unit 20: vlan-tags outer 20 inner-range 30-40"),
    ("juniper_junos", _junos("vlan-id-range 100-200"),
     "interfaces ge-0/0/1 unit 20: vlan-id-range 100-200"),
    ("juniper_junos", _junos("vlan-id none"),
     "interfaces ge-0/0/1 unit 20: vlan-id none"),
    ("juniper_junos", _junos("vlan-id 20", "vlan-tags outer 20 inner 30"),
     "interfaces ge-0/0/1 unit 20: vlan-id 20; vlan-tags outer 20 inner 30"),
]


def left_out_problems(codec: str, text: str, row: str) -> list[str]:
    problems = []
    tree = get_codec(codec).parse(text)
    addresses = {a.ip for i in tree.interfaces for a in i.ipv4_addresses}
    if "203.0.113.1" in addresses:
        problems.append("the sub-interface is in the tree")
    if "192.0.2.129" not in addresses:
        problems.append("its neighbour of one tag is not")
    if row + _ROW not in tree.dropped_tier3_sections:
        problems.append(f"no row: {tree.dropped_tier3_sections}")
    return problems


@pytest.mark.parametrize(
    ("codec", "text", "row"), LEFT_OUT, ids=[r for _c, _t, r in LEFT_OUT],
)
def test_a_statement_not_read_whole_leaves_it_out(codec, text, row) -> None:
    assert left_out_problems(codec, text, row) == []


@pytest.mark.parametrize(
    ("codec", "text", "row"), LEFT_OUT, ids=[r for _c, _t, r in LEFT_OUT],
)
def test_on_every_target_it_is_said_and_not_written(codec, text, row) -> None:
    for target in list_public_codecs():
        job = _job(codec, target, text)
        assert "203.0.113.1" not in job.rendered, target
        assert row + _ROW in job.dropped_tier3_sections, target


def test_the_left_out_check_sees_a_first_id(monkeypatch) -> None:
    """With the pass that leaves a stanza out gone, IOS-XE reads
    ``second-dot1q any`` as nothing it can write, and the
    sub-interface is in the tree under its outer tag again."""
    monkeypatch.setattr(iosxe_parse, "without_unread_tags", lambda raw, _a, _b: (raw, []))
    codec, text, row = LEFT_OUT[0]
    assert left_out_problems(codec, text, row) != []


def test_a_submodes_statement_is_not_the_stanzas() -> None:
    """An IOS-XE ``service instance`` has an ``encapsulation`` of its
    own, a line deeper: it is not the port's tag statement, and the
    port is neither left out nor tagged."""
    text = (
        "hostname r1\n!\ninterface GigabitEthernet0/0/2\n"
        " description to a customer\n"
        " service instance 10 ethernet\n"
        "  encapsulation dot1q 10 second-dot1q any\n"
        " !\n!\nend\n"
    )
    tree = get_codec("cisco_iosxe_cli").parse(text)
    port = next(i for i in tree.interfaces if i.name == "GigabitEthernet0/0/2")
    assert (port.dot1q_vlan, port.dot1q_inner_vlan) == (None, None)
    assert port.description == "to a customer"
    assert not [r for r in tree.dropped_tier3_sections if r.endswith(_ROW)]


# --- VyOS QinQ ---------------------------------------------------------------

VYOS_SET = (
    "set system host-name r1\n"
    "set interfaces ethernet eth0 address 10.1.0.1/24\n"
    "set interfaces ethernet eth0 vif-s 1000 vif-c 20 address 192.0.2.1/24\n"
    "set interfaces ethernet eth0 vif-s 1000 vif-c 21 address 192.0.2.65/26\n"
    "set interfaces ethernet eth0 vif 30 address 192.0.2.129/26\n"
)
VYOS_BRACE = (
    "interfaces {\n    ethernet eth0 {\n        address 10.1.0.1/24\n"
    "        vif-s 1000 {\n            vif-c 20 {\n"
    "                address 192.0.2.1/24\n            }\n        }\n"
    "        vif 30 {\n            address 192.0.2.129/26\n        }\n"
    "    }\n}\nsystem {\n    host-name r1\n}\n"
)
VYOS_ROW = (
    "interfaces ethernet eth0 vif-s 1000: an 802.1ad service VLAN; it "
    "and its vif-c sub-interfaces are not translated"
)


@pytest.mark.parametrize("text", [VYOS_SET, VYOS_BRACE], ids=["set", "brace"])
def test_a_vyos_service_vlan_is_said(text: str) -> None:
    tree = get_codec("vyos").parse(text)
    assert tree.dropped_tier3_sections.count(VYOS_ROW) == 1
    vlans = {i.name: i.dot1q_vlan for i in tree.interfaces if i.dot1q_vlan}
    assert vlans == {"eth0.30": 30}


# --- the VLAN map --------------------------------------------------------------


def test_a_dropped_outer_tag_takes_the_inner_with_it() -> None:
    intent = CanonicalIntent(interfaces=[CanonicalInterface(
        name="Gi0/1.20", dot1q_vlan=20, dot1q_inner_vlan=30,
        ipv4_addresses=[CanonicalIPv4Address(ip="203.0.113.1", prefix_length=24)],
    )])
    result = translate_vlan_ids(intent, {20: None})
    iface = intent.interfaces[0]
    assert (iface.dot1q_vlan, iface.dot1q_inner_vlan) == (None, None)
    assert result.warnings == [
        "vlan_rename: interface 'Gi0/1.20' had 802.1Q sub-interface VLAN "
        "20 which was dropped — tag and its inner tag 30 cleared"
    ]


def test_a_renumbered_outer_tag_keeps_its_inner() -> None:
    """The inner tag is a customer's, not a VLAN of the device: a map
    moves the outer one only."""
    intent = CanonicalIntent(interfaces=[CanonicalInterface(
        name="Gi0/1.20", dot1q_vlan=20, dot1q_inner_vlan=30,
    )])
    translate_vlan_ids(intent, {20: 120, 30: 130})
    iface = intent.interfaces[0]
    assert (iface.dot1q_vlan, iface.dot1q_inner_vlan) == (120, 30)


# --- the Junos device statement -----------------------------------------------


def _unit(name: str, outer: int | None, inner: int | None = None, ip: str = ""):
    return CanonicalInterface(
        name=name, dot1q_vlan=outer, dot1q_inner_vlan=inner,
        ipv4_addresses=(
            [CanonicalIPv4Address(ip=ip, prefix_length=24)] if ip else []
        ),
    )


#: (the tree's interfaces, the device lines the output must hold), from
#: Juniper's "Binding VLAN IDs to Logical Interfaces" and "Configuring
#: Tagged Interface with multiple tagged vlans and native vlan".
DEVICE_LINES = [
    ([_unit("ge-0/0/1.10", 10), _unit("ge-0/0/1.20", 20)],
     ["set interfaces ge-0/0/1 vlan-tagging"]),
    ([_unit("ge-0/0/1.10", 10, 100), _unit("ge-0/0/1.20", 20, 200)],
     ["set interfaces ge-0/0/1 stacked-vlan-tagging"]),
    ([_unit("ge-0/0/1.10", 10), _unit("ge-0/0/1.20", 20, 200)],
     ["set interfaces ge-0/0/1 flexible-vlan-tagging"]),
    ([_unit("ae1.10", 10)], ["set interfaces ae1 vlan-tagging"]),
    ([_unit("reth0.10", 10)], ["set interfaces reth0 vlan-tagging"]),
    ([_unit("xe-0/0/6:2.10", 10)], ["set interfaces xe-0/0/6:2 vlan-tagging"]),
    ([CanonicalInterface(name="ge-0/0/1.10", dot1q_vlan=10, dot1q_native=True)],
     ["set interfaces ge-0/0/1 flexible-vlan-tagging",
      "set interfaces ge-0/0/1 native-vlan-id 10"]),
    ([_unit("ge-0/0/1", None, ip="192.0.2.1"), _unit("ge-0/0/1.10", 10)],
     ["set interfaces ge-0/0/1 vlan-tagging",
      "# review: ge-0/0/1 unit 0 has no tag, beside units under "
      "vlan-tagging: Juniper documents untagged frames on such a device "
      "only through native-vlan-id (with flexible-vlan-tagging) and a "
      "unit of that vlan-id -- not established that a unit with no tag "
      "commits there"]),
]

_DEVICE_LINE = re.compile(
    r"^(?:set interfaces \S+ (?:(?:flexible-|stacked-)?vlan-tagging|native-vlan-id \d+)"
    r"|# review: \S+ unit \d+ has no tag.*)$"
)


def device_line_problems(interfaces: list[CanonicalInterface], lines: list[str]) -> list[str]:
    rendered = get_codec("juniper_junos").render(
        CanonicalIntent(interfaces=[i.model_copy() for i in interfaces]),
    )
    got = [ln for ln in rendered.splitlines() if _DEVICE_LINE.match(ln)]
    return [] if got == lines else [f"{got}"]


@pytest.mark.parametrize(("interfaces", "lines"), DEVICE_LINES)
def test_a_tagged_device_is_told(interfaces, lines) -> None:
    assert device_line_problems(interfaces, lines) == []


def test_the_device_check_sees_a_device_not_told(monkeypatch) -> None:
    monkeypatch.setattr(
        junos_render, "_device_tags",
        lambda _ifaces: junos_render._DeviceTags({}, {}, {}, set()),
    )
    interfaces, lines = DEVICE_LINES[0]
    assert device_line_problems(interfaces, lines) != []


def test_a_unit_of_a_tunnel_or_a_loopback_tells_no_device() -> None:
    """``lo0`` and a tunnel are not told apart by a tag on the wire,
    and Juniper puts the statement on an Ethernet interface."""
    assert device_line_problems([_unit("lo0.10", 10), _unit("gr-0/0/0.10", 10)], []) == []


def test_a_device_is_told_once() -> None:
    rendered = get_codec("juniper_junos").render(CanonicalIntent(interfaces=[
        _unit("ge-0/0/1", 5, ip="192.0.2.1"), _unit("ge-0/0/1.10", 10),
        _unit("ge-0/0/1.20", 20),
    ]))
    assert rendered.splitlines().count("set interfaces ge-0/0/1 vlan-tagging") == 1
    assert "set interfaces ge-0/0/1 unit 0 vlan-id 5" in rendered.splitlines()


def test_junos_reads_its_own_tags_back() -> None:
    interfaces = [
        _unit("ge-0/0/1", 5, ip="192.0.2.1"), _unit("ge-0/0/1.10", 10),
        _unit("ge-0/0/1.20", 20, 200),
        CanonicalInterface(
            name="ge-0/0/2.7", dot1q_vlan=7, dot1q_native=True,
            ipv4_addresses=[CanonicalIPv4Address(ip="198.51.100.1", prefix_length=24)],
        ),
    ]
    codec = get_codec("juniper_junos")
    back = codec.parse(codec.render(CanonicalIntent(interfaces=interfaces)))
    tags = {
        i.name: (i.dot1q_vlan, i.dot1q_inner_vlan, i.dot1q_native)
        for i in back.interfaces
    }
    assert tags == {
        "ge-0/0/1": (5, None, False), "ge-0/0/1.10": (10, None, False),
        "ge-0/0/1.20": (20, 200, False), "ge-0/0/2": (None, None, False),
        "ge-0/0/2.7": (7, None, True),
    }
