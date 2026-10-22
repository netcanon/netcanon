# VLAN configuration: OPNsense versus MikroTik RouterOS

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

- ``<if>`` — parent BSD device.
- ``<tag>`` — 802.1Q VLAN id.
- ``<descr>`` — operator-friendly label (lands in canonical
  ``description`` per ``parse.py``; a ``<vlan>`` has no name of its
  own, so the parser names the canonical VLAN after its
  ``<vlanif>``).
- ``<vlanif>`` — auto-generated child device name (``vlan0.10``).

OPNsense has **no VLAN-centric port-membership model** and **no
first-class SVI** — L3 addressing on a VLAN happens by assigning
the ``<vlanif>`` child to a zone (``<opt2>``) and putting the
address on the zone.

## MikroTik RouterOS

Sources:
- [VLAN — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN)
- [Basic VLAN switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching)

Retrieved: 2026-04-30

RouterOS splits VLAN modeling across **two unrelated planes**:

### Plane 1: `/interface vlan` (router-on-a-stick)

```
/interface vlan
add comment="Users VLAN" interface=bridge1 name=vlan10 vlan-id=10

/ip address
add address=10.10.10.1/24 interface=vlan10
```

Tagged sub-interface bound to ONE parent — closely matches OPNsense's
"VLAN as one tagged sub-interface on one parent" model.

### Plane 2: bridge VLAN filtering (switching model)

```
/interface bridge
add name=bridge1 vlan-filtering=yes

/interface bridge vlan
add bridge=bridge1 vlan-ids=10 untagged=ether2 tagged=ether3
```

VLAN-centric port-membership for switching deployments.  OPNsense
source NEVER populates the canonical ``tagged_ports`` /
``untagged_ports`` lists, so RouterOS Plane-2 render emits no port-
membership rows from this source.

## Cross-vendor mapping

Canonical surface:

```
CanonicalVlan(id, name, description, tagged_ports[], untagged_ports[],
              ipv4_addresses[])
CanonicalInterface(switchport_mode, access_vlan, trunk_allowed_vlans,
                   trunk_native_vlan, voice_vlan)
```

### vlans[].id

OPNsense ``<vlan>/<tag>10</tag>`` ↔ RouterOS ``vlan-id=10``.  Both
vendors share the 1-4094 range.  Round-trips cleanly.

### vlans[].name / vlans[].description

The OPNsense parser names the canonical VLAN after its device
(``<vlanif>``, e.g. ``vlan0.10``) and reads ``<descr>``
(``USER VLAN``) as its ``description``.  The name round-trips:
RouterOS writes it as the Plane 1 VLAN interface's
``name=vlan0.10`` and reads it back.  The description is lost:
RouterOS has one ``comment=`` for a VLAN interface, which the render
gives the interface's own description (the zone's, e.g.
``comment="Voice VLAN gateway"``), so the VLAN's label does not
reach the output.
RouterOS declares ``/vlans/vlan/description`` lossy, which the
validation report lists for each VLAN.

### vlans[].tagged_ports / vlans[].untagged_ports

OPNsense never populates these lists — no VLAN-centric port-
membership concept.  RouterOS Plane-2 (bridge VLAN filtering) render
emits no port-membership rows from this source.  Operators
reconstruct switching topology manually post-migration if needed.

### vlans[].ipv4_addresses

OPNsense's L3 face of a VLAN tag is the zone owning the ``<vlanif>``
device, not a first-class SVI on the VLAN itself.  The OPNsense
parser does not populate ``CanonicalVlan.ipv4_addresses``: it puts
the zone's address on the zone's interface record, named after the
device, which the RouterOS target writes as an address of that
interface (``add address=192.168.20.1/24 interface=vlan0.20`` on the
kitchen sink).  The address reaches the output; the VLAN record holds
none.

### interfaces[] switchport fields

OPNsense source never populates switchport_mode / access_vlan /
trunk_allowed_vlans / trunk_native_vlan / voice_vlan — there's no
switching fabric to model.  RouterOS-target Plane-2 render emits no
bridge VLAN filtering config from this source.

### Disposition

| Field | Disposition |
|---|---|
| `vlans[].id` | good |
| `vlans[].name` | good (OPNsense device `vlan0.10` → RouterOS Plane 1 `name=`) |
| `vlans[].description` | lossy (OPNsense `<descr>` has no line; the one `comment=` holds the interface's own description) |
| `vlans[].tagged_ports` | not_applicable (OPNsense never populates) |
| `vlans[].untagged_ports` | not_applicable (OPNsense never populates) |
| `vlans[].ipv4_addresses` | lossy (OPNsense parse wire-up pending; SVI absorption not synthesised) |
| `interfaces[].switchport_mode` | not_applicable |
| `interfaces[].access_vlan` | not_applicable |
| `interfaces[].trunk_allowed_vlans` | not_applicable |
| `interfaces[].trunk_native_vlan` | not_applicable |
| `interfaces[].voice_vlan` | not_applicable |
