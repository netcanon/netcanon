# Routing protocols (BGP / OSPF / EIGRP): Arista EOS versus Cisco IOS-XE

## Arista EOS

Source: [EOS 4.36.0F — Border Gateway Protocol (BGP)](https://www.arista.com/en/um-eos/eos-border-gateway-protocol-bgp)
Source: [EOS 4.36.0F — Open Shortest Path First Version 2 (OSPFv2)](https://www.arista.com/en/um-eos/eos-open-shortest-path-first-version-2)
Retrieved: 2026-04-30

OSPF (near-identical to Cisco):

```
router ospf 1
 router-id 10.0.0.1
 network 10.0.0.0/24 area 0
 redistribute connected
```

Note Arista uses CIDR for `network` statements; Cisco uses
wildcard-mask (`0.0.0.255` style).

BGP (near-identical):

```
router bgp 65001
 router-id 10.0.0.1
 neighbor 10.0.0.2 remote-as 65002
 neighbor 10.0.0.2 update-source Loopback0
 address-family ipv4
  network 10.1.0.0/16
  neighbor 10.0.0.2 activate
```

EIGRP: **not supported on Arista**.

## Cisco IOS-XE

Source: Cisco IOS XE IP Routing Configuration Guide — BGP / OSPF /
EIGRP.

OSPF:

```
router ospf 1
 router-id 10.0.0.1
 network 10.0.0.0 0.0.0.255 area 0
 redistribute connected subnets
```

BGP:

```
router bgp 65001
 router-id 10.0.0.1
 neighbor 10.0.0.2 remote-as 65002
 neighbor 10.0.0.2 update-source Loopback0
 address-family ipv4
  network 10.1.0.0 mask 255.255.0.0
  neighbor 10.0.0.2 activate
 exit-address-family
```

EIGRP:

```
router eigrp 100
 network 10.0.0.0 0.255.255.255
 no auto-summary
```

EIGRP is Cisco-proprietary (now an open standard via RFC 7868 but
without ecosystem adoption beyond Cisco).  Irrelevant on this
direction since Arista source can never carry EIGRP.

## Cross-vendor mapping

Routing protocols are **out of canonical scope** in v1.  No
`CanonicalBGP` / `CanonicalOSPF` / `CanonicalEIGRP` models exist.

Both codecs declare these stanzas as parse-and-ignore:

- Arista EOS: capability matrix lists `/routing/bgp` and
  `/routing/ospf` under `unsupported` with explicit rationale ("BGP
  stanzas parse-and-ignore in v1 — neighbor tables, redistribution,
  address-families are silently dropped" and "OSPF areas /
  redistribution / interface-level cost tuning parse-and-ignore in
  v1.").
- Cisco IOS-XE: top-of-file Limitations docstring states "Routing
  protocols (BGP/OSPF), ACLs, crypto, AAA-policy, QoS, and route-maps
  are silently skipped on parse and not emitted on render — out of
  canonical scope."

Note that the Arista codec DOES partially walk `router bgp` for the
specific purpose of extracting per-VRF RD + RT communities (see
`vrf.md` and `mac_vrf.md`); but the BGP topology itself (neighbors,
address-families, route-maps) is dropped.

Disposition: **unsupported** (Tier 3 informational on both vendors;
no canonical model).  Reason: routing-protocol intent requires a
substantial canonical model (neighbor tables, address-families, route-
maps) and is gated on a future audit pass.
