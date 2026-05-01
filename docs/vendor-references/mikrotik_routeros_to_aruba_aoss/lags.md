# LAGs: MikroTik RouterOS versus Aruba AOS-S

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

RouterOS bonding uses Linux bonding-driver modes:

- `802.3ad` — LACP (active mode)
- `active-backup` — failover (no Aruba equivalent)
- `balance-rr` — round-robin (no Aruba equivalent)
- `balance-xor` — XOR-based static aggregation (closest to Aruba
  static `trunk`)
- `balance-tlb` / `balance-alb` — adaptive load-balancing (no
  Aruba equivalent)
- `broadcast` — broadcast on all slaves (no Aruba equivalent)

Bond identity is `bond<N>`.  The `slaves=` attribute is comma-
separated physical interface names.

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
- `lacp` — IEEE 802.3ad
- `trunk` — static (no LACP)
- `fec` — HP-proprietary (legacy)
- `dt-lacp` — distributed-trunk LACP for multi-chassis aggregation

LAG identity is `Trk<N>`.

## Cross-vendor mapping

The canonical surface is

```
CanonicalLAG(name, members: list[str], mode: str)
```

with `mode` normalised to `"active"` / `"passive"` / `"static"`.

### Mode mapping

| RouterOS | Aruba | Canonical |
|---|---|---|
| `802.3ad` | `lacp` | `active` |
| `active-backup` | (no equivalent) | `static` (with banner) |
| `balance-rr` | (no equivalent) | `static` (with banner) |
| `balance-xor` | `trunk` | `static` |
| `balance-tlb` / `balance-alb` | (no equivalent) | `static` (with banner) |
| `broadcast` | (no equivalent) | `static` (with banner) |

RouterOS-only modes (`active-backup`, `balance-rr`, `balance-tlb`,
`balance-alb`, `broadcast`) have no Aruba equivalent.  Cross-vendor
render to Aruba collapses these to static `trunk` with a banner —
operator must validate that static aggregation is acceptable for
the destination peer.

### Naming

RouterOS `bond1` -> Aruba `Trk1` (rename mesh canonicalises).

### Member port lists

RouterOS `slaves=ether3,ether4` expands to two member port records
on parse; Aruba target render emits `trunk 3-4 trk1 lacp` after
the rename mesh maps the physical ports.  The codec helper
`_extract_lag_number` handles the `bond<N>` -> `trk<N>` integer
suffix preservation.

### Disposition

| Field | Disposition |
|---|---|
| `lags[].name` | lossy (`bond<N>` <-> `Trk<N>` rename) |
| `lags[].members` | good (rename mesh maps physical ports) |
| `lags[].mode` | lossy (RouterOS-only modes collapse to `static` with banner) |
