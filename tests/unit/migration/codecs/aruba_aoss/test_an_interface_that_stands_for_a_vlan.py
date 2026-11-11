"""An interface that stands for a VLAN is that VLAN on AOS-S, by the
tree's own id, or a review line.

AOS-S routes on a VLAN and has no form for a routed sub-interface.  The
renderer read a VLAN's id from an interface's NAME: a sub-interface came
out as ``interface <port>.<unit>``, a stanza AOS-S has no form for, and
a RouterOS VLAN interface ``vlan10`` that carries VLAN 20 put its address
on VLAN 10 -- in jobs that said nothing of either.  Now a sub-interface
is VLAN <tag>, tagged on its port, with its addresses, and a VLAN
interface its parser links to its VLAN record by name is that record's
VLAN -- or, where the VLAN is called by its label on AOS-S, the VLAN of
the label it carries; what cannot be written so is left out under a
``; review:`` line.

The sources are typed by hand, one per grammar that states a
sub-interface, each with a unit whose number is not its tag, and sent
onto AOS-S through the plan path with the port named ``2``.  The output
is read as text, by a reader of this module's own, and with the AOS-S
parser; and each check is handed the defect it is for.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalVlan,
)
from netcanon.migration.codecs.aruba_aoss import codec as aoss_codec
from netcanon.migration.codecs.aruba_aoss import render as aoss_render
from netcanon.migration.codecs.aruba_aoss import vlan_interfaces
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_vlan_members_reach_the_output import _captures

pytestmark = pytest.mark.unit

AOSS = "aruba_aoss"
_IP = "198.51.100.1"

#: Per source codec: the port, and a config with a sub-interface of it
#: that carries VLAN 200 and the address ``198.51.100.1/24`` -- unit 100
#: where the grammar lets a unit's number differ from its tag.
_SOURCES: dict[str, tuple[str, str]] = {
    "cisco_iosxe_cli": ("GigabitEthernet0/0/2", (
        "hostname r1\ninterface GigabitEthernet0/0/2\n no switchport\n!\n"
        "interface GigabitEthernet0/0/2.100\n encapsulation dot1Q 200\n"
        " ip address 198.51.100.1 255.255.255.0\n!\n"
    )),
    "juniper_junos": ("ge-0/0/2", (
        "set system host-name r1\nset interfaces ge-0/0/2 vlan-tagging\n"
        "set interfaces ge-0/0/2 unit 100 vlan-id 200\n"
        "set interfaces ge-0/0/2 unit 100 family inet address 198.51.100.1/24\n"
    )),
    "arista_eos": ("Ethernet2", (
        "hostname r1\n!\ninterface Ethernet2\n   no switchport\n!\n"
        "interface Ethernet2.100\n   encapsulation dot1q vlan 200\n"
        "   ip address 198.51.100.1/24\n!\n"
    )),
    "cisco_nxos": ("Ethernet1/2", (
        "hostname r1\n!\ninterface Ethernet1/2\n  no switchport\n!\n"
        "interface Ethernet1/2.100\n  encapsulation dot1q 200\n"
        "  ip address 198.51.100.1/24\n!\n"
    )),
    # The parser makes an empty VLAN record of the tag as well.
    "cisco_iosxr": ("GigabitEthernet0/0/0/2", (
        "hostname r1\n!\ninterface GigabitEthernet0/0/0/2\n!\n"
        "interface GigabitEthernet0/0/0/2.100\n encapsulation dot1q 200\n"
        " ipv4 address 198.51.100.1 255.255.255.0\n!\n"
    )),
    # A vif's number is its tag.
    "vyos": ("eth2", (
        "interfaces {\n    ethernet eth2 {\n        vif 200 {\n"
        "            address 198.51.100.1/24\n        }\n    }\n}\n"
        "system {\n    host-name r1\n}\n"
    )),
    # A VLAN interface on a port, whose name is free text.
    "fortigate_cli": ("port2", (
        "config system interface\n"
        '    edit "port2"\n        set vdom "root"\n        set type physical\n    next\n'
        '    edit "users"\n        set vdom "root"\n        set ip 198.51.100.1 255.255.255.0\n'
        '        set interface "port2"\n        set vlanid 200\n    next\nend\n'
    )),
    "opnsense": ("igb2", (
        '<?xml version="1.0"?>\n<opnsense>\n'
        "  <system><hostname>r1</hostname><domain>example.test</domain></system>\n"
        "  <interfaces>\n"
        "    <opt1><if>vlan0.100</if><enable>1</enable><ipaddr>198.51.100.1</ipaddr>"
        "<subnet>24</subnet></opt1>\n"
        "  </interfaces>\n"
        "  <vlans>\n    <vlan><if>igb2</if><tag>200</tag><vlanif>vlan0.100</vlanif></vlan>\n"
        "  </vlans>\n</opnsense>\n"
    )),
    "mikrotik_routeros": ("ether2", (
        "/interface vlan\nadd interface=ether2 name=vlan100 vlan-id=200\n"
        "/ip address\nadd address=198.51.100.1/24 interface=vlan100\n"
        "/system identity\nset name=r1\n"
    )),
}


def _job(source: str, text: str, port_rename_map: dict[str, str]) -> MigrationJob:
    job = run_plan_with_checked_names(
        get_codec(source), get_codec(AOSS), text, port_rename_map=port_rename_map,
    )
    assert job.rendered, job.error
    return job


def _stanzas(text: str) -> dict[str, list[str]]:
    """Each stanza of an AOS-S *text* by its header line, with its lines
    stripped: from a line in column 0 to the next.  A header met twice
    has the lines of both."""
    stanzas: dict[str, list[str]] = {}
    body: list[str] | None = None
    for line in text.splitlines():
        if line[:1].strip():
            body = stanzas.setdefault(line.strip(), [])
        elif body is not None and line.strip():
            body.append(line.strip())
    return stanzas


def _on(text: str, ip: str) -> list[str]:
    """The interfaces the AOS-S parser reads *ip* onto."""
    return [
        iface.name for iface in get_codec(AOSS).parse(text).interfaces
        if any(address.ip == ip for address in iface.ipv4_addresses)
    ]


def _tagged(text: str, vid: int) -> list[str]:
    """The ports the AOS-S parser reads as tagged in VLAN *vid*."""
    return [
        port.lower() for vlan in get_codec(AOSS).parse(text).vlans
        if vlan.id == vid for port in vlan.tagged_ports
    ]


def _written_problems(job: MigrationJob, vid: int = 200, port: str = "2") -> list[str]:
    """What is wrong with a sub-interface of VLAN *vid* on *port*,
    address ``198.51.100.1/24``, in the output of *job*: it has to be
    VLAN *vid*, tagged on *port*, with the address and nothing else, in
    the text and read back; no stanza of a unit; one warning that says
    so; and a job that is ``partial``."""
    out = job.rendered or ""
    stanzas = _stanzas(out)
    problems: list[str] = []
    body = stanzas.get(f"vlan {vid}")
    if body != [f"tagged {port}", f"ip address {_IP}/24", "exit"]:
        problems.append(f"vlan {vid} is {body}")
    units = [h for h in stanzas if h.startswith("interface ") and "." in h]
    if units:
        problems.append(f"the output has {units}")
    if _tagged(out, vid) != [port]:
        problems.append(f"VLAN {vid} is read as tagged on {_tagged(out, vid)}")
    if _on(out, _IP) != [f"Vlan{vid}"]:
        problems.append(f"{_IP} is read onto {_on(out, _IP)}")
    said = [w for w in job.warnings if f"is written as VLAN {vid}, tagged on {port}:" in w]
    if len(said) != 1:
        problems.append(f"the job says it {len(said)} times")
    if job.status is not MigrationJobStatus.partial:
        problems.append(f"the job is {job.status.value}")
    return problems


class TestASubInterface:
    @pytest.mark.parametrize("source", sorted(_SOURCES))
    def test_is_the_vlan_of_its_tag_on_its_port(self, source: str) -> None:
        port, text = _SOURCES[source]
        assert _written_problems(_job(source, text, {port: "2"})) == []

    def test_the_iosxr_record_of_the_tag_is_the_vlan_it_is_written_as(self) -> None:
        """The IOS XR parser makes a VLAN record of each tag a
        sub-interface states: it holds nothing, and is no network of its
        own beside the sub-interface."""
        tree = get_codec("cisco_iosxr").parse(_SOURCES["cisco_iosxr"][1])
        assert [(v.id, v.tagged_ports, v.untagged_ports, v.ipv4_addresses) for v in tree.vlans] == [
            (200, [], [], []),
        ]

    def test_a_route_out_of_it_goes_out_of_its_vlan(self) -> None:
        port, text = _SOURCES["cisco_iosxe_cli"]
        text += "ip route 192.0.2.0 255.255.255.0 GigabitEthernet0/0/2.100\n"
        job = _job("cisco_iosxe_cli", text, {port: "2"})
        assert "ip route 192.0.2.0/24 vlan 200" in job.rendered.splitlines()

    def test_its_ipv6_address_and_vrrp_group_are_its_vlans(self) -> None:
        port, text = _SOURCES["cisco_iosxe_cli"]
        text = text.replace(
            " ip address 198.51.100.1 255.255.255.0\n",
            " ip address 198.51.100.1 255.255.255.0\n ipv6 address 2001:db8:200::1/64\n"
            " vrrp 5 ip 198.51.100.254\n",
        )
        job = _job("cisco_iosxe_cli", text, {port: "2"})
        body = _stanzas(job.rendered)["vlan 200"]
        assert "ipv6 address 2001:db8:200::1/64" in body
        assert body[body.index("vrrp vrid 5") + 1] == "virtual-ip-address 198.51.100.254"
        (vlan_200,) = [i for i in get_codec(AOSS).parse(job.rendered).interfaces if i.name == "Vlan200"]
        assert [g.virtual_ips for g in vlan_200.vrrp_groups] == [["198.51.100.254"]]
        assert [a.ip for a in vlan_200.ipv6_addresses] == ["2001:db8:200::1"]

    def test_a_dhcp_pool_on_it_is_served_by_its_vlan(self) -> None:
        """A FortiGate pool on a VLAN interface was on an interface no
        VLAN stanza stood for, and so served only to relayed clients:
        it is the VLAN's now, as the interface is."""
        port, text = _SOURCES["fortigate_cli"]
        text += (
            "config system dhcp server\n    edit 1\n"
            "        set default-gateway 198.51.100.1\n        set netmask 255.255.255.0\n"
            '        set interface "users"\n        config ip-range\n            edit 1\n'
            "                set start-ip 198.51.100.100\n                set end-ip 198.51.100.200\n"
            "            next\n        end\n    next\nend\n"
        )
        job = _job("fortigate_cli", text, {port: "2"})
        stanzas = _stanzas(job.rendered)
        assert stanzas["vlan 200"] == [
            "tagged 2", f"ip address {_IP}/24", "dhcp-server", "exit",
        ]
        assert "range 198.51.100.100 198.51.100.200" in stanzas['dhcp-server pool "pool-1"']
        assert [line for line in job.rendered.splitlines() if line.startswith("; review:")] == []
        assert [pool.interface for pool in get_codec(AOSS).parse(job.rendered).dhcp_servers] == [
            "Vlan200",
        ]

    def test_one_in_a_vrf_is_written_without_it(self) -> None:
        """As the renderer writes every interface of a VRF, an SVI of
        IOS-XE among them: AOS-S has no VRF, and the job lists the VRF
        as dropped."""
        text = (
            "hostname r1\nvrf definition red\n address-family ipv4\n exit-address-family\n!\n"
            "interface GigabitEthernet0/0/2\n no switchport\n!\n"
            "interface GigabitEthernet0/0/2.100\n encapsulation dot1Q 200\n"
            " vrf forwarding red\n ip address 198.51.100.1 255.255.255.0\n!\n"
        )
        job = _job("cisco_iosxe_cli", text, {"GigabitEthernet0/0/2": "2"})
        assert _written_problems(job) == []
        assert [line for line in job.rendered.splitlines() if line.startswith("; review:")] == []
        assert "/interfaces/interface/config/vrf" in {
            lossy.path for lossy in job.validation.lossy_paths
        }

    @pytest.mark.parametrize("source", sorted(_SOURCES))
    @pytest.mark.parametrize("defect", ["under_its_own_name", "on_no_port", "unsaid"])
    def test_the_check_sees_each_defect(
        self, source: str, defect: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Handed the renderer as it was (no interface read for the VLAN
        it stands for), one that tags no port in the VLAN, or a job that
        says nothing, the check above fails."""
        real = aoss_render.prepare_vlan_interfaces

        def prepare(tree):
            if defect == "under_its_own_name":
                return vlan_interfaces.Prepared(tree)
            prepared = real(tree)
            if defect == "on_no_port":
                for vlan in prepared.tree.vlans:
                    vlan.tagged_ports = []
            return prepared

        monkeypatch.setattr(aoss_render, "prepare_vlan_interfaces", prepare)
        if defect == "unsaid":
            monkeypatch.setattr(aoss_codec, "vlan_interface_warnings", lambda tree: [])
        port, text = _SOURCES[source]
        assert _written_problems(_job(source, text, {port: "2"})) != []


_IOSXE_PORT = "interface GigabitEthernet0/0/2\n no switchport\n!\n"
_IOSXE_UNIT = (
    "interface GigabitEthernet0/0/2.100\n{body} ip address 198.51.100.1 255.255.255.0\n!\n"
)
_MAP = {"GigabitEthernet0/0/2": "2", "GigabitEthernet0/0/3": "3", "GigabitEthernet0/0/4": "4"}

#: Each sub-interface AOS-S has no form for, as IOS-XE states it, and
#: why it is left out (the text of its review line, between ``interface
#: 2.100`` and ``; not written``).
_REFUSED = {
    "two tags": (
        _IOSXE_PORT + _IOSXE_UNIT.format(body=" encapsulation dot1Q 200 second-dot1q 300\n"),
        "matches two 802.1Q tags (200, then 300), and AOS-S has no form for that",
    ),
    "the untagged frames": (
        _IOSXE_PORT + _IOSXE_UNIT.format(body=" encapsulation dot1Q 200 native\n"),
        "also takes the untagged frames of 2, and an AOS-S VLAN has no form for that",
    ),
    "disabled": (
        _IOSXE_PORT + _IOSXE_UNIT.format(body=" encapsulation dot1Q 200\n shutdown\n"),
        "is disabled, and an AOS-S VLAN cannot be",
    ),
    "VLAN 1": (
        _IOSXE_PORT + _IOSXE_UNIT.format(body=" encapsulation dot1Q 1\n"),
        "carries VLAN 1, the switch's default VLAN, which every port of the switch is in",
    ),
    "a VLAN with a port": (
        "vlan 200\n!\ninterface GigabitEthernet0/0/4\n switchport access vlan 200\n!\n"
        + _IOSXE_PORT + _IOSXE_UNIT.format(body=" encapsulation dot1Q 200\n"),
        "carries VLAN 200, which the config also has as a VLAN; on AOS-S the two would "
        "be one network",
    ),
    "a VLAN with an address": (
        "vlan 200\n!\ninterface Vlan200\n ip address 192.0.2.1 255.255.255.0\n!\n"
        + _IOSXE_PORT + _IOSXE_UNIT.format(body=" encapsulation dot1Q 200\n"),
        "carries VLAN 200, which the config also has as a VLAN; on AOS-S the two would "
        "be one network",
    ),
    "another unit of the tag": (
        _IOSXE_PORT + _IOSXE_UNIT.format(body=" encapsulation dot1Q 200\n")
        + "interface GigabitEthernet0/0/3\n no switchport\n!\n"
        "interface GigabitEthernet0/0/3.100\n encapsulation dot1Q 200\n"
        " ip address 198.51.101.1 255.255.255.0\n!\n",
        "carries VLAN 200, as 3.100 does; on AOS-S the two would be one network",
    ),
}


def _refused_problems(job: MigrationJob, name: str, why: str, ip: str = _IP) -> list[str]:
    """What is wrong with interface *name*, left out for *why*, in the
    output of *job*: one review line where it would be and one warning,
    each saying why; its address nowhere; a job that is ``partial``."""
    out = job.rendered or ""
    problems: list[str] = []
    review = [line for line in out.splitlines() if line == f"; review: interface {name} {why}; not written"]
    if len(review) != 1:
        problems.append(f"{len(review)} review lines")
    said = [w for w in job.warnings if w == f"interface {name} {why}; not written"]
    if len(said) != 1:
        problems.append(f"{len(said)} warnings")
    if ip in out:
        problems.append(f"{ip} is in the output")
    if job.status is not MigrationJobStatus.partial:
        problems.append(f"the job is {job.status.value}")
    return problems


class TestWhatIsLeftOut:
    @pytest.mark.parametrize("case", sorted(_REFUSED))
    def test_under_a_review_line(self, case: str) -> None:
        text, why = _REFUSED[case]
        job = _job("cisco_iosxe_cli", "hostname r1\n" + text, _MAP)
        assert _refused_problems(job, "2.100", why) == []
        # No VLAN takes the port for it.
        assert "2" not in _tagged(job.rendered, 200)

    def test_two_units_of_one_tag_are_both_left_out(self) -> None:
        text, _ = _REFUSED["another unit of the tag"]
        job = _job("cisco_iosxe_cli", "hostname r1\n" + text, _MAP)
        why = "carries VLAN 200, as 2.100 does; on AOS-S the two would be one network"
        assert _refused_problems(job, "3.100", why, ip="198.51.101.1") == []

    def test_a_route_out_of_one_is_not_written(self) -> None:
        text, _ = _REFUSED["disabled"]
        text += "ip route 192.0.2.0 255.255.255.0 GigabitEthernet0/0/2.100\n"
        job = _job("cisco_iosxe_cli", "hostname r1\n" + text, _MAP)
        assert [line for line in job.rendered.splitlines() if line.startswith("ip route")] == []
        assert [
            line for line in job.rendered.splitlines()
            if line.startswith("; review: static route 192.0.2.0/24 goes out 2.100, ")
        ]

    @pytest.mark.parametrize("case", sorted(_REFUSED))
    def test_the_check_sees_a_line_unsaid(self, case: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """Handed a renderer that writes no review line, or a job that
        says nothing, the check above fails."""
        real = aoss_render.prepare_vlan_interfaces

        def prepare(tree):
            prepared = real(tree)
            return vlan_interfaces.Prepared(
                prepared.tree, {}, prepared.not_a_vlan, prepared.warnings,
            )

        text, why = _REFUSED[case]
        monkeypatch.setattr(aoss_render, "prepare_vlan_interfaces", prepare)
        job = _job("cisco_iosxe_cli", "hostname r1\n" + text, _MAP)
        assert _refused_problems(job, "2.100", why) != []
        monkeypatch.undo()
        monkeypatch.setattr(aoss_codec, "vlan_interface_warnings", lambda tree: [])
        job = _job("cisco_iosxe_cli", "hostname r1\n" + text, _MAP)
        assert _refused_problems(job, "2.100", why) != []


def _address(ip: str) -> list[CanonicalIPv4Address]:
    return [CanonicalIPv4Address(ip=ip, prefix_length=24)]


def _render(tree: CanonicalIntent) -> tuple[str, list[str]]:
    codec = get_codec(AOSS)
    return codec.render(tree), codec.render_warnings(tree)


class TestTreesNoParserMakesHere:
    """Shapes the sources above do not state, built as trees."""

    def test_an_svi_named_for_the_tag(self) -> None:
        """``Vlan200`` stands for VLAN 200 by its name, and keeps that
        reading: the sub-interface is left out."""
        tree = CanonicalIntent(interfaces=[
            CanonicalInterface(name="Vlan200", ipv4_addresses=_address("192.0.2.1")),
            CanonicalInterface(name="2"),
            CanonicalInterface(
                name="2.100", dot1q_vlan=200, vlan_parent="2", ipv4_addresses=_address(_IP),
            ),
        ])
        out, warnings = _render(tree)
        why = (
            "stands for VLAN 200, as Vlan200 does, and an AOS-S VLAN stanza is one "
            "interface's"
        )
        assert f"; review: interface 2.100 {why}; not written" in out.splitlines()
        assert f"interface 2.100 {why}; not written" in warnings
        assert _IP not in out

    @pytest.mark.parametrize(("parent", "why"), [
        ("loopback0", "is a unit of loopback0, which is no port AOS-S can tag"),
        ("oobm", "is a unit of oobm, which is no port AOS-S can tag"),
        ("2.5", "is a unit of 2.5, which is no port AOS-S can tag"),
        # A port list is written unquoted: a name with a space, a comma
        # or a quote in it is no entry of one (FortiOS names are free
        # text).  This parser would read `tagged my port` back whole.
        ("my port", "is a unit of my port, which is no port AOS-S can tag"),
        ("1,2", "is a unit of 1,2, which is no port AOS-S can tag"),
        ('"wan"', 'is a unit of "wan", which is no port AOS-S can tag'),
        ("", "names no port it is a unit of"),
    ])
    def test_on_no_port_aoss_can_tag(self, parent: str, why: str) -> None:
        tree = CanonicalIntent(interfaces=[
            CanonicalInterface(
                name="sub", dot1q_vlan=200, vlan_parent=parent or None,
                ipv4_addresses=_address(_IP),
            ),
        ])
        out, warnings = _render(tree)
        assert f"; review: interface sub {why}; not written" in out.splitlines()
        assert f"interface sub {why}; not written" in warnings
        assert _IP not in out

    def test_a_vlan_interface_of_two_vlans(self) -> None:
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(id=20, name="lan"), CanonicalVlan(id=30, name="lan")],
            interfaces=[CanonicalInterface(
                name="lan", interface_type="ianaift:l3ipvlan", vlan_parent="bridge1",
                ipv4_addresses=_address(_IP),
            )],
        )
        out, warnings = _render(tree)
        why = "is the interface of VLANs 20, 30, and an AOS-S VLAN stanza is one VLAN's"
        assert f"; review: interface lan {why}; not written" in out.splitlines()
        assert f"interface lan {why}; not written" in warnings
        assert _IP not in out

    def test_a_vlan_interface_in_a_vrf(self) -> None:
        """Written without its VRF, as every interface is, and as the
        VLAN its record names -- not VLAN 10, by its name."""
        tree = CanonicalIntent(
            vlans=[CanonicalVlan(id=20, name="vlan10")],
            interfaces=[CanonicalInterface(
                name="vlan10", interface_type="ianaift:l3ipvlan", vlan_parent="bridge1",
                vrf="red", ipv4_addresses=_address(_IP),
            )],
        )
        out, _ = _render(tree)
        assert [line for line in out.splitlines() if line.startswith("; review:")] == []
        assert f"ip address {_IP}/24" in _stanzas(out)["vlan 20"]
        assert "vlan 10" not in _stanzas(out)
        assert "red" not in out

    def test_the_tree_given_is_not_changed(self) -> None:
        port, text = _SOURCES["cisco_iosxe_cli"]
        tree = get_codec("cisco_iosxe_cli").parse(text)
        before = tree.model_dump()
        get_codec(AOSS).render(tree)
        get_codec(AOSS).render_warnings(tree)
        assert tree.model_dump() == before


def _ros(vlans: list[str], addresses: list[str], extra: str = "") -> str:
    """A RouterOS config with VLAN interfaces *vlans* on a bridge."""
    return (
        "/interface bridge\nadd name=bridge1\n"
        "/interface bridge port\nadd bridge=bridge1 interface=ether2\n"
        "/interface vlan\n" + "".join(f"{line}\n" for line in vlans)
        + "/ip address\n" + "".join(f"{line}\n" for line in addresses)
        + extra + "/system identity\nset name=r1\n"
    )


class TestAVlanInterfaceItsRecordNames:
    """A VLAN interface its parser links to its VLAN record by name is
    that record's VLAN, never the digits in its name: on RouterOS a name
    is free text."""

    def test_its_name_says_another_vlan(self) -> None:
        text = _ros(
            ["add interface=bridge1 name=vlan10 vlan-id=20",
             "add interface=bridge1 name=office vlan-id=30"],
            ["add address=10.20.0.1/24 interface=vlan10", "add address=10.30.0.1/24 interface=office"],
            "/ip route\nadd dst-address=192.168.50.0/24 gateway=vlan10\n",
        )
        out = _job("mikrotik_routeros", text, {}).rendered
        stanzas = _stanzas(out)
        assert "ip address 10.20.0.1/24" in stanzas["vlan 20"]
        assert "ip address 10.30.0.1/24" in stanzas["vlan 30"]
        assert "vlan 10" not in stanzas
        assert _on(out, "10.20.0.1") == ["Vlan20"]
        assert "ip route 192.168.50.0/24 vlan 20" in out.splitlines()
        assert not [h for h in stanzas if h.startswith("interface ")]

    def test_two_names_that_say_each_others_vlan(self) -> None:
        text = _ros(
            ["add interface=bridge1 name=vlan10 vlan-id=20",
             "add interface=bridge1 name=vlan20 vlan-id=10"],
            ["add address=10.20.0.1/24 interface=vlan10", "add address=10.10.0.1/24 interface=vlan20"],
        )
        out = _job("mikrotik_routeros", text, {}).rendered
        assert (_on(out, "10.20.0.1"), _on(out, "10.10.0.1")) == (["Vlan20"], ["Vlan10"])
        stanzas = _stanzas(out)
        assert "ip address 10.20.0.1/24" in stanzas["vlan 20"]
        assert "ip address 10.10.0.1/24" in stanzas["vlan 10"]

    def test_a_disabled_one_is_left_out(self) -> None:
        text = _ros(
            ["add disabled=yes interface=bridge1 name=vlan10 vlan-id=20"],
            ["add address=10.20.0.1/24 interface=vlan10"],
        )
        job = _job("mikrotik_routeros", text, {})
        assert _refused_problems(job, "vlan10", "is disabled, and an AOS-S VLAN cannot be", "10.20.0.1") == []

    def test_an_opnsense_device_on_a_bridge(self) -> None:
        """``vlan0.100`` names VLAN 100 by its form; its device carries
        200."""
        text = (
            '<?xml version="1.0"?>\n<opnsense>\n'
            "  <system><hostname>r1</hostname><domain>example.test</domain></system>\n"
            "  <interfaces>\n"
            "    <lan><if>igb1</if><enable>1</enable><ipaddr>192.0.2.1</ipaddr>"
            "<subnet>24</subnet></lan>\n"
            "    <opt1><if>vlan0.100</if><enable>1</enable><ipaddr>198.51.100.1</ipaddr>"
            "<subnet>24</subnet></opt1>\n"
            "  </interfaces>\n"
            "  <bridges>\n    <bridged><members>lan</members><bridgeif>bridge0</bridgeif></bridged>\n"
            "  </bridges>\n"
            "  <vlans>\n    <vlan><if>bridge0</if><tag>200</tag><vlanif>vlan0.100</vlanif></vlan>\n"
            "  </vlans>\n</opnsense>\n"
        )
        out = _job("opnsense", text, {}).rendered
        assert _on(out, _IP) == ["Vlan200"]
        assert f"ip address {_IP}/24" in _stanzas(out)["vlan 200"]
        assert "vlan 100" not in _stanzas(out)

    def test_the_check_sees_the_reading_by_its_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Handed the renderer as it was, ``vlan10`` is VLAN 10."""
        monkeypatch.setattr(
            aoss_render, "prepare_vlan_interfaces", lambda tree: vlan_interfaces.Prepared(tree),
        )
        text = _ros(
            ["add interface=bridge1 name=vlan10 vlan-id=20"],
            ["add address=10.20.0.1/24 interface=vlan10"],
        )
        out = _job("mikrotik_routeros", text, {}).rendered
        assert _on(out, "10.20.0.1") != ["Vlan20"]


#: RouterOS VLAN interfaces whose names say each other's VLAN, each with
#: a label: ``vlan10`` carries VLAN 20 and is labelled ``Users``.
_ROS_LABELLED = _ros(
    ['add comment="Users" interface=bridge1 name=vlan10 vlan-id=20',
     'add comment="Voice" interface=bridge1 name=vlan20 vlan-id=10'],
    ["add address=10.20.0.1/24 interface=vlan10", "add address=10.10.0.1/24 interface=vlan20"],
)

#: The same on a FortiGate's FortiLink, labelled with ``set alias``.
_FORTILINK_LABELLED = (
    "config system interface\n"
    '    edit "fortilink"\n        set vdom "root"\n        set fortilink enable\n'
    "        set type aggregate\n    next\n"
    '    edit "vlan10"\n        set vdom "root"\n        set ip 10.20.0.1 255.255.255.0\n'
    '        set alias "Users"\n        set interface "fortilink"\n        set vlanid 20\n    next\n'
    '    edit "vlan20"\n        set vdom "root"\n        set ip 10.10.0.1 255.255.255.0\n'
    '        set alias "Voice"\n        set interface "fortilink"\n        set vlanid 10\n    next\n'
    "end\n"
)

#: OPNsense VLAN devices on a bridge whose names say each other's tag,
#: each with a ``<descr>``: ``vlan0.100`` carries VLAN 200, ``USERS``.
_OPN_LABELLED = (
    '<?xml version="1.0"?>\n<opnsense>\n'
    "  <system><hostname>r1</hostname><domain>example.test</domain></system>\n"
    "  <interfaces>\n"
    "    <lan><if>igb1</if><enable>1</enable><ipaddr>192.0.2.1</ipaddr><subnet>24</subnet></lan>\n"
    "    <opt1><if>vlan0.100</if><enable>1</enable><ipaddr>198.51.100.1</ipaddr>"
    "<subnet>24</subnet></opt1>\n"
    "    <opt2><if>vlan0.200</if><enable>1</enable><ipaddr>203.0.113.1</ipaddr>"
    "<subnet>24</subnet></opt2>\n"
    "  </interfaces>\n"
    "  <bridges>\n    <bridged><members>lan</members><bridgeif>bridge0</bridgeif></bridged>\n"
    "  </bridges>\n"
    "  <vlans>\n"
    "    <vlan><if>bridge0</if><tag>200</tag><descr>USERS</descr><vlanif>vlan0.100</vlanif></vlan>\n"
    "    <vlan><if>bridge0</if><tag>100</tag><descr>VOICE</descr><vlanif>vlan0.200</vlanif></vlan>\n"
    "  </vlans>\n</opnsense>\n"
)

_UNKNOWN = "which VLAN it carries is not known here: no VLAN is named after it, nor has its label"


class TestAVlanInterfaceByItsLabel:
    """A VLAN that has a label is called by it on AOS-S, and its record is
    then named after no interface: where the platform has one label for
    a VLAN and its interface, the record is found by the label the
    interface carries; where none is found, the interface is left out
    and said, never read by the digits of its name.  Read so, each
    address below went to the other VLAN."""

    @pytest.mark.parametrize(
        ("source", "text"),
        [("mikrotik_routeros", _ROS_LABELLED), ("fortigate_cli", _FORTILINK_LABELLED)],
        ids=["routeros", "fortilink"],
    )
    def test_each_is_the_vlan_of_its_label(self, source: str, text: str) -> None:
        out = _job(source, text, {}).rendered
        stanzas = _stanzas(out)
        assert (_on(out, "10.20.0.1"), _on(out, "10.10.0.1")) == (["Vlan20"], ["Vlan10"])
        assert {'name "Users"', "ip address 10.20.0.1/24"} <= set(stanzas["vlan 20"])
        assert {'name "Voice"', "ip address 10.10.0.1/24"} <= set(stanzas["vlan 10"])
        assert not [h for h in stanzas if h.lower().startswith("interface vlan")]
        assert not [line for line in out.splitlines() if line.startswith("; review: interface vlan")]

    def test_one_that_holds_nothing_is_no_stanza(self) -> None:
        text = _ros(['add comment="Users" interface=bridge1 name=vlan10 vlan-id=20'], [])
        out = _job("mikrotik_routeros", text, {}).rendered
        assert 'name "Users"' in _stanzas(out)["vlan 20"]
        assert not [h for h in _stanzas(out) if h.startswith("interface ")]
        assert not [line for line in out.splitlines() if line.startswith("; review: interface")]

    def test_one_label_of_two_vlans_is_left_out(self) -> None:
        text = _ros(
            ['add comment="Users" interface=bridge1 name=vlan10 vlan-id=20',
             'add comment="Users" interface=bridge1 name=vlan20 vlan-id=10'],
            ["add address=10.20.0.1/24 interface=vlan10", "add address=10.10.0.1/24 interface=vlan20"],
        )
        job = _job("mikrotik_routeros", text, {})
        why = "has the label of VLANs 10, 20, and which of them it carries is not known here"
        assert _refused_problems(job, "vlan10", why, "10.20.0.1") == []
        assert _refused_problems(job, "vlan20", why, "10.10.0.1") == []

    def test_an_opnsense_device_with_a_label_is_left_out(self) -> None:
        """OPNsense labels a VLAN device and the zone on it apart, so
        nothing links ``vlan0.100`` to its VLAN once that VLAN is called
        by its label.  The VLANs are written, by their labels."""
        job = _job("opnsense", _OPN_LABELLED, {})
        why = f"rides on bridge0, and {_UNKNOWN}"
        assert _refused_problems(job, "vlan0.100", why, "198.51.100.1") == []
        assert _refused_problems(job, "vlan0.200", why, "203.0.113.1") == []
        stanzas = _stanzas(job.rendered)
        assert 'name "USERS"' in stanzas["vlan 200"]
        assert 'name "VOICE"' in stanzas["vlan 100"]

    def test_an_entry_that_names_it_for_its_vlan(self) -> None:
        """An entry of the port map that names it ``Vlan20``, the name
        AOS-S has for VLAN 20's interface, says its VLAN: the record is
        still named after the name the entry replaced."""
        text = _ros(["add interface=bridge1 name=vlan10 vlan-id=20"], ["add address=10.20.0.1/24 interface=vlan10"])
        out = _job("mikrotik_routeros", text, {"vlan10": "Vlan20"}).rendered
        assert _on(out, "10.20.0.1") == ["Vlan20"]
        assert "ip address 10.20.0.1/24" in _stanzas(out)["vlan 20"]

    def test_an_entry_that_names_no_vlan_is_left_out(self) -> None:
        """Up to 0.7.7 this was ``interface lan`` with the address, a
        stanza AOS-S has no form for."""
        text = _ros(["add interface=bridge1 name=vlan10 vlan-id=20"], ["add address=10.20.0.1/24 interface=vlan10"])
        job = _job("mikrotik_routeros", text, {"vlan10": "lan"})
        assert _refused_problems(job, "lan", f"rides on bridge1, and {_UNKNOWN}", "10.20.0.1") == []

    def test_the_check_sees_the_link_by_its_label_taken_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(vlan_interfaces, "_ONE_LABEL", frozenset())
        out = _job("mikrotik_routeros", _ROS_LABELLED, {}).rendered
        assert (_on(out, "10.20.0.1"), _on(out, "10.10.0.1")) != (["Vlan20"], ["Vlan10"])

    def test_the_check_sees_a_reading_by_its_digits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Handed a reader of the digits of any name, ``vlan0.100`` is
        VLAN 100, which it does not carry."""
        monkeypatch.setattr(
            vlan_interfaces, "_AOSS_VLAN_NAME_RE", re.compile(r"[A-Za-z]+\d*\.?([1-9]\d{0,3})"),
        )
        job = _job("opnsense", _OPN_LABELLED, {})
        assert _refused_problems(job, "vlan0.100", f"rides on bridge0, and {_UNKNOWN}", "198.51.100.1") != []


def test_the_platforms_of_one_label() -> None:
    """``_ONE_LABEL`` is the parsers that read one label as the
    description of a VLAN and of the interface it is named after, on the
    committed captures and on the sources typed here; on no tree of
    theirs does the interface say otherwise.  OPNsense describes the
    interface by its zone.  The sources are read as well because no
    FortiOS capture has a VLAN interface on a FortiLink."""
    same: set[str] = set()
    apart: set[str] = set()
    texts = [(codec, path.read_text(encoding="utf-8")) for codec, _rel, path in _captures()]
    texts += [
        ("mikrotik_routeros", _ROS_LABELLED), ("fortigate_cli", _FORTILINK_LABELLED),
        ("opnsense", _OPN_LABELLED),
    ]
    for codec, text in texts:
        tree = get_codec(codec).parse(text)
        described = {iface.name: iface.description for iface in tree.interfaces}
        for vlan in tree.vlans:
            if vlan.description.strip() and vlan.name in described:
                (same if described[vlan.name] == vlan.description else apart).add(tree.source_vendor)
    assert same == set(vlan_interfaces._ONE_LABEL)
    assert not same & apart, same & apart


def _on_a_dropped_bridge(comment: str = "") -> str:
    """RouterOS ``vlan10``, carrying VLAN 20, on a bridge named as
    RouterOS names its default one: AOS-S has no name for it, and the
    port translator takes it off the VLAN interface."""
    return (
        "/interface bridge\nadd name=bridge\n"
        "/interface bridge port\nadd bridge=bridge interface=ether2\n"
        f"/interface vlan\nadd {comment}interface=bridge name=vlan10 vlan-id=20\n"
        "/ip address\nadd address=10.20.0.1/24 interface=vlan10\n"
        "/system identity\nset name=r1\n"
    )


class TestOnAParentTheJobDrops:
    """A VLAN interface whose parent the port translator dropped is found
    by its record or its label all the same, and never read by its name:
    read so, ``vlan10`` was VLAN 10's interface of a grammar, and its
    address went into VLAN 10."""

    @pytest.mark.parametrize("comment", ["", 'comment="Users" '], ids=["named", "labelled"])
    def test_it_is_the_vlan_it_carries(self, comment: str) -> None:
        job = _job("mikrotik_routeros", _on_a_dropped_bridge(comment), {})
        assert job.unresolved_ports == ["bridge"]
        out = job.rendered
        assert _on(out, "10.20.0.1") == ["Vlan20"]
        assert "ip address 10.20.0.1/24" in _stanzas(out)["vlan 20"]
        assert "vlan 10" not in _stanzas(out)
        assert not [h for h in _stanzas(out) if h.startswith("interface ")]

    def test_one_that_nothing_links_is_left_out(self) -> None:
        job = _job("mikrotik_routeros", _on_a_dropped_bridge(), {"vlan10": "lan"})
        why = f"rides on no port of the output, and {_UNKNOWN}"
        assert _refused_problems(job, "lan", why, "10.20.0.1") == []

    def test_the_check_sees_it_read_by_its_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(vlan_interfaces, "NAMES_A_VLAN_AFTER_ITS_INTERFACE", frozenset())
        out = _job("mikrotik_routeros", _on_a_dropped_bridge(), {}).rendered
        assert _on(out, "10.20.0.1") != ["Vlan20"]
