# Static routes: OPNsense versus Arista EOS

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
default via `<gateway>WAN_GW</gateway>` inside `<wan>` is the
OPNsense idiom; an explicit `0.0.0.0/0` route is uncommon.

## Arista EOS

Source: [Arista EOS User Manual — Routing Configuration](https://www.arista.com/en/um-eos/eos-routing-configuration)
Retrieved: 2026-05-01

```
ip route 0.0.0.0/0 10.0.0.1
ip route 10.50.0.0/16 10.0.1.1 5
ip route vrf TENANT_A 10.100.0.0/24 10.100.0.254
```

- Flat `ip route DEST/N GW [metric]` form.
- Per-VRF routes use `ip route vrf <name> ...`.
- Default route is the explicit `0.0.0.0/0` form.

## Cross-vendor mapping (OPNsense -> Arista EOS)

- `static_routes`: **lossy** — OPNsense's two-block model
  requires a JOIN to resolve named gateway references to bare
  next-hop IPs.  The opnsense codec capability matrix lists
  `/staticroutes/route` as supported in the kitchen-sink XML but
  parser wire-up is incomplete; cross-pair render emits nothing
  on the Arista target until parse lands.  The OPNsense
  default-route idiom (implicit `<gateway>` on the WAN zone)
  requires synthesising a `0.0.0.0/0` canonical record on parse —
  currently not done.
- Per-VRF static routes: **not_applicable** — OPNsense has no
  VRF model.
