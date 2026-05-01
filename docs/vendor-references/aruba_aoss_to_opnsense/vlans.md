# VLANs: Aruba AOS-S versus OPNsense

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Advanced Traffic Management Guide —
VLANs](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba is VLAN-centric: each `vlan <id>` stanza carries its port
membership inline.

```
vlan 10
   name "USERS"
   untagged 1-12
   tagged 23-24
   ip address 10.10.10.1 255.255.255.0
   exit
vlan 20
   name "VOICE"
   untagged 13-20
   tagged 23-24
   ip address 10.10.20.1/24
   exit
```

- `name "X"` is a per-VLAN human label (32-character max).
- `untagged <range>` lists the access-mode ports for this VLAN.
- `tagged <range>` lists the trunk-mode ports that carry this VLAN
  with its 802.1Q tag.
- `ip address X` inside a VLAN stanza is the SVI L3 address (the
  aruba_aoss codec absorbs this into `CanonicalVlan.ipv4_addresses`
  via the `_svi_absorption` module).
- Default VLAN is 1.  Range 2-4094.

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
      <tag>20</tag>
      <pcp>0</pcp>
      <descr>VOICE</descr>
      <vlanif>em1_vlan20</vlanif>
    </vlan>
  </vlans>
</opnsense>
```

OPNsense's `<vlan>` element carries:

- `<if>` — parent physical (or aggregated) device the tag rides on.
- `<tag>` — 802.1Q VLAN ID (1-4094).
- `<pcp>` — 802.1Q priority code point (default 0).
- `<descr>` — free-form description.
- `<vlanif>` — synthesised device name used by zone-assigned
  interfaces.

There is NO concept of "VLAN-centric port-membership list" on
OPNsense.  A VLAN exists only as a tagged sub-interface on ONE
parent NIC.  Untagged traffic is the parent NIC's native frames; not
a per-port toggle.

## Cross-vendor mapping

Canonical fields covered:

```
CanonicalVlan:
  id, name, description,
  tagged_ports: list[str], untagged_ports: list[str],
  ipv4_addresses: list[CanonicalIPv4Address]
```

Aruba -> OPNsense:

- `vlans[].id`: **good** — both use 1-4094 range.
- `vlans[].name`: **lossy** — Aruba's per-VLAN `name "<x>"` collapses
  with `description` to OPNsense's single `<descr>` element.  One
  canonical field drops on render.
- `vlans[].description`: **lossy** — same rationale as `name`.
- `vlans[].tagged_ports` / `untagged_ports`: **unsupported** —
  OPNsense has no per-VLAN port-membership concept.  Cross-pair render
  emits no port-membership XML; the operator must manually assign
  each `<vlan>` element to a zone (`<wan>` / `<lan>` / `<optN>`).
- `vlans[].ipv4_addresses` (SVI absorption): **lossy** — Aruba's
  per-VLAN `ip address` (absorbed onto the canonical VLAN record by
  `_svi_absorption.py`) has no first-class OPNsense equivalent.  The
  OPNsense pattern is to assign the VLAN sub-interface to a zone and
  put the address on the zone (`<opt2>`).  The canonical model
  carries the SVI address but the OPNsense render path does not
  synthesise the corresponding zone — operator-curated.
