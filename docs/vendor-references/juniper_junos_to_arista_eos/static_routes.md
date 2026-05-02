# Static routes

Default-VRF and per-instance static-route configuration on each
platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/topic-map/static-routing-overview.html (retrieved 2026-05-01)
- Arista: https://www.arista.com/en/um-eos/eos-routing-configuration (retrieved 2026-05-01)

Citation ids: `junos-static-routing`, `arista-routing-cg`.

## Junos form

```
set routing-options static route 0.0.0.0/0 next-hop 10.0.0.254
set routing-options static route 192.168.1.0/24 next-hop 10.0.0.1
set routing-options static route 192.168.1.0/24 preference 250
set routing-options static route 192.168.2.0/24 qualified-next-hop 10.0.0.2 preference 200
set routing-options static route 192.168.2.0/24 qualified-next-hop 10.0.0.3 preference 210

set routing-instances TENANT-A routing-options static route 10.10.10.0/24 next-hop 10.0.0.10

set routing-options rib inet6.0 static route ::/0 next-hop 2001:db8::1
```

Junos's `qualified-next-hop` is the structural way to declare
multiple alternate next-hops with per-NH preference.  IPv6 static
routes live under `routing-options rib inet6.0 static`.

## Arista form

```
ip route 0.0.0.0/0 10.0.0.254
ip route 192.168.1.0/24 10.0.0.1 250
ip route vrf TENANT-A 10.10.10.0/24 10.0.0.10
ipv6 route ::/0 2001:db8::1
```

Arista's syntax is positional: `ip route <prefix> <next-hop>
[<preference>]`.  Per-VRF routes use `ip route vrf <name>`.  IPv6
uses `ipv6 route` (separate command, parallel shape).

## Mapping notes

- **Default-VRF static routes.** Direct one-to-one
  (`set routing-options static route X/N next-hop Y` ->
  `ip route X/N Y`).
- **Preference.** Both accept an administrative-distance / preference
  integer; Junos `preference 250` -> Arista's positional third
  argument.  Round-trip preserved.
- **Qualified next-hop.** Junos's per-NH preference under one
  prefix collapses to multiple `ip route` lines on Arista (one per
  next-hop).  Canonical model carries the per-NH list; the
  structural transformation is internal to each codec.  Lossless
  on the next-hop set; lossy on the structural Junos grouping
  (qualified-next-hop block becomes flat lines on Arista).
- **Per-VRF static routes.** Junos's
  `set routing-instances X routing-options static` -> Arista's
  `ip route vrf X` form.  Both support per-VRF; canonical
  `CanonicalStaticRoute.vrf` discriminates.
- **IPv6 static routes.** Junos's `routing-options rib inet6.0
  static` -> Arista's `ipv6 route` syntax.  CanonicalStaticRoute
  is IPv4-shaped today (no `family` discriminator); IPv6 routes
  parse-and-ignore in the juniper_junos codec.  Lossy by deferral.
