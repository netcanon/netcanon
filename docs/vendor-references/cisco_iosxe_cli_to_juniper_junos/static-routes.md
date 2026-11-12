# Static routes: Cisco IOS-XE versus Juniper Junos

<!-- junos-route-preference -->
> **Update 2026-11-12 — a route's distance is written as its Junos `preference`.**  Up to 0.7.7 the Junos render wrote destination and next hop only, so a floating route (`ip route <prefix> <mask> <next hop> <distance>`) came out as a second next hop of the same preference, carrying traffic beside the route it backs up.  The next hops at a destination's lowest distance are now written `next-hop <address>` with one `route <prefix> preference <n>` line, and each other next hop `qualified-next-hop <address> preference <n>` ("The qualified next-hop preference and metric override the route preference and metric", Juniper, "Static Route Preferences and Qualified Next Hops").  A destination whose routes mix a stated and an unstated distance is a known limitation: the unstated one is written at the Junos default, 5, where the IOS-XE default is 1.  The "Administrative distance versus preference" note below predates this.

<!-- junos-rib-inet6 -->
> **Update 2026-11-12 — an IPv6 static route is written under `rib inet6.0`.**  Up to 0.7.7 the Junos render wrote an IPv6 static route under `routing-options static`, as an IPv4 route is.  Junos holds an IPv6 static route in `inet6.0`, `set routing-options rib inet6.0 static route ...` ([Juniper, Example: Configuring IPv6 Static Routes](https://www.juniper.net/documentation/en_US/junos12.3/topics/example/policy-ipv6-static-routes.html)), and in a routing instance in `<instance>.inet6.0` ("In a routing instance, the routing table name must include the routing instance name", [Juniper, rib (Routing Options)](https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/ref/statement/rib-edit-routing-options.html)).  The render now writes it there, and the Junos parser reads it back.

How global and per-VRF static routes are declared.

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_pi/configuration/xe-17/iri-xe-17-book/iri-static-route-support.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/topic-map/static-routing-overview.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/ref/statement/static-edit-routing-options.html (retrieved 2026-04-30)

Citation ids: `cisco-static-routes`, `junos-static-routing`.

## Cisco IOS-XE form

Default-VRF static route (dotted-decimal mask):

```
ip route 10.0.0.0 255.255.255.0 192.168.1.1
ip route 10.0.0.0 255.255.255.0 192.168.1.1 50
ip route 0.0.0.0 0.0.0.0 192.168.1.254
```

Optional trailing integer is the administrative distance (default
1).  Cisco accepts both dotted-decimal and CIDR mask forms in
modern IOS-XE; the running-config emits dotted-decimal.

Per-VRF static route:

```
ip route vrf TENANT_A 10.10.0.0 255.255.255.0 10.10.0.254
```

IPv6:

```
ipv6 route 2001:db8:1::/64 2001:db8:0::1
```

## Junos form

Global (master `inet.0`) static route:

```
set routing-options static route 10.0.0.0/24 next-hop 192.168.1.1
set routing-options static route 10.0.0.0/24 metric 50
set routing-options static route 0.0.0.0/0 next-hop 192.168.1.254
```

Junos uses CIDR exclusively (`/<prefix>`); no dotted-decimal
form.  Multi-line per-route attributes (next-hop, metric,
preference, qualified-next-hop) stack as separate `set` lines.

Per-VRF (routing-instance) static route:

```
set routing-instances TENANT_A routing-options static route 10.10.0.0/24 next-hop 10.10.0.254
```

IPv6 (under `inet6.0`):

```
set routing-options rib inet6.0 static route 2001:db8:1::/64 next-hop 2001:db8:0::1
```

## Mapping notes

- **Mask form.** Cisco's dotted-decimal mask is normalised by the
  codec parser to the same canonical
  `CanonicalStaticRoute{destination, gateway, metric}` shape that
  Junos's CIDR form parses into.  Destination is stored as CIDR
  (`<addr>/<prefix>`) on the canonical side.
- **Administrative distance versus preference.** Cisco's "AD" and
  Junos's "preference" are vendor-specific concepts that don't
  map directly; the canonical `CanonicalStaticRoute.metric` field
  is documented as the operator-visible metric (defaults to 0
  meaning "not specified").  Cross-vendor migration drops the
  distance/preference value unless explicitly preserved by the
  operator.
- **Per-VRF.** Both vendors model per-VRF static routes; Cisco
  uses `ip route vrf X` and Junos uses `set routing-instances X
  routing-options static route`.  The canonical model carries the
  discriminator on `CanonicalStaticRoute.vrf`.  Both codecs now parse
  that discriminator and render it back out
  (`/routing/static-route/vrf` is `supported` on both): the
  `cisco_iosxe_cli` codec round-trips `ip route vrf X`, and the
  `juniper_junos` codec harvests `set routing-instances X
  routing-options static route <dest> next-hop <gw>` into
  `CanonicalStaticRoute.vrf` and emits it back out.  (Junos models the
  next-hop form only; `discard`/`reject` blackhole routes and the
  explicit `rib <name>` form — e.g. IPv6 `inet6.0` — are not modelled,
  same as the global table.)
- **Next-hop variants.** Cisco supports `ip route DEST MASK
  <interface>` (recursive next-hop); Junos uses `qualified-next-hop`
  for similar semantics.  Both surfaces fall under the canonical
  `gateway` field as opaque string today.

Disposition: **good** on per-VRF routes (the Cisco source preserves
the VRF on `CanonicalStaticRoute.vrf` and the Junos render now emits
`set routing-instances X routing-options static route ...`, so per-VRF
next-hop routes round-trip in both directions), **good** on
default-VRF IPv4 / IPv6 static routes.
