# Static routes: Aruba AOS-S versus Arista EOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IPv4 Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba supports two forms — modern CIDR and legacy default-gateway:

```
ip default-gateway 10.0.0.1
ip route 192.168.99.0/24 10.0.0.254
ip route 172.16.0.0 255.255.0.0 10.0.0.254          ; dotted-mask also parses
```

The codec normalises `ip default-gateway X` to a `0.0.0.0/0`
canonical record so the same `CanonicalStaticRoute(destination,
gateway, ...)` shape covers both forms.

Aruba has **no VRF** — every static route lives in the global
routing table.  There is no `ip route vrf <name> ...` form.

## Arista EOS

Source: [Arista EOS — IPv4 / Static Routes](https://www.arista.com/en/um-eos/eos-ipv4)
Retrieved: 2026-05-01

Arista EOS uses CIDR notation:

```
ip route 0.0.0.0/0 192.168.100.1
ip route 10.50.0.0/16 10.0.0.2
ip route vrf TENANT_A 10.100.0.0/16 10.100.0.254     ; per-VRF route
ipv6 route ::/0 2001:db8:0:1::2
```

Per-VRF static routes use the `ip route vrf <name>` form (parsed
by the EOS codec).

## Cross-vendor mapping

The canonical surface is `CanonicalStaticRoute(destination,
gateway, interface, metric, description)` — destination is a CIDR
string, gateway is a next-hop IP, no VRF field on the record (a
known canonical-model gap).

Aruba -> Arista round-trip:

* `ip route 192.168.99.0/24 10.0.0.254` -> `ip route
  192.168.99.0/24 10.0.0.254` (identical syntax, both emit CIDR).
* `ip route 172.16.0.0 255.255.0.0 10.0.0.254` (legacy dotted-mask
  on Aruba) -> normalised to `172.16.0.0/16` on canonical ->
  `ip route 172.16.0.0/16 10.0.0.254` on Arista render.
* `ip default-gateway 10.0.0.1` (Aruba legacy) -> `0.0.0.0/0`
  canonical -> `ip route 0.0.0.0/0 10.0.0.1` on Arista render.

Aruba never carries per-VRF static routes (no VRF concept on the
platform), so the Cisco/Arista-only `ip route vrf X` form is
structurally absent on this direction — no data to lose.

The Aruba kitchen-sink exercises all three forms:

```
ip default-gateway 10.0.0.1
ip route 192.168.99.0/24 10.0.0.254
ip route 172.16.0.0 255.255.0.0 10.0.0.254
```

— each renders to clean Arista CIDR-form static routes.

Disposition: **good** (CIDR-native on both vendors; default-
gateway legacy form normalises cleanly; per-VRF form
structurally absent on Aruba source).
