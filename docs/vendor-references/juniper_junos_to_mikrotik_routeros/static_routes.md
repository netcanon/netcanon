# Static routes: Juniper Junos versus MikroTik RouterOS

<!-- junos-rib-inet6 -->
> **Update 2026-11-12 — an IPv6 static route of `rib inet6.0` is read.**  Junos holds an IPv6 static route in `inet6.0`, `set routing-options rib inet6.0 static route ...` ([Juniper, Example: Configuring IPv6 Static Routes](https://www.juniper.net/documentation/en_US/junos12.3/topics/example/policy-ipv6-static-routes.html)), and in a routing instance in `<instance>.inet6.0` ("In a routing instance, the routing table name must include the routing instance name", [Juniper, rib (Routing Options)](https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/ref/statement/rib-edit-routing-options.html)).  Up to 0.7.7 the Junos parser read no `rib` line, and such a route was lost on every target, with nothing said, whatever the body below says of it.  A static route of `rib inet.0` and `rib inet6.0`, and of the instance's own two tables, is now read as one of `static` is; a static route of any other table is left out, and one row counts them.  The body's `set routing-options static route ::/0 ...` is not where Junos holds an IPv6 route.

<!-- ipv6-route-section -->
> **Update 2026-11-12 — an IPv6 route is written into `/ipv6 route`.**  Up to 0.7.7 the RouterOS render wrote every route, the IPv6 ones included, as an `add` of `/ip route`, the menu of the IPv4 routes ([MikroTik, IP Routing](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing): "To add or remove routes /ip(ipv6) route menus should be used").  Each route is now written into the section of its family, and the RouterOS parser reads both.  What the body below says of an IPv6 route onto RouterOS was written before that.

<!-- vrf-route-left-out -->
> **Update 2026-11-12 — a route of a VRF is left out of a RouterOS output under a review line.**  Up to 0.7.7 the RouterOS render wrote a route of another vendor's VRF as an `add` of `/ip route`, a route of the main table, where it routed traffic the source routed in another VRF; the job was `partial` for the route's VRF and said nothing more.  The output makes no VRF or routing table, and it now writes `# review: static route <destination> is in VRF <name>, and the output puts nothing in a VRF; not written` in its place.  On the committed inputs the 5 routes of a VRF, on 4 cells, are left out.  What follows about a route of a VRF on the RouterOS side describes the output before this change.

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
`routing-table=<vrf-name>` parameter; the `mikrotik_routeros` codec
does not yet parse / render that form (it declares
`/routing/static-route/vrf` `unsupported`), so this is currently
lossy even though `CanonicalStaticRoute.vrf` exists (deferred —
lands alongside VRF wire-up).

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
  RouterOS `/ip route ... routing-table=X`.  Lossy on this pair: the
  `juniper_junos` source codec now harvests per-VRF statics onto
  `CanonicalStaticRoute.vrf` (`set routing-instances X routing-options
  static route <dest> next-hop <gw>`), so the VRF reaches canonical,
  but the `mikrotik_routeros` codec declares `/routing/static-route/vrf`
  `unsupported` and does not render the `routing-table=X` form — so
  Junos-source per-VRF routes flatten to the global table on RouterOS
  render.
* Junos's `qualified-next-hop` (weighted multi-NH) flattens to
  multiple canonical entries on parse; RouterOS render emits each
  as a separate `/ip route` record (no native multi-NH composite on
  RouterOS).

Disposition: **lossy** overall — default-VRF IPv4 + IPv6 static routes
round-trip cleanly; per-VRF entries flatten to global; preference /
metric semantics drift; qualified-next-hop expands.
