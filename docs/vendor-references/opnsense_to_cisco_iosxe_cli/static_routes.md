# Static routes: OPNsense versus Cisco IOS-XE

## OPNsense

Source: [OPNsense Gateways manual](https://docs.opnsense.org/manual/gateways.html)
Retrieved: 2026-04-30

OPNsense splits static-route declaration into TWO blocks:

```xml
<opnsense>
  <gateways>
    <gateway_item>
      <interface>wan</interface>
      <gateway>198.51.100.1</gateway>
      <name>WAN_GW</name>
      <ipprotocol>inet</ipprotocol>
      <priority>254</priority>
    </gateway_item>
  </gateways>
  <staticroutes>
    <route>
      <network>10.1.0.0/24</network>
      <gateway>WAN_GW</gateway>
      <descr>Tenant subnet via WAN</descr>
      <disabled>0</disabled>
    </route>
  </staticroutes>
</opnsense>
```

Routes reference NAMED gateways from the ``<gateways>`` block.  The
documentation: "static routes ... depend on the entries shown in the
gateway page."  CIDR throughout; no dotted-mask form.

The OPNsense codec does NOT currently parse ``<staticroutes>`` into
``CanonicalIntent.static_routes`` — the canonical list is empty on
OPNsense-source intent today.

## Cisco IOS-XE

Source: Cisco IOS XE Routing Configuration Guide — `ip route` command.

```
ip route 10.1.0.0 255.255.255.0 192.0.2.1
ip route 0.0.0.0 0.0.0.0 192.0.2.1
ip route vrf TENANT 10.1.0.0 255.255.255.0 192.0.2.1
```

Bare next-hop IP form; dotted-mask; per-VRF qualifier optional.

## Cross-vendor mapping

Canonical fields (see ``CanonicalStaticRoute``):

```
destination, gateway, interface, metric, description
```

OPNsense -> Cisco:

- ``destination``: would be **good** once OPNsense parse wire-up
  lands — CIDR ↔ dotted-mask conversion is mechanical.
- ``gateway``: **lossy** — OPNsense's named-gateway indirection
  means the canonical ``gateway`` field would need to hold the
  resolved IP (not the OPNsense ``WAN_GW`` name).  Resolution
  requires reading the ``<gateways>`` block alongside; the codec
  must do the lookup.
- ``interface``: **lossy** — OPNsense gateways are bound to a zone
  via ``<gateway_item>/<interface>`` rather than a per-route
  interface.  The cross-pair would need to translate the zone label
  to a Cisco interface name (which would still be opaque without
  port-rename information).
- ``metric``: **lossy** — OPNsense's ``<priority>`` (1-255 with
  inverted semantics) maps loosely to Cisco's optional administrative
  -distance integer (0-255).
- ``description``: **good** — both vendors model free-form route
  descriptions.

WIRE-UP DISPOSITION: **lossy** because the OPNsense codec doesn't
currently parse ``<staticroutes>`` (no canonical records emitted
from OPNsense source).  Cross-pair therefore emits no Cisco
``ip route`` lines today.  Lands when OPNsense parse wire-up
completes.
