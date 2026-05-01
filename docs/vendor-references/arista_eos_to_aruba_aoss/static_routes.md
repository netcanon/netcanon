# Static routes: Arista EOS versus Aruba AOS-S

## Arista EOS

Source: [Arista EOS — IPv4 / Static Routes](https://www.arista.com/en/um-eos/eos-ipv4)
Retrieved: 2026-05-01

Arista EOS uses CIDR notation:

```
ip route 0.0.0.0/0 192.168.100.1
ip route 10.50.0.0/16 10.0.0.2
ip route vrf TENANT_A 10.100.0.0/16 10.100.0.254     ; per-VRF
ipv6 route ::/0 2001:db8:0:1::2
```

Per-VRF static routes use the `ip route vrf <name>` form (parsed
by the EOS codec but currently lossy to canonical because
`CanonicalStaticRoute` lacks a VRF field).

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv4 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba uses `ip route` with either CIDR or dotted-mask form, plus
a legacy `ip default-gateway` variant for the default route:

```
ip default-gateway 10.0.0.1
ip route 192.168.99.0/24 10.0.0.254
ip route 172.16.0.0 255.255.0.0 10.0.0.254          ; dotted-mask also parses
```

Aruba has **no VRF** — every static route lives in the global
routing table.  No `ip route vrf <name>` form.

## Cross-vendor mapping

The canonical surface is `CanonicalStaticRoute(destination,
gateway, interface, metric, description)`.  Destination is a
CIDR string; gateway is a next-hop IP.

Arista -> Aruba round-trip:

* `ip route 192.168.99.0/24 10.0.0.254` -> `ip route
  192.168.99.0/24 10.0.0.254` (identical syntax).
* `ip route 0.0.0.0/0 192.168.100.1` -> `ip route 0.0.0.0/0
  192.168.100.1` on Aruba; the codec does NOT collapse to the
  legacy `ip default-gateway` form (modern AOS-S accepts both).
* `ipv6 route ::/0 ...` -> currently not parsed reliably by
  `aruba_aoss` (the codec's static-route surface focuses on
  IPv4); IPv6 default routes drop on this direction.

Per-VRF static routes (`ip route vrf TENANT_A ...`) are
currently **parse-and-ignore on Arista** (the canonical model
has no VRF field on `CanonicalStaticRoute`), so the data never
reaches the canonical tree — nothing to render on Aruba either.
Known gap; lands alongside richer VRF wire-up.

The Arista kitchen-sink:

```
ip route 0.0.0.0/0 192.168.100.1
ip route 10.50.0.0/16 10.0.0.2
ipv6 route ::/0 2001:db8:0:1::2
```

— v4 routes land cleanly on Aruba; v6 drops.

Disposition: **good** for IPv4 default-VRF static routes;
**lossy** for IPv6 routes (canonical-side gap on Aruba parse) and
per-VRF routes (canonical-side gap on the route record).
