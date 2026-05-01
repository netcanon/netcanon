# IPv4 / IPv6 addressing: Arista EOS versus Aruba AOS-S

## Arista EOS

Source: [Arista EOS — IPv4](https://www.arista.com/en/um-eos/eos-ipv4) and [Arista EOS — IPv6](https://www.arista.com/en/um-eos/eos-ipv6)
Retrieved: 2026-05-01

Arista EOS uses CIDR notation natively:

```
interface Ethernet1
   no switchport
   ip address 10.0.0.1/31
   ipv6 address 2001:db8:0:1::1/64
   ipv6 address fe80::1 link-local
!
interface Vlan100
   ip address 192.168.10.1/24
```

Routed-port mode requires the explicit `no switchport` directive
(EOS defaults `Ethernet<N>` to L2 access).  IPv6 link-local
addresses are declared via the `link-local` suffix keyword.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv6 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv6/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba accepts addresses in either CIDR or dotted-mask form, but
emits CIDR uniformly in `show running-config`:

```
interface A1
   routing
   ip address 10.0.0.2/30
   ipv6 address 2001:db8:0:a::2/64
   ipv6 address fe80::a:2/64 link-local
   enable
   exit
```

Routed-port mode requires the explicit `routing` keyword (the
inverse of Arista's `no switchport`).  IPv6 link-local syntax
matches Arista's exactly.

## Cross-vendor mapping

The canonical surface is `CanonicalIPv4Address(ip, prefix_length)`
and `CanonicalIPv6Address(ip, prefix_length, scope)`.

Arista -> Aruba round-trip:

* IPv4: prefix-length stays, no dotted-mask conversion needed
  (both vendors emit CIDR natively).
* IPv6: identical syntax including the `link-local` discriminator.
  `CanonicalIPv6Address.scope` round-trips losslessly.
* Routed-port mode: Arista's `no switchport` and Aruba's `routing`
  keyword both translate to the canonical "no switchport_mode"
  state on parse.  Render emits the target vendor's form
  correctly.

MTU is currently **not parsed** by the `aruba_aoss` codec — the
field is empty on Aruba's parse side, so the Arista source's
`mtu 9214` jumbo-frame setting drops on Aruba render.  This is a
codec-side wire-up gap.

The Arista synthetic kitchen-sink (`ks-leaf-01`) carries:

```
interface Ethernet1
   no switchport
   mtu 9214                              ; drops on Aruba render
   ip address 10.0.0.1/31
   ipv6 address 2001:db8:0:1::1/64
   ipv6 address fe80::1 link-local
```

— addresses round-trip cleanly; `mtu` drops with a banner.

Disposition: **good** for v4 / v6 addresses (CIDR-native on both
vendors; link-local syntax matches); **lossy** for `mtu`
(canonical field is populated by Arista parse but Aruba render
has no MTU emission path).
