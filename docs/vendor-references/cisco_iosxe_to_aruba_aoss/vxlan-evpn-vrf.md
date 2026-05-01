# VXLAN, EVPN, and VRF — Cisco NETCONF source to AOS-S CLI target

Source: [openconfig-network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

Source: [openconfig-evpn YANG model (GitHub)](https://github.com/openconfig/public/tree/master/release/models/evpn)
Retrieved: 2026-05-01

Source: [Catalyst 9000 Series EVPN-VXLAN Configuration Guide](https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-15/configuration_guide/vxlan/b_1715_bgp_evpn_vxlan_9300_cg.html)
Retrieved: 2026-05-01

## Why this is the simplest topic in the pair

Both sides agree: nothing happens.

* cisco_iosxe source codec: matrix declares `/vxlan-vnis/*` under
  `unsupported`.  Parser doesn't read EVPN / network-instances.
  `intent.vxlan_vnis`, `intent.evpn_type5_routes`,
  `intent.routing_instances` stay empty after parse.
* aruba_aoss target codec: matrix ALSO declares `/vxlan-vnis/*`
  under `unsupported` ("VXLAN not modelled — AOS-S is a campus
  L2/L3 codec").  AOS-S has no VRF concept either (single global
  routing table).

Result: every field in this category is `not_applicable` on this
direction (source has no data; target couldn't accept it anyway).

The only authentic translation event would be a real Catalyst 9300
EVPN-VXLAN fabric replicated to an AOS-S campus switch — which
makes no sense as a use case (campus switches don't do EVPN
fabrics).  This pair correctly declares the whole category off-
limits.

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `vxlan_vnis` | not_applicable | both source and target `unsupported` |
| `evpn_type5_routes` | not_applicable | both `unsupported` |
| `routing_instances` | not_applicable | source not parsed; target has no VRF concept |
| `interfaces[].vrf` | not_applicable | source parser doesn't walk; target has no VRF |
