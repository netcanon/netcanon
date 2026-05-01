# Static routes: Juniper Junos versus Cisco IOS-XE

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
- **Per-VRF.** Both vendors model per-VRF static routes; the
  canonical model lacks a VRF discriminator on
  `CanonicalStaticRoute` in v1, so per-VRF static routes are
  parse-and-ignore on both codecs pending schema extension.
- **Qualified-next-hop.** Junos's `qualified-next-hop` (multiple
  next-hops with per-NH metrics) has no clean Cisco equivalent;
  Cisco models the same intent through multiple parallel
  `ip route` lines with distinct ADs.  Canonical model carries
  one `gateway` + `metric` per route entry; the qualified-NH
  detail flattens to one or more separate canonical entries.

Disposition: **lossy** on per-VRF routes (deferred), **good** on
default-VRF IPv4 / IPv6 static routes; **lossy** on
qualified-next-hop preservation.
