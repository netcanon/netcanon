"""An OPNsense VLAN device on a port or a LAGG is a sub-interface of it.

``<vlan><if>igb2</if><tag>20</tag><vlanif>vlan01</vlanif></vlan>`` tags
the frames of one device on ``igb2``, and OPNsense takes the same tag on
another parent as another device.  The parser read every such device as a
VLAN interface and a VLAN of its tag: onto IOS-XE, NX-OS, EOS or Junos it
came out as ``interface Vlan20`` or ``irb.20``, an interface no port
carries, and VLAN 20 on nothing.  It now reads the PARENT:

* a bridge (one ``<bridges>`` names, or one named ``bridge`` and digits),
  another VLAN device, a zone's key (``lan``, ``opt3``: never a device's
  name, and what the renderer writes for a VLAN in a config with no port),
  or a name that says it is a VLAN interface, a loopback or a tunnel: a
  VLAN interface and a VLAN of its tag, as before;
* anything else: a port, or a LAGG where ``<laggs>`` names it or its name
  says it is one.  The device is a routed sub-interface of it, typed as
  its parent, its tag its own, and no VLAN.  Zones are not typed, and the
  classifier does not read every driver's name (``igc0``).

Its description is its zone's, and the device's ``<descr>`` where the
zone has none; a ``<descr>`` beside a zone's own is said in a row.

Across vendors a sub-interface goes where its parent goes, named by its
tag; between two OPNsense configs it keeps its name.  What each input
states is typed here by hand, and each output is read as TEXT.

See also: ``tests/unit/migration/test_a_sub_interface_onto_opnsense.py``
(another vendor's sub-interface onto OPNsense) and
``codecs/opnsense/test_a_vlan_device_is_defined.py``.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from netcanon.migration.codecs import get_codec
from netcanon.migration.codecs.opnsense import parse as opn_parse
from netcanon.migration.codecs.registry import list_public_codecs
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

_ROOT = Path(__file__).resolve().parents[5]
_SUPERGATE = (
    _ROOT / "tests" / "fixtures" / "real" / "opnsense"
    / "user_contrib_supergate_opn25.xml"
)

#: One VLAN device on each kind of parent.
_EACH_PARENT = """<?xml version="1.0"?>
<opnsense>
  <system><hostname>fw</hostname></system>
  <interfaces>
    <lan><if>igb1</if><enable>1</enable><ipaddr>192.0.2.1</ipaddr><subnet>26</subnet></lan>
  </interfaces>
  <laggs>
    <lagg><members>igb4,igb5</members><laggif>lagg0</laggif><proto>lacp</proto></lagg>
  </laggs>
  <bridges>
    <bridged><members>lan</members><bridgeif>bridge0</bridgeif></bridged>
  </bridges>
  <vlans version="1.0.0">
    <vlan uuid="fakeuuid-0001"><if>igb2</if><tag>20</tag><pcp>0</pcp><proto/>
      <descr/><vlanif>vlan01</vlanif></vlan>
    <vlan uuid="fakeuuid-0002"><if>lagg0</if><tag>30</tag><pcp>0</pcp><proto/>
      <descr/><vlanif>vlan02</vlanif></vlan>
    <vlan uuid="fakeuuid-0003"><if>igc0</if><tag>40</tag><pcp>0</pcp><proto/>
      <descr/><vlanif>vlan03</vlanif></vlan>
    <vlan uuid="fakeuuid-0004"><if>bridge0</if><tag>50</tag><pcp>0</pcp><proto/>
      <descr/><vlanif>vlan04</vlanif></vlan>
    <vlan uuid="fakeuuid-0005"><if>bridge1</if><tag>55</tag><pcp>0</pcp><proto/>
      <descr/><vlanif>vlan05</vlanif></vlan>
    <vlan uuid="fakeuuid-0006"><if>igb3</if><tag>60</tag><pcp>0</pcp><proto>802.1q</proto>
      <descr/><vlanif>vlan06</vlanif></vlan>
    <vlan uuid="fakeuuid-0007"><if>vlan06</if><tag>65</tag><pcp>0</pcp><proto>802.1q</proto>
      <descr/><vlanif>vlan06.65</vlanif></vlan>
    <vlan uuid="fakeuuid-0008"><if>vlan0.99</if><tag>70</tag><pcp>0</pcp><proto/>
      <descr/><vlanif>vlan07</vlanif></vlan>
    <vlan uuid="fakeuuid-0009"><if>lan</if><tag>80</tag><pcp>0</pcp><proto/>
      <descr/><vlanif>vlan08</vlanif></vlan>
    <vlan uuid="fakeuuid-0010"><if>opt3</if><tag>85</tag><pcp>0</pcp><proto/>
      <descr/><vlanif>vlan09</vlanif></vlan>
  </vlans>
</opnsense>
"""

#: Devices on ports and on a LAGG, with what each zone gives them: a
#: zone with a description of its own, a zone with none, and a device no
#: zone assigns.
_ON_PORTS = """<?xml version="1.0"?>
<opnsense>
  <system><hostname>fw</hostname></system>
  <interfaces>
    <lan><if>igb1</if><descr>LAN</descr><enable>1</enable><ipaddr>192.0.2.1</ipaddr><subnet>26</subnet></lan>
    <opt1><if>vlan01</if><descr>GUEST</descr><enable>1</enable><ipaddr>198.51.100.1</ipaddr><subnet>26</subnet></opt1>
    <opt2><if>igb2_vlan30</if><enable>1</enable><ipaddr>198.51.100.65</ipaddr><subnet>26</subnet></opt2>
    <opt3><if>vlan0.40</if><enable>1</enable><ipaddr>198.51.100.129</ipaddr><subnet>26</subnet></opt3>
  </interfaces>
  <laggs>
    <lagg><members>igb4,igb5</members><laggif>lagg0</laggif><proto>lacp</proto></lagg>
  </laggs>
  <vlans version="1.0.0">
    <vlan uuid="fakeuuid-0001"><if>igb2</if><tag>20</tag><pcp>0</pcp><proto/>
      <descr>Guest</descr><vlanif>vlan01</vlanif></vlan>
    <vlan uuid="fakeuuid-0002"><if>igb2</if><tag>30</tag><pcp>0</pcp><proto/>
      <descr>Cameras</descr><vlanif>igb2_vlan30</vlanif></vlan>
    <vlan uuid="fakeuuid-0003"><if>lagg0</if><tag>40</tag><pcp>0</pcp><proto/>
      <descr/><vlanif>vlan0.40</vlanif></vlan>
    <vlan uuid="fakeuuid-0004"><if>igb1</if><tag>50</tag><pcp>0</pcp><proto/>
      <descr>Spare</descr><vlanif>vlan02</vlanif></vlan>
  </vlans>
</opnsense>
"""

#: What the capture states (its ``<vlans>`` read by hand): five devices
#: on ``ixl0``, each with a ``<descr>`` beside its zone's own.
_SUPERGATE_DEVICES = {
    "vlan0.10": 10, "vlan0.11": 11, "vlan0.20": 20, "vlan0.100": 100, "vlan0.150": 150,
}

#: Targets that have no form for a sub-interface's tag (its
#: ``/interfaces/interface/dot1q-vlan`` is unsupported there).  Typed
#: by hand, and compared with what the jobs report.
_NO_FORM_FOR_THE_TAG = {"aruba_aoscx", "aruba_aoss", "cisco_iosxe", "dell_os10"}


def _job(target: str, text: str = _ON_PORTS, port_rename_map: dict | None = None):
    return run_plan_with_checked_names(
        get_codec("opnsense"), get_codec(target), text,
        port_rename_map=port_rename_map or {},
    )


def _devices(xml: str) -> dict[str, tuple[str, str, str]]:
    """``{<vlanif>: (<if>, <tag>, <descr>)}`` of an OPNsense output."""
    return {
        (vlan.findtext("vlanif") or "").strip(): (
            (vlan.findtext("if") or "").strip(),
            (vlan.findtext("tag") or "").strip(),
            (vlan.findtext("descr") or "").strip(),
        )
        for vlan in ET.fromstring(xml).findall("./vlans/vlan")
    }


def _zones(xml: str) -> dict[str, str]:
    """``{zone <if>: zone <descr>}`` of an OPNsense output."""
    return {
        (zone.findtext("if") or "").strip(): (zone.findtext("descr") or "").strip()
        for zone in ET.fromstring(xml).findall("./interfaces/*")
    }


class TestWhatTheParserReads:
    @pytest.mark.parametrize(
        ("name", "interface_type", "tag", "parent"),
        [
            # A port whose name says it is one.
            ("vlan01", "ianaift:ethernetCsmacd", 20, "igb2"),
            # A LAGG <laggs> names.
            ("vlan02", "ianaift:ieee8023adLag", 30, "lagg0"),
            # A port whose name the classifier does not read.
            ("vlan03", "ianaift:ethernetCsmacd", 40, "igc0"),
            # A bridge <bridges> names, and one named as a bridge is.
            ("vlan04", "ianaift:l3ipvlan", None, "bridge0"),
            ("vlan05", "ianaift:l3ipvlan", None, "bridge1"),
            # A device another rides on, its <proto> stated 802.1q, is on
            # a port; the one on it is on a VLAN device.
            ("vlan06", "ianaift:ethernetCsmacd", 60, "igb3"),
            ("vlan06.65", "ianaift:l3ipvlan", None, "vlan06"),
            # A name that says it is a VLAN interface.
            ("vlan07", "ianaift:l3ipvlan", None, "vlan0.99"),
            # A zone's key, which is no device.
            ("vlan08", "ianaift:l3ipvlan", None, "lan"),
            ("vlan09", "ianaift:l3ipvlan", None, "opt3"),
        ],
    )
    def test_each_parent(self, name: str, interface_type: str, tag, parent: str) -> None:
        tree = get_codec("opnsense").parse(_EACH_PARENT)
        iface = next(i for i in tree.interfaces if i.name == name)
        assert (iface.interface_type, iface.dot1q_vlan, iface.vlan_parent) == (
            interface_type, tag, parent,
        )

    def test_a_sub_interface_is_no_vlan(self) -> None:
        tree = get_codec("opnsense").parse(_EACH_PARENT)
        assert sorted((v.id, v.name) for v in tree.vlans) == [
            (50, "vlan04"), (55, "vlan05"), (65, "vlan06.65"), (70, "vlan07"),
            (80, "vlan08"), (85, "vlan09"),
        ]

    def test_the_description_is_the_zones_then_the_devices(self) -> None:
        tree = get_codec("opnsense").parse(_ON_PORTS)
        described = {i.name: i.description for i in tree.interfaces}
        # The zone's own; the device's where the zone has none, or where
        # no zone assigns it.
        assert described["vlan01"] == "GUEST"
        assert described["igb2_vlan30"] == "Cameras"
        assert described["vlan02"] == "Spare"
        # The device's own beside the zone's is said.
        rows = [r for r in tree.dropped_tier3_sections if "<descr> of its own" in r]
        assert rows == [
            "<vlans><vlan> vlan01: a <descr> of its own beside its zone's -- "
            "the VLAN device's description is not translated",
        ]

    def test_the_capture(self) -> None:
        tree = get_codec("opnsense").parse(_SUPERGATE.read_text(encoding="utf-8"))
        held = {
            i.name: (i.interface_type, i.dot1q_vlan, i.vlan_parent)
            for i in tree.interfaces if i.name in _SUPERGATE_DEVICES
        }
        assert held == {
            name: ("ianaift:ethernetCsmacd", tag, "ixl0")
            for name, tag in _SUPERGATE_DEVICES.items()
        }
        assert tree.vlans == []
        said = sorted(
            r.split(":")[0].removeprefix("<vlans><vlan> ")
            for r in tree.dropped_tier3_sections if "<descr> of its own" in r
        )
        assert said == sorted(_SUPERGATE_DEVICES)


class TestOntoAnotherVendor:
    def test_eos(self) -> None:
        job = _job("arista_eos")
        assert job.status == MigrationJobStatus.completed, job.error
        renames = job.port_renames
        port, lagg = renames["igb2"], renames["lagg0"]
        for block in (
            f"interface {port}.20\n   description GUEST\n   encapsulation dot1q vlan 20\n"
            "   ip address 198.51.100.1/26\n",
            f"interface {port}.30\n   description Cameras\n   encapsulation dot1q vlan 30\n"
            "   ip address 198.51.100.65/26\n",
            f"interface {lagg}.40\n   encapsulation dot1q vlan 40\n"
            "   ip address 198.51.100.129/26\n",
            f"interface {renames['igb1']}.50\n   description Spare\n   encapsulation dot1q vlan 50\n",
        ):
            assert block in job.rendered
        lines = job.rendered.splitlines()
        assert not [line for line in lines if line.startswith(("vlan ", "interface Vlan"))]

    def test_the_reading_as_it_was_is_seen(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every device a VLAN interface and a VLAN: the check above
        finds the VLAN and its interface."""
        monkeypatch.setattr(opn_parse, "_port_type_of", lambda *args: None)
        lines = _job("arista_eos").rendered.splitlines()
        assert [line for line in lines if line.startswith(("vlan ", "interface Vlan"))]

    def test_junos(self) -> None:
        job = _job("juniper_junos")
        assert job.status == MigrationJobStatus.completed, job.error
        lines = set(job.rendered.splitlines())
        port = job.port_renames["igb2"]
        for tag, address in ((20, "198.51.100.1/26"), (30, "198.51.100.65/26")):
            assert f"set interfaces {port} unit {tag} vlan-id {tag}" in lines
            assert f"set interfaces {port} unit {tag} family inet address {address}" in lines
        assert f"set interfaces {port} vlan-tagging" in lines
        assert not [line for line in lines if line.startswith(("set vlans", "set interfaces irb"))]

    def test_a_port_the_classifier_does_not_read_is_said_until_it_is_named(self) -> None:
        """``igc0`` is no name the classifier reads: the device went where
        it went, under it, and the job says so.  An entry for the port
        takes the sub-interface with it."""
        text = _ON_PORTS.replace("<if>igb2</if><tag>20</tag>", "<if>igc0</if><tag>20</tag>")
        job = _job("arista_eos", text)
        assert job.status == MigrationJobStatus.partial
        assert "vlan01" in job.untranslated_ports
        job = _job("arista_eos", text, {"igc0": "Ethernet7"})
        assert job.status == MigrationJobStatus.completed, job.error
        assert (
            "interface Ethernet7.20\n   description GUEST\n   encapsulation dot1q vlan 20\n"
            "   ip address 198.51.100.1/26\n" in job.rendered
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
        for target in set(list_public_codecs()) - _NO_FORM_FOR_THE_TAG:
            job = _job(target)
            assert job.status == MigrationJobStatus.completed, (target, job.error)
            assert job.untranslated_ports == [], target


class TestBetweenTwoOPNsenseConfigs:
    def test_each_device_stands(self) -> None:
        job = _job("opnsense")
        assert job.status == MigrationJobStatus.completed, job.error
        devices = _devices(job.rendered)
        assert {name: d[:2] for name, d in devices.items()} == {
            "vlan01": ("igb2", "20"), "igb2_vlan30": ("igb2", "30"),
            "vlan0.40": ("lagg0", "40"), "vlan02": ("igb1", "50"),
        }

    def test_a_device_no_zone_assigns_keeps_its_description_and_gets_no_zone(self) -> None:
        job = _job("opnsense")
        assert _devices(job.rendered)["vlan02"][2] == "Spare"
        assert "vlan02" not in _zones(job.rendered)


def test_another_vendors_sub_interface_with_a_description_alone() -> None:
    """A sub-interface that holds a description and nothing else is a
    device whose ``<descr>`` is the description, and no zone: a zone
    would assign it, and enable it, on the target.  Read back, it is the
    same sub-interface."""
    text = (
        "hostname r1\ninterface GigabitEthernet0/0/2\n no switchport\n!\n"
        "interface GigabitEthernet0/0/2.100\n description users\n encapsulation dot1Q 200\n!\n"
    )
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec("opnsense"), text, port_rename_map={},
    )
    port = job.port_renames["GigabitEthernet0/0/2"]
    name = job.port_renames["GigabitEthernet0/0/2.100"]
    assert _devices(job.rendered)[name] == (port, "200", "users")
    assert name not in _zones(job.rendered)
    back = next(i for i in get_codec("opnsense").parse(job.rendered).interfaces if i.name == name)
    assert (back.dot1q_vlan, back.vlan_parent, back.description) == (200, port, "users")
