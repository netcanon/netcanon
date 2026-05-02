# VXLAN / EVPN: MikroTik RouterOS versus Juniper Junos (unsupported on RouterOS source)

How VXLAN and EVPN are modelled on each platform.

Sources:
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/47579231/Bridging+and+Switching (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/topics/concept/evpn-vxlan-data-center-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-irb-within-data-center.html (retrieved 2026-05-01)

Citation ids: `mikrotik-switching-model`, `junos-evpn-overview`,
`junos-evpn-irb-example`.

## RouterOS form

RouterOS 7.x has a `/interface vxlan` section for raw VXLAN tunnels,
but does NOT implement EVPN control-plane (no MP-BGP / EVPN address
family) and the canonical surface does not auto-render VXLAN tunnels
from canonical-portable fabric primitives.  RouterOS is router-first /
SMB-class — VXLAN fabric overlays are out of scope.

The mikrotik_routeros codec capability matrix lists
`/vxlan-vnis/vni`, `/vxlan-vnis/source-interface`,
`/vxlan-vnis/udp-port` under `unsupported` ("RouterOS VXLAN exists
but is rare in canonical scope and not modelled in v1.").

## Junos form

```
set vlans USERS vlan-id 10
set vlans USERS vxlan vni 10010
set switch-options vtep-source-interface lo0.0
set switch-options route-distinguisher 172.16.0.1:1
set switch-options vrf-target target:65000:9999
set switch-options vxlan-port 4789
```

Junos has rich EVPN-VXLAN support — VLAN-to-VNI mappings under
`vlans <name> vxlan vni <N>`, switch-level globals under
`switch-options`, EVPN-Type5 under `routing-instances <vrf>
protocols evpn ip-prefix-routes vni <N>`.

## Cross-vendor mapping

* `vxlan_vnis[].*`: RouterOS source codec lists `/vxlan-vnis/vni`
  under `unsupported` — canonical `vxlan_vnis` list is empty after
  RouterOS parse.  Junos render emits no `set vlans <name> vxlan
  vni` lines because there is no canonical source data.  Effectively
  not_applicable on this direction (parse-side absence).
* `evpn_type5_routes`: RouterOS does not model EVPN at all —
  canonical list always empty after RouterOS parse.  Junos render
  emits no Type-5 records.

Disposition: **not_applicable** — RouterOS source has no EVPN-VXLAN
canonical data to lose; Junos render emits no fabric overlay
configuration on this direction.  Unlike the inverse direction
(Junos source -> RouterOS target which is unsupported because Junos
DOES populate the canonical data and RouterOS cannot consume it),
RouterOS -> Junos is structurally absent on the source side.
