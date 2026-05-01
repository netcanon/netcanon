# Static routes: Cisco IOS-XE versus MikroTik RouterOS

## Cisco IOS-XE

Source: Cisco IOS XE IP Routing: Protocol-Independent Configuration
Guide.

```
ip route 0.0.0.0 0.0.0.0 198.51.100.1
ip route 10.0.0.0 255.255.255.0 192.0.2.1 100
ip route 10.10.0.0 255.255.0.0 GigabitEthernet0/0/2
ip route vrf TENANT-A 10.20.0.0 255.255.0.0 192.0.2.5
```

Cisco's classic form takes destination + dotted-decimal mask + next-
hop, with optional administrative distance and an optional `vrf`
name prefix for per-VRF routes.

## MikroTik RouterOS

Source: [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)

Retrieved: 2026-04-30

```
/ip route
add dst-address=0.0.0.0/0 gateway=198.51.100.1
add dst-address=10.0.0.0/24 gateway=192.0.2.1 distance=100
add dst-address=10.10.0.0/16 gateway=ether2
add dst-address=10.20.0.0/16 gateway=192.0.2.5 routing-table=TENANT-A
```

RouterOS's form is `dst-address=` (CIDR) + `gateway=` (next-hop
address OR outgoing interface).  Per-VRF routing uses
`routing-table=<name>` (RouterOS 7+); pre-v7 used a separate
`/ip route vrf` namespace.

Optional fields include `distance=` (administrative distance,
matching Cisco's), `comment=`, `blackhole=yes`,
`suppress-hw-offload=yes`.

## Cross-vendor mapping

The canonical surface is

```
CanonicalStaticRoute(destination: str, gateway: str, interface: str,
                     metric: int, description: str)
```

`destination` is CIDR; both codecs convert to/from dotted-mask as
needed.  `gateway` is the next-hop IP; `interface` is populated when
the source declared an outgoing-interface form.  `metric` maps to
Cisco's distance field and RouterOS's `distance=` parameter.

### Per-VRF routes

The canonical model **does not yet carry a `vrf` field** on
`CanonicalStaticRoute` — the cross-vendor VRF-aware static route is
deferred until the canonical schema gains the field.  Today, both
codecs preserve the parsed route (Cisco's `ip route vrf X ...` line
and RouterOS's `/ip route add routing-table=X ...` line) but
emit them under the global / default routing table on render.

### Disposition

| Field | Disposition |
|---|---|
| `static_routes[].destination` | good |
| `static_routes[].gateway` | good |
| `static_routes[].interface` | good (Cisco interface gateway form -> `gateway=ether2`) |
| `static_routes[].metric` | good |
| `static_routes[].description` | good |
| Per-VRF static routes (canonical schema gap) | lossy (drops to default VRF on render) |
