# VLANs: OPNsense versus Aruba AOS-S

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

OPNsense VLAN model:

- A `<vlan>` element is a TAGGED SUB-INTERFACE on a parent NIC.
- No port-membership concept — every `<vlan>` rides exactly one
  `<if>` (the parent NIC).
- Untagged traffic is the parent NIC's native frames.
- The L3 face (the firewall's IP on this VLAN) lives on a zone
  interface that references the synthesised `<vlanif>` device name.

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Advanced Traffic Management Guide —
VLANs](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
vlan 10
   name "USERS"
   untagged 1-12
   tagged 23-24
   ip address 10.10.10.1 255.255.255.0
   exit
```

Aruba VLAN-centric model:

- Per-VLAN port-membership is declared inline in the VLAN stanza.
- `untagged <ports>` and `tagged <ports>` lists.
- SVI absorption: per-VLAN `ip address` is the L3 face (the
  aruba_aoss codec absorbs onto `CanonicalVlan.ipv4_addresses`).

## Cross-vendor mapping

OPNsense -> Aruba:

- `vlans[].id`: **good** — both vendors share 1-4094.
- `vlans[].name`: **lossy** — OPNsense `<descr>` is the only label
  field; canonical `name` and `description` both populate from it
  on parse, so both fields carry the same text.  Aruba's per-VLAN
  `name "<x>"` lands cleanly with no Aruba-side loss; the loss is
  upstream (OPNsense never carried distinct `name` and `description`
  in the first place).
- `vlans[].description`: **lossy** — same rationale; one OPNsense
  XML field populating two canonical fields.
- `vlans[].tagged_ports` / `untagged_ports`: **not_applicable** —
  OPNsense never populates the port-membership lists on parse (no
  per-VLAN port concept).  Aruba target render emits no `tagged` /
  `untagged` lines because canonical lists are empty.  Operator
  must reconstruct trunk topology manually.
- `vlans[].ipv4_addresses` (SVI): **lossy** — OPNsense doesn't have
  a first-class SVI concept; the closest equivalent is a zone
  interface (`<opt2>`) referencing the VLAN's `<vlanif>` device
  name, with the IP on the zone.  The opnsense codec does not
  currently project the zone-side IP back onto a `CanonicalVlan.
  ipv4_addresses` record; cross-pair render emits no SVI L3 line in
  the Aruba VLAN stanza.
