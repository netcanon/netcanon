# VXLAN / EVPN: Juniper Junos versus MikroTik RouterOS (unsupported on RouterOS)

How VXLAN and EVPN are modelled on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/topics/concept/evpn-vxlan-data-center-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-irb-within-data-center.html (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/47579231/Bridging+and+Switching (retrieved 2026-05-01)

Citation ids: `junos-evpn-overview`, `junos-evpn-irb-example`,
`mikrotik-switching-model`.

## Junos form

```
set vlans USERS vlan-id 10
set vlans USERS vxlan vni 10010
set vlans VOICE vlan-id 20
set vlans VOICE vxlan vni 10020
set vlans TENANT_A_DATA vlan-id 100
set vlans TENANT_A_DATA l3-interface irb.100
set vlans TENANT_A_DATA vxlan vni 10100

set switch-options vtep-source-interface lo0.0
set switch-options route-distinguisher 172.16.0.1:1
set switch-options vrf-target target:65000:9999
set switch-options vxlan-port 4789

set routing-instances TENANT_A instance-type vrf
set routing-instances TENANT_A protocols evpn ip-prefix-routes vni 50100
set routing-instances TENANT_A vrf-target target:65000:10000
```

Junos models VXLAN VNI mappings inside `vlans <name> vxlan vni <N>`
records, with switch-level globals (VTEP source interface, RD, VRF-
target, UDP port) under `switch-options`.  EVPN Type-5 (IP-prefix)
advertisements are a VRF-property model — the L3 VNI lives under
`routing-instances <vrf> protocols evpn ip-prefix-routes vni <N>`.

## RouterOS form

RouterOS 7.x has a `/interface vxlan` section for raw VXLAN tunnels,
but does NOT implement EVPN control-plane (no MP-BGP / EVPN address
family) and does not auto-render VXLAN tunnels from canonical-portable
fabric primitives.  RouterOS is router-first / SMB-class — VXLAN
fabric overlays are out of scope.

The MikroTik RouterOS codec capability matrix lists
`/vxlan-vnis/vni`, `/vxlan-vnis/source-interface`,
`/vxlan-vnis/udp-port` under `unsupported` with rationale "RouterOS
VXLAN exists but is rare in canonical scope and not modelled in v1."

## Cross-vendor mapping

* `vxlan_vnis[].*`: Junos source carries the canonical records
  (`/vxlan-vnis/vni` is supported in JunosCodec._CAPS); MikroTik
  target codec has the path under `unsupported`.  Cross-pair drops to
  unsupported on the RouterOS render side — codec emits a banner
  comment marking the dropped VNI mappings.
* `evpn_type5_routes`: Junos source models L3 VNI via
  `CanonicalRoutingInstance.l3_vni` (MP-BGP / EVPN address-family is
  Tier-3 parse-and-ignore in v1 anyway); RouterOS does not model
  EVPN at all.  Effectively unsupported on the cross-pair.

Disposition: **unsupported** — Junos source carries the canonical
schema fields, but RouterOS target has no auto-rendered VXLAN /
EVPN surface.  Drop with banner.
