# LAGs: MikroTik RouterOS bonding versus OPNsense lagg(4)

## MikroTik RouterOS

Source: [Bonding — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8323193/Bonding)

Retrieved: 2026-04-30

```
/interface bonding
add comment="LACP bond to upstream core" name=bond1 \
    slaves=ether3,ether4 mode=802.3ad
add comment="Active/backup bond to secondary" name=bond2 \
    slaves=ether5,ether6 mode=active-backup
```

RouterOS bonding modes mirror the Linux kernel's bonding driver:

| Mode | Description |
|---|---|
| `802.3ad` | LACP (the cross-vendor standard) |
| `active-backup` | One slave active, others standby |
| `balance-rr` | Round-robin packet distribution (no peer support) |
| `balance-xor` | Static hash; no LACP signalling |
| `broadcast` | Frames duplicated to all slaves |
| `balance-tlb` | Adaptive transmit load balancing |
| `balance-alb` | Adaptive load balancing (ARP rewrites) |

LAG name is operator-chosen (``bond1``, ``bond2``); members are
listed inline with ``slaves=ether3,ether4``.

## OPNsense

Source: [OPNsense Devices manual (LAGG tab)](https://docs.opnsense.org/manual/other-interfaces.html)

Retrieved: 2026-04-30

```xml
<laggs version="1.0.0">
  <lagg uuid="...">
    <laggif>lagg0</laggif>
    <members>opt3,opt4</members>
    <proto>lacp</proto>
    <descr>Bonded uplink to core switch</descr>
  </lagg>
</laggs>
```

OPNsense uses the FreeBSD ``lagg(4)`` driver for link aggregation.
LAG names are auto-numbered by the driver (``lagg0``, ``lagg1``,
…) — operators do not freely choose names; the kernel assigns
them in creation order.

OPNsense ``<proto>`` values map to FreeBSD ``lagg(4)`` protocols:

| `<proto>` | Description |
|---|---|
| `lacp` | IEEE 802.3ad LACP (active-only; FreeBSD always negotiates actively) |
| `failover` | Primary/standby (closest to RouterOS active-backup) |
| `loadbalance` | Static hash distribution (closest to RouterOS balance-xor) |
| `roundrobin` | Round-robin (closest to RouterOS balance-rr) |
| `none` | Bundle interfaces without aggregation logic |

## Cross-vendor mapping

Canonical surface:

```
CanonicalLAG(name, members[], mode)
```

The OPNsense codec parses ``<laggs>`` into CanonicalLAG records but
its capability matrix doesn't currently advertise ``/lag/aggregate``
in supported[].  Render is partial pending wire-up.

### name

RouterOS ``bond1`` ↔ OPNsense ``lagg0`` — different naming
conventions (RouterOS one-based, FreeBSD zero-based).  Port-rename
mesh canonicalises.

### members

RouterOS ``slaves=ether3,ether4`` ↔ OPNsense ``<members>opt3,opt4
</members>``.  Member lists round-trip via the rename mesh.  Note
that OPNsense's ``<members>`` lists ZONE names rather than BSD
device names in the synthetic kitchen-sink (so the parser's
reverse-link to ``CanonicalInterface.name`` matches the zone tag).

### mode

Mode mapping:

| RouterOS `mode=` | OPNsense `<proto>` | Notes |
|---|---|---|
| `802.3ad` | `lacp` | Direct match |
| `active-backup` | `failover` | Direct match |
| `balance-xor` | `loadbalance` | Direct match |
| `balance-rr` | `roundrobin` | Direct match |
| `broadcast` | (none) | OPNsense has no broadcast mode; collapse to `loadbalance` with banner |
| `balance-tlb` | (none) | FreeBSD lagg has no adaptive-TLB mode; collapse to `failover` with banner |
| `balance-alb` | (none) | FreeBSD lagg has no adaptive-ALB mode; collapse to `failover` with banner |

LACP-specific extras (system-priority, key, port-priority) are not
modelled canonically (CanonicalLAG carries ``mode`` only); cross-pair
emits FreeBSD defaults on render.

### Disposition

| Field | Disposition |
|---|---|
| `lags[].name` | lossy (rename-mesh canonicalises) |
| `lags[].members` | lossy (rename-mesh canonicalises member identities) |
| `lags[].mode` | lossy (RouterOS-rich modes collapse on FreeBSD lagg) |
