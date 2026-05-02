# LAGs / link aggregation: FortiGate FortiOS versus MikroTik RouterOS

## FortiGate FortiOS CLI

Sources:
- [FortiGate / FortiOS 7.4 Administration Guide — Aggregate interfaces](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/954635/interface-settings) — `set type aggregate / set member / set lacp-mode`.

Retrieved: 2026-04-30

```
config system interface
    edit "agg1"
        set alias "downstream-bond"
        set type aggregate
        set member "port2" "port3"
        set lacp-mode active
        set ip 10.20.0.1 255.255.255.0
        set status up
    next
    edit "agg2"
        set type aggregate
        set member "port5" "port6"
        set lacp-mode passive
        set status up
    next
end
```

Notable FortiOS specifics:

- Aggregate interfaces are created via `set type aggregate` on a parent interface name (operator-named: `agg1`, `LAG_uplink`, etc.).
- `set member "<port>" "<port>"` is a quoted, space-separated list of member port names on the same `edit` block.
- `set lacp-mode active | passive | static` selects LACP mode.  `active` initiates LACP; `passive` waits; `static` is no LACP (manual port-channel).
- IP addresses, MTU, and status attach directly to the aggregate parent (members are bare ports with `status up`, no IP / VLAN attached).

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

- Bonds live under `/interface bonding` with operator-driven naming: `bond1`, `bond2`, etc.
- `slaves=etherN,etherM` is a comma-separated member list (no quotes).
- `mode=` selects the bonding algorithm:
  - `802.3ad` — IEEE 802.3ad LACP (the only mode RouterOS labels explicitly as LACP).
  - `active-backup` — primary/backup failover (no LACP).
  - `balance-rr`, `balance-xor`, `balance-tlb`, `balance-alb`, `broadcast` — Linux-bonding-derived modes with no FortiGate equivalent.
- **RouterOS has no separate active/passive LACP mode distinction** — `mode=802.3ad` is symmetric LACP that responds to peer mode.
- IP addresses attach via `/ip address add interface=bond1 address=...`; VLAN child interfaces attach via `/interface vlan add interface=bond1 ...`.

## Cross-vendor mapping (FortiGate → RouterOS)

Canonical surface (per-LAG):

```
CanonicalLAG.name: str
CanonicalLAG.members: list[str]
CanonicalLAG.mode: str   # "active" (LACP) | "passive" | "static"
```

Plus `CanonicalInterface.lag_member_of` on each member port.

- **name** — `lossy`.  FortiOS aggregates are operator-named (`agg1`, `LAG_uplink`); RouterOS bonds are operator-named (`bond1`).  The port-rename mesh applies operator-curated mappings on cross-vendor render.  No structural information is lost — only the surface name.
- **members** — `good`.  FortiOS quoted-list `set member "port2" "port3"` parses to canonical `members=["port2", "port3"]`; RouterOS render emits `slaves=ether2,ether3` after the rename mesh translates port names.
- **mode** — `lossy`.  FortiOS `lacp-mode active` and `lacp-mode passive` both map to RouterOS `mode=802.3ad` (RouterOS does not distinguish active vs passive LACP — its 802.3ad mode is symmetric).  FortiOS `lacp-mode static` (manual port-channel, no LACP) maps to RouterOS `mode=balance-xor` as the closest static-load-distribution analogue, with a banner.  RouterOS-unique modes (active-backup, balance-rr, balance-tlb, balance-alb, broadcast) only appear in the inverse direction.
- **lag_member_of** on member interfaces — `good`.  FortiOS members carry no per-member channel-group reference (the membership is recorded only on the aggregate parent's `set member` list); the FortiGate codec back-fills `lag_member_of` on each member by inverting the membership map.  RouterOS render does not require a per-member directive (membership is on the bond's `slaves=` attribute).
- **IP addresses on the aggregate parent** — `good` (handled via the per-interface IP address fields, not via LAG-specific machinery).
