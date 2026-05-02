# VXLAN, EVPN, and MAC-VRF — OpenConfig NETCONF source to Arista EOS target

Source: [openconfig-evpn YANG model (GitHub)](https://github.com/openconfig/public/tree/master/release/models/evpn)
Retrieved: 2026-05-01

Source: [OpenConfig network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

Source: [Arista EOS VXLAN Configuration Guide (4.36.0F)](https://www.arista.com/en/um-eos/eos-vxlan-configuration)
Retrieved: 2026-05-01

Source: [Arista EOS Configuring EVPN (4.35.2F)](https://www.arista.com/en/um-eos/eos-configuring-evpn)
Retrieved: 2026-05-01

## Source surface

The cisco_iosxe codec's CapabilityMatrix declares VXLAN paths under
`unsupported` explicitly:

* `/vxlan-vnis/vni`
* `/vxlan-vnis/source-interface`
* `/vxlan-vnis/udp-port`

with the reason: "VXLAN not modelled in this NETCONF/OpenConfig stub
codec.  CLI sibling defers VXLAN wire-up until Catalyst demand
arrives; NETCONF stays in lockstep."

The parser does not walk `openconfig-evpn` content,
`<network-instances>`, or any VXLAN augment.  `intent.vxlan_vnis`,
`intent.evpn_type5_routes`, and `intent.routing_instances` are all
empty after parse regardless of source XML content.

## Target surface

The arista_eos codec is the most VXLAN/EVPN-mature codec in the
suite.  Its render walks `intent.vxlan_vnis` and emits:

```
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan udp-port 4789
   vxlan vlan <id> vni <vni>
```

It walks `intent.routing_instances` for VRF + MAC-VRF emission,
and uses `intent.routing_instances[].l3_vni` to drive symmetric
IRB Type-5 announcement under `router bgp`.

The arista_eos CapabilityMatrix declares `/vxlan-vnis/vni`,
`/vxlan-vnis/source-interface`, `/vxlan-vnis/udp-port`, and
`/routing-instances/instance` under `supported`.

## What survives the round-trip

Nothing.  Source is empty for these fields; target render emits
nothing.  This pair is structurally unable to migrate VXLAN / EVPN
state regardless of how rich the underlying device's NETCONF
datastore is.

For Cisco -> Arista EVPN-VXLAN flows specifically (a real DC
migration use case), use `cisco_iosxe_cli` as the source codec
instead — the CLI parser also doesn't yet wire VXLAN (matrix
declares `/vxlan-vnis/*` `unsupported` in lockstep with NETCONF),
but the CLI source's broader feature coverage (VRFs, BGP, etc.)
gives operators a partial migration path that this NETCONF source
doesn't.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `vxlan_vnis` | not_applicable | Source matrix declares `/vxlan-vnis/*` `unsupported`; parser populates nothing |
| `vxlan_vnis[].vlan_id` | not_applicable | Same |
| `vxlan_vnis[].vni` | not_applicable | Same |
| `vxlan_vnis[].source_interface` | not_applicable | Same |
| `vxlan_vnis[].udp_port` | not_applicable | Same |
| `vxlan_vnis[].mcast_group` | not_applicable | Same |
| `vxlan_vnis[].flood_list` | not_applicable | Same |
| `evpn_type5_routes` | not_applicable | Per-prefix records not populated by either codec; doubly source-side empty |

## When this flips

VXLAN/EVPN wire-up on the cisco_iosxe codec is gated on Catalyst-VXLAN
demand (per the matrix reason).  When that demand surfaces and both
the parse and render paths land VXLAN handling, this YAML's
`not_applicable` rows for vxlan_vnis flip to `good` (Arista is
already richly wired) for the canonical-stable surface — the
forward-direction render gap on the Arista -> Cisco pair stays
because the target render also gets wired in lockstep.
