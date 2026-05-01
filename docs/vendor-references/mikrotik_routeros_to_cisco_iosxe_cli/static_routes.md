# Static routes: MikroTik RouterOS versus Cisco IOS-XE

## MikroTik RouterOS

Source: [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)

Retrieved: 2026-04-30

```
/ip route
add dst-address=0.0.0.0/0 gateway=198.51.100.1
add dst-address=10.0.0.0/24 gateway=192.0.2.1 distance=100
add dst-address=10.10.0.0/16 gateway=ether2
add dst-address=10.20.0.0/16 gateway=192.0.2.5 routing-table=TENANT-A
add dst-address=10.30.0.0/16 blackhole=yes
```

RouterOS additional features:

- `gateway=` accepts an outgoing-interface name (e.g. `ether2`)
  for connected-style routes.
- `distance=` is the administrative distance (matches Cisco's).
- `routing-table=<name>` (RouterOS 7+) declares per-VRF static
  routes.
- `blackhole=yes` sets a discard route.
- `suppress-hw-offload=yes` opts a route out of ASIC offload.

## Cisco IOS-XE

Source: Cisco IOS XE IP Routing: Protocol-Independent Configuration
Guide.

```
ip route 0.0.0.0 0.0.0.0 198.51.100.1
ip route 10.0.0.0 255.255.255.0 192.0.2.1 100
ip route 10.10.0.0 255.255.0.0 GigabitEthernet0/0/2
ip route vrf TENANT-A 10.20.0.0 255.255.0.0 192.0.2.5
ip route 10.30.0.0 255.255.0.0 Null0
```

Cisco prefixes per-VRF routes with `vrf <name>` and uses `Null0` as
the blackhole next-hop.

## Cross-vendor mapping

The canonical surface is

```
CanonicalStaticRoute(destination, gateway, interface, metric, description)
```

### Direct round-trip behaviour

- `dst-address` <-> `<dest> <mask>` (CIDR <-> dotted-mask, codec
  converts).
- `gateway=192.0.2.1` <-> `<gw>`.
- `gateway=ether2` <-> outgoing-interface form
  (`ip route 10.10.0.0 255.255.0.0 GigabitEthernet0/0/2`); the
  rename mesh maps interface names.
- `distance=100` <-> trailing administrative distance.
- `comment=` -> `description` field (Cisco `name` keyword on
  `ip route`); good.

### Lossy points

- **blackhole**: `blackhole=yes` -> `Null0` next-hop is a
  semantic equivalent but the canonical model has no first-class
  blackhole flag.  Cisco render uses the `Null0` interface name
  in the `interface` field; round-trip is round-trip-equivalent
  but not byte-equivalent.
- **routing-table** (per-VRF): canonical model lacks a `vrf`
  field on `CanonicalStaticRoute` today.  Per-VRF routes from
  RouterOS source drop to the global / default routing table on
  Cisco render.

### Disposition

| Field | Disposition (MikroTik -> Cisco) |
|---|---|
| `static_routes[].destination` | good |
| `static_routes[].gateway` | good |
| `static_routes[].interface` | good (gateway-as-interface form maps) |
| `static_routes[].metric` | good |
| `static_routes[].description` | good |
| Per-VRF routes (canonical schema gap) | lossy (drops to default VRF on render) |
| `blackhole=yes` (no canonical flag) | lossy (encoded via `Null0` interface name; semantic-equivalent) |
