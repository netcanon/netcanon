# VXLAN / EVPN: Aruba AOS-S versus Arista EOS

## Aruba AOS-S

AOS-S has **no VXLAN concept**.  The platform is a campus L2/L3
switch — VXLAN and EVPN are DC-fabric features that AOS-S
deliberately does not model.  The 16.10 Management and
Configuration Guide makes no reference to VXLAN, VTEP, VNI, or
EVPN.

The `aruba_aoss` codec capability matrix explicitly lists:

```
unsupported=[
    UnsupportedPath(
        path="/vxlan-vnis/vni",
        reason="VXLAN not modelled — AOS-S is a campus L2/L3 codec.",
    ),
    UnsupportedPath(
        path="/vxlan-vnis/source-interface",
        reason="VXLAN not modelled (see /vxlan-vnis/vni).",
    ),
    UnsupportedPath(
        path="/vxlan-vnis/udp-port",
        reason="VXLAN not modelled (see /vxlan-vnis/vni).",
    ),
]
```

So `CanonicalIntent.vxlan_vnis` is **always empty** when the
source is parsed by `aruba_aoss`.

## Arista EOS

Source: [Arista EOS — VXLAN Configuration Example](https://eos.arista.com/vxlan-configuration-example/)
Retrieved: 2026-05-01

Arista EOS has rich VXLAN / EVPN support:

```
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan udp-port 4789
   vxlan vlan 10 vni 10010
   vxlan vlan 20 vni 10020
   vxlan vlan 100 vni 10100
   vxlan vrf TENANT_A vni 50100
!
router bgp 65001
   address-family evpn
      neighbor 10.0.0.0 activate
```

The `arista_eos` codec capability matrix lists `/vxlan-vnis/vni`,
`/vxlan-vnis/source-interface`, and `/vxlan-vnis/udp-port` under
**supported**.  The Arista synthetic kitchen-sink (`ks-leaf-01`)
exercises this exhaustively: VLAN-to-VNI mappings (10010, 10020,
10100), L3 VNI for `vrf TENANT_A` (50100), explicit
`source-interface Loopback0`, explicit `udp-port 4789`.

## Cross-vendor mapping

* Aruba source never populates `CanonicalIntent.vxlan_vnis` (no
  concept on the platform).
* Arista target ADVERTISES VXLAN support but has no source data
  to emit on this direction — the field is structurally empty.

So the field is structurally absent on this direction.  The
asymmetric loss is real but lives on the REVERSE direction
(arista_eos -> aruba_aoss), where Arista's VXLAN data drops
silently on the Aruba target with an `unsupported` capability
hit.

`evpn_type5_routes` follows the same pattern — Aruba never
populates the per-prefix EVPN list; Arista parses it into
`CanonicalRoutingInstance.l3_vni` (a VRF property), but with no
Aruba VRF concept the L3 VNI value also drops.

Disposition: **not_applicable** (Aruba source carries no VXLAN
data; the field is never populated on this direction).
