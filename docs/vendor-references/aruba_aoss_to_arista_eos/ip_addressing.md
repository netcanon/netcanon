# IPv4 / IPv6 addressing: Aruba AOS-S versus Arista EOS

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

vlan 10
   ip address 10.10.10.1 255.255.255.0
   ip address 10.10.20.1/24                ; both forms parse
   exit
```

Routed-port mode requires the explicit `routing` keyword inside
the interface stanza (a no-op on the canonical layer; codec
infers L3-vs-switchport from the presence of `ip address`).

The IPv6 link-local address is declared via the `link-local`
suffix keyword.  Aruba's `link-local` token is preserved in the
canonical model via `CanonicalIPv6Address.scope = "link-local"`.

## Arista EOS

Source: [Arista EOS — IPv4](https://www.arista.com/en/um-eos/eos-ipv4) and [Arista EOS — IPv6](https://www.arista.com/en/um-eos/eos-ipv6)
Retrieved: 2026-05-01

Arista EOS uses CIDR notation natively (Cisco-compatible grammar
but with the slash-prefix form preferred):

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

Routed-port semantics are inverted from Aruba — Arista defaults
all `Ethernet<N>` to L2 switchport; routed mode requires the
explicit `no switchport` directive.  The codec normalises both
on parse so the canonical layer sees only "is there an
ipv4_address?".

Arista's IPv6 link-local syntax matches Aruba's exactly — both
emit `ipv6 address fe80::X link-local`.

## Cross-vendor mapping

The canonical surface is `CanonicalIPv4Address(ip, prefix_length)`
and `CanonicalIPv6Address(ip, prefix_length, scope)`.

Aruba -> Arista round-trip:

* IPv4: prefix-length stays, no dotted-mask conversion needed
  (both vendors accept CIDR natively).  The legacy dotted-mask
  form Aruba accepts on parse normalises to CIDR on the canonical
  side and emits as CIDR on the Arista render.
* IPv6: identical syntax including the `link-local` discriminator.
  `CanonicalIPv6Address.scope` round-trips losslessly.
* Routed-port mode: Aruba's `routing` keyword and Arista's `no
  switchport` directive both translate to the canonical "no
  switchport_mode" state on parse.  Render emits the target
  vendor's form correctly.

The synthetic kitchen-sinks demonstrate the round-trip:

* Aruba kitchen-sink: `interface A1 / routing / ip address
  10.0.0.2/30 / ipv6 address 2001:db8:0:a::2/64 / ipv6 address
  fe80::a:2/64 link-local`
* Arista kitchen-sink (`ks-leaf-01`): `interface Ethernet1 / no
  switchport / ip address 10.0.0.1/31 / ipv6 address
  2001:db8:0:1::1/64 / ipv6 address fe80::1 link-local`

Disposition: **good** for both v4 and v6 addresses (CIDR-native
on both vendors; no dotted-mask conversion noise; link-local
syntax matches).
