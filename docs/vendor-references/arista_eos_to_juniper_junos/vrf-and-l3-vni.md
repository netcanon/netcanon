# VRF / routing-instance + Layer-3 VNI

How each platform declares the L3 isolation primitive (VRF) and the
Layer-3 VNI used for symmetric IRB EVPN Type-5 advertisements.

Sources:
- Arista: https://www.arista.com/en/um-eos/eos-configuring-evpn (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/evpn/topics/example/evpn-vxlan-irb-within-data-center.html (retrieved 2026-05-01)

Citation ids: `arista-evpn-cg`, `junos-evpn-irb-example`.

## Arista EOS form

```
vrf instance TENANT-A
ip routing vrf TENANT-A

interface Vxlan1
   vxlan vrf TENANT-A vni 50001

router bgp 65001
   vrf TENANT-A
      rd 10.255.0.1:50001
      route-target import evpn 64500:50001
      route-target export evpn 64500:50001
      redistribute connected
```

VRF declaration: `vrf instance <name>` + `ip routing vrf <name>`.
L3 VNI: `vxlan vrf <name> vni <N>` inside the `Vxlan1` interface.
RD/RT: per-VRF block under `router bgp`.

## Junos form

```
set routing-instances TENANT-A instance-type vrf
set routing-instances TENANT-A interface irb.100
set routing-instances TENANT-A route-distinguisher 10.255.0.1:50001
set routing-instances TENANT-A vrf-target target:64500:50001
set routing-instances TENANT-A protocols evpn ip-prefix-routes vni 50001
set routing-instances TENANT-A protocols evpn ip-prefix-routes encapsulation vxlan
```

VRF declaration: `set routing-instances <name> instance-type vrf`.
L3 VNI: `protocols evpn ip-prefix-routes vni <N>` inside the
routing-instance.  RD/RT: directly on the routing-instance.

## Mapping notes

- Canonical `CanonicalRoutingInstance{name, instance_type,
  route_distinguisher, rt_imports, rt_exports, l3_vni}` carries
  the cross-vendor surface losslessly.
- Per-interface VRF membership lives on `CanonicalInterface.vrf`
  (back-pointer pattern) — the codec render walks
  `tree.interfaces` to synthesise the parent-side stanza.
- L3 VNI mapping: Arista `vxlan vrf X vni N` → canonical
  `routing_instances[X].l3_vni = N` → Junos `set routing-instances
  X protocols evpn ip-prefix-routes vni N`.
- EVPN Type-5 announcements are **implicit** from VRF membership +
  l3_vni in the canonical model; explicit per-prefix
  `CanonicalEvpnType5Route` records are a lossy-by-default
  extension point that no codec populates today (would require
  route-map / policy-statement parsing).  Operators relying on
  selective prefix export will see a review-required banner.
- Per-VRF BGP neighbor activation is **not modelled canonically**
  (BGP listed under `unsupported` for both codecs).  The render
  emits the EVPN-VXLAN data-plane intent only; the operator wires
  BGP overlay manually.
