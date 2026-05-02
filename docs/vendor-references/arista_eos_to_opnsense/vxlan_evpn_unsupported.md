# VXLAN / EVPN Type-5 / VRF unsupported on OPNsense

Arista EOS is widely deployed as a leaf in DC EVPN-VXLAN spine-leaf
fabrics; OPNsense is a FreeBSD-based router/firewall with neither a
VXLAN data-plane nor an EVPN control-plane.  All overlay state is
unsupported on the OPNsense target.

## What Arista carries

Sources:
- [Arista EOS VXLAN Configuration Guide](https://www.arista.com/en/um-eos/eos-vxlan-configuration) (retrieved 2026-05-01)
- [Arista EOS Configuring EVPN](https://www.arista.com/en/um-eos/eos-configuring-evpn) (retrieved 2026-05-01)

```
vrf instance TENANT_A
!
ip routing vrf TENANT_A
!
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan udp-port 4789
   vxlan vlan 10 vni 10010
   vxlan vlan 20 vni 10020
   vxlan vlan 100 vni 10100
   vxlan vrf TENANT_A vni 50100
!
router bgp 65001
   neighbor 10.255.0.2 remote-as 65000
   address-family evpn
      neighbor 10.255.0.2 activate
   vrf TENANT_A
      rd 65001:100
      route-target import evpn 65001:100
      route-target export evpn 65001:100
```

Arista EVPN-VXLAN state covers:

- VLAN-to-VNI bindings (`vxlan vlan N vni X`) — populated into
  `CanonicalIntent.vxlan_vnis` on the Arista side.
- VTEP source interface (`vxlan source-interface Loopback0`) —
  Arista codec capability matrix declares
  `/vxlan-vnis/source-interface` supported.
- UDP port (default 4789) — capability
  `/vxlan-vnis/udp-port` supported.
- L3 VNI for symmetric IRB (`vxlan vrf X vni N`) — populated
  into `CanonicalRoutingInstance.l3_vni`.
- Per-VRF route-distinguisher and route-target import/export
  (under `router bgp / vrf X`) — populated into
  `CanonicalRoutingInstance.{route_distinguisher, rt_imports,
  rt_exports}`.
- MAC-VRF / EVPN address-family activation in BGP — Arista codec
  capability matrix lists `/routing/bgp` as parse-and-ignore
  (BGP-level surface is out of scope for v1).

## What OPNsense lacks

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
and [OPNsense Routing](https://docs.opnsense.org/manual/routes.html)
Retrieved: 2026-04-30

OPNsense `config.xml` has NO:

- VXLAN tunnel data-plane modelling (no `<vxlan>` element type).
  The opnsense codec capability matrix explicitly lists
  `/vxlan-vnis/vni`, `/vxlan-vnis/source-interface`,
  `/vxlan-vnis/udp-port` as unsupported with rationale "VXLAN
  not modelled — OPNsense is a firewall codec."
- EVPN BGP control-plane (no MP-BGP, no `address-family evpn`).
- VRF / routing-instance schema in `config.xml`.  The FreeBSD
  kernel supports VNETs and FIBs but OPNsense exposes neither
  through its data model.

## Cross-vendor disposition

Canonical fields affected (Arista as source, OPNsense as target):

- `vxlan_vnis`: **unsupported** — entire list drops.
- `vxlan_vnis[].vlan_id`, `[].vni`, `[].mcast_group`,
  `[].flood_list`, `[].source_interface`, `[].udp_port`: same.
- `evpn_type5_routes`: **unsupported** — list always drops; in
  practice the Arista codec doesn't populate per-prefix records
  (l3_vni is the cross-vendor primitive instead).
- `routing_instances`: **unsupported** — VRF list drops on render.
- `interfaces[].vrf`: **unsupported** — back-pointer drops.

All overlay / VRF intent is preserved on the canonical tree but
drops at the OPNsense render boundary.  The rename-pane shows
the unsupported-category banners declared on the OPNsense codec.
