# VRF / routing-instances: Aruba AOS-S versus Cisco IOS-XE

## Aruba AOS-S

AOS-S has **no VRF concept**.  The platform is a campus L2/L3
switch with a single global IP routing table.  The 16.10
Management and Configuration Guide does not document a `vrf`
keyword anywhere in the syntax.

Every L3 interface participates in the same default routing
table; per-tenant isolation is not in scope on AOS-S.

(Note: Aruba's CX-line — AOS-CX — DOES have a VRF concept, but
that is a different OS and a different codec.  This pair targets
the ProCurve/AOS-S heritage line via the `aruba_aoss` codec.)

## Cisco IOS-XE

Source: [Cisco IOS XE 17.x MPLS Layer 3 VPNs Configuration Guide — Configuring VRF Definition](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/mp_l3_vpns/configuration/xe-17/mp-l3-vpns-xe-17-book.html)
Retrieved: 2026-04-30

Cisco supports VRFs via `vrf definition <name>`:

```
vrf definition MGMT
 rd 65000:1
 address-family ipv4
  route-target import 65000:1
  route-target export 65000:1
 exit-address-family
```

The `cisco_iosxe_cli` codec capability matrix lists
`/routing-instances/instance` as **unsupported** — VRF
declarations parse-and-ignore in v1.

## Cross-vendor mapping

* Aruba source never populates `CanonicalIntent.routing_instances`
  or `CanonicalInterface.vrf` (no VRF concept).
* Cisco target does not consume them either (parse-and-ignore on
  the Cisco side; the canonical paths are listed unsupported).

So the field is structurally empty in both directions.

`apply_groups` and `group_content` are Junos-specific concepts;
neither Aruba nor Cisco populates them.

Disposition: **not_applicable** (Aruba source carries no VRF; the
field is never populated on this direction).
