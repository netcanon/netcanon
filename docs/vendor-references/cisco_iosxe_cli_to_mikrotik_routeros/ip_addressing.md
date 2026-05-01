# IP addressing: Cisco IOS-XE versus MikroTik RouterOS

## Cisco IOS-XE

Source: Cisco IOS XE IP Addressing Configuration Guide.

```
interface GigabitEthernet0/0/1
 ip address 192.0.2.1 255.255.255.0
 ip address 198.51.100.1 255.255.255.0 secondary
 ipv6 address 2001:db8::1/64
 ipv6 address fe80::1 link-local
```

Two notable shapes:

- IPv4 addresses are dotted-decimal mask form (`A.B.C.D MASK`); the
  `secondary` keyword piles additional v4 subnets on the same SVI.
- IPv6 always uses CIDR (`2001:db8::1/64`) and the `link-local`
  keyword forces a `fe80::/10` address into link-local scope.

## MikroTik RouterOS

Sources:
- [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)
- [VLAN — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN)
- [DHCP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/DHCP)

Retrieved: 2026-04-30

RouterOS decouples address declaration from the interface stanza
entirely.  Addresses live under `/ip address` (v4) and `/ipv6 address`
(v6); the interface stanza stays clean.

```
/ip address
add address=192.0.2.1/24 interface=ether1 network=192.0.2.0
add address=198.51.100.1/24 interface=ether1 network=198.51.100.0

/ipv6 address
add address=2001:db8::1/64 interface=ether1
add address=fe80::1 interface=ether1 advertise=no
```

Two notes:

- All IPv4 addresses are CIDR (`A.B.C.D/N`); RouterOS does not accept
  the dotted-mask form.  No `secondary` keyword — every `/ip address
  add` line is a peer.
- The `network` parameter is informational; RouterOS auto-derives it
  from `address` and the prefix-length.  `/export verbose` emits it;
  `/export` (terse) hides it.

## Cross-vendor mapping

The canonical surface is

```
CanonicalIPv4Address(ip: str, prefix_length: int)
CanonicalIPv6Address(ip: str, prefix_length: int, scope: "global" | "link-local")
```

Both codecs convert from / to dotted-mask <-> CIDR transparently.
The `secondary` keyword on Cisco is treated as "another address on
the same interface" canonically — equivalent to a second
`/ip address add` line on MikroTik, so it round-trips without
loss.

The IPv6 `scope` discriminator was added in the canonical model
specifically so cross-vendor link-local handling stays intact;
both codecs preserve it.

`dhcp_client` (the `interfaces[].dhcp_client` flag) maps:
Cisco's `ip address dhcp` to MikroTik's `/ip dhcp-client add
interface=etherN disabled=no`.  Cross-vendor good.

### Disposition

| Field | Disposition |
|---|---|
| `interfaces[].ipv4_addresses` | good |
| `interfaces[].ipv6_addresses` | good |
| `interfaces[].dhcp_client` | good |
