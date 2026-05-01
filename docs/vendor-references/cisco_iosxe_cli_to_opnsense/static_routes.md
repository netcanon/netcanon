# Static routes: Cisco IOS-XE versus OPNsense

## Cisco IOS-XE

Source: Cisco IOS XE Routing Configuration Guide — `ip route` command
reference.

```
ip route 10.1.0.0 255.255.255.0 192.0.2.1
ip route 10.2.0.0 255.255.0.0 GigabitEthernet1/0/1
ip route 0.0.0.0 0.0.0.0 192.0.2.1
ip route vrf TENANT 10.1.0.0 255.255.255.0 192.0.2.1
```

Optional administrative-distance integer trails the next-hop:

```
ip route 10.1.0.0 255.255.255.0 192.0.2.1 200
```

Per-VRF static routes use the ``vrf <NAME>`` qualifier between
``ip route`` and the destination network.

## OPNsense

Source: [OPNsense Gateways manual](https://docs.opnsense.org/manual/gateways.html)
Retrieved: 2026-04-30

OPNsense splits static-route declaration into TWO config.xml blocks:

```xml
<opnsense>
  <gateways>
    <gateway_item>
      <interface>wan</interface>
      <gateway>198.51.100.1</gateway>
      <name>WAN_GW</name>
      <descr>WAN upstream</descr>
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

The route's ``<gateway>`` element points to a NAMED gateway that must
exist in ``<gateways>``.  This is the documented OPNsense convention:
"static routes ... depend on the entries shown in the gateway page."
A bare next-hop IP cannot live directly on a static-route line —
operators must create or reuse a named gateway first.

OPNsense uses CIDR (``10.1.0.0/24``) throughout.  No dotted-mask
form.

## Cross-vendor mapping

Canonical fields (see ``CanonicalStaticRoute``):

```
destination: str        # CIDR
gateway: str            # next-hop IP
interface: str          # outgoing interface name
metric: int
description: str
```

Cisco -> OPNsense considerations:

- ``destination``: **good** — Cisco's dotted-mask converts to CIDR
  trivially.
- ``gateway``: **lossy** — Cisco's ``ip route ... 192.0.2.1`` uses a
  bare next-hop.  OPNsense requires a NAMED gateway record in
  ``<gateways>``.  The cross-vendor render must synthesise a gateway
  name (e.g. ``GW_192_0_2_1``) and emit BOTH the ``<gateway_item>`` and
  the ``<route>``.  The OPNsense codec does not currently parse OR
  emit ``<staticroutes>``; the cross-pair therefore emits nothing
  (parse-and-ignore).
- ``interface``: **lossy** — Cisco's interface-as-next-hop
  (``ip route X Y GigabitEthernet1/0/1``) has no direct OPNsense
  equivalent.  OPNsense gateways are interface-anchored via
  ``<interface>`` but the named-gateway abstraction means the
  interface is bound to the GATEWAY record, not the route record.
- ``metric``: **lossy** — Cisco's optional administrative-distance
  integer maps loosely to OPNsense gateway ``<priority>`` (different
  scale: Cisco AD 0-255 versus OPNsense priority 1-255 with inverted
  semantics).
- ``description``: **good** — both vendors model free-form route
  descriptions.

Per-VRF static routes (Cisco ``ip route vrf X ...``) are
**unsupported** on the cross-pair: the canonical model
(``CanonicalStaticRoute``) lacks a ``vrf`` field, and OPNsense has no
canonical-portable VRF model.

Disposition: **lossy** at the field level.  At the WIRE-UP level, the
OPNsense codec's capability matrix does not currently advertise any
``/routing/static-route`` path — the canonical static_routes list
parses but the OPNsense render path does not emit
``<staticroutes>``.  Cross-pair effectively drops the route list.
Lands when OPNsense ``<staticroutes>`` + ``<gateways>`` wire-up is
added.
