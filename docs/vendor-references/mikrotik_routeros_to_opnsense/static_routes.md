# Static routes: MikroTik RouterOS versus OPNsense

## MikroTik RouterOS

Source: [IP Routing — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing)

Retrieved: 2026-04-30

```
/ip route
add comment="Default route to ISP" dst-address=0.0.0.0/0 gateway=198.51.100.1
add comment="Branch network via core" dst-address=10.50.0.0/16 gateway=10.0.0.254
add comment="Blackhole RFC1918 leakage" dst-address=192.168.99.0/24 gateway=bridge1
add comment="IPv6 default" dst-address=::/0 gateway=2001:db8:0:1::1
```

RouterOS uses CIDR notation natively (``dst-address=10.0.0.0/24``).
Gateway can be either an IP address (``gateway=198.51.100.1``) or
an interface name (``gateway=ether2`` / ``gateway=bridge1``).
Per-VRF routes carry a ``routing-table=TENANT-A`` parameter — the
MikroTik codec does not yet parse VRF context.

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

The ``<gateways>/<gateway_item>`` block declares NAMED gateways
(reusable handles) that bind a next-hop IP to an OPNsense zone.
The ``<staticroutes>/<route>`` block then references those named
gateways by ``<gateway>WAN_GW</gateway>`` rather than embedding
the IP directly.  This is OPNsense-specific plumbing that has no
counterpart on RouterOS (where ``gateway=`` carries the IP or
interface inline).

## Cross-vendor mapping

Canonical surface:

```
CanonicalStaticRoute(destination, gateway, interface, metric,
                     description)
```

The OPNsense codec does not currently parse OR emit the
``<gateways>`` / ``<staticroutes>`` blocks (nothing in capability
matrix.supported references either path).  RouterOS-source canonical
``static_routes`` therefore drop on render — render emits no
``<staticroutes>`` block.

### Specific lossy points

- **Default-table routes** — ``/ip route add dst-address=
  10.50.0.0/16 gateway=10.0.0.254`` arrives in canonical with
  ``destination="10.50.0.0/16"`` + ``gateway="10.0.0.254"`` but
  the OPNsense render path skips it.  Lands when wire-up is added.
- **Default route (``0.0.0.0/0``)** — RouterOS expresses the default
  via a ``dst-address=0.0.0.0/0`` static route; OPNsense's idiom is
  to set the WAN zone's ``<gateway>`` attribute (which references a
  ``<gateway_item>`` by name).  Operator-curated mapping needed.
- **Per-VRF routes** — RouterOS ``routing-table=TENANT-A`` is not
  modelled on canonical (CanonicalStaticRoute has no ``vrf`` field)
  and the MikroTik codec does not yet parse VRF context.  Drops
  unconditionally.
- **Interface-as-gateway** — RouterOS ``gateway=bridge1`` (interface
  name as next-hop) maps to OPNsense's named-gateway pattern with
  ``<interface>...</interface>`` set; not a 1:1 wire shape.
- **IPv6 routes** — same parser gap as IPv4 on the OPNsense side.

### Disposition

| Field | Disposition |
|---|---|
| `static_routes[].destination` | lossy (OPNsense render wire-up pending) |
| `static_routes[].gateway` | lossy (OPNsense render wire-up pending; named-gateway indirection) |
| `static_routes[].interface` | lossy (OPNsense render wire-up pending) |
| `static_routes[].metric` | lossy (OPNsense render wire-up pending) |
| `static_routes[].description` | lossy (OPNsense render wire-up pending; otherwise good) |
