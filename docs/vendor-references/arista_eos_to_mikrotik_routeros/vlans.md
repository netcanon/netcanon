# VLAN configuration: Arista EOS versus MikroTik RouterOS

## Arista EOS

Source: [Arista EOS — Virtual LANs (VLANs)](https://www.arista.com/en/um-eos/eos-virtual-lans-vlans)
Retrieved: 2026-05-01

Arista EOS is **interface-centric** (Cisco-style), with first-
class SVI L3 entities:

```
vlan 10
   name USERS
!
vlan 20
   name VOICE
!
vlan 100
   name TENANT_A_DATA
!
interface Vlan100
   description "Tenant A data SVI"
   vrf TENANT_A
   ip address 10.100.0.1/24
   ipv6 address 2001:db8:100:100::1/64
!
interface Ethernet2
   switchport mode access
   switchport access vlan 10
!
interface Ethernet3
   switchport mode trunk
   switchport trunk native vlan 1
   switchport trunk allowed vlan 10,20,100,200
```

The `vlan N / name X` stanza never lists ports; membership is
per-port via `switchport access vlan` / `switchport trunk allowed
vlan`.  SVI L3 lives on a separate `interface Vlan<N>` block —
which can carry a `vrf <name>` line for L3 isolation.

Arista's canonical projection (`project_switchport_to_vlan`
transform) re-folds the per-port surface into VLAN-centric
`tagged_ports` / `untagged_ports` lists for cross-vendor render.

## MikroTik RouterOS

Sources:
- [VLAN — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN)
- [Basic VLAN switching (bridge VLAN filtering) — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching)
- [Bridging and Switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/47579231/Bridging+and+Switching)

Retrieved: 2026-05-01

RouterOS uses a **two-plane model**:

* **Plane 1 (router-on-a-stick):** `/interface vlan` creates a
  routed VLAN sub-interface on a parent (bridge or physical port).
  L3 lives on `/ip address`.
* **Plane 2 (bridge VLAN filtering):** for switching tagged
  traffic between physical ports through a bridge.  Configured
  via `vlan-filtering=yes` on `/interface bridge` plus per-port
  `pvid=` and `/interface bridge vlan` rows declaring tagged /
  untagged membership.

```
/interface bridge
add name=bridge1 vlan-filtering=yes

/interface bridge port
add bridge=bridge1 interface=ether2 pvid=10
add bridge=bridge1 interface=ether3

/interface bridge vlan
add bridge=bridge1 vlan-ids=10 untagged=ether2 tagged=ether3
add bridge=bridge1 vlan-ids=20,100,200 tagged=ether3

/interface vlan
add name=vlan100 interface=bridge1 vlan-id=100

/ip address
add address=10.100.0.1/24 interface=vlan100
```

The L3 SVI emerges as a **separate** `/interface vlan` row plus
its own `/ip address` row.  The VLAN's symbolic name conflates
with the L3 interface name (`vlan100`) — there is no separate
descriptive name field on the wire.

The `mikrotik_routeros` codec capability matrix lists
`/vlans/vlan/id` and `/vlans/vlan/name` under **supported**.
`/vlans/vlan/name` is also listed under **lossy** with the
rationale that RouterOS stores the VLAN's name as the L3
interface name, NOT a separate descriptive name field.

## Cross-vendor mapping

The canonical model is VLAN-centric (design principle 1).

Arista -> RouterOS round-trip:

* Arista parse: `interface Ethernet2 / switchport access vlan 10`
  populates a per-port record.  The
  `project_switchport_to_vlan` transform re-projects to canonical
  VLAN-centric `tagged_ports` / `untagged_ports`.
* Arista parse: `interface Vlan100 / ip address X/N` populates
  `CanonicalVlan.ipv4_addresses` directly via the SVI-absorption
  helper.
* Arista parse: `vlan 100 / name TENANT_A_DATA` populates
  `CanonicalVlan.name="TENANT_A_DATA"`.
* RouterOS render: emits Plane 1 (`/interface vlan add
  name=vlan100 interface=bridge1 vlan-id=100`) plus its `/ip
  address` row for the SVI.  The operator-typed name lifts
  partially — RouterOS's wire form uses `name=vlan<id>` by
  convention, conflating the L3 interface name with the VLAN's
  symbolic name.  If the canonical name is non-empty and
  hostname-safe, the codec may emit `name=<canonical>` instead.
* RouterOS render: emits Plane 2 (bridge VLAN filtering) rows
  to back the per-port membership.  Plane-2 wire-up is partial
  in v1 — the rendered config may not fully populate every
  bridge-VLAN row that an equivalent hand-written RouterOS
  config would have.

VRF on the SVI is the asymmetric loss — Arista's `interface
Vlan100 / vrf TENANT_A` carries data RouterOS does not model
(see `vxlan_evpn_unsupported.md`).  The `vrf` field on the
canonical interface silently drops on RouterOS render.

The Arista synthetic kitchen-sink (`ks-leaf-01`) carries:

```
vlan 10 / name USERS
vlan 20 / name VOICE
vlan 100 / name TENANT_A_DATA
vlan 200 / name TRANSIT
interface Vlan100 / vrf TENANT_A / ip address 10.100.0.1/24
interface Vlan200 / ip address 10.200.0.1/24
```

— the bare VLAN definitions and SVI absorption land cleanly on
RouterOS via `/interface vlan` + `/ip address`; the `vrf
TENANT_A` line drops with a banner.

Round-trip lossless for VLAN id and SVI v4 address (when SVI is
in the default VRF).  Lossy for VLAN name (conflated with L3
interface name) and description.

Disposition: **lossy** — see the YAML for the per-field break-
down.
