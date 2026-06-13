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
ways.  Per-VRF static routes are handled asymmetrically on this pair:
the `cisco_iosxe_cli` target renders the `ip route vrf X ...` form and
the canonical `CanonicalStaticRoute.vrf` field carries the
discriminator, but the `arista_eos` source codec does not yet parse
`ip route vrf X ...` into that field (it declares
`/routing/static-route/vrf` `unsupported`), so on Arista -> Cisco the
VRF never reaches canonical and the route lands in the global table.
This is an Arista parse-side gap, not a canonical-model gap; see
`vrf.md`.

Disposition: **good** for default-VRF routes; **lossy** for VRF-scoped
routes (Arista source does not yet parse the per-VRF form).
