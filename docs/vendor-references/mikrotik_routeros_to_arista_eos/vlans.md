# VLAN configuration: MikroTik RouterOS versus Arista EOS

## MikroTik RouterOS

Sources:
- [VLAN — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/88014957/VLAN)
- [Basic VLAN switching (bridge VLAN filtering) — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/103841826/Basic+VLAN+switching)
- [Bridging and Switching — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/47579231/Bridging+and+Switching)

Retrieved: 2026-05-01

RouterOS uses a **two-plane model** for VLAN handling:

* **Plane 1 (router-on-a-stick / sub-interface):** `/interface
  vlan` creates a routed VLAN sub-interface on a parent (bridge
  or physical port).  L3 lives on `/ip address`.
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
add comment="Users VLAN" interface=bridge1 name=vlan100 vlan-id=100
add comment="Voice VLAN" interface=bridge1 name=vlan200 vlan-id=200

/ip address
add address=10.100.0.1/24 interface=vlan100
add address=10.200.0.1/24 interface=vlan200
```

The L3 SVI emerges as a separate `/interface vlan` row plus its
own `/ip address` row.  The VLAN's symbolic name conflates with
the L3 interface name (`vlan100`) — there is no separate
descriptive name field on the wire.

The `mikrotik_routeros` codec capability matrix lists
`/vlans/vlan/id` and `/vlans/vlan/name` under **supported**.
`/vlans/vlan/name` is also listed under **lossy** with the
rationale that RouterOS stores the VLAN's name as the L3
interface name.

**Plane 2 wire-up is partial** in v1: the codec parses
`/interface vlan` rows and populates `vlans[].id` + `vlans[].
name`, but the per-port membership (`tagged_ports` /
`untagged_ports`) lifted from `/interface bridge port` and
`/interface bridge vlan` is incomplete — only basic patterns are
recognised.

## Arista EOS

Source: [Arista EOS — Virtual LANs (VLANs)](https://www.arista.com/en/um-eos/eos-virtual-lans-vlans)
Retrieved: 2026-05-01

Arista EOS is **interface-centric** (Cisco-style):

```
vlan 100
   name USERS
!
vlan 200
   name VOICE
!
interface Vlan100
   description "Users VLAN"
   ip address 10.100.0.1/24
!
interface Vlan200
   description "Voice VLAN"
   ip address 10.200.0.1/24
!
interface Ethernet2
   switchport mode access
   switchport access vlan 10
!
interface Ethernet3
   switchport mode trunk
   switchport trunk allowed vlan 10,20,100,200
!
```

The `vlan N / name X` stanza never lists ports; membership is
per-port via `switchport access vlan` / `switchport trunk
allowed vlan`.  SVI L3 lives on a separate `interface Vlan<N>`
block.

## Cross-vendor mapping

The canonical model is VLAN-centric (design principle 1).

RouterOS -> Arista round-trip:

* RouterOS `/interface vlan add name=vlan100 vlan-id=100
  comment="Users VLAN"` populates `CanonicalVlan(id=100,
  name="vlan100", description="Users VLAN")`.  The conflated
  `name=vlan100` is the wire identity; Arista render emits
  `vlan 100 / name VLAN_100` (or `name <canonical-name>` if the
  parsed name is non-vacuous).
* RouterOS bridge VLAN filtering rows lift to canonical
  `tagged_ports` / `untagged_ports` lists where Plane-2 parsing
  succeeds.  Arista render transposes back to per-port
  `switchport access vlan` / `switchport trunk allowed vlan`.
* RouterOS `/ip address add address=10.100.0.1/24
  interface=vlan100` -> Arista `interface Vlan100 / ip address
  10.100.0.1/24`.  SVI absorption handles both directions.

Lossy bits:

* **VLAN name conflation:** RouterOS stores the VLAN's name as
  the L3 interface name (`vlan100`), not as a separate
  descriptive field.  Arista render emits `name VLAN_<N>` when
  the source name is the literal `vlan<id>` form, or the
  RouterOS comment value if it lifts cleanly.

* **Plane-2 partial wire-up:** RouterOS bridge VLAN filtering
  parsing is incomplete in v1 — bridge-port pvid= and /interface
  bridge vlan rows partially populate canonical port lists.
  Arista render's per-port switchport emission may under-
  populate the access/trunk membership, requiring operator
  review.

* **Description:** RouterOS source has no separate VLAN
  description field; the `comment=` value lifts to canonical
  `description` if present.  Arista render emits a comment
  rather than a first-class description on the `vlan <N>`
  stanza.

The MikroTik synthetic kitchen-sink (`ks-edge-01`) carries:

```
/interface vlan add comment="Users VLAN" name=vlan100 vlan-id=100
/interface vlan add comment="Voice VLAN" name=vlan200 vlan-id=200
/interface vlan add comment="Management VLAN" name=vlan300 vlan-id=300
/ip address add address=10.100.0.1/24 interface=vlan100
/ip address add address=10.200.0.1/24 interface=vlan200
```

— the VLAN definitions and SVI absorption land cleanly on Arista
via `vlan N / name vlan<N>` + `interface Vlan<N> / ip address`.

Round-trip lossless for VLAN id and SVI v4 address.  Lossy for
VLAN name (conflated) and per-port membership (Plane-2 partial).

Disposition: **lossy** — see the YAML for the per-field
breakdown.
