# VLAN configuration: MikroTik RouterOS versus OPNsense

## MikroTik RouterOS

Sources:
- [VLAN — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN)
- [Basic VLAN switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching)

Retrieved: 2026-04-30

RouterOS splits VLAN modeling across **two unrelated planes**:

### Plane 1: `/interface vlan` (router-on-a-stick)

```
/interface vlan
add comment="Users VLAN" interface=bridge1 name=vlan100 vlan-id=100
add comment="Voice VLAN" interface=bridge1 name=vlan200 vlan-id=200

/ip address
add address=10.100.0.1/24 interface=vlan100
add address=10.200.0.1/24 interface=vlan200
```

Each ``/interface vlan`` line creates a tagged sub-interface bound to
ONE parent (``interface=bridge1``).  This is the routed-VLAN form —
similar to Linux ``vlan100@eth1`` 802.1Q sub-interfaces.

### Plane 2: bridge VLAN filtering (switching model)

```
/interface bridge
add name=bridge1 vlan-filtering=yes

/interface bridge port
add bridge=bridge1 interface=ether2 pvid=10
add bridge=bridge1 interface=ether3

/interface bridge vlan
add bridge=bridge1 vlan-ids=10 untagged=ether2 tagged=ether3
add bridge=bridge1 vlan-ids=20,30 tagged=ether3
```

Only enabled when ``vlan-filtering=yes`` on the bridge.  Each
``/interface bridge vlan`` row is a VLAN-centric membership
declaration — which conveniently matches the canonical VLAN-centric
port-list shape.  RouterOS does NOT model VLAN ``description`` as a
first-class field on either plane; operators stash names in
``/interface vlan name=`` (Plane 1) or in port ``comment=`` fields
(Plane 2).

## OPNsense

Source: [OPNsense Devices manual (VLAN tab)](https://docs.opnsense.org/manual/other-interfaces.html)

Retrieved: 2026-04-30

```xml
<vlans>
  <vlan uuid="...">
    <if>em1</if>
    <tag>10</tag>
    <pcp>0</pcp>
    <descr>USER VLAN</descr>
    <vlanif>vlan0.10</vlanif>
  </vlan>
  <vlan uuid="...">
    <if>em1</if>
    <tag>20</tag>
    <pcp>0</pcp>
    <descr>VOICE VLAN</descr>
    <vlanif>vlan0.20</vlanif>
  </vlan>
</vlans>
```

OPNsense models a VLAN as a **single tagged sub-interface on ONE
parent NIC**:

- ``<if>`` is the parent BSD device (``em1``).
- ``<tag>`` is the 802.1Q VLAN id.
- ``<descr>`` is the operator-friendly label.  An OPNsense ``<vlan>``
  has no name of its own; Netcanon reads ``<descr>`` as the VLAN's
  description.
- ``<vlanif>`` is the auto-generated FreeBSD child device name
  (``vlan0.10``).

Crucially, OPNsense has **no VLAN-centric port-membership model**.
There is no list of "ports tagged for VLAN 10" — only one parent
NIC per VLAN.  L3 addressing on a VLAN happens by assigning the
``<vlanif>`` (e.g. ``vlan0.20``) to a zone (``<opt2>``) and putting
the address on the zone (``<opt2><ipaddr>...``).

## Cross-vendor mapping

The canonical surface is

```
CanonicalVlan(id, name, description, tagged_ports[], untagged_ports[],
              ipv4_addresses[])
CanonicalInterface(switchport_mode, access_vlan, trunk_allowed_vlans,
                   trunk_native_vlan, voice_vlan)
```

### vlans[].id

RouterOS ``vlan-id=10`` ↔ OPNsense ``<tag>10</tag>``.  Both vendors
share the 1-4094 range.  Round-trips cleanly.

### vlans[].name / vlans[].description

RouterOS conflates the L3 interface name (``vlan10``) with the
descriptive VLAN name on Plane 1 (per the MikroTik codec's
``LossyPath`` on ``/vlans/vlan/name``): a RouterOS VLAN is named
after its interface (``vlan100``).  The OPNsense render writes that
interface as the VLAN's ``<vlan>`` device under the same name
(``<vlanif>vlan100</vlanif>``), on the parent the config states, and
the OPNsense parser names a VLAN after its device, so the name comes
back.  But not in a form OPNsense takes: its VLAN form refuses a
device name other than ``vlan0`` followed by digits and dots, or
``<parent>_vlan<id>``, when the VLAN is saved, and the render says
so in a ``<!-- review: -->`` comment beside each such device.
``name`` is recorded **lossy** for that.

The description comes back unchanged: the RouterOS parser takes a
VLAN's description from its interface's ``comment``, the OPNsense
render writes it as the device's ``<descr>``, and the OPNsense parser
reads ``<descr>`` as the VLAN's description.

### vlans[].tagged_ports / vlans[].untagged_ports

OPNsense has no VLAN-centric port-membership model.  Even if the
RouterOS codec successfully populates the lists from Plane-2 (bridge
VLAN filtering) parse, the OPNsense render emits no port-membership
XML.  Operators reconstruct trunk topology manually by assigning
each ``<vlan>`` element to an OPNsense zone.

### vlans[].ipv4_addresses

RouterOS ``/interface vlan name=vlan100`` + ``/ip address add
address=X interface=vlan100`` (SVI absorption) has no first-class
OPNsense equivalent.  The OPNsense pattern is to assign the VLAN
sub-interface to a zone (``<opt2>``) and put the address on the
zone.  The render writes the VLAN interface as a zone whose
``<if>`` is the VLAN device written under its name (``vlan100``),
with the address on the zone; read back, the address is on that
interface record, not on the VLAN.

### interfaces[] switchport fields

OPNsense has no switching fabric.  RouterOS-side switchport state
(synthesised from Plane-2 bridge-port pvid= + bridge-vlan rows) drops
on render because there is no per-port allowed-VLAN list, no access /
trunk mode toggle, and no LLDP-MED voice VLAN concept on OPNsense.

### Disposition

| Field | Disposition |
|---|---|
| `vlans[].id` | good |
| `vlans[].name` | lossy (comes back as the device name, which OPNsense's VLAN form refuses; a review comment says so) |
| `vlans[].description` | good (`comment` ↔ `<descr>`) |
| `vlans[].tagged_ports` | unsupported (no OPNsense per-port model) |
| `vlans[].untagged_ports` | unsupported (no OPNsense per-port model) |
| `vlans[].ipv4_addresses` | lossy (no first-class OPNsense SVI; the address is on the zone) |
| `interfaces[].switchport_mode` | unsupported (OPNsense not a switch) |
| `interfaces[].access_vlan` | unsupported |
| `interfaces[].trunk_allowed_vlans` | unsupported |
| `interfaces[].trunk_native_vlan` | unsupported |
| `interfaces[].voice_vlan` | unsupported |
