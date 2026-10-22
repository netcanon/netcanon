"""A warning is not a status: port names, with no devices declared.

The terminal status of a job was decided by the validation report and
by "the input parsed to nothing".  What the port translator did reached
the job as warning lines only.  So a job said ``completed`` in which
two source names ended on one name of the output -- the config of two
interfaces written as one --, in which a name was dropped because the
target has none for it, or in which a name the translator could not
read was written into another vendor's config as the source config has
it.  A check that refuses the first two was made only where devices
are declared (``run_plan_with_models``), and only for hardware ports.

``run_plan_with_checked_names`` is what every plan endpoint runs when
none are: ``run_plan_with_overrides``, and then a look at the finished
run.  Three things are read here.

* **The condition**, branch by branch, on small configs.
* **Every committed capture onto every public codec**, with an empty
  port map: how many jobs move from ``completed`` to ``partial`` is
  pinned by source codec and by reason, no job moves any other way,
  none moves between two configs of one codec, and nothing but the
  status, its sentence and the three fields differs from what
  ``run_plan_with_overrides`` returns.
* **The rendered output** of every job that is still ``completed``,
  read back with the target's own parser (``read_back``): no interface
  of the output carries the addresses of two source interfaces, no
  interface of the source that has an address is missing from it, and
  the translator's own warnings name no interface it left under a
  foreign name.  That oracle asks nothing of the function it
  guards, nor of the list of names that function groups: it works
  from addresses, which the translator does not touch, from the
  source config parsed again, from the warning lines, and -- for
  which names left as they were are the target's own -- from the
  text and a table typed here by hand.  It sees
  what an address shows and no more -- two access ports on one name,
  with no address on either, are outside it, and are what the
  condition's own tests are for.
"""

from __future__ import annotations

import inspect
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from netcanon.migration.canonical.port_names import names_a_target
from netcanon.migration.codecs.base import CodecBase, RenderError
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services import migration_pipeline
from netcanon.services.migration_pipeline import (
    run_plan_with_checked_names,
    run_plan_with_overrides,
)

pytestmark = pytest.mark.unit

COMPLETED = MigrationJobStatus.completed
PARTIAL = MigrationJobStatus.partial
FAILED = MigrationJobStatus.failed

#: How the sentence a job's ``error`` carries begins.
NOT_SETTLED = "Port names are not settled: "


def _checked(
    source_name: str, target_name: str, text: str,
    port_map: dict[str, str | None] | None = None, **more,
) -> MigrationJob:
    """The job ``POST /plan`` runs for a request that declares no
    devices: an absent port map is ``{}`` there."""
    return run_plan_with_checked_names(
        get_codec(source_name), get_codec(target_name), text,
        port_rename_map={} if port_map is None else port_map, **more,
    )


def _unchecked(
    source_name: str, target_name: str, text: str,
    port_map: dict[str, str | None] | None = None,
) -> MigrationJob:
    return run_plan_with_overrides(
        get_codec(source_name), get_codec(target_name), text,
        port_rename_map={} if port_map is None else port_map,
    )


def _rest(job: MigrationJob) -> dict:
    """Everything of a job but what the check may change, and what
    differs between any two runs."""
    data = job.model_dump(mode="json")
    for key in (
        "id", "created_at", "completed_at", "status", "error",
        "fused_ports", "unresolved_ports", "untranslated_ports",
    ):
        data.pop(key)
    return data


# ---------------------------------------------------------------------------
# The read-back: the rendered output, parsed again with the target's parser
# ---------------------------------------------------------------------------

#: How many times the read-back has been asked, so that a test which
#: is meant to ask it can show that it did.
_READ_BACKS = {"asked": 0}


def _addresses(iface) -> list[str]:
    return [a.ip for a in iface.ipv4_addresses] + [a.ip for a in iface.ipv6_addresses]


def _configured(tree) -> set[str]:
    """The names *tree* configures something under: an interface, a
    LAG, a member of a LAG, a port in a VLAN's lists.  Written out
    here so that the oracle does not take the translator's word for
    which names those are.  A name the config only refers to (a
    route's interface, a DHCP pool's, a track entry, a VXLAN source)
    is not one."""
    names: set[str] = set()
    for iface in tree.interfaces:
        names.add(iface.name)
        if iface.lag_member_of:
            names.add(iface.lag_member_of)
    for vlan in tree.vlans:
        names.update(vlan.tagged_ports)
        names.update(vlan.untagged_ports)
    for lag in tree.lags:
        names.add(lag.name)
        names.update(lag.members)
    return names


def _in_text(ip: str, text: str) -> bool:
    """*ip* stands in *text* as an address of its own, not as the
    front of a longer one."""
    return re.search(r"(?<![\w.:])" + re.escape(ip) + r"(?![\w:]|\.\d)", text) is not None


#: Codec pairs of ONE platform, typed here by hand: IOS-XE as CLI
#: text and over NETCONF.  A name of one is a name of the other.
_ONE_PLATFORM = ({"cisco_iosxe", "cisco_iosxe_cli"},)

#: Platforms on which an operator chooses interface names as free
#: text, typed here by hand.
_FREE_TEXT = {"fortigate_cli", "mikrotik_routeros"}

#: The line that opens a VLAN's interface in the output of each
#: target that calls it ``Vlan<id>``, typed here by hand from what
#: the platforms print, so that the oracle does not put to a codec
#: the question the pipeline puts to it.
_OPENS_A_VLAN_INTERFACE = {
    "arista_eos": "interface {name}",
    "cisco_iosxe_cli": "interface {name}",
    "cisco_nxos": "interface {name}",
    "cisco_iosxe": "<name>{name}</name>",
}


def _left_by_the_translator(tree, job: MigrationJob) -> list[str]:
    """The names *tree* configures something under that the
    translator's own warning says it could not classify and left as
    they were, sorted."""
    return [
        name for name in sorted(_configured(tree))
        if any(
            line.endswith(f"could not classify port name {name!r}; left verbatim")
            for line in job.warnings
        )
    ]


def _right_as_it_stands(
    name: str, tree, source: CodecBase, target: CodecBase, rendered: str,
) -> bool:
    """The oracle's own answer to whether *name*, left as the source
    config has it, is no foreign name in *rendered*.

    Between two codecs of one platform it is the platform's own.
    Otherwise one case is known here, and it is read from the text:
    a VLAN's interface -- the source parser typed it so, the name is
    ``Vlan`` and the id of a VLAN the source config has, and the
    source is no platform where a name is free text -- on a target
    that opens that interface with that very name."""
    if {source.name, target.name} in _ONE_PLATFORM:
        return True
    opens = _OPENS_A_VLAN_INTERFACE.get(target.name)
    if opens is None or source.name in _FREE_TEXT:
        return False
    types = {iface.interface_type for iface in tree.interfaces if iface.name == name}
    if types != {"ianaift:l3ipvlan"} or name not in {f"Vlan{vlan.id}" for vlan in tree.vlans}:
        return False
    return opens.format(name=name) in {row.strip() for row in rendered.splitlines()}


def read_back(
    source: CodecBase, target: CodecBase, text: str, job: MigrationJob,
    port_map: dict[str, str | None],
) -> list[str]:
    """What the rendered output of *job* shows that a job called
    ``completed`` must not, as complaints; ``[]`` when it shows none.

    * An interface of the output that carries addresses of two
      source interfaces: two interfaces were written as one.
    * An interface of the source that has an address and is not in
      the output -- a hardware port, a loopback, a tunnel, a hardware
      switch: any -- unless the job lists it in ``port_drops`` and an
      entry of *port_map* decided it (its own, or one that dropped
      the port it is a unit of).
    * A name the source config configures something under that the
      translator's own warning says it could not classify and left
      as it was -- unless the name is the target's own as it stands
      (:func:`_right_as_it_stands`).  (The warning is there only
      while no entry decided the name: one that has an entry is
      never classified.)

    An address counts only where one source interface holds it.  An
    interface is in the output when the target's parser gives back
    one with its address -- or, failing that, when the address
    stands in the text: a target's own form need not read back as an
    interface (the AOS-S ``oobm`` block, a VLAN's address in its
    VLAN stanza), and a check that allowed for that in no branch
    would report an interface that is there.
    """
    _READ_BACKS["asked"] += 1
    before = source.parse(text)
    after = target.parse(job.rendered)
    holders: dict[str, list[str]] = {}
    for iface in before.interfaces:
        for ip in _addresses(iface):
            holders.setdefault(ip, []).append(iface.name)
    # An address says which interface it came from only where one
    # source interface holds it: the same address in two routing
    # instances is nobody's.
    owner = {ip: names[0] for ip, names in holders.items() if len(names) == 1}

    complaints: list[str] = []
    for iface in after.interfaces:
        sources = sorted({owner[ip] for ip in _addresses(iface) if ip in owner})
        if len(sources) > 1:
            complaints.append(
                f"{iface.name!r} in the output carries the addresses of {sources}"
            )

    read = {ip for iface in after.interfaces for ip in _addresses(iface)}
    dropped_by_entry = {name for name, to in port_map.items() if to is None}
    for iface in before.interfaces:
        mine = [ip for ip in _addresses(iface) if owner.get(ip) == iface.name]
        if not mine:
            continue
        if read.intersection(mine) or any(_in_text(ip, job.rendered) for ip in mine):
            continue
        port = iface.name.rpartition(".")[0]
        decided = iface.name in port_map or port in dropped_by_entry
        if not (iface.name in job.port_drops and decided):
            complaints.append(
                f"{iface.name!r} has an address and is not in the output, "
                f"and no entry of the port map decided it"
            )

    for name in _left_by_the_translator(before, job):
        if not _right_as_it_stands(name, before, source, target, job.rendered):
            complaints.append(
                f"{name!r} was left as the source config has it, and no "
                f"entry of the port map decided it"
            )
    return complaints


# ---------------------------------------------------------------------------
# Small configs, one per branch
# ---------------------------------------------------------------------------

#: A stacked AOS-S switch: ``1/1`` is an access port and ``1/A1`` a
#: port of the uplink module.  No other vendor's names have a letter
#: slot, so both are written ``Ethernet1`` on EOS.  (No address on
#: the VLAN: its interface is a name of its own, and has a test of
#: its own below.)
_AOSS_TWO_PORTS = """; JL322A Configuration Editor; Created on release #WC.16.11.0001
hostname "sw"
module 1 type jl322a
vlan 1
   name "DEFAULT_VLAN"
   untagged 1/1-1/2,1/A1
   exit
"""

#: A Junos router: a port, the loopback, and a line that refers to
#: the loopback as Junos does, with its unit.
_JUNOS = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.1/24",
    "set interfaces lo0 unit 0 family inet address 192.0.2.1/32",
    "set switch-options vtep-source-interface lo0.0",
    "set vlans VLAN100 vlan-id 100",
    "set vlans VLAN100 vxlan vni 10100",
    "",
])
#: ... and an ``irb`` and a ``vlan`` unit of one VLAN beside it (the
#: two Junos grammars' names for a VLAN interface): every target that
#: has a VLAN interface names both after the VLAN.  (A unit of ``lo0``
#: was this example, and is a loopback of its own now: ``lo0.2`` is
#: ``Loopback2``.)
_JUNOS_TWO_VLAN_INTERFACES = _JUNOS + "\n".join([
    "set interfaces irb unit 100 family inet address 192.0.2.65/26",
    "set interfaces vlan unit 100 family inet address 192.0.2.2/32",
    "",
])
#: ... and a port of a second FPC, which a target that numbers its
#: ports in one run names as the first one's.
_JUNOS_TWO_FPCS = _JUNOS + "set interfaces ge-1/0/1 unit 0 family inet address 10.2.0.1/24\n"

#: Two aggregates numbered from 0, which IOS numbers from 1.
_JUNOS_TWO_LAGS = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/1 ether-options 802.3ad ae0",
    "set interfaces ge-0/0/2 ether-options 802.3ad ae1",
    "set interfaces ae0 unit 0 family inet address 10.0.0.1/24",
    "set interfaces ae1 unit 0 family inet address 10.0.1.1/24",
    "",
])

#: A port, the loopback, two VLAN interfaces of one VLAN, and the
#: management port, which IOS-XE has no name for.
_JUNOS_BOTH = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.1/24",
    "set interfaces lo0 unit 0 family inet address 192.0.2.1/32",
    "set interfaces irb unit 100 family inet address 192.0.2.65/26",
    "set interfaces vlan unit 100 family inet address 192.0.2.2/32",
    "set interfaces fxp0 unit 0 family inet address 198.51.100.9/24",
    "",
])

#: An NX-OS switch with its management port.
_NXOS_MGMT = "\n".join([
    "!Command: show running-config", "version 9.3(11) Bios:version", "hostname r1", "",
    "interface Ethernet1/1", "  no switchport", "  ip address 10.1.0.1/24", "",
    "interface mgmt0", "  vrf member management", "  ip address 192.0.2.9/24", "",
])

#: ... and one whose ports AOS-S has no name for, one with a unit.
_NXOS_UNIT = "\n".join([
    "!Command: show running-config", "version 9.3(11) Bios:version", "hostname r1", "",
    "interface Ethernet1/1", "  description PARENT", "  no switchport", "",
    "interface Ethernet1/1.54", "  encapsulation dot1q 300", "  ip address 10.54.0.1/24", "",
    "interface Ethernet1/2", "  no switchport", "  ip address 10.2.0.1/24", "",
])

#: An access port and the VLAN interface of its VLAN.
_IOS_SVI = "\n".join([
    "!", "version 17.9", "hostname r1", "!",
    "vlan 10", " name users", "!",
    "interface GigabitEthernet1/0/1", " switchport mode access",
    " switchport access vlan 10", "!",
    "interface Vlan10", " ip address 10.10.0.1 255.255.255.0", "!", "end", "",
])

#: Two routed ports, and a route that names the first in lower case.
_IOS_TWO_SPELLINGS = "\n".join([
    "!", "version 17.9", "hostname r1", "!",
    "interface GigabitEthernet1/0/1", " ip address 10.1.0.1 255.255.255.0", "!",
    "interface GigabitEthernet1/0/2", " ip address 10.2.0.1 255.255.255.0", "!",
    "ip route 10.9.0.0 255.255.0.0 gigabitethernet1/0/1", "!",
    "end", "",
])

#: A VyOS port with a ``vif 0``: unit 0 with a stanza of its own.
_VYOS_VIF_0 = "\n".join([
    "interfaces {", "    ethernet eth1 {", "        address 10.1.0.1/24",
    "        vif 0 {", "            address 10.54.0.1/24", "        }", "    }",
    "    ethernet eth2 {", "        address 10.2.0.1/24", "    }", "}",
    "system {", "    host-name r1", "}",
    '// vyos-config-version: "system@27:interfaces@29"', "",
])


#: Two routed ports of an EOS switch.
_EOS_TWO_PORTS = "\n".join([
    "! device: sw (DCS-7050SX-64, EOS-4.26.0F)", "hostname sw", "!",
    "interface Ethernet1", "   no switchport", "   ip address 10.1.0.1/24", "!",
    "interface Ethernet2", "   no switchport", "   ip address 10.2.0.1/24", "!",
    "end", "",
])

#: A Junos port, and a line that refers to unit 0 of ANOTHER port --
#: one the config has no interface for.
_JUNOS_STRAY_UNIT = "\n".join([
    "set system host-name r1",
    "set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.1/24",
    "set system services dhcp-local-server group g1 interface ge-0/0/0.0",
    "set access address-assignment pool g1 family inet network 10.0.0.0/24",
    "",
])

#: RouterOS, where an operator names interfaces and letter case tells
#: two of them apart: ``WAN`` and ``wan`` are two ports.
_ROUTEROS_TWO_CASES = "\n".join([
    "# by RouterOS 7.13",
    "/interface ethernet",
    "set [ find default-name=ether1 ] name=WAN",
    "set [ find default-name=ether2 ] name=wan",
    "/ip address",
    "add address=10.1.0.1/24 interface=WAN",
    "add address=10.2.0.1/24 interface=wan",
    "",
])

#: FortiOS, where letter case is part of a name too: a port, and the
#: management port, which IOS-XE has no name for.
_FORTIOS_MGMT = "\n".join([
    "#config-version=FGT60F-7.2.5-FW-build1517-230606:opmode=0:vdom=0",
    "config system interface",
    '    edit "port1"', "        set ip 10.1.0.1 255.255.255.0", "    next",
    '    edit "mgmt"', "        set ip 192.0.2.9 255.255.255.0", "    next",
    "end", "",
])

#: A FortiGate whose LAN address is on its hardware switch: a logical
#: name no other vendor has a form for.
_FORTIOS_HARD_SWITCH = "\n".join([
    "#config-version=FGT60F-7.2.5-FW-build1517-230606:opmode=0:vdom=0",
    "config system interface",
    '    edit "wan1"', "        set ip 198.51.100.2 255.255.255.252", "    next",
    '    edit "internal"', "        set ip 192.168.1.99 255.255.255.0",
    "        set type hard-switch", "    next",
    "end", "",
])

#: A Catalyst port, and the port of a virtual router: ``GigabitEthernet1``
#: has no slot, and the IOS-XE classifier does not read it.  A route
#: to ``Null0`` beside them: a name in a place a port name goes that
#: is no interface of the config.
_IOS_UNREAD = "\n".join([
    "!", "version 17.9", "hostname r1", "!",
    "interface GigabitEthernet1/0/1", " ip address 10.1.0.1 255.255.255.0", "!",
    "interface GigabitEthernet1", " ip address 10.2.0.1 255.255.255.0", "!",
    "ip route 10.50.0.0 255.255.0.0 Null0", "!",
    "end", "",
])

#: An AOS-S switch whose VLAN has an address.  Its parser carries the
#: address on an interface it names ``Vlan20``, and its classifier
#: does not read that name.
_AOSS_VLAN_ADDRESS = """; JL322A Configuration Editor; Created on release #WC.16.11.0001
hostname "sw"
module 1 type jl322a
vlan 1
   name "DEFAULT_VLAN"
   untagged 1/1-1/2
   exit
vlan 20
   name "users"
   tagged 1/2
   ip address 10.0.20.1 255.255.255.0
   exit
"""


# ---------------------------------------------------------------------------
# 1. Two source names on one name of the output
# ---------------------------------------------------------------------------


class TestTwoNamesOnOneName:
    def test_two_hardware_ports(self) -> None:
        job = _checked("aruba_aoss", "arista_eos", _AOSS_TWO_PORTS)
        assert job.status == PARTIAL
        assert job.fused_ports == {"Ethernet1": ["1/1", "1/A1"]}
        assert job.unresolved_ports == []
        # The job the translator's warning used to be all there was of.
        assert _unchecked("aruba_aoss", "arista_eos", _AOSS_TWO_PORTS).status == COMPLETED

    def test_a_port_and_a_logical_name(self) -> None:
        """Whoever decided it: here an entry puts the VLAN interface
        on the name the translator gives the access port."""
        job = _checked(
            "cisco_iosxe_cli", "arista_eos", _IOS_SVI, {"Vlan10": "Ethernet1"},
        )
        assert job.status == PARTIAL
        assert job.fused_ports == {"Ethernet1": ["GigabitEthernet1/0/1", "Vlan10"]}

    @pytest.mark.parametrize(
        ("text", "target_name", "expected"),
        [
            (
                _JUNOS_TWO_VLAN_INTERFACES, "arista_eos",
                {"Vlan100": ["irb.100", "vlan.100"]},
            ),
            (_JUNOS_TWO_LAGS, "cisco_iosxe_cli", {"Port-channel1": ["ae0", "ae1"]}),
        ],
        ids=["two VLAN interfaces", "two aggregates"],
    )
    def test_two_logical_names(self, text: str, target_name: str, expected: dict) -> None:
        """With no device declared there is no pairing whose ports
        alone need protecting: two VLAN interfaces on one are two
        interfaces written as one, and no hardware port is in it."""
        job = _checked("juniper_junos", target_name, text)
        assert job.fused_ports == expected
        assert not set(job.source_ports).intersection(*expected.values())
        assert job.status == PARTIAL
        assert _unchecked("juniper_junos", target_name, text).status == COMPLETED

    def test_it_is_cleared_by_a_name_of_its_own(self) -> None:
        job = _checked("aruba_aoss", "arista_eos", _AOSS_TWO_PORTS, {"1/A1": "Ethernet49"})
        assert (job.status, job.fused_ports, job.error) == (COMPLETED, {}, None)

    def test_it_is_cleared_by_dropping_one(self) -> None:
        job = _checked("aruba_aoss", "arista_eos", _AOSS_TWO_PORTS, {"1/A1": None})
        assert (job.status, job.fused_ports, job.unresolved_ports) == (COMPLETED, {}, [])
        assert job.port_drops == ["1/A1"]

    def test_a_dropped_name_frees_its_name(self) -> None:
        """A name that was dropped reached no name, so it shares
        none: the port sent to where it stood has that name to
        itself."""
        entries: dict[str, str | None] = {"Ethernet1": None, "Ethernet2": "Ethernet1"}
        job = _checked("arista_eos", "arista_eos", _EOS_TWO_PORTS, entries)
        assert job.port_drops == ["Ethernet1"]
        assert job.port_renames == {"Ethernet2": "Ethernet1"}
        assert (job.status, job.fused_ports, job.error) == (COMPLETED, {}, None)
        assert read_back(
            get_codec("arista_eos"), get_codec("arista_eos"), _EOS_TWO_PORTS, job, entries,
        ) == []

    def test_two_entries_on_one_name_are_said(self) -> None:
        """An operator who sends two ports to one name on purpose has
        still written two interfaces as one, and the job says so --
        as it does where devices are declared
        (``port_mapping_plan.fused``, whoever decided it)."""
        job = _checked(
            "aruba_aoss", "arista_eos", _AOSS_TWO_PORTS,
            {"1/A1": "Ethernet7", "1/2": "Ethernet7"},
        )
        assert job.status == PARTIAL
        assert job.fused_ports == {"Ethernet7": ["1/2", "1/A1"]}

    def test_names_compare_as_the_target_does(self) -> None:
        """``Trk1`` and ``trk1`` are one port on AOS-S and on EOS;
        ``DMZ`` and ``dmz`` are two interfaces on FortiOS, where an
        operator chooses the names."""
        entries = {"GigabitEthernet1/0/1": "Trk1", "GigabitEthernet1/0/2": "trk1"}
        job = _checked("cisco_iosxe_cli", "aruba_aoss", _IOS_TWO_SPELLINGS, entries)
        assert job.fused_ports == {
            "Trk1": ["GigabitEthernet1/0/1", "GigabitEthernet1/0/2"],
        }
        entries = {"GigabitEthernet1/0/1": "DMZ", "GigabitEthernet1/0/2": "dmz"}
        job = _checked(
            "cisco_iosxe_cli", "fortigate_cli", _IOS_TWO_SPELLINGS, entries, force=True,
        )
        assert job.fused_ports == {}

    def test_two_spellings_of_one_source_are_one(self) -> None:
        """IOS names have no letter case: the route's
        ``gigabitethernet1/0/1`` is the port, not a second one."""
        job = _checked("cisco_iosxe_cli", "arista_eos", _IOS_TWO_SPELLINGS)
        assert job.port_renames["gigabitethernet1/0/1"] == "Ethernet1"
        assert job.port_renames["GigabitEthernet1/0/1"] == "Ethernet1"
        assert (job.status, job.fused_ports) == (COMPLETED, {})


# ---------------------------------------------------------------------------
# 2. What is not a second interface
# ---------------------------------------------------------------------------


class TestWhatIsNotASecondInterface:
    @pytest.mark.parametrize("target_name", ["arista_eos", "cisco_nxos", "aruba_aoscx"])
    def test_unit_0_beside_its_interface(self, target_name: str) -> None:
        """Junos refers to ``lo0`` as ``lo0.0``.  Both names end on
        the target's loopback, and they are one interface."""
        job = _checked("juniper_junos", target_name, _JUNOS)
        assert job.port_renames["lo0.0"] == job.port_renames["lo0"]
        assert (job.status, job.fused_ports, job.error) == (COMPLETED, {}, None)

    def test_another_unit_is_a_second_interface(self) -> None:
        """``lo0.2`` is the loopback of a routing instance.  Put on
        ``Loopback0`` beside ``lo0`` by an entry, it is two interfaces
        in one -- and the reference ``lo0.0`` is still not a third."""
        text = _JUNOS + "set interfaces lo0 unit 2 family inet address 192.0.2.2/32\n"
        job = _checked("juniper_junos", "arista_eos", text, {"lo0.2": "Loopback0"})
        assert job.port_renames["lo0.0"] == "Loopback0"
        assert job.fused_ports == {"Loopback0": ["lo0", "lo0.2"]}
        assert job.status == PARTIAL

    def test_unit_0_with_a_stanza_of_its_own(self) -> None:
        """A VyOS ``vif 0`` is an interface with an address of its
        own.  Its name is unit 0 of its port all the same, and here
        the tree that is rendered holds two interfaces under the one
        name: they are counted."""
        job = _checked("vyos", "arista_eos", _VYOS_VIF_0)
        assert job.fused_ports == {"Ethernet1": ["eth1", "eth1.0"]}
        assert job.status == PARTIAL
        # And the output shows it: two stanzas of the one name.  The
        # EOS reader does not read the second back -- VLAN 0 is no
        # 802.1Q VLAN id, so a stanza tagged 0 is left out, and says
        # so -- so the text is read, not the parse.
        assert job.rendered.count("\ninterface Ethernet1\n") == 2
        assert get_codec("arista_eos").parse(job.rendered).dropped_tier3_sections == [
            "interface Ethernet1: encapsulation dot1q vlan 0 -- not one "
            "802.1Q tag and at most one inner tag, so the sub-interface "
            "is not translated"
        ]

    def test_unit_0_of_a_port_that_is_not_there(self) -> None:
        """Unit 0 is set aside beside ITS interface.  Here a line
        refers to ``ge-0/0/0.0`` and the config has no ``ge-0/0/0``:
        FortiOS numbers its ports from 1, the reference lands on the
        name ``ge-0/0/1`` is given, and that is two names on one --
        the unit 0 of some other port is not ``ge-0/0/1`` written
        another way."""
        job = _checked("juniper_junos", "fortigate_cli", _JUNOS_STRAY_UNIT, force=True)
        assert job.port_renames == {"ge-0/0/1": "port1", "ge-0/0/0.0": "port1"}
        assert job.fused_ports == {"port1": ["ge-0/0/1", "ge-0/0/0.0"]}
        assert job.status == PARTIAL

    def test_what_is_counted_is_what_is_rendered(self) -> None:
        """A caller's transforms run before the count.  One that takes
        the ``vif 0`` out leaves one interface under the name: its
        unit 0 is then a second way of writing it and no more, where
        without the transform it is a second interface."""
        def without_the_vif(tree):
            tree.interfaces = [
                iface for iface in tree.interfaces
                if "10.54.0.1" not in [a.ip for a in iface.ipv4_addresses]
            ]
            return tree

        job = _checked("vyos", "arista_eos", _VYOS_VIF_0, transforms=[without_the_vif])
        assert "10.54.0.1" not in job.rendered and "10.1.0.1" in job.rendered
        assert job.port_renames["eth1.0"] == job.port_renames["eth1"] == "Ethernet1"
        assert job.fused_ports == {}
        assert _checked("vyos", "arista_eos", _VYOS_VIF_0).fused_ports == {
            "Ethernet1": ["eth1", "eth1.0"],
        }

    def test_no_more_are_set_aside_than_missing(self) -> None:
        """Four names on one name, three interfaces under it in the
        tree that is rendered: one of the four is a second way of
        writing an interface, and exactly one unit 0 is set aside.
        The other is listed -- it is an interface the output has."""
        job = MigrationJob(
            source_codec="juniper_junos", target_codec="arista_eos",
            source_ports=["a", "b"], source_other_names=["a.0", "b.0"],
            port_renames={"a": "x", "a.0": "x", "b": "x", "b.0": "x"},
        )
        listed = migration_pipeline._shared_final_names(job, Counter({"x": 3}), True, True)
        assert listed == {"x": ["a", "b", "b.0"]}
        # Two interfaces under it: both units are a second spelling.
        listed = migration_pipeline._shared_final_names(job, Counter({"x": 2}), True, True)
        assert listed == {"x": ["a", "b"]}

    def test_a_vlan_interface_the_target_absorbs(self) -> None:
        """AOS-S writes a VLAN's address in the VLAN's own stanza and
        has no interface name for it.  The translator leaves the name
        as it is and drops nothing; nothing shares the name, and the
        address is in the output.  Left by design and not for want of
        a name: it is not among the names left as they were either."""
        job = _checked("cisco_iosxe_cli", "aruba_aoss", _IOS_SVI)
        assert "Vlan10" not in job.port_renames and "Vlan10" not in job.port_drops
        assert "   ip address 10.10.0.1/24\n" in job.rendered
        assert (job.status, job.fused_ports, job.unresolved_ports) == (COMPLETED, {}, [])
        assert job.untranslated_ports == []


# ---------------------------------------------------------------------------
# 3. A name the translator dropped
# ---------------------------------------------------------------------------


class TestADroppedPort:
    def test_one_nobody_decided(self) -> None:
        job = _checked("cisco_nxos", "cisco_iosxe_cli", _NXOS_MGMT)
        assert job.port_drops == ["mgmt0"]
        assert job.unresolved_ports == ["mgmt0"] and job.fused_ports == {}
        assert job.status == PARTIAL
        assert "192.0.2.9" not in job.rendered
        assert _unchecked("cisco_nxos", "cisco_iosxe_cli", _NXOS_MGMT).status == COMPLETED

    @pytest.mark.parametrize(
        "entry", [None, "GigabitEthernet0/0"], ids=["dropped", "given a name"],
    )
    def test_an_entry_decides_it(self, entry: str | None) -> None:
        """``None`` is the operator saying the port is to go; a name
        puts it in the output."""
        job = _checked("cisco_nxos", "cisco_iosxe_cli", _NXOS_MGMT, {"mgmt0": entry})
        assert (job.status, job.unresolved_ports, job.error) == (COMPLETED, [], None)
        assert ("192.0.2.9" in job.rendered) is (entry is not None)

    def test_an_entry_for_another_port_does_not(self) -> None:
        job = _checked(
            "cisco_nxos", "cisco_iosxe_cli", _NXOS_MGMT, {"Ethernet1/1": "GigabitEthernet9"},
        )
        assert (job.status, job.unresolved_ports) == (PARTIAL, ["mgmt0"])

    def test_a_key_in_another_letter_case(self) -> None:
        """NX-OS names have no letter case, and the translator takes
        ``MGMT0`` for the port the config calls ``mgmt0``.  So does
        the check: the port was decided."""
        job = _checked("cisco_nxos", "cisco_iosxe_cli", _NXOS_MGMT, {"MGMT0": None})
        assert job.port_drops == ["mgmt0"]
        assert (job.status, job.unresolved_ports) == (COMPLETED, [])

    def test_a_unit_is_listed_with_its_port(self) -> None:
        """AOS-S has no name for ``Ethernet1/1``.  The port goes, its
        unit goes with it, and each is an interface the output does
        not have."""
        job = _checked("cisco_nxos", "aruba_aoss", _NXOS_UNIT)
        assert job.unresolved_ports == ["Ethernet1/1", "Ethernet1/1.54", "Ethernet1/2"]
        assert job.unresolved_ports == job.port_drops
        assert job.status == PARTIAL

    @pytest.mark.parametrize("key", ["Ethernet1/1", "ethernet1/1"])
    def test_dropping_a_port_decides_its_units(self, key: str) -> None:
        """A unit goes where its port goes.  The entry that drops the
        port is the decision for the unit too: asking for a second
        one would contradict the rule that took it."""
        job = _checked(
            "cisco_nxos", "aruba_aoss", _NXOS_UNIT, {key: None, "Ethernet1/2": None},
        )
        assert "Ethernet1/1.54" in job.port_drops
        assert (job.status, job.unresolved_ports, job.error) == (COMPLETED, [], None)

    def test_naming_a_port_leaves_its_unit(self) -> None:
        """Only an entry that DROPS a port decides its units.  Junos
        ``fxp0`` given a name is in the output; its unit 5 is a unit
        of a management port, which no rule sends after its port,
        and IOS-XE has no name for it: dropped, and nobody said so."""
        text = _JUNOS_BOTH + "set interfaces fxp0 unit 5 family inet address 198.51.100.9/24\n"
        named = _checked(
            "juniper_junos", "cisco_iosxe_cli", text,
            {"fxp0": "GigabitEthernet0/0", "vlan.100": "Loopback2"},
        )
        assert named.port_drops == ["fxp0.5"]
        assert (named.status, named.unresolved_ports) == (PARTIAL, ["fxp0.5"])
        dropped = _checked(
            "juniper_junos", "cisco_iosxe_cli", text, {"fxp0": None, "vlan.100": "Loopback2"},
        )
        assert dropped.port_drops == ["fxp0", "fxp0.5"]
        assert (dropped.status, dropped.unresolved_ports) == (COMPLETED, [])

    def test_a_logical_name_is_listed_too(self) -> None:
        """A tunnel AOS-S has no form for is dropped, and what was
        configured on it is not in the output.  That it is no
        hardware port changes nothing of that: the job says so, and
        an entry decides it -- as for a port."""
        text = _IOS_SVI.replace(
            "end\n", "interface Tunnel7\n ip address 10.77.0.1 255.255.255.0\n!\nend\n",
        )
        source, target = get_codec("cisco_iosxe_cli"), get_codec("aruba_aoss")
        job = _checked("cisco_iosxe_cli", "aruba_aoss", text)
        assert job.port_drops == ["Tunnel7"] and "Tunnel7" not in job.source_ports
        assert (job.status, job.unresolved_ports) == (PARTIAL, ["Tunnel7"])
        assert "10.77.0.1" not in job.rendered
        # The read-back asks after every interface with an address.
        assert read_back(source, target, text, _unchecked("cisco_iosxe_cli", "aruba_aoss", text), {}) == [
            "'Tunnel7' has an address and is not in the output, and no entry "
            "of the port map decided it"
        ]
        entries: dict[str, str | None] = {"Tunnel7": None}
        job = _checked("cisco_iosxe_cli", "aruba_aoss", text, entries)
        assert (job.status, job.unresolved_ports, job.error) == (COMPLETED, [], None)
        assert read_back(source, target, text, job, entries) == []

    def test_a_hardware_switch_with_an_address(self) -> None:
        """A FortiGate ``internal`` hardware switch is no port of any
        other vendor: it is dropped, and the LAN address with it."""
        job = _checked("fortigate_cli", "cisco_iosxe_cli", _FORTIOS_HARD_SWITCH, force=True)
        assert job.source_ports == ["wan1"] and job.source_other_names == ["internal"]
        assert job.port_drops == ["internal"] and "192.168.1.99" not in job.rendered
        assert (job.status, job.unresolved_ports) == (PARTIAL, ["internal"])
        assert job.error == (
            "Port names are not settled: 1 other name(s) the target has no "
            "form for (such as a loopback, a tunnel or a hardware switch) "
            "were dropped from the output. An entry in port_rename_map "
            "settles each: a target name for a dropped name, or null to "
            "say it is to go."
        )
        named = _checked(
            "fortigate_cli", "cisco_iosxe_cli", _FORTIOS_HARD_SWITCH,
            {"internal": "Vlan1"}, force=True,
        )
        assert (named.status, named.unresolved_ports) == (COMPLETED, [])
        assert "192.168.1.99" in named.rendered

    def test_a_blank_target_decides_nothing(self) -> None:
        """``""`` is not a name and not a way to drop.  The HTTP API
        refuses it; a caller that reaches the pipeline another way
        has the entry set aside and said, the port is dropped as it
        was going to be, and nobody decided that."""
        for blank in ("", "   ", "\u200b", "\x00", "\ufeff\u2060"):
            job = _checked("cisco_nxos", "cisco_iosxe_cli", _NXOS_MGMT, {"mgmt0": blank})
            assert (job.status, job.unresolved_ports) == (PARTIAL, ["mgmt0"])
            assert "interface \n" not in job.rendered and "192.0.2.9" not in job.rendered
            assert job.rendered.count("\ninterface ") == 1, repr(blank)
            assert job.warnings.count(
                "port_rename: the entry for 'mgmt0' has no target name (it is "
                "empty or blank); entry skipped \u2014 to drop the port, map it to null"
            ) == 1
        assert names_a_target("") is False and names_a_target(" ") is False
        assert names_a_target("\u200b") is False and names_a_target("\x00") is False
        assert names_a_target(None) is True and names_a_target("x") is True


# ---------------------------------------------------------------------------
# 3b. A source whose names have letter case
# ---------------------------------------------------------------------------


class TestASourceWhoseNamesHaveLetterCase:
    """On RouterOS and FortiOS an operator chooses the names, and
    ``WAN`` and ``wan`` are two interfaces."""

    def test_two_cases_are_two_sources(self) -> None:
        """Sent to one name they are two on one -- not one source
        written two ways, which is what the pair would be from a
        platform whose names have no letter case."""
        job = _checked(
            "mikrotik_routeros", "arista_eos", _ROUTEROS_TWO_CASES,
            {"WAN": "Ethernet1", "wan": "Ethernet1"}, force=True,
        )
        assert job.fused_ports == {"Ethernet1": ["WAN", "wan"]}
        assert job.status == PARTIAL
        job = _checked(
            "mikrotik_routeros", "arista_eos", _ROUTEROS_TWO_CASES,
            {"WAN": "Ethernet1", "wan": "Ethernet2"}, force=True,
        )
        assert (job.status, job.fused_ports, job.error) == (COMPLETED, {}, None)

    def test_left_alone_one_where_case_is_none(self) -> None:
        """Neither name is one the RouterOS classifier reads, so both
        stay.  EOS reads the two as one interface; FortiOS, where
        case is part of a name, as two."""
        job = _checked("mikrotik_routeros", "arista_eos", _ROUTEROS_TWO_CASES, force=True)
        assert job.fused_ports == {"WAN": ["WAN", "wan"]}
        assert job.untranslated_ports == ["WAN", "wan"]
        job = _checked("mikrotik_routeros", "fortigate_cli", _ROUTEROS_TWO_CASES, force=True)
        assert job.fused_ports == {}
        assert job.untranslated_ports == ["WAN", "wan"]

    def test_another_case_is_another_name(self) -> None:
        """``MGMT`` is not the FortiOS port ``mgmt``.  The translator
        sets the entry aside and says so, and the check does not take
        it for a decision about ``mgmt`` either."""
        job = _checked(
            "fortigate_cli", "cisco_iosxe_cli", _FORTIOS_MGMT, {"MGMT": None}, force=True,
        )
        assert (
            "port_rename: source port 'MGMT' does not exist in the parsed "
            "config; entry ignored"
        ) in job.warnings
        assert job.port_drops == ["mgmt"]
        assert (job.status, job.unresolved_ports) == (PARTIAL, ["mgmt"])
        job = _checked(
            "fortigate_cli", "cisco_iosxe_cli", _FORTIOS_MGMT, {"mgmt": None}, force=True,
        )
        assert (job.status, job.unresolved_ports) == (COMPLETED, [])


# ---------------------------------------------------------------------------
# 3c. A name the translator could not read, left as the source has it
# ---------------------------------------------------------------------------


class TestANameLeftAsItWas:
    def test_one_the_translator_could_not_read(self) -> None:
        """An IOS name in an EOS config, in a job that said
        ``completed``."""
        source, target = get_codec("cisco_iosxe_cli"), get_codec("arista_eos")
        before = _unchecked("cisco_iosxe_cli", "arista_eos", _IOS_UNREAD)
        assert before.status == COMPLETED
        assert "interface GigabitEthernet1\n" in before.rendered
        assert read_back(source, target, _IOS_UNREAD, before, {}) == [
            "'GigabitEthernet1' was left as the source config has it, and no "
            "entry of the port map decided it"
        ]
        job = _checked("cisco_iosxe_cli", "arista_eos", _IOS_UNREAD)
        assert job.untranslated_ports == ["GigabitEthernet1"]
        assert (job.fused_ports, job.unresolved_ports, job.port_drops) == ({}, [], [])
        assert job.status == PARTIAL
        # One list a client reads; what the pipeline handed it on by
        # is no field of the job.
        assert not [key for key in job.model_dump() if key.startswith("_")]
        assert job.error == (
            "Port names are not settled: 1 name(s) could not be read as any "
            "kind of port: whatever the output has of them is under the name "
            "the source config has for them, which the target may not "
            "accept. An entry in "
            "port_rename_map settles each: for a name left as it was, the "
            "name it is to have on the target (its own, if that is right "
            "there) or null. Or declare both devices, to pair ports by "
            "position."
        )
        assert job.rendered == before.rendered

    @pytest.mark.parametrize(
        "entry", ["Ethernet7", "GigabitEthernet1", None],
        ids=["given a name", "kept as it is", "dropped"],
    )
    def test_an_entry_decides_it(self, entry: str | None) -> None:
        """Another name, ``None`` -- or the name ITSELF, which is how
        an operator says it is right on the target as it stands."""
        entries: dict[str, str | None] = {"GigabitEthernet1": entry}
        job = _checked("cisco_iosxe_cli", "arista_eos", _IOS_UNREAD, entries)
        assert (job.status, job.untranslated_ports, job.error) == (COMPLETED, [], None)
        assert ("10.2.0.1" in job.rendered) is (entry is not None)
        if entry is not None:
            assert f"interface {entry}\n" in job.rendered
        assert read_back(
            get_codec("cisco_iosxe_cli"), get_codec("arista_eos"), _IOS_UNREAD, job, entries,
        ) == []

    def test_a_key_in_another_letter_case(self) -> None:
        """IOS names have no letter case: the entry is for the port
        the config calls ``GigabitEthernet1``."""
        job = _checked(
            "cisco_iosxe_cli", "arista_eos", _IOS_UNREAD, {"gigabitethernet1": "Ethernet7"},
        )
        assert job.port_renames["GigabitEthernet1"] == "Ethernet7"
        assert (job.status, job.untranslated_ports) == (COMPLETED, [])

    def test_they_are_listed_in_the_order_met(self) -> None:
        """As the translator met them, which is the order the config
        has them in -- the order of the rows a client shows them
        beside -- and not sorted."""
        text = "\n".join([
            "!", "version 17.9", "hostname r1", "!",
            "interface GigabitEthernet3", " ip address 10.3.0.1 255.255.255.0", "!",
            "interface GigabitEthernet1", " ip address 10.1.0.1 255.255.255.0", "!",
            "interface GigabitEthernet2", " ip address 10.2.0.1 255.255.255.0", "!",
            "end", "",
        ])
        job = _checked("cisco_iosxe_cli", "arista_eos", text)
        assert job.untranslated_ports == [
            "GigabitEthernet3", "GigabitEthernet1", "GigabitEthernet2",
        ]
        assert job.untranslated_ports != sorted(job.untranslated_ports)

    def test_a_reference_is_not_listed(self) -> None:
        """A route to ``Null0``.  The translator cannot read that
        either and leaves it, but it is no interface of the config:
        what a route names is not always one, and a job is not held
        for every route to nowhere."""
        text = _IOS_UNREAD.replace(
            "interface GigabitEthernet1\n ip address 10.2.0.1 255.255.255.0\n!\n", "",
        )
        job = _checked("cisco_iosxe_cli", "arista_eos", text)
        assert (
            "cisco_iosxe_cli: could not classify port name 'Null0'; left verbatim"
        ) in job.warnings
        assert "ip route 10.50.0.0/16 Null0" in job.rendered
        assert (job.status, job.untranslated_ports, job.error) == (COMPLETED, [], None)

    def test_a_logical_name_counts_too(self) -> None:
        """An AOS-S VLAN's address is carried on an interface its
        parser names ``Vlan20``, which its classifier does not read.
        On Junos that is an interface named ``Vlan20``."""
        job = _checked("aruba_aoss", "juniper_junos", _AOSS_VLAN_ADDRESS)
        assert "Vlan20" not in job.source_ports and "Vlan20" in job.source_other_names
        assert (
            "set interfaces Vlan20 unit 0 family inet address 10.0.20.1/24"
        ) in job.rendered
        assert job.untranslated_ports == ["Vlan20"]
        assert job.status == PARTIAL
        # No hardware port among them: a pair of devices decides nothing.
        assert "devices" not in job.error.partition(NOT_SETTLED)[2]

    def test_one_codec_lists_nothing(self) -> None:
        """No name is classified there: each stands, valid by
        construction, and nothing but an entry changes one."""
        job = _checked("cisco_iosxe_cli", "cisco_iosxe_cli", _IOS_UNREAD)
        assert "interface GigabitEthernet1\n" in job.rendered
        assert not [line for line in job.warnings if "classify" in line]
        assert (job.status, job.error) == (COMPLETED, None)
        assert (job.fused_ports, job.unresolved_ports, job.untranslated_ports) == ({}, [], [])


# ---------------------------------------------------------------------------
# 3d. A name left as it was that is the target's own
# ---------------------------------------------------------------------------

#: An old IOS router.  ``Ethernet0`` is a 10 Mb/s port, which the
#: IOS-XE classifier does not read -- and EOS calls a port that.
_IOS_ETHERNET_0 = "\n".join([
    "!", "version 15.2", "hostname r1", "!",
    "interface Ethernet0", " ip address 10.2.0.1 255.255.255.0", "!",
    "end", "",
])

#: RouterOS, where an operator names a VLAN's interface.  This one is
#: called ``vlan100`` and carries VLAN 20.
_ROUTEROS_VLAN_NAME = "\n".join([
    "# by RouterOS 7.13",
    "/interface bridge", "add name=bridge1",
    "/interface vlan",
    "add interface=bridge1 name=vlan100 vlan-id=20",
    "/ip address",
    "add address=10.0.20.1/24 interface=vlan100",
    "",
])

#: The AOS-S switch above, with a stanza for port ``1/1``.
_AOSS_VLAN_AND_PORT = _AOSS_VLAN_ADDRESS.replace(
    "vlan 1\n", 'interface 1/1\n   name "desk"\n   exit\nvlan 1\n',
)

_LEFT_VLAN20 = "aruba_aoss: could not classify port name 'Vlan20'; left verbatim"


class TestANameTheTargetWritesItself:
    """Not every name the translator left is a foreign name on the
    target.  An AOS-S VLAN's address is carried on an interface the
    AOS-S parser names ``Vlan20``; its classifier does not read that
    name, the translator leaves it -- and on EOS, IOS-XE and NX-OS
    that is exactly what the interface is called."""

    @pytest.mark.parametrize(
        ("target_name", "line"),
        [
            ("arista_eos", "interface Vlan20\n"),
            ("cisco_iosxe_cli", "interface Vlan20\n"),
            ("cisco_nxos", "interface Vlan20\n"),
            ("cisco_iosxe", "<name>Vlan20</name>"),
        ],
    )
    def test_a_vlan_interface_called_that(
        self, target_name: str, line: str,
    ) -> None:
        source, target = get_codec("aruba_aoss"), get_codec(target_name)
        before = _unchecked("aruba_aoss", target_name, _AOSS_VLAN_ADDRESS)
        job = _checked("aruba_aoss", target_name, _AOSS_VLAN_ADDRESS)
        # The translator says what it did, as it always has ...
        assert _LEFT_VLAN20 in job.warnings
        assert line in job.rendered and "10.0.20.1" in job.rendered
        # ... and nothing is under a foreign name: the job is what
        # it was before the status looked at the names.
        assert job.untranslated_ports == []
        assert (job.status, job.error) == (before.status, before.error)
        assert NOT_SETTLED not in (job.error or "")
        if target_name != "cisco_iosxe":
            # (Over NETCONF the job is ``partial`` for its validation.)
            assert job.status == COMPLETED
            assert read_back(source, target, _AOSS_VLAN_ADDRESS, job, {}) == []

    @pytest.mark.parametrize(
        "target_name",
        [
            "aruba_aoscx", "cisco_iosxr", "dell_os10", "fortigate_cli",
            "juniper_junos", "mikrotik_routeros", "opnsense", "vyos",
        ],
    )
    def test_and_where_it_is_called_otherwise(self, target_name: str) -> None:
        """``interface vlan 20`` on AOS-CX, ``irb.20`` on Junos,
        ``vlan20`` on OS10: on every other target the same name is
        the source's, and the job is held for it."""
        job = _checked("aruba_aoss", target_name, _AOSS_VLAN_ADDRESS, force=True)
        assert _LEFT_VLAN20 in job.warnings and "Vlan20" in job.rendered
        assert job.untranslated_ports == ["Vlan20"]
        assert job.status == PARTIAL and NOT_SETTLED in job.error

    def test_a_spelling_read_and_not_written(self) -> None:
        """OS10 reads ``Vlan20`` as a VLAN's interface and prints
        ``vlan20``.  A classifier is lenient about what it reads;
        only the spelling a target writes itself is known to be its
        own, and nothing here shows OS10 takes the other."""
        os10 = get_codec("dell_os10")
        read = os10.classify_port_name("Vlan20")
        assert (read.kind, os10.format_port_identity(read)) == ("svi", "vlan20")
        job = _checked("aruba_aoss", "dell_os10", _AOSS_VLAN_ADDRESS)
        assert "interface Vlan20\n" in job.rendered
        assert job.untranslated_ports == ["Vlan20"]

    def test_two_codecs_of_one_platform(self) -> None:
        """IOS-XE as CLI text and over NETCONF: a name the CLI
        classifier does not read is still a name of IOS-XE."""
        job = _checked("cisco_iosxe_cli", "cisco_iosxe", _IOS_UNREAD)
        assert (
            "cisco_iosxe_cli: could not classify port name 'GigabitEthernet1'; "
            "left verbatim"
        ) in job.warnings
        assert "<name>GigabitEthernet1</name>" in job.rendered
        assert job.untranslated_ports == []
        assert NOT_SETTLED not in (job.error or "")
        before = _unchecked("cisco_iosxe_cli", "cisco_iosxe", _IOS_UNREAD)
        assert (job.status, job.error) == (before.status, before.error)
        # On another platform the same name is listed.
        other = _checked("cisco_iosxe_cli", "arista_eos", _IOS_UNREAD)
        assert other.untranslated_ports == ["GigabitEthernet1"]

    def test_which_codecs_are_one_platform(self) -> None:
        """A codec states its platform as the id of a file under
        ``netcanon/migration/vendors/``.  Exactly one pair of the
        public codecs shares one; a codec given another's id by
        mistake would have every name it leaves pass unlisted."""
        from netcanon.migration.vendors import load_vendors

        names = list_public_codecs()
        vendors = load_vendors()
        assert all(get_codec(name).capabilities.vendor_id in vendors for name in names)
        pairs = {
            frozenset((a, b)) for a in names for b in names
            if a != b and migration_pipeline._one_platform(get_codec(a), get_codec(b))
        }
        assert pairs == {frozenset(("cisco_iosxe", "cisco_iosxe_cli"))}
        # Asked either way round; and one codec is one platform.
        assert all(
            migration_pipeline._one_platform(get_codec(name), get_codec(name))
            for name in names
        )
        # Two codecs that state no platform are not thereby one.
        nameless = SimpleNamespace(capabilities=SimpleNamespace(vendor_id=""))
        assert not migration_pipeline._one_platform(nameless, nameless)
        assert not migration_pipeline._one_platform(SimpleNamespace(), SimpleNamespace())

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("interface_type", "ianaift:softwareLoopback"),
            ("interface_type", "ianaift:ethernetCsmacd"),
            ("interface_type", ""),
            ("kind", "mgmt"),
        ],
        ids=["a loopback", "a hardware port", "nothing said", "marked from context"],
    )
    def test_only_as_what_the_source_says_it_is(self, field: str, value: str) -> None:
        """EOS reads ``Vlan20`` as a VLAN's interface.  Where the
        tree that is rendered says the interface under that name is
        something else, the target's reading of the name says
        nothing about it, and the name is listed."""
        def as_something_else(tree):
            for iface in tree.interfaces:
                if iface.name == "Vlan20":
                    setattr(iface, field, value)
            return tree

        job = _checked(
            "aruba_aoss", "arista_eos", _AOSS_VLAN_ADDRESS, transforms=[as_something_else],
        )
        assert "interface Vlan20\n" in job.rendered
        assert job.untranslated_ports == ["Vlan20"] and job.status == PARTIAL

    def test_never_a_hardware_port(self) -> None:
        """``Ethernet0`` of an IOS router, which EOS reads as a port
        and writes back as it is.  Which port of another device a
        port is, is what a declared device answers; no reading of a
        name does."""
        eos = get_codec("arista_eos")
        read = eos.classify_port_name("Ethernet0")
        assert (read.kind, eos.format_port_identity(read)) == ("physical", "Ethernet0")
        job = _checked("cisco_iosxe_cli", "arista_eos", _IOS_ETHERNET_0)
        assert "interface Ethernet0\n" in job.rendered
        assert job.source_ports == ["Ethernet0"]
        assert job.untranslated_ports == ["Ethernet0"] and job.status == PARTIAL

    def test_never_from_free_text_names(self) -> None:
        """A RouterOS VLAN interface called ``vlan100`` that carries
        VLAN 20.  On OS10 ``interface vlan100`` IS the interface of
        VLAN 100, and the address of VLAN 20 is written under it."""
        os10 = get_codec("dell_os10")
        read = os10.classify_port_name("vlan100")
        assert (read.kind, os10.format_port_identity(read)) == ("svi", "vlan100")
        job = _checked("mikrotik_routeros", "dell_os10", _ROUTEROS_VLAN_NAME, force=True)
        assert "interface vlan100\n" in job.rendered and "10.0.20.1" in job.rendered
        assert "vlan100" in job.untranslated_ports

    @pytest.mark.parametrize("reverse", [False, True], ids=["port first", "port last"])
    def test_two_interfaces_under_the_name(self, reverse: bool) -> None:
        """An entry sends a port onto ``Vlan20``.  The tree that is
        rendered then holds a VLAN's interface and a port under the
        one name, and the name is vouched for as neither."""
        def order(tree):
            tree.interfaces.sort(key=lambda iface: iface.interface_type, reverse=reverse)
            return tree

        job = _checked(
            "aruba_aoss", "arista_eos", _AOSS_VLAN_AND_PORT, {"1/1": "Vlan20"},
            transforms=[order],
        )
        assert job.fused_ports == {"Vlan20": ["1/1", "Vlan20"]}
        assert job.untranslated_ports == ["Vlan20"]

    @pytest.mark.parametrize(
        ("name", "kinds", "source_name", "target_name", "written", "own"),
        [
            ("Vlan10", {"svi"}, "aruba_aoss", "arista_eos", "Vlan10", True),
            ("Loopback0", {"loopback"}, "aruba_aoss", "arista_eos", "Loopback0", True),
            ("Port-Channel1", {"lag"}, "aruba_aoss", "arista_eos", "Port-Channel1", True),
            ("Tunnel1", {"tunnel"}, "aruba_aoss", "arista_eos", "Tunnel1", True),
            ("vlan10", {"svi"}, "aruba_aoss", "dell_os10", "vlan10", True),
            ("loopback0", {"loopback"}, "aruba_aoss", "cisco_nxos", "loopback0", True),
            # Read as another kind than the source config gave.
            ("Loopback0", {"svi"}, "aruba_aoss", "arista_eos", "Loopback0", False),
            # Read, and written another way.
            ("vlan10", {"svi"}, "aruba_aoss", "arista_eos", "Vlan10", False),
            ("Port-channel1", {"lag"}, "aruba_aoss", "arista_eos", "Port-Channel1", False),
            ("Vlan10", {"svi"}, "aruba_aoss", "dell_os10", "vlan10", False),
            # A hardware port, however the target reads it.
            ("Ethernet0", {"physical"}, "cisco_iosxe_cli", "arista_eos", "Ethernet0", False),
            ("mgmt0", {"mgmt"}, "aruba_aoss", "cisco_nxos", "mgmt0", False),
            # Two things under the name, or nothing.
            ("Vlan10", {"svi", "loopback"}, "aruba_aoss", "arista_eos", "Vlan10", False),
            ("Vlan10", {"svi", ""}, "aruba_aoss", "arista_eos", "Vlan10", False),
            ("Vlan10", set(), "aruba_aoss", "arista_eos", "Vlan10", False),
            # A unit of another name: OPNsense reads any ``<name>.<n>``.
            ("agg1.100", {"svi"}, "vyos", "opnsense", "agg1.100", False),
            # A target whose names are free text.
            ("lo", {"loopback"}, "vyos", "mikrotik_routeros", "lo", False),
            ("loopback0", {"loopback"}, "cisco_nxos", "fortigate_cli", "loopback0", False),
            # A source whose names are.
            ("loopback0", {"loopback"}, "mikrotik_routeros", "cisco_nxos", "loopback0", False),
        ],
    )
    def test_the_rule_line_by_line(
        self, name: str, kinds: set[str], source_name: str, target_name: str,
        written: str, own: bool,
    ) -> None:
        """*written* is what the target writes its reading of the
        name back as.  Every row is a name its target reads; all but
        the three "written another way" are written back as they
        are, so what refuses a row is the one thing it is there
        for."""
        source, target = get_codec(source_name), get_codec(target_name)
        assert target.format_port_identity(target.classify_port_name(name)) == written
        assert migration_pipeline._the_targets_own(name, kinds, source, target) is own

    def test_a_classifier_that_raises(self, monkeypatch) -> None:
        """A per-vendor classifier, on a string from a pasted config.
        One that fails on it has not read it; the name is listed and
        the job is not failed for it."""
        target = get_codec("arista_eos")

        def fail(_name):
            raise ValueError("no")

        assert migration_pipeline._the_targets_own(
            "Vlan20", {"svi"}, get_codec("aruba_aoss"), target,
        )
        monkeypatch.setattr(target, "classify_port_name", fail)
        assert not migration_pipeline._the_targets_own(
            "Vlan20", {"svi"}, get_codec("aruba_aoss"), target,
        )


# ---------------------------------------------------------------------------
# 4. The status, the sentence and the fields
# ---------------------------------------------------------------------------

#: What the sentence says of each kind, and what it says settles it.
_SAID = {
    "fused": (
        "1 name(s) in the output received more than one source name, so the "
        "config of two interfaces is written as one. "
    ),
    "ports": "2 port(s) the target has no name for were dropped from the output. ",
    "others": (
        "1 other name(s) the target has no form for (such as a loopback, a "
        "tunnel or a hardware switch) were dropped from the output. "
    ),
    "left": (
        "1 name(s) could not be read as any kind of port: whatever the "
        "output has of them is under the name the source config has for "
        "them, which the target may not accept. "
    ),
}
_SETTLED_BY = {
    "fused": "a name of its own, or null, for all but one of the names that share one",
    "dropped": "a target name for a dropped name, or null to say it is to go",
    "left": (
        "for a name left as it was, the name it is to have on the target "
        "(its own, if that is right there) or null"
    ),
}
_OR_DEVICES = " Or declare both devices, to pair ports by position."
_DEVICES_FOR_SOME = (
    " Declaring both devices pairs the hardware ports among these by "
    "position; the names that are not hardware ports need an entry either way."
)


class TestWhatTheJobSays:
    def test_both_in_one_job(self) -> None:
        job = _checked("juniper_junos", "cisco_iosxe_cli", _JUNOS_BOTH)
        assert job.fused_ports == {"Vlan100": ["irb.100", "vlan.100"]}
        assert job.unresolved_ports == ["fxp0"]
        assert job.untranslated_ports == []
        assert job.status == PARTIAL
        assert job.error == (
            "Port names are not settled: 1 name(s) in the output received "
            "more than one source name, so the config of two interfaces is "
            "written as one. 1 port(s) the target has no name for were "
            "dropped from the output. An entry in port_rename_map settles "
            "each: a name of its own, or null, for all but one of the names "
            "that share one; a target name for a dropped name, or null to "
            "say it is to go. Declaring both devices pairs the hardware "
            "ports among these by position; the names that are not hardware "
            "ports need an entry either way."
        )

    def test_an_entry_for_each_settles_it(self) -> None:
        job = _checked(
            "juniper_junos", "cisco_iosxe_cli", _JUNOS_BOTH,
            {"vlan.100": "Loopback2", "fxp0": None},
        )
        assert (job.status, job.error) == (COMPLETED, None)
        assert (job.fused_ports, job.unresolved_ports) == ({}, [])
        assert read_back(
            get_codec("juniper_junos"), get_codec("cisco_iosxe_cli"), _JUNOS_BOTH, job,
            {"vlan.100": "Loopback2", "fxp0": None},
        ) == []

    @pytest.mark.parametrize(
        ("fused", "dropped", "left", "hardware", "said", "settled_by", "devices"),
        [
            ({"a": ["x", "y"]}, [], [], ["x"], ["fused"], ["fused"], _OR_DEVICES),
            ({"a": ["x", "y"]}, [], [], [], ["fused"], ["fused"], ""),
            ({}, ["p", "q"], [], ["p", "q"], ["ports"], ["dropped"], _OR_DEVICES),
            ({}, ["t"], [], [], ["others"], ["dropped"], ""),
            ({}, [], ["g"], ["g"], ["left"], ["left"], _OR_DEVICES),
            ({}, [], ["v"], [], ["left"], ["left"], ""),
            (
                {"a": ["x", "y"]}, ["p", "q", "t"], ["g"], ["p", "q"],
                ["fused", "ports", "others", "left"], ["fused", "dropped", "left"],
                _DEVICES_FOR_SOME,
            ),
        ],
        ids=[
            "shared, with a port", "shared, logical names only", "ports dropped",
            "a logical name dropped", "a port left as it was",
            "a logical name left as it was", "all of them",
        ],
    )
    def test_the_sentence_names_each_kind(
        self, fused: dict, dropped: list[str], left: list[str], hardware: list[str],
        said: list[str], settled_by: list[str], devices: str,
    ) -> None:
        """Declaring both devices is offered only where a hardware
        port is among what is listed: the pairing is of hardware
        ports, and a job with both devices declared does not hold
        for two loopbacks on one or for a tunnel dropped.  Sent there
        for those, an operator would get ``completed`` for the same
        output."""
        assert migration_pipeline._names_message(fused, dropped, left, hardware) == (
            NOT_SETTLED + "".join(_SAID[kind] for kind in said)
            + "An entry in port_rename_map settles each: "
            + "; ".join(_SETTLED_BY[kind] for kind in settled_by) + "." + devices
        )

    @pytest.mark.parametrize(
        ("dropped", "left"), [(["p", "t"], []), (["p"], ["v"])],
        ids=["beside a tunnel dropped", "beside a VLAN interface left"],
    )
    def test_devices_decide_the_port_and_no_more(
        self, dropped: list[str], left: list[str],
    ) -> None:
        """A port that was dropped, and one other name that is no
        port.  The devices decide the port; the sentence says the
        other name needs an entry either way -- and does not, where
        that name is a port as well."""
        said = migration_pipeline._names_message({}, dropped, left, ["p"])
        assert said.endswith(_DEVICES_FOR_SOME)
        said = migration_pipeline._names_message({}, dropped, left, ["p", "t", "v"])
        assert said.endswith(_OR_DEVICES) and _DEVICES_FOR_SOME not in said

    def test_nothing_unsettled_says_nothing(self) -> None:
        assert migration_pipeline._names_message({}, [], [], ["x"]) == ""

    def test_devices_are_not_offered_for_these(self) -> None:
        """Two VLAN interfaces on one.  With both devices declared
        the same output is ``completed``: the pairing is of hardware
        ports and asks nothing of these.  So the sentence here does
        not offer it."""
        job = _checked("juniper_junos", "arista_eos", _JUNOS_TWO_VLAN_INTERFACES)
        assert job.fused_ports == {"Vlan100": ["irb.100", "vlan.100"]}
        assert not set(job.source_ports).intersection(job.fused_ports["Vlan100"])
        assert job.error == (
            NOT_SETTLED + _SAID["fused"] + "An entry in port_rename_map "
            "settles each: " + _SETTLED_BY["fused"] + "."
        )

    def test_already_partial_keeps_its_first(self) -> None:
        """VyOS cannot carry the VXLAN of this config, so the job is
        ``partial`` for the validation report.  The sentence about
        the names is added after that one, not put in its place."""
        before = _unchecked("juniper_junos", "vyos", _JUNOS_TWO_FPCS)
        assert before.status == PARTIAL and before.error
        job = _checked("juniper_junos", "vyos", _JUNOS_TWO_FPCS)
        assert job.status == PARTIAL
        assert job.fused_ports == {"eth1": ["ge-0/0/1", "ge-1/0/1"]}
        first, _, second = job.error.partition(" " + NOT_SETTLED)
        assert first == before.error
        assert second.startswith("1 name(s) in the output received more than one")

    def test_a_failed_job_is_untouched(self) -> None:
        before = _unchecked("juniper_junos", "cisco_iosxe_cli", "")
        job = _checked("juniper_junos", "cisco_iosxe_cli", "")
        assert job.status == FAILED and job.rendered is None
        assert job.error == before.error
        assert (job.fused_ports, job.unresolved_ports, job.untranslated_ports) == ({}, [], [])
        assert _rest(job) == _rest(before)

    def test_a_job_that_did_not_render(self, monkeypatch) -> None:
        """The translator ran, and dropped a port, before the render
        failed.  There is no output for two names to share or a port
        to be missing from: the failure is the whole of what the job
        says."""
        target = get_codec("cisco_iosxe_cli")

        def refuse(_tree):
            raise RenderError("no")

        monkeypatch.setattr(target, "render", refuse)
        job = run_plan_with_checked_names(
            get_codec("cisco_nxos"), target, _NXOS_MGMT, port_rename_map={},
        )
        assert job.status == FAILED and job.rendered is None
        assert job.error == "render failed: no"
        assert job.port_drops == ["mgmt0"]
        assert (job.fused_ports, job.unresolved_ports) == ({}, [])
        # Nor a name left as it was: there is no output for it to be in.
        target = get_codec("arista_eos")
        monkeypatch.setattr(target, "render", refuse)
        job = run_plan_with_checked_names(
            get_codec("cisco_iosxe_cli"), target, _IOS_UNREAD, port_rename_map={},
        )
        assert job.status == FAILED and job.rendered is None
        assert job.untranslated_ports == []

    @pytest.mark.parametrize(
        ("source_name", "target_name", "text"),
        [
            ("juniper_junos", "cisco_iosxe_cli", _JUNOS_BOTH),
            ("aruba_aoss", "arista_eos", _AOSS_TWO_PORTS),
            ("cisco_iosxe_cli", "arista_eos", _IOS_UNREAD),
        ],
        ids=["junos", "aoss", "ios"],
    )
    def test_no_port_map_translates_nothing(
        self, source_name: str, target_name: str, text: str,
    ) -> None:
        """``None`` is the translator not run at all: no name changes,
        so no two can have ended on one and none was dropped."""
        source, target = get_codec(source_name), get_codec(target_name)
        before = run_plan_with_overrides(source, target, text, port_rename_map=None)
        job = run_plan_with_checked_names(source, target, text, port_rename_map=None)
        assert (job.port_renames, job.port_drops) == ({}, [])
        assert (job.fused_ports, job.unresolved_ports, job.untranslated_ports) == ({}, [], [])
        assert (job.status, job.error) == (before.status, before.error)
        assert _rest(job) == _rest(before)
        # With the translator run, the same config is not settled.
        assert _checked(source_name, target_name, text).status == PARTIAL

    def test_nothing_else_of_the_job_moves(self) -> None:
        """Nothing is renamed or dropped by the check: the output is
        the one ``run_plan_with_overrides`` rendered."""
        before = _unchecked("juniper_junos", "cisco_iosxe_cli", _JUNOS_BOTH)
        job = _checked("juniper_junos", "cisco_iosxe_cli", _JUNOS_BOTH)
        assert job.rendered == before.rendered
        assert _rest(job) == _rest(before)

    def test_a_callers_transform_still_runs(self) -> None:
        def rename_host(tree):
            tree.hostname = "renamed"
            return tree

        job = _checked(
            "juniper_junos", "cisco_iosxe_cli", _JUNOS_BOTH, transforms=[rename_host],
        )
        assert "hostname renamed" in job.rendered
        assert job.fused_ports == {"Vlan100": ["irb.100", "vlan.100"]}

    def test_it_takes_what_the_frozen_one_takes(self) -> None:
        """Every handler's arguments fit both: the helper that
        dispatches them passes the same keywords to either."""
        ours = inspect.signature(run_plan_with_checked_names).parameters
        theirs = inspect.signature(run_plan_with_overrides).parameters
        assert [(p.name, p.kind, p.default) for p in ours.values()] == [
            (p.name, p.kind, p.default) for p in theirs.values()
        ]


# ---------------------------------------------------------------------------
# 5. The oracle is handed the defect it is for
# ---------------------------------------------------------------------------


class TestTheReadBackItself:
    """A check nobody has seen fail is not known to check anything.
    Each job here is one the pipeline called ``completed`` before the
    status looked at the names."""

    def test_two_interfaces_written_as_one(self) -> None:
        job = _unchecked("juniper_junos", "arista_eos", _JUNOS_TWO_VLAN_INTERFACES)
        assert job.status == COMPLETED
        assert read_back(
            get_codec("juniper_junos"), get_codec("arista_eos"),
            _JUNOS_TWO_VLAN_INTERFACES, job, {},
        ) == ["'Vlan100' in the output carries the addresses of ['irb.100', 'vlan.100']"]

    def test_a_port_that_is_not_in_the_output(self) -> None:
        job = _unchecked("cisco_nxos", "cisco_iosxe_cli", _NXOS_MGMT)
        assert job.status == COMPLETED
        assert read_back(
            get_codec("cisco_nxos"), get_codec("cisco_iosxe_cli"), _NXOS_MGMT, job, {},
        ) == [
            "'mgmt0' has an address and is not in the output, and no entry "
            "of the port map decided it"
        ]

    def test_a_port_an_entry_dropped_is_fine(self) -> None:
        entries: dict[str, str | None] = {"mgmt0": None}
        job = _unchecked("cisco_nxos", "cisco_iosxe_cli", _NXOS_MGMT, entries)
        assert read_back(
            get_codec("cisco_nxos"), get_codec("cisco_iosxe_cli"), _NXOS_MGMT, job, entries,
        ) == []

    def test_a_drop_the_job_does_not_list_is_one(self) -> None:
        """An entry alone is not enough: the job has to say the port
        went."""
        job = _unchecked("cisco_nxos", "cisco_iosxe_cli", _NXOS_MGMT)
        job.port_drops = []
        assert read_back(
            get_codec("cisco_nxos"), get_codec("cisco_iosxe_cli"), _NXOS_MGMT, job,
            {"mgmt0": None},
        ) != []

    def test_a_port_found_only_in_the_text(self) -> None:
        """AOS-S writes a management port in its ``oobm`` block, which
        its parser gives back as no interface.  The port is in the
        output, and the oracle looks at the text before saying it is
        not."""
        source, target = get_codec("cisco_nxos"), get_codec("aruba_aoss")
        text = _NXOS_MGMT.replace(
            "interface Ethernet1/1\n  no switchport\n  ip address 10.1.0.1/24\n\n", "",
        )
        job = _unchecked("cisco_nxos", "aruba_aoss", text)
        assert job.port_renames == {"mgmt0": "oobm"}
        assert "192.0.2.9" in job.rendered
        assert not [
            iface for iface in target.parse(job.rendered).interfaces
            if "192.0.2.9" in _addresses(iface)
        ]
        assert read_back(source, target, text, job, {}) == []

    def test_an_address_of_either_family_counts(self) -> None:
        """Interfaces that have only IPv6 addresses: two VLAN
        interfaces written as one, and a port that is not in the
        output."""
        text = "\n".join([
            "set system host-name r1",
            "set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.1/24",
            "set interfaces irb unit 100 family inet6 address 2001:db8::1/64",
            "set interfaces vlan unit 100 family inet6 address 2001:db8:1::1/64",
            "",
        ])
        job = _unchecked("juniper_junos", "arista_eos", text)
        assert job.status == COMPLETED
        assert read_back(
            get_codec("juniper_junos"), get_codec("arista_eos"), text, job, {},
        ) == ["'Vlan100' in the output carries the addresses of ['irb.100', 'vlan.100']"]

        text = _NXOS_MGMT.replace("ip address 192.0.2.9/24", "ipv6 address 2001:db8:9::9/64")
        job = _unchecked("cisco_nxos", "cisco_iosxe_cli", text)
        assert job.status == COMPLETED and "2001:db8:9::9" not in job.rendered
        assert read_back(
            get_codec("cisco_nxos"), get_codec("cisco_iosxe_cli"), text, job, {},
        ) == [
            "'mgmt0' has an address and is not in the output, and no entry "
            "of the port map decided it"
        ]

    def test_a_logical_interface_counts(self) -> None:
        """A FortiGate hardware switch with the LAN address.  Its
        classifier does not call it a port, and a read-back that
        asked only after ports would agree with the condition that
        nothing was lost."""
        job = run_plan_with_overrides(
            get_codec("fortigate_cli"), get_codec("cisco_iosxe_cli"),
            _FORTIOS_HARD_SWITCH, port_rename_map={}, force=True,
        )
        assert job.status == COMPLETED and "192.168.1.99" not in job.rendered
        assert read_back(
            get_codec("fortigate_cli"), get_codec("cisco_iosxe_cli"),
            _FORTIOS_HARD_SWITCH, job, {},
        ) == [
            "'internal' has an address and is not in the output, and no entry "
            "of the port map decided it"
        ]

    def test_an_entry_for_a_left_name_is_fine(self) -> None:
        """The warning is there only while nobody decided the name;
        with an entry the translator never asks the classifier."""
        entries: dict[str, str | None] = {"GigabitEthernet1": "GigabitEthernet1"}
        job = _unchecked("cisco_iosxe_cli", "arista_eos", _IOS_UNREAD, entries)
        assert "interface GigabitEthernet1\n" in job.rendered
        assert read_back(
            get_codec("cisco_iosxe_cli"), get_codec("arista_eos"), _IOS_UNREAD, job, entries,
        ) == []

    def test_a_name_left_that_is_the_targets_own(self) -> None:
        """An AOS-S VLAN's interface on EOS is called what the AOS-S
        parser calls it, and the oracle reads that from the text.
        Where the text opens the interface another way, or the target
        is not one the oracle has a line for, the name is a foreign
        one."""
        source = get_codec("aruba_aoss")
        complaint = [
            "'Vlan20' was left as the source config has it, and no entry "
            "of the port map decided it"
        ]
        for target_name, said in [
            ("arista_eos", []), ("cisco_nxos", []),
            ("dell_os10", complaint), ("juniper_junos", complaint),
        ]:
            job = _unchecked("aruba_aoss", target_name, _AOSS_VLAN_ADDRESS)
            assert job.status == COMPLETED and "Vlan20" in job.rendered
            assert read_back(
                source, get_codec(target_name), _AOSS_VLAN_ADDRESS, job, {},
            ) == said, target_name
        # The line has to be in the output, and be the whole name.
        job = _unchecked("aruba_aoss", "arista_eos", _AOSS_VLAN_ADDRESS)
        job.rendered = job.rendered.replace("interface Vlan20\n", "interface Vlan200\n")
        assert read_back(
            source, get_codec("arista_eos"), _AOSS_VLAN_ADDRESS, job, {},
        ) == complaint

    def test_what_the_oracle_takes_for_right(self) -> None:
        """Its own table, row by row: one platform; a VLAN's
        interface where the target opens one with that name; and
        nothing else -- not another kind of interface, not a VLAN the
        source config does not have, not a name from a platform where
        names are free text."""
        aoss, eos = get_codec("aruba_aoss"), get_codec("arista_eos")
        tree = aoss.parse(_AOSS_VLAN_ADDRESS)
        text = "interface Vlan20\n   ip address 10.0.20.1/24\n"
        assert _right_as_it_stands("Vlan20", tree, aoss, eos, text)
        assert not _right_as_it_stands("Vlan20", tree, aoss, eos, "interface Vlan200\n")
        assert not _right_as_it_stands("Vlan20", tree, aoss, get_codec("dell_os10"), text)
        assert not _right_as_it_stands(
            "Vlan20", tree, get_codec("mikrotik_routeros"), eos, text,
        )
        # ... nor the interface of a VLAN the source config lacks,
        tree.vlans = [vlan for vlan in tree.vlans if vlan.id != 20]
        assert not _right_as_it_stands("Vlan20", tree, aoss, eos, text)
        # nor one the source parser read as something else.
        tree = aoss.parse(_AOSS_VLAN_ADDRESS)
        (svi,) = [iface for iface in tree.interfaces if iface.name == "Vlan20"]
        svi.interface_type = "ianaift:softwareLoopback"
        assert not _right_as_it_stands("Vlan20", tree, aoss, eos, text)
        ios = get_codec("cisco_iosxe_cli")
        tree = ios.parse(_IOS_UNREAD)
        assert _right_as_it_stands("GigabitEthernet1", tree, ios, get_codec("cisco_iosxe"), "")
        assert not _right_as_it_stands("GigabitEthernet1", tree, ios, eos, "")

    def test_it_says_how_often_it_was_asked(self) -> None:
        """What lets the test over the captures show that it asked."""
        asked = _READ_BACKS["asked"]
        job = _unchecked("cisco_nxos", "cisco_iosxe_cli", _NXOS_MGMT)
        read_back(get_codec("cisco_nxos"), get_codec("cisco_iosxe_cli"), _NXOS_MGMT, job, {})
        assert _READ_BACKS["asked"] == asked + 1

    def test_an_address_two_hold_is_nobodys(self) -> None:
        """The same address on two source interfaces (one in each of
        two routing instances) says nothing about where an interface
        of the output came from, and is left out: taken for the first
        interface that holds it, it would make the second look like
        two interfaces in one."""
        text = "\n".join([
            "set system host-name r1",
            "set interfaces ge-0/0/1 unit 0 family inet address 10.0.0.1/24",
            "set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.1/24",
            "set interfaces ge-0/0/2 unit 0 family inet address 10.0.0.1/24",
            "set interfaces ge-0/0/2 unit 0 family inet address 10.2.0.1/24",
            "",
        ])
        source, target = get_codec("juniper_junos"), get_codec("arista_eos")
        job = _checked("juniper_junos", "arista_eos", text)
        assert job.status == COMPLETED
        assert [
            [address.ip for address in iface.ipv4_addresses]
            for iface in target.parse(job.rendered).interfaces
        ] == [["10.0.0.1", "10.1.0.1"], ["10.0.0.1", "10.2.0.1"]]
        assert read_back(source, target, text, job, {}) == []

    @pytest.mark.parametrize(
        ("ip", "text", "found"),
        [
            ("10.1.0.1", "ip address 10.1.0.1 255.255.255.0", True),
            ("10.1.0.1", "address 10.1.0.1/24", True),
            ("10.1.0.1", "ip address 10.1.0.10 255.255.255.0", False),
            ("0.1.0.1", "ip address 10.1.0.1 255.255.255.0", False),
            ("2001:db8::1", "address 2001:db8::1/64", True),
            ("2001:db8::1", "address 2001:db8::10/64", False),
        ],
    )
    def test_an_address_inside_another_is_not_it(
        self, ip: str, text: str, found: bool,
    ) -> None:
        assert _in_text(ip, text) is found


# ---------------------------------------------------------------------------
# 6. Every committed capture onto every public codec
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
#: The native capture extensions (the filter the real-capture test and
#: the mesh tool use).
_SUFFIXES = {".txt", ".cfg", ".xml", ".conf", ".rsc", ".set"}


def _captures() -> dict[str, list[Path]]:
    """Every committed capture, by its source codec."""
    found: dict[str, list[Path]] = {}
    for directory in sorted((FIXTURES / "real").iterdir()):
        codec = DIR_TO_CODEC_NAME.get(directory.name)
        if codec is None or not directory.is_dir():
            continue
        paths = [
            path for path in sorted(directory.iterdir())
            if path.is_file() and path.suffix.lower() in _SUFFIXES
        ]
        if paths:
            found.setdefault(codec, []).extend(paths)
    return found


CAPTURES = _captures()

#: Jobs that were ``completed`` and are ``partial``, with an empty port
#: map, by source codec and by reason.  The columns, in order: a name
#: of the output shared by source names one of which is a hardware
#: port; shared by logical names only; a hardware port dropped; a
#: logical name dropped; a name left as the source config has it;
#: more than one of those.  Measured, and pinned: a capture added to
#: the corpus, or a change to a classifier or a formatter, moves a
#: number here and says which.
_MOVES: dict[str, tuple[int, int, int, int, int, int]] = {
    "arista_eos": (0, 0, 9, 1, 0, 0),
    # From (0, 0, 6, 0, 0, 0): onto Junos the global table has one
    # loopback, unit 0 of lo0.  The two arch3 leafs have `loopback 0`
    # and `loopback 1` there; `loopback 1` was written `lo1`, an
    # interface Junos does not have, and is dropped and listed (+2).
    "aruba_aoscx": (0, 0, 6, 2, 0, 0),
    # From (8, 0, 0, 0, 6, 0): an AOS-S stanza ends at its `exit`, not
    # at a line in column 0.  The KB.15.15 capture, every line at
    # column 0, had been read as three empty VLANs; its 48 letter-slot
    # ports and `Vlan2` / `Vlan3` are now in the output as the source
    # names them, onto EOS, AOS-CX, IOS-XE CLI, NX-OS, OS10 and Junos
    # (+6 left as the source has it).  The template render's three
    # VLAN addresses are read: onto Junos its `Vlan<N>` names are left
    # as well, beside its fused uplink (-1 fused, +1 several).
    "aruba_aoss": (7, 0, 0, 0, 12, 1),
    # From (10, 0, 0, 0, 3, 20): the IOSv capture whose every line is
    # at column 0 is refused by the IOS-XE CLI parser now, and is no
    # longer among the captures (it is under `refused/`); two of its
    # jobs had a name shared with a hardware port.  And from (8, 0, 0,
    # 0, 3, 20): onto AOS-S, the umbrella capture's routes out `dhcp`
    # are left out under a review line, AOS-S having no such next hop,
    # and the job is `partial` for them before any name is checked.
    # And the EVPN leaf's `Loopback2`, the VTEP source beside
    # `Loopback0`, was `lo2` onto Junos (+1 logical name dropped).
    "cisco_iosxe_cli": (8, 0, 0, 1, 3, 19),
    # From (4, 0, 13, 0, 1, 2): batfish_ibgp_rr has two loopbacks in
    # the global table; onto Junos `Loopback123` was `lo123` (+1).
    # And onto RouterOS a sub-interface is a VLAN interface on its
    # port, and `/interfaces/interface/dot1q-vlan` is lossy where it
    # was unsupported.  The CST capture's job was `partial` for the
    # matrix alone; it is `partial` for its names now,
    # `MgmtEth0/RP0/CPU0/0` and `BVI500` together (+1 several).
    # And onto FortiOS a routed sub-interface is a VLAN interface on
    # its port with its own tag, and the same path is lossy there.
    # The PA3 design capture onto FortiOS had been `partial` for
    # that path alone; the validation report passes it now, and its
    # two TenGigE ports on `port1` and its `BVI500`, left as the
    # source has it, hold it (+1 several).
    "cisco_iosxr": (4, 0, 13, 1, 1, 4),
    "cisco_nxos": (0, 0, 11, 0, 0, 0),
    "dell_os10": (0, 0, 14, 0, 0, 0),
    "fortigate_cli": (0, 0, 0, 0, 0, 11),
    # From (0, 0, 7, 0, 5, 7): no record is made for a bare `irb`
    # or `st0` that no line configures, so it is no longer a name
    # left.  Two jobs of batfish_evpntype5 (onto EOS and NX-OS)
    # listed nothing else and are `completed`; three that listed it
    # beside a dropped port now list the port alone.
    #
    # From (0, 0, 8, 0, 3, 6): a unit of lo0 is a loopback of its own
    # (`lo0.2` is `Loopback2`), so the two captures whose routing
    # instances each have one no longer put them on one loopback, and
    # list only the names left as they were (-2 several, +2 left).
    "juniper_junos": (0, 0, 8, 0, 5, 4),
    # From (0, 0, 0, 0, 21, 7): a RouterOS line broken anywhere and
    # continued is read whole, so the CRS310 capture's ports are
    # called by the names the operator gave them (`Desktop`,
    # `Access Point`).  No classifier reads such a name, so each is
    # left as the source has it and listed; and `ether1` and
    # `sfp-sfpplus1`, which the translator had put on one target
    # port, are not in the config to be put there.  Three jobs that
    # listed both now list the names alone.
    "mikrotik_routeros": (0, 0, 0, 0, 24, 4),
    "opnsense": (4, 0, 0, 0, 23, 1),
    "vyos": (17, 0, 0, 0, 0, 0),
}

#: Names the translator left as the source config has them that a
#: job does NOT list, because they are the target's own as they
#: stand: counted over every job (jobs x names), by source codec and
#: target codec.  An AOS-S VLAN's interface (``Vlan<id>``) on the
#: four targets that call it that, and every name of IOS-XE between
#: its two codecs.  A number that moves, or a pair that appears, is
#: a name that left the list: read the output line it is on before
#: changing this table.
_STANDS: dict[str, dict[str, int]] = {
    # 19, from 14: an AOS-S stanza ends at its `exit`, so the VLAN
    # addresses of the KB.15.15 capture (`Vlan2`, `Vlan3`) and of the
    # template render (`Vlan1`, `Vlan20`, `Vlan30`) are read.  Each is
    # `interface Vlan<N>` in the output of the four.
    "aruba_aoss": {
        "arista_eos": 19, "cisco_iosxe": 19, "cisco_iosxe_cli": 19, "cisco_nxos": 19,
    },
    # 18, from 19: `ethernet` of batfish_cisco_interface.txt was one
    # of them while `interface ethernet 1/11` was read as that word.
    # Read as `ethernet1/11` and `ethernet1/12` the two are ports the
    # classifier reads, and are renamed (`FastEthernet1/11`) between
    # the two codecs as every `Ethernet<slot>/<port>` already is.
    "cisco_iosxe_cli": {"cisco_iosxe": 18},
}


def _reason(job: MigrationJob) -> int:
    """The column of :data:`_MOVES` a job that lists names counts in."""
    hardware = set(job.source_ports)
    kinds: list[int] = []
    if job.fused_ports:
        with_a_port = any(hardware.intersection(names) for names in job.fused_ports.values())
        kinds.append(0 if with_a_port else 1)
    if hardware.intersection(job.unresolved_ports):
        kinds.append(2)
    if set(job.unresolved_ports) - hardware:
        kinds.append(3)
    if job.untranslated_ports:
        kinds.append(4)
    return kinds[0] if len(kinds) == 1 else 5


def _a_port_is_among(job: MigrationJob) -> bool:
    """A hardware port is among what *job* lists: what a pair of
    declared devices would have something to decide about."""
    hardware = set(job.source_ports)
    listed = [*job.unresolved_ports, *job.untranslated_ports]
    for names in job.fused_ports.values():
        listed.extend(names)
    return bool(hardware.intersection(listed))


class TestEveryCommittedCapture:
    def test_every_source_codec_is_pinned(self) -> None:
        """So that a codec's captures cannot go unread."""
        assert set(_MOVES) == set(CAPTURES)

    def test_the_totals(self) -> None:
        """What the documents say moved, kept true by the table."""
        by_reason = [sum(row[i] for row in _MOVES.values()) for i in range(6)]
        assert by_reason == [40, 0, 61, 5, 68, 44]
        assert sum(by_reason) == 218
        assert sum(sum(row.values()) for row in _STANDS.values()) == 94

    @pytest.mark.parametrize("codec_name", sorted(_MOVES))
    def test_what_moves_and_what_is_read_back(self, codec_name: str) -> None:
        source = get_codec(codec_name)
        moved = [0, 0, 0, 0, 0, 0]
        stands: Counter[str] = Counter()
        still_completed = 0
        asked = _READ_BACKS["asked"]
        for path in CAPTURES[codec_name]:
            text = path.read_text(encoding="utf-8", errors="replace")
            tree = source.parse(text)
            for target_name in list_public_codecs():
                target = get_codec(target_name)
                where = f"{path.parent.name}/{path.name} -> {target_name}"
                before = run_plan_with_overrides(source, target, text, port_rename_map={})
                job = run_plan_with_checked_names(source, target, text, port_rename_map={})
                # Nothing but the status, its sentence and the fields.
                assert _rest(job) == _rest(before), where
                assert job.rendered == before.rendered, where
                said = bool(
                    job.fused_ports or job.unresolved_ports or job.untranslated_ports
                )
                if codec_name == target_name:
                    # One codec on both sides and no entry: no name is
                    # classified, moved or dropped, and nothing is listed.
                    assert not said and job.status == before.status, where
                if before.status == COMPLETED:
                    assert job.status == (PARTIAL if said else COMPLETED), where
                else:
                    # No job moves the other way, and none to or from failed.
                    assert job.status == before.status, where
                if said:
                    assert job.rendered is not None, where
                    assert NOT_SETTLED in job.error, where
                    if before.error:
                        assert job.error.startswith(before.error + " " + NOT_SETTLED), where
                    # A pair of devices is offered where it would have
                    # a hardware port to decide, and nowhere else.
                    ours = job.error.partition(NOT_SETTLED)[2]
                    assert ("both devices" in ours) is _a_port_is_among(job), where
                else:
                    assert job.error == before.error, where
                # A name the translator left is listed, or is the
                # target's own as it stands -- whatever the status,
                # and by the oracle's own reading of the output.
                left = _left_by_the_translator(tree, job)
                assert set(job.untranslated_ports) <= set(left), where
                for name in left:
                    if name not in job.untranslated_ports:
                        assert _right_as_it_stands(
                            name, tree, source, target, job.rendered,
                        ), f"{where}: {name}"
                        stands[target_name] += 1
                if job.status == COMPLETED:
                    still_completed += 1
                    assert read_back(source, target, text, job, {}) == [], where
                if before.status == COMPLETED and said:
                    moved[_reason(job)] += 1
        assert tuple(moved) == _MOVES[codec_name]
        assert dict(stands) == _STANDS.get(codec_name, {})
        # Every job still called completed was read back, and there
        # are some: a loop that reads none back passes every line above.
        assert still_completed > 0
        assert _READ_BACKS["asked"] - asked == still_completed
