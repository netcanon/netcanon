# IPv4 / IPv6 addressing: Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv6 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv6/2930F-3810-5400/index.htm)
Source: [Aruba ArubaOS-Switch 16.10 IPv4 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
interface A1
   routing
   ip address 10.0.0.2/30
   ipv6 address 2001:db8:0:a::2/64
   ipv6 address fe80::a:2/64 link-local
   enable
   exit

vlan 10
   name "USERS"
   untagged 1-12
   ip address 10.10.10.1 255.255.255.0
   exit
```

Notable AOS-S specifics:

- **Routed-port hint.**  The `routing` keyword tags the port as a
  L3 routed interface (no switchport behaviour).
- **IPv4 mask form is mixed.**  AOS-S accepts both CIDR
  (`ip address 10.0.0.2/30`) and dotted-decimal (`ip address
  10.0.0.2 255.255.255.252`).  The codec normalises to canonical
  prefix-length on parse.
- **IPv6 link-local discriminator.**  An explicit `link-local`
  suffix tags the address; the codec populates
  `CanonicalIPv6Address.scope = "link-local"`.
- **VLAN SVI absorption.**  L3 addresses can be configured inside
  the VLAN stanza directly (`vlan 10 / ip address ...`); the codec
  populates `CanonicalVlan.ipv4_addresses` rather than synthesising
  a separate `interface Vlan10` stanza (`absorbs_svi_into_vlan =
  True`).

## FortiGate FortiOS CLI

Source: [Fortinet FortiOS Administration Guide — Interface settings](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings).
Retrieved: 2026-04-30

```
config system interface
    edit "port1"
        set ip 198.51.100.2 255.255.255.252
        set ip6-address 2001:db8:cafe::2/64
        set allowaccess ping https ssh
        set status up
    next
end
```

Notable FortiOS specifics:

- **Mask is dotted-decimal** in `set ip` (FortiOS does not accept
  CIDR for IPv4 addresses).  The codec helper converts canonical
  prefix-length to dotted mask on render.
- **Single IPv4 primary per interface.**  FortiOS does not have a
  Cisco-style secondary-IP concept; the parse-time policy is to
  capture only the first IP address per interface.  Aruba sources
  rarely configure secondaries on routed ports.
- **IPv6 is `set ip6-address`** with CIDR.  FortiOS source carries
  no explicit `link-local` keyword; the codec defaults
  `CanonicalIPv6Address.scope = "global"` on parse.

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface:

```
class CanonicalIPv4Address(BaseModel):
    ip: str
    prefix_length: int
class CanonicalIPv6Address(BaseModel):
    ip: str
    prefix_length: int
    scope: str = "global"        # 'global' | 'link-local'
```

- **ipv4_addresses[].ip** — `good`.  Direct preservation; CIDR
  prefix on Aruba converts to FortiOS dotted-mask via the codec
  helper.
- **ipv4_addresses[].prefix_length** — `good`.  Same.
- **ipv4_addresses (multiple per interface)** — `lossy`.  Aruba
  rarely carries secondaries; FortiGate parse drops them.  Aruba
  -> FortiGate render emits only the first.
- **ipv6_addresses[].ip / prefix_length** — `good`.  Direct
  preservation.
- **ipv6_addresses[].scope** — `lossy` on link-local.  FortiOS
  source has no explicit scope keyword; FortiGate render emits
  link-local addresses without the discriminator (FortiOS
  auto-detects from `fe80::/10` prefix).

Disposition: **good** for primary IPv4 + IPv6 global; **lossy** for
IPv6 link-local scope round-trip and IPv4 secondaries (rare on
this direction).
