# VLAN render gap — `fortigate_cli` source to `cisco_iosxe` target

Source: [openconfig-vlan YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-vlan.html)
Retrieved: 2026-05-01

Source: [Fortinet FortiGate Cookbook — VLAN configuration](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/)
Retrieved: 2026-05-01

## FortiGate VLAN source

FortiGate models VLAN membership as **child interfaces** hanging
off a parent:

```
config system interface
    edit "port1.100"
        set type vlan
        set vlanid 100
        set interface "port1"
        set ip 10.10.0.1 255.255.255.0
    next
end
```

The FortiGate parser synthesises a `CanonicalVlan` record from
each child-interface stanza:

* `intent.vlans[].id` from the `set vlanid` value
* `intent.vlans[].name` synthesised from the edit ID (e.g.
  `"port1.100"`)
* `intent.vlans[].ipv4_addresses` from the child interface's `set ip`
  (SVI-style absorption)

`tagged_ports` / `untagged_ports` are typically empty because
FortiGate's child-interface model encodes membership via the
parent's identity, not as a port list.  The canonical
`CanonicalVlan` record holds the VLAN header but not multi-port
trunk membership.

## OpenConfig VLAN target

`openconfig-vlan` models VLAN definitions under
`<network-instances><network-instance><vlans><vlan>` with `<id>`
and `<name>` leaves.  Per-port membership lives in the
`switched-vlan` augment under each `<interface><ethernet>`.

## What the cisco_iosxe target render does

Nothing.  `_render_canonical()` walks `intent.interfaces` only —
no `<network-instances>`, no `<vlans>`, no `switched-vlan`
augment emission.  After render, the output XML carries no VLAN
intent regardless of how many VLAN child interfaces the FortiGate
source had.

The cisco_iosxe codec's CapabilityMatrix declares `/vlans/vlan/id`
and `/vlans/vlan/name` under `supported`, but those declarations
are aspirational — the actual emit path doesn't walk
`intent.vlans`.  The render gap is the binding constraint.

Note: the synthesised SVI interfaces (each a
`CanonicalInterface` with `name="port1.100"` and
ipv4_addresses set from FortiGate's child-interface) DO survive
via the cisco_iosxe interfaces walk — they appear as standalone
OpenConfig `<interface>` records in the output XML.  The
`vlans` top-level VLAN-definition stanza does NOT.  A downstream
OpenConfig consumer would see the SVIs without VLAN-membership
context.

## Disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `vlans` | unsupported | cisco_iosxe render doesn't walk `intent.vlans` |
| `vlans[].id` | unsupported | Same render-side gap |
| `vlans[].name` | unsupported | Same render-side gap |
| `vlans[].ipv4_addresses` | good | Survives via the synthesised SVI interface in `intent.interfaces` |
| `interfaces[].switchport_mode` | unsupported | cisco_iosxe render doesn't emit `switched-vlan` augment (note: FortiGate parser doesn't populate this anyway, so doubly missing) |
| `interfaces[].access_vlan` | unsupported | Same render-side gap |
| `interfaces[].trunk_allowed_vlans` | unsupported | Same render-side gap |

These are `unsupported` (render-side wire-up gap) rather than
`not_applicable` because the FortiGate source DOES populate
`intent.vlans` and the canonical layer DOES carry the VLAN
records — the loss happens at the cisco_iosxe render boundary.
