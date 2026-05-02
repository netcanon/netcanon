# LAGs: Arista EOS Port-Channel versus MikroTik RouterOS bonding

## Arista EOS

Source: [Arista EOS — Link Aggregation Control Protocol (LACP)](https://www.arista.com/en/um-eos/eos-link-aggregation-control-protocol-lacp)
Retrieved: 2026-05-01

```
interface Ethernet4
   description "LAG member 1"
   channel-group 10 mode active
!
interface Ethernet5
   description "LAG member 2"
   channel-group 10 mode active
!
interface Port-Channel10
   description "Bonded uplink to core"
   no switchport
   ip address 10.0.1.1/31
!
interface Port-Channel20
   description "Bonded trunk to leaf-02"
   switchport mode trunk
   switchport trunk allowed vlan 100,200
```

Arista's port-channel naming uses **capital-C** `Port-Channel<N>`,
distinguishing from Cisco IOS-XE / NX-OS's lowercase-c
`Port-channel<N>`.  Member assignment is per-interface via
`channel-group <N> mode active|passive|on` (active/passive =
LACP; on = static).

The aggregate `interface Port-Channel<N>` carries L3 / switchport
attributes; member ports inherit forwarding state from the
aggregate.

MLAG (multi-chassis LAG) lives under a separate
`mlag configuration` block — a paired-switch construct where
two physical switches present a single LAG to the downstream
device.  The canonical model has no MLAG primitive; MLAG-
specific attributes drop to raw_sections.

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

Naming convention is `bondN` by convention (operator-chosen).

There is no MC-LAG / MLAG concept on stock RouterOS — RouterOS
operates standalone bonds; for redundancy at the device level,
operators use VRRP or routing protocols.

## Cross-vendor mapping

The canonical surface is `CanonicalIntent.lags:
list[CanonicalLAG]` with fields `name` / `members: list[str]` /
`mode` (`active|passive|static`).  Per-interface
`CanonicalInterface.lag_member_of` carries the back-pointer.

Arista -> RouterOS round-trip:

**Mode mapping:**

| Arista | RouterOS | Notes |
|---|---|---|
| `mode active` | `mode=802.3ad` | Direct; LACP active |
| `mode passive` | `mode=802.3ad` | Direct; LACP passive (codec emits banner — RouterOS does not distinguish) |
| `mode on` (static) | `mode=balance-xor` | Closest non-LACP analogue with banner |

**Naming mesh:** Arista `Port-Channel10` -> RouterOS `bond1` (or
`bond10` to preserve the index — operator preference).  The
rename mesh canonicalises across the cross-pair.

**Members:** Arista's per-member `channel-group N mode active`
projection lifts to canonical `CanonicalLAG.members =
["Ethernet4", "Ethernet5"]`; RouterOS render emits `slaves=
ether3,ether4` after the rename mesh.

**MLAG:** Arista's `mlag configuration` peer-bond is structurally
absent on RouterOS — the canonical model has no MLAG primitive,
and the rendered RouterOS config emits a single-chassis bond with
a banner noting the loss of multi-chassis redundancy.  Operator
must re-implement using VRRP or routing-level redundancy.

**RouterOS-only modes** (active-backup, balance-rr, balance-tlb,
balance-alb, broadcast) have no Arista equivalent and would only
appear in the inverse direction (RouterOS source).

**LACP tuning** (`lacp-rate=1sec`, `transmit-hash-policy`) lives
outside the canonical surface; lands in raw_sections from the
RouterOS source side, drops on render from the Arista source
side.

The Arista synthetic kitchen-sink (`ks-leaf-01`) carries
`Port-Channel10` (bonded uplink, L3) and `Port-Channel20`
(bonded trunk, L2 with allowed VLANs).  Both lift to canonical
`CanonicalLAG` records and render to RouterOS as `/interface
bonding` rows; the L3 IP and L2 trunk membership lift through
their respective channels (interfaces, vlans).

Disposition: **lossy** — mode mapping with banners on
non-LACP/passive cases; MLAG drops; RouterOS-only modes appear
inverse-only.
