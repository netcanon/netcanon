# Static routes: OPNsense versus FortiGate FortiOS

Reverse direction.  Forward direction in
`../fortigate_cli_to_opnsense/static_routes.md`.

## OPNsense

OPNsense's two-block model:

```xml
<opnsense>
  <gateways>
    <gateway_item>
      <interface>wan</interface>
      <gateway>198.51.100.1</gateway>
      <name>WAN_GW</name>
      <descr>Upstream ISP</descr>
    </gateway_item>
  </gateways>
  <staticroutes>
    <route>
      <network>10.20.0.0/16</network>
      <gateway>WAN_GW</gateway>
      <descr>Lab subnets</descr>
    </route>
  </staticroutes>
</opnsense>
```

Source: [OPNsense Gateways
manual](https://docs.opnsense.org/manual/gateways.html), [OPNsense
Static Routes
manual](https://docs.opnsense.org/manual/staticroutes.html)
Retrieved: 2026-05-01

OPNsense notes:

- Routes reference NAMED gateways via `<gateway>WAN_GW</gateway>`,
  not bare next-hop IPs.  Resolving to bare IP requires a JOIN
  with the `<gateway_item>` table.
- Default route is implicit on the WAN zone's `<gateway>` flag,
  NOT a `<route>` element with `0.0.0.0/0`.
- The OPNsense codec capability matrix lists `/staticroutes/route`
  in the kitchen-sink XML but parser wire-up is incomplete —
  cross-pair drops static routes pending wire-up.

## FortiGate FortiOS

See `../fortigate_cli_to_opnsense/static_routes.md` for the
FortiGate-side shape.  Key points:

- Routes live under `config router static` as a numbered edit-table.
- `set dst <addr> <mask>` uses dotted-mask form.
- `set gateway` is the bare next-hop IP.
- `set device` is the egress interface name.
- Default route is `set dst 0.0.0.0 0.0.0.0` — first-class entry
  (unlike OPNsense's WAN-flag idiom).

## Cross-vendor mapping (OPNsense -> FortiGate)

Canonical fields covered (`CanonicalStaticRoute`):

```
prefix, prefix_length, next_hop, interface, distance, description, vrf
```

- **lossy** — Multiple loss vectors:
  1. OPNsense parser does not wire `<staticroutes>` into
     `CanonicalIntent.static_routes` in v1 (capability matrix lists
     the path but parser branch is incomplete).  Canonical list is
     empty after OPNsense parse — nothing to render on FortiGate
     pending wire-up.
  2. Even with parser wire-up, the OPNsense default-route idiom
     (implicit `<gateway>` on the WAN zone) requires synthesising a
     `0.0.0.0/0` canonical record on parse — currently not done.
  3. Named-gateway JOIN: OPNsense `<route>/<gateway>WAN_GW</gateway>`
     references a named gateway; the parser must resolve to the
     `<gateway_item>` `<gateway>` IP to populate the canonical
     `next_hop` scalar.
- `description`: lossy on both ends (OPNsense `<descr>` -> FortiGate
  `set comment` not currently parsed).
- `interface`: lossy — interface name needs the rename mesh
  conversion (OPNsense `wan` -> FortiGate `port1`).
- `vrf`: not_applicable — neither vendor populates this on parse in v1.
