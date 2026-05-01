# IP addressing: MikroTik RouterOS versus Cisco IOS-XE

## MikroTik RouterOS

Sources:
- [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)
- [IPv6 Address — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328149/IPv6+Address)

Retrieved: 2026-04-30

RouterOS keeps address declarations in a separate plane from the
interface stanza:

```
/ip address
add address=192.0.2.1/24 interface=ether1 network=192.0.2.0
add address=198.51.100.1/24 interface=ether1

/ipv6 address
add address=2001:db8::1/64 interface=ether1
add address=fe80::1 interface=ether1 advertise=no
```

All v4 addresses are CIDR (`/N`); RouterOS does not accept dotted-
mask form.  No `secondary` keyword — every `add` line is a peer
address.

## Cisco IOS-XE

Source: Cisco IOS XE IP Addressing Configuration Guide.

```
interface GigabitEthernet0/0/1
 ip address 192.0.2.1 255.255.255.0
 ip address 198.51.100.1 255.255.255.0 secondary
 ipv6 address 2001:db8::1/64
 ipv6 address fe80::1 link-local
```

IPv4 is dotted-decimal mask form on Cisco; IPv6 is CIDR with
`link-local` keyword for `fe80::/10` scope.

## Cross-vendor mapping

The canonical surface is

```
CanonicalIPv4Address(ip, prefix_length)
CanonicalIPv6Address(ip, prefix_length, scope: "global" | "link-local")
```

Both codecs convert dotted-mask <-> CIDR transparently.

### Multiple v4 addresses on one interface

RouterOS source with multiple `/ip address add ... interface=ether1`
lines maps to Cisco render with the first address as primary and
the rest as `secondary`.  This convention preserves operational
semantics; both vendors treat the order as priority.

### IPv6 link-local

RouterOS's `advertise=no` on a `fe80::/10` address is the codec's
parse cue for link-local scope (RouterOS does not require an
explicit keyword).  Render emits Cisco's `link-local` keyword
when `scope="link-local"`.

### dhcp_client

RouterOS's `/ip dhcp-client add interface=etherN disabled=no` maps
to Cisco's `ip address dhcp` on the interface stanza.  Round-trip
clean.

### Disposition

| Field | Disposition (MikroTik -> Cisco) |
|---|---|
| `interfaces[].ipv4_addresses` | good |
| `interfaces[].ipv6_addresses` | good |
| `interfaces[].dhcp_client` | good |
