# LAGs (link aggregation): MikroTik RouterOS versus Juniper Junos

How aggregated-Ethernet / bonding interfaces are declared on each
platform.

Sources:
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/8323193/Bonding (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/lag-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/sampling-forwarding-monitoring/topics/example/lag-aggregated-ethernet-link-configuring.html (retrieved 2026-05-01)

Citation ids: `mikrotik-bonding`, `junos-lag-overview`,
`junos-ae-example`.

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
interface and a comma-separated `slaves=` list.  No chassis-wide
allocation step.  Mode tokens: `802.3ad` (LACP), `active-backup`
(failover, no Junos analogue), `balance-rr` (round-robin),
`balance-xor` (static hash), `balance-tlb` / `balance-alb`
(adaptive load-balancing), `broadcast`.

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
allocation.

## Cross-vendor mapping

* `lags[].name`: RouterOS `bond<N>` -> Junos `ae<N>` (codec policy).
  Naming convention preserved through the rename mesh.
* `lags[].members`: RouterOS `slaves=` -> Junos per-member
  `ether-options 802.3ad ae<N>` back-pointer.  Member names follow
  the per-pane port-rename mesh.
* `lags[].mode`: RouterOS `mode=802.3ad` -> Junos
  `aggregated-ether-options lacp active`.  RouterOS-only modes
  (`active-backup`, `balance-rr`, `balance-tlb`, `balance-alb`,
  `broadcast`) have no Junos LAG-record equivalent — flatten to
  `lacp active` with banner OR drop to a non-aggregated form.
* RouterOS `mode=balance-xor` (static hash) -> Junos LAG without
  `lacp` (membership only).  Closest match.
* Chassis allocation: RouterOS dynamic; Junos render emits a
  synthesised `set chassis aggregated-devices ethernet device-count
  <N>` based on the count of `ae<N>` interfaces created.
* MTU and addressing: RouterOS bond's `/ip address` -> Junos `ae0
  unit 0 family inet address`.

Disposition: **lossy** — `802.3ad` / `balance-xor` / `802.3ad-with-
mode-changes` map cleanly; the RouterOS-only modes (active-backup,
balance-rr, balance-tlb, balance-alb, broadcast) collapse with
banner; chassis device-count synthesised on render.
