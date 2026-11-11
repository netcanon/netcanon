"""A number AOS-CX, OS10, EOS or RouterOS counts from 1 is never written as 0.

Each of the first three counts a port, a stack member and a LAG from 1.
``vsf_switch_port_name``, ``os10_port_name`` and
``fixed_switch_port_name`` refuse a port below 1 (each module says
which vendor guide it rests on).  HPE gives an AOS-CX LAG id of 1 to
256, Dell an OS10 port-channel of 1 to 128, and Arista an EOS channel
group of 1 through 2000.  OS10 has no stacking, so its node is always
1, and it has one management port, ``mgmt1/1/1``.

A Junos FPC, PIC port and ``ae`` are numbered from 0, as are an IOS XR
slot and an IOS-XE router's slot.  With no devices declared, the
name-shape translator wrote such a port ``0/1/3`` (AOS-CX),
``ethernet0/1/3`` (OS10) or ``Ethernet0`` (EOS), and ``ae0`` as ``lag
0``, ``port-channel0`` or ``Port-Channel0``.  No such switch has those
names, and the jobs said ``completed``.  A 0 is now written as 1.  Where
that gives two source names one name, the job says so.

RouterOS counts a port from 1 as well: every factory name of the
committed exports, target profiles and model families does, and with
no configuration of its own a router puts its address "on ether1, or
combo1, or sfp1" (MikroTik, Default configurations).  Its names are
flat (``ether3``), so a port of member 0 or 1 and module 0 is written
by its port number alone, and a port 0 there -- a VyOS ``eth0``, an
OPNsense ``igb0``, a Junos ``ge-0/0/0`` -- was written ``ether0`` or
``sfp-sfpplus0``, a port no router has.  It is written as port 1, and
``bond0`` was already ``bond1``.

Each name is read by a reader typed here, not by the codec's own
classifier, which reads a 0 as readily as a 1.
"""

from __future__ import annotations

import itertools
import re

import pytest

from netcanon.migration.canonical.port_names import PortIdentity
from netcanon.migration.codecs.arista_eos.port_names import fixed_switch_port_name
from netcanon.migration.codecs.aruba_aoscx.port_names import vsf_switch_port_name
from netcanon.migration.codecs.dell_os10.port_names import os10_port_name
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_vlan_members_reach_the_output import _captures

pytestmark = pytest.mark.unit

_TARGETS = ("aruba_aoscx", "dell_os10", "arista_eos", "mikrotik_routeros")

#: What each target calls a port, a LAG and its management port,
#: typed from the vendors' grammars.  A number above what a target
#: takes (a LAG 256 onto OS10) is not what this module is about.
_PORT = {
    "aruba_aoscx": re.compile(r"(\d+)/(\d+)/(\d+)"),
    "dell_os10": re.compile(r"ethernet(\d+)/(\d+)/(\d+)"),
    "arista_eos": re.compile(r"Ethernet(\d+)(?:/(\d+))?"),
    # The cage, then the port, then a breakout lane.  The longer cage
    # names first: ``sfp28-1`` is not ``sfp`` and 28.
    "mikrotik_routeros": re.compile(
        r"(?:sfp-sfpplus|sfp28-|qsfp28-|qsfpplus|ether|combo|sfp)(\d+)(?:-(\d+))?"
    ),
}
_LAG = {
    "aruba_aoscx": re.compile(r"lag (\d+)"),
    "dell_os10": re.compile(r"port-channel(\d+)"),
    "arista_eos": re.compile(r"Port-Channel(\d+)"),
    "mikrotik_routeros": re.compile(r"bond(\d+)"),
}
#: RouterOS has no management port, and its formatter writes none.
_MGMT = {
    "aruba_aoscx": re.compile(r"mgmt"),
    "dell_os10": re.compile(r"mgmt1/1/1"),
    "arista_eos": re.compile(r"Management([1-9]\d*)"),
}


def _numbers(target: str, kind: str, name: str) -> list[int]:
    """The numbers in *name*, read as *target* writes a *kind*; fails
    if the target's grammar has no such name."""
    if kind in ("physical", "breakout"):
        m = _PORT[target].fullmatch(name)
        assert m, (target, kind, name)
        numbers = [int(g) for g in m.groups() if g is not None]
        if target == "dell_os10":
            assert numbers[0] == 1, f"OS10 has no node {numbers[0]}: {name}"
        return numbers
    if kind == "lag":
        m = _LAG[target].fullmatch(name)
        assert m, (target, kind, name)
        return [int(m.group(1))]
    assert kind == "mgmt", kind
    assert _MGMT[target].fullmatch(name), (target, kind, name)
    return [1]


def _job(source: str, target: str, text: str):
    return run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map={},
    )


# ---------------------------------------------------------------------------
# The rule, as each module states it
# ---------------------------------------------------------------------------


def test_each_grammar_refuses_0() -> None:
    with pytest.raises(ValueError, match="1-based"):
        vsf_switch_port_name(member=0, port=2)
    with pytest.raises(ValueError, match="1-based"):
        vsf_switch_port_name(member=1, port=0)
    with pytest.raises(ValueError, match="counts from 1"):
        os10_port_name(port=0)
    with pytest.raises(ValueError, match="counts from 1"):
        fixed_switch_port_name(port=0, multi_lane=False)


# ---------------------------------------------------------------------------
# The formatter, over every number it can be given
# ---------------------------------------------------------------------------

_VALUES = (None, 0, 1, 2, 7)


def _identities():
    for stack, module, port in itertools.product(_VALUES, repeat=3):
        yield PortIdentity(kind="physical", stack=stack, module=module, port=port, original="x")
    for index in _VALUES:
        yield PortIdentity(kind="lag", index=index, original="x")
    for stack, module, port in itertools.product(_VALUES, repeat=3):
        yield PortIdentity(kind="mgmt", stack=stack, module=module, port=port, original="x")
    for port, lane in itertools.product(_VALUES, repeat=2):
        yield PortIdentity(
            kind="breakout", port=port, breakout_lane=lane,
            breakout_parent="Ethernet49", original="x",
        )


@pytest.mark.parametrize("target", _TARGETS)
def test_no_number_the_formatter_writes_is_0(target: str) -> None:
    """Every name the formatter writes for a port, a lane, a LAG or a
    management port is one its target has: each number is at least 1,
    and a number that is at least 1 is kept as it was."""
    codec = get_codec(target)
    written = 0
    for identity in _identities():
        name = codec.format_port_identity(identity)
        if name is None:
            continue
        written += 1
        numbers = _numbers(target, identity.kind, name)
        assert all(n >= 1 for n in numbers), (identity, name)
        if identity.kind == "lag":
            assert numbers == [identity.index or 1], (identity, name)
        elif identity.kind == "physical" and target == "aruba_aoscx":
            assert numbers == [identity.stack or 1, identity.module or 1, identity.port or 1]
        elif identity.kind == "physical" and target == "dell_os10":
            assert numbers == [1, identity.module or 1, identity.port or 1]
        elif identity.kind == "physical" and target == "mikrotik_routeros":
            # One flat number: the port itself on member 0 or 1 and
            # module 0, and a number of its own past 100 elsewhere.
            if (identity.stack or 0) <= 1 and not identity.module:
                assert numbers == [identity.port or 1], (identity, name)
            else:
                assert numbers[0] >= 100, (identity, name)
        elif identity.kind == "physical":
            first = identity.port if identity.port is not None else identity.module
            assert numbers == [first or 1], (identity, name)
    assert written


# ---------------------------------------------------------------------------
# Through the pipeline
# ---------------------------------------------------------------------------

_JUNOS = "set system host-name r1\n"

#: A source name numbered from 0, in a config that gives it an
#: address, and what each target writes it as.
_ONE: dict[str, tuple[str, str, str, dict[str, str]]] = {
    "junos fpc 0": ("juniper_junos", "ge-0/0/3", (
        _JUNOS + "set interfaces ge-0/0/3 unit 0 family inet address 198.51.100.1/24\n"
    ), {"aruba_aoscx": "1/1/3", "dell_os10": "ethernet1/1/3", "arista_eos": "Ethernet3",
        "mikrotik_routeros": "ether3"}),
    "junos port 0": ("juniper_junos", "ge-0/0/0", (
        _JUNOS + "set interfaces ge-0/0/0 unit 0 family inet address 198.51.100.1/24\n"
    ), {"aruba_aoscx": "1/1/1", "dell_os10": "ethernet1/1/1", "arista_eos": "Ethernet1",
        "mikrotik_routeros": "ether1"}),
    "junos 10G port 0": ("juniper_junos", "xe-0/0/0", (
        _JUNOS + "set interfaces xe-0/0/0 unit 0 family inet address 198.51.100.1/24\n"
    ), {"aruba_aoscx": "1/1/1", "dell_os10": "ethernet1/1/1", "arista_eos": "Ethernet1",
        "mikrotik_routeros": "sfp-sfpplus1"}),
    "vyos eth0": ("vyos", "eth0", (
        "set system host-name r1\nset interfaces ethernet eth0 address 198.51.100.1/24\n"
    ), {"aruba_aoscx": "1/1/1", "dell_os10": "ethernet1/1/1", "arista_eos": "Ethernet1",
        "mikrotik_routeros": "ether1"}),
    "junos ae0": ("juniper_junos", "ae0", (
        _JUNOS + "set chassis aggregated-devices ethernet device-count 2\n"
        "set interfaces ge-1/0/5 ether-options 802.3ad ae0\n"
        "set interfaces ae0 unit 0 family inet address 198.51.100.1/24\n"
    ), {"aruba_aoscx": "lag 1", "dell_os10": "port-channel1", "arista_eos": "Port-Channel1",
        "mikrotik_routeros": "bond1"}),
    "ios xr slot 0": ("cisco_iosxr", "GigabitEthernet0/0/0/2", (
        "hostname r1\ninterface GigabitEthernet0/0/0/2\n"
        " ipv4 address 198.51.100.1 255.255.255.0\n!\nend\n"
    ), {"aruba_aoscx": "1/1/2", "dell_os10": "ethernet1/1/2", "arista_eos": "Ethernet2",
        "mikrotik_routeros": "ether2"}),
    "ios xr port 0": ("cisco_iosxr", "GigabitEthernet0/0/0/0", (
        "hostname r1\ninterface GigabitEthernet0/0/0/0\n"
        " ipv4 address 198.51.100.1 255.255.255.0\n!\nend\n"
    ), {"aruba_aoscx": "1/1/1", "dell_os10": "ethernet1/1/1", "arista_eos": "Ethernet1",
        "mikrotik_routeros": "ether1"}),
    "ios-xe router slot 0": ("cisco_iosxe_cli", "GigabitEthernet0/0/2", (
        "hostname r1\ninterface GigabitEthernet0/0/2\n"
        " ip address 198.51.100.1 255.255.255.0\n!\nend\n"
    ), {"aruba_aoscx": "1/1/2", "dell_os10": "ethernet1/1/2", "arista_eos": "Ethernet2",
        "mikrotik_routeros": "ether2"}),
    "ios-xe stack member 2": ("cisco_iosxe_cli", "GigabitEthernet2/0/1", (
        "hostname r1\ninterface GigabitEthernet2/0/1\n no switchport\n"
        " ip address 198.51.100.1 255.255.255.0\n!\nend\n"
    ), {"aruba_aoscx": "2/1/1", "dell_os10": "ethernet1/1/1", "arista_eos": "Ethernet1",
        "mikrotik_routeros": "ether1001"}),
    "junos fxp0": ("juniper_junos", "fxp0", (
        _JUNOS + "set interfaces fxp0 unit 0 family inet address 198.51.100.1/24\n"
    ), {"aruba_aoscx": "mgmt", "dell_os10": "mgmt1/1/1", "arista_eos": "Management1"}),
    "ios xr management": ("cisco_iosxr", "MgmtEth0/RP0/CPU0/0", (
        "hostname r1\ninterface MgmtEth0/RP0/CPU0/0\n"
        " ipv4 address 198.51.100.1 255.255.255.0\n!\nend\n"
    ), {"aruba_aoscx": "mgmt", "dell_os10": "mgmt1/1/1", "arista_eos": "Management1"}),
}


@pytest.mark.parametrize("target", _TARGETS)
@pytest.mark.parametrize("case", sorted(_ONE))
def test_a_name_numbered_from_0_is_written_from_1(case: str, target: str) -> None:
    source, name, text, written = _ONE[case]
    if target not in written:
        pytest.skip(f"{target} has no name for {name}")
    job = _job(source, target, text)
    assert job.port_renames.get(name) == written[target]
    assert job.status == MigrationJobStatus.completed, job.error
    # The target's parser finds the address on that name.
    tree = get_codec(target).parse(job.rendered)
    (holder,) = [
        i for i in tree.interfaces
        if any(a.ip == "198.51.100.1" for a in i.ipv4_addresses)
    ]
    assert holder.name == written[target]


#: Two source names that a 0 written as 1 puts on one name.
_TWO: dict[str, tuple[str, tuple[str, str], str, dict[str, str]]] = {
    "junos fpc 0 and 1": ("juniper_junos", ("ge-0/0/3", "ge-1/0/3"), (
        _JUNOS + "set interfaces ge-0/0/3 unit 0 family inet address 198.51.100.1/24\n"
        "set interfaces ge-1/0/3 unit 0 family inet address 203.0.113.1/24\n"
    ), {"aruba_aoscx": "1/1/3", "dell_os10": "ethernet1/1/3", "arista_eos": "Ethernet3",
        "mikrotik_routeros": "ether3"}),
    "junos port 0 and 1": ("juniper_junos", ("ge-0/0/0", "ge-0/0/1"), (
        _JUNOS + "set interfaces ge-0/0/0 unit 0 family inet address 198.51.100.1/24\n"
        "set interfaces ge-0/0/1 unit 0 family inet address 203.0.113.1/24\n"
    ), {"aruba_aoscx": "1/1/1", "dell_os10": "ethernet1/1/1", "arista_eos": "Ethernet1",
        "mikrotik_routeros": "ether1"}),
    "vyos eth0 and eth1": ("vyos", ("eth0", "eth1"), (
        "set system host-name r1\nset interfaces ethernet eth0 address 198.51.100.1/24\n"
        "set interfaces ethernet eth1 address 203.0.113.1/24\n"
    ), {"aruba_aoscx": "1/1/1", "dell_os10": "ethernet1/1/1", "arista_eos": "Ethernet1",
        "mikrotik_routeros": "ether1"}),
    "junos ae0 and ae1": ("juniper_junos", ("ae0", "ae1"), (
        _JUNOS + "set chassis aggregated-devices ethernet device-count 2\n"
        "set interfaces ge-1/0/5 ether-options 802.3ad ae0\n"
        "set interfaces ge-1/0/6 ether-options 802.3ad ae1\n"
        "set interfaces ae0 unit 0 family inet address 198.51.100.1/24\n"
        "set interfaces ae1 unit 0 family inet address 203.0.113.1/24\n"
    ), {"aruba_aoscx": "lag 1", "dell_os10": "port-channel1", "arista_eos": "Port-Channel1",
        "mikrotik_routeros": "bond1"}),
    "ios xr slot 0 and 1": ("cisco_iosxr", ("GigabitEthernet0/0/0/2", "GigabitEthernet0/1/0/2"), (
        "hostname r1\ninterface GigabitEthernet0/0/0/2\n ipv4 address 198.51.100.1 255.255.255.0\n!\n"
        "interface GigabitEthernet0/1/0/2\n ipv4 address 203.0.113.1 255.255.255.0\n!\nend\n"
    ), {"aruba_aoscx": "1/1/2", "dell_os10": "ethernet1/1/2", "arista_eos": "Ethernet2"}),
    "ios-xe two stack members": ("cisco_iosxe_cli", ("GigabitEthernet1/0/1", "GigabitEthernet2/0/1"), (
        "hostname r1\ninterface GigabitEthernet1/0/1\n no switchport\n"
        " ip address 198.51.100.1 255.255.255.0\n!\n"
        "interface GigabitEthernet2/0/1\n no switchport\n"
        " ip address 203.0.113.1 255.255.255.0\n!\nend\n"
    ), {"dell_os10": "ethernet1/1/1", "arista_eos": "Ethernet1"}),
}


@pytest.mark.parametrize("target", _TARGETS)
@pytest.mark.parametrize("case", sorted(_TWO))
def test_two_names_on_one_are_said(case: str, target: str) -> None:
    """Written from 1, a name numbered from 0 can be the name of its
    neighbour: the job is ``partial``, and lists the two."""
    source, names, text, on = _TWO[case]
    if target not in on:
        pytest.skip(f"{target} has the two names apart")
    job = _job(source, target, text)
    assert job.status == MigrationJobStatus.partial
    assert sorted(job.fused_ports.get(on[target], [])) == sorted(names)
    assert job.error.startswith("Port names are not settled: ")


# ---------------------------------------------------------------------------
# Over the committed captures
# ---------------------------------------------------------------------------


def test_no_committed_name_is_given_a_0() -> None:
    """Over every committed capture of every other codec: the name each
    of the four targets writes for a port, a LAG or a management port
    is one it has, and a name numbered from 0 at the source is among
    them on each target."""
    from_0 = dict.fromkeys(_TARGETS, 0)
    for codec, _rel, path in _captures():
        source = get_codec(codec)
        for iface in source.parse(path.read_text(encoding="utf-8")).interfaces:
            identity = source.classify_port_name(iface.name)
            if identity.kind not in ("physical", "lag", "mgmt"):
                continue
            zero = 0 in (identity.stack, identity.module, identity.port, identity.index)
            for target in _TARGETS:
                if codec == target:
                    continue
                name = get_codec(target).format_port_identity(identity)
                if name is None:
                    continue
                assert all(n >= 1 for n in _numbers(target, identity.kind, name)), (
                    codec, target, identity.kind,
                )
                from_0[target] += zero
    assert all(from_0.values()), from_0
