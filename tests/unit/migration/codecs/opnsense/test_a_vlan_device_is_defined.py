"""A VLAN device is defined where a zone names it, on its own parent and tag.

An OPNsense ``<vlan>`` is a VLAN DEVICE (core ``Vlan.xml``): ``<if>`` the
device it rides on, ``<tag>``, ``<pcp>``, ``<proto>``, ``<descr>``, and
``<vlanif>`` the device's own name, which a zone's ``<if>`` assigns.
OPNsense names a device itself (``vlan01``, ``vlan02`` ... or, on older
configs, ``<parent>_vlan<tag>``) or takes a typed ``vlan0`` and digits and
dots (``Vlan.php``), so the digits of a device's name are not its tag.

The parser read a ``<vlan>`` for its tag and its ``<descr>`` alone, and the
renderer wrote every VLAN as ``<parent>_vlan<tag>`` on a parent it chose.
So every zone on a VLAN named a device the output did not define, and the
committed capture's five VLANs came out on its WAN port, in a job from
OPNsense to OPNsense that said ``completed``.  Onto RouterOS and FortiOS
the tag of ``vlan01`` was read from its name: VLAN 1.

What each input STATES is typed here by hand, from the vendor's grammar
and from the capture's own lines; the outputs are read by readers of this
module (the standard library's XML reader, and a few lines of text for
RouterOS and FortiOS), not by the codecs' parsers.  Each check is handed
an output with the defect it is for, and has to fail.

See also: ``docs/vendors/opnsense.md`` ("VLAN devices"),
``netcanon/migration/codecs/opnsense/parse.py::_parse_vlan_devices``.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names

_ROOT = Path(__file__).resolve().parents[5]
_SUPERGATE = (
    _ROOT / "tests" / "fixtures" / "real" / "opnsense"
    / "user_contrib_supergate_opn25.xml"
)

# Two VLAN devices on igb2, each assigned to a zone with an address --
# one named as OPNsense names a new device, one in the legacy form -- and
# a third that no zone assigns.
HAND = """<?xml version="1.0"?>
<opnsense>
  <system><hostname>fw</hostname></system>
  <interfaces>
    <wan><if>igb0</if><descr>WAN</descr><enable>1</enable><ipaddr>203.0.113.2</ipaddr><subnet>30</subnet></wan>
    <lan><if>igb1</if><descr>LAN</descr><enable>1</enable><ipaddr>192.0.2.1</ipaddr><subnet>26</subnet></lan>
    <opt1><if>igb2</if><descr>DMZ</descr><enable>1</enable><ipaddr>192.0.2.65</ipaddr><subnet>26</subnet></opt1>
    <opt2><if>vlan01</if><descr>GUEST</descr><enable>1</enable><ipaddr>198.51.100.1</ipaddr><subnet>26</subnet></opt2>
    <opt3><if>igb2_vlan30</if><descr>CAMS</descr><enable>1</enable><ipaddr>198.51.100.65</ipaddr><subnet>26</subnet></opt3>
  </interfaces>
  <vlans version="1.0.0">
    <vlan uuid="fakeuuid-0001"><if>igb2</if><tag>20</tag><pcp>0</pcp><proto/>
      <descr>Guest</descr><vlanif>vlan01</vlanif></vlan>
    <vlan uuid="fakeuuid-0002"><if>igb2</if><tag>30</tag><pcp>0</pcp><proto/>
      <descr>Cameras</descr><vlanif>igb2_vlan30</vlanif></vlan>
    <vlan uuid="fakeuuid-0003"><if>igb2</if><tag>40</tag><pcp>0</pcp><proto/>
      <descr>Spare</descr><vlanif>vlan02</vlanif></vlan>
  </vlans>
</opnsense>
"""

#: What HAND states: each device's parent and tag, and which have a zone.
HAND_DEVICES = {
    "vlan01": ("igb2", "20"),
    "igb2_vlan30": ("igb2", "30"),
    "vlan02": ("igb2", "40"),
}
HAND_ZONED = {"vlan01", "igb2_vlan30"}

#: What the capture states (its ``<vlans>`` and ``<interfaces>``, read by
#: hand): five devices on ixl0, each assigned to a zone.
SUPERGATE_DEVICES = {
    "vlan0.10": ("ixl0", "10"),
    "vlan0.100": ("ixl0", "100"),
    "vlan0.11": ("ixl0", "11"),
    "vlan0.20": ("ixl0", "20"),
    "vlan0.150": ("ixl0", "150"),
}
SUPERGATE_ZONED = set(SUPERGATE_DEVICES)

# An 802.1ad (QinQ) pair: an outer device whose <proto> is blank, which
# OPNsense sends as 802.1ad because another VLAN rides on it
# (interfaces.inc, interfaces_vlan_configure), and the inner device on it,
# named as Vlan.php requires on a parent whose name holds "vlan".  And a
# device with a priority other than 0.
QINQ = """<?xml version="1.0"?>
<opnsense>
  <system><hostname>fw</hostname></system>
  <interfaces>
    <wan><if>igb0</if><enable>1</enable><ipaddr>203.0.113.2</ipaddr><subnet>30</subnet></wan>
    <lan><if>igb1</if><enable>1</enable><ipaddr>192.0.2.1</ipaddr><subnet>26</subnet></lan>
    <opt1><if>vlan01</if><enable>1</enable><ipaddr>198.51.100.1</ipaddr><subnet>26</subnet></opt1>
    <opt2><if>qinq01</if><enable>1</enable><ipaddr>198.51.100.65</ipaddr><subnet>26</subnet></opt2>
    <opt3><if>vlan02</if><enable>1</enable><ipaddr>198.51.100.129</ipaddr><subnet>26</subnet></opt3>
  </interfaces>
  <vlans version="1.0.0">
    <vlan uuid="fakeuuid-0011"><if>igb1</if><tag>100</tag><pcp>0</pcp><proto/>
      <descr>outer</descr><vlanif>vlan01</vlanif></vlan>
    <vlan uuid="fakeuuid-0012"><if>vlan01</if><tag>200</tag><pcp>0</pcp><proto/>
      <descr>inner</descr><vlanif>qinq01</vlanif></vlan>
    <vlan uuid="fakeuuid-0013"><if>igb1</if><tag>300</tag><pcp>5</pcp><proto>802.1q</proto>
      <descr>voice</descr><vlanif>vlan02</vlanif></vlan>
  </vlans>
  <dhcpd>
    <opt2><enable/><range><from>198.51.100.70</from><to>198.51.100.90</to></range></opt2>
  </dhcpd>
</opnsense>
"""


# ---------------------------------------------------------------------------
# Readers of this module
# ---------------------------------------------------------------------------


def _opnsense_devices(xml: str) -> dict[str, tuple[str, str, str]]:
    """``{<vlanif>: (<if>, <tag>, <proto>)}`` of an OPNsense output."""
    root = ET.fromstring(xml)
    found: dict[str, tuple[str, str, str]] = {}
    for vlan in root.findall("./vlans/vlan"):
        found[(vlan.findtext("vlanif") or "").strip()] = (
            (vlan.findtext("if") or "").strip(),
            (vlan.findtext("tag") or "").strip(),
            (vlan.findtext("proto") or "").strip(),
        )
    return found


def _opnsense_zones(xml: str) -> dict[str, str]:
    """``{zone <if>: zone <ipaddr>}`` of an OPNsense output."""
    root = ET.fromstring(xml)
    return {
        (zone.findtext("if") or "").strip(): (zone.findtext("ipaddr") or "")
        for zone in root.findall("./interfaces/*")
    }


def _routeros_by_address(text: str) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """``({address: interface}, {vlan name: (parent, vlan-id)})`` of a
    RouterOS output, read from its ``/ip address`` and ``/interface vlan``
    lines."""
    def value(line: str, key: str) -> str:
        m = re.search(rf'(?:^|\s){key}=("[^"]*"|\S+)', line)
        return m.group(1).strip('"') if m else ""

    section = ""
    addresses: dict[str, str] = {}
    vlans: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("/"):
            section = line
            continue
        if not line.startswith("add "):
            continue
        if section == "/ip address":
            addresses[value(line, "address").split("/")[0]] = value(line, "interface")
        elif section == "/interface vlan":
            vlans[value(line, "name")] = (value(line, "interface"), value(line, "vlan-id"))
    return addresses, vlans


def _fortios_blocks(text: str) -> dict[str, dict[str, str]]:
    """``{edit name: {"ip", "vlanid", "interface"}}`` of the ``config
    system interface`` block of a FortiOS output."""
    blocks: dict[str, dict[str, str]] = {}
    inside = False
    current: dict[str, str] | None = None
    for line in text.splitlines():
        s = line.strip()
        if s == "config system interface":
            inside = True
            continue
        if not inside:
            continue
        if s == "end" and current is None:
            break
        m = re.fullmatch(r'edit "([^"]+)"', s)
        if m:
            current = blocks.setdefault(m.group(1), {})
            continue
        if s == "next":
            current = None
            continue
        if current is None:
            continue
        m = re.fullmatch(r"set ip (\S+) \S+", s)
        if m:
            current["ip"] = m.group(1)
        m = re.fullmatch(r"set vlanid (\d+)", s)
        if m:
            current["vlanid"] = m.group(1)
        m = re.fullmatch(r'set interface "([^"]+)"', s)
        if m:
            current["interface"] = m.group(1)
    return blocks


# ---------------------------------------------------------------------------
# Checks, each handed its defect below
# ---------------------------------------------------------------------------


def _check_opnsense(
    xml: str, devices: dict[str, tuple[str, str]], zoned: set[str],
) -> list[str]:
    """What is wrong with an OPNsense output of a config that states
    *devices*, *zoned* of them assigned to a zone."""
    problems: list[str] = []
    written = _opnsense_devices(xml)
    zones = _opnsense_zones(xml)
    for name, (parent, tag) in devices.items():
        if name not in written:
            problems.append(f"no <vlan> defines {name}")
        elif written[name][:2] != (parent, tag):
            problems.append(f"{name} is {written[name][:2]}, not {(parent, tag)}")
    for zone_if in zones:
        if (zone_if in devices or re.fullmatch(r"vlan\d.*|.*_vlan\d+", zone_if)) \
                and zone_if not in written:
            problems.append(f"a zone names {zone_if}, which no <vlan> defines")
    zoned_out = {name for name in zones if name in devices}
    if zoned_out != zoned:
        problems.append(f"the zones assign {sorted(zoned_out)}, not {sorted(zoned)}")
    return problems


def _check_routeros(text: str) -> list[str]:
    """HAND onto RouterOS: each VLAN interface found by its address has
    the tag HAND states, on the port that has igb2's address."""
    addresses, vlans = _routeros_by_address(text)
    parent = addresses.get("192.0.2.65", "")
    problems: list[str] = []
    for address, tag in (("198.51.100.1", "20"), ("198.51.100.65", "30")):
        name = addresses.get(address, "")
        if vlans.get(name) != (parent, tag):
            problems.append(f"{address} is on {name}: {vlans.get(name)}, not {(parent, tag)}")
    if (parent, "40") not in vlans.values():
        problems.append(f"no VLAN interface of tag 40 on {parent}")
    return problems


def _check_fortios(text: str) -> list[str]:
    """HAND onto FortiOS: the same, from its interface blocks."""
    blocks = _fortios_blocks(text)
    by_ip = {block.get("ip"): name for name, block in blocks.items()}
    parent = by_ip.get("192.0.2.65", "")
    problems: list[str] = []
    for address, tag in (("198.51.100.1", "20"), ("198.51.100.65", "30")):
        block = blocks.get(by_ip.get(address, ""), {})
        if (block.get("interface"), block.get("vlanid")) != (parent, tag):
            problems.append(f"{address}: {block}, not on {parent} with tag {tag}")
    if not any(
        (b.get("interface"), b.get("vlanid")) == (parent, "40") for b in blocks.values()
    ):
        problems.append(f"no VLAN interface of tag 40 on {parent}")
    return problems


def _run(source: str, target: str, text: str):
    return run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map={},
    )


# ---------------------------------------------------------------------------
# OPNsense to OPNsense
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "devices", "zoned"),
    [
        pytest.param(HAND, HAND_DEVICES, HAND_ZONED, id="hand"),
        pytest.param(None, SUPERGATE_DEVICES, SUPERGATE_ZONED, id="supergate"),
    ],
)
def test_each_device_keeps_its_parent_and_its_tag(text, devices, zoned):
    text = text if text is not None else _SUPERGATE.read_text(encoding="utf-8")
    job = _run("opnsense", "opnsense", text)
    assert _check_opnsense(job.rendered, devices, zoned) == []
    # And each zone keeps its address on the device it names.
    zones = _opnsense_zones(job.rendered)
    source_zones = _opnsense_zones(text)
    for name in zoned:
        assert zones[name] == source_zones[name], name


def test_a_device_no_zone_assigns_is_given_no_zone():
    job = _run("opnsense", "opnsense", HAND)
    assert "vlan02" in _opnsense_devices(job.rendered)
    assert "vlan02" not in _opnsense_zones(job.rendered)


# ---------------------------------------------------------------------------
# Onto RouterOS and FortiOS
# ---------------------------------------------------------------------------


def test_onto_routeros_each_tag_is_the_one_the_vlan_states():
    assert _check_routeros(_run("opnsense", "mikrotik_routeros", HAND).rendered) == []


def test_onto_fortios_each_tag_is_the_one_the_vlan_states():
    assert _check_fortios(_run("opnsense", "fortigate_cli", HAND).rendered) == []


# ---------------------------------------------------------------------------
# What is not one 802.1Q tag is left out, and said
# ---------------------------------------------------------------------------


def test_an_8021ad_pair_is_left_out_and_said():
    job = _run("opnsense", "opnsense", QINQ)
    written = _opnsense_devices(job.rendered)
    zones = _opnsense_zones(job.rendered)
    assert "vlan01" not in written and "qinq01" not in written
    assert "vlan01" not in zones and "qinq01" not in zones
    # Nothing of theirs is written as an 802.1Q tag, or as an address.
    assert "<tag>100</tag>" not in job.rendered
    assert "<tag>200</tag>" not in job.rendered
    assert "198.51.100.1<" not in job.rendered
    assert "198.51.100.65" not in job.rendered
    # The pool on the inner device goes with it.
    assert "198.51.100.70" not in job.rendered
    rows = job.dropped_tier3_sections
    assert any("vlan01" in r and "802.1ad" in r for r in rows), rows
    assert any("qinq01" in r and "rides on vlan01" in r for r in rows), rows
    assert any("<dhcpd><opt2>" in r for r in rows), rows
    # The device whose priority is not 0 is kept, and its priority said.
    assert written["vlan02"][:2] == ("igb1", "300")
    assert any("vlan02" in r and "<pcp>" in r for r in rows), rows


def test_a_stated_8021ad_proto_is_left_out():
    text = HAND.replace(
        "<tag>20</tag><pcp>0</pcp><proto/>",
        "<tag>20</tag><pcp>0</pcp><proto>802.1ad</proto>",
    )
    job = _run("opnsense", "opnsense", text)
    assert "vlan01" not in _opnsense_devices(job.rendered)
    assert "198.51.100.1<" not in job.rendered
    assert any("vlan01" in r and "802.1ad" in r for r in job.dropped_tier3_sections)


def test_a_vlan_that_carries_a_device_is_written_8021q():
    """A VLAN interface that another rides on is written ``802.1q``:
    blank, OPNsense would send it as 802.1ad."""
    ros = """# by RouterOS 7.12
/interface ethernet
set [ find default-name=ether1 ] name=ether1
/interface vlan
add interface=ether1 name=vlan0.100 vlan-id=100
add interface=vlan0.100 name=vlan0.200 vlan-id=200
"""
    job = _run("mikrotik_routeros", "opnsense", ros)
    written = _opnsense_devices(job.rendered)
    outer = [v for v in written.values() if v[1] == "100"]
    assert outer and outer[0][2] == "802.1q", written


# ---------------------------------------------------------------------------
# Other vendors' VLAN interfaces onto OPNsense
# ---------------------------------------------------------------------------

_IOS = """hostname r1
!
vlan 10
 name USERS
!
vlan 20
 name GUEST
!
interface GigabitEthernet0/0/0
 ip address 203.0.113.2 255.255.255.252
!
interface GigabitEthernet0/0/1
 switchport mode trunk
 switchport trunk allowed vlan 10,20
!
interface Vlan10
 ip address 192.0.2.1 255.255.255.192
!
interface Vlan20
 ip address 198.51.100.1 255.255.255.192
!
end
"""

#: The device names OPNsense's VLAN form takes (``Vlan.php``) on a parent
#: whose name does not hold "vlan": ``vlan0`` and one to ten digits and
#: dots, or ``<parent>_vlan<tag>``.
_TAKEN = re.compile(r"vlan0[0-9.]{1,10}")


def test_an_svi_is_a_device_of_its_vlan_under_a_name_opnsense_takes():
    job = _run("cisco_iosxe_cli", "opnsense", _IOS)
    written = _opnsense_devices(job.rendered)
    zones = _opnsense_zones(job.rendered)
    for address, tag in (("192.0.2.1", "10"), ("198.51.100.1", "20")):
        name = next(n for n, a in zones.items() if a == address)
        assert name in written, (name, written)
        assert written[name][1] == tag
        parent = written[name][0]
        assert _TAKEN.fullmatch(name) or name == f"{parent}_vlan{tag}", name


_AOSCX = """hostname sw1
vlan 1
vlan 11
    name SERVERS
interface 1/1/1
    no shutdown
    no routing
    vlan trunk native 1
    vlan trunk allowed 11
interface vlan 11
    ip address 192.0.2.1/26
"""


def test_an_aoscx_svi_is_the_device_of_its_vlan():
    """AOS-CX names an SVI ``vlan 11``, with a space.  Read as the
    VLAN's interface, it is the device written for VLAN 11, so the zone
    for it names a device the output defines -- on the bare render, and
    on the plan path, where the translator renames the port first."""
    bare = get_codec("opnsense").render(get_codec("aruba_aoscx").parse(_AOSCX))
    for rendered in (bare, _run("aruba_aoscx", "opnsense", _AOSCX).rendered):
        written = _opnsense_devices(rendered)
        zones = _opnsense_zones(rendered)
        name = next(n for n, a in zones.items() if a == "192.0.2.1")
        assert name in written, (name, written)
        assert written[name][1] == "11"
        # One device for the tag: none of the legacy <parent>_vlan11 beside it.
        assert [n for n, d in written.items() if d[1] == "11"] == [name]


def test_a_name_opnsense_refuses_is_said_and_the_xml_stays_well_formed():
    """A RouterOS VLAN interface's free name is kept, with a review
    comment -- whose text holds ``--`` as the name does, broken apart,
    since XML refuses ``--`` in a comment."""
    ros = """# by RouterOS 7.12
/interface ethernet
set [ find default-name=ether1 ] name=ether1
/interface vlan
add interface=ether1 name=guest--net- vlan-id=20
/ip address
add address=198.51.100.1/26 interface=guest--net-
"""
    job = _run("mikrotik_routeros", "opnsense", ros)
    written = _opnsense_devices(job.rendered)  # parses: well-formed
    assert written["guest--net-"][1] == "20"
    assert "OPNsense's VLAN form refuses the device name guest- -net" in job.rendered


# ---------------------------------------------------------------------------
# Each check is handed the defect it is for
# ---------------------------------------------------------------------------


def test_the_opnsense_check_fails_on_each_defect():
    good = _run("opnsense", "opnsense", HAND).rendered
    assert _check_opnsense(good, HAND_DEVICES, HAND_ZONED) == []
    # The old renderer's output: every device named <parent>_vlan<tag>.
    renamed = good.replace("<vlanif>vlan01</vlanif>", "<vlanif>igb2_vlan20</vlanif>")
    assert _check_opnsense(renamed, HAND_DEVICES, HAND_ZONED)
    # Another parent.
    moved = good.replace("<if>igb2</if>\n      <tag>20</tag>", "<if>igb0</if>\n      <tag>20</tag>")
    assert moved != good
    assert _check_opnsense(moved, HAND_DEVICES, HAND_ZONED)
    # The tag read from the name.
    assert _check_opnsense(good.replace("<tag>20</tag>", "<tag>1</tag>"), HAND_DEVICES, HAND_ZONED)
    # A zone for the device no zone assigned.
    zoned = good.replace(
        "</interfaces>", "<opt9><if>vlan02</if><enable/></opt9></interfaces>",
    )
    assert _check_opnsense(zoned, HAND_DEVICES, HAND_ZONED)


def test_the_routeros_check_fails_on_each_defect():
    good = _run("opnsense", "mikrotik_routeros", HAND).rendered
    assert _check_routeros(good) == []
    assert "vlan-id=20" in good
    assert _check_routeros(good.replace("vlan-id=20", "vlan-id=1"))
    assert _check_routeros(good.replace("vlan-id=40", "vlan-id=4"))
    _, vlans = _routeros_by_address(good)
    parent = vlans["vlan01"][0]
    assert _check_routeros(good.replace(f"interface={parent} name=vlan01", "interface=ether9 name=vlan01"))


def test_the_fortios_check_fails_on_each_defect():
    good = _run("opnsense", "fortigate_cli", HAND).rendered
    assert _check_fortios(good) == []
    assert "set vlanid 20" in good
    assert _check_fortios(good.replace("set vlanid 20", "set vlanid 1"))
    assert _check_fortios(good.replace("set vlanid 40", "set vlanid 4"))
    blocks = _fortios_blocks(good)
    parent = blocks["vlan01"]["interface"]
    assert _check_fortios(good.replace(f'set interface "{parent}"', 'set interface "port9"', 1))
