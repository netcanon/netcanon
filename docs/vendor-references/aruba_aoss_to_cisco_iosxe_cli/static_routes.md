# Static routes: Aruba AOS-S versus Cisco IOS-XE

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IP Routing Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S uses **CIDR notation** for the destination:

```
ip route 10.0.0.0/8 192.0.2.1
ip route 0.0.0.0/0 198.51.100.1
ip default-gateway 192.168.10.254
```

`ip default-gateway` is a legacy directive that pre-dates the
generic `ip route 0.0.0.0/0`; the codec normalises both into the
same `CanonicalStaticRoute(destination="0.0.0.0/0", ...)` record.

AOS-S has **no VRF concept** (campus-grade switching with a
single global IP routing table — see
`vrf_unsupported.md`).  Per-VRF static routes never appear on
this side.

## Cisco IOS-XE

Source: [Cisco IOS XE 17.x IP Routing: Configuring Static Routes](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_pi/configuration/xe-17/iri-xe-17-book/iri-static-route.html)
Retrieved: 2026-04-30

Cisco uses **dotted-decimal mask** for the destination:

```
ip route 10.0.0.0 255.0.0.0 192.0.2.1
ip route 0.0.0.0 0.0.0.0 198.51.100.1
ip route vrf MGMT 0.0.0.0 0.0.0.0 198.51.100.254
```

## Cross-vendor mapping

* Aruba parse: read `/8` directly into
  `CanonicalStaticRoute.destination`.
* Cisco render: emit dotted mask via `_cidr_to_dest_mask`.

Default-VRF static routes round-trip cleanly Aruba -> Cisco.  The
`ip default-gateway` legacy form normalises to a `0.0.0.0/0`
CIDR canonical record that the Cisco side renders as
`ip route 0.0.0.0 0.0.0.0 <gw>`.

Aruba never populates a VRF for static routes (no VRF concept), so
the Cisco-only `ip route vrf X` form is not in scope on this
direction.

Disposition: **good**.
