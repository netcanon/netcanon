# Static routes: Junos versus OPNsense

<!-- junos-rib-inet6 -->
> **Update 2026-11-12 — an IPv6 static route of `rib inet6.0` is read.**  Junos holds an IPv6 static route in `inet6.0`, `set routing-options rib inet6.0 static route ...` ([Juniper, Example: Configuring IPv6 Static Routes](https://www.juniper.net/documentation/en_US/junos12.3/topics/example/policy-ipv6-static-routes.html)), and in a routing instance in `<instance>.inet6.0` ("In a routing instance, the routing table name must include the routing instance name", [Juniper, rib (Routing Options)](https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/ref/statement/rib-edit-routing-options.html)).  Up to 0.7.7 the Junos parser read no `rib` line, and such a route was lost on every target, with nothing said, whatever the body below says of it.  A static route of `rib inet.0` and `rib inet6.0`, and of the instance's own two tables, is now read as one of `static` is; a static route of any other table is left out, and one row counts them.  The body's IPv6 example under `routing-options static`, and its sentence that IPv6 statics live there, are not so.

## Junos

Source: [Junos static-routing topic-map](https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/topic-map/static-routing-overview.html)
Retrieved: 2026-05-01

```
set routing-options static route 0.0.0.0/0 next-hop 10.0.0.2
set routing-options static route 10.50.0.0/16 next-hop 10.0.0.3
set routing-options static route ::/0 next-hop 2001:db8::2
set routing-options static route 192.0.2.0/24 qualified-next-hop 10.0.0.4 preference 5
```

Junos static-route notes:

- Default route uses `0.0.0.0/0` (IPv4) or `::/0` (IPv6).
- `next-hop <addr>` is the standard primary form; `qualified-next-hop`
  adds a per-NH preference value (Junos's equivalent of Cisco AD).
- Per-VRF static routes nest under `set routing-instances <vrf>
  routing-options static route ...`.
- IPv6 statics live in the same `routing-options static` hierarchy
  (no separate stanza).

## OPNsense

Source: [OPNsense Gateways manual](https://docs.opnsense.org/manual/gateways.html)
Retrieved: 2026-04-30

OPNsense splits static-route declaration into two blocks.  First, a
named gateway:

```xml
<gateways>
  <gateway_item>
    <interface>opt1</interface>
    <gateway>10.0.0.3</gateway>
    <name>UPSTREAM_GW</name>
    <ipprotocol>inet</ipprotocol>
    <descr>Upstream router on opt1</descr>
  </gateway_item>
</gateways>
```

Then, a static route referencing the named gateway:

```xml
<staticroutes>
  <route>
    <network>10.50.0.0/16</network>
    <gateway>UPSTREAM_GW</gateway>
    <descr>Lab tenant subnet</descr>
    <disabled>0</disabled>
  </route>
</staticroutes>
```

OPNsense static-route notes:

- The two-block structure is mandatory — routes can't reference a
  bare next-hop IP, only a NAMED gateway.
- The named gateway is bound to a zone interface (`opt1`).
- Default route is implicit via the WAN gateway's `<defaultgw>1`
  flag, NOT an explicit `0.0.0.0/0` static route.
- IPv6 routes use `<ipprotocol>inet6</ipprotocol>` on the gateway and
  IPv6 prefix in `<network>`.
- The OPNsense codec does not currently parse OR emit `<gateways>`
  or `<staticroutes>` blocks; canonical static_routes drop on render.

## Cross-vendor mapping

Junos -> OPNsense:

- `static_routes`: **unsupported** — Junos default IPv4 + named-prefix
  + IPv6 statics in `set routing-options static route X/N next-hop Y`
  parse cleanly to canonical entries with `destination` (CIDR), and
  `gateway`.  The OPNsense codec renders neither `<gateways>` nor
  `<staticroutes>`, so the entire list drops — the record does not
  survive the trip, which is `unsupported`, not `lossy`; the codec
  declares `/routing/static-route` and every leaf beneath it
  unsupported, and validation blocks rather than warns.
- Per-VRF static routes (Junos `set routing-instances <vrf> routing-
  options static`) are unsupported on the cross-pair: the
  `juniper_junos` source codec now harvests per-VRF statics onto
  `CanonicalStaticRoute.vrf` (`set routing-instances X routing-options
  static route <dest> next-hop <gw>`), so the VRF is populated on this
  direction, but OPNsense has no VRF model and drops it on render.
- Junos's `qualified-next-hop` flattens to multiple canonical entries
  (one per NH); preference values drop (OPNsense has no
  per-route preference field outside the gateway hierarchy).
- `metric` / `description` round-trip the canonical scalar through
  to OPNsense's `<descr>` (where wire-up exists).

Disposition: **unsupported**, dominated by the render gap on OPNsense
(the structural mapping itself is straightforward, and would be merely
lossy once `<staticroutes>` rendering lands); VRF-bound routes are
unsupported for a second, independent reason — OPNsense has no VRF
model at all.
