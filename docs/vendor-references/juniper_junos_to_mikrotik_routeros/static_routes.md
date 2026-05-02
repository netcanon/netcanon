# Static routes: Juniper Junos versus MikroTik RouterOS

How static routes are declared on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/topic-map/static-routing-overview.html (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing (retrieved 2026-05-01)

Citation ids: `junos-static-routing`, `mikrotik-ip-routing`.

## Junos form

```
set routing-options static route 0.0.0.0/0 next-hop 10.0.0.2
set routing-options static route 10.50.0.0/16 next-hop 10.0.0.3
set routing-options static route ::/0 next-hop 2001:db8::2

set routing-instances TENANT_A routing-options static route \
    192.168.10.0/24 next-hop 10.0.10.1
```

Junos uses CIDR notation natively (`X/N` for IPv4; same form for
IPv6).  Per-VRF static routes nest under `routing-instances <name>`.
Junos exposes a `preference` scalar (administrative distance
analogue) and richer next-hop options (`qualified-next-hop` for
weighted multi-NH, `discard` / `reject` for blackhole).

## RouterOS form

```
/ip route
add comment="Default route to ISP" dst-address=0.0.0.0/0 gateway=198.51.100.1
add comment="Branch network" dst-address=10.50.0.0/16 gateway=10.0.0.254
add comment="Blackhole" dst-address=192.168.99.0/24 gateway=bridge1 \
    type=blackhole

/ipv6 route
add dst-address=::/0 gateway=2001:db8:0:1::1

# RouterOS 7+ per-VRF route:
/ip route
add dst-address=10.0.10.0/24 gateway=10.0.10.1 routing-table=tenant-a
```

RouterOS uses CIDR natively as well.  Gateway can be either an IP or
an interface name (`gateway=ether1` is valid).  Per-VRF static routes
on RouterOS 7+ live under the same `/ip route` section with a
`routing-table=<vrf-name>` parameter; the canonical model lacks a
`vrf` field on `CanonicalStaticRoute` so this is currently lossy
(deferred — lands alongside VRF wire-up).

## Cross-vendor mapping

* CIDR <-> CIDR: direct mapping for IPv4 and IPv6 destinations.
* `next-hop <ip>` -> `gateway=<ip>`: identical semantic.
* IPv6 default route (`::/0`): supported on both via the same CIDR
  shape.
* `metric` / `preference`: Junos `preference` (administrative-
  distance analogue) and RouterOS `distance` are vendor-specific
  scalars not 1:1; canonical `metric` is the operator-visible metric,
  not preference / AD.
* Per-VRF: Junos `routing-instances <X> routing-options static` ->
  RouterOS `/ip route ... routing-table=X`.  Lossy in the canonical
  v1 because `CanonicalStaticRoute` lacks a `vrf` field — Junos source
  per-VRF routes flatten to the global table on RouterOS render.
* Junos's `qualified-next-hop` (weighted multi-NH) flattens to
  multiple canonical entries on parse; RouterOS render emits each
  as a separate `/ip route` record (no native multi-NH composite on
  RouterOS).

Disposition: **lossy** overall — default-VRF IPv4 + IPv6 static routes
round-trip cleanly; per-VRF entries flatten to global; preference /
metric semantics drift; qualified-next-hop expands.
