# LAGs: Aruba AOS-S versus MikroTik RouterOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide
— Trunk groups chapter](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
trunk 23-24 trk1 lacp
trunk A3-A4 trk2 trunk
```

Aruba builds LAGs with `trunk <port-list> trk<N> {lacp|trunk|fec|
dt-lacp}`:

- `lacp` — IEEE 802.3ad LACP (active mode by default)
- `trunk` — static link aggregation (no LACP control plane)
- `fec` — HP-proprietary "Fast EtherChannel" (legacy ProCurve)
- `dt-lacp` — distributed-trunk LACP for stacked / VSF chassis
  (multi-chassis LAG)

LAG identity is the bare `Trk<N>` interface name (`Trk1`, `Trk2`),
which appears as a separate `interface Trk1 / name "..."` stanza
for description-bearing config.  Member ports keep their physical
identity (`interface 23 / name "lag-member-23"`).

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

RouterOS bonding uses `/interface bonding add name=<bond> slaves=
<comma-list> mode=<mode>` with modes drawn from the Linux bonding
driver:

- `802.3ad` — LACP (active mode)
- `active-backup` — failover (no Aruba equivalent)
- `balance-rr` — round-robin (no Aruba equivalent)
- `balance-xor` — XOR-based static aggregation (closest to Aruba
  `trunk`)
- `balance-tlb` / `balance-alb` — adaptive load-balancing (no
  Aruba equivalent)
- `broadcast` — broadcast on all slaves (no Aruba equivalent)

The `slaves=` attribute is a comma-separated list of physical
interface names; member ports do not retain their pre-bonding
addressing (RouterOS removes per-slave IP addresses when bonding).

## Cross-vendor mapping

The canonical surface is

```
CanonicalLAG(name, members: list[str], mode: str)
```

with `mode` normalised to `"active"` (LACP active) / `"passive"`
(LACP passive, rare) / `"static"` (a static aggregate: no LACP,
and the peer's ports grouped too) / `"active-backup"` (one port at
a time; the peer's ports need no aggregate).

### Mode mapping

| Aruba | RouterOS | Canonical |
|---|---|---|
| `lacp` | `802.3ad` | `active` |
| `trunk` | `balance-xor` | `static` |
| `fec` | `balance-xor` (with banner) | `static` |
| `dt-lacp` | `802.3ad` (with banner — RouterOS has no MC-LAG) | `active` |
| (no Aruba equivalent) | `balance-rr` / `broadcast` / no `mode` (come back `balance-xor`) | `static` |
| (no Aruba equivalent; the inverse writes `trunk` with a review line) | `active-backup` / `balance-tlb` / `balance-alb` (come back `active-backup`) | `active-backup` |

Aruba `dt-lacp` (multi-chassis distributed-trunk) has no native
RouterOS equivalent — RouterOS does not implement MC-LAG.
Cross-vendor render emits an `802.3ad` bond with a banner noting
the multi-chassis intent has dropped.

### Naming

Aruba `Trk1` -> RouterOS `bond1` (rename mesh canonicalises).  The
codec helper `_extract_lag_number` parses the trailing digit on
the Aruba side; the RouterOS render emits the matching `bond<N>`.

### Member port lists

Aruba's `trunk 23-24 trk1 lacp` expands to two member port records
on parse (interface 23 + interface 24) plus a `Trk1` LAG record;
RouterOS render emits the bond with `slaves=ether23,ether24` after
the rename mesh maps each member.

### Disposition

| Field | Disposition |
|---|---|
| `lags[].name` | lossy (`Trk<N>` <-> `bond<N>` rename) |
| `lags[].members` | good (rename mesh maps physical ports) |
| `lags[].mode` | lossy (Aruba `fec` / `dt-lacp` collapse to `static` / `active` with banner) |
| RouterOS-only modes | lossy on inverse direction (`balance-rr` / `broadcast` -> `static`, written `trunk`; `active-backup` / `balance-tlb` / `balance-alb` -> `active-backup`, written as a static `trunk` with a review line) |
