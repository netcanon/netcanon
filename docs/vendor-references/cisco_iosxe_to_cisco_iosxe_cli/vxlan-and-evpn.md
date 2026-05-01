# VXLAN + EVPN — NETCONF source rendered to IOS-XE CLI

For full bidirectional content (CLI form, OpenConfig
`openconfig-evpn` / `openconfig-vxlan` augments, EVPN Type-5
canonical model) see the sibling file
`../cisco_iosxe_cli_to_cisco_iosxe/vxlan-and-evpn.md`.

## Direction-specific disposition

Both codecs declare every VXLAN canonical path as `unsupported`.
The NETCONF codec parser doesn't walk `<network-instances>` or any
`openconfig-vxlan` augment, so:

| Canonical field | NETCONF -> CLI |
|---|---|
| `vxlan_vnis[].vlan_id` | not_applicable — parser never populates |
| `vxlan_vnis[].vni` | not_applicable |
| `vxlan_vnis[].mcast_group` | not_applicable |
| `vxlan_vnis[].flood_list` | not_applicable |
| `vxlan_vnis[].source_interface` | not_applicable |
| `vxlan_vnis[].udp_port` | not_applicable |
| `evpn_type5_routes` | not_applicable |

Once wired (likely co-landing with VRF wire-up because Type-5 routes
are scoped per network-instance), the same-vendor cross-pair will
flip to:

* L2 VNI bindings (`vxlan_vnis[].vlan_id`, `.vni`,
  `.source_interface`, `.udp_port`) -> `good`.  Same vendor, same
  `interface nve1 / member vni <N>` CLI grammar, no naming or
  capitalisation divergence.
* `mcast_group` and `flood_list` -> `good` for the underlay-multicast
  + head-end-replication models that IOS-XE supports.
* EVPN Type-5 -> `lossy` (deferred).  Same canonical-model gap as
  cross-vendor pairs: per-prefix records aren't populated by any
  codec today; the canonical surface is `CanonicalRoutingInstance.l3_vni`
  rather than per-prefix `CanonicalEvpnType5Route` records.
