# LAGs: OPNsense lagg(4) versus MikroTik RouterOS bonding

## OPNsense

Source: [OPNsense Devices manual (LAGG tab)](https://docs.opnsense.org/manual/other-interfaces.html)

Retrieved: 2026-04-30

```xml
<laggs version="1.0.0">
  <lagg uuid="...">
    <laggif>lagg0</laggif>
    <members>igb2,igb3</members>
    <proto>lacp</proto>
    <descr>Bonded uplink to core switch</descr>
  </lagg>
</laggs>
```

OPNsense uses the FreeBSD ``lagg(4)`` driver.  LAG names are
auto-numbered (``lagg0``, ``lagg1``, …); kernel-assigned in
creation order.  ``<proto>`` values: ``lacp`` (active-only),
``failover``, ``fec``, ``loadbalance``, ``roundrobin``, ``none``.
``failover`` by default accepts traffic only on the active port and
needs no aggregate on the peer; ``loadbalance`` "is a static setup
and does not negotiate aggregation with the peer"; ``none`` passes
no traffic ([FreeBSD
lagg(4)](https://man.freebsd.org/cgi/man.cgi?query=lagg&sektion=4)).

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

``mode`` is one of ``active`` / ``passive`` (LACP), ``static`` (a
static aggregate: the peer's ports are grouped too) and
``active-backup`` (the peer's ports need no aggregate).  The OPNsense
and RouterOS capability matrices classify ``/lags/lag/name`` and
``/lags/lag/members`` as supported and ``/lags/lag/mode`` as lossy.

### name

OPNsense ``lagg<N>`` ↔ RouterOS ``bond<N>`` — different naming
conventions (FreeBSD zero-based, RouterOS one-based).  The port
translator keeps the number (``lagg5`` is ``bond5``) and writes
``lagg0`` as ``bond1``, so ``lagg0`` beside ``lagg1`` is two LAGs on
one name: the job is ``partial`` and lists both.  There is no +1
offset.  The bare pipeline (``run_plan``) translates no port names,
and writes the source's name (``name=lagg0``).

### members

OPNsense ``<members>igb2,igb3</members>`` ↔ RouterOS
``slaves=ether3,ether4``.  Member identities differ; port-rename
mesh canonicalises.  A member is a BSD device name in no zone:
"Only unassigned interfaces can be added to LAGG" (same page, Other
Types); the example listed zone names until 2026-10-20.

### mode

Mode mapping (cleaner than the inverse direction because OPNsense's
mode set is a subset of RouterOS's):

| OPNsense `<proto>` | RouterOS `mode=` |
|---|---|
| `lacp` | `802.3ad` (canonical `active`) |
| `failover` | `active-backup` (canonical `active-backup`) |
| `loadbalance` / `fec` | `balance-xor` (canonical `static`) |
| `roundrobin` | `balance-xor` (canonical `static`; the round-robin algorithm is not kept) |
| `none` | `balance-xor` (read as `static`, a known limitation: `none` passes no traffic, and the tree has no value for it) |

LACP-specific extras (system-priority, key, port-priority) are not
modelled canonically; cross-pair emits RouterOS defaults on render.

### Disposition

| Field | Disposition |
|---|---|
| `lags[].name` | lossy (rename-mesh canonicalises) |
| `lags[].members` | lossy (rename-mesh canonicalises member identities) |
| `lags[].mode` | lossy (`roundrobin`, `fec` and `none` come back as `balance-xor`; `<proto>none</proto>` has no clean RouterOS analogue) |
