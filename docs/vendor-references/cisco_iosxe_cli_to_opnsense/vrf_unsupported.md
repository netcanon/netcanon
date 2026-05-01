# VRF / routing-instance: Cisco IOS-XE versus OPNsense

## Cisco IOS-XE

Source: Cisco IOS XE VPN Configuration Guide — VRF / Multi-VRF CE.

```
vrf definition TENANT_A
 description Customer A Layer-3 VRF
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
ip route vrf TENANT_A 10.20.0.0 255.255.255.0 10.10.10.254
```

Cisco IOS-XE models a full enterprise VRF surface with route
distinguishers, route-target import/export, per-VRF routing tables,
and per-interface ``vrf forwarding`` membership.

## OPNsense

OPNsense (FreeBSD-based router/firewall) does NOT model VRFs in
``config.xml``.  FreeBSD does support FIB-based virtual routing
tables (``setfib``), and OPNsense surfaces a per-gateway "FIB" select
for advanced setups, but there is no:

- ``<vrfs>`` or ``<routing-instances>`` block in ``config.xml``
- ``<route-distinguisher>`` element
- per-interface ``<vrf>`` element
- BGP-EVPN signalling for L3VPN

OPNsense's "multi-WAN" use case uses gateway groups + policy-based
routing on firewall rules to steer traffic between independent
upstream paths — semantically very different from MPLS-style VRF
isolation.

## Cross-vendor mapping

Canonical fields impacted:

- ``CanonicalRoutingInstance`` (the entire model): **unsupported**
  on OPNsense.  No corresponding XML elements in ``config.xml``.
- ``CanonicalInterface.vrf``: **unsupported** — OPNsense interfaces
  carry no VRF-membership field.

Note: the Cisco IOS-XE codec itself currently parse-and-ignores VRF
declarations (per its capability matrix entry for
``/routing-instances/instance``).  The cross-pair therefore drops
to ``unsupported`` from BOTH sides — Cisco source emits no canonical
``CanonicalRoutingInstance`` records, and OPNsense target couldn't
render them anyway.

Disposition: **unsupported**.  Operators migrating Cisco multi-VRF
configurations to OPNsense must replace the VRF isolation with a
firewall-based segmentation model (separate zones with explicit
inter-zone rules), which is a fundamentally different network
topology.
