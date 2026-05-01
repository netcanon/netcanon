# VXLAN-EVPN: Juniper Junos versus Cisco IOS-XE

How VXLAN VTEPs, VLAN-to-VNI bindings, and EVPN overlays are
declared.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/topics/concept/evpn-vxlan-data-center-overview.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-irb-within-data-center.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9500/software/release/17-9/configuration_guide/vxlan/b_179_bgp_evpn_vxlan_9500_cg.html (retrieved 2026-04-30)

Citation ids: `junos-evpn-overview`, `junos-evpn-irb-example`, `cisco-evpn-vxlan-cg`.

## Junos form

```
set switch-options vtep-source-interface lo0.0
set switch-options route-distinguisher 10.255.0.1:1
set switch-options vrf-target target:64500:1

set vlans v100 vlan-id 100
set vlans v100 vxlan vni 10100
set vlans v100 vxlan ingress-node-replication
set vlans v100 l3-interface irb.100

set protocols evpn vni-options vni 10100 vrf-target target:64500:10100
set protocols evpn encapsulation vxlan
set protocols evpn extended-vni-list all

set routing-instances TENANT_A instance-type vrf
set routing-instances TENANT_A protocols evpn ip-prefix-routes vni 50001
set routing-instances TENANT_A protocols evpn ip-prefix-routes encapsulation vxlan
```

VTEP source: `set switch-options vtep-source-interface lo0.0`.
L2 VNI binding: `set vlans NAME vxlan vni N` (one line, scoped to
the named VLAN).  L3 VNI: `protocols evpn ip-prefix-routes vni N`
inside the routing-instance.

## Cisco IOS-XE form (Catalyst 9000)

```
l2vpn evpn
 replication-type ingress

interface nve1
 source-interface Loopback0
 host-reachability protocol bgp
 member vni 10100 mcast-group 239.1.1.100
 member vni 10100 ingress-replication
 member vni 50001 vrf TENANT_A

vlan configuration 100
 member evpn-instance 100 vni 10100
```

VTEP source: `interface nve1 / source-interface Loopback0`.  L2
VNI binding split between `vlan configuration <N>` and
`interface nve1 / member vni <N>`.  L3 VNI: `member vni <N> vrf
<X>`.

## Mapping notes

- **VTEP source.** Junos's `lo0.0` -> Cisco's `Loopback0` via the
  port-rename mesh; canonical `CanonicalVxlan.source_interface`
  is opaque.
- **VLAN-to-VNI binding.** Junos's single-line `set vlans NAME
  vxlan vni N` maps to Cisco's split `member vni N` (under nve1)
  + `member evpn-instance / vni` (under vlan configuration).
  Canonical `CanonicalVxlan{vlan_id, vni}` flattens both forms.
- **L3 VNI.** Junos's `protocols evpn ip-prefix-routes vni N`
  inside the routing-instance maps to canonical
  `CanonicalRoutingInstance.l3_vni`; Cisco emits as `member vni
  N vrf X` under nve1.
- **Replication mode.** Junos's `vxlan ingress-node-replication`
  (head-end) vs Cisco's `member vni N ingress-replication` —
  same semantic, different scoping.  Underlay-multicast
  alternative: Junos doesn't natively model BUM via underlay
  multicast in the same way; Cisco's `mcast-group` directive is
  closer to a multicast-rendezvous configuration.
- **VRF-target plumbing.** Junos's `set switch-options
  vrf-target` (chassis-wide default) and per-VNI `vni-options
  vni N vrf-target` are not directly modelled by canonical;
  cross-vendor render uses `CanonicalRoutingInstance.{rt_imports,
  rt_exports}` for the per-VRF case.

## Capability matrix status

- Junos codec capability matrix lists `/vxlan-vnis/vni`,
  `/vxlan-vnis/source-interface`, and `/vxlan-vnis/udp-port`
  under `supported` (GAP 6, GAP-EVPN-2 wired).
- Cisco IOS-XE codec capability matrix lists the same paths under
  `unsupported` with rationale "IOS-XE VXLAN mappings parse-and-
  ignore in v1.  CanonicalVxlan schema exists; wire-up deferred
  until demand arrives for Catalyst-to-Arista (or Catalyst-to-
  Junos) migrations."

Disposition: **unsupported** for Junos -> Cisco render today
(canonical model intact, Cisco render-side wire-up deferred).
