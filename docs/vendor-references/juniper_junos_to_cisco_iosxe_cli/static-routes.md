# Static routes: Juniper Junos versus Cisco IOS-XE

<!-- junos-route-preference -->
> **Update 2026-11-12 — a static route's `preference` is read as its distance.**  Up to 0.7.7 the parser read no `preference` and no `qualified-next-hop`, so a floating route lost its backup and a route held at a preference came out at the IOS-XE default.  Each next hop's preference -- a qualified next hop's own, else the route's, else `static defaults preference` -- is now its distance, written `ip route <prefix> <mask> <next hop> <distance>`; where some next hops of a route state one, the others are given Junos's default, 5.  A next hop at a preference of 0 or of 255 and above, and a qualified next hop with a `metric` of its own at the preference of another next hop of the route, are left out with a row.  The "Preference vs administrative distance" and "Qualified-next-hop" notes below predate this.

<!-- junos-rib-inet6 -->
> **Update 2026-11-12 — an IPv6 static route of `rib inet6.0` is read.**  Junos holds an IPv6 static route in `inet6.0`, `set routing-options rib inet6.0 static route ...` ([Juniper, Example: Configuring IPv6 Static Routes](https://www.juniper.net/documentation/en_US/junos12.3/topics/example/policy-ipv6-static-routes.html)), and in a routing instance in `<instance>.inet6.0` ("In a routing instance, the routing table name must include the routing instance name", [Juniper, rib (Routing Options)](https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/ref/statement/rib-edit-routing-options.html)).  Up to 0.7.7 the Junos parser read no `rib` line, and such a route was lost on every target, with nothing said, whatever the body below says of it.  A static route of `rib inet.0` and `rib inet6.0`, and of the instance's own two tables, is now read as one of `static` is; a static route of any other table is left out, and one row counts them.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/ref/statement/static-edit-routing-options.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/topic-map/static-routing-overview.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_pi/configuration/xe-17/iri-xe-17-book/iri-static-route-support.html (retrieved 2026-04-30)

Citation ids: `junos-static-routing`, `cisco-static-routes`.

## Junos form

```
set routing-options static route 10.0.0.0/24 next-hop 192.168.1.1
set routing-options static route 10.0.0.0/24 metric 50
set routing-options static route 0.0.0.0/0 next-hop 192.168.1.254
set routing-options static route 10.0.0.0/24 preference 5
set routing-options static route 10.0.0.0/24 qualified-next-hop 192.168.1.2 metric 100
```

Per-route attributes (next-hop, metric, preference,
qualified-next-hop) stack as separate `set` lines under the same
prefix.

Per-VRF (routing-instance) static:

```
set routing-instances TENANT_A routing-options static route 10.10.0.0/24 next-hop 10.10.0.254
```

IPv6 (under `inet6.0`):

```
set routing-options rib inet6.0 static route 2001:db8:1::/64 next-hop 2001:db8:0::1
```

## Cisco IOS-XE form

```
ip route 10.0.0.0 255.255.255.0 192.168.1.1
ip route 10.0.0.0 255.255.255.0 192.168.1.1 50
ip route 0.0.0.0 0.0.0.0 192.168.1.254

ip route vrf TENANT_A 10.10.0.0 255.255.255.0 10.10.0.254

ipv6 route 2001:db8:1::/64 2001:db8:0::1
```

## Mapping notes

- **Mask form.** Junos's CIDR form parses to the same canonical
  `CanonicalStaticRoute{destination, gateway, metric}` as Cisco's
  dotted-decimal mask.  Round-trip is lossless on the integer
  prefix-length.
- **Preference vs administrative distance.** Junos's
  `preference` and Cisco's "AD" are vendor-specific scalars that
  don't translate 1:1 (Junos statics default to preference 5;
  Cisco statics default to AD 1).  The canonical
  `CanonicalStaticRoute.metric` field is the operator-visible
  metric, not preference/AD; cross-vendor migration drops the
  preference/AD value unless the operator explicitly preserves it.
- **Per-VRF.** Both vendors model per-VRF static routes, and the
  canonical `CanonicalStaticRoute.vrf` field carries the
  discriminator.  The `juniper_junos` source codec now harvests
  `set routing-instances X routing-options static route <dest>
  next-hop <gw>` into that field, and the `cisco_iosxe_cli` target
  codec renders it back out as `ip route vrf X`
  (`/routing/static-route/vrf` is `supported` on both), so per-VRF
  next-hop routes round-trip on this direction.  (Junos parses the
  next-hop form only; `discard`/`reject` blackhole routes and the
  explicit `rib <name>` IPv6 form remain unmodelled, same as the
  global table.)
- **Qualified-next-hop.** Junos's `qualified-next-hop` (multiple
  next-hops with per-NH metrics) has no clean Cisco equivalent;
  Cisco models the same intent through multiple parallel
  `ip route` lines with distinct ADs.  Canonical model carries
  one `gateway` + `metric` per route entry; the qualified-NH
  detail flattens to one or more separate canonical entries.

Disposition: **good** on per-VRF routes (the Junos source codec now
harvests per-VRF statics onto `CanonicalStaticRoute.vrf` and the Cisco
target renders `ip route vrf X`, so per-VRF next-hop routes round-trip
on this direction), **good** on default-VRF IPv4 / IPv6 static routes;
**lossy** on qualified-next-hop preservation.
