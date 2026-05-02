# Static routes: MikroTik RouterOS versus Arista EOS

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
10.50.0.0/16`).  The next-hop is `gateway=<ip>` for an IP address
or `gateway=<iface-name>` for an interface form.

Per-VRF routes use `routing-table=<name>` (RouterOS 7+ form;
formerly `routing-mark=` on RouterOS 6).

Special next-hop forms:

* `type=blackhole` for null-routed prefixes
* `type=unreachable` / `type=prohibit` for ICMP-style discards
* `distance=N` for administrative distance

The `mikrotik_routeros` codec capability matrix lists
`/routing/static-route` under **supported**.

## Arista EOS

Source: [Arista EOS — Routing Overview](https://www.arista.com/en/um-eos/eos-routing-overview)
Retrieved: 2026-05-01

```
ip routing
ip routing vrf TENANT_A

ip route 0.0.0.0/0 192.168.100.1
ip route 10.50.0.0/16 10.0.0.2
ip route 192.168.99.0/24 Null0
ip route vrf TENANT_A 10.100.0.0/16 10.100.255.1

ipv6 unicast-routing

ipv6 route ::/0 2001:db8:0:1::2
```

Arista uses **CIDR notation** for static-route destinations
(`ip route 10.50.0.0/16 10.0.0.2`).  Per-VRF routes use `ip
route vrf <name> ...`.  Blackhole routes use the `Null0`
interface form.

The `arista_eos` codec capability matrix lists
`/routing/static-route` under **supported**.

## Cross-vendor mapping

The canonical surface is `CanonicalIntent.static_routes:
list[CanonicalStaticRoute]` with fields `destination` (CIDR),
`gateway`, `interface`, `metric`, `description`.

RouterOS -> Arista round-trip:

* RouterOS `/ip route add dst-address=10.50.0.0/16
  gateway=10.0.0.254` parses to `CanonicalStaticRoute(destination=
  "10.50.0.0/16", gateway="10.0.0.254")`.  Arista render emits
  `ip route 10.50.0.0/16 10.0.0.254`.
* RouterOS `/ipv6 route add dst-address=::/0 gateway=
  2001:db8:0:1::1` -> Arista `ipv6 route ::/0 2001:db8:0:1::1`.
* RouterOS's interface form (`gateway=ether2`) maps to Arista's
  interface-as-gateway form (`ip route X/N Ethernet2`) via the
  rename mesh.
* RouterOS's `distance=N` -> Arista's positional administrative-
  distance.

Lossy bits:

* **Per-VRF routes:** RouterOS's `routing-table=TENANT_A` drops
  to default VRF on render because the canonical model lacks a
  vrf field on `CanonicalStaticRoute` (deferred — lands
  alongside VRF wire-up in both codecs).

* **Blackhole:** RouterOS's `type=blackhole` flag has no
  canonical surface — the codec encodes it via the `Null0`
  next-hop interface name on Arista side, which is semantic-
  equivalent but not byte-identical.

* **type=unreachable / prohibit:** RouterOS supports these ICMP-
  style discard forms; Arista does not have direct equivalents
  beyond `Null0`.  Drops with banner.

* **comment:** RouterOS source `comment=` lifts to canonical
  `description`; Arista has no per-route description field —
  drops on render with banner.

The MikroTik synthetic kitchen-sink carries four IPv4 routes
(default + RFC1918 branch + blackhole + IPv6 default).  The
default and branch routes round-trip cleanly; the blackhole
maps to `Null0` semantic-equivalent; the IPv6 default lifts
through the canonical IPv6 path.

Disposition: **lossy** — default-table / IPv4 + IPv6 round-trip
well; per-VRF / blackhole-flag / per-route comment drop with
banners.
