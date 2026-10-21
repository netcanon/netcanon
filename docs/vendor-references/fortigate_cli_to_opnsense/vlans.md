# VLANs: FortiGate FortiOS versus OPNsense

Both vendors model VLANs as 802.1Q sub-interfaces of a parent NIC,
NOT as VLAN-centric port-membership stanzas.  This is unusual for
the wider mesh (Cisco / Aruba / Arista all use VLAN-centric port
lists); FortiGate ↔ OPNsense is a relatively clean fit because of
the shared sub-interface idiom.

## FortiGate FortiOS

Source: [FortiGate / FortiOS 7.4 Cookbook — VLAN
configuration](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/)
Retrieved: 2026-05-01

```
config system interface
    edit "port2.10"
        set vdom "root"
        set ip 10.0.10.1 255.255.255.0
        set type vlan
        set vlanid 10
        set interface "port2"
        set role lan
        set alias "Users-VLAN-10"
    next
    edit "port2.20"
        set vdom "root"
        set ip 10.0.20.1 255.255.255.0
        set type vlan
        set vlanid 20
        set interface "port2"
        set role lan
        set alias "Voice-VLAN-20"
    next
end
```

Notes:

- VLANs are NOT a separate top-level entity on FortiGate.  Each VLAN
  is a child interface in `config system interface` with `set type
  vlan / set vlanid N / set interface "<parent>"`.
- The edit name (`port2.10`) is the synthesised VLAN-child name.
- `set alias` (≤25 chars) is the per-VLAN-child description.
- An L3 SVI is just `set ip` on the VLAN-child interface.
- A single VLAN tag CAN be expressed on multiple parent interfaces
  by creating multiple VLAN-child interfaces (`port2.10` AND
  `port3.10`); each is independent.
- There is no per-VLAN list of which physical ports tag/untag the
  VLAN — membership is implicit in the parent attribute.

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

Notes:

- Each `<vlan>` element binds a single 802.1Q tag to ONE parent NIC
  (the `<if>` element).
- `<vlanif>` is the synthesised BSD device name (`<parent>_vlan<tag>`
  on older configs; current OPNsense names a new one `vlan01`,
  `vlan02` ..., or takes a typed `vlan0` and digits and dots, so the
  digits of the name are not the tag).  This is what shows up on a
  zone interface's `<if>` element to use the VLAN as a
  routed/firewalled interface.
- `<pcp>` is the 802.1p priority bit, optional.
- `<descr>` is unbounded text.
- A SINGLE VLAN tag on multiple parent NICs requires multiple
  `<vlan>` elements (one per parent) — same as FortiGate.
- L3 SVI: NOT directly on the `<vlan>` element.  Operator must
  define a zone interface (`<opt2>`) referencing the `<vlanif>`
  device name and put the IP there.

## Cross-vendor mapping

Canonical fields covered:

```
CanonicalVlan:
  id, name, description, ipv4_addresses,
  tagged_ports, untagged_ports
```

FortiGate -> OPNsense:

- `vlans[].id`: **good** — FortiGate `set vlanid 10` ↔ OPNsense
  `<vlan>/<tag>10</tag>`.  Both vendors share the 1-4094 range.
- `vlans[].name`: **lossy** — FortiGate's edit-name (`port2.10`)
  doubles as VLAN identity, and the canonical `name` populates from
  it on parse.  The value survives: the OPNsense render writes that
  interface as the VLAN's device under the same name (`<vlanif>`),
  which the OPNsense parser reads back as the VLAN's name.  But not
  in a form OPNsense takes: its VLAN form refuses a device name other
  than `vlan0` followed by digits and dots, or `<parent>_vlan<id>`,
  when the VLAN is saved, and the render says so in a
  `<!-- review: -->` comment beside each such device (`port4.300`,
  `VL_200`).
- `vlans[].description`: **good** — OPNsense keeps a VLAN's
  description as its `<vlan>`'s `<descr>` (unbounded).  No FortiGate
  VLAN on the corpus carries one, so nothing is measured.
- `vlans[].tagged_ports` / `untagged_ports`: **not_applicable** —
  FortiGate parse never populates these (canonical lists are empty
  on parse) because neither vendor uses VLAN-centric port lists.
  Membership is encoded as the parent interface's identity, not as a
  port list per VLAN.
- `vlans[].ipv4_addresses` (SVI): **not_applicable** — FortiGate
  places the L3 address on the VLAN-child edit (`set ip` on
  `agg1.100`), which the parser keeps on that interface record, not
  on `CanonicalVlan.ipv4_addresses`, so no VLAN record holds one.  OPNsense
  requires a zone interface (`<opt2>`) referencing the VLAN's
  `<vlanif>` and putting the IP there.  The render writes the
  VLAN-child interface as a zone whose `<if>` is the VLAN device
  written under its name (`agg1.100`), with the address on the zone;
  read back, the address is on that interface record, not on the
  VLAN.
