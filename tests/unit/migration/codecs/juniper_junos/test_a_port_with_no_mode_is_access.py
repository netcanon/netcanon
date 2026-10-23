"""A Junos port that states no mode is an access port.

``family ethernet-switching vlan members X`` with no ``interface-mode``
(ELS) or ``port-mode`` line was read as a TRUNK, on the word of a
comment that the commit validator treats it so.  Juniper says the
opposite: "when you boot the switch and do not explicitly configure a
port mode, all interfaces on the switch are in access mode"
(Configuring Gigabit Ethernet Interfaces (CLI Procedure), the ELS
page; the ``port-mode`` statement's Default says the same).  An access
port of VLAN 10 came out as a trunk of VLAN 10 on every target, in a
job that said ``completed``.

A port with no mode that names more than one VLAN is written in its
first VLAN, and one row of ``dropped_tier3_sections`` says so for all
such ports -- as does a port that states ``interface-mode access`` and
names several, which was left to its first VLAN in silence before.

The output is read as text, by a reader typed here for IOS-XE's
grammar, and with the target's parser.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.codecs.juniper_junos.parse import IN_SEVERAL_SHOWN
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

JUNOS = get_codec("juniper_junos")

VLANS = "set vlans DATA vlan-id 10\nset vlans VOICE vlan-id 20\n"
MEMBER = "set interfaces {port} unit 0 family ethernet-switching vlan members {vlan}\n"
MODE = "set interfaces {port} unit 0 family ethernet-switching interface-mode {mode}\n"


def _port(text: str, name: str = "ge-0/0/1"):
    return next(i for i in JUNOS.parse(text).interfaces if i.name == name)


def _iosxe_modes(text: str) -> dict[str, tuple[str, str]]:
    """``{interface: (mode, access VLAN)}`` of each IOS-XE stanza that
    states ``switchport mode``."""
    out: dict[str, tuple[str, str]] = {}
    current = None
    for line in text.splitlines():
        head = re.fullmatch(r"interface (\S+)\s*", line)
        if head:
            current = head.group(1)
            continue
        mode = re.fullmatch(r" switchport mode (\S+)\s*", line)
        if current and mode:
            out[current] = (mode.group(1), out.get(current, ("", ""))[1])
        vlan = re.fullmatch(r" switchport access vlan (\d+)\s*", line)
        if current and vlan:
            out[current] = (out.get(current, ("", ""))[0], vlan.group(1))
    return out


def test_no_mode_is_access() -> None:
    port = _port(VLANS + MEMBER.format(port="ge-0/0/1", vlan="DATA"))
    assert (port.switchport_mode, port.access_vlan, port.trunk_allowed_vlans) == ("access", 10, [])


def test_a_numeric_member_with_no_mode() -> None:
    port = _port(VLANS + MEMBER.format(port="ge-0/0/1", vlan="20"))
    assert (port.switchport_mode, port.access_vlan) == ("access", 20)


@pytest.mark.parametrize("mode", ["interface-mode", "port-mode"])
def test_a_stated_mode_is_kept(mode: str) -> None:
    text = (
        VLANS
        + f"set interfaces ge-0/0/1 unit 0 family ethernet-switching {mode} trunk\n"
        + MEMBER.format(port="ge-0/0/1", vlan="DATA")
    )
    port = _port(text)
    assert (port.switchport_mode, port.access_vlan, port.trunk_allowed_vlans) == ("trunk", None, [10])


def test_the_mode_line_after_the_members_line() -> None:
    """Order in a set-form config is free."""
    text = VLANS + MEMBER.format(port="ge-0/0/1", vlan="DATA") + MODE.format(port="ge-0/0/1", mode="trunk")
    assert _port(text).switchport_mode == "trunk"


@pytest.mark.parametrize(
    "members",
    [["DATA", "VOICE"], ["DATA", "10-11"], ["DATA", "all"]],
    ids=["two-names", "a-range", "all"],
)
@pytest.mark.parametrize("stated", [False, True], ids=["no-mode", "access"])
def test_an_access_port_in_several_vlans_is_said(members: list[str], stated: bool) -> None:
    text = VLANS + (MODE.format(port="ge-0/0/1", mode="access") if stated else "")
    text += "".join(MEMBER.format(port="ge-0/0/1", vlan=m) for m in members)
    tree = JUNOS.parse(text)
    port = next(i for i in tree.interfaces if i.name == "ge-0/0/1")
    assert (port.switchport_mode, port.access_vlan) == ("access", 10)
    rows = [r for r in tree.dropped_tier3_sections if "more than one VLAN" in r]
    assert rows == [
        "interfaces ge-0/0/1: family ethernet-switching vlan members -- an access "
        "port (no interface-mode is access) that names more than one VLAN is "
        "written in its first VLAN only"
    ]


def test_one_vlan_twice_is_one_vlan() -> None:
    text = VLANS + MEMBER.format(port="ge-0/0/1", vlan="DATA") + MEMBER.format(port="ge-0/0/1", vlan="10")
    tree = JUNOS.parse(text)
    assert not [r for r in tree.dropped_tier3_sections if "more than one VLAN" in r]


def test_the_row_is_one_for_many_ports() -> None:
    ports = [f"ge-0/0/{n}" for n in range(IN_SEVERAL_SHOWN + 4)]
    text = VLANS + "".join(
        MEMBER.format(port=p, vlan="DATA") + MEMBER.format(port=p, vlan="VOICE") for p in ports
    )
    rows = [r for r in JUNOS.parse(text).dropped_tier3_sections if "more than one VLAN" in r]
    assert len(rows) == 1
    assert rows[0].startswith(f"interfaces {', '.join(ports[:IN_SEVERAL_SHOWN])} and 4 more: ")


def test_an_access_port_reaches_iosxe_as_one() -> None:
    text = VLANS + MEMBER.format(port="ge-0/0/1", vlan="DATA")
    job = run_plan_with_checked_names(JUNOS, get_codec("cisco_iosxe_cli"), text, port_rename_map={})
    assert job.rendered, (job.status, job.error)
    modes = _iosxe_modes(job.rendered)
    assert list(modes.values()) == [("access", "10")]
    back = [i for i in get_codec("cisco_iosxe_cli").parse(job.rendered).interfaces if i.switchport_mode]
    assert [(i.switchport_mode, i.access_vlan) for i in back] == [("access", 10)]


@pytest.mark.parametrize("target", sorted(list_public_codecs()))
def test_no_target_is_given_a_trunk(target: str) -> None:
    """Whatever a target writes for an access port, it does not write
    one of VLAN 10 as a trunk."""
    text = VLANS + MEMBER.format(port="ge-0/0/1", vlan="DATA")
    job = run_plan_with_checked_names(JUNOS, get_codec(target), text, port_rename_map={})
    if not job.rendered:
        return
    for iface in get_codec(target).parse(job.rendered).interfaces:
        assert iface.switchport_mode != "trunk", (target, iface.name)
