# VRF (routing-instances): Cisco IOS-XE versus Aruba AOS-S

## Cisco IOS-XE

Source: [Cisco IOS XE 17.x MPLS Layer 3 VPNs Configuration Guide — Configuring VRF Definition](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/mp_l3_vpns/configuration/xe-17/mp-l3-vpns-xe-17-book.html)
Retrieved: 2026-04-30

Cisco VRF declaration uses `vrf definition <name>` plus
address-family stanzas:

```
vrf definition MGMT
 rd 65000:1
 address-family ipv4
  route-target import 65000:1
  route-target export 65000:1
 exit-address-family
!
interface GigabitEthernet0/0/0
 vrf forwarding MGMT
 ip address 198.51.100.1 255.255.255.252
```

Per-interface VRF membership is `vrf forwarding <name>`.  Per-VRF
static routes use `ip route vrf <name> ...`.  Per-VRF DNS / NTP /
SNMP exist via the `vrf <name>` modifier on the directive.

## Aruba AOS-S

AOS-S has **no VRF concept**.  The platform is a campus L2/L3
switch with a single global IP routing table; the manuals do not
document a `vrf` keyword.  Every L3 interface participates in the
same default routing table.

(Note: Aruba's CX-line — AOS-CX — DOES have a VRF concept, but that
is a different operating system and codec.  This pair targets the
ProCurve/AOS-S heritage line via the `aruba_aoss` codec.)

## Cross-vendor mapping

* Cisco `cisco_iosxe_cli` capability matrix declares
  `/routing-instances/instance` as `unsupported`: VRF declarations
  parse-and-ignore in v1, and per-interface `vrf forwarding`
  parse-and-ignore.
* Aruba `aruba_aoss` capability matrix does not list
  `/routing-instances/instance` as supported and never populates
  `CanonicalIntent.routing_instances` or
  `CanonicalInterface.vrf`.

Cross-pair disposition:

* `routing_instances` — **unsupported**.  Source codec parse-and-
  ignores; target codec has no concept.
* `interfaces[].vrf` — **unsupported**.  Same as above; the field
  stays empty on both sides.
* Per-VRF static routes — **lossy**.  Cisco source carries them
  via the `ip route vrf X ...` directive (the codec's static-route
  parser currently lacks a vrf field on `CanonicalStaticRoute`).
  The route is dropped on Cisco -> Aruba migration.

Disposition: **unsupported** for the entire VRF surface.
