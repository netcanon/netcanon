# Routing protocols (BGP / OSPF / EIGRP): Arista EOS versus Aruba AOS-S

## Arista EOS

Source: [Arista EOS — Border Gateway Protocol (BGP)](https://www.arista.com/en/um-eos/eos-border-gateway-protocol-bgp) and [Arista EOS — OSPF](https://www.arista.com/en/um-eos/eos-ospf)
Retrieved: 2026-05-01

Arista EOS supports a full DC-class routing protocol suite:

```
router bgp 65001
   router-id 10.255.0.1
   neighbor 10.0.0.0 remote-as 65000
   !
   vrf TENANT_A
      rd 10.255.0.1:50100
      route-target import evpn 65000:50100
   !
   address-family evpn
      neighbor 10.0.0.0 activate
!
router ospf 1
   router-id 10.255.0.1
   passive-interface default
   no passive-interface Ethernet1
```

Plus IS-IS (`router isis`), and PIM / IGMP for multicast.

The `arista_eos` codec capability matrix lists `/routing/bgp` and
`/routing/ospf` under **unsupported** with rationale "BGP
stanzas parse-and-ignore in v1 — neighbor tables, redistribution,
address-families are silently dropped" and "OSPF areas /
redistribution / interface-level cost tuning parse-and-ignore in
v1".

So while the BGP/OSPF data is on the wire and the parser walks
it for VRF + RD + RT extraction (the routing-instance side),
the actual neighbor / area / redistribution semantics never
land in canonical.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Multicast and Routing Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MRG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S supports OSPFv2/v3 (campus-class), RIP, and PIM-DM/SM —
but **not** BGP, IS-IS, or EIGRP.  No EVPN address-family
(VXLAN/EVPN are absent on the platform).

Example AOS-S OSPF:

```
router ospf
   area 0
   area 0.0.0.10 stub
   exit
interface 1
   ip ospf 1 area 0
```

The `aruba_aoss` codec does **not** advertise any
`/routing/bgp`, `/routing/ospf`, or `/routing/isis` paths in its
supported set — routing-protocol data is Tier-3 informational
only and parse-and-ignore.

## Cross-vendor mapping

* Arista source: BGP / OSPF / IS-IS data exists on the wire but
  is parse-and-ignore on the canonical layer (codec capability
  matrix unsupported).  EVPN-specific BGP details land on
  `routing_instances` records via the `vrf <name>` sub-stanza
  walker, but the neighbor / address-family / redistribution
  primitives don't reach canonical.
* Aruba target: no render path for any routing protocol surface
  beyond raw-section preservation.

So the dynamic routing protocol surface is **uniformly
unsupported on this direction**.  Operators migrating an Arista
DC-spine config to a campus AOS-S target should NOT expect any
BGP / OSPF data to land — the migration banner surfaces this as
"routing protocols dropped, manual configuration required".

EIGRP is Cisco-only on the WIRE (Arista has no EIGRP), so the
question doesn't arise on this direction.

Disposition: **unsupported** (Arista parse drops to canonical-
empty; Aruba render has no path either; one of those rare
"unsupported on both sides for the same canonical reason"
fields).
