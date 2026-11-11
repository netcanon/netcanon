"""AOS-S has no member 0.

AOS-S numbers stack and VSF members from 1 (the model families: a
2930M stack is members 1-10, a 2930F fabric 1-8, each graded from
HPE's guides), and ``physical_port_name`` refuses a member below 1.
A Junos FPC, an IOS XR slot and an IOS-XE router's slot are numbered
from 0.  With no devices declared, the name-shape translator wrote
such a port ``0/<n>`` -- a member AOS-S does not have -- in a job that
said ``completed``.  It is written on member 1, as a port 0 is written
as port 1; a port of member 0 beside the same port of member 1 then
has one name, and the job says so.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.codecs.aruba_aoss.port_names import (
    classify_port_name as aoss_identity,
)
from netcanon.migration.codecs.aruba_aoss.port_names import (
    format_port_identity,
    physical_port_name,
)
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_vlan_members_reach_the_output import _captures

pytestmark = pytest.mark.unit

#: A routed port of member (or slot) 0 in each grammar that numbers
#: them from 0, with an address, and the AOS-S name it is written as.
_MEMBER_0: dict[str, tuple[str, str, str]] = {
    "juniper_junos": (
        "ge-0/0/2",
        "set system host-name r1\nset interfaces ge-0/0/2 unit 0 family inet address 198.51.100.1/24\n",
        "1/2",
    ),
    "cisco_iosxr": (
        "GigabitEthernet0/0/0/2",
        "hostname r1\ninterface GigabitEthernet0/0/0/2\n ipv4 address 198.51.100.1 255.255.255.0\n!\nend\n",
        "1/2",
    ),
    "cisco_iosxe_cli": (
        "GigabitEthernet0/0/2",
        "hostname r1\ninterface GigabitEthernet0/0/2\n ip address 198.51.100.1 255.255.255.0\n!\nend\n",
        "1/2",
    ),
}

#: The same port of member 0 and of member 1, each with an address.
_TWO_MEMBERS: dict[str, tuple[tuple[str, str], str]] = {
    "juniper_junos": (("ge-0/0/2", "ge-1/0/2"), (
        "set system host-name r1\n"
        "set interfaces ge-0/0/2 unit 0 family inet address 198.51.100.1/24\n"
        "set interfaces ge-1/0/2 unit 0 family inet address 203.0.113.1/24\n"
    )),
    "cisco_iosxr": (("GigabitEthernet0/0/0/2", "GigabitEthernet0/1/0/2"), (
        "hostname r1\ninterface GigabitEthernet0/0/0/2\n ipv4 address 198.51.100.1 255.255.255.0\n!\n"
        "interface GigabitEthernet0/1/0/2\n ipv4 address 203.0.113.1 255.255.255.0\n!\nend\n"
    )),
}

_A_MEMBER = re.compile(r"^(\d+)/[A-Za-z]?\d+$")


def _job(source: str, text: str):
    return run_plan_with_checked_names(
        get_codec(source), get_codec("aruba_aoss"), text, port_rename_map={},
    )


def test_aoss_refuses_member_0_itself() -> None:
    """The rule the formatter is held to, as the module states it."""
    with pytest.raises(ValueError, match="1-based"):
        physical_port_name(member=0, slot="", port=2)


@pytest.mark.parametrize("source", sorted(_MEMBER_0))
def test_a_port_of_member_0_is_written_on_member_1(source: str) -> None:
    name, text, written = _MEMBER_0[source]
    assert get_codec(source).classify_port_name(name).stack == 0
    job = _job(source, text)
    assert job.port_renames.get(name) == written
    lines = job.rendered.splitlines()
    assert f"interface {written}" in lines
    assert not [line for line in lines if line.startswith("interface 0/")]
    assert job.status == MigrationJobStatus.completed
    # The AOS-S parser reads it back as a port of member 1.
    tree = get_codec("aruba_aoss").parse(job.rendered)
    (port,) = [i for i in tree.interfaces if i.ipv4_addresses]
    assert port.name == written and aoss_identity(port.name).stack == 1


@pytest.mark.parametrize("source", sorted(_TWO_MEMBERS))
def test_member_0_beside_member_1_is_two_ports_on_one_name(source: str) -> None:
    """Written on member 1, a port of member 0 has the name of the same
    port of member 1: the job is ``partial``, and lists the two."""
    names, text = _TWO_MEMBERS[source]
    job = _job(source, text)
    assert job.status == MigrationJobStatus.partial
    assert sorted(job.fused_ports.get("1/2", [])) == sorted(names)
    assert job.error.startswith("Port names are not settled: ")


def test_no_committed_port_is_given_member_0() -> None:
    """Over every committed capture of every other codec: no name the
    formatter writes for a physical port is a port of member 0, and a
    port whose source numbers it member 0 is a port of member 1."""
    seen = 0
    for codec, _rel, path in _captures():
        if codec == "aruba_aoss":
            continue
        source = get_codec(codec)
        for iface in source.parse(path.read_text(encoding="utf-8")).interfaces:
            identity = source.classify_port_name(iface.name)
            if identity.kind != "physical":
                continue
            written = format_port_identity(identity)
            m = _A_MEMBER.match(written or "")
            if m is None:
                continue
            assert int(m.group(1)) >= 1, (codec, written)
            if identity.stack == 0:
                assert int(m.group(1)) == 1, (codec, written)
                seen += 1
    assert seen
