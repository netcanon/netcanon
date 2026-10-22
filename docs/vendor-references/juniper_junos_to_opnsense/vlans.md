# VLANs and switchport membership: Junos versus OPNsense

How VLAN definitions, port membership, and SVI L3 are declared on
each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html (retrieved 2026-05-01)
- OPNsense: https://docs.opnsense.org/manual/other-interfaces.html (retrieved 2026-04-30)

## Junos form

Name-keyed VLAN definitions; per-interface membership lives on the
`family ethernet-switching` surface:

```
set vlans USERS vlan-id 100
set vlans USERS description "User VLAN"
set vlans USERS l3-interface irb.100

set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members USERS

set interfaces ge-0/0/24 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/24 unit 0 family ethernet-switching vlan members [ USERS VOICE ]
set interfaces ge-0/0/24 native-vlan-id 1
```

The SVI is a separate IRB unit:

```
set interfaces irb unit 100 family inet address 192.168.10.1/24
```

VLAN names allow letters, digits, hyphens, periods only (no
underscores, up to 255 chars).  Junos VLANs also support VXLAN
binding (`set vlans NAME vxlan vni N`) — see
`vxlan_evpn_unsupported.md`.

## OPNsense form

OPNsense models VLANs as per-tag sub-interfaces on a parent NIC.
A VLAN exists only AS a tagged sub-interface — there is NO
VLAN-centric port-membership model.

```xml
<vlans>
  <vlan uuid="...">
    <if>em1</if>
    <tag>100</tag>
    <pcp>0</pcp>
    <descr>USERS VLAN</descr>
    <vlanif>vlan0.100</vlanif>
  </vlan>
  <vlan uuid="...">
    <if>em1</if>
    <tag>200</tag>
    <pcp>0</pcp>
    <descr>VOICE VLAN</descr>
    <vlanif>vlan0.200</vlanif>
  </vlan>
</vlans>
```

To consume a VLAN's traffic, the operator assigns the synthesised
`<vlanif>` (e.g. `vlan0.100`) to a zone in `<interfaces>`:

```xml
<interfaces>
  <opt2>
    <if>vlan0.100</if>
    <descr>USERS gateway</descr>
    <enable>1</enable>
    <ipaddr>192.168.10.1</ipaddr>
    <subnet>24</subnet>
  </opt2>
</interfaces>
```

Key shape differences from Junos:

- A VLAN belongs to ONE parent NIC (`<if>em1</if>`) — there is no
  trunking concept where a VLAN appears on multiple ports.  All
  tags ride the parent NIC by virtue of being declared.
- "Untagged" traffic is the parent NIC's native (untagged) frames;
  not a per-port toggle.
- The L3 SVI lives on the zone (`<opt2>`) that consumes the
  `vlan0.100` interface, not on the VLAN itself.
- An OPNsense `<vlan>` has no name of its own; its `<descr>` is
  free-form text — no character-set restrictions.

## Cross-vendor mapping

Junos -> OPNsense:

* `vlans[].id`: **good** — Junos `vlan-id` ↔ OPNsense `<tag>`.  Both
  share the 1-4094 range.
* `vlans[].name`: **lossy** — the name does not come back.  The
  render writes each VLAN as a `<vlan>` device, under the name of
  the source's VLAN interface where there is one (`irb.100`),
  otherwise as `<parent>_vlan<id>` on a port that carries the VLAN
  or a default one (`xe-0/0/0_vlan2021`), and writes the Junos VLAN
  name as the device's `<descr>` where the VLAN has no description.
  The OPNsense parser names a VLAN after its device (`<vlanif>`) and
  reads `<descr>` as its description, so `TENANT_A_DATA` comes back
  as the description of a VLAN named `irb.100`.  A device name
  OPNsense's VLAN form would refuse (`irb.100`) gets a
  `<!-- review: -->` comment beside it.
* `vlans[].description`: **lossy** — a VLAN with no description
  gains one, its name (see `name`).  A Junos `description` on a VLAN
  is kept and its name lost: the render gives `<descr>` the
  description first.
* `vlans[].tagged_ports` / `untagged_ports`: **unsupported** —
  OPNsense has no VLAN-centric port-membership model.  Junos source
  populates these from per-interface `vlan members` and the canonical
  list carries them, but the OPNsense render emits no port-membership
  XML; operators reconstruct trunk topology manually by assigning
  each `<vlan>` to a zone.
* `vlans[].ipv4_addresses` (SVI absorption): **lossy** — Junos's `set
  vlans NAME l3-interface irb.100` plus `set interfaces irb unit 100
  family inet address X/N` lands on `CanonicalVlan.ipv4_addresses`.
  OPNsense's pattern is to put the address on the zone consuming the
  VLAN, not on the VLAN itself.  The render writes the IRB unit as a
  zone whose `<if>` is the VLAN device written under its name
  (`irb.100`), with the address on the zone; read back, the address
  is on that interface record, not on the VLAN.

Disposition: **lossy / unsupported** dominate due to the role
mismatch (Junos models richer L2 surface than OPNsense's
firewall-shaped wire-format expresses).
