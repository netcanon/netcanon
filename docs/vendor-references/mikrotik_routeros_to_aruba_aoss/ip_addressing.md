# IPv4 / IPv6 addressing: MikroTik RouterOS versus Aruba AOS-S

## MikroTik RouterOS

Source: [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)
Retrieved: 2026-04-30

```
/ip address
add address=198.51.100.2/30 interface=ether1
add address=10.0.0.1/24 interface=bridge1
add address=10.100.0.1/24 interface=vlan100
add address=10.255.0.1/32 interface=bond1

/ipv6 address
add address=2001:db8:0:1::2/64 interface=ether1
add address=fe80::1/64 interface=ether1 advertise=no
add address=2001:db8:100::1/64 interface=vlan100
```

RouterOS keeps IP addressing in a separate `/ip address` (and
`/ipv6 address`) section, decoupled from the interface declaration.
Each row binds a single CIDR address to an interface; multiple
addresses on one interface are multiple rows.

RouterOS infers IPv6 link-local-vs-global from the `fe80::/10`
prefix (no explicit keyword on the wire).  An `advertise=no`
attribute is RouterOS's way of saying "this is a link-local
administrative address; do not include in router advertisements".

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv6 Configuration Guide for
2930F / 2930M / 3810 / 5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv6/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
vlan 10
   ip address 10.10.10.1/24
   ipv6 address 2001:db8::1/64
   ipv6 address fe80::a:1/64 link-local
   exit

interface A1
   routing
   ip address 10.0.0.2/30
   ipv6 address 2001:db8:0:a::2/64
   exit
```

Aruba accepts both CIDR and dotted-mask IPv4 forms inside an
interface or VLAN stanza.  Per-interface routed addressing is
gated by the `routing` keyword (without which the port operates
L2-only).  IPv6 addresses can carry an explicit `link-local`
discriminator; without the keyword the address is treated as
global / scope=routable.

## Cross-vendor mapping

The canonical surface is

```
CanonicalInterface.ipv4_addresses: list[CanonicalIPv4Address]
CanonicalInterface.ipv6_addresses: list[CanonicalIPv6Address]
CanonicalIPv4Address(ip, prefix_length)
CanonicalIPv6Address(ip, prefix_length, scope)
```

IPv4 addressing round-trips cleanly: RouterOS `add address=
10.0.0.1/24 interface=ether1` lands on `(ip, prefix_length)`;
Aruba render emits `ip address 10.0.0.1/24` inside the routed
interface stanza (or inside the matching VLAN stanza for SVI
addresses on bridge interfaces).

IPv6 addressing round-trips with a small fidelity dip on the
**link-local** scope discriminator: RouterOS infers from the
`fe80::/10` prefix; Aruba uses an explicit `link-local` keyword.
Cross-vendor render works in either direction because both codecs
end up at the same scoped record.

### SVI absorption

RouterOS `/ip address add address=X/N interface=vlanY` populates
`CanonicalVlan.ipv4_addresses` (via the codec's interface-type
inference for the `vlanY` parent), and the Aruba target renderer
emits the address inside the matching `vlan Y / ip address X/N`
stanza (per AOS-S's `absorbs_svi_into_vlan: true` policy).

### Routed-vs-L2 binding

RouterOS bare `/interface ethernet` is L3 by default; binding it to
an `/ip address` line keeps it routed.  Aruba target render emits
the matching `routing` keyword inside the interface stanza so the
port operates as L3 on Aruba too.

### Disposition

| Field | Disposition |
|---|---|
| `interfaces[].ipv4_addresses` | good |
| `interfaces[].ipv6_addresses` | good (link-local scope preserved) |
| `vlans[].ipv4_addresses` (SVI absorption) | good |
| Routed-vs-L2 gate (`routing` keyword on Aruba) | good (synthesised on render from canonical L3 surface) |
