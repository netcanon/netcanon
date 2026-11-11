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
`mode` (`active|passive|static|active-backup`).  `static` is a
static aggregate whose peer groups its ports too; `active-backup` is
a bond whose peer needs no aggregate.  The Linux bonding guide
([Switch Configuration](https://docs.kernel.org/networking/bonding.html))
says which is which: `active-backup`, `balance-tlb` and
`balance-alb` "do not require any specific configuration of the
switch", while `balance-rr`, `balance-xor` and `broadcast` need the
switch's ports grouped.

RouterOS -> Arista round-trip:

**Mode mapping:**

| RouterOS | Arista | Notes |
|---|---|---|
| `mode=802.3ad` | `mode active` | Direct; LACP active |
| `mode=balance-xor` | `mode on` (static) | Static aggregate (canonical `static`); MikroTik's mode for a static LAG |
| `mode=balance-rr`, or no `mode` (RouterOS's default) | `mode on` (static) | Static aggregate (canonical `static`); round-robin is not modelled, and the inverse writes `balance-xor` |
| `mode=broadcast` | `mode on` (static) | Static aggregate (canonical `static`); the inverse writes `balance-xor` |
| `mode=active-backup` | `mode on` + `! review:` line | Canonical `active-backup`.  Arista has no bond that needs nothing of its peer: written as a static aggregate with a review line and a job warning.  The switch's ports must be configured as that static aggregate, or the host bond re-designed (single port + STP redundancy or VRRP). |
| `mode=balance-tlb` | `mode on` + `! review:` line | Same as active-backup. |
| `mode=balance-alb` | `mode on` + `! review:` line | Same as active-backup. |

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
"ether4"])` -> Arista `interface Port-Channel1`.  `bond2` lifts to
`mode="active-backup"` and is written `channel-group N mode on` with
a `! review:` line because Arista has no active-backup; the operator
likely wants either separate ports with STP / VRRP redundancy, or
the switch's ports configured as that static channel-group.

Disposition: **lossy** — LACP modes round-trip cleanly; the static
modes (balance-xor, balance-rr, broadcast) are written `mode on`;
active-backup, balance-tlb and balance-alb are written `mode on`
with a `! review:` line and a job warning.
