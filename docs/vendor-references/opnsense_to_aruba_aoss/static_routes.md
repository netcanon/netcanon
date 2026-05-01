# Static routes: OPNsense versus Aruba AOS-S

## OPNsense

Source: [OPNsense Gateways manual](https://docs.opnsense.org/manual/gateways.html)
and [Static Routes](https://docs.opnsense.org/manual/staticroutes.html)
Retrieved: 2026-04-30

OPNsense splits static-route declaration into TWO blocks:

```xml
<opnsense>
  <gateways>
    <gateway_item>
      <name>WAN_GW</name>
      <interface>wan</interface>
      <gateway>198.51.100.1</gateway>
      <ipprotocol>inet</ipprotocol>
    </gateway_item>
  </gateways>
  <staticroutes>
    <route>
      <network>10.50.0.0/16</network>
      <gateway>WAN_GW</gateway>
    </route>
  </staticroutes>
</opnsense>
```

- Named gateway records carry the next-hop IP and the interface
  binding.
- `<staticroutes>/<route>` references the named gateway, not a bare
  IP.
- Default route is implicit via the WAN zone's `<gateway>`
  reference.

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 IPv4 Configuration Guide — Static
routes](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
ip route 10.50.0.0/16 198.51.100.1
ip route 0.0.0.0/0 198.51.100.1
```

- Flat `ip route DEST/N GW` form (CIDR or dotted-mask).
- No VRF concept — every static is in the global table.
- Default-gateway form `ip default-gateway <gw>` is legacy; the
  codec normalises to `0.0.0.0/0` on canonical.

## Cross-vendor mapping

Canonical fields (`CanonicalStaticRoute`):

```
destination, gateway, interface, metric, description
```

OPNsense -> Aruba:

- `static_routes`: **lossy** — OPNsense's two-block model means the
  parser would need to JOIN `<staticroutes>/<route>` against
  `<gateways>/<gateway_item>` to resolve the named gateway to an IP
  before populating `CanonicalStaticRoute.gateway`.  The opnsense
  codec capability matrix lists `/staticroutes/route` as supported
  in the kitchen-sink XML but parser wire-up is incomplete; cross-
  pair render emits nothing on the Aruba target until parse lands.
  The default-route case (OPNsense's implicit `<gateway>` on the
  WAN zone) requires synthesising a `0.0.0.0/0` canonical record on
  parse — currently not done.
