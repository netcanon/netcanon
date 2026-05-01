# VRF / routing-instances: Aruba AOS-S versus Arista EOS

## Aruba AOS-S

AOS-S has **no VRF concept**.  The platform is a campus L2/L3
switch with a single global IP routing table.  The 16.10
Management and Configuration Guide does not document a `vrf`
keyword anywhere in the syntax.

Every L3 interface participates in the same default routing
table; per-tenant isolation is not in scope on AOS-S.

(Note: Aruba's CX-line — AOS-CX — DOES have a VRF concept, but
that is a different OS and a different codec.  This pair targets
the ProCurve / AOS-S heritage line via the `aruba_aoss` codec.)

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
to extract RD + RT communities; the renderer emits the parent
`vrf instance <name>` block plus per-interface `vrf <name>` lines
plus the `router bgp / vrf <name>` sub-stanza.

Arista also models L3 EVPN VNIs via `vxlan vrf <name> vni <N>`
inside the `interface Vxlan1` stanza, which the codec stores on
`CanonicalRoutingInstance.l3_vni`.

## Cross-vendor mapping

* Aruba source never populates `CanonicalIntent.routing_instances`
  or `CanonicalInterface.vrf` (no VRF concept on the platform).
* Arista target ADVERTISES VRF support but has no source data to
  emit on this direction — the field is structurally empty.

So the field is structurally absent in this direction.  The
asymmetric loss is real but lives on the REVERSE direction
(arista_eos -> aruba_aoss), where Arista's rich VRF surface drops
on the Aruba target.

`apply_groups` and `group_content` are Junos-specific concepts;
neither Aruba nor Arista populates them.

Disposition: **not_applicable** (Aruba source carries no VRF;
the field is never populated on this direction).
