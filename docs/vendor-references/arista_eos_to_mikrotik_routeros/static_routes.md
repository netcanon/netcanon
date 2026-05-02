# Static routes: Arista EOS versus MikroTik RouterOS

## Arista EOS

Source: [Arista EOS — Routing Overview](https://www.arista.com/en/um-eos/eos-routing-overview)
Retrieved: 2026-05-01

```
ip routing
ip routing vrf TENANT_A

ip route 0.0.0.0/0 192.168.100.1
ip route 10.50.0.0/16 10.0.0.2

ipv6 unicast-routing

ipv6 route ::/0 2001:db8:0:1::2

ip route vrf TENANT_A 10.100.0.0/16 10.100.255.1
```

Arista uses **CIDR notation** for static-route destinations
(`ip route 10.50.0.0/16 10.0.0.2`) — no dotted-mask form on
modern EOS (older EOS releases accepted `ip route 10.50.0.0
255.255.0.0 10.0.0.2` for backward compatibility, but the
canonical-form output of `show running-config` always uses CIDR).

IPv6 routes use `ipv6 route` with the same CIDR form.  Per-VRF
routes use `ip route vrf <name> ...`.

The next-hop can be an IP address or an outgoing interface name
(`ip route 10.0.0.0/24 Ethernet1`).  Optional positional
parameters include administrative-distance and tag:

```
ip route 10.50.0.0/16 10.0.0.2 200 tag 100
```

Where `200` is the administrative distance and `tag 100` is the
route-tag.

The `arista_eos` codec capability matrix lists
`/routing/static-route` under **supported**.

## MikroTik RouterOS

Source: [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)
Retrieved: 2026-05-01

```
/ip route
add comment="Default route to ISP" dst-address=0.0.0.0/0 gateway=198.51.100.1
add comment="Branch network via core" dst-address=10.50.0.0/16 gateway=10.0.0.254
add comment="Blackhole RFC1918 leakage" dst-address=192.168.99.0/24 type=blackhole
add comment="Per-VRF route" dst-address=10.100.0.0/16 gateway=10.100.255.1 routing-table=TENANT_A

/ipv6 route
add dst-address=::/0 gateway=2001:db8:0:1::1
```

RouterOS uses **CIDR notation** natively (`dst-address=
10.50.0.0/16`).  The next-hop is `gateway=<ip>` for an IP
address or `gateway=<iface-name>` for an interface form.

Per-VRF routes use `routing-table=<name>` (RouterOS 7+ form,
formerly `routing-mark=` on RouterOS 6).

Special next-hop forms:

* `type=blackhole` for null-routed prefixes.
* `type=unreachable` / `type=prohibit` for ICMP-style discards.
* `distance=N` for administrative distance.

The `mikrotik_routeros` codec capability matrix lists
`/routing/static-route` under **supported**.

## Cross-vendor mapping

The canonical surface is `CanonicalIntent.static_routes:
list[CanonicalStaticRoute]` with fields `destination` (CIDR),
`gateway`, `interface`, `metric`, `description`.

Arista -> RouterOS round-trip:

* Arista `ip route 10.50.0.0/16 10.0.0.2` parses to
  `CanonicalStaticRoute(destination="10.50.0.0/16",
  gateway="10.0.0.2")`.  RouterOS render emits `/ip route add
  dst-address=10.50.0.0/16 gateway=10.0.0.2`.
* Arista `ipv6 route ::/0 2001:db8:0:1::2` parses to
  `CanonicalStaticRoute(destination="::/0",
  gateway="2001:db8:0:1::2")`.  RouterOS render emits `/ipv6
  route add dst-address=::/0 gateway=2001:db8:0:1::2`.
* Arista's interface-as-gateway form (`ip route X/N Ethernet1`)
  maps to RouterOS's interface form (`gateway=ether1`).
* Arista's positional administrative-distance (`ip route X/N GW
  200`) maps to RouterOS's `distance=200`.

Lossy bits:

* **Per-VRF routes:** Arista's `ip route vrf TENANT_A ...` drops
  to the global table on render because the canonical
  `CanonicalStaticRoute` model lacks a `vrf` field (deferred —
  lands alongside the broader VRF wire-up in both codecs).
  RouterOS's `routing-table=TENANT_A` form is similarly
  unreachable from the canonical layer in this direction.

* **Tag:** Arista's `tag <N>` route-tag has no canonical surface;
  drops on parse.  Operators using tag-based redistribution
  policy will see a banner.

* **Blackhole / Null0:** Arista's `Null0` interface form (legacy)
  is supported but the canonical model has no first-class
  blackhole flag — round-trip is semantic-equivalent but not
  byte-identical.

Disposition: **lossy** — default-VRF round-trips well; per-VRF /
tag / blackhole semantics drop with banners.
