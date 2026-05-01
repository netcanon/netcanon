# Static routes: Aruba AOS-S versus MikroTik RouterOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv4 Configuration Guide for
2930F / 2930M / 3810 / 5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
ip default-gateway 10.0.0.1
ip route 192.168.99.0/24 10.0.0.254
ip route 172.16.0.0 255.255.0.0 10.0.0.254
```

Aruba accepts both CIDR and dotted-mask destination forms.  The
legacy `ip default-gateway <gw>` directive is shorthand for
`ip route 0.0.0.0/0 <gw>`; the codec normalises it on parse.
Aruba has **no VRF concept** — all static routes live in the global
table.

## MikroTik RouterOS

Source: [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)
Retrieved: 2026-04-30

```
/ip route
add dst-address=192.168.99.0/24 gateway=10.0.0.254
add dst-address=0.0.0.0/0 gateway=10.0.0.1
add dst-address=10.50.0.0/16 gateway=ether2
add dst-address=192.168.0.0/24 blackhole=yes
```

RouterOS uses `/ip route add dst-address=X/N gateway=Y` with CIDR
destinations.  The gateway can be either an IP address or an
interface name (`gateway=ether2` -> connected via interface).
Blackhole / unreachable / prohibit semantics are flag-encoded
(`blackhole=yes`, `type=unreachable`).

Per-routing-table routes use `routing-table=<name>` (RouterOS 7+
VRF model).  Default-table routes omit the attribute.

## Cross-vendor mapping

The canonical surface is

```
CanonicalStaticRoute(destination, gateway, interface, metric, description)
```

Default-table IPv4 routes round-trip cleanly:

- Aruba `ip route 192.168.99.0/24 10.0.0.254` -> RouterOS `/ip
  route add dst-address=192.168.99.0/24 gateway=10.0.0.254`
- Aruba `ip default-gateway 10.0.0.1` normalises to `0.0.0.0/0`
  destination; RouterOS render emits the equivalent `dst-address=
  0.0.0.0/0 gateway=10.0.0.1`.

The `interface` field on `CanonicalStaticRoute` round-trips for
Aruba-side absent (Aruba does not encode interface-as-gateway in
its static-route directive — it uses connected interfaces only).
RouterOS source `/ip route add gateway=ether2` populates the
interface field on parse and cross-vendor render emits an Aruba-
side comment because Aruba's `ip route` does not accept an
interface as gateway.

### Lossy bits

- **Per-VRF routes** — Aruba has no VRF concept, so the source
  side never populates a per-VRF route record.  Inverse direction
  RouterOS source has `/ip route routing-table=<name>` but the
  canonical schema lacks a `vrf` field on `CanonicalStaticRoute`
  (deferred — lands alongside VRF wire-up).  Per-VRF RouterOS
  source routes drop to the global table on render.
- **Blackhole / unreachable** — RouterOS has explicit flags
  (`blackhole=yes`, `type=unreachable`); Aruba expresses
  blackhole via `null0` interface-as-gateway form (which the
  aruba_aoss codec does not currently parse).  Cross-vendor
  fidelity is poor in either direction.
- **Metric** — Aruba accepts a per-route metric via
  `ip route X/N <gw> distance <D>` (the canonical model carries
  this on `metric`); RouterOS uses `distance=<N>`.  Round-trip
  preserves the value but the ordering convention differs slightly
  (Aruba's "distance" is administrative distance; RouterOS's
  "distance" is the same concept).

### Disposition

| Field | Disposition |
|---|---|
| `static_routes[].destination` | good |
| `static_routes[].gateway` | good (IP form); lossy when source uses interface-as-gateway |
| `static_routes[].interface` | lossy (Aruba does not encode; RouterOS does) |
| `static_routes[].metric` | good (round-trips) |
| `static_routes[].description` | lossy (RouterOS comment= maps; Aruba has no field) |
| Per-VRF (`routing-table=`) | unsupported (canonical schema gap) |
| Blackhole | lossy (flag-vs-interface encoding mismatch) |
