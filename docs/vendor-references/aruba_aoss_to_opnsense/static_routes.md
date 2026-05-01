# Static routes: Aruba AOS-S versus OPNsense

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 IPv4 Configuration Guide — Static
routes](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
ip route 0.0.0.0/0 10.0.0.1
ip route 10.50.0.0/16 10.0.0.1
ip default-gateway 10.0.0.1
```

- CIDR notation is preferred (`10.50.0.0/16`).  The dotted-mask form
  (`ip route 10.50.0.0 255.255.0.0 10.0.0.1`) also parses.
- `ip default-gateway <gw>` is the legacy AOS-S directive that
  predates `ip route 0.0.0.0/0`; the codec normalises it to a
  `0.0.0.0/0` canonical record.
- No VRF concept — every static route is in the global table.
- No metric attribute on the basic form (advanced administrative
  distance lives in policy-based routing extensions, out of canonical
  scope).

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
      <descr>Default gateway</descr>
    </gateway_item>
  </gateways>
  <staticroutes>
    <route>
      <network>10.50.0.0/16</network>
      <gateway>WAN_GW</gateway>
      <descr>Lab subnet</descr>
    </route>
  </staticroutes>
</opnsense>
```

Two-stage model:

- `<gateways>/<gateway_item>` declares NAMED gateway records
  (per-IP-family) tied to a zone interface.
- `<staticroutes>/<route>` references the named gateway, not a bare
  next-hop IP.

Default route is implicit — assigning a gateway as the system
default in the zone interface block (`<gateway>WAN_GW</gateway>`
inside `<wan>`) is the OPNsense idiom; an explicit `0.0.0.0/0` route
is uncommon.

## Cross-vendor mapping

Canonical fields covered:

```
CanonicalStaticRoute:
  destination: str   # CIDR
  gateway: str       # next-hop IP
  interface: str     # outgoing interface name
  metric: int
  description: str
```

Aruba -> OPNsense:

- `static_routes`: **lossy** — Aruba's flat `ip route DEST/N GW` form
  carries the next-hop IP directly; OPNsense expects a NAMED gateway
  reference plus a separate `<gateway_item>` declaration.  The
  cross-pair render would need to synthesise both blocks and pick a
  gateway name (e.g. `cv_gw_<index>`) — the OPNsense codec capability
  matrix does not currently advertise `/routing/static-route` on its
  render side, so this drops pending wire-up.  Aruba's
  `ip default-gateway` form is normalised to `0.0.0.0/0` on canonical
  but the OPNsense idiom is to set the default via the WAN zone's
  `<gateway>` rather than a `0.0.0.0/0` route.
- Per-VRF static routes: **not_applicable** — Aruba has no VRF.
