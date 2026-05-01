# VXLAN, EVPN, and VRF — AOS-S source to OpenConfig NETCONF target

Source: [openconfig-network-instance use cases](https://openconfig.net/docs/models/network_instance/)
Retrieved: 2026-05-01

Source: [openconfig-evpn YANG model (GitHub)](https://github.com/openconfig/public/tree/master/release/models/evpn)
Retrieved: 2026-05-01

## Why this is the simplest topic in the pair

Both sides agree: nothing happens.

* AOS-S source codec: aruba_aoss CapabilityMatrix declares
  `/vxlan-vnis/*` under `unsupported` ("VXLAN not modelled — AOS-S
  is a campus L2/L3 codec").  The parser populates neither
  `intent.vxlan_vnis` nor `intent.evpn_type5_routes` nor
  `intent.routing_instances`.  AOS-S has no VRF concept (single
  global routing table on ProCurve heritage hardware).
* cisco_iosxe target codec: ALSO declares `/vxlan-vnis/*` under
  `unsupported`.  The render path doesn't emit VXLAN / EVPN /
  network-instances.

Result: every field in this category is `not_applicable` on this
direction (source has no data; target has no render path either,
but the not_applicable label dominates because there's nothing to
classify as a translation event).

## Disposition

| Field | Disposition | Reason |
|---|---|---|
| `vxlan_vnis` | not_applicable | AOS-S has no VXLAN concept |
| `evpn_type5_routes` | not_applicable | AOS-S has no EVPN concept |
| `routing_instances` | not_applicable | AOS-S has no VRF concept |
| `interfaces[].vrf` | not_applicable | always empty on AOS-S parse |
