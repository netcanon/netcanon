# VRF / routing-instance unsupported on both vendors (RouterOS source -> OPNsense target)

## RouterOS side: codec parser gap

RouterOS 7+ has VRF support via ``/ip vrf``:

```
/ip vrf
add name=TENANT-A interfaces=ether2,vlan100
add name=TENANT-B interfaces=ether3
```

Each VRF binds a list of interfaces; per-VRF static routes carry
``routing-table=TENANT-A``; per-VRF BGP / OSPF instances live under
``/routing bgp/instance`` and ``/routing ospf/instance``.

**The MikroTik codec does NOT yet parse ``/ip vrf``.**  The canonical
``routing_instances`` list is empty after parsing a RouterOS source
even when the source carries VRF declarations.  Per-interface
``CanonicalInterface.vrf`` field is also empty.  Documented as
unsupported on the codec side pending wire-up.

## OPNsense side: no VRF model

OPNsense's ``config.xml`` has **no VRF schema**.  FreeBSD does
support FIBs (multiple routing tables via ``setfib(1)`` / ``net.fibs``
sysctl) and ``vnet`` jails for full network-stack isolation, but
neither is exposed through OPNsense's web GUI or ``config.xml``
schema.  The OPNsense codec has no place to write a VRF declaration
and never emits one.

## Cross-pair disposition

The cross-pair surface is **empty regardless of structural
compatibility**:

- Source side never populates the canonical VRF list (parser gap).
- Target side has no XML block to render into.

Both vendors land at unsupported on this surface.  When MikroTik
codec wire-up lands, the cross-pair surface will UPGRADE to
unsupported (RouterOS source can carry VRFs; OPNsense target
structurally cannot — flatten to global table with banner).

## EVPN / VXLAN

RouterOS does not support EVPN at all; ``/ip vrf`` carries no
``l3-vni`` analogue.  OPNsense (as a firewall codec) does not model
VXLAN or EVPN either — both codecs list ``/vxlan-vnis/vni`` under
unsupported in their capability matrices.  ``vxlan_vnis`` and
``evpn_type5_routes`` canonical lists stay empty in both directions
between this pair.

## Disposition

| Field | Disposition |
|---|---|
| `routing_instances` | unsupported (RouterOS parser gap; OPNsense has no VRF) |
| `interfaces[].vrf` | unsupported |
| `vxlan_vnis` | unsupported (neither vendor models VXLAN in canonical scope) |
| `evpn_type5_routes` | unsupported (neither vendor models EVPN) |
