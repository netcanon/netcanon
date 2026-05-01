# Static routes: Cisco IOS-XE versus Aruba AOS-S

## Cisco IOS-XE

Source: [Cisco IOS XE 17.x IP Routing: Configuring Static Routes](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_pi/configuration/xe-17/iri-xe-17-book/iri-static-route.html)
Retrieved: 2026-04-30

Cisco's static-route syntax uses **dotted-decimal** for the
destination mask:

```
ip route 10.0.0.0 255.0.0.0 192.0.2.1
ip route 0.0.0.0 0.0.0.0 GigabitEthernet0/0/0 198.51.100.1
ip route vrf MGMT 0.0.0.0 0.0.0.0 198.51.100.254
```

Per-VRF static routes use the `vrf <name>` keyword between
`ip route` and the destination.  Optional trailing tokens:
administrative-distance integer, `tag <N>`, `name <description>`,
`permanent`.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IP Routing Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S accepts CIDR for both the destination and the next-hop
specification — there is no dotted-mask form.  Verbatim manual
shape:

```
ip route 10.0.0.0/8 192.0.2.1
ip route 0.0.0.0/0 198.51.100.1
ip default-gateway 192.168.10.254
```

`ip default-gateway` is a legacy AOS-S directive that pre-dates the
generic `ip route 0.0.0.0/0`; the codec parses both into the same
`CanonicalStaticRoute(destination="0.0.0.0/0", ...)` record.  AOS-S
has **no VRF concept** (see `vrf_unsupported.md`), so per-VRF static
routes have no equivalent.

## Cross-vendor mapping

The canonical model stores destinations in CIDR notation
(`CanonicalStaticRoute.destination = "10.0.0.0/8"`).  The codecs
convert:

* Cisco parse: dotted mask -> prefix length via the parse-module's
  `_mask_to_prefix` helper.
* Aruba parse: read `/8` directly.
* Cisco render: emit dotted mask via `_cidr_to_dest_mask`.
* Aruba render: emit CIDR directly.

Default-VRF static routes round-trip cleanly.  Per-VRF static routes
(`ip route vrf X ...`) are lossy:

* Cisco -> Aruba: drop the VRF; the route lands in the global
  table.  `CanonicalStaticRoute` lacks a `vrf` field today.
* Aruba -> Cisco: never populated on the Aruba side (no VRF
  concept), so this direction is not affected.

Disposition: **good** for default-VRF.  **Lossy** for per-VRF
(Cisco-only feature that has no Aruba equivalent and no canonical
field).
