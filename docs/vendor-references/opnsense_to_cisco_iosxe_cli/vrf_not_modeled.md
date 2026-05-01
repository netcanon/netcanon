# VRF / routing-instance: OPNsense versus Cisco IOS-XE

## OPNsense

OPNsense (FreeBSD-based router/firewall) does NOT model VRFs in
``config.xml``.  FreeBSD does support FIB-based routing tables
(``setfib``), and OPNsense surfaces a per-gateway "FIB" select for
multi-WAN setups, but there is no:

- ``<vrfs>`` or ``<routing-instances>`` block
- route-distinguisher / route-target model
- per-interface VRF-membership element
- BGP-EVPN signalling

OPNsense's "multi-WAN" use case uses gateway groups + policy-based
routing on firewall rules to steer traffic.

The OPNsense parser therefore NEVER POPULATES
``CanonicalIntent.routing_instances`` or
``CanonicalInterface.vrf``.

## Cisco IOS-XE

Cisco IOS-XE has a full enterprise VRF model:

```
vrf definition TENANT_A
 rd 65000:100
 address-family ipv4
  route-target import 65000:100
  route-target export 65000:100
 exit-address-family
!
interface GigabitEthernet1/0/24
 vrf forwarding TENANT_A
 ip address 10.10.10.1 255.255.255.0
!
```

Note however that the ``cisco_iosxe_cli`` codec currently parse-
and-ignores VRF declarations (per its capability matrix entry for
``/routing-instances/instance``); the cross-pair is academic until
that wire-up lands on the Cisco side too.

## Cross-vendor mapping

- ``CanonicalIntent.routing_instances``: **not_applicable** from an
  OPNsense source — the parser never populates this list.  Cisco
  target codec doesn't render the canonical list today either, so
  the cross-pair drops silently.
- ``CanonicalInterface.vrf``: **not_applicable** from an OPNsense
  source — the parser never populates this field.
- ``CanonicalEvpnType5Route``: **not_applicable** — same rationale.
- ``CanonicalVxlan``: **not_applicable** — OPNsense has no VXLAN
  surface either.

Disposition: **not_applicable** for the entire VRF / routing-instance
/ EVPN-VXLAN surface from an OPNsense source.  Operators with VRF
requirements should expect this surface to be a manual rebuild on
the Cisco target.
