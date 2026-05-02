# Static routes: OPNsense versus Junos

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
- The named gateway is bound to a zone interface.
- Default route is implicit via the WAN gateway's `<defaultgw>1`
  flag, NOT an explicit `0.0.0.0/0` static route.
- The OPNsense codec does not currently parse OR emit `<gateways>`
  / `<staticroutes>`; canonical static_routes are always empty
  on parse from this source.

## Junos

Source: [Junos static-routing topic-map](https://www.juniper.net/documentation/us/en/software/junos/static-routing/topics/topic-map/static-routing-overview.html)
Retrieved: 2026-05-01

```
set routing-options static route 0.0.0.0/0 next-hop 10.0.0.2
set routing-options static route 10.50.0.0/16 next-hop 10.0.0.3
set routing-options static route ::/0 next-hop 2001:db8::2
```

Junos static-route notes:

- Default route uses `0.0.0.0/0` (IPv4) or `::/0` (IPv6).
- `next-hop <addr>` is the standard primary form.
- Per-VRF static routes nest under
  `set routing-instances <vrf> routing-options static route ...`.

## Cross-vendor mapping

OPNsense -> Junos:

- `static_routes`: **lossy** — OPNsense codec parse path is
  incomplete (`<staticroutes>` / `<gateways>` not currently wired
  into `CanonicalIntent.static_routes`).  Even if wired, the
  named-gateway resolution would need to look up the gateway IP
  by name during the canonical-build phase.  Cross-pair currently
  delivers an empty list; Junos target receives nothing.
- The structural mapping IS sound for when wire-up lands: each
  OPNsense `<staticroutes>/<route>` becomes one Junos `set routing-
  options static route X/N next-hop Y`, with the gateway IP looked
  up from the named `<gateways>/<gateway_item>` block.
- Default route: OPNsense's WAN-gateway default flag has no direct
  Junos analogue; the canonical model would need to synthesise
  `0.0.0.0/0 → wan_gw_ip` to round-trip.

Disposition: **lossy** — codec wire-up gap on OPNsense parse
dominates.  No VRF-bound routes (OPNsense has no VRF), so per-VRF
static-route concerns don't apply.
