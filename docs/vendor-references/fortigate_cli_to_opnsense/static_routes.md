# Static routes: FortiGate FortiOS versus OPNsense

## FortiGate FortiOS

Source: [FortiGate / FortiOS 7.4 Administration Guide — Static
routes](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Retrieved: 2026-05-01

```
config router static
    edit 1
        set dst 0.0.0.0 0.0.0.0
        set gateway 198.51.100.1
        set device "port1"
        set distance 10
        set comment "Default route to ISP"
    next
    edit 2
        set dst 10.20.0.0 255.255.0.0
        set gateway 10.0.10.254
        set device "internal"
    next
end
```

Notes:

- Routes are numbered edits under `config router static`.
- `set dst <addr> <mask>` uses dotted-mask form for v4.  IPv6 is
  separate (`config router static6`).
- `set device <iface>` is the egress interface name.
- `set distance` is the administrative distance (default 10).
- `set comment` is unbounded text but not currently parsed by the
  codec into a canonical description.
- `set vrf <id>` (FortiOS 7.x) attaches the route to a per-interface
  integer VRF; not parsed into canonical in v1.

## OPNsense

Source: [OPNsense Gateways
manual](https://docs.opnsense.org/manual/gateways.html) and
[OPNsense Static Routes
manual](https://docs.opnsense.org/manual/staticroutes.html)
Retrieved: 2026-05-01

OPNsense splits static-route declaration into TWO blocks:

```xml
<opnsense>
  <gateways>
    <gateway_item>
      <interface>wan</interface>
      <gateway>198.51.100.1</gateway>
      <name>WAN_GW</name>
      <descr>Upstream ISP</descr>
    </gateway_item>
    <gateway_item>
      <interface>lan</interface>
      <gateway>10.0.10.254</gateway>
      <name>LAN_GW</name>
      <descr>Lab gateway</descr>
    </gateway_item>
  </gateways>
  <staticroutes>
    <route>
      <network>10.20.0.0/16</network>
      <gateway>LAN_GW</gateway>
      <descr>Lab subnets</descr>
    </route>
  </staticroutes>
</opnsense>
```

Notes:

- `<gateways>/<gateway_item>` declares NAMED next-hops (each one
  binds a name to an `<interface>` + `<gateway>` IP).
- `<staticroutes>/<route>` references named gateways by their `<name>`
  rather than the bare IP.  This requires a JOIN to translate.
- The default route (`0.0.0.0/0`) is NOT typically expressed as a
  `<route>` element — the OPNsense idiom is to mark a `<gateway_item>`
  as default-on-WAN, which the firewall consumes implicitly.
- IPv6 routes use the same `<staticroutes>/<route>` shape with
  IPv6 prefixes.
- No `set distance` analogue in the per-route element; gateway
  priority lives on `<gateway_item>`.

## Cross-vendor mapping

Canonical fields covered (`CanonicalStaticRoute`):

```
prefix, prefix_length, next_hop, interface, distance, description, vrf
```

FortiGate -> OPNsense:

- **lossy** — Two-stage divergence:
  1. FortiGate's flat per-route table flattens into canonical
     `static_routes` cleanly (FortiGate codec parses `dst`/`mask` ->
     prefix/prefix_length; `gateway` -> `next_hop`; `device` ->
     `interface`).
  2. OPNsense rendering would have to synthesise a `<gateway_item>`
     per unique next-hop on the canonical list (or reuse an
     existing one if the operator pre-declared it), then emit
     `<route>` elements.  The OPNsense codec capability matrix
     does NOT currently advertise `/routing/static-route` as
     supported — render is unwired pending wire-up.
- The default-route idiom diverges: FortiGate's
  `set dst 0.0.0.0 0.0.0.0 / set gateway X` is a first-class entry
  in `config router static`; the OPNsense equivalent is to set the
  WAN zone's default-gateway flag rather than emit a `<route>`.
- `description`: lossy — FortiGate `set comment` is not currently
  parsed by the codec, so canonical `description` is empty after
  FortiGate parse and nothing renders on OPNsense.
- `interface`: lossy — interface name needs the rename mesh
  conversion (FortiGate `port1` -> OPNsense `wan`).
- `distance`: FortiGate `set distance` integer preserves through
  canonical but OPNsense's `<gateway_item>` priority field lives
  outside the per-route block; cross-pair drops this on render.
- `vrf`: not_applicable — FortiGate `set vrf <id>` is not parsed
  in v1; OPNsense has no VRF schema either.
