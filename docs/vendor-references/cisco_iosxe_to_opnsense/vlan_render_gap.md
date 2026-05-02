# VLAN handling — Cisco NETCONF source to OPNsense target

Source: [openconfig-vlan YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-vlan.html)
Retrieved: 2026-05-01

Source: [OPNsense Devices manual (VLAN tab)](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-05-01

## The double gap

VLAN handling on this cross-pair has TWO independent gaps stacked:

1. The cisco_iosxe SOURCE codec's `parse()` does not walk `<vlans>`
   or the `openconfig-vlan:switched-vlan` augment under
   `<ethernet>`.  `intent.vlans` is empty after parse, regardless
   of what the device's NETCONF reply carries.
2. The OPNsense TARGET codec doesn't model VLAN-centric port
   membership.  OPNsense's `<vlans>/<vlan>` carries `<if>` (parent
   NIC) + `<tag>` + `<descr>`, no per-VLAN port list.  Trunking is
   implicit: every `<vlan>` whose `<if>` matches a physical NIC
   rides that NIC.

## OpenConfig VLAN model

The full openconfig-vlan model has `vlans/vlan` records carrying
`vlan-id`, `name`, `status`, plus the `switched-vlan` augment on
`/interfaces/interface/ethernet` with `interface-mode` (ACCESS /
TRUNK), `access-vlan`, `trunk-vlans`, `native-vlan`.

A real Cisco IOS XE 17.x `<get-config>` reply against the union
YANG datastore returns these subtrees populated when the underlying
running-config has VLANs and switchport configuration.  But the
cisco_iosxe codec's parse() ignores both.

## OPNsense VLAN model

```xml
<vlans>
  <vlan>
    <if>em1</if>
    <tag>10</tag>
    <descr>Users</descr>
  </vlan>
  <vlan>
    <if>em1</if>
    <tag>20</tag>
    <descr>Voice</descr>
  </vlan>
</vlans>
```

The VLAN exists as a tagged sub-interface on ONE parent NIC (the
`<if>` element).  To assign it L3 + a zone label, operators map
the synthesised device name (`em1_vlan10`) to a `<wan>`/`<lan>`/
`<optN>` element.

There is no per-VLAN port-membership list because OPNsense isn't a
switch.  Cisco's
`switchport trunk allowed vlan 10,20,30` form has nothing to map to.

## Cross-pair disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `vlans` | not_applicable | source parser doesn't read `<vlans>` |
| `vlans[].id` | not_applicable | same as parent |
| `vlans[].name` | not_applicable | same as parent |
| `vlans[].description` | not_applicable | same as parent |
| `vlans[].tagged_ports` | not_applicable | source parser doesn't read; OPNsense target also unsupported |
| `vlans[].untagged_ports` | not_applicable | same as tagged_ports |
| `vlans[].ipv4_addresses` | not_applicable | source parser doesn't read; OPNsense's L3-on-VLAN model is zone-side anyway |

Note: this differs from the `cisco_iosxe_cli__opnsense.yaml`
sibling pair where the CLI parser DOES populate `intent.vlans` and
the cross-pair runs into the OPNsense render-side modelling
boundary (resulting in `lossy` for the id/name/description and
`unsupported` for the port-membership lists).  On the NETCONF
direction the source-parse gap dominates and everything is
`not_applicable`.

When (if) parser-side wire-up lands for `<vlans>` in the
cisco_iosxe codec, the dispositions on this pair would flip:

- `vlans[].id`: `not_applicable` -> `good`
- `vlans[].name` / `vlans[].description`: -> `lossy` (collapse into
  OPNsense `<descr>`)
- `vlans[].tagged_ports` / `untagged_ports`: -> `unsupported`
  (OPNsense target doesn't model)
- `vlans[].ipv4_addresses`: -> `lossy` (OPNsense moves L3 to zone side)
