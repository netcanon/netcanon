# Static routes: MikroTik RouterOS versus Juniper Junos

<!-- junos-route-preference -->
> **Update 2026-11-12 — a route's distance is written as its Junos `preference`.**  Up to 0.7.7 the Junos render wrote destination and next hop only, so a route's distance was lost and a floating route came out as a second next hop of the same preference, carrying traffic beside the route it backs up.  The next hops at a destination's lowest distance are now written `next-hop <address>` with one `route <prefix> preference <n>` line, and each other next hop `qualified-next-hop <address> preference <n>` ("The qualified next-hop preference and metric override the route preference and metric", Juniper, "Static Route Preferences and Qualified Next Hops").  A destination whose next hops mix a stated and an unstated distance is a known limitation: the unstated one is written at the Junos default, 5.  What the body below says of the distance on this pair predates this.

<!-- junos-rib-inet6 -->
> **Update 2026-11-12 — an IPv6 static route is written under `rib inet6.0`.**  Up to 0.7.7 the Junos render wrote an IPv6 static route under `routing-options static`, as an IPv4 route is.  Junos holds an IPv6 static route in `inet6.0`, `set routing-options rib inet6.0 static route ...` ([Juniper, Example: Configuring IPv6 Static Routes](https://www.juniper.net/documentation/en_US/junos12.3/topics/example/policy-ipv6-static-routes.html)), and in a routing instance in `<instance>.inet6.0` ("In a routing instance, the routing table name must include the routing instance name", [Juniper, rib (Routing Options)](https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/ref/statement/rib-edit-routing-options.html)).  The render now writes it there, and the Junos parser reads it back.  The body's `set routing-options static route ::/0 ...` is the form the render wrote before.

<!-- ipv6-route-section -->
> **Update 2026-11-12 — an IPv6 route of `/ipv6 route` is read.**  Up to 0.7.7 the RouterOS parser read no `/ipv6 route` section, and every IPv6 route of a RouterOS config was lost on every target, with nothing said, whatever the body below says of it.  `/ipv6 route` is now read with the keys of `/ip route` ([MikroTik, IP Routing](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing): "To add or remove routes /ip(ipv6) route menus should be used"), and a route of another routing table, a disabled route and a route that discards are left out of it and said as they are there.  Until the change in the note above, the Junos render wrote it under `routing-options static`.

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
  A route whose `gateway=` is an interface alone (`gateway=ether1`)
  is read as the route's interface, and is not written: the Junos
  renderer writes `next-hop <gateway>` only and declares
  `/routing/static-route/interface` unsupported, so the job's report
  lists the route.  (Updated 2026-11-05: up to 0.7.7 the RouterOS
  parser read the name as the gateway, and it was written as a Junos
  next hop naming an interface the device does not have.)
* IPv6 default (`::/0`): supported on both via the same CIDR shape.
  RouterOS `/ipv6 route` is parsed by the codec separately; canonical
  records carry the v6 prefix shape.
* `metric` / `distance`: RouterOS `distance=` is the AD analogue;
  Junos `preference` is also AD; canonical `metric` is the operator-
  visible metric, not preference / AD — drift on round-trip.
* Per-VRF: RouterOS `/ip route ... routing-table=X` -> Junos
  `routing-instances X routing-options static`.  Lossy on this pair
  because the `mikrotik_routeros` source codec does not parse the
  `routing-table=X` form (it declares `/routing/static-route/vrf`
  `unsupported`), so `CanonicalStaticRoute.vrf` is never populated
  from this source and there is no VRF to carry — the Junos target
  would render `set routing-instances X routing-options static route
  ...` if one were present.
* RouterOS `type=blackhole` -> Junos `discard` is structurally
  similar but not modelled canonically — drops to a simple
  destination-only record.

Disposition: **lossy** overall — default-VRF IPv4 + IPv6 round-trip
cleanly; per-VRF entries flatten to global; preference / metric
semantics drift; blackhole / type semantics drop.
