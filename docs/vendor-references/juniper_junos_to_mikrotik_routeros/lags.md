# LAGs (link aggregation): Juniper Junos versus MikroTik RouterOS

How aggregated-Ethernet / bonding interfaces are declared on each
platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/lag-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sampling-forwarding-monitoring/topics/example/lag-aggregated-ethernet-link-configuring.html (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/8323193/Bonding (retrieved 2026-05-01)

Citation ids: `junos-lag-overview`, `junos-ae-example`,
`mikrotik-bonding`.

## Junos form

```
set chassis aggregated-devices ethernet device-count 2

set interfaces ge-0/0/2 description "LAG ae0 member 1"
set interfaces ge-0/0/2 ether-options 802.3ad ae0
set interfaces ge-0/0/3 description "LAG ae0 member 2"
set interfaces ge-0/0/3 ether-options 802.3ad ae0

set interfaces ae0 description "Bonded uplink to spine"
set interfaces ae0 mtu 9192
set interfaces ae0 aggregated-ether-options lacp active
set interfaces ae0 unit 0 family inet address 10.1.0.1/31
```

Junos uses `ae<N>` (aggregated-Ethernet) interfaces.  Membership is
declared on the physical (member) side via `ether-options 802.3ad
ae<N>`; LACP mode (active / passive) lives under the `ae<N>`
record's `aggregated-ether-options lacp` sub-tree.  Junos requires
a chassis-wide `aggregated-devices ethernet device-count <N>`
allocation that pre-allocates the maximum number of ae interfaces
the chassis will support.

## RouterOS form

```
/interface bonding
add comment="LACP bond to upstream core" name=bond1 \
    slaves=ether3,ether4 mode=802.3ad
add comment="Active/backup bond" name=bond2 \
    slaves=ether5,ether6 mode=active-backup

/ip address
add address=10.255.0.1/32 interface=bond1
```

RouterOS uses `/interface bonding` records with a named primary
interface (`name=bond1`) and a comma-separated `slaves=` list.  No
chassis-wide allocation step.  Mode tokens: `802.3ad` (LACP),
`active-backup` (failover, no Junos analogue), `balance-rr`
(round-robin), `balance-xor` (static hash), `balance-tlb` /
`balance-alb` (adaptive load-balancing), `broadcast`.  Only `802.3ad`
maps cleanly to a Junos LAG; the others are RouterOS-only.

## Cross-vendor mapping

* `lags[].name`: Junos `ae<N>` -> RouterOS `bond<N>` (codec policy).
  Naming convention preserved through the rename mesh.
* `lags[].members`: Junos's per-member `ether-options 802.3ad ae<N>`
  back-pointer transposes to the canonical `members: list[str]` on
  the LAG record and back to RouterOS `slaves=` (forward list).
  Member names follow the per-pane port-rename mesh.
* `lags[].mode`: Junos `aggregated-ether-options lacp active` ->
  RouterOS `mode=802.3ad`.  Junos has no `passive` distinct from
  `active` once LACP is enabled; the canonical `passive` enum value
  collapses to `802.3ad` on RouterOS render.  Junos's static (no-LACP)
  membership maps to RouterOS `mode=balance-xor` (closest static
  analogue) with a banner.
* RouterOS-only modes (`active-backup`, `balance-rr`, `balance-tlb`,
  `balance-alb`, `broadcast`) have no Junos equivalent and would only
  appear in the inverse direction.
* Chassis allocation: Junos's `set chassis aggregated-devices
  ethernet device-count` has no RouterOS analogue (RouterOS
  allocates dynamically per-bond); drops on render.

Disposition: **good** for typical LACP bonds with documented mode
mappings; **lossy** for static / non-LACP modes (collapse to
balance-xor) and for chassis-wide allocation.
