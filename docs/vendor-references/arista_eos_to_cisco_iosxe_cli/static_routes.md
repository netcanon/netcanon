# Static routes: Arista EOS versus Cisco IOS-XE

## Arista EOS

Source: [EOS 4.36.0F — IPv4](https://www.arista.com/en/um-eos/eos-ipv4)
Retrieved: 2026-04-30

Arista uses CIDR throughout:

```
switch(config)# ip route 172.17.252.0/24 vlan 500
switch(config)# ip route 0.0.0.0/0 192.14.0.4
```

Optional admin-distance trails the next-hop, same as Cisco.

VRF-scoped:

```
ip route vrf TENANT 10.1.0.0/24 192.0.2.1
```

## Cisco IOS-XE

Source: Cisco IOS XE Routing Configuration Guide — `ip route` command
reference.

Cisco syntax uses dotted-quad mask + next-hop:

```
ip route 10.1.0.0 255.255.255.0 192.0.2.1
ip route 10.2.0.0 255.255.0.0 GigabitEthernet1/0/1
ip route 0.0.0.0 0.0.0.0 192.0.2.1
ip route vrf TENANT 10.1.0.0 255.255.255.0 192.0.2.1
```

Optional administrative-distance integer trails the next-hop:

```
ip route 10.1.0.0 255.255.255.0 192.0.2.1 200
```

## Cross-vendor mapping

The canonical model stores destination as CIDR
(`CanonicalStaticRoute.destination: str  # CIDR notation`) plus a
gateway and optional outgoing interface.  Both codecs convert at the
boundary; round-trip is lossless within the canonical surface.

Tracked fields (gateway, interface, metric, description) survive both
ways.  Per-VRF static routes (`ip route vrf X ...`) are currently
parse-and-ignore in v1 — the canonical `CanonicalStaticRoute` lacks a
`vrf` field.  This is a known gap that lands alongside richer VRF
wire-up; see `vrf.md`.

Disposition: **good** for default-VRF routes; **lossy** for VRF-scoped
routes (canonical model gap).
