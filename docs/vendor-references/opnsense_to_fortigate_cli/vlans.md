# VLANs: OPNsense versus FortiGate FortiOS

Reverse direction.  See `../fortigate_cli_to_opnsense/vlans.md` for
the shared backdrop — both vendors model VLANs as 802.1Q sub-interfaces
of a parent NIC, NOT as VLAN-centric port-membership stanzas.

## OPNsense

Source: [OPNsense Devices manual — VLAN
tab](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-05-01

```xml
<opnsense>
  <vlans>
    <vlan uuid="...">
      <if>em1</if>
      <tag>10</tag>
      <pcp>0</pcp>
      <descr>Users-VLAN-10</descr>
      <vlanif>em1_vlan10</vlanif>
    </vlan>
    <vlan uuid="...">
      <if>em1</if>
      <tag>20</tag>
      <pcp>0</pcp>
      <descr>Voice-VLAN-20</descr>
      <vlanif>em1_vlan20</vlanif>
    </vlan>
  </vlans>
</opnsense>
```

OPNsense notes:

- Each `<vlan>` element binds a single tag to ONE parent NIC.
- `<descr>` is the only label field — both canonical `name` and
  `description` populate from it on parse, so they share the same
  text.
- `<vlanif>` is the synthesised BSD device name; this is what
  shows up on a zone interface to use the VLAN as a routed/firewalled
  interface.
- Per-VLAN L3 SVI: NOT directly on the `<vlan>` element.  The
  operator defines a zone interface (`<opt2>`) referencing
  `<vlanif>em1_vlan10</vlanif>` and puts the IP there.

## FortiGate FortiOS

See `../fortigate_cli_to_opnsense/vlans.md` for the FortiGate-side
shape.  Key points:

- VLANs are NOT a separate top-level entity.  Each VLAN is a child
  interface in `config system interface` with `set type vlan / set
  vlanid N / set interface "<parent>"`.
- The edit name (`port2.10`) is the synthesised VLAN-child name.
- `set alias` (≤25 chars) is the per-VLAN-child description.
- An L3 SVI is just `set ip` on the VLAN-child interface.

## Cross-vendor mapping (OPNsense -> FortiGate)

- `vlans[].id`: **good** — OPNsense `<tag>10</tag>` ↔ FortiGate
  `set vlanid 10`.  Both vendors share the 1-4094 range.
- `vlans[].name`: **lossy** — OPNsense's `<descr>` is the only label
  field; canonical `name` and `description` both populate from it on
  parse, so both fields carry the same text.  FortiGate `set alias`
  is the closest analogue but caps at 25 characters; long OPNsense
  descriptions truncate on FortiGate render.
- `vlans[].description`: **lossy** — same rationale as `vlans[].name`
  — one OPNsense XML field populating two canonical fields.
- `vlans[].tagged_ports` / `untagged_ports`: **not_applicable** —
  OPNsense never populates per-VLAN port-membership lists on parse
  (no per-VLAN port concept).  FortiGate target's child-interface
  model encodes membership via parent identity rather than per-VLAN
  port lists, so the empty canonical list maps to nothing on render.
- `vlans[].ipv4_addresses` (SVI): **lossy** — OPNsense doesn't have
  a first-class SVI concept; the closest equivalent is a zone
  interface (`<opt2>`) referencing the VLAN's `<vlanif>` device name
  with the IP on the zone.  The opnsense codec does not currently
  project the zone-side IP back onto a CanonicalVlan.ipv4_addresses
  record; cross-pair render emits the FortiGate VLAN-child interface
  without an SVI L3 line pending wire-up.
- The fundamental shape compatibility (both use 802.1Q sub-interfaces
  with parent attribute) makes this direction relatively clean
  modulo the SVI projection gap.
