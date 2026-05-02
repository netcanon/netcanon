# Routing-instances / VRF: Juniper Junos versus MikroTik RouterOS

How VRFs / routing-instances are declared on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/instance-type-edit-routing-instances.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/vpn-l3/topics/topic-map/l3vpns-overview.html (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/95584418/VRF (retrieved 2026-05-01)

Citation ids: `junos-instance-type`, `junos-l3vpn`, `mikrotik-vrf`.

## Junos form

```
set routing-instances TENANT_A instance-type vrf
set routing-instances TENANT_A description "Tenant A L3 VRF"
set routing-instances TENANT_A route-distinguisher 172.16.0.1:10000
set routing-instances TENANT_A vrf-target target:65000:10000
set routing-instances TENANT_A interface irb.100
set routing-instances TENANT_A protocols evpn ip-prefix-routes vni 50100

set routing-instances TENANT_B instance-type mac-vrf
set routing-instances TENANT_B route-distinguisher 172.16.0.1:20000
set routing-instances TENANT_B vrf-target import target:65000:20000
set routing-instances TENANT_B vrf-target export target:65000:20001

set routing-instances RTR_C instance-type virtual-router
set routing-instances RTR_C description "Lightweight virtual router for transit"
```

Junos models multiple routing-instance types: `vrf` (the cross-
vendor baseline — L3VPN-style with RD + RT + interfaces),
`mac-vrf` (EVPN MAC-VRF for L2 multi-tenancy), `virtual-router`
(lightweight L3 isolation without MP-BGP — no RD/RT), `l2vpn`,
`evpn`.  RD and per-direction RTs (`vrf-target import`, `vrf-target
export`) live on the routing-instance.  Per-interface VRF binding
is declared at the routing-instance level (`set routing-instances X
interface Y`).

## RouterOS form

```
/ip vrf
add interfaces=vlan100 name=tenant-a
add interfaces=vlan200 name=tenant-b
```

RouterOS 7+ has `/ip vrf` for VRF-lite functionality (a single
global routing daemon with multiple FIBs).  The VRF record carries
the VRF name and the list of bound interfaces; RD and RT are
NOT stored on the VRF record — they live under BGP per-VRF
(`/routing bgp connection ... vrf=tenant-a`) on the BGP side, where
the canonical model does not yet wire them up.  The mikrotik_routeros
codec does not model `/ip vrf` parsing in v1.

## Cross-vendor mapping

* `routing_instances[].name`: Junos `set routing-instances <name>`
  -> RouterOS `/ip vrf add name=<name>`.  Direct mapping.
* `routing_instances[].instance_type`: Junos's `vrf` /
  `virtual-router` are L3 routing isolation primitives that map to
  RouterOS `/ip vrf` (VRF-lite); Junos's `mac-vrf` (EVPN L2 multi-
  tenancy) has no RouterOS equivalent — drop with banner.
* `routing_instances[].route_distinguisher`: Junos
  `route-distinguisher <rd>` -> no RouterOS field on `/ip vrf` (RD
  lives under BGP); drops on render.
* `routing_instances[].rt_imports` / `rt_exports`: same as RD —
  RouterOS keeps them under `/routing bgp` per-VRF; drops on
  `/ip vrf` render.
* `routing_instances[].description`: Junos has it; no RouterOS field.
* `routing_instances[].l3_vni` (EVPN Type-5): Junos source carries
  it; RouterOS does not model EVPN at all — drop with banner.
* Per-interface VRF (`CanonicalInterface.vrf`): Junos's
  `set routing-instances X interface Y` -> RouterOS's `/ip vrf set
  X interfaces=Y,Y2,...` (forward list).
* The mikrotik_routeros codec does not yet wire up `/ip vrf` parsing,
  so the canonical `routing_instances` list is empty after parsing
  a RouterOS source — but the codec's RENDER path does not yet
  emit `/ip vrf` blocks either, so a Junos-source -> RouterOS-target
  migration drops the entire VRF surface with a banner.

Disposition: **unsupported** — even though Junos source carries the
canonical records, the mikrotik_routeros codec does not render
`/ip vrf` from canonical, so the cross-pair drops the entire VRF
surface.  Lands when RouterOS-side wire-up arrives.  RD/RT loss
will REMAIN structural even after wire-up because RouterOS keeps
them under BGP, not on the VRF record.
