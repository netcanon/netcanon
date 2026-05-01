# VXLAN-EVPN: Cisco IOS-XE versus Juniper Junos

How VXLAN VTEPs, VLAN-to-VNI bindings, and EVPN overlays are
declared.

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9500/software/release/17-9/configuration_guide/vxlan/b_179_bgp_evpn_vxlan_9500_cg.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn-vxlan/topics/concept/evpn-vxlan-data-center-overview.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-irb-within-data-center.html (retrieved 2026-04-30)

Citation ids: `cisco-evpn-vxlan-cg`, `junos-evpn-overview`, `junos-evpn-irb-example`.

## Cisco IOS-XE form

Catalyst 9000-series VXLAN-EVPN configuration uses an `nve` (Network
Virtualization Edge) interface:

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

VLAN-to-VNI binding is split across the `vlan configuration <N>`
stanza (membership) and the `interface nve1 / member vni <N>` lines
(VTEP plumbing).  L3 VNI for VRFs binds via `member vni <N> vrf <X>`.

## Junos form

```
set switch-options vtep-source-interface lo0.0
set switch-options route-distinguisher 10.255.0.1:1
set switch-options vrf-target target:64500:1

set vlans v100 vlan-id 100
set vlans v100 vxlan vni 10100
set vlans v100 vxlan ingress-node-replication

set protocols evpn vni-options vni 10100 vrf-target target:64500:10100
set protocols evpn encapsulation vxlan
set protocols evpn extended-vni-list all
```

For L3 VNIs (Type-5):

```
set routing-instances TENANT_A instance-type vrf
set routing-instances TENANT_A protocols evpn ip-prefix-routes vni 50001
set routing-instances TENANT_A protocols evpn ip-prefix-routes encapsulation vxlan
```

## Mapping notes

- **VTEP source.** Cisco's `interface nve1 / source-interface
  Loopback0` maps to Junos's `set switch-options
  vtep-source-interface lo0.0`.  Canonical
  `CanonicalVxlan.source_interface` carries the operator-form
  string; the port-rename mesh bridges `Loopback0` and `lo0.0`.
- **VLAN-to-VNI binding.** Cisco's `member vni <N>` under `nve1`
  plus `vlan configuration <N> / member evpn-instance / vni`
  combines into the canonical `CanonicalVxlan{vlan_id, vni}`
  pair.  Junos's `set vlans NAME vxlan vni <N>` is the same
  semantic in a single line.
- **L3 VNI / Type-5.** Cisco's `member vni <N> vrf <X>` maps to
  canonical `CanonicalRoutingInstance.l3_vni`; Junos emits as
  `set routing-instances X protocols evpn ip-prefix-routes vni N`.
- **Ingress replication versus multicast.** Both vendors support
  both head-end (ingress) replication and underlay multicast for
  BUM traffic.  Canonical `mcast_group` (empty = ingress) and
  `flood_list` (explicit VTEP IPs) carry the discriminator.  Cisco's
  `host-reachability protocol bgp` (BGP-EVPN signalled discovery)
  is the default on both vendors and isn't separately modelled.
- **UDP port.** Both default to 4789 (IANA standard); explicit
  override on Cisco via `interface nve1 / vxlan udp-port` (rare),
  on Junos rarely tunable.  Canonical preserves.

## Capability matrix status

- Cisco IOS-XE codec capability matrix lists `/vxlan-vnis/vni`,
  `/vxlan-vnis/source-interface`, and `/vxlan-vnis/udp-port` under
  `unsupported` with rationale "IOS-XE VXLAN mappings parse-and-
  ignore in v1.  CanonicalVxlan schema exists; wire-up deferred
  until demand arrives for Catalyst-to-Arista (or Catalyst-to-
  Junos) migrations."
- Junos codec capability matrix lists the same paths under
  `supported` (GAP 6 wire-up).

Disposition: **unsupported** for Cisco-source today (parse-and-
ignore); **good** for Junos-source.
