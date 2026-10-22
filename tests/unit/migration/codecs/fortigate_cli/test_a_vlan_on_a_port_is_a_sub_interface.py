"""A FortiOS VLAN interface on a port or an aggregate is a sub-interface of it.

``edit "VL_100"`` / ``set vlanid 100`` / ``set interface "LAG_INTERNAL"``
tags the frames of one interface on ``LAG_INTERNAL``, under a name of
the operator's own.  FortiOS writes a VLAN interface on a port and on a
switch interface with the same lines, so the parser tells the two apart
by the PARENT:

* on a port -- one whose own edit says ``set type physical``, or, where
  its edit states no type or there is none, one whose name says it is a
  port -- or on an aggregate that is not a FortiLink one, it is a
  sub-interface: typed as its parent, its tag its own, and no VLAN of
  the tag;
* on a FortiLink aggregate, a hardware or software switch, another
  VLAN interface (Q-in-Q), or anything that is neither (``internal``,
  ``fortilink``), it is a VLAN interface and a VLAN of its tag, as
  before.

Across vendors a sub-interface goes where its parent goes, named by its
TAG whatever its own name looks like; between two FortiOS configs it
keeps its name.  Before, every one was a VLAN interface and a VLAN:
onto IOS-XE, NX-OS, EOS or Junos it came out as ``interface Vlan100``
or ``irb.100`` -- an interface no port carries -- and ``gn-mgmt``, a
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

#: One VLAN interface on each kind of parent.  ``agg2`` is defined
#: after the VLAN interface on it.
_EACH_PARENT = """config system interface
    edit "port3"
        set alias "uplink"
        set type physical
    next
    edit "agg1"
        set type aggregate
        set member "port5" "port6"
    next
    edit "fl"
        set type aggregate
        set member "port7" "port8"
        set fortilink enable
    next
    edit "internal"
        set type hard-switch
    next
    edit "sw1"
        set type switch
    next
    edit "gn-mgmt"
        set interface "port3"
        set vlanid 11
    next
    edit "port2.10"
        set interface "port2"
        set vlanid 10
    next
    edit "VL_20"
        set interface "agg1"
        set vlanid 20
    next
    edit "VL_25"
        set interface "agg2"
        set vlanid 25
    next
    edit "fsw30"
        set interface "fl"
        set vlanid 30
    next
    edit "VL_40"
        set interface "internal"
        set vlanid 40
    next
    edit "VL_45"
        set interface "sw1"
        set vlanid 45
    next
    edit "VL_50"
        set interface "lan"
        set vlanid 50
    next
    edit "VL_55"
        set interface "fortilink"
        set vlanid 55
    next
    edit "wan2"
        set interface "port4"
        set vlanid 60
    next
    edit "VL_65"
        set interface "wan2"
        set vlanid 65
    next
    edit "agg2"
        set type aggregate
        set member "port9" "port10"
    next
end
"""

#: Sub-interfaces on ports alone, every name of which some target has a
#: form for.
_ON_PORTS = """config system interface
    edit "port3"
        set ip 10.3.0.1 255.255.255.0
        set alias "uplink"
        set type physical
    next
    edit "gn-mgmt"
        set ip 10.11.0.1 255.255.255.0
        set interface "port3"
        set vlanid 11
    next
    edit "port2.10"
        set ip 10.10.0.1 255.255.255.0
        set interface "port2"
        set vlanid 10
    next
end
"""

#: And one on an aggregate, whose name FortiOS leaves to the operator.
_ON_AN_AGGREGATE = """config system interface
    edit "agg1"
        set type aggregate
        set member "port5" "port6"
    next
    edit "VL_20"
        set ip 10.20.0.1 255.255.255.0
        set interface "agg1"
        set vlanid 20
    next
end
"""

#: Targets that have no form for a sub-interface's tag (its
#: ``/interfaces/interface/dot1q-vlan`` is unsupported there).  Typed
#: by hand, and compared with what the jobs report.
_NO_FORM_FOR_THE_TAG = {"aruba_aoscx", "aruba_aoss", "cisco_iosxe", "dell_os10"}


def _job(target: str, text: str = _ON_PORTS, port_rename_map: dict | None = None):
    return run_plan_with_checked_names(
        get_codec("fortigate_cli"), get_codec(target), text,
        port_rename_map=port_rename_map or {},
    )


class TestWhatTheParserReads:
    @pytest.mark.parametrize(
        ("name", "interface_type", "tag", "parent"),
        [
            # A port its own edit says is one.
            ("gn-mgmt", "ianaift:ethernetCsmacd", 11, "port3"),
            # A port no edit names, whose name says it is one.
            ("port2.10", "ianaift:ethernetCsmacd", 10, "port2"),
            # An aggregate, and one defined after the VLAN interface.
            ("VL_20", "ianaift:ieee8023adLag", 20, "agg1"),
            ("VL_25", "ianaift:ieee8023adLag", 25, "agg2"),
            # A FortiLink aggregate, a hardware switch, a software
            # switch, and names that are no port: a VLAN interface, as
            # before.
            ("fsw30", "ianaift:l3ipvlan", None, "fl"),
            ("VL_40", "ianaift:l3ipvlan", None, "internal"),
            ("VL_45", "ianaift:l3ipvlan", None, "sw1"),
            ("VL_50", "ianaift:l3ipvlan", None, "lan"),
            ("VL_55", "ianaift:l3ipvlan", None, "fortilink"),
            # A VLAN interface on a VLAN interface (Q-in-Q), whose
            # name looks like a port's: one tag on a VLAN interface.
            ("wan2", "ianaift:ethernetCsmacd", 60, "port4"),
            ("VL_65", "ianaift:l3ipvlan", None, "wan2"),
        ],
    )
    def test_each_parent(self, name: str, interface_type: str, tag, parent: str) -> None:
        tree = get_codec("fortigate_cli").parse(_EACH_PARENT)
        iface = next(i for i in tree.interfaces if i.name == name)
        assert (iface.interface_type, iface.dot1q_vlan, iface.vlan_parent) == (
            interface_type, tag, parent,
        )

    def test_a_sub_interface_is_no_vlan(self) -> None:
        tree = get_codec("fortigate_cli").parse(_EACH_PARENT)
        assert sorted((v.id, v.name) for v in tree.vlans) == [
            (30, "fsw30"), (40, "VL_40"), (45, "VL_45"), (50, "VL_50"), (55, "VL_55"),
            (65, "VL_65"),
        ]

    def test_the_alias_is_the_sub_interfaces_description(self) -> None:
        tree = get_codec("fortigate_cli").parse(
            _ON_PORTS.replace('        set vlanid 11\n', '        set vlanid 11\n        set alias "mgmt"\n'),
        )
        assert next(i for i in tree.interfaces if i.name == "gn-mgmt").description == "mgmt"


class TestOntoAnotherVendor:
    def test_eos(self) -> None:
        job = _job("arista_eos")
        assert job.status == MigrationJobStatus.completed, job.error
        for block in (
            "interface Ethernet3.11\n   encapsulation dot1q vlan 11\n   ip address 10.11.0.1/24\n",
            "interface Ethernet2.10\n   encapsulation dot1q vlan 10\n   ip address 10.10.0.1/24\n",
        ):
            assert block in job.rendered
        lines = job.rendered.splitlines()
        assert not [line for line in lines if line.startswith(("vlan ", "interface Vlan"))]

    def test_junos(self) -> None:
        job = _job("juniper_junos")
        assert job.status == MigrationJobStatus.completed, job.error
        lines = set(job.rendered.splitlines())
        for port, tag in (("ge-0/0/3", 11), ("ge-0/0/2", 10)):
            assert f"set interfaces {port} vlan-tagging" in lines
            assert f"set interfaces {port} unit {tag} vlan-id {tag}" in lines
            assert f"set interfaces {port} unit {tag} family inet address 10.{tag}.0.1/24" in lines
        assert not [line for line in lines if line.startswith(("set vlans", "set interfaces irb"))]

    def test_an_aggregate_is_said_until_it_is_named(self) -> None:
        """No classifier reads ``agg1``: its sub-interface went where it
        went, under ``agg1``, and the job says both names.  An entry for
        the aggregate takes the sub-interface with it."""
        job = _job("arista_eos", _ON_AN_AGGREGATE)
        assert job.status == MigrationJobStatus.partial
        assert {"agg1", "VL_20"} <= set(job.untranslated_ports)
        job = _job("arista_eos", _ON_AN_AGGREGATE, {"agg1": "Port-Channel1"})
        assert job.status == MigrationJobStatus.completed, job.error
        assert (
            "interface Port-Channel1.20\n   encapsulation dot1q vlan 20\n   ip address 10.20.0.1/24\n"
            in job.rendered
        )

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


class TestBetweenTwoFortiOSConfigs:
    def test_each_edit_stands(self) -> None:
        job = _job("fortigate_cli", _ON_PORTS + _ON_AN_AGGREGATE)
        assert job.status == MigrationJobStatus.completed, job.error
        edits = {}
        name = None
        for line in job.rendered.splitlines():
            if line.startswith('    edit "'):
                name = line.strip()[len('edit "'):-1]
            elif line.startswith("        set ") and name:
                edits.setdefault(name, set()).add(line.strip())
        assert {"set vlanid 11", 'set interface "port3"'} <= edits["gn-mgmt"]
        assert {"set vlanid 10", 'set interface "port2"'} <= edits["port2.10"]
        assert {"set vlanid 20", 'set interface "agg1"'} <= edits["VL_20"]
