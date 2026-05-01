# VRF / routing-instances: Arista EOS versus Aruba AOS-S

## Arista EOS

Source: [Arista EOS — Static Inter-VRF Route](https://www.arista.com/en/um-eos/eos-static-inter-vrf-route)
Retrieved: 2026-05-01

Arista EOS supports VRFs via `vrf instance <name>` plus per-
interface `vrf <name>` membership and BGP `vrf <name>` sub-
stanzas:

```
vrf instance TENANT_A
!
ip routing
ip routing vrf TENANT_A
!
interface Vlan100
   vrf TENANT_A
   ip address 10.100.0.1/24
!
router bgp 65001
   vrf TENANT_A
      rd 10.255.0.1:50100
      route-target import evpn 65000:50100
      route-target export evpn 65000:50100
```

The `arista_eos` codec capability matrix lists
`/routing-instances/instance` and
`/interfaces/interface/config/vrf` under **supported**.  The
parser walks `vrf instance` blocks AND `router bgp / vrf <name>`
to extract RD + RT communities; `CanonicalRoutingInstance`
records are emitted with the full VRF surface.

Arista also models L3 EVPN VNIs via `vxlan vrf <name> vni <N>`
inside the `interface Vxlan1` stanza, which the codec stores on
`CanonicalRoutingInstance.l3_vni`.

## Aruba AOS-S

AOS-S has **no VRF concept**.  The platform is a campus L2/L3
switch with a single global IP routing table.  The 16.10
Management and Configuration Guide does not document a `vrf`
keyword anywhere in the syntax.

Every L3 interface participates in the same default routing
table; per-tenant isolation is not in scope on AOS-S.

(Aruba's CX-line — AOS-CX — DOES have a VRF concept, but that
is a different OS and a different codec.  This pair targets the
ProCurve / AOS-S heritage line via the `aruba_aoss` codec.)

## Cross-vendor mapping

* Arista source populates `CanonicalIntent.routing_instances` and
  `CanonicalInterface.vrf` with rich data on real captures
  (vrf instance + RD + RT + per-interface vrf membership +
  optional l3_vni for EVPN Type-5).
* Aruba target has no render path — the `aruba_aoss` codec does
  not advertise `/routing-instances/instance` in its supported
  set (the path simply does not exist in AOS-S grammar).

So the field drops silently on Aruba render.  The validation
report surfaces an unsupported-path banner with operator
review-required marker.

This is the **major asymmetric loss** on the arista_eos ->
aruba_aoss direction.  Arista carries fully-modelled VRFs in DC
deployments; Aruba simply has no place to put them.

Per-VRF static routes (`ip route vrf X ...`) drop with the same
banner — the canonical static-route record has no VRF field, so
the data never even reaches the canonical tree (lossy at parse).

`apply_groups` / `group_content` are Junos-specific; neither
Arista nor Aruba populates them.

Disposition: **unsupported** (Arista source carries rich VRF
data; Aruba target has no render path; field drops with an
operator review-required banner).
