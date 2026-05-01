# Switching philosophy: Cisco IOS-XE versus MikroTik RouterOS

## Cisco IOS-XE

Cisco IOS-XE distinguishes L2 ports from L3 ports at the interface
level via the `switchport` keyword.  An `interface GigabitEthernet
0/0/1` defaults to L3 on routers and L2 on Catalyst switches; the
`switchport` / `no switchport` keyword toggles modes.  L2 ports take
`switchport mode {access|trunk|dot1q-tunnel}` plus per-mode
parameters; L3 ports take an `ip address` declaration directly on
the interface.

The L2 plane is single — every L2 port belongs to the implicit
default bridge (the chassis switching fabric); there is no
operator-visible bridge object.

## MikroTik RouterOS

Source: [Bridging and Switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/47579231/Bridging+and+Switching)

Retrieved: 2026-04-30

RouterOS has historically been **router-first**: every interface
defaults to a routed L3 port, and switching is opt-in via an
explicit `/interface bridge` object with member ports.  A SOHO
RouterBoard typically has all ethernet ports bound into a single
`bridge1` to emulate Cisco-style switching; carrier deployments
with strict L3 boundaries omit the bridge entirely.

Three switching modes co-exist:

1. **Pure routing** — no bridge; each `etherN` is a separate
   broadcast domain.
2. **Software bridge** — `/interface bridge` + `/interface bridge
   port` for ports.  CPU-switched; no hardware offload.
3. **Bridge VLAN filtering** (`vlan-filtering=yes`) — emulates
   Cisco-style switchport semantics on CRS-series hardware via
   ASIC-offloaded VLAN tables.

The CRS3xx, CRS5xx, CCR2116, CCR2216 platforms do hardware-
accelerated bridge VLAN filtering; older CRS1xx/2xx use a
separate `/interface ethernet switch` plane that is being
deprecated in favour of bridge VLAN filtering.

## Cross-vendor mapping summary

| Cisco model | MikroTik model |
|---|---|
| L3 routed port (`no switchport` + `ip address`) | bare `etherN` + `/ip address add interface=etherN` |
| L2 access port (`switchport mode access`, `switchport access vlan N`) | `/interface bridge port` `pvid=N` + `frame-types=admit-only-untagged-and-priority-tagged` |
| L2 trunk port (`switchport mode trunk`, `switchport trunk allowed vlan ...`) | `/interface bridge port` `frame-types=admit-only-vlan-tagged` + `/interface bridge vlan` membership rows |
| Native VLAN on trunk (`switchport trunk native vlan N`) | bridge-port `pvid=N` while frame-types still `admit-all` |
| Voice VLAN (`switchport voice vlan N`) | no equivalent — LLDP-MED voice-VLAN advertisement is a separate plane |
| L3 SVI (`interface Vlan100` + `ip address ...`) | `/interface vlan name=vlan100 vlan-id=100 interface=bridge1` + `/ip address add interface=vlan100` |
| Routed sub-interface (`GigabitEthernet0/0/1.10` with `encapsulation dot1q 10`) | `/interface vlan name=vlan10 vlan-id=10 interface=ether1` |

Two structural differences shape the disposition table:

1. RouterOS's `/interface vlan` (Plane 1) is a routed sub-interface
   model — directly equivalent to Cisco's `interface
   GigabitEthernet0/0/1.10` form, NOT to switchport-on-a-VLAN.
   When a Cisco source uses sub-interfaces, RouterOS Plane 1 is the
   right target.
2. RouterOS's bridge VLAN filtering (Plane 2) is a switching
   model — directly equivalent to Cisco's switchport access/trunk
   form.  When a Cisco source is L2-switched, RouterOS Plane 2 is
   the right target — and the canonical model's VLAN-centric port
   lists land cleanly there.

The MikroTik codec's v1 wire-up handles Plane 1 cleanly; Plane 2
parsing of bridge-port `pvid=` and `frame-types=` is partial.
Cross-vendor render from Cisco-source canonical to RouterOS-target
emits a Plane 2 section when `tagged_ports[]` / `untagged_ports[]`
populated.
