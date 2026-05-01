# IPv4 / IPv6 addressing: Aruba AOS-S versus MikroTik RouterOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv6 Configuration Guide for
2930F / 2930M / 3810 / 5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv6/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba accepts both CIDR (`ip address 10.10.10.1/24`) and dotted-mask
(`ip address 10.10.10.1 255.255.255.0`) forms inside an interface
or VLAN stanza.  The codec normalises to CIDR on parse.

```
vlan 10
   name "USERS"
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

Per-interface routed addressing is gated by `routing` (without
which the port operates as L2-only).  IPv6 addresses can carry an
explicit `link-local` discriminator; without the keyword the
address is treated as global / scope=routable.

## MikroTik RouterOS

Source: [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)
Retrieved: 2026-04-30

RouterOS keeps IP addressing in a separate `/ip address` (and
`/ipv6 address`) section, decoupled from the interface declaration:

```
/ip address
add address=10.10.10.1/24 interface=vlan10
add address=10.0.0.2/30 interface=ether1

/ipv6 address
add address=2001:db8::1/64 interface=vlan10
add address=fe80::1/64 interface=ether1 advertise=no
```

Each `/ip address` row binds a single CIDR address to an interface;
multiple addresses on one interface are multiple rows.  RouterOS
infers IPv6 link-local-vs-global from the `fe80::/10` prefix
(no explicit keyword).  An explicit `advertise=no` is RouterOS's
way of saying "this is a link-local administrative address; do not
include in router advertisements".

## Cross-vendor mapping

The canonical surface is

```
CanonicalInterface.ipv4_addresses: list[CanonicalIPv4Address]
CanonicalInterface.ipv6_addresses: list[CanonicalIPv6Address]
CanonicalIPv4Address(ip, prefix_length)
CanonicalIPv6Address(ip, prefix_length, scope)  # scope: "global" | "link-local"
```

IPv4 addressing round-trips cleanly: Aruba's CIDR or dotted-mask
form lands on `(ip, prefix_length)`; RouterOS render emits one
`/ip address add address=X/N interface=Y` per address.

IPv6 addressing round-trips with a small fidelity dip on the
**link-local** discriminator: Aruba uses an explicit `link-local`
keyword (canonical `scope="link-local"`); RouterOS infers from the
`fe80::/10` prefix.  Cross-vendor render works in either direction
because both codecs end up at the same scoped record, but a manual
edit on RouterOS that omits the auto-inferred scope (e.g. an
operator-typed `2001:db8::ff/64` on a routed interface) preserves
on round-trip.

VLAN SVI absorption interacts with the addressing here: Aruba
parses `vlan 10 / ip address X/N` directly into
`CanonicalVlan.ipv4_addresses`.  The RouterOS render
materialises this as a synthetic `/interface vlan add name=vlan10
vlan-id=10 interface=<bridge>` plus `/ip address add address=X/N
interface=vlan10`.  The choice of parent interface (the bridge name)
is a render-time policy decision — operators may need to rebind to
the correct trunk after migration.

### Disposition

| Field | Disposition |
|---|---|
| `interfaces[].ipv4_addresses` | good |
| `interfaces[].ipv6_addresses` | good (link-local discriminator preserved) |
| `vlans[].ipv4_addresses` (SVI absorption) | good |
| Routed-vs-L2 gate (`routing` keyword on Aruba) | not_applicable on canonical (interface_type discriminates) |
