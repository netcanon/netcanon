# VRF / routing-instances: MikroTik RouterOS versus Aruba AOS-S

## MikroTik RouterOS

Source: [VRF — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/95584418/VRF)
Retrieved: 2026-04-30

```
/ip vrf
add name=TENANT-A interfaces=ether2,ether3
add name=TENANT-B interfaces=ether4

/ip route
add dst-address=10.50.0.0/16 gateway=10.0.0.254 \
    routing-table=TENANT-A
```

RouterOS 7+ supports VRFs via `/ip vrf add name=<vrf> interfaces=
<list>`, with per-interface membership encoded as a list on the
VRF declaration.  Per-VRF routing happens via `routing-table=<vrf>`
on `/ip route` rows.

Route-distinguisher / route-target / MP-BGP plumbing lives under
`/routing bgp` rather than the VRF block — RouterOS does not
collocate RD / RT with the VRF declaration.

The mikrotik_routeros codec does NOT yet parse `/ip vrf` — the
canonical `routing_instances` list is empty after parsing a
RouterOS source.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Multicast and Routing Guide
for 2930F / 2930M / 3810 / 5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MRG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba AOS-S has **no VRF concept** on the 2930F / 2930M / 3810 /
5400R platforms.  Single global routing table; no
`vrf definition` analogue, no per-interface VRF binding, no
`route-distinguisher` / `route-target` machinery.

`CanonicalIntent.routing_instances` is empty on Aruba target
render (no rendering path exists).

## Cross-vendor mapping

Both ends drop VRF data in this direction:

- RouterOS source -> Aruba target: even when the RouterOS source
  has `/ip vrf` declarations, the mikrotik_routeros codec does
  not populate `routing_instances` on parse (codec gap).  Aruba
  target also cannot accept VRFs structurally.

When RouterOS-side `/ip vrf` parsing lands, the cross-pair surface
will UPGRADE to **lossy** in this direction (RouterOS source can
carry VRFs; Aruba target structurally cannot — flatten to global
table with banner).

EVPN Type-5 routes: RouterOS does not model EVPN at all.  Aruba
has no MP-BGP / EVPN concept.  Field always empty on this cross-
pair.

VXLAN VNIs: both codecs list `/vxlan-vnis/vni` under `unsupported`
in their capability matrices.

### Disposition

| Field | Disposition |
|---|---|
| `routing_instances` | unsupported (RouterOS codec gap; Aruba target absent) |
| `interfaces[].vrf` | unsupported (codec gap; Aruba absent) |
| `vxlan_vnis` | unsupported (both ends list under unsupported) |
| `evpn_type5_routes` | unsupported (RouterOS does not model; Aruba has no EVPN) |
