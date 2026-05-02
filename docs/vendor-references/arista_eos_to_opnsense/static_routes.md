# Static routes: Arista EOS versus OPNsense

## Arista EOS

Source: [Arista EOS User Manual — Routing Configuration](https://www.arista.com/en/um-eos/eos-routing-configuration)
Retrieved: 2026-05-01

```
ip route 0.0.0.0/0 10.0.0.1
ip route 10.50.0.0/16 10.0.1.1 5
ip route vrf TENANT_A 10.100.0.0/24 10.100.0.254
```

- CIDR notation (`10.50.0.0/16`) is canonical Arista form.
- Optional administrative-distance integer trails the next-hop
  (`5` in the example) — the canonical
  `CanonicalStaticRoute.metric` carries it.
- Per-VRF routes use `ip route vrf <name> ...`; canonical lacks a
  per-route VRF field today (would require schema extension on
  `CanonicalStaticRoute`).
- Default route is the bare `0.0.0.0/0` form (no `ip
  default-gateway` legacy directive on Arista).

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
- `<staticroutes>/<route>` references the named gateway, not a
  bare next-hop IP.

Default route is implicit — assigning a gateway as the system
default in the zone interface block (`<gateway>WAN_GW</gateway>`
inside `<wan>`) is the OPNsense idiom; an explicit `0.0.0.0/0`
route is uncommon.

## Cross-vendor mapping (Arista -> OPNsense)

Canonical fields covered:

```
CanonicalStaticRoute:
  destination: str   # CIDR
  gateway: str       # next-hop IP
  interface: str     # outgoing interface name
  metric: int
  description: str
```

- `static_routes`: **lossy** — Arista's flat `ip route DEST/N GW`
  form carries the next-hop IP directly; OPNsense expects a NAMED
  gateway reference plus a separate `<gateway_item>` declaration.
  Cross-pair render would need to synthesise both blocks and pick
  a gateway name (e.g. `cv_gw_<index>`) — the OPNsense codec
  capability matrix does not currently advertise
  `/routing/static-route` on its render side, so this drops
  pending wire-up.  Arista's `0.0.0.0/0` form would also need
  remapping to the OPNsense default-gateway idiom (set via the WAN
  zone interface) rather than emitting an explicit
  `<route><network>0.0.0.0/0</network></route>`.
- Per-VRF static routes (Arista `ip route vrf X ...`):
  **unsupported** — canonical lacks a VRF field on
  `CanonicalStaticRoute`, and OPNsense has no VRF model anyway.
