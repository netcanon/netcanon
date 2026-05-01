# Switching philosophy: Aruba AOS-S versus MikroTik RouterOS

## Aruba AOS-S — campus L2/L3 switch

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba AOS-S is an **enterprise campus L2/L3 switch** with a
ProCurve heritage (originally HP's Cisco-CLI-compatible offering).
The platform assumes a switching-first deployment model: ports
default to L2, VLANs are first-class, switchport-mode semantics
(access / trunk) live on the wire.

Key model features:

- **VLAN-centric port membership** on the wire — `vlan 10 /
  untagged 1-24 / tagged 25-26` declares membership on the VLAN,
  not on the port.
- **Absorbed SVI L3** — `vlan 10 / ip address X/N` puts the SVI
  L3 inside the VLAN stanza (no separate `interface Vlan10` block).
- **Per-port `routing` toggle** — interfaces default to L2; an
  explicit `routing` keyword inside an interface stanza switches
  it to routed mode.
- **Spanning-tree on by default** (MSTP).  RSTP and PVST+ are
  available but operators rarely change the default.
- **DHCP-snooping, ARP-protection, BPDU-guard** etc. — campus
  security features that are first-class on the wire.

## MikroTik RouterOS — router-first OS with optional bridge

Source: [Bridging and Switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/47579231/Bridging+and+Switching)
Retrieved: 2026-04-30

RouterOS is a **router-first OS** (originally for x86 router boards;
later extended to switch silicon).  The native L3 model treats
every interface as a routed port; switching is layered on top via
the `/interface bridge` construct.

Key model features:

- **No native L2/L3 distinction on physical ports.**  Every
  `/interface ethernet` is a routed L3 port until explicitly
  bridged.
- **Bridge-VLAN filtering** is opt-in via `vlan-filtering=yes` on
  `/interface bridge`.  Without it, bridges are flat L2 (no VLAN
  awareness).
- **Two VLAN planes** — `/interface vlan` for routed sub-interfaces
  (router-on-a-stick) and bridge VLAN filtering for switching.
  See `vlans.md` for the plane mismatch detail.
- **Spanning-tree** on `/interface bridge` is `protocol-mode=rstp`
  by default; RouterOS has STP / RSTP / MSTP support but no PVST.
- **DHCP-snooping** is NOT first-class on RouterOS — operators
  emulate via firewall rules.  ARP-protection works through
  `arp=reply-only` on the bridge and per-host static ARP
  entries.

## Cross-vendor implications

The mismatch matters more than the syntax-level differences:

- Aruba ports default to L2 + L2 features (BPDU-guard, ARP-protect)
  on the wire; RouterOS ports default to routed L3 + no L2
  protections.  Cross-vendor render to RouterOS must explicitly
  add a bridge with `vlan-filtering=yes` and bind ports to the
  bridge — otherwise the migrated config has L3 routing where the
  source had L2 switching.
- Aruba's per-port `routing` keyword switches a port to L3.
  RouterOS-equivalent: omit the port from the bridge and bind an
  `/ip address` directly.  The aruba_aoss `routing` interfaces are
  modelled as L3 routed in the canonical schema (no special
  switchport_mode); RouterOS render emits the bare `/ip address
  add interface=etherX` form without bridging.

Tier-3 features (DHCP-snooping, ARP-protect, BPDU-guard) are
**unsupported** on the cross-pair: they have no canonical model and
land in `raw_sections` for operator review.

### Aruba feature -> RouterOS rough mapping

| Aruba | RouterOS | Notes |
|---|---|---|
| L2 access port | `/interface bridge port` (bridge member) | Aruba default; needs explicit bridge on RouterOS |
| L3 routed port (`routing` on interface) | `/ip address add interface=X` | Native on RouterOS |
| `vlan 10 / untagged 1-24` | `/interface bridge vlan` (Plane 2) | Plane-2 wire-up partial |
| `vlan 10 / ip address X/N` | `/interface vlan name=vlan10` + `/ip address` | SVI absorption -> two-section split |
| `spanning-tree` (MSTP default) | `/interface bridge protocol-mode=rstp` | RSTP/MSTP overlap; PVST NA |
| `dhcp-snooping` | (no equivalent; firewall rules) | Tier-3, raw_sections |
| `loop-protect` | `/interface bridge port frame-types=...` | Partial overlap |

### Disposition

The switching-philosophy mismatch shows up as **lossy** dispositions
on the per-field VLAN / interface entries (see `vlans.md` and
`interface_naming.md` for the per-field breakdown), not as a
top-level field of its own — the canonical model abstracts the
philosophy difference behind VLAN-centric membership.
