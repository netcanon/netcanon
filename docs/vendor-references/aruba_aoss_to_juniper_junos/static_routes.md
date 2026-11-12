# Static routes: Aruba AOS-S versus Juniper Junos

<!-- junos-route-preference -->
> **Update 2026-11-12 — a route's distance is written as its Junos `preference`.**  Up to 0.7.7 the Junos render wrote destination and next hop only, so a route's distance was lost and a floating route came out as a second next hop of the same preference, carrying traffic beside the route it backs up.  The next hops at a destination's lowest distance are now written `next-hop <address>` with one `route <prefix> preference <n>` line, and each other next hop `qualified-next-hop <address> preference <n>` ("The qualified next-hop preference and metric override the route preference and metric", Juniper, "Static Route Preferences and Qualified Next Hops").  A destination whose next hops mix a stated and an unstated distance is a known limitation: the unstated one is written at the Junos default, 5.  What the body below says of the distance on this pair predates this.

<!-- junos-rib-inet6 -->
> **Update 2026-11-12 — an IPv6 static route is written under `rib inet6.0`.**  Up to 0.7.7 the Junos render wrote an IPv6 static route under `routing-options static`, as an IPv4 route is.  Junos holds an IPv6 static route in `inet6.0`, `set routing-options rib inet6.0 static route ...` ([Juniper, Example: Configuring IPv6 Static Routes](https://www.juniper.net/documentation/en_US/junos12.3/topics/example/policy-ipv6-static-routes.html)), and in a routing instance in `<instance>.inet6.0` ("In a routing instance, the routing table name must include the routing instance name", [Juniper, rib (Routing Options)](https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/ref/statement/rib-edit-routing-options.html)).  The render now writes it there, and the Junos parser reads it back.  The AOS-S parser reads `ipv6 route`, so such a route reaches Junos, whatever the body says.

How IPv4 / IPv6 static routes are declared on each platform.

Sources:
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/topic-map/static-routing-overview.html (retrieved 2026-05-01)

Citation ids: `aruba-static-routes`, `junos-static-routing`.

## Aruba AOS-S form

```
ip route 192.168.99.0/24 10.0.0.254
ip route 172.16.0.0 255.255.0.0 10.0.0.254
ip default-gateway 10.0.0.1
ipv6 route 2001:db8:99::/48 2001:db8::254
```

AOS-S accepts both CIDR (`/24`) and dotted-mask
(`255.255.0.0`) forms on the same `ip route` directive.  The legacy
`ip default-gateway <gw>` directive is normalised by the codec to a
`0.0.0.0/0` canonical static route.

Aruba has no VRF concept on AOS-S, so per-VRF static routes are
structurally absent.

## Junos form

```
set routing-options static route 192.168.99.0/24 next-hop 10.0.0.254
set routing-options static route 0.0.0.0/0 next-hop 10.0.0.1
set routing-options rib inet6.0 static route 2001:db8:99::/48 next-hop 2001:db8::254
```

Per-routing-instance (VRF) form:

```
set routing-instances TENANT_A routing-options static route 10.50.0.0/16 next-hop 10.0.0.3
```

Junos accepts CIDR exclusively for `route <prefix>`.  Junos's
`qualified-next-hop` allows per-NH preference / metric overrides;
this richer form is not modelled in the canonical
`CanonicalStaticRoute` (single next-hop only).

## Cross-vendor mapping

Canonical `CanonicalStaticRoute(destination, gateway, interface,
metric, description)` normalises the dotted-mask / CIDR difference
on parse.

Specifics:

* Aruba's `ip default-gateway <gw>` normalises to `0.0.0.0/0` with
  the gateway as next-hop; Junos render emits
  `set routing-options static route 0.0.0.0/0 next-hop <gw>`.
* Aruba's IPv6 static routes (`ipv6 route X/N <gw>`) parse-and-
  ignore today (the canonical static-route record carries IPv4
  semantics most natively); the Junos `rib inet6.0` form is not
  populated from Aruba source.
* Aruba's mixed-form `ip route 172.16.0.0 255.255.0.0 10.0.0.254`
  converts to CIDR via the codec's `_dest_mask_to_cidr` helper
  (similar to the Cisco -> CIDR helper).
* Junos's `preference` / `qualified-next-hop` plumbing has no
  equivalent on Aruba's flat directive set.  Junos source -> Aruba
  flattens to a single-next-hop record.

Disposition: **good** for default-VRF static routes (Aruba carries
no VRF concept; per-VRF is structurally absent on this direction).
