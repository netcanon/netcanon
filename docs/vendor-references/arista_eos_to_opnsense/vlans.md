# VLANs: Arista EOS versus OPNsense

## Arista EOS

Source: [Arista EOS VLAN Configuration](https://www.arista.com/en/um-eos/eos-vlan-configuration)
Retrieved: 2026-05-01

Arista carries VLAN definitions and per-port assignments separately
(unlike Aruba's VLAN-centric stanza).  The canonical layer transposes
the per-interface `switchport access/trunk` lines into the VLAN's
port-membership lists during parse.

```
vlan 10
   name USERS
!
vlan 20
   name VOICE
!
vlan 100
   name TENANT_A_DATA
!
interface Ethernet2
   switchport mode access
   switchport access vlan 10
!
interface Ethernet3
   switchport mode trunk
   switchport trunk allowed vlan 10,20,100,200
!
interface Vlan100
   description "Tenant A data SVI"
   ip address 10.100.0.1/24
```

Arista VLAN notes:

- `vlan <id>` stanza carries `name <X>` (32-character truncation;
  no quoting required).
- VLAN IDs span 1-4094 (default 1, reserved range 1002-1005 for
  legacy compatibility).
- SVIs are first-class `interface Vlan<N>` records with their own
  L3 attributes (IP, MTU, VRF membership).

## OPNsense

Source: [OPNsense Devices manual — VLAN tab](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-04-30

```xml
<opnsense>
  <vlans>
    <vlan>
      <if>em1</if>
      <tag>10</tag>
      <pcp>0</pcp>
      <descr>USERS</descr>
      <vlanif>em1_vlan10</vlanif>
    </vlan>
    <vlan>
      <if>em1</if>
      <tag>100</tag>
      <pcp>0</pcp>
      <descr>TENANT_A_DATA</descr>
      <vlanif>em1_vlan100</vlanif>
    </vlan>
  </vlans>
</opnsense>
```

OPNsense `<vlan>` element carries:

- `<if>` — parent physical (or aggregated) device the tag rides on.
- `<tag>` — 802.1Q VLAN ID (1-4094).
- `<pcp>` — 802.1Q priority code point (default 0).
- `<descr>` — free-form description.
- `<vlanif>` — synthesised device name used by zone-assigned
  interfaces.

There is NO concept of "VLAN-centric port-membership list" on
OPNsense.  A VLAN exists only as a tagged sub-interface on ONE
parent NIC.  Untagged traffic is the parent NIC's native frames;
not a per-port toggle.

## Cross-vendor mapping (Arista -> OPNsense)

Canonical fields covered:

```
CanonicalVlan:
  id, name, description,
  tagged_ports: list[str], untagged_ports: list[str],
  ipv4_addresses: list[CanonicalIPv4Address]
```

- `vlans[].id`: **good** — Arista `vlan N` ↔ OPNsense
  `<vlan>/<tag>N</tag>`.  Both vendors share the 1-4094 range.
- `vlans[].name`: **lossy** — Arista per-VLAN `name <x>` collapses
  with `description` to OPNsense's single `<descr>` element.
- `vlans[].description`: **lossy** — same rationale as `name`.
- `vlans[].tagged_ports` / `untagged_ports`: **unsupported** —
  OPNsense has no per-VLAN port-membership concept.  The Arista
  `switchport access` / `trunk allowed` per-port intent (which the
  parser transposes onto `CanonicalVlan` lists) drops on render;
  operators reconstruct trunk topology manually by assigning each
  `<vlan>` to a zone.
- `vlans[].ipv4_addresses` (SVI absorption): **lossy** — Arista's
  first-class `interface Vlan<N>` SVI with `ip address X/N` has no
  first-class OPNsense equivalent.  The OPNsense pattern is to
  assign the VLAN sub-interface to a zone (`<opt2>`) and put the
  address on the zone.  The canonical model carries the SVI
  address but the OPNsense render path does not synthesise the
  corresponding zone — operator-curated.
