# LAGs: MikroTik RouterOS bonding versus Arista EOS Port-Channel

## MikroTik RouterOS

Source: [Bonding — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8323193/Bonding)
Retrieved: 2026-05-01

```
/interface bonding
add comment="LACP bond to upstream core" name=bond1 \
    slaves=ether3,ether4 mode=802.3ad
add comment="Active/backup bond to secondary" name=bond2 \
    slaves=ether5,ether6 mode=active-backup
```

RouterOS bonding is configured under `/interface bonding` with a
`slaves=` attribute listing member interfaces (comma-separated)
and a `mode=` attribute selecting the bonding algorithm:

* `802.3ad` — IEEE 802.3ad LACP (active mode)
* `active-backup` — Linux-style active/backup
* `balance-rr` — round-robin
* `balance-xor` — XOR-based hash (closest static / non-LACP
  analogue)
* `balance-tlb` — adaptive transmit load balancing
* `balance-alb` — adaptive load balancing (TLB + receive)
* `broadcast` — transmit on all slaves

LACP-specific tuning: `lacp-rate=1sec|30secs`,
`transmit-hash-policy=layer-2|layer-2-and-3|layer-3-and-4`.

Naming convention is `bondN` by convention.

## Arista EOS

Source: [Arista EOS — Link Aggregation Control Protocol (LACP)](https://www.arista.com/en/um-eos/eos-link-aggregation-control-protocol-lacp)
Retrieved: 2026-05-01

```
interface Ethernet3
   description "LAG member 1"
   channel-group 1 mode active
!
interface Ethernet4
   description "LAG member 2"
   channel-group 1 mode active
!
interface Port-Channel1
   description "LACP bond to upstream core"
!
```

Arista's port-channel naming uses **capital-C** `Port-Channel<N>`,
distinguishing from Cisco's lowercase-c `Port-channel<N>`.
Member assignment is per-interface via `channel-group <N> mode
active|passive|on`.

The aggregate `interface Port-Channel<N>` carries L3 / switchport
attributes; member ports inherit forwarding state from the
aggregate.

Arista has no MLAG, balance-rr, balance-tlb, balance-alb or
broadcast bonding mode — Arista's `EtherChannel` is purely LACP
+ static, leaving the other RouterOS modes without an
equivalent.

## Cross-vendor mapping

The canonical surface is `CanonicalIntent.lags:
list[CanonicalLAG]` with fields `name` / `members: list[str]` /
`mode` (`active|passive|static`).

RouterOS -> Arista round-trip:

**Mode mapping:**

| RouterOS | Arista | Notes |
|---|---|---|
| `mode=802.3ad` | `mode active` | Direct; LACP active |
| `mode=balance-xor` | `mode on` (static) | Closest static analogue with banner |
| `mode=active-backup` | `mode active` | Lossy — Arista has no active-backup; codec emits banner.  Operator likely wants single-port + STP redundancy or VRRP rather than channel-group. |
| `mode=balance-rr` | `mode on` (static) | Lossy — round-robin not modelled by Arista; banner. |
| `mode=balance-tlb` | `mode on` | Lossy — adaptive load balancing not modelled; banner. |
| `mode=balance-alb` | `mode on` | Same as balance-tlb. |
| `mode=broadcast` | (no equivalent) | Drops with banner; canonical mode falls back to `static`. |

**Naming mesh:** RouterOS `bond1` -> Arista `Port-Channel1` (the
rename mesh canonicalises; capital-C distinguishes from Cisco's
lowercase form).

**Members:** RouterOS `slaves=ether3,ether4` lifts to
`CanonicalLAG.members = ["ether3", "ether4"]`; Arista render
emits `interface Ethernet3 / channel-group 1 mode active` plus
`interface Ethernet4 / channel-group 1 mode active`.

**LACP tuning** (`lacp-rate=`, `transmit-hash-policy=`) lives
outside the canonical surface; lands in raw_sections from the
RouterOS source side and drops on Arista render.  Arista has its
own `lacp rate fast|normal` directive that operator can re-apply
manually if needed.

The MikroTik synthetic kitchen-sink carries `bond1` (LACP /
802.3ad) and `bond2` (active-backup).  `bond1` lifts cleanly to
`CanonicalLAG(name="bond1", mode="active", members=["ether3",
"ether4"])` -> Arista `interface Port-Channel1`.  `bond2`
collapses to `mode="static"` with banner because Arista has no
active-backup; the operator likely wants either separate ports
with STP / VRRP redundancy, or a static-channel-group.

Disposition: **lossy** — LACP modes round-trip cleanly; non-LACP
RouterOS-only modes (active-backup, balance-rr/tlb/alb,
broadcast) collapse to static with operator review banners.
