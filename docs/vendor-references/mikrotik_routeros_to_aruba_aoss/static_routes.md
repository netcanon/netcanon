# Static routes: MikroTik RouterOS versus Aruba AOS-S

## MikroTik RouterOS

Source: [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)
Retrieved: 2026-04-30

```
/ip route
add comment="Default route to ISP" dst-address=0.0.0.0/0 \
    gateway=198.51.100.1
add comment="Branch network via core" dst-address=10.50.0.0/16 \
    gateway=10.0.0.254
add comment="Blackhole RFC1918 leakage" dst-address=192.168.99.0/24 \
    gateway=bridge1
add comment="IPv6 default" dst-address=::/0 gateway=2001:db8:0:1::1
add dst-address=10.10.0.0/16 gateway=10.0.0.254 \
    routing-table=TENANT-A
```

RouterOS `/ip route add dst-address=X/N gateway=Y` with CIDR
destinations.  Gateway can be either an IP address or an interface
name (`gateway=ether2`).  Blackhole / unreachable / prohibit
semantics are flag-encoded (`blackhole=yes`, `type=unreachable`).
Per-VRF routes use `routing-table=<name>`.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv4 Configuration Guide for
2930F / 2930M / 3810 / 5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
ip default-gateway 10.0.0.1
ip route 192.168.99.0/24 10.0.0.254
ip route 172.16.0.0 255.255.0.0 10.0.0.254
```

Aruba accepts both CIDR and dotted-mask forms.  `ip default-gateway
<gw>` is shorthand for `ip route 0.0.0.0/0 <gw>`; the codec
normalises on parse.  Aruba has **no VRF concept** — all static
routes live in the global table.

## Cross-vendor mapping

The canonical surface is

```
CanonicalStaticRoute(destination, gateway, interface, metric, description)
```

Default-table IPv4 routes round-trip cleanly:
- RouterOS `dst-address=192.168.99.0/24 gateway=10.0.0.254` ->
  Aruba `ip route 192.168.99.0/24 10.0.0.254`
- RouterOS `dst-address=0.0.0.0/0 gateway=10.0.0.1` -> Aruba
  `ip route 0.0.0.0/0 10.0.0.1` (the legacy `ip default-gateway`
  form is not the codec's render-time choice; canonical CIDR maps
  to explicit `ip route 0.0.0.0/0 <gw>` on render).

### Lossy bits

- **Per-VRF routes** — RouterOS source `routing-table=TENANT-A`
  drops to the global table on render because the canonical
  schema lacks a `vrf` field on `CanonicalStaticRoute` (deferred —
  lands alongside VRF wire-up).  Aruba target has no VRF
  concept anyway, so the loss is structural.
- **Blackhole / unreachable** — RouterOS has explicit
  `blackhole=yes` / `type=unreachable` flags; the canonical model
  does not carry this.  Aruba expresses blackhole via `null0`
  interface-as-gateway form which the aruba_aoss codec does not
  currently parse.  Cross-vendor fidelity is poor — RouterOS
  source blackhole routes drop on render with a banner.
- **Interface-as-gateway** — RouterOS `gateway=ether2` (connected
  via interface) populates `CanonicalStaticRoute.interface` on
  parse.  Aruba's `ip route` directive does not accept an
  interface as gateway; canonical interface-only routes drop on
  Aruba render with a banner.
- **IPv6 routes** — RouterOS `/ip route add dst-address=::/0` with
  IPv6 destination populates the canonical static-route record
  with an IPv6 destination.  The aruba_aoss codec render path
  for IPv6 static routes is not currently implemented; v6 routes
  drop on Aruba target with a banner.

### Disposition

| Field | Disposition |
|---|---|
| `static_routes[].destination` | good (IPv4); lossy (IPv6 not rendered on Aruba target) |
| `static_routes[].gateway` | good (IP form); lossy (interface form not on Aruba) |
| `static_routes[].interface` | lossy (RouterOS encodes; Aruba does not) |
| `static_routes[].metric` | good |
| `static_routes[].description` | lossy (RouterOS comment= maps; Aruba has no field) |
| Per-VRF (`routing-table=`) | unsupported (canonical schema gap; Aruba has no VRF) |
| Blackhole | lossy (RouterOS flag drops; Aruba has no canonical blackhole) |
