# LAGs: OPNsense lagg(4) versus MikroTik RouterOS bonding

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

OPNsense uses the FreeBSD ``lagg(4)`` driver.  LAG names are
auto-numbered (``lagg0``, ``lagg1``, …); kernel-assigned in
creation order.  ``<proto>`` values: ``lacp`` (active-only),
``failover``, ``loadbalance``, ``roundrobin``, ``none``.

## MikroTik RouterOS

Source: [Bonding — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8323193/Bonding)

Retrieved: 2026-04-30

```
/interface bonding
add comment="Bonded uplink to core switch" name=bond1 \
    slaves=ether3,ether4 mode=802.3ad
```

RouterOS bonding modes mirror Linux kernel bonding driver:

| Mode | Description |
|---|---|
| `802.3ad` | LACP |
| `active-backup` | Primary / standby |
| `balance-rr` | Round-robin |
| `balance-xor` | Static hash |
| `broadcast` | Frames duplicated |
| `balance-tlb` | Adaptive transmit load balancing |
| `balance-alb` | Adaptive load balancing |

LAG names operator-chosen.

## Cross-vendor mapping

Canonical surface:

```
CanonicalLAG(name, members[], mode)
```

The OPNsense codec parses ``<laggs>`` into CanonicalLAG records but
its capability matrix doesn't currently advertise ``/lag/aggregate``
in supported[].  Render is partial pending wire-up.

### name

OPNsense ``lagg0`` ↔ RouterOS ``bond1`` — different naming
conventions (FreeBSD zero-based, RouterOS one-based).  Port-rename
mesh canonicalises.

### members

OPNsense ``<members>opt3,opt4</members>`` ↔ RouterOS
``slaves=ether3,ether4``.  Member identities differ; port-rename
mesh canonicalises.

### mode

Mode mapping (cleaner than the inverse direction because OPNsense's
mode set is a subset of RouterOS's):

| OPNsense `<proto>` | RouterOS `mode=` |
|---|---|
| `lacp` | `802.3ad` |
| `failover` | `active-backup` |
| `loadbalance` | `balance-xor` |
| `roundrobin` | `balance-rr` |
| `none` | (no direct equivalent; collapse to `balance-xor` with banner) |

LACP-specific extras (system-priority, key, port-priority) are not
modelled canonically; cross-pair emits RouterOS defaults on render.

### Disposition

| Field | Disposition |
|---|---|
| `lags[].name` | lossy (rename-mesh canonicalises) |
| `lags[].members` | lossy (rename-mesh canonicalises member identities) |
| `lags[].mode` | lossy (`<proto>none</proto>` has no clean RouterOS analogue) |
