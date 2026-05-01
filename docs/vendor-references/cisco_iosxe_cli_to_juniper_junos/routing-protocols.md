# Routing protocols (BGP / OSPF / IS-IS / EIGRP): Cisco IOS-XE versus Juniper Junos

Status of BGP, OSPF, IS-IS, EIGRP, and MPLS support on each codec.

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_bgp/configuration/xe-17/irg-xe-17-book.html (retrieved 2026-04-30)
- Cisco (OSPF): https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_ospf/configuration/xe-17/iro-xe-17-book.html (retrieved 2026-04-30)
- Juniper (BGP): https://www.juniper.net/documentation/us/en/software/junos/bgp/topics/topic-map/bgp-overview.html (retrieved 2026-04-30)
- Juniper (OSPF): https://www.juniper.net/documentation/us/en/software/junos/ospf/topics/topic-map/ospf-overview.html (retrieved 2026-04-30)

Citation ids: `cisco-bgp-cg`, `cisco-ospf-cg`, `junos-bgp-overview`, `junos-ospf-overview`.

## Cisco IOS-XE form

Stanza-form router config:

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

router eigrp 100
 network 10.0.0.0 0.0.0.255

ip routing
mpls ip
```

## Junos form

Hierarchical set-form:

```
set protocols bgp group EBGP type external
set protocols bgp group EBGP local-as 65001
set protocols bgp group EBGP neighbor 10.0.0.2 peer-as 65002
set protocols bgp group EVPN-OVERLAY family evpn signaling

set protocols ospf area 0.0.0.0 interface ge-0/0/0.0
set protocols ospf area 0.0.0.0 interface lo0.0 passive

set routing-options router-id 10.255.0.1
set routing-options autonomous-system 65001
```

EIGRP is Cisco-proprietary; Junos has no equivalent.

## Mapping notes

- **Canonical scope.** Neither codec models BGP, OSPF, IS-IS, or
  EIGRP at the canonical level today.  Both codec capability
  matrices list the routing-protocol paths under `unsupported` /
  parse-and-ignore.
- **EIGRP gap.** Cisco-only protocol; cross-vendor migration
  emits a banner directing the operator to implement OSPF or BGP
  manually on the Junos target.
- **BGP-EVPN intent.** Although BGP itself isn't modelled, the
  EVPN-VXLAN data-plane intent (per-VLAN VNI binding,
  per-VRF L3 VNI) IS modelled via `CanonicalVxlan` and
  `CanonicalRoutingInstance.l3_vni`.  Operators wire the
  control-plane BGP overlay manually.
- **Tier-3 raw_sections.** The codec parsers preserve unrecognised
  router stanzas in `raw_sections` (Tier-3) so operators can
  copy-paste the original config into a banner shown by the
  validation report.

Disposition: **unsupported** for the router stanza family on
both directions.  Documented in both codec capability matrices.
