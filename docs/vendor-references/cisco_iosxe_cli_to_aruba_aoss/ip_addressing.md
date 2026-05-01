# IPv4 / IPv6 addressing: Cisco IOS-XE versus Aruba AOS-S

## Cisco IOS-XE

Source: [Cisco IOS XE 17.x IP Addressing: ARP Configuration Guide](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr/configuration/xe-17/ipaddr-xe-17-book.html)
Retrieved: 2026-04-30

Cisco uses **dotted-decimal subnet masks** for IPv4:

```
interface GigabitEthernet0/0/0
 ip address 192.0.2.1 255.255.255.0
 ipv6 address 2001:db8::1/64
 ipv6 address fe80::1 link-local
```

The `ipv6 address ... link-local` form requires the explicit
`link-local` keyword on Cisco; otherwise the address falls under
`family inet6 global`.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv6 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv6/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S uses **CIDR prefix-length notation** for both v4 and v6 and
embeds the SVI's L3 address inside the VLAN stanza (there is no
separate `interface Vlan<N>`):

```
vlan 100
   name "USERS"
   ip address 192.168.10.1/24
   ipv6 address 2001:db8::1/64
   ipv6 address fe80::1/64 link-local
   exit
```

The `link-local` discriminator is identical to Cisco's keyword.  AOS-S
also accepts `ipv6 address dhcp full` (DHCPv6 client) but the SLAAC
case is the bare `ipv6 enable` directive.

## Cross-vendor mapping

The canonical model stores both forms as
`CanonicalIPv4Address(ip, prefix_length)` /
`CanonicalIPv6Address(ip, prefix_length, scope)` — the dotted-mask
versus CIDR distinction is normalised on parse.  The codecs convert:

* Cisco parse: `_mask_to_prefix("255.255.255.0")` -> `24`.
* Aruba parse: read the trailing `/24` directly.
* Cisco render: `_prefix_to_mask(24)` -> `"255.255.255.0"`.
* Aruba render: emit `192.168.10.1/24`.

Round-trip is lossless on the address + prefix-length tuple.  The
`scope` discriminator (`global` / `link-local`) preserves across both
vendors via the explicit `link-local` keyword.

The known Cisco-side limitation (single-line `ip address` only —
`secondary` addresses are dropped on parse) is documented in the
codec's parse module; this is a Cisco -> Aruba lossy path, not
Aruba -> Cisco.

Disposition: **good** for the primary address.  **Lossy** for Cisco
secondaries and for `ipv6 address dhcp` semantics that have no
canonical equivalent.
