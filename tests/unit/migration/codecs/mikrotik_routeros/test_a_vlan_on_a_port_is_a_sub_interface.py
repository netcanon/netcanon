"""A RouterOS VLAN interface on a port or a LAG is a sub-interface of it.

``/interface vlan add interface=ether3 name=gn-mgmt vlan-id=11`` rides
on the port its line names, under a name of the operator's own.
RouterOS writes a VLAN interface on a port and on a bridge with the
same line, so the parser tells the two apart by the PARENT:

* on a port -- one a line of ``/interface ethernet`` names (renamed or
  not), or, where no line does, one whose name says it is a port --
  or on a LAG (``/interface bonding``), it is a sub-interface: typed as
  its parent, its tag its own, and no VLAN of the tag;
* on a bridge, or on anything that is neither (``wlan1``), it is a VLAN
  interface and a VLAN of its tag, as before.

Across vendors a sub-interface goes where its port goes, named by its
TAG whatever its own name looks like; between two RouterOS configs it
keeps its name.  Before, every one was a VLAN interface and a VLAN:
onto IOS-XE, NX-OS, EOS or Junos it came out as ``interface Vlan11``
or ``irb.11`` -- an interface no port carries -- and ``gn-mgmt``, a
name no classifier reads, held every job of it ``partial``.

What each line means is typed here by hand, and each output is read
as TEXT, so that no expectation is the parser's or the renderer's own
answer.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs import get_codec
from netcanon.migration.codecs.registry import list_public_codecs
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

#: One VLAN interface on each kind of parent.
_EACH_PARENT = """/interface bridge
add name=bridge1
/interface ethernet
set [ find default-name=ether3 ] comment=uplink
set [ find default-name=ether4 ] name=wan
/interface bonding
add name=bond1 slaves=ether5,ether6 mode=802.3ad
/interface vlan
add interface=ether3 name=gn-mgmt vlan-id=11
add interface=ether2 name=ether2.10 vlan-id=10
add interface=bond1 name=bond1.20 vlan-id=20
add interface=wan name=wan-isp vlan-id=35
add interface=bridge1 name=vlan30 vlan-id=30
add interface=wlan1 name=wifi40 vlan-id=40
/ip address
add address=10.11.0.1/24 interface=gn-mgmt
add address=10.10.0.1/24 interface=ether2.10
add address=10.20.0.1/24 interface=bond1.20
add address=10.35.0.1/24 interface=wan-isp
add address=10.30.0.1/24 interface=vlan30
"""

#: Sub-interfaces on ports and a LAG alone, every name of which some
#: target has a form for.
_ON_PORTS = """/interface ethernet
set [ find default-name=ether3 ] comment=uplink
/interface bonding
add name=bond1 slaves=ether5,ether6 mode=802.3ad
/interface vlan
add interface=ether3 name=gn-mgmt vlan-id=11
add interface=ether2 name=ether2.10 vlan-id=10
add interface=bond1 name=bond1.20 vlan-id=20
/ip address
add address=10.11.0.1/24 interface=gn-mgmt
add address=10.10.0.1/24 interface=ether2.10
add address=10.20.0.1/24 interface=bond1.20
add address=10.3.0.1/24 interface=ether3
"""

#: Targets that have no form for a sub-interface's tag (its
#: ``/interfaces/interface/dot1q-vlan`` is unsupported there).  Typed
#: by hand, and compared with what the jobs report.
_NO_FORM_FOR_THE_TAG = {"aruba_aoscx", "aruba_aoss", "cisco_iosxe", "dell_os10"}


def _job(target: str, text: str = _ON_PORTS):
    return run_plan_with_checked_names(
        get_codec("mikrotik_routeros"), get_codec(target), text, port_rename_map={},
    )


class TestWhatTheParserReads:
    @pytest.mark.parametrize(
        ("name", "interface_type", "tag", "parent"),
        [
            # A port a line of ``/interface ethernet`` names.
            ("gn-mgmt", "ianaift:ethernetCsmacd", 11, "ether3"),
            # A port no line names, whose name says it is one.
            ("ether2.10", "ianaift:ethernetCsmacd", 10, "ether2"),
            # A LAG.
            ("bond1.20", "ianaift:ieee8023adLag", 20, "bond1"),
            # A port the operator renamed: its line says it is a port,
            # its name does not.
            ("wan-isp", "ianaift:ethernetCsmacd", 35, "wan"),
            # A bridge, and something that is neither: a VLAN
            # interface, as before.
            ("vlan30", "ianaift:l3ipvlan", None, "bridge1"),
            ("wifi40", "ianaift:l3ipvlan", None, "wlan1"),
        ],
    )
    def test_each_parent(self, name: str, interface_type: str, tag, parent: str) -> None:
        tree = get_codec("mikrotik_routeros").parse(_EACH_PARENT)
        iface = next(i for i in tree.interfaces if i.name == name)
        assert (iface.interface_type, iface.dot1q_vlan, iface.vlan_parent) == (
            interface_type, tag, parent,
        )

    def test_a_sub_interface_is_no_vlan(self) -> None:
        tree = get_codec("mikrotik_routeros").parse(_EACH_PARENT)
        assert sorted((v.id, v.name) for v in tree.vlans) == [(30, "vlan30"), (40, "wifi40")]


class TestOntoAnotherVendor:
    def test_eos(self) -> None:
        job = _job("arista_eos")
        assert job.status == MigrationJobStatus.completed, job.error
        for block in (
            "interface Ethernet3.11\n   encapsulation dot1q vlan 11\n   ip address 10.11.0.1/24\n",
            "interface Ethernet2.10\n   encapsulation dot1q vlan 10\n   ip address 10.10.0.1/24\n",
            "interface Port-Channel1.20\n   encapsulation dot1q vlan 20\n   ip address 10.20.0.1/24\n",
        ):
            assert block in job.rendered
        lines = job.rendered.splitlines()
        assert not [line for line in lines if line.startswith(("vlan ", "interface Vlan"))]

    def test_junos(self) -> None:
        job = _job("juniper_junos")
        assert job.status == MigrationJobStatus.completed, job.error
        lines = set(job.rendered.splitlines())
        for port, tag in (("ge-0/0/3", 11), ("ge-0/0/2", 10), ("ae1", 20)):
            assert f"set interfaces {port} vlan-tagging" in lines
            assert f"set interfaces {port} unit {tag} vlan-id {tag}" in lines
            assert f"set interfaces {port} unit {tag} family inet address 10.{tag}.0.1/24" in lines
        assert not [line for line in lines if line.startswith(("set vlans", "set interfaces irb"))]

    def test_a_renamed_port_is_said(self) -> None:
        """``wan`` is ``ether4`` under a name of the operator's, which
        no classifier reads: its sub-interface went where it went,
        under ``wan``, and the job says both names."""
        job = _job("arista_eos", _EACH_PARENT)
        assert job.status == MigrationJobStatus.partial
        assert {"wan", "wan-isp"} <= set(job.untranslated_ports)

    def test_where_the_target_has_no_form_for_the_tag(self) -> None:
        reported = set()
        for target in list_public_codecs():
            job = _job(target)
            paths = {u.path for u in job.validation.unsupported_paths}
            if "/interfaces/interface/dot1q-vlan" in paths:
                reported.add(target)
                assert job.status == MigrationJobStatus.partial, target
        assert reported == _NO_FORM_FOR_THE_TAG

    def test_every_other_target_says_completed(self) -> None:
        """Each was ``partial``: ``gn-mgmt`` was a name nobody
        decided, left as it was in another vendor's config."""
        for target in set(list_public_codecs()) - _NO_FORM_FOR_THE_TAG:
            job = _job(target)
            assert job.status == MigrationJobStatus.completed, (target, job.error)
            assert job.untranslated_ports == [], target


class TestBetweenTwoRouterOSConfigs:
    def test_each_line_stands(self) -> None:
        job = _job("mikrotik_routeros")
        assert job.status == MigrationJobStatus.completed, job.error
        vlan_lines = {
            " ".join(sorted(line.split()[1:]))
            for line in job.rendered.split("/interface vlan\n", 1)[1].split("\n/", 1)[0].splitlines()
            if line.startswith("add ")
        }
        assert vlan_lines == {
            "interface=ether3 name=gn-mgmt vlan-id=11",
            "interface=ether2 name=ether2.10 vlan-id=10",
            "interface=bond1 name=bond1.20 vlan-id=20",
        }
