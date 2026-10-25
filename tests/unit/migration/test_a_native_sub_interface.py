"""A routed port's untagged frames go to the sub-interface that says so.

Junos ``native-vlan-id <tag>`` on a device whose units carry tags, with
the unit of ``vlan-id <tag>``, and IOS-XE ``encapsulation dot1Q <tag>
native`` on a sub-interface, state one fact: which sub-interface takes
the untagged frames that arrive on its port ("The logical interface on
which untagged packets are to be received must be configured with the
same native VLAN ID", Juniper; "To make a subinterface the default
handler of untagged packets coming to the port, use this keyword",
Cisco).  The tree held the Junos statement as the device's
``trunk_native_vlan``, a switchport's field, and IOS-XE took its own
out of the text with a row.  So a Junos router's native sub-interface
was written onto IOS-XE as ``switchport trunk native vlan`` on a routed
port, and left out by EOS and NX-OS, in jobs that said ``completed``.

The tree now has ``dot1q_native`` on the sub-interface.  The two
targets that have a form write it; every other target reports
``/interfaces/interface/dot1q-native`` unsupported, so the job is not
``completed``.  Each output is read here as text, by a reader per
grammar written here, and the sub-interface is found by its address,
not its name.  Each check is handed the defect it is for.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

_PATH = "/interfaces/interface/dot1q-native"

#: The targets that write a native sub-interface, typed by hand.
_STATES = frozenset({"cisco_iosxe_cli", "juniper_junos"})

_JUNOS = """set system host-name r1
set interfaces ge-0/0/1 vlan-tagging
set interfaces ge-0/0/1 native-vlan-id 100
set interfaces ge-0/0/1 unit 100 vlan-id 100
set interfaces ge-0/0/1 unit 100 family inet address 10.1.0.1/24
set interfaces ge-0/0/1 unit 200 vlan-id 200
set interfaces ge-0/0/1 unit 200 family inet address 10.2.0.1/24
"""

_IOSXE = """hostname r1
!
interface GigabitEthernet0/0/1
 no ip address
!
interface GigabitEthernet0/0/1.100
 encapsulation dot1Q 100 native
 ip address 10.1.0.1 255.255.255.0
!
interface GigabitEthernet0/0/1.200
 encapsulation dot1Q 200
 ip address 10.2.0.1 255.255.255.0
!
end
"""

_SOURCES = {"juniper_junos": _JUNOS, "cisco_iosxe_cli": _IOSXE}

#: The address of the sub-interface that takes the untagged frames,
#: and of the one that does not, in both sources.
_NATIVE = "10.1.0.1"
_TAGGED = "10.2.0.1"


def _iosxe_stanzas(text: str) -> list[list[str]]:
    """Each ``interface`` stanza: its header and the indented lines
    after it."""
    stanzas: list[list[str]] = []
    for line in text.splitlines():
        if line.startswith("interface "):
            stanzas.append([line])
        elif stanzas and line[:1].isspace():
            stanzas[-1].append(line)
        elif line.strip():
            stanzas.append([])
    return [s for s in stanzas if s]


def _iosxe_native_tags(text: str) -> dict[str, int | None]:
    """By the address on it, the tag each IOS-XE sub-interface states,
    and whether it says ``native``: ``{address: tag}`` for one that
    does, ``{address: None}`` for one that does not."""
    found: dict[str, int | None] = {}
    for stanza in _iosxe_stanzas(text):
        address = tag = None
        native = False
        for line in stanza[1:]:
            m = re.fullmatch(r" ip address (\S+) \S+", line)
            if m:
                address = m.group(1)
            m = re.fullmatch(r" encapsulation dot1Q (\d+)( native)?", line)
            if m:
                tag, native = int(m.group(1)), bool(m.group(2))
        if address is not None and tag is not None:
            found[address] = tag if native else None
    return found


def _junos_native_tags(text: str) -> dict[str, int | None]:
    """By the address on it, the ``vlan-id`` of each Junos unit, where
    its device's ``native-vlan-id`` is that tag and the device says
    ``flexible-vlan-tagging``; ``None`` for every other unit."""
    lines = set(text.splitlines())
    tags: dict[tuple[str, str], int] = {}
    addresses: dict[str, tuple[str, str]] = {}
    for line in lines:
        m = re.fullmatch(r"set interfaces (\S+) unit (\d+) vlan-id (\d+)", line)
        if m:
            tags[(m.group(1), m.group(2))] = int(m.group(3))
        m = re.fullmatch(
            r"set interfaces (\S+) unit (\d+) family inet address ([\d.]+)/\d+",
            line,
        )
        if m:
            addresses[m.group(3)] = (m.group(1), m.group(2))
    found: dict[str, int | None] = {}
    for address, (device, unit) in addresses.items():
        tag = tags.get((device, unit))
        if tag is None:
            continue
        native = (
            f"set interfaces {device} native-vlan-id {tag}" in lines
            and f"set interfaces {device} flexible-vlan-tagging" in lines
        )
        found[address] = tag if native else None
    return found


_READERS = {
    "cisco_iosxe_cli": _iosxe_native_tags,
    "juniper_junos": _junos_native_tags,
}


def _says_a_switchport_native(text: str) -> list[str]:
    """Lines that state VLAN 100 as a switchport's untagged VLAN, in
    any grammar: a line with ``native``, ``untagged`` or ``pvid`` and
    the id."""
    return [
        line for line in text.splitlines()
        if re.search(r"native|untagged|pvid", line, re.IGNORECASE)
        and re.search(r"(?<!\d)100(?!\d)", line)
    ]


def _run(source: str, target: str, text: str | None = None, **kw):
    return run_plan_with_checked_names(
        get_codec(source), get_codec(target), text or _SOURCES[source],
        port_rename_map={}, **kw,
    )


def _unsupported(job) -> set[str]:
    return {p.path for p in job.validation.unsupported_paths}


# ---------------------------------------------------------------------------
# The readers, each handed the defect it is for
# ---------------------------------------------------------------------------


def test_the_iosxe_reader_sees_a_sub_interface_without_native() -> None:
    assert _iosxe_native_tags(_IOSXE) == {_NATIVE: 100, _TAGGED: None}
    assert _iosxe_native_tags(_IOSXE.replace(" 100 native", " 100")) == {
        _NATIVE: None, _TAGGED: None,
    }


def test_the_junos_reader_needs_the_statement_and_the_tagging() -> None:
    told = _JUNOS.replace("vlan-tagging", "flexible-vlan-tagging")
    assert _junos_native_tags(told) == {_NATIVE: 100, _TAGGED: None}
    assert _junos_native_tags(_JUNOS)[_NATIVE] is None
    assert _junos_native_tags(
        told.replace("native-vlan-id 100", "native-vlan-id 200"),
    )[_NATIVE] is None


def test_the_switchport_check_sees_the_old_line() -> None:
    assert _says_a_switchport_native(" switchport trunk native vlan 100\n")
    assert not _says_a_switchport_native(" encapsulation dot1Q 1000 native\n")


# ---------------------------------------------------------------------------
# The parsers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_the_parser_marks_the_sub_interface(source: str) -> None:
    tree = get_codec(source).parse(_SOURCES[source])
    native = {
        i.ipv4_addresses[0].ip: i.dot1q_vlan
        for i in tree.interfaces if i.dot1q_native
    }
    assert native == {_NATIVE: 100}
    # And no switchport's native VLAN is made of it.
    assert all(i.trunk_native_vlan is None for i in tree.interfaces)
    assert not tree.dropped_tier3_sections


def test_a_junos_native_vlan_that_names_no_unit_is_said() -> None:
    text = _JUNOS.replace("native-vlan-id 100", "native-vlan-id 300")
    tree = get_codec("juniper_junos").parse(text)
    assert not any(i.dot1q_native for i in tree.interfaces)
    assert all(i.trunk_native_vlan is None for i in tree.interfaces)
    assert tree.dropped_tier3_sections == [
        "interfaces ge-0/0/1 native-vlan-id 300 -- no unit of that one "
        "vlan-id is in the output to take the device's untagged frames, so "
        "the statement is not translated"
    ]


def test_a_second_iosxe_native_sub_interface_is_said() -> None:
    text = _IOSXE.replace("dot1Q 200", "dot1Q 200 native")
    tree = get_codec("cisco_iosxe_cli").parse(text)
    assert [i.name for i in tree.interfaces if i.dot1q_native] == [
        "GigabitEthernet0/0/1.100",
    ]
    assert tree.dropped_tier3_sections == [
        "interface GigabitEthernet0/0/1.200: encapsulation dot1Q 200 "
        "native -- a second native sub-interface of GigabitEthernet0/0/1; "
        "written without native"
    ]


def test_a_switchport_native_vlan_stays_a_switchports() -> None:
    """A Junos trunk's ``native-vlan-id`` is its native VLAN, not a
    unit's."""
    text = (
        "set interfaces ge-0/0/2 native-vlan-id 10\n"
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching "
        "interface-mode trunk\n"
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching "
        "vlan members 10\n"
        "set vlans V10 vlan-id 10\n"
    )
    tree = get_codec("juniper_junos").parse(text)
    port = next(i for i in tree.interfaces if i.name == "ge-0/0/2")
    assert (port.switchport_mode, port.trunk_native_vlan) == ("trunk", 10)
    assert not any(i.dot1q_native for i in tree.interfaces)


# ---------------------------------------------------------------------------
# Every public codec as a target
# ---------------------------------------------------------------------------


_PAIRS = [
    (source, target)
    for source in sorted(_SOURCES) for target in sorted(list_public_codecs())
]


def test_the_targets_that_state_it_are_the_codecs_that_say_so() -> None:
    declared = {
        name for name in list_public_codecs()
        if _PATH in get_codec(name).capabilities.supported
    }
    assert declared == _STATES


@pytest.mark.parametrize(("source", "target"), _PAIRS)
def test_every_target_states_it_or_says_it(source: str, target: str) -> None:
    job = _run(source, target)
    text = job.rendered or ""
    # Never as a switchport's native VLAN, on any target.
    assert not _says_a_switchport_native(
        "\n".join(
            line for line in text.splitlines()
            if not re.search(r"dot1Q 100 native|native-vlan-id 100", line)
        )
    ), text
    if target in _STATES:
        assert _READERS[target](text) == {_NATIVE: 100, _TAGGED: None}, text
        assert _PATH not in _unsupported(job)
    else:
        assert _PATH in _unsupported(job)
        assert job.status != MigrationJobStatus.completed


@pytest.mark.parametrize("target", sorted(_STATES))
@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_the_output_reads_back(source: str, target: str) -> None:
    text = _run(source, target).rendered or ""
    tree = get_codec(target).parse(text)
    native = {
        i.ipv4_addresses[0].ip: i.dot1q_vlan
        for i in tree.interfaces if i.dot1q_native and i.ipv4_addresses
    }
    assert native == {_NATIVE: 100}


# ---------------------------------------------------------------------------
# The VLAN map
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", sorted(_STATES))
@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_a_renumbered_tag_keeps_its_native(source: str, target: str) -> None:
    job = _run(source, target, vlan_rename_map={100: 110})
    assert _READERS[target](job.rendered or "") == {_NATIVE: 110, _TAGGED: None}


@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_a_dropped_tag_takes_its_native_with_it(source: str) -> None:
    job = _run(source, "cisco_iosxe_cli", vlan_rename_map={100: None})
    text = job.rendered or ""
    assert " native" not in text.replace("dot1Q 200", ""), text
    assert any("dropped" in w and "100" in w for w in job.warnings)
