# Static routes: Juniper Junos versus Aruba AOS-S

<!-- junos-rib-inet6 -->
> **Update 2026-11-12 — an IPv6 static route of `rib inet6.0` is read.**  Junos holds an IPv6 static route in `inet6.0`, `set routing-options rib inet6.0 static route ...` ([Juniper, Example: Configuring IPv6 Static Routes](https://www.juniper.net/documentation/en_US/junos12.3/topics/example/policy-ipv6-static-routes.html)), and in a routing instance in `<instance>.inet6.0` ("In a routing instance, the routing table name must include the routing instance name", [Juniper, rib (Routing Options)](https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/ref/statement/rib-edit-routing-options.html)).  Up to 0.7.7 the Junos parser read no `rib` line, and such a route was lost on every target, with nothing said, whatever the body below says of it.  A static route of `rib inet.0` and `rib inet6.0`, and of the instance's own two tables, is now read as one of `static` is; a static route of any other table is left out, and one row counts them.

How IPv4 / IPv6 static routes are declared on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/topic-map/static-routing-overview.html (retrieved 2026-05-01)
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm (retrieved 2026-05-01)

Citation ids: `junos-static-routing`, `aruba-static-routes`.

## Junos form

```
set routing-options static route 192.168.99.0/24 next-hop 10.0.0.254
set routing-options static route 0.0.0.0/0 next-hop 10.0.0.1
set routing-options rib inet6.0 static route ::/0 next-hop 2001:db8::2
```

Per-routing-instance:

```
set routing-instances TENANT_A routing-options static route 10.50.0.0/16 next-hop 10.0.0.3
```

Junos's `qualified-next-hop` allows per-NH preference / metric
overrides; this richer form is not modelled in the canonical
`CanonicalStaticRoute` (single next-hop only).

## Aruba AOS-S form

```
ip route 192.168.99.0/24 10.0.0.254
ip route 172.16.0.0 255.255.0.0 10.0.0.254
ip default-gateway 10.0.0.1
ipv6 route 2001:db8:99::/48 2001:db8::254
```

AOS-S has no VRF concept on this platform line.

## Cross-vendor mapping

Canonical `CanonicalStaticRoute` normalises CIDR form.

Specifics:

* Junos's `route 0.0.0.0/0 next-hop X` -> Aruba `ip default-gateway X`
  (the legacy form) OR `ip route 0.0.0.0/0 X` — codec render emits
  the modern form for consistency.
* Junos `route X/N next-hop Y` -> Aruba `ip route X/N Y` (CIDR
  preserved).
* Per-routing-instance static routes (`set routing-instances
  TENANT_A routing-options static`) are dropped on Aruba render —
  Aruba has no VRF concept (see `vrf_unsupported.md`).  The
  validation report flags the loss.
* Junos's `qualified-next-hop` flattens to multiple
  `CanonicalStaticRoute` entries; Aruba render emits one `ip route`
  line per entry.
* Junos's `preference` attribute has no Aruba analogue; drops on
  render.
* IPv6 static routes (`set routing-options rib inet6.0 static`) —
  the canonical `CanonicalStaticRoute` is IPv4-shaped today; IPv6
  static routes parse-and-ignore.  Lossy by deferral.

Disposition: **lossy** for default-VRF (basic round-trip clean;
IPv6 + per-VRF + qualified-next-hop drop).  **Unsupported** for the
per-VRF static-route surface.
