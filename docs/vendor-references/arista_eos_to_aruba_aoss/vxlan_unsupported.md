# VXLAN / EVPN: Arista EOS versus Aruba AOS-S

## Arista EOS

Source: [Arista EOS — VXLAN Configuration Example](https://eos.arista.com/vxlan-configuration-example/) and [Arista TechHub — L2VPN-EVPN](https://www.arista.com/en/um-eos/eos-section-19-1-evpn)
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
   vlan 100
      rd 10.255.0.1:100
      route-target both 65000:100
      redistribute learned
   !
   vrf TENANT_A
      rd 10.255.0.1:50100
      route-target import evpn 65000:50100
      route-target export evpn 65000:50100
   !
   address-family evpn
      neighbor 10.0.0.0 activate
```

The `arista_eos` codec capability matrix lists `/vxlan-vnis/vni`,
`/vxlan-vnis/source-interface`, `/vxlan-vnis/udp-port`, and
`/routing-instances/instance` under **supported**.  The parser
populates `CanonicalIntent.vxlan_vnis` with a `CanonicalVxlan`
record per VLAN-to-VNI mapping (carrying source_interface +
udp_port broadcast across all records for the VTEP).

L3 VNI (the `vxlan vrf <name> vni <N>` line) lands on
`CanonicalRoutingInstance.l3_vni`.

EVPN MAC-VRF (the `router bgp / vlan N` per-VLAN binding) lands
as a `CanonicalRoutingInstance` with `instance_type="mac-vrf"`.

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

## Cross-vendor mapping

* Arista source populates `CanonicalIntent.vxlan_vnis` with rich
  per-VLAN mappings, source-interface, and UDP port.  The
  Arista synthetic kitchen-sink (`ks-leaf-01`) carries five VNI
  records: VLAN 10/20/100 + L3-VNI 50100 for `vrf TENANT_A`.
* Aruba target has no render path — the codec's capability
  matrix lists every VXLAN xpath under `unsupported`.  The data
  drops on render with an operator review-required banner.

`evpn_type5_routes` drops with the same banner — the L3 VNI on
`CanonicalRoutingInstance.l3_vni` has no Aruba emission path
either (the entire VRF concept is missing).

EVPN MAC-VRF records (`instance_type="mac-vrf"`) face the same
fate — Aruba has no MAC-VRF concept.  The records sit in
`routing_instances` after parse and silently drop on Aruba
render.

This is **the major asymmetric loss** on the arista_eos ->
aruba_aoss direction.  Arista's rich DC fabric data has no home
on a campus AOS-S target.

Disposition: **unsupported** (Arista source carries rich
VXLAN/EVPN data; Aruba target has no render path; field drops
with an operator review-required banner).
