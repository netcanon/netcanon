# IPv4 / IPv6 addressing: Aruba AOS-S versus Cisco IOS-XE

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv6 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv6/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S uses **CIDR prefix-length** notation for both v4 and v6.
SVI L3 absorbed into the VLAN stanza:

```
vlan 100
   ip address 192.168.10.1/24
   ipv6 address 2001:db8::1/64
   ipv6 address fe80::1/64 link-local
   exit
```

Per-routed-port (where AOS-S has L3 ports — uncommon on 2930F,
supported on 3810/5400R via `routing` directive):

```
interface 25
   routing
   ip address 198.51.100.1/30
```

Codec parses the AOS-S form into
`CanonicalInterface.ipv4_addresses[0] = CanonicalIPv4Address(ip="198.51.100.1", prefix_length=30)`.

## Cisco IOS-XE

Source: [Cisco IOS XE 17.x IP Addressing: ARP Configuration Guide](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr/configuration/xe-17/ipaddr-xe-17-book.html)
Retrieved: 2026-04-30

Cisco uses **dotted-decimal** subnet masks for IPv4:

```
interface Vlan100
 ip address 192.168.10.1 255.255.255.0
 ipv6 address 2001:db8::1/64
 ipv6 address fe80::1 link-local
```

Cisco's `secondary` keyword on additional `ip address` lines is
**not modelled** in the canonical tree — first address wins on
parse.

## Cross-vendor mapping

The canonical model normalises to prefix-length form on parse and
emits the vendor-native form on render:

* Aruba parse: read `/24` directly.
* Cisco render: convert to dotted mask via `_prefix_to_mask(24)`
  -> `"255.255.255.0"`.

The `link-local` discriminator on `CanonicalIPv6Address.scope`
preserves across both vendors.

Aruba -> Cisco specifics:

* Aruba's VLAN-centric SVI absorption (`vlan 100 / ip address X`)
  emits as `interface Vlan100 / ip address X N` on the Cisco
  side via the existing canonical -> Cisco render path.
* Aruba never carries Cisco-style `secondary` addresses, so this
  is a no-op direction.
* Aruba's `ipv6 address dhcp full` (DHCPv6 client) has no
  canonical equivalent — the parser drops the directive.

Disposition: **good** for the primary v4/v6 address.
