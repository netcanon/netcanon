# VRF / routing-instances: Aruba AOS-S versus MikroTik RouterOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Multicast and Routing Guide
for 2930F / 2930M / 3810 / 5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MRG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba AOS-S has **no VRF concept** on the 2930F / 2930M / 3810 /
5400R platforms.  The campus L2/L3 model assumes a single global
routing table — there is no `vrf definition` analogue, no per-
interface VRF binding, and no `route-distinguisher` / `route-target`
machinery on the wire.

`CanonicalIntent.routing_instances` is always empty on Aruba parse.
`CanonicalInterface.vrf` is always empty on Aruba parse.

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
VRF declaration (rather than per-interface as on Cisco).  Per-VRF
routing happens via `routing-table=<vrf>` on `/ip route` rows.

Route-distinguisher / route-target / MP-BGP plumbing lives under
`/routing bgp` rather than the VRF block — RouterOS does not
collocate RD / RT with the VRF declaration.

The mikrotik_routeros codec does NOT yet parse `/ip vrf` — the
canonical `routing_instances` list is empty after parsing a
RouterOS source.  The aruba_aoss codec does not parse VRFs either
(no concept).

## Cross-vendor mapping

Both ends of the pair currently drop VRF data:

- Aruba source -> RouterOS target: `routing_instances` always
  empty on parse (Aruba has no VRF), so RouterOS render emits
  nothing.
- RouterOS source -> Aruba target: Even when RouterOS source has
  `/ip vrf` declarations, the mikrotik_routeros codec does not
  populate `routing_instances` on parse.  Aruba target also
  cannot accept VRFs structurally, so the field is empty either
  way.

When RouterOS-side `/ip vrf` parsing lands, the cross-pair surface
will UPGRADE to **lossy** (RouterOS can carry VRFs; Aruba
structurally cannot).  At that point Aruba target will need a
banner explaining that the source-side VRFs have been flattened
to the global table.

EVPN Type-5 routes have the same disposition: Aruba has no MP-BGP /
EVPN concept; RouterOS does not model EVPN at all.  Field always
empty on this cross-pair regardless of direction.

VXLAN VNIs likewise: both codecs list `/vxlan-vnis/vni` under
`unsupported` in their capability matrices.

### Disposition

| Field | Disposition |
|---|---|
| `routing_instances` | unsupported (both ends do not model in v1) |
| `interfaces[].vrf` | unsupported (Aruba structurally absent; RouterOS codec gap) |
| `vxlan_vnis` | unsupported (both ends list under unsupported) |
| `evpn_type5_routes` | unsupported (Aruba has no EVPN; RouterOS does not model) |
