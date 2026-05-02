# VXLAN / EVPN / VRF: MikroTik RouterOS versus Arista EOS

## MikroTik RouterOS

Sources:
- [VRF — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/95584418/VRF)
- [Bridging and Switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/47579231/Bridging+and+Switching)

Retrieved: 2026-05-01

RouterOS has **no VXLAN / EVPN / MAC-VRF concept** in the
canonical-portable surface.

VRF support exists on RouterOS 7+ via `/ip vrf`:

```
/ip vrf
add interfaces=ether2,vlan100 name=TENANT_A
```

But:

* The `mikrotik_routeros` codec does NOT yet wire up `/ip vrf`
  parsing — the canonical `routing_instances` list is empty
  after parsing.
* Even when parser wire-up lands, RouterOS keeps RD/RT under BGP
  (`/routing bgp instance set ...`) rather than the VRF block.
* RouterOS has no L3-VNI / EVPN-Type-5 / MAC-VRF first-class
  concept.

VXLAN exists on RouterOS 7+ as `/interface vxlan`, but the
surface is incomplete relative to DC-fabric semantics — there is
no MAC-VRF, no EVPN-Type-2/5, no symmetric IRB.  The
`mikrotik_routeros` codec capability matrix explicitly lists:

```
unsupported=[
    UnsupportedPath(
        path="/vxlan-vnis/vni",
        reason=(
            "RouterOS VXLAN exists but is rare in canonical "
            "scope and not modelled in v1."
        ),
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

## Arista EOS

Sources:
- [Arista EOS — VXLAN Configuration](https://www.arista.com/en/um-eos/eos-vxlan-configuration)
- [Arista EOS — Configuring EVPN](https://www.arista.com/en/um-eos/eos-configuring-evpn)

Retrieved: 2026-05-01

Arista EOS has rich VXLAN / EVPN / VRF support — the platform is
purpose-built for DC fabric deployments.  See the inverse pair's
`vxlan_evpn_unsupported.md` for the full Arista-side grammar.

The `arista_eos` codec capability matrix lists
`/vxlan-vnis/vni`, `/vxlan-vnis/source-interface`,
`/vxlan-vnis/udp-port`, and `/routing-instances/instance` under
**supported** — Arista is the canonical fabric-bearing target
vendor.

## Cross-vendor mapping

In this direction (RouterOS source -> Arista target), the
asymmetry is **structural absence on the source side** rather
than absent render path on the target side:

* **VXLAN VNI bindings:** RouterOS source never carries fabric-
  class VXLAN/EVPN data into the canonical tree (codec lists the
  paths under unsupported).  Canonical `vxlan_vnis` is empty
  after parse.  Arista render produces no `interface Vxlan1`
  block — which is correct behaviour for a RouterOS source.

* **VRF / routing-instances:** RouterOS source has no parser
  wire-up for `/ip vrf` in v1; canonical `routing_instances` is
  empty after parse.  Arista render produces no `vrf instance`
  blocks.  When MikroTik-side parser wire-up lands (RouterOS 7+
  has `/ip vrf` support), the cross-pair surface will UPGRADE to
  lossy because RouterOS keeps RD/RT under BGP rather than the
  VRF block, and RouterOS has no MAC-VRF / L3-VNI / EVPN-Type-5
  first-class concept.  In v1, the cross-pair is empty.

* **EVPN Type-5 routes:** Same story; canonical empty after
  RouterOS parse, Arista render emits nothing.

* **MAC-VRF:** No RouterOS source data; no Arista render.

This is **the asymmetric direction with the least cross-vendor
loss** on the fabric surface — because RouterOS source carries
nothing fabric-related, there is nothing to drop.  Operators
wanting fabric features on the Arista target after migration
must configure them manually:

```
vrf instance TENANT_A
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan vlan 100 vni 10100
   vxlan vrf TENANT_A vni 50100
router bgp 65001
   address-family evpn
      neighbor 10.0.0.0 activate
   vrf TENANT_A
      rd 10.255.0.1:50100
      route-target import evpn 65000:50100
      route-target export evpn 65000:50100
```

— this is a manual post-migration step, not an automatic
translation.

The MikroTik synthetic kitchen-sink (`ks-edge-01`) carries no
VXLAN / EVPN / VRF data — none of the canonical fabric surfaces
populate after RouterOS parse.

Disposition: **unsupported** for `vxlan_vnis`,
`evpn_type5_routes`, and `routing_instances`.  RouterOS source
has no parse population; Arista target has no source data to
consume.  The fields stay empty regardless.
