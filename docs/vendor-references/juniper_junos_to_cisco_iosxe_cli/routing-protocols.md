# Routing protocols (BGP / OSPF / IS-IS): Juniper Junos versus Cisco IOS-XE

Sources:
- Juniper (BGP): https://www.juniper.net/documentation/us/en/software/junos/bgp/topics/topic-map/bgp-overview.html (retrieved 2026-04-30)
- Juniper (OSPF): https://www.juniper.net/documentation/us/en/software/junos/ospf/topics/topic-map/ospf-overview.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_bgp/configuration/xe-17/irg-xe-17-book.html (retrieved 2026-04-30)
- Cisco (OSPF): https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_ospf/configuration/xe-17/iro-xe-17-book.html (retrieved 2026-04-30)

Citation ids: `junos-bgp-overview`, `junos-ospf-overview`, `cisco-bgp-cg`, `cisco-ospf-cg`.

## Junos form

```
set protocols bgp group EBGP type external
set protocols bgp group EBGP local-as 65001
set protocols bgp group EBGP neighbor 10.0.0.2 peer-as 65002
set protocols bgp group EVPN-OVERLAY type internal
set protocols bgp group EVPN-OVERLAY family evpn signaling

set protocols ospf area 0.0.0.0 interface ge-0/0/0.0
set protocols ospf area 0.0.0.0 interface lo0.0 passive

set policy-options policy-statement EXPORT-DIRECT term direct from protocol direct
set policy-options policy-statement EXPORT-DIRECT term direct then accept
set protocols bgp group EBGP export EXPORT-DIRECT

set routing-options router-id 10.255.0.1
set routing-options autonomous-system 65001
```

Junos uses `protocols bgp / group <NAME>` for neighbour grouping
(comparable to Cisco peer-groups), and `policy-options
policy-statement` for routing policy.

## Cisco IOS-XE form

```
router bgp 65001
 bgp router-id 10.255.0.1
 neighbor 10.0.0.2 remote-as 65002
 address-family ipv4
  neighbor 10.0.0.2 activate
 exit-address-family
 address-family l2vpn evpn
  neighbor 10.0.0.2 activate
 exit-address-family

router ospf 1
 router-id 10.255.0.1
 network 10.0.0.0 0.0.0.255 area 0
```

## Mapping notes

- **Out of canonical scope.** Neither Junos nor Cisco IOS-XE codec
  models BGP / OSPF / IS-IS at the canonical level today.  Both
  capability matrices list the routing-protocol paths under
  `unsupported` / parse-and-ignore.
- **Tier-3 raw_sections.** The codec parsers preserve unrecognised
  router stanzas in `raw_sections` (Tier-3) so operators can
  copy-paste the original config into a banner shown by the
  validation report.
- **EVPN data-plane intent.** Although BGP itself isn't modelled,
  the EVPN-VXLAN data-plane intent (per-VLAN VNI binding, per-VRF
  L3 VNI) IS modelled via `CanonicalVxlan` and
  `CanonicalRoutingInstance.l3_vni`.  Operators wire the
  control-plane BGP overlay manually after migration.
- **Policy plumbing asymmetry.** Junos's
  `policy-options policy-statement` is structurally distinct from
  Cisco's `route-map`; canonical doesn't model either.
  Cross-vendor migration of policy-statement intent is a known
  out-of-scope gap.
- **No EIGRP equivalent on Junos.** Cisco-only protocol; not
  applicable on Junos source.

Disposition: **unsupported** for the router protocol family on
both directions.  Documented in both codec capability matrices.
