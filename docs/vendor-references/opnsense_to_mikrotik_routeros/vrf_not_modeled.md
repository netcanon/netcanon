# VRF not modelled on OPNsense source (OPNsense -> RouterOS)

## OPNsense side: no VRF model

OPNsense's ``config.xml`` has **no VRF schema**.  FreeBSD does
support FIBs (multiple routing tables via ``setfib(1)`` / ``net.fibs``
sysctl) and ``vnet`` jails for full network-stack isolation, but
neither is exposed through OPNsense's web GUI or ``config.xml``.

The OPNsense codec NEVER populates:

- ``CanonicalIntent.routing_instances``
- ``CanonicalInterface.vrf``

These fields stay at their default empty values after an OPNsense
parse.

## RouterOS side: parser gap

RouterOS 7+ has VRF support via ``/ip vrf``:

```
/ip vrf
add name=TENANT-A interfaces=ether2
```

But the MikroTik codec does NOT yet wire up the parser.  Even if the
canonical ``routing_instances`` list WERE populated by some other
source, the RouterOS target render would not emit ``/ip vrf`` lines
in v1.

## Cross-pair disposition: not_applicable

On the OPNsense -> RouterOS direction:

- Source never populates the canonical VRF list (no model).
- Target codec parser is a known gap (no ``/ip vrf`` wire-up yet).

Cross-pair surface is empty regardless.  When the MikroTik codec's
``/ip vrf`` wire-up lands, the cross-pair surface stays
not_applicable on this direction (the source still never populates).

## EVPN / VXLAN

OPNsense (firewall codec) and RouterOS (rare canonical scope) both
list ``/vxlan-vnis/vni`` under unsupported in their capability
matrices.  ``vxlan_vnis`` and ``evpn_type5_routes`` canonical lists
stay empty in both directions between this pair.

## Disposition

| Field | Disposition |
|---|---|
| `routing_instances` | not_applicable (OPNsense never populates) |
| `interfaces[].vrf` | not_applicable |
| `vxlan_vnis` | not_applicable |
| `evpn_type5_routes` | not_applicable |
