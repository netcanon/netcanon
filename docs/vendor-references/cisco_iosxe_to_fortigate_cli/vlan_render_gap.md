# VLAN render gap — `cisco_iosxe` source to `fortigate_cli` target

Source: [openconfig-vlan YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-vlan.html)
Retrieved: 2026-05-01

Source: [Fortinet FortiGate Cookbook — VLAN configuration](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/)
Retrieved: 2026-05-01

## OpenConfig VLAN scope

`openconfig-vlan` models VLAN definitions under
`<network-instances><network-instance><vlans><vlan>` and per-port
membership via the `openconfig-vlan:switched-vlan` augment under
each `<interface><ethernet>` element.  A real Catalyst 9K NETCONF
reply carries both — VLAN headers (`<id>`, `<name>`) and
per-interface trunk / access membership.

The `netconfig.migration.codecs.cisco_iosxe.parse()` walks
`<interfaces>` only.  It does NOT walk `<network-instances>`
(where VLAN headers live) and does NOT walk the `switched-vlan`
augment.  After parse:

* `intent.vlans` is empty regardless of source content.
* Per-interface `switchport_mode` / `access_vlan` /
  `trunk_allowed_vlans` / `trunk_native_vlan` / `voice_vlan` are
  all None / empty regardless of source content.

## FortiGate VLAN model

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

There is no top-level VLAN-stanza concept on FortiGate (no analogue
to Cisco's `vlan 100 / name DATA`).  VLAN identity is the parent
+ vlanid pair, with the operator-named edit ID providing a
human-readable handle.

## Cross-vendor mapping

If `intent.vlans` were populated AND
`intent.interfaces[].access_vlan` / `trunk_allowed_vlans` were
populated, the FortiGate render would synthesise child interfaces
per (parent, vlan-id) tuple.  Today the v1 render does not
automatically synthesise multi-port VLAN membership — operators
must reconstruct the topology manually on FortiGate.

But this entire question is moot on this cross-pair: the cisco_iosxe
parser populates none of the source-side fields.  Disposition is
therefore `not_applicable` (source structurally absent) rather than
`unsupported` (active drop on render).

## Disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `vlans` (top-level list) | not_applicable | NETCONF parser doesn't walk `<network-instances><vlans>` |
| `interfaces[].switchport_mode` | not_applicable | NETCONF parser doesn't walk `switched-vlan` augment |
| `interfaces[].access_vlan` | not_applicable | Same parser-side gap |
| `interfaces[].trunk_allowed_vlans` | not_applicable | Same parser-side gap |
| `interfaces[].trunk_native_vlan` | not_applicable | Same parser-side gap |
| `interfaces[].voice_vlan` | not_applicable | Parser gap + FortiGate has no voice-VLAN concept |

Promotes to mostly `lossy` (parent-interface synthesis gap on
FortiGate render) when the cisco_iosxe parser wires
`<network-instances>` + `switched-vlan`.
