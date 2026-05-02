# LAGs / link aggregation: MikroTik RouterOS versus FortiGate FortiOS

## MikroTik RouterOS

Sources:
- [Bonding — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8323193/Bonding) — `/interface bonding`.

Retrieved: 2026-04-30

```
/interface bonding
add comment="LACP bond to upstream core" name=bond1 \
    slaves=ether3,ether4 mode=802.3ad
add comment="Active/backup bond to secondary" name=bond2 \
    slaves=ether5,ether6 mode=active-backup
```

Notable RouterOS specifics:

- Bonds live under `/interface bonding`.  `name=` is operator-driven (`bond1`, `bond2`).  `slaves=` is a comma-separated member list.
- `mode=` selects the bonding algorithm:
  - `802.3ad` — IEEE 802.3ad LACP (the only RouterOS LACP form; symmetric — responds to peer mode).
  - `active-backup` — primary/backup failover (no LACP).
  - `balance-rr`, `balance-xor`, `balance-tlb`, `balance-alb`, `broadcast` — Linux-bonding-derived modes with no FortiGate equivalent.
- IP addresses attach to the bond via `/ip address add interface=bond1 ...`.

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Administration Guide — Aggregate interfaces](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings) — `set type aggregate / set member / set lacp-mode`.

Retrieved: 2026-04-30

```
config system interface
    edit "agg1"
        set type aggregate
        set member "port2" "port3"
        set lacp-mode active
    next
end
```

FortiOS aggregate interfaces are operator-named (`agg1`, `LAG_uplink`, etc.) created via `set type aggregate`.  `set member "<port>" "<port>"` is a quoted, space-separated list.  `set lacp-mode active | passive | static` selects the mode.

IP addresses, MTU, and status attach to the aggregate parent.

## Cross-vendor mapping (RouterOS → FortiGate)

Canonical surface (per-LAG):

```
CanonicalLAG.name: str
CanonicalLAG.members: list[str]
CanonicalLAG.mode: str   # "active" (LACP) | "passive" | "static"
```

- **name** — `lossy`.  RouterOS bonds are operator-named (`bond1`); FortiOS aggregates are operator-named (`agg1`).  The port-rename mesh applies operator-curated mappings on cross-vendor render.
- **members** — `good`.  RouterOS `slaves=ether3,ether4` parses to canonical `members=["ether3", "ether4"]`; FortiOS render emits `set member "port3" "port4"` after the rename mesh.
- **mode** — `lossy`.  RouterOS-unique modes lose information on FortiGate render:
  - `802.3ad` -> FortiOS `lacp-mode active` (RouterOS does not distinguish active vs passive LACP, so the FortiGate side defaults to active).
  - `active-backup` -> FortiOS has no native active-backup mode on aggregate interfaces; closest analogue is FortiOS interface redundancy (`set type redundant`) which the FortiGate codec does not currently render via the LAG path.  The render emits `lacp-mode static` with a banner.
  - `balance-rr`, `balance-xor`, `balance-tlb`, `balance-alb`, `broadcast` -> FortiOS has no equivalent; collapse to `lacp-mode static` with banner.  The semantic of the load-distribution algorithm is lost.
- **lag_member_of** on member interfaces — `good`.  RouterOS membership is recorded only on the bond's `slaves=` attribute; the MikroTik codec back-fills `lag_member_of` on each member by inverting the membership map.  FortiOS render adds the rename-meshed member ports to `set member` on the aggregate parent.
- **IP addresses on the bond / aggregate parent** — `good` (handled via the per-interface IP address fields).
