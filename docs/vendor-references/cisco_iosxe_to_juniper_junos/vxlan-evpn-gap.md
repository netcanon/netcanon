# VXLAN, EVPN — parse-side gap on cisco_iosxe; supported on Junos

Source: [openconfig-evpn YANG model (GitHub)](https://github.com/openconfig/public/tree/master/release/models/evpn)
Retrieved: 2026-05-01

Source: [OpenConfig network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

Source: [Catalyst 9000 Series EVPN-VXLAN Configuration Guide](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-15/configuration_guide/vxlan/b_1715_bgp_evpn_vxlan_9300_cg.html)
Retrieved: 2026-05-01

Source: [Junos EVPN-VXLAN data-center overview](https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/topics/concept/evpn-vxlan-data-center-overview.html)
Retrieved: 2026-05-01

Source: [Junos EVPN-VXLAN Centrally-Routed Bridging Fabric example](https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-irb-within-data-center.html)
Retrieved: 2026-05-01

## What OpenConfig models

The `openconfig-evpn` model carries EVPN ESI / EVI / Type-2 / Type-5
records under network-instance plus dedicated sub-namespaces.
OpenConfig coverage of VXLAN VTEP source-interface and UDP port
lives under `openconfig-network-instance` augments.  Real Catalyst
NETCONF replies vary in coverage by train; many Catalyst 9000
images expose only the Cisco-IOS-XE-vxlan native YANG module
rather than a complete OpenConfig EVPN tree.

## What the cisco_iosxe parser actually reads

Nothing.  The parser walks `<interfaces>` only.  `intent.vxlan_vnis`
and `intent.evpn_type5_routes` are empty after parse.

The codec's CapabilityMatrix declares `/vxlan-vnis/vni`,
`/vxlan-vnis/source-interface`, and `/vxlan-vnis/udp-port` under
`unsupported` explicitly with reason "VXLAN not modelled in this
NETCONF/OpenConfig stub codec.  CLI sibling defers VXLAN wire-up
until Catalyst demand arrives; NETCONF stays in lockstep."

This is a doubly-deferred surface: parse-side gap AND explicit
matrix-`unsupported` declaration.

## What the Junos target render does with empty input

Nothing.  The render walks `intent.vxlan_vnis` to emit
`set vlans <name> vxlan vni <N>` and `set switch-options vtep-source-
interface lo0.0` — empty list emits nothing.

The juniper_junos codec is rich on the VXLAN render side: GAP 6 +
GAP-EVPN-2 wire `/vxlan-vnis/vni`, `/vxlan-vnis/source-interface`,
`/vxlan-vnis/udp-port` as `supported`.  L3 VNI for EVPN Type-5
routes maps via `CanonicalRoutingInstance.l3_vni` to `set routing-
instances <vrf> protocols evpn ip-prefix-routes vni <N>`.
MAC-VRF and L3-VRF instance types are first-class.

## Disposition

| Field | Today |
|---|---|
| `vxlan_vnis` (top-level) | not_applicable |
| `vxlan_vnis[].vlan_id` | not_applicable |
| `vxlan_vnis[].vni` | not_applicable |
| `vxlan_vnis[].mcast_group` | not_applicable |
| `vxlan_vnis[].flood_list` | not_applicable |
| `vxlan_vnis[].source_interface` | not_applicable |
| `vxlan_vnis[].udp_port` | not_applicable |
| `evpn_type5_routes` | not_applicable |

The disposition is `not_applicable` rather than `unsupported`
because the SOURCE has no data.  If the cisco_iosxe codec eventually
wires VXLAN parse via Cisco-IOS-XE-vxlan native YANG bridging, the
classification would flip to `good` for vlan_id / vni / source_interface
/ udp_port (Junos accepts the canonical surface cleanly), and `lossy`
for `mcast_group` (Junos's flood-and-learn vs ingress-replication
operator-curated mapping) and `flood_list` (Junos's per-VTEP IRB
list).

EVPN Type-5 stays `not_applicable` regardless: both codecs declare
`/evpn-type5-routes/route` under lossy-by-default with rationale
that Type-5 is a VRF-property model (`CanonicalRoutingInstance.l3_vni`)
rather than per-prefix records — no codec populates the per-prefix
list today.

## Reverse direction asymmetry

The reverse direction (juniper_junos__cisco_iosxe) marks these
fields `unsupported` because Junos source IS wired (populates
`intent.vxlan_vnis` from `set vlans <name> vxlan vni <N>`) but
Cisco target render isn't — render-side gap.  Same operational
meaning ("nothing emerges in the output"), schematically different
labelling ("source had nothing" vs "target couldn't emit").
