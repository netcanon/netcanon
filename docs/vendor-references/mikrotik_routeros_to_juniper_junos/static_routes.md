# Static routes: MikroTik RouterOS versus Juniper Junos

How static routes are declared on each platform.

Sources:
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/topic-map/static-routing-overview.html (retrieved 2026-05-01)

Citation ids: `mikrotik-ip-routing`, `junos-static-routing`.

## RouterOS form

```
/ip route
add comment="Default route to ISP" dst-address=0.0.0.0/0 gateway=198.51.100.1
add comment="Branch network via core" dst-address=10.50.0.0/16 gateway=10.0.0.254
add comment="Blackhole" dst-address=192.168.99.0/24 type=blackhole

/ipv6 route
add dst-address=::/0 gateway=2001:db8:0:1::1

# RouterOS 7+ per-VRF route:
/ip route
add dst-address=10.0.10.0/24 gateway=10.0.10.1 routing-table=tenant-a
```

RouterOS uses CIDR natively.  Gateway can be either an IP or an
interface name (`gateway=ether1` is valid).  Per-VRF static routes
on RouterOS 7+ live under the same `/ip route` section with a
`routing-table=<vrf-name>` parameter.

## Junos form

```
set routing-options static route 0.0.0.0/0 next-hop 10.0.0.2
set routing-options static route 10.50.0.0/16 next-hop 10.0.0.3
set routing-options static route 192.168.99.0/24 discard
set routing-options static route ::/0 next-hop 2001:db8::2

set routing-instances TENANT_A routing-options static route \
    192.168.10.0/24 next-hop 10.0.10.1
```

Junos uses CIDR notation natively.  Per-VRF static routes nest under
`routing-instances <name>`.  Junos exposes a `preference` scalar
(administrative-distance analogue), `qualified-next-hop` for weighted
multi-NH, and `discard` / `reject` for blackhole.

## Cross-vendor mapping

* CIDR -> CIDR: direct mapping for IPv4 and IPv6.
* `gateway=` -> `next-hop`: identical semantic for IP next-hops.
  RouterOS interface-as-gateway form (`gateway=ether1`) maps to
  Junos's `next-hop` of the corresponding interface name (Junos
  accepts interface next-hops as well).
* IPv6 default (`::/0`): supported on both via the same CIDR shape.
  RouterOS `/ipv6 route` is parsed by the codec separately; canonical
  records carry the v6 prefix shape.
* `metric` / `distance`: RouterOS `distance=` is the AD analogue;
  Junos `preference` is also AD; canonical `metric` is the operator-
  visible metric, not preference / AD — drift on round-trip.
* Per-VRF: RouterOS `/ip route ... routing-table=X` -> Junos
  `routing-instances X routing-options static`.  Lossy in canonical
  v1 (no `vrf` field on `CanonicalStaticRoute`).
* RouterOS `type=blackhole` -> Junos `discard` is structurally
  similar but not modelled canonically — drops to a simple
  destination-only record.

Disposition: **lossy** overall — default-VRF IPv4 + IPv6 round-trip
cleanly; per-VRF entries flatten to global; preference / metric
semantics drift; blackhole / type semantics drop.
