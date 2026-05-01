# Switching philosophy: MikroTik RouterOS versus Cisco IOS-XE

## MikroTik RouterOS

Source: [Bridging and Switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/47579231/Bridging+and+Switching)

Retrieved: 2026-04-30

RouterOS is **router-first**.  Every interface defaults to L3; an
explicit `/interface bridge` object plus `/interface bridge port`
member declarations is required to switch traffic between ports.
Three switching modes:

1. **Pure routing** — no bridge; each `etherN` is its own
   broadcast domain.
2. **Software bridge** — CPU-switched; no hardware offload.
3. **Bridge VLAN filtering** (`vlan-filtering=yes`) — emulates
   Cisco-style switchport semantics on CRS-series hardware via
   ASIC-offloaded VLAN tables.

The CRS3xx, CRS5xx, CCR2116, CCR2216 platforms support hardware-
accelerated bridge VLAN filtering.  Older CRS1xx/2xx use a
deprecated `/interface ethernet switch` plane.

Firewall, NAT, queues, MPLS LSP signalling, and wireless all live
in independent planes that the canonical model treats as Tier-3
informational only.

## Cisco IOS-XE

Cisco IOS-XE distinguishes L2 ports from L3 ports at the interface
level via the `switchport` keyword.  No operator-visible bridge
object — the chassis switching fabric is implicit.  L2 ports take
`switchport mode access|trunk|dot1q-tunnel` plus per-mode
parameters; L3 ports take `ip address` directly.

## Cross-vendor mapping summary (MikroTik -> Cisco direction)

| MikroTik model | Cisco model |
|---|---|
| `etherN` with no bridge membership + `/ip address add interface=etherN` | L3 routed port (`no switchport` + `ip address`) |
| `/interface bridge port` `pvid=N` + `frame-types=admit-only-untagged-and-priority-tagged` | L2 access port (`switchport mode access` + `switchport access vlan N`) |
| `/interface bridge port` `frame-types=admit-only-vlan-tagged` + `/interface bridge vlan` rows | L2 trunk (`switchport mode trunk` + `switchport trunk allowed vlan ...`) |
| `/interface vlan name=vlan10 vlan-id=10 interface=ether1` (Plane 1) | Routed sub-interface `GigabitEthernet0/0/1.10` with `encapsulation dot1q 10` |
| `/interface vlan name=vlan10 vlan-id=10 interface=bridge1` (Plane 1 over Plane 2) | SVI `interface Vlan10` |
| `/interface bonding mode=802.3ad slaves=...` | `interface Port-channel<N>` + per-member `channel-group <N> mode active` |
| Loopback emulation via empty bridge with IP | `interface Loopback<N>` |

### One-way structural losses (MikroTik features lost on Cisco render)

Tier-3 (informational-only on the canonical model; not auto-rendered
by the cross-vendor pipeline regardless of vendor capability):

- `/ip firewall filter` / `/ip firewall nat` / `/ip firewall mangle`
  — RouterOS firewall rules.  Land in `raw_sections` for review.
- `/queue simple` / `/queue tree` — QoS shaping policies.  Tier-3.
- `/interface wireless` — wireless interface configuration.  Tier-3.
- `/system scheduler` / `/system script` — scripting / scheduling.
  Tier-3.
- `/ppp profile` / `/ppp secret` — PPP and PPPoE plumbing.  Tier-3.
- `/ip ipsec` — IPsec tunnel configuration.  Tier-3.
- `/tool` — RouterOS-specific diagnostic / monitoring tools.  Tier-3.

The canonical model does not surface these today; Cisco IOS-XE has
analogous (often very different-shaped) mechanisms but no auto-
render pipeline.  The validation report surfaces unmapped sections.
