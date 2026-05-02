# Static routes: OPNsense versus MikroTik RouterOS

## OPNsense

Source: [OPNsense Gateways manual](https://docs.opnsense.org/manual/gateways.html)

Retrieved: 2026-04-30

OPNsense splits static-route declaration into TWO blocks in
``config.xml``:

```xml
<gateways>
  <gateway_item>
    <name>WAN_GW</name>
    <interface>wan</interface>
    <gateway>198.51.100.1</gateway>
    <ipprotocol>inet</ipprotocol>
  </gateway_item>
</gateways>
<staticroutes version="1.0.0">
  <route uuid="...">
    <network>10.50.0.0/16</network>
    <gateway>WAN_GW</gateway>
    <descr>Lab tenant subnet via WAN</descr>
    <disabled>0</disabled>
  </route>
</staticroutes>
```

The ``<gateways>`` block declares NAMED gateways (reusable handles)
that bind a next-hop IP to an OPNsense zone.  ``<staticroutes>``
references those named gateways by ``<gateway>WAN_GW</gateway>``
rather than embedding the IP directly — OPNsense-specific plumbing.

## MikroTik RouterOS

Source: [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)

Retrieved: 2026-04-30

```
/ip route
add comment="Lab tenant subnet via WAN" \
    dst-address=10.50.0.0/16 gateway=198.51.100.1
add comment="Default route to ISP" \
    dst-address=0.0.0.0/0 gateway=198.51.100.1
```

RouterOS uses CIDR notation natively.  Gateway can be either an IP
address or an interface name (``gateway=ether2``).  No named-gateway
indirection.

## Cross-vendor mapping

Canonical surface:

```
CanonicalStaticRoute(destination, gateway, interface, metric,
                     description)
```

The OPNsense codec does not currently parse the ``<gateways>`` /
``<staticroutes>`` blocks (nothing in capability matrix.supported
references either path).  Canonical ``static_routes`` list arrives
EMPTY from an OPNsense source today.  RouterOS target therefore
emits no ``/ip route add`` lines from an OPNsense source.  Lands
when OPNsense parse wire-up resolves the gateway-name indirection
to bare next-hop IPs.

### Specific lossy points

- **Default-table routes** — would round-trip cleanly when wire-up
  lands (CIDR ↔ CIDR).
- **Default route (``0.0.0.0/0``)** — OPNsense's idiom is the
  WAN-zone ``<gateway>`` attribute (referencing a ``<gateway_item>``
  by name), not a ``<staticroutes>`` ``0.0.0.0/0`` entry.  Operator-
  curated mapping to RouterOS's ``dst-address=0.0.0.0/0`` form.
- **Gateway-name indirection** — OPNsense ``<gateway>WAN_GW</gateway>``
  must be resolved to the underlying IP via the ``<gateways>``
  block's ``<gateway>198.51.100.1</gateway>`` attribute.  Codec
  must walk the named-gateway table on parse.
- **Per-VRF routes** — OPNsense has no VRF model, so the source
  never carries per-VRF routes.  RouterOS target codec also doesn't
  parse ``routing-table=`` today.
- **IPv6 routes** — same parse wire-up gap as IPv4.

### Disposition

| Field | Disposition |
|---|---|
| `static_routes[].destination` | lossy (OPNsense parse wire-up pending) |
| `static_routes[].gateway` | lossy (named-gateway indirection; parse wire-up pending) |
| `static_routes[].interface` | lossy (OPNsense parse wire-up pending) |
| `static_routes[].metric` | lossy (OPNsense parse wire-up pending) |
| `static_routes[].description` | lossy (OPNsense parse wire-up pending) |
