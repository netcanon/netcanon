"""A unit of any Junos interface is written under its device.

The parser makes a record named ``<device>.<N>`` of ``set interfaces
<device> unit N``, and no Junos interface has a dot in its name, so the
only form the renderer can write for it is ``set interfaces <device>
unit N``.  It did so only for a device shaped like a port
(``ge-0/0/0``).  Every other device -- the ``lo0`` units a routing
instance takes, the ``st0`` units of a VPN, a unit of an aggregate --
was written ``set interfaces lo0.10 unit 0 ...``, a name Junos refuses
at commit; for a unit of an aggregate its ``vlan-id`` was not written
at all.  Both committed Junos captures that have such units were
translated to Junos so, in jobs that said ``completed``, and so was a
``Port-channel1.10`` from IOS-XE, EOS or NX-OS.

The expected lines are typed from the captures' text by hand, and each
output is read as text as well as with the parser: the parser reads
``set interfaces lo0.10 unit 0`` back as ``lo0.10`` too, so a check of
the parse alone passes the defect.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.definitions import LIBRARY_DIR
from netcanon.migration.codecs.juniper_junos.render import _split_subiface_name
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.device_models import inventory_from_profile
from netcanon.migration.target_profiles import load_profiles_dir
from netcanon.services.migration_pipeline import (
    run_plan,
    run_plan_with_checked_names,
    run_plan_with_models,
)

pytestmark = pytest.mark.unit

REAL = Path(__file__).resolve().parents[4] / "fixtures" / "real" / "junos"

#: A ``set interfaces`` line whose interface name has a dot in it:
#: no Junos interface is named so.
_DOTTED = re.compile(r"^set interfaces (\S+\.\d+)(?: |$)", re.MULTILINE)

#: Capture -> lines its Junos output must hold, typed from the
#: capture's own ``set interfaces lo0|st0 unit N`` lines.
CAPTURES = {
    "jnprautomate_mnha_vsrx_a_junos.set": [
        "set interfaces lo0 unit 2 family inet address 10.12.12.12/32",
        'set interfaces lo0 unit 10 description "PROD_LOOPBACKS"',
        "set interfaces lo0 unit 10 family inet address 10.165.251.200/32",
        "set interfaces lo0 unit 10 family inet address 203.0.113.100/32",
        "set interfaces lo0 unit 10 family inet address 10.165.251.222/32",
        'set interfaces st0 unit 100 description "REMOTE_ACCESS_VPN"',
        "set interfaces st0 unit 100 family inet mtu 1420",
        'set interfaces st0 unit 200 description "SITE-TO-SITE-VPN_PROD"',
        "set interfaces st0 unit 200 family inet mtu 1420",
        # ``set routing-instances HA-ICD interface lo0.20`` and no
        # line of its own: the unit the instance takes is still made.
        "set interfaces lo0 unit 20",
    ],
    "ksator_labmgmt_qfx10k2_junos173.set": [
        "set interfaces lo0 unit 2 family inet address 10.254.21.5/32",
        "set interfaces lo0 unit 2 family inet6 address fd20:10:254:21::5/128",
        "set interfaces lo0 unit 3 family inet address 10.254.31.5/32",
        "set interfaces lo0 unit 3 family inet6 address fd20:10:254:31::5/128",
        "set interfaces lo0 unit 100 family inet address 10.254.20.100/32",
        "set interfaces lo0 unit 100 family inet6 address fd20:2222::2100/128",
    ],
}

#: Capture -> the units its routing instances take, typed from its
#: ``set routing-instances <ri> interface <unit>`` lines.
BOUND = {
    "jnprautomate_mnha_vsrx_a_junos.set": {
        "lo0.20", "lo0.2", "lo0.10", "st0.100", "st0.200",
    },
    "ksator_labmgmt_qfx10k2_junos173.set": {"lo0.2", "lo0.100", "lo0.3"},
}


def _junos():
    return get_codec("juniper_junos")


@pytest.mark.parametrize("capture", sorted(CAPTURES))
def test_a_captures_units_are_written_under_their_device(capture: str) -> None:
    raw = (REAL / capture).read_text(encoding="utf-8")
    job = run_plan(_junos(), _junos(), raw)
    assert job.status.value == "completed", job.error
    out = job.rendered or ""
    assert _DOTTED.findall(out) == []
    lines = set(out.splitlines())
    missing = [line for line in CAPTURES[capture] if line not in lines]
    assert missing == []


@pytest.mark.parametrize("capture", sorted(BOUND))
def test_each_unit_a_routing_instance_takes_is_defined(capture: str) -> None:
    """The instance still names ``lo0.10`` (Junos's own way to name a
    unit there), and the unit it names is one the output defines."""
    raw = (REAL / capture).read_text(encoding="utf-8")
    out = run_plan(_junos(), _junos(), raw).rendered or ""
    named = set(re.findall(r"^set routing-instances \S+ interface (\S+)$", out, re.MULTILINE))
    assert BOUND[capture] <= named
    defined = {
        f"{dev}.{unit}"
        for dev, unit in re.findall(r"^set interfaces (\S+) unit (\d+)(?: |$)", out, re.MULTILINE)
    }
    assert BOUND[capture] - defined == set()


@pytest.mark.parametrize(
    "device", ["lo0", "st0", "ae0", "reth0", "me0", "em0", "fxp0", "vme", "gr-0/0/0"]
)
def test_a_unit_of_each_device(device: str) -> None:
    src = (
        f"set interfaces {device} unit 5 description unit-five\n"
        f"set interfaces {device} unit 5 family inet address 10.0.5.1/32\n"
    )
    out = run_plan(_junos(), _junos(), src).rendered or ""
    assert _DOTTED.findall(out) == []
    assert f'set interfaces {device} unit 5 description "unit-five"' in out.splitlines()
    assert f"set interfaces {device} unit 5 family inet address 10.0.5.1/32" in out.splitlines()
    back = {i.name: i for i in _junos().parse(out).interfaces}
    assert [str(a.ip) for a in back[f"{device}.5"].ipv4_addresses] == ["10.0.5.1"]


def test_a_management_unit_follows_its_port_onto_a_declared_device() -> None:
    """``me0`` of an EX4300 is ``em0`` of an EX4600, and its unit 5
    goes with it -- under the device, not as ``em0.5 unit 0`` (a known
    limitation until this was mended)."""
    profiles = load_profiles_dir(LIBRARY_DIR / "target_profiles")
    src = (
        "set system host-name sw\n"
        "set interfaces me0 unit 0 family inet address 192.0.2.10/24\n"
        "set interfaces me0 unit 5 family inet address 192.0.2.50/24\n"
        "set interfaces ge-0/0/0 description up\n"
    )
    job = run_plan_with_models(
        _junos(), _junos(), src,
        inventory_from_profile(profiles["juniper_junos/EX4300-48T"]),
        inventory_from_profile(profiles["juniper_junos/EX4600-40F"]),
    )
    assert job.port_renames["me0.5"] == "em0.5"
    out = job.rendered or ""
    assert _DOTTED.findall(out) == []
    assert "set interfaces em0 unit 5 family inet address 192.0.2.50/24" in out.splitlines()


def test_a_unit_of_an_aggregate_keeps_its_vlan_id() -> None:
    src = (
        "set interfaces ae0 vlan-tagging\n"
        "set interfaces ae0 unit 10 vlan-id 10\n"
        "set interfaces ae0 unit 10 family inet address 10.10.10.1/24\n"
    )
    out = run_plan(_junos(), _junos(), src).rendered or ""
    assert "set interfaces ae0 unit 10 vlan-id 10" in out.splitlines()
    back = {i.name: i for i in _junos().parse(out).interfaces}
    assert back["ae0.10"].dot1q_vlan == 10


#: A routed sub-interface of a port-channel, in each grammar that
#: writes one.  The translator sends it after its LAG (``ae1.10``).
PORT_CHANNEL_UNITS = {
    "cisco_iosxe_cli": (
        "hostname r1\n!\ninterface GigabitEthernet0/0/1\n channel-group 1 mode active\n!\n"
        "interface Port-channel1\n no ip address\n!\n"
        "interface Port-channel1.10\n encapsulation dot1Q 10\n"
        " ip address 10.10.10.1 255.255.255.0\n!\nend\n"
    ),
    "arista_eos": (
        "hostname r1\n!\ninterface Ethernet1\n channel-group 1 mode active\n!\n"
        "interface Port-Channel1\n no switchport\n!\n"
        "interface Port-Channel1.10\n encapsulation dot1q vlan 10\n"
        " ip address 10.10.10.1/24\n!\nend\n"
    ),
    "cisco_nxos": (
        "hostname r1\n!\ninterface Ethernet1/1\n channel-group 1 mode active\n!\n"
        "interface port-channel1\n no switchport\n!\n"
        "interface port-channel1.10\n encapsulation dot1q 10\n"
        " ip address 10.10.10.1/24\n!\n"
    ),
}


@pytest.mark.parametrize("source", sorted(PORT_CHANNEL_UNITS))
def test_a_port_channel_sub_interface_onto_junos(source: str) -> None:
    job = run_plan_with_checked_names(
        get_codec(source), _junos(), PORT_CHANNEL_UNITS[source], port_rename_map={}
    )
    out = job.rendered or ""
    assert _DOTTED.findall(out) == []
    assert "set interfaces ae1 unit 10 vlan-id 10" in out.splitlines()
    assert "set interfaces ae1 unit 10 family inet address 10.10.10.1/24" in out.splitlines()


def _unit_mtu_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if re.match(r"set interfaces \S+ unit \d+ family \S+ mtu ", line)]


def test_a_units_mtu_is_written_per_family() -> None:
    """A unit has no ``mtu`` of its own in Junos: it is set per family,
    and the parser reads it back.  The device states no MTU and the
    unit's is above 1500, which needs a larger media MTU: said."""
    src = (
        "hostname r1\n!\ninterface GigabitEthernet0/0/1\n no ip address\n!\n"
        "interface GigabitEthernet0/0/1.20\n mtu 1546\n encapsulation dot1Q 20\n"
        " ip address 10.20.20.1 255.255.255.0\n ipv6 address 2001:db8:20::1/64\n!\nend\n"
    )
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), _junos(), src, port_rename_map={}
    )
    out = job.rendered or ""
    assert _unit_mtu_lines(out) == [
        "set interfaces ge-0/0/1 unit 20 family inet mtu 1546",
        "set interfaces ge-0/0/1 unit 20 family inet6 mtu 1546",
    ]
    review = [line for line in out.splitlines() if line.startswith("# review: family mtu 1546")]
    assert len(review) == 1
    assert "ge-0/0/1 unit 20" in review[0]
    assert "states no mtu" in review[0]
    back = {i.name: i for i in _junos().parse(out).interfaces}
    assert back["ge-0/0/1.20"].mtu == 1546


@pytest.mark.parametrize(
    ("lines", "written", "said"),
    [
        # No address: an MTU stated without one is for family inet
        # (the capture's unnumbered ``st0`` units).
        (["set interfaces st0 unit 1 family inet mtu 1420"],
         ["set interfaces st0 unit 1 family inet mtu 1420"], False),
        # An IPv6-only unit keeps its MTU on inet6.
        (["set interfaces ge-0/0/1 unit 7 family inet6 address 2001:db8::1/64",
          "set interfaces ge-0/0/1 unit 7 family inet6 mtu 1400"],
         ["set interfaces ge-0/0/1 unit 7 family inet6 mtu 1400"], False),
        # The device's MTU is larger: nothing to say.
        (["set interfaces ge-0/0/1 mtu 9192",
          "set interfaces ge-0/0/1 unit 7 family inet address 10.7.7.1/24",
          "set interfaces ge-0/0/1 unit 7 family inet mtu 9000"],
         ["set interfaces ge-0/0/1 unit 7 family inet mtu 9000"], False),
        # The device's MTU is not larger: said.
        (["set interfaces ge-0/0/1 mtu 1514",
          "set interfaces ge-0/0/1 unit 7 family inet address 10.7.7.1/24",
          "set interfaces ge-0/0/1 unit 7 family inet mtu 9000"],
         ["set interfaces ge-0/0/1 unit 7 family inet mtu 9000"], True),
    ],
)
def test_a_units_family_mtu_round_trips(lines: list[str], written: list[str], said: bool) -> None:
    src = "\n".join(lines) + "\n"
    tree = _junos().parse(src)
    out = run_plan(_junos(), _junos(), src).rendered or ""
    assert _unit_mtu_lines(out) == written
    assert any(line.startswith("# review: family mtu") for line in out.splitlines()) is said
    back = {i.name: i.mtu for i in _junos().parse(out).interfaces}
    assert back == {i.name: i.mtu for i in tree.interfaces}


def test_unit_0s_family_mtu_is_not_the_devices() -> None:
    """Unit 0 is the device's own record, whose ``mtu`` is the device's
    media MTU: a family MTU of unit 0 is not read into it."""
    tree = _junos().parse(
        "set interfaces ge-0/0/1 mtu 9192\n"
        "set interfaces ge-0/0/1 unit 0 family inet mtu 9000\n"
        "set interfaces ge-0/0/2 unit 0 family inet mtu 9000\n"
    )
    mtus = {i.name: i.mtu for i in tree.interfaces}
    assert mtus["ge-0/0/1"] == 9192
    assert mtus.get("ge-0/0/2") is None


def test_where_both_families_state_an_mtu_inets_is_kept() -> None:
    tree = _junos().parse(
        "set interfaces ge-0/0/1 unit 7 family inet6 mtu 1400\n"
        "set interfaces ge-0/0/1 unit 7 family inet mtu 1450\n"
    )
    assert {i.name: i.mtu for i in tree.interfaces}["ge-0/0/1.7"] == 1450


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ge-0/0/0.100", ("ge-0/0/0", 100)),
        ("ge-0/0/0.0", ("ge-0/0/0", 0)),
        ("xe-0/0/6:2.10", ("xe-0/0/6:2", 10)),
        ("lo0.10", ("lo0", 10)),
        ("st0.100", ("st0", 100)),
        ("ae1.10", ("ae1", 10)),
        ("irb.10", ("irb", 10)),
        # Unit 0 of any other device would be that device's own unit 0.
        ("eth0.0", (None, None)),
        ("irb.0", (None, None)),
        ("lo0", (None, None)),
        ("ether1.backup", (None, None)),
        ("my port.5", (None, None)),
        # Longer than any platform's unit; not made a number.
        ("lo0.12345678901", (None, None)),
    ],
)
def test_split_subiface_name(name: str, expected: tuple) -> None:
    assert _split_subiface_name(name) == expected
