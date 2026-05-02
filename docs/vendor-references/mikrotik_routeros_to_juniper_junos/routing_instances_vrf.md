# Routing-instances / VRF: MikroTik RouterOS versus Juniper Junos

How VRFs / routing-instances are declared on each platform.

Sources:
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/95584418/VRF (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/instance-type-edit-routing-instances.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/vpn-l3/topics/topic-map/l3vpns-overview.html (retrieved 2026-05-01)

Citation ids: `mikrotik-vrf`, `junos-instance-type`, `junos-l3vpn`.

## RouterOS form

```
/ip vrf
add interfaces=vlan100 name=tenant-a
add interfaces=vlan200 name=tenant-b
```

RouterOS 7+ has `/ip vrf` for VRF-lite functionality (a single
global routing daemon with multiple FIBs).  The VRF record carries
the VRF name and the list of bound interfaces; RD and RT are NOT
stored on the VRF record — they live under BGP per-VRF
(`/routing bgp connection ... vrf=tenant-a`) on the BGP side, where
the canonical model does not yet wire them up.

The mikrotik_routeros codec does not model `/ip vrf` parsing in v1.

## Junos form

```
set routing-instances TENANT_A instance-type vrf
set routing-instances TENANT_A description "Tenant A L3 VRF"
set routing-instances TENANT_A route-distinguisher 172.16.0.1:10000
set routing-instances TENANT_A vrf-target target:65000:10000
set routing-instances TENANT_A interface irb.100
set routing-instances TENANT_A protocols evpn ip-prefix-routes vni 50100
```

Junos models multiple instance types (`vrf` / `mac-vrf` /
`virtual-router` / `l2vpn` / `evpn`).  RD and per-direction RTs
(`vrf-target import`, `vrf-target export`) live on the routing-
instance.  Per-interface VRF binding declared at the routing-
instance level.

## Cross-vendor mapping

* RouterOS source carries `/ip vrf` records — but the codec doesn't
  parse them in v1, so canonical `routing_instances` is always empty
  after RouterOS parse.  Junos render emits no `set routing-instances`
  blocks regardless of RouterOS source content.
* When RouterOS-side wire-up lands, the cross-pair surface becomes
  **lossy**: RouterOS source can carry VRF name + interfaces but
  not RD / RT (those live under BGP) — Junos render emits the
  routing-instance + interfaces but no `route-distinguisher` /
  `vrf-target` lines unless BGP wire-up on RouterOS also lands.
* Per-interface VRF (`CanonicalInterface.vrf`): RouterOS's
  `/ip vrf set X interfaces=Y,Z` -> Junos's `set routing-instances
  X interface Y` + `set interfaces Y unit 0 family inet ...` (the
  interface binding moves under the routing-instance on Junos).
* `routing_instances[].l3_vni` (EVPN Type-5): RouterOS does not
  model EVPN; never populated.  Junos render emits no
  `protocols evpn ip-prefix-routes vni` lines on this direction.

Disposition: **unsupported** in v1 because RouterOS-side `/ip vrf`
parsing is not wired up — canonical `routing_instances` is always
empty after RouterOS parse.  Will UPGRADE to **lossy** when the
RouterOS codec gains `/ip vrf` parsing (RD/RT structurally absent on
RouterOS side regardless).
