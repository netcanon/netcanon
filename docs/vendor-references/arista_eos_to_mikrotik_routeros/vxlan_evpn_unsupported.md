# VXLAN / EVPN / VRF: Arista EOS versus MikroTik RouterOS

## Arista EOS

Sources:
- [Arista EOS — VXLAN Configuration](https://www.arista.com/en/um-eos/eos-vxlan-configuration)
- [Arista EOS — Configuring EVPN](https://www.arista.com/en/um-eos/eos-configuring-evpn)

Retrieved: 2026-05-01

Arista EOS has rich VXLAN / EVPN / VRF support — the platform is
purpose-built for DC fabric deployments.

```
vrf instance TENANT_A
!
ip routing
ip routing vrf TENANT_A
!
interface Vlan100
   description "Tenant A data SVI"
   vrf TENANT_A
   ip address 10.100.0.1/24
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
   router-id 10.255.0.1
   neighbor 10.0.0.0 remote-as 65000
   !
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
   !
```

The `arista_eos` codec capability matrix lists the following under
**supported**:

```
"/vxlan-vnis/vni",
"/vxlan-vnis/source-interface",
"/vxlan-vnis/udp-port",
"/routing-instances/instance",
"/interfaces/interface/config/vrf",
```

The parser populates:

* `CanonicalIntent.vxlan_vnis`: a `CanonicalVxlan` record per
  `vxlan vlan N vni M` line, carrying `source_interface` and
  `udp_port` broadcast across all records for the VTEP.
* `CanonicalIntent.routing_instances`: a `CanonicalRoutingInstance`
  per `vrf instance <name>`, with RD/RT bindings under `router
  bgp / vrf <name>` and L3-VNI from `vxlan vrf <name> vni <N>`.
* `CanonicalRoutingInstance.l3_vni`: from `vxlan vrf X vni N`.
* `CanonicalInterface.vrf`: per-interface VRF binding from `vrf
  TENANT_A` on `interface Vlan100` etc.
* `CanonicalRoutingInstance` with `instance_type="mac-vrf"`: from
  `router bgp / vlan N` per-VLAN MAC-VRF bindings.

EVPN Type-5 IP-prefix advertisements are an IMPLICIT property of
`CanonicalRoutingInstance.l3_vni` (any subnet carried by a
VRF-assigned interface gets announced).  The
`CanonicalEvpnType5Route` per-prefix list is lossy by default
(no codec populates it today).

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
  (`/routing bgp instance set ...`) rather than the VRF block,
  so the `route_distinguisher` / `rt_imports` / `rt_exports`
  fields will be lossy on the cross-pair (different vendor wire
  shape).
* RouterOS has no L3-VNI / EVPN-Type-5 / MAC-VRF first-class
  concept.

The `mikrotik_routeros` codec capability matrix explicitly lists:

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

(Note: VXLAN does technically exist on RouterOS 7+ as
`/interface vxlan`, but the surface is incomplete relative to
DC-fabric semantics — there is no MAC-VRF, no EVPN-Type-2/5,
no symmetric IRB.  The codec opts out of modelling it in v1.)

## Cross-vendor mapping

This is the **major asymmetric loss** in this direction.

* **VXLAN VNI bindings:** Arista carries rich `CanonicalIntent.
  vxlan_vnis` data (source_interface, udp_port, per-VLAN-to-VNI
  mappings).  RouterOS has no render path — the data drops with
  an operator review-required banner.

* **VRF / routing-instances:** Arista carries fully-modelled
  VRFs with RD/RT/l3_vni.  RouterOS has no canonical render path
  in v1.  Per-interface VRF binding (`CanonicalInterface.vrf`)
  drops on render because the target has no VRF concept the
  codec can land it in.

* **EVPN Type-5 routes:** Implicit on Arista via VRF + l3_vni;
  no equivalent on RouterOS.  Operators wanting overlay routing
  on the RouterOS target after migration must re-implement using
  out-of-canonical-scope mechanisms (BGP per-VRF instances on
  RouterOS 7+, plus firewall-based isolation, plus
  policy-routing).

* **MAC-VRF:** Arista's `router bgp / vlan N / rd ... / route-
  target both` per-VLAN MAC-VRF bindings live in
  `CanonicalRoutingInstance` records with
  `instance_type="mac-vrf"`.  RouterOS has no MAC-VRF concept;
  drops on render.

The Arista synthetic kitchen-sink (`ks-leaf-01`) carries:

```
vrf instance TENANT_A
interface Vxlan1 / vxlan source-interface Loopback0
                / vxlan udp-port 4789
                / vxlan vlan 10 vni 10010
                / vxlan vlan 20 vni 10020
                / vxlan vlan 100 vni 10100
                / vxlan vrf TENANT_A vni 50100
router bgp 65001 / vlan 100 / rd 10.255.0.1:100 / route-target both 65000:100
                 / vrf TENANT_A / rd 10.255.0.1:50100
                                / route-target import/export evpn 65000:50100
```

— five VNI records (4 L2-VNI + 1 L3-VNI), one VRF-with-l3_vni,
one MAC-VRF record.  All drop on the RouterOS render with
operator review-required banners.

This is **the major asymmetric loss** on the arista_eos ->
mikrotik_routeros direction.  Arista's rich DC fabric data has
no home on a router-first RouterOS target.  Operators planning
this migration should carefully evaluate whether the canonical-
portable subset (basic services, L3 addressing, static routes,
VLAN sub-interfaces) is sufficient for their use case — fabric-
overlay semantics will need to be re-built from scratch on the
RouterOS side.

Disposition: **unsupported** for `vxlan_vnis`,
`evpn_type5_routes`, and `routing_instances`.  Arista source
carries rich data; RouterOS target has no render path; the
fields drop with operator review-required banners.
