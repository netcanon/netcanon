"""A Junos unit 0 that carries a tag is a sub-interface of its device.

Junos names a unit of every device, and where frames carry no tag
unit 0 is what every other platform calls the interface: the parser
reads its lines onto the device's record.  Under ``vlan-tagging`` a
unit 0 can be given a ``vlan-id`` like any other unit (Juniper's router
examples tag unit 0; the EX and QFX references say a tag "cannot be
configured on logical interface unit 0").  Read onto the device's
record, the tag and the unit's addresses were the port's own on every
target -- ``encapsulation dot1Q 54`` and the unit's address on the main
interface -- in jobs that said ``completed``.

Now the unit is a record of its own, ``<device>.0``, and the device
keeps what its own lines state.  Across vendors the unit goes after its
port NAMED BY ITS TAG (``ge-0/0/1.0`` tagged 54 is ``Ethernet1.54``):
``.0`` is the port itself on every other platform.  Between two Junos
configs it stays unit 0.  A tagged unit 0 that switches has no form in
the tree, and is left out and said.

What is read here is the rendered output of every public target,
parsed with the target's own parser and found BY ADDRESS, and as text
by a reader of this module's own -- compared with what the source
states, written out by hand below.  Each check is handed the defect
it is for: the parser's old reading, with the unit's lines on the
device.
"""
from __future__ import annotations

import re

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
)
from netcanon.migration.codecs.juniper_junos import parse as junos_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_units_follow_their_port import _holders, _tags

JUNOS = "juniper_junos"

#: A device with a description of its own, a unit 0 tagged 54 and a
#: unit 10 tagged 10, each with an address; and a port whose unit 0
#: carries no tag.
_ROUTED = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/1 description PARENT",
    "set interfaces ge-0/0/1 vlan-tagging",
    "set interfaces ge-0/0/1 unit 0 vlan-id 54",
    "set interfaces ge-0/0/1 unit 0 family inet address 10.54.0.1/24",
    "set interfaces ge-0/0/1 unit 10 vlan-id 10",
    "set interfaces ge-0/0/1 unit 10 family inet address 10.1.0.1/24",
    "set interfaces ge-0/0/2 unit 0 family inet address 10.2.0.1/24",
    "",
])

#: Lines of the device and lines of its unit 0 that say the same kind
#: of thing: a description, an MTU, whether it is disabled.
_OWN_AND_THE_UNITS = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/1 description PARENT",
    "set interfaces ge-0/0/1 disable",
    "set interfaces ge-0/0/1 mtu 9000",
    "set interfaces ge-0/0/1 vlan-tagging",
    "set interfaces ge-0/0/1 unit 0 description UNIT",
    "set interfaces ge-0/0/1 unit 0 vlan-id 54",
    "set interfaces ge-0/0/1 unit 0 family inet mtu 1500",
    "set interfaces ge-0/0/1 unit 0 family inet address 10.54.0.1/24",
    "",
])

#: An aggregate whose unit 0 carries a tag.
_AGGREGATE = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/1 ether-options 802.3ad ae2",
    "set interfaces ae2 description UPLINK",
    "set interfaces ae2 vlan-tagging",
    "set interfaces ae2 unit 0 vlan-id 54",
    "set interfaces ae2 unit 0 family inet address 10.54.0.1/24",
    "",
])

#: The unit 0 in a routing instance and a route's next hop.
_REFERRED_TO = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/1 vlan-tagging",
    "set interfaces ge-0/0/1 unit 0 vlan-id 54",
    "set interfaces ge-0/0/1 unit 0 family inet address 10.54.0.1/24",
    "set interfaces ge-0/0/2 unit 0 family inet address 10.2.0.1/24",
    "set routing-instances red instance-type vrf",
    "set routing-instances red interface ge-0/0/1.0",
    "set routing-instances blue instance-type vrf",
    "set routing-instances blue interface ge-0/0/2.0",
    "set routing-instances blue interface ge-0/0/9.0",
    "set routing-options static route 192.0.2.0/24 next-hop ge-0/0/1.0",
    "",
])

#: A tagged unit 0 that switches.
_SWITCHING = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/1 description PARENT",
    "set interfaces ge-0/0/1 vlan-tagging",
    "set interfaces ge-0/0/1 unit 0 vlan-id 54",
    "set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members v54",
    "set vlans v54 vlan-id 54",
    "",
])

#: Unit 0 and unit 54 of one port, unit 0 tagged 54.
_ONE_NAME = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/1 vlan-tagging",
    "set interfaces ge-0/0/1 unit 0 vlan-id 54",
    "set interfaces ge-0/0/1 unit 0 family inet address 10.54.0.1/24",
    "set interfaces ge-0/0/1 unit 54 vlan-id 100",
    "set interfaces ge-0/0/1 unit 54 family inet address 10.100.0.1/24",
    "",
])


def _folded(iface_state, stated) -> list[str]:
    """The parser's old reading: unit 0's lines on the device, the
    unit no record of its own.  (The lines are read onto the device
    as well as into the unit's bucket; dropping the bucket is all it
    takes.)"""
    for state in iface_state.values():
        state.pop(junos_parse._UNIT_0, None)
        state.pop(junos_parse._OWN, None)
    return []


def _job(text: str, target_name: str) -> MigrationJob:
    job = run_plan_with_checked_names(
        get_codec(JUNOS), get_codec(target_name), text, port_rename_map={},
    )
    assert job.rendered, job.error
    return job


def _stanza(rendered: str, name: str) -> list[str]:
    """The lines of ``interface <name>`` in a config whose stanzas are
    told apart by their indentation (IOS-XE, NX-OS, EOS, IOS XR,
    AOS-CX, OS10, AOS-S): from the header to the next line in column
    0."""
    lines: list[str] = []
    inside = False
    for line in rendered.splitlines():
        if line[:1].strip():
            inside = line.split() == ["interface", *name.split()]
            continue
        if inside:
            lines.append(line.strip())
    return lines


#: Targets whose stanzas this module's text reader reads.
_INDENTED = {
    "cisco_iosxe_cli", "cisco_nxos", "arista_eos", "cisco_iosxr",
    "aruba_aoscx", "dell_os10", "aruba_aoss",
}


def _unit_problems(target_name: str) -> list[str]:
    """What is wrong with the tagged unit 0 of ``_ROUTED`` in the
    output for *target_name*."""
    job = _job(_ROUTED, target_name)
    target = get_codec(target_name)
    out = target.parse(job.rendered)
    where = job.port_renames.get("ge-0/0/1", "ge-0/0/1")
    expected = "ge-0/0/1.0" if target_name == JUNOS else f"{where}.54"
    holders = _holders(out, "10.54.0.1")
    if len(holders) != 1:
        return [f"10.54.0.1 is on {[h.name for h in holders]}"]
    (unit,) = holders
    problems: list[str] = []
    if unit.name != expected:
        problems.append(f"10.54.0.1 is on {unit.name!r}, not {expected!r}")
    others = {address.ip for address in unit.ipv4_addresses} - {"10.54.0.1"}
    if others:
        problems.append(f"{unit.name!r} holds {sorted(others)} as well")
    tens = _holders(out, "10.1.0.1")
    if [ten.name for ten in tens] in ([], [unit.name]):
        problems.append(f"unit 10 is on {[ten.name for ten in tens]}")
    if job.port_renames.get("ge-0/0/1.0", "ge-0/0/1.0") != expected:
        problems.append(
            f"the job sends ge-0/0/1.0 to {job.port_renames.get('ge-0/0/1.0')!r}"
        )
    if (
        54 not in _tags(target_name, out, unit, job.rendered)
        and job.status == MigrationJobStatus.completed
    ):
        problems.append("tag 54 is not on the unit, and the job is completed")
    if target_name in _INDENTED:
        port_lines = _stanza(job.rendered, where)
        if any("10.54.0.1" in line or re.search(r"\b54\b", line) for line in port_lines):
            problems.append(f"the stanza of {where!r} states the unit: {port_lines}")
    return problems


class TestTheParse:
    def test_the_unit_is_a_record_of_its_own(self) -> None:
        tree = get_codec(JUNOS).parse(_ROUTED)
        by_name = {i.name: i for i in tree.interfaces}
        assert sorted(by_name) == ["ge-0/0/1", "ge-0/0/1.0", "ge-0/0/1.10", "ge-0/0/2"]
        unit, device = by_name["ge-0/0/1.0"], by_name["ge-0/0/1"]
        assert unit.dot1q_vlan == 54
        assert [a.ip for a in unit.ipv4_addresses] == ["10.54.0.1"]
        assert (device.description, device.dot1q_vlan, device.ipv4_addresses) == (
            "PARENT", None, [],
        )

    def test_a_unit_0_with_no_tag_is_the_device(self) -> None:
        tree = get_codec(JUNOS).parse(_ROUTED)
        (port,) = _holders(tree, "10.2.0.1")
        assert port.name == "ge-0/0/2"
        assert "ge-0/0/2.0" not in {i.name for i in tree.interfaces}

    def test_each_keeps_what_its_own_lines_state(self) -> None:
        """The device's description, MTU and ``disable`` are the
        device's; the unit's description and ``family inet mtu`` the
        unit's.  Read onto one record, the unit's description took
        the device's place."""
        tree = get_codec(JUNOS).parse(_OWN_AND_THE_UNITS)
        by_name = {i.name: i for i in tree.interfaces}
        device, unit = by_name["ge-0/0/1"], by_name["ge-0/0/1.0"]
        assert (device.description, device.enabled, device.mtu is not None) == (
            "PARENT", False, True,
        )
        assert (unit.description, unit.enabled, unit.ip_mtu, unit.mtu) == (
            "UNIT", True, 1500, None,
        )

    def test_a_disabled_unit_is_the_units(self) -> None:
        text = _ROUTED.replace(
            "set interfaces ge-0/0/1 unit 0 vlan-id 54",
            "set interfaces ge-0/0/1 unit 0 vlan-id 54\nset interfaces ge-0/0/1 unit 0 disable",
        )
        by_name = {i.name: i for i in get_codec(JUNOS).parse(text).interfaces}
        assert (by_name["ge-0/0/1"].enabled, by_name["ge-0/0/1.0"].enabled) == (True, False)

    def test_an_aggregates_unit_0(self) -> None:
        by_name = {i.name: i for i in get_codec(JUNOS).parse(_AGGREGATE).interfaces}
        assert by_name["ae2.0"].dot1q_vlan == 54
        assert (by_name["ae2"].description, by_name["ae2"].ipv4_addresses) == ("UPLINK", [])

    def test_a_routing_instance_binds_the_unit(self) -> None:
        """``interface ge-0/0/1.0`` names the unit where the unit is a
        record of its own, and the device where it is not -- and a
        unit 0 of a port the config has no line for is the port, as
        it was."""
        by_name = {i.name: i for i in get_codec(JUNOS).parse(_REFERRED_TO).interfaces}
        assert (by_name["ge-0/0/1.0"].vrf, by_name["ge-0/0/1"].vrf) == ("red", "")
        assert by_name["ge-0/0/2"].vrf == "blue"
        assert by_name["ge-0/0/9"].vrf == "blue"
        assert "ge-0/0/2.0" not in by_name and "ge-0/0/9.0" not in by_name

    def test_a_unit_that_switches_is_left_out_and_said(self) -> None:
        tree = get_codec(JUNOS).parse(_SWITCHING)
        by_name = {i.name: i for i in tree.interfaces}
        assert sorted(by_name) == ["ge-0/0/1"]
        device = by_name["ge-0/0/1"]
        assert (device.description, device.dot1q_vlan, device.switchport_mode) == (
            "PARENT", None, None,
        )
        assert [
            row for row in tree.dropped_tier3_sections if "ge-0/0/1: unit 0" in row
        ] == [
            "interfaces ge-0/0/1: unit 0 with a tag and family ethernet-switching "
            "-- a tagged unit that switches has no form in the tree, so the unit "
            "is not translated"
        ]

    def test_a_device_that_takes_no_tagging_statement_is_its_unit_0(self) -> None:
        """Juniper puts ``vlan-tagging`` on an Ethernet device; a
        tagged unit 0 of any other name is read onto its device, as it
        was.  Such a name is another vendor's VLAN interface, written
        here as unit 0 of a device of its name."""
        text = "\n".join([
            "set interfaces VL_100 unit 0 vlan-id 100",
            "set interfaces VL_100 unit 0 family inet address 10.100.0.1/24",
            "",
        ])
        by_name = {i.name: i for i in get_codec(JUNOS).parse(text).interfaces}
        assert sorted(by_name) == ["VL_100"]
        assert by_name["VL_100"].dot1q_vlan == 100
        assert [a.ip for a in by_name["VL_100"].ipv4_addresses] == ["10.100.0.1"]

    #: Where a device tagged 54 is read back from, written out by hand:
    #: the unit, of a device that takes a tagging statement; else the
    #: device.
    @pytest.mark.parametrize(("device", "holder"), [
        ("ge-0/0/1", "ge-0/0/1.0"),
        ("ae2", "ae2.0"),
        ("reth0", "reth0.0"),
        ("VL_100", "VL_100"),
        ("gn-mgmt", "gn-mgmt"),
    ])
    def test_each_reads_back_what_the_other_writes(self, device: str, holder: str) -> None:
        """A device that carries a tag is written ``unit 0 vlan-id``;
        read back, the tag and the address are on one record.  Read as
        a unit of a name that takes no tagging statement, a FortiGate
        or RouterOS VLAN interface lost its address to a record of a
        unit that its source does not have."""
        codec = get_codec(JUNOS)
        rendered = codec.render(CanonicalIntent(interfaces=[CanonicalInterface(
            name=device, dot1q_vlan=54,
            ipv4_addresses=[CanonicalIPv4Address(ip="10.54.0.1", prefix_length=24)],
        )]))
        assert f"set interfaces {device} unit 0 vlan-id 54" in rendered.splitlines()
        tree = codec.parse(rendered)
        assert [(i.name, i.dot1q_vlan) for i in _holders(tree, "10.54.0.1")] == [(holder, 54)]
        assert [i.name for i in tree.interfaces if i.dot1q_vlan is not None] == [holder]

    def test_a_tag_statement_not_read_whole_leaves_out_the_unit_only(self) -> None:
        text = _ROUTED.replace(
            "unit 0 vlan-id 54", "unit 0 vlan-id-list 54-56",
        )
        tree = get_codec(JUNOS).parse(text)
        by_name = {i.name: i for i in tree.interfaces}
        assert "ge-0/0/1.0" not in by_name and not _holders(tree, "10.54.0.1")
        assert by_name["ge-0/0/1"].description == "PARENT"
        assert any(
            row.startswith("interfaces ge-0/0/1 unit 0: vlan-id-list 54-56")
            for row in tree.dropped_tier3_sections
        )


class TestEveryTarget:
    @pytest.mark.parametrize("target_name", list_public_codecs())
    def test_the_unit_is_an_interface_of_its_own(self, target_name: str) -> None:
        assert _unit_problems(target_name) == []

    @pytest.mark.parametrize("target_name", list_public_codecs())
    def test_the_check_sees_the_old_reading(
        self, target_name: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(junos_parse, "_tagged_units_0", _folded)
        assert _unit_problems(target_name) != []

    @pytest.mark.parametrize("target_name", list_public_codecs())
    def test_a_unit_that_switches_puts_its_tag_on_no_port(self, target_name: str) -> None:
        job = _job(_SWITCHING, target_name)
        assert _switching_problems(job, target_name) == []

    @pytest.mark.parametrize("target_name", list_public_codecs())
    def test_the_switching_check_sees_the_old_reading(
        self, target_name: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(junos_parse, "_tagged_units_0", _folded)
        job = _job(_SWITCHING, target_name)
        assert _switching_problems(job, target_name) != []


def _switching_problems(job: MigrationJob, target_name: str) -> list[str]:
    """The port of ``_SWITCHING`` carries tag 54 in the output, or the
    job does not say the unit was left out."""
    out = get_codec(target_name).parse(job.rendered)
    where = job.port_renames.get("ge-0/0/1", "ge-0/0/1")
    problems = [
        f"{iface.name!r} carries tag 54"
        for iface in out.interfaces
        if iface.name == where and iface.dot1q_vlan == 54
    ]
    if target_name in _INDENTED:
        port_lines = _stanza(job.rendered, where)
        problems += [f"{where!r}: {line}" for line in port_lines if "dot1" in line.lower()]
    if target_name == JUNOS and "unit 0 vlan-id 54" in job.rendered:
        problems.append("the Junos output tags unit 0")
    if not any("unit 0 with a tag and family ethernet-switching" in row
               for row in job.dropped_tier3_sections):
        problems.append("the job does not say the unit was left out")
    return problems


class TestBetweenTwoJunosConfigs:
    def test_unit_0_stays_unit_0(self) -> None:
        """Rendered as the source states it, and read back as the
        source is read."""
        junos = get_codec(JUNOS)
        job = _job(_ROUTED, JUNOS)
        lines = job.rendered.splitlines()
        for line in (
            "set interfaces ge-0/0/1 vlan-tagging",
            "set interfaces ge-0/0/1 unit 0 vlan-id 54",
            "set interfaces ge-0/0/1 unit 0 family inet address 10.54.0.1/24",
            'set interfaces ge-0/0/1 description "PARENT"',
        ):
            assert line in lines
        assert job.status == MigrationJobStatus.completed
        assert junos.parse(job.rendered).interfaces == junos.parse(_ROUTED).interfaces

    def test_an_aggregates_unit_0_is_written_under_it(self) -> None:
        """``ae2.0`` is unit 0 of ``ae2``: no Junos interface has a dot
        in its name, and ``ae2`` is told its units carry tags."""
        job = _job(_AGGREGATE, JUNOS)
        lines = job.rendered.splitlines()
        assert "set interfaces ae2 vlan-tagging" in lines
        assert "set interfaces ae2 unit 0 vlan-id 54" in lines
        assert "set interfaces ae2 unit 0 family inet address 10.54.0.1/24" in lines
        assert not [line for line in lines if "ae2.0" in line]

    def test_the_references_stay_unit_0(self) -> None:
        job = _job(_REFERRED_TO, JUNOS)
        lines = job.rendered.splitlines()
        assert "set routing-instances red interface ge-0/0/1.0" in lines
        assert "set routing-options static route 192.0.2.0/24 next-hop ge-0/0/1.0" in lines


class TestAcrossVendors:
    @pytest.mark.parametrize(
        ("target_name", "lag"), [("arista_eos", "Port-Channel2"), ("cisco_iosxe_cli", "Port-channel2")],
    )
    def test_an_aggregates_unit_0(self, target_name: str, lag: str) -> None:
        job = _job(_AGGREGATE, target_name)
        assert job.port_renames["ae2"] == lag
        assert job.port_renames["ae2.0"] == f"{lag}.54"
        (unit,) = _holders(get_codec(target_name).parse(job.rendered), "10.54.0.1")
        assert (unit.name, unit.dot1q_vlan) == (f"{lag}.54", 54)

    @pytest.mark.parametrize("target_name", ["arista_eos", "cisco_iosxe_cli", "cisco_nxos"])
    def test_the_references_go_with_it(self, target_name: str) -> None:
        """The instance binds the unit, not its port, and the route's
        next hop is the unit's new name."""
        job = _job(_REFERRED_TO, target_name)
        out = get_codec(target_name).parse(job.rendered)
        where = job.port_renames["ge-0/0/1"]
        (unit,) = _holders(out, "10.54.0.1")
        assert (unit.name, unit.vrf) == (f"{where}.54", "red")
        assert [i.vrf for i in out.interfaces if i.name == where] in ([""], [])
        (route,) = [r for r in out.static_routes if r.destination.startswith("192.0.2.0")]
        assert route.interface == f"{where}.54"

    @pytest.mark.parametrize("target_name", ["arista_eos", "cisco_iosxe_cli"])
    def test_two_units_on_one_name_are_said(self, target_name: str) -> None:
        """Unit 0 tagged 54 and unit 54 are one name onto a target that
        names a unit 0 by its tag: the job is ``partial`` and says
        which."""
        job = _job(_ONE_NAME, target_name)
        where = job.port_renames["ge-0/0/1"]
        assert job.status == MigrationJobStatus.partial
        assert job.fused_ports == {f"{where}.54": ["ge-0/0/1.0", "ge-0/0/1.54"]}
