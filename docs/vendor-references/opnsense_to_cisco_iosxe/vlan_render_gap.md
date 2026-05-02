# VLAN handling — OPNsense source to Cisco NETCONF target

Source: [OPNsense Devices manual (VLAN tab)](https://docs.opnsense.org/manual/other-interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-vlan YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-vlan.html)
Retrieved: 2026-05-01

## OPNsense source shape

OPNsense's `<vlans>` block records each VLAN as a tagged sub-
interface on a parent NIC:

```xml
<vlans>
  <vlan>
    <if>em1</if>
    <tag>10</tag>
    <descr>Users</descr>
  </vlan>
</vlans>
```

The OPNsense parser maps `<descr>` into canonical
`CanonicalVlan.name` (per `parse.py`), leaving
`CanonicalVlan.description` empty.  Tagged/untagged port lists are
not a thing on OPNsense — every `<vlan>` rides its parent NIC, no
per-port toggles.  L3 addressing of a VLAN is via a zone (`<optN>`)
mapped to the synthesised vlan device (`em1_vlan10`); the OPNsense
codec doesn't surface that into `CanonicalVlan.ipv4_addresses`
today (zone-side L3 stays on the interface record instead).

## Cisco target render shape

The `cisco_iosxe._render_canonical()` method does NOT emit a
`<vlans>` element regardless of what the canonical tree carries in
`intent.vlans`.  The render is `<interfaces>`-only.  Even though the
matrix declares `/vlans/vlan/id` and `/vlans/vlan/name` under
`supported`, the rendering path doesn't act on them.

Real OpenConfig YANG VLAN stanzas would look like:

```xml
<vlans xmlns="http://openconfig.net/yang/vlan">
  <vlan>
    <vlan-id>10</vlan-id>
    <config>
      <vlan-id>10</vlan-id>
      <name>Users</name>
      <status>ACTIVE</status>
    </config>
  </vlan>
</vlans>
```

But the cisco_iosxe target codec emits none of this.

## Cross-pair disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `vlans` | unsupported | OPNsense source populates id + name; target render emits no `<vlans>` element |
| `vlans[].id` | unsupported | same as parent |
| `vlans[].name` | unsupported | same |
| `vlans[].description` | unsupported | OPNsense source leaves empty (collapses into `name`); target render also emits nothing |
| `vlans[].tagged_ports` | not_applicable | OPNsense source never populates |
| `vlans[].untagged_ports` | not_applicable | OPNsense source never populates |
| `vlans[].ipv4_addresses` | not_applicable | OPNsense source doesn't currently populate (zone-side L3) |

The `unsupported` label here reflects render-side gap: OPNsense
source DOES populate VLAN id + name, but the cisco_iosxe target
render drops the data.  When render-side wire-up lands, the
disposition flips to `good` for id, `lossy` for name (canonical
collapse), and stays `not_applicable` for the port-membership
sub-fields (OPNsense parser doesn't and won't populate, since
OPNsense isn't a switch).

This differs from the `opnsense__cisco_iosxe_cli.yaml` sibling pair
where the CLI target's render DOES emit VLAN stanzas; that pair
runs into the OPNsense source's structural absence of port-
membership lists (`not_applicable` for tagged/untagged).  On this
NETCONF direction the render-side gap dominates everything except
the structurally-absent fields.
