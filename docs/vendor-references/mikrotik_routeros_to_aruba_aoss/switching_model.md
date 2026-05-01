# Switching philosophy: MikroTik RouterOS versus Aruba AOS-S

## MikroTik RouterOS — router-first OS with optional bridge

Source: [Bridging and Switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/47579231/Bridging+and+Switching)
Retrieved: 2026-04-30

RouterOS is a **router-first OS** (originally for x86 router boards;
later extended to switch silicon).  The native L3 model treats
every interface as a routed port; switching is layered on top via
the `/interface bridge` construct.

Key model features:
- **No native L2/L3 distinction on physical ports.**  Every
  `/interface ethernet` is a routed L3 port until explicitly bridged.
- **Bridge-VLAN filtering** is opt-in via `vlan-filtering=yes` on
  `/interface bridge`.  Without it, bridges are flat L2 (no VLAN
  awareness).
- **Two VLAN planes** — `/interface vlan` (router-on-a-stick) for
  routed sub-interfaces and bridge VLAN filtering for switching.
- **Spanning-tree** on `/interface bridge` is `protocol-mode=rstp`
  by default.  STP / RSTP / MSTP supported; no PVST.
- **Tier-3 plumbing** (firewall rules, NAT, mangle, queues,
  wireless, scripts, IPsec, scheduler, PPP, hotspot) is rich and
  has no canonical model — drops to `raw_sections`.

## Aruba AOS-S — campus L2/L3 switch

Source: [Aruba ArubaOS-Switch 16.10 Advanced Traffic Management Guide](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ATMG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Aruba AOS-S is an **enterprise campus L2/L3 switch** with a
ProCurve heritage.  Switching-first deployment: ports default to
L2; VLANs are first-class; switchport-mode (access/trunk) lives
on the VLAN-centric port lists.

Key model features:
- **VLAN-centric port membership** — `vlan 10 / untagged 1-24`
  declares membership on the VLAN.
- **Absorbed SVI L3** — `vlan 10 / ip address X/N` puts the L3
  inside the VLAN stanza.
- **Per-port `routing` toggle** for L3 routed mode.
- **MSTP** spanning-tree on by default; RSTP / PVST+ available.
- **Campus security features** (DHCP-snooping, ARP-protection,
  BPDU-guard, loop-protection) first-class on the wire.

## Cross-vendor implications

The switching philosophy mismatch is the dominant source of cross-
vendor drift on this pair:

- RouterOS Tier-3 plumbing (firewall / NAT / mangle / queues /
  wireless / scripts / IPsec / scheduler) is RICH and has no
  canonical analogue.  Cross-vendor render to Aruba drops these
  with a banner — they remain in `raw_sections` for operator
  review.  This is the dominant lossy path on this direction —
  the RouterOS source carries far more semantic richness than the
  canonical model captures.
- RouterOS bare ethernet ports (no bridge membership) lift to
  Aruba target as **routed** interfaces (`routing` keyword).
  Operators who want L2 switching must explicitly construct a
  RouterOS bridge before migration so the canonical port-list
  populates.
- L2 features that Aruba carries but RouterOS does not (DHCP-
  snooping, ARP-protect, BPDU-guard) are STRUCTURALLY absent on
  the RouterOS source — Aruba target render emits no equivalent.
  This is **not_applicable** rather than lossy in this direction
  (the source had nothing to lose).
- Spanning-tree mode mapping: RouterOS RSTP -> Aruba RSTP works;
  RouterOS MSTP -> Aruba MSTP works; RouterOS source with no
  bridge means no STP at all on the RouterOS side, so Aruba
  target falls back to its MSTP default.

### RouterOS feature -> Aruba rough mapping

| RouterOS | Aruba | Notes |
|---|---|---|
| `/interface bridge port` (L2 bridge) | VLAN-centric `untagged` / `tagged` lists | Plane-2 wire-up partial |
| `/interface ethernet` bare (L3) | `interface X / routing / ip address ...` | Direct on canonical |
| `/interface vlan` + `/ip address` | `vlan <id> / ip address X/N` | SVI absorption -> single stanza |
| `/interface bridge protocol-mode=rstp` | `spanning-tree mode rstp` | Direct overlap |
| `/ip firewall filter` | (no equivalent; raw_sections) | Tier-3 |
| `/queue` | (no equivalent; raw_sections) | Tier-3 |
| `/interface wireless` | (no equivalent on AOS-S; AP plane) | Tier-3 |
| `/ip ipsec` | (no equivalent on AOS-S) | Tier-3 |

### Disposition

The switching-philosophy mismatch shows up as **lossy** on per-
field VLAN / interface entries (see `vlans.md` and
`interface_naming.md`) and as **not_applicable** on
`raw_sections` (Tier-3 by design — never auto-rendered).
